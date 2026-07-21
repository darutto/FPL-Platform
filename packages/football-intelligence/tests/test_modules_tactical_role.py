from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pandas as pd
import pytest

from football_data_contract.enums import EvidenceDirection, Flank, FormationDepth, SignalBasis
from football_intelligence.features.registry_v2 import FEATURE_REGISTRY_VERSION, ROLE_MAPPING_VERSION
from football_intelligence.features.store_v2 import FeatureV2ValidationError, build_features_v2
from football_intelligence.modules import ModuleStatus, UnsupportedFeatureContractError
from football_intelligence.modules.tactical_role import (
    FRESH_168H,
    FRESH_24H,
    FRESH_72H,
    MAX_ROLE_DISTANCE,
    MODEL_VERSION,
    NOMINAL_POSITION_INPUT_VERSION,
    OUT_OF_POSITION_MAPPING_VERSION,
    ROLE_VOCABULARY,
    FlankShare,
    RoleDistributionRow,
    RoleShare,
    RoleWindowSummary,
    TacticalRoleInput,
    evaluate_tactical_role,
    load_tactical_role_input,
)

from test_features_v2 import sources


CALCULATED_AT = "2026-08-08T00:00:00Z"
BUILT_AT = "2026-08-01T00:00:00Z"


def _modal(counts):
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if counts else None


def _rows(segment, counts, eligible, basis=SignalBasis.OBSERVED):
    result = []
    for (role, flank, depth), count in counts.items():
        result.append(RoleDistributionRow(
            segment, role, flank, depth, count, count / eligible,
            ROLE_MAPPING_VERSION, basis,
        ))
    return result


def _summary(segment, counts, eligible, comparable=True, basis=SignalBasis.OBSERVED):
    mapped = sum(counts.values())
    role_counts = {}
    for (role, _, _), count in counts.items():
        role_counts[role] = role_counts.get(role, 0) + count
    return RoleWindowSummary(
        segment, eligible, mapped, eligible - mapped, _modal(role_counts),
        comparable, ROLE_MAPPING_VERSION, basis,
    )


def make_input(
    *,
    last=None,
    recent=None,
    prior=None,
    eligible=(6, 2, 4),
    nominal="MID",
    bases=(SignalBasis.OBSERVED, SignalBasis.OBSERVED, SignalBasis.OBSERVED),
    built_at=BUILT_AT,
    calculated_at=CALCULATED_AT,
):
    if last is None:
        last = {("central_midfield", "center", "midfield"): 5, ("winger", "left", "attack"): 1}
    if recent is None:
        recent = {("central_midfield", "center", "midfield"): eligible[1]} if eligible[1] else {}
    if prior is None:
        prior = {("central_midfield", "center", "midfield"): eligible[2]} if eligible[2] else {}
    values = (last, recent, prior)
    comparable = bool(eligible[1] and eligible[2])
    summaries = tuple(_summary(segment, counts, size, comparable, basis) for segment, counts, size, basis in zip(
        ("last_10", "last_3", "prior_7"), values, eligible, bases))
    distribution = tuple(row for segment, counts, size, basis in zip(
        ("last_10", "last_3", "prior_7"), values, eligible, bases) for row in _rows(segment, counts, size, basis))
    return TacticalRoleInput(
        fixture_id="target", team_id="team_a", player_id="player_1",
        calculated_at=calculated_at, feature_registry_version=FEATURE_REGISTRY_VERSION,
        feature_build_id="fi6b", feature_built_at=built_at,
        nominal_position=nominal, summaries=summaries, distribution=distribution,
    )


def replace(item, **updates):
    return type(item)(**{**item.__dict__, **updates})


def test_golden_stable_role_output_versions_and_neutral_evidence():
    result = evaluate_tactical_role(make_input(calculated_at="2026-08-01T12:00:00Z"))
    assert result.status is ModuleStatus.OK
    assert result.model_version == MODEL_VERSION == "tactical-role-v1"
    assert result.role_mapping_version == ROLE_MAPPING_VERSION == "role-map-v2"
    assert result.nominal_position_input_version == NOMINAL_POSITION_INPUT_VERSION == "fpl-nominal-position-v1"
    assert OUT_OF_POSITION_MAPPING_VERSION == "nominal-role-distance-v1"
    assert result.primary_role == "central_midfield"
    assert result.role_stability == pytest.approx(5 / 6)
    assert result.primary_flank is Flank.CENTRAL
    assert result.formation_depth is FormationDepth.MID
    assert tuple(value.code for value in result.evidence) == ("ROLE_STABLE",)
    assert all(value.direction is EvidenceDirection.NEUTRAL and value.impact == 0.0 for value in result.evidence)


def test_golden_changed_role_and_maximum_distance_oop_are_ordered():
    recent = {("forward", "center", "attack"): 2}
    prior = {("center_back", "center", "defense"): 4}
    last = {**recent, **prior}
    result = evaluate_tactical_role(make_input(last=last, recent=recent, prior=prior, nominal="FWD"))
    assert result.role_change_detected is True
    assert result.primary_role == "center_back"
    assert result.out_of_position_score == 1.0
    assert tuple(value.code for value in result.evidence) == ("OUT_OF_POSITION", "ROLE_CHANGED")
    assert all(value.direction is EvidenceDirection.NEUTRAL and value.impact == 0.0 for value in result.evidence)


@pytest.mark.parametrize("mapped,expected_status", [(2, ModuleStatus.MISSING_CONTEXT), (3, ModuleStatus.OK)])
def test_mapped_start_minimum_boundary(mapped, expected_status):
    counts = {("central_midfield", "center", "midfield"): mapped}
    result = evaluate_tactical_role(make_input(last=counts, eligible=(mapped, min(2, mapped), max(0, mapped - 2))))
    assert result.status is expected_status
    if mapped == 3:
        assert "sparse_role_history" in result.reason_codes and result.confidence < 1.0
    else:
        assert result.reason_codes == ("insufficient_role_history",)


@pytest.mark.parametrize("mapped,emits", [(4, False), (5, True)])
def test_role_stable_five_start_boundary(mapped, emits):
    counts = {("central_midfield", "center", "midfield"): mapped}
    result = evaluate_tactical_role(make_input(last=counts, eligible=(mapped, 2, mapped - 2)))
    assert ("ROLE_STABLE" in {item.code for item in result.evidence}) is emits


@pytest.mark.parametrize("primary,secondary,emits", [(6, 2, True), (5, 3, False)])
def test_role_stability_exact_point_seven_five_boundary(primary, secondary, emits):
    counts = {
        ("central_midfield", "center", "midfield"): primary,
        ("winger", "left", "attack"): secondary,
    }
    result = evaluate_tactical_role(make_input(last=counts, eligible=(8, 2, 6)))
    assert ("ROLE_STABLE" in {item.code for item in result.evidence}) is emits


def test_partial_mapping_keeps_governed_and_public_denominators_distinct():
    last = {("central_midfield", "center", "midfield"): 3, ("winger", "left", "attack"): 1}
    recent = {("central_midfield", "center", "midfield"): 1}
    prior = {("central_midfield", "center", "midfield"): 2, ("winger", "left", "attack"): 1}
    item = make_input(last=last, recent=recent, prior=prior, eligible=(6, 2, 4))
    governed = sum(row.role_share for row in item.distribution if row.window_segment == "last_10")
    result = evaluate_tactical_role(item)
    assert governed == pytest.approx(4 / 6) and governed < 1.0
    assert sum(row.share for row in result.role_distribution) == pytest.approx(1.0, abs=1e-9)
    assert result.confidence < evaluate_tactical_role(make_input()).confidence
    assert "partial_role_mapping" in result.reason_codes
    assert result.role_stability == pytest.approx(3 / 4)


def test_governed_modal_role_is_authoritative_and_lexically_validated():
    tied = {("forward", "center", "attack"): 2, ("center_back", "center", "defense"): 2}
    item = make_input(last=tied, eligible=(4, 2, 2))
    assert evaluate_tactical_role(item).primary_role == "center_back"
    summaries = list(item.summaries)
    summaries[0] = RoleWindowSummary(**{**summaries[0].__dict__, "modal_role": "forward"})
    with pytest.raises(FeatureV2ValidationError, match="modal role"):
        evaluate_tactical_role(replace(item, summaries=tuple(summaries)))


def test_flank_tie_chooses_left_and_center_bridges_to_central():
    tied = {("winger", "left", "attack"): 2, ("winger", "right", "attack"): 2}
    result = evaluate_tactical_role(make_input(last=tied, eligible=(4, 2, 2)))
    assert result.primary_flank is Flank.LEFT
    assert tuple(row.flank for row in result.flank_distribution) == (Flank.LEFT, Flank.RIGHT)
    central = evaluate_tactical_role(make_input())
    assert central.primary_flank is Flank.CENTRAL


@pytest.mark.parametrize("store_depth,expected", [
    ("goalkeeper", FormationDepth.DEEP), ("defense", FormationDepth.DEEP),
    ("midfield", FormationDepth.MID), ("attack", FormationDepth.ADVANCED),
])
def test_formation_depth_bridge_all_store_values(store_depth, expected):
    role = {"goalkeeper": "goalkeeper", "defense": "center_back", "midfield": "central_midfield", "attack": "forward"}[store_depth]
    counts = {(role, "center", store_depth): 4}
    assert evaluate_tactical_role(make_input(last=counts, eligible=(4, 2, 2))).formation_depth is expected


@pytest.mark.parametrize("recent_count,prior_count,expected", [
    (1, 2, None), (2, 1, None), (2, 2, False),
])
def test_role_change_one_versus_two_boundaries(recent_count, prior_count, expected):
    recent = {("central_midfield", "center", "midfield"): recent_count}
    prior = {("central_midfield", "center", "midfield"): prior_count}
    last = {("central_midfield", "center", "midfield"): recent_count + prior_count}
    result = evaluate_tactical_role(make_input(last=last, recent=recent, prior=prior,
        eligible=(recent_count + prior_count, recent_count, prior_count)))
    assert result.role_change_detected is expected
    assert ("role_change_not_comparable" in result.reason_codes) is (expected is None)


def test_missing_nominal_preserves_role_and_only_removes_oop():
    result = evaluate_tactical_role(make_input(nominal=None))
    assert result.status is ModuleStatus.OK and result.primary_role == "central_midfield"
    assert result.out_of_position_score is None and "nominal_position_missing" in result.reason_codes
    assert "OUT_OF_POSITION" not in {item.code for item in result.evidence}


ROLE_CLASS = {
    "goalkeeper": "GK", "center_back": "DEF", "full_back": "DEF", "wing_back": "DEF",
    "central_midfield": "MID", "wide_midfield": "MID", "winger": "MID", "forward": "FWD",
}
AXIS = {"DEF": 1, "MID": 2, "FWD": 3}


@pytest.mark.parametrize("nominal", ["GK", "DEF", "MID", "FWD"])
@pytest.mark.parametrize("role", sorted(ROLE_VOCABULARY))
def test_complete_four_by_eight_oop_table(nominal, role):
    role_class = ROLE_CLASS[role]
    expected_distance = 0 if nominal == role_class else (
        MAX_ROLE_DISTANCE if "GK" in (nominal, role_class) else min(MAX_ROLE_DISTANCE, abs(AXIS[nominal] - AXIS[role_class])))
    depth = "goalkeeper" if role == "goalkeeper" else "defense" if role_class == "DEF" else "midfield" if role_class == "MID" else "attack"
    flank = "left" if role in {"wing_back", "wide_midfield", "winger"} else "center"
    counts = {(role, flank, depth): 4}
    result = evaluate_tactical_role(make_input(last=counts, nominal=nominal, eligible=(4, 2, 2)))
    assert result.out_of_position_score == expected_distance / MAX_ROLE_DISTANCE
    assert ("OUT_OF_POSITION" in {item.code for item in result.evidence}) is (expected_distance == MAX_ROLE_DISTANCE)


def test_observed_proxy_and_mixed_basis_or_reduction_and_penalty():
    observed = evaluate_tactical_role(make_input())
    proxy = evaluate_tactical_role(make_input(bases=(SignalBasis.INFERRED_PROXY,) * 3))
    mixed = evaluate_tactical_role(make_input(bases=(SignalBasis.OBSERVED, SignalBasis.INFERRED_PROXY, SignalBasis.OBSERVED)))
    assert observed.role_basis is SignalBasis.OBSERVED
    assert proxy.role_basis is mixed.role_basis is SignalBasis.INFERRED_PROXY
    assert proxy.confidence < observed.confidence and "proxy_role_basis" in proxy.reason_codes
    assert all(item.basis is SignalBasis.INFERRED_PROXY for item in mixed.evidence)


@pytest.mark.parametrize("hours,quality", [
    (FRESH_24H, 1.0), (FRESH_24H + 0.01, 0.8), (FRESH_72H, 0.8),
    (FRESH_72H + 0.01, 0.5), (FRESH_168H, 0.5), (FRESH_168H + 0.01, 0.25),
])
def test_freshness_half_open_boundaries(hours, quality):
    calculated = pd.Timestamp(BUILT_AT) + pd.Timedelta(hours=hours)
    result = evaluate_tactical_role(make_input(calculated_at=calculated.isoformat().replace("+00:00", "Z")))
    expected = 0.4 * 0.6 + 0.25 + 0.15 * quality + 0.1 + 0.1
    assert result.confidence == pytest.approx(expected)


def test_negative_build_age_is_typed_validation_failure():
    with pytest.raises(FeatureV2ValidationError, match="later"):
        evaluate_tactical_role(make_input(built_at="2026-08-09T00:00:00Z"))


def test_reason_evidence_order_reversal_replay_and_frozen_contracts():
    item = make_input(last={("forward", "center", "attack"): 3},
        recent={("forward", "center", "attack"): 1}, prior={("forward", "center", "attack"): 2},
        eligible=(5, 1, 4), nominal=None,
        bases=(SignalBasis.INFERRED_PROXY,) * 3, calculated_at="2026-08-10T01:00:00Z")
    first = evaluate_tactical_role(item)
    reversed_item = replace(item, summaries=tuple(reversed(item.summaries)), distribution=tuple(reversed(item.distribution)))
    assert first == evaluate_tactical_role(item) == evaluate_tactical_role(reversed_item)
    assert first.reason_codes == (
        "sparse_role_history", "partial_role_mapping", "stale_feature_build",
        "proxy_role_basis", "nominal_position_missing", "role_change_not_comparable",
    )
    assert tuple(value.code for value in first.evidence) == tuple(sorted(value.code for value in first.evidence))
    with pytest.raises(FrozenInstanceError):
        first.confidence = 0.0
    with pytest.raises(FrozenInstanceError):
        first.role_distribution[0].share = 0.0
    assert isinstance(first.role_distribution, tuple) and isinstance(first.flank_distribution, tuple)


def test_unknown_vocab_nonfinite_counts_shares_and_metadata_fail_closed():
    item = make_input()
    bad_row = RoleDistributionRow("last_10", "unknown", "center", "midfield", 1, 0.1,
        ROLE_MAPPING_VERSION, SignalBasis.OBSERVED)
    with pytest.raises(FeatureV2ValidationError, match="vocabulary"):
        evaluate_tactical_role(replace(item, distribution=(bad_row,) + item.distribution[1:]))
    bad_share = RoleDistributionRow(**{**item.distribution[0].__dict__, "role_share": float("nan")})
    with pytest.raises(FeatureV2ValidationError, match="finite"):
        evaluate_tactical_role(replace(item, distribution=(bad_share,) + item.distribution[1:]))
    bad_count = RoleDistributionRow(**{**item.distribution[0].__dict__, "role_count": -1})
    with pytest.raises(FeatureV2ValidationError, match="positive"):
        evaluate_tactical_role(replace(item, distribution=(bad_count,) + item.distribution[1:]))


def test_duplicate_missing_segments_unknown_nominal_and_version_fail_closed():
    item = make_input()
    with pytest.raises(FeatureV2ValidationError, match="duplicate"):
        evaluate_tactical_role(replace(item, summaries=item.summaries + (item.summaries[0],)))
    with pytest.raises(FeatureV2ValidationError, match="missing required"):
        evaluate_tactical_role(replace(item, summaries=item.summaries[:-1]))
    with pytest.raises(FeatureV2ValidationError, match="nominal"):
        replace(item, nominal_position="ATT")
    with pytest.raises(UnsupportedFeatureContractError, match="input version"):
        replace(item, nominal_position_input_version="unversioned")


def _build(tmp_path):
    base, context = sources(tmp_path / "source")
    root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="fi6b", built_at="2026-08-01T00:00:00Z")
    return root / "builds-v2/fi6b", base, context


def test_loader_happy_absence_v1_unversioned_and_corruption(tmp_path):
    build, base, context = _build(tmp_path)
    loaded = load_tactical_role_input(build, base, context, fixture_id="target", team_id="team_a",
        player_id="player_1", nominal_position="MID", calculated_at=CALCULATED_AT)
    assert evaluate_tactical_role(loaded).status is ModuleStatus.OK
    missing = load_tactical_role_input(tmp_path / "absent", None, None, fixture_id="target", team_id="team_a",
        player_id="player_1", nominal_position="MID", calculated_at=CALCULATED_AT)
    assert evaluate_tactical_role(missing).status is ModuleStatus.MISSING_CONTEXT
    absent_row = load_tactical_role_input(build, base, context, fixture_id="target", team_id="team_a",
        player_id="missing", nominal_position="MID", calculated_at=CALCULATED_AT)
    assert evaluate_tactical_role(absent_row).status is ModuleStatus.MISSING_CONTEXT

    v1 = tmp_path / "v1"; v1.mkdir(); (v1 / "manifest.json").write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(UnsupportedFeatureContractError):
        load_tactical_role_input(v1, base, context, fixture_id="target", team_id="team_a",
            player_id="player_1", nominal_position="MID", calculated_at=CALCULATED_AT)
    root = tmp_path / "root"; root.mkdir(); (root / "_features_v2_latest.json").write_text("{}")
    with pytest.raises(UnsupportedFeatureContractError, match="unversioned"):
        load_tactical_role_input(root, base, context, fixture_id="target", team_id="team_a",
            player_id="player_1", nominal_position="MID", calculated_at=CALCULATED_AT)

    dataset = build / "datasets/player_role_distribution.parquet"
    frame = pd.read_parquet(dataset); frame.loc[0, "role_count"] = 99; frame.to_parquet(dataset, index=False)
    with pytest.raises(FeatureV2ValidationError, match="hash"):
        load_tactical_role_input(build, base, context, fixture_id="target", team_id="team_a",
            player_id="player_1", nominal_position="MID", calculated_at=CALCULATED_AT)


def test_source_has_no_prohibited_dependencies_language_or_wall_clock():
    source = Path(__file__).parents[1] / "football_intelligence/modules/tactical_role.py"
    text = source.read_text(encoding="utf-8").casefold()
    prohibited_imports = (
        "sportmonks", "provider_client", "requests", "httpx", "urllib", "zonal",
        "tool_registry", "finalresponse", "orchestrat", "renderer", "fpl_ui",
    )
    assert not any(token in text for token in prohibited_imports)
    assert "datetime.now" not in text and "datetime.utcnow" not in text and "time.time" not in text
    prohibited_phrases = (
        "average position", "buy ", "sell ", "transfer ", "captain ", "captaincy",
        " bench ", " pick ", " avoid ", "recommendation",
    )
    summaries = " ".join(item.summary for item in evaluate_tactical_role(make_input(nominal="GK")).evidence).casefold()
    assert not any(token in summaries for token in prohibited_phrases)
