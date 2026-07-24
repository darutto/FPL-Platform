from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from football_data_contract.enums import EvidenceDirection, SignalBasis, SubjectType
from football_intelligence.features.registry_v2 import (
    COMPETITION_WEIGHT_VERSION,
    FEATURE_REGISTRY_VERSION,
)
from football_intelligence.features.store_v2 import (
    FeatureV2ValidationError,
    build_features_v2,
)
from football_intelligence.modules import ModuleStatus, UnsupportedFeatureContractError
from football_intelligence.modules.fixture_context import (
    COMPETITION_STAGES,
    CONGESTION_EVIDENCE_THRESHOLD,
    FIXTURE_PRIORITY_VERSION,
    FRESH_168H,
    FRESH_24H,
    FRESH_72H,
    LEAGUE_BANDS,
    MODEL_VERSION,
    PRIORITY_TABLE,
    REASON_ORDER,
    FixtureContextInput,
    FixturePriority,
    evaluate_fixture_context,
    load_fixture_context_input,
)

from test_features_v2 import sources


CALCULATED_AT = "2026-08-02T00:00:00Z"
BUILT_AT = "2026-08-01T00:00:00Z"


def make_input(**updates):
    values = {
        "fixture_id": "target",
        "team_id": "team_a",
        "calculated_at": CALCULATED_AT,
        "feature_registry_version": FEATURE_REGISTRY_VERSION,
        "feature_build_id": "fi6c",
        "feature_built_at": BUILT_AT,
        "weighted_trailing_congestion_21d": 4.0,
        "weighted_leading_congestion_21d": 3.0,
        "trailing_fixtures_considered": 4,
        "leading_fixtures_considered": 3,
        "previous_rest_days": 7.0,
        "next_rest_days": 7.0,
        "target_competition_tier": "league",
        "target_competition_stage": "league",
        "league_position_band": "top",
        "schedule_context_as_of_utc": "2026-07-31T00:00:00Z",
        "standing_context_as_of_utc": "2026-07-30T00:00:00Z",
        "competition_weight_version": COMPETITION_WEIGHT_VERSION,
    }
    values.update(updates)
    return FixtureContextInput(**values)


def test_golden_complete_context_is_exact_frozen_and_emits_neutral_team_evidence():
    result = evaluate_fixture_context(make_input())
    assert result.status is ModuleStatus.OK
    assert result.model_version == MODEL_VERSION == "fixture-context-v1"
    assert result.fixture_priority_version == FIXTURE_PRIORITY_VERSION == "fixture-priority-v1"
    assert result.fixture_priority is FixturePriority.CRITICAL
    assert result.congestion_index == 7.0
    assert result.weighted_trailing_congestion_21d == 4.0
    assert result.weighted_leading_congestion_21d == 3.0
    assert (result.previous_rest_days, result.next_rest_days) == (7.0, 7.0)
    assert result.confidence == 1.0
    assert result.reason_codes == ("fixture_congestion",)
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.code == "FIXTURE_CONGESTION"
    assert evidence.subject_type is SubjectType.TEAM
    assert evidence.subject_id == "team_a" and evidence.fixture_id == "target"
    assert evidence.direction is EvidenceDirection.NEUTRAL and evidence.impact == 0.0
    assert evidence.basis is SignalBasis.OBSERVED and evidence.confidence == 1.0
    assert evidence.source_features == (
        "weighted_trailing_congestion_21d",
        "weighted_leading_congestion_21d",
    )
    assert evidence.model_version == MODEL_VERSION and evidence.calculated_at == CALCULATED_AT
    with pytest.raises(FrozenInstanceError):
        result.confidence = 0.0
    assert isinstance(result.reason_codes, tuple) and isinstance(result.evidence, tuple)


def test_priority_vocabulary_has_no_low_and_table_is_complete():
    assert tuple(value.value for value in FixturePriority) == ("unknown", "normal", "high", "critical")
    assert len(PRIORITY_TABLE) == len(LEAGUE_BANDS) * len(COMPETITION_STAGES) == 55
    assert set(PRIORITY_TABLE) == {
        (band, stage) for band in LEAGUE_BANDS for stage in COMPETITION_STAGES
    }


EXPECTED_PRIORITY = {
    "league": {
        "top": "critical", "upper_mid": "normal", "lower_mid": "normal", "bottom": "critical",
    },
    "qualification": {band: "normal" for band in LEAGUE_BANDS[:-1]},
    "group": {band: "normal" for band in LEAGUE_BANDS[:-1]},
    "league_phase": {band: "normal" for band in LEAGUE_BANDS[:-1]},
    "round_of_32": {band: "normal" for band in LEAGUE_BANDS[:-1]},
    "round_of_16": {band: "high" for band in LEAGUE_BANDS[:-1]},
    "quarter_final": {band: "high" for band in LEAGUE_BANDS[:-1]},
    "semi_final": {band: "critical" for band in LEAGUE_BANDS[:-1]},
    "final": {band: "critical" for band in LEAGUE_BANDS[:-1]},
    "replay": {band: "high" for band in LEAGUE_BANDS[:-1]},
}


@pytest.mark.parametrize(
    ("band", "stage"),
    [(band, stage) for band in LEAGUE_BANDS for stage in COMPETITION_STAGES],
)
def test_all_priority_table_cells_are_pinned_and_tier_never_changes_priority(band, stage):
    expected = "unknown" if band == "unknown" or stage == "unknown" else EXPECTED_PRIORITY[stage][band]
    assert PRIORITY_TABLE[(band, stage)].value == expected
    if expected != "unknown":
        results = {
            evaluate_fixture_context(make_input(
                league_position_band=band,
                target_competition_stage=stage,
                target_competition_tier=tier,
            )).fixture_priority
            for tier in ("league", "domestic_cup", "continental", "unknown")
        }
        assert results == {FixturePriority(expected)}


@pytest.mark.parametrize(("field", "reason"), [
    ("league_position_band", "unknown_league_position_band"),
    ("target_competition_stage", "unknown_competition_stage"),
    ("target_competition_tier", "target_competition_tier_unavailable"),
])
def test_priority_context_failures_emit_one_exact_reason_and_no_partial_output(field, reason):
    value = None if field == "target_competition_tier" else "unknown"
    updates = {field: value}
    if field == "league_position_band":
        updates["standing_context_as_of_utc"] = None
    result = evaluate_fixture_context(make_input(**updates))
    assert result.status is ModuleStatus.MISSING_CONTEXT
    assert result.reason_codes == (reason,) and result.confidence == 0.0
    assert result.fixture_priority is None and result.congestion_index is None
    assert result.evidence == ()


def test_literal_unknown_tier_is_valid_and_does_not_change_priority():
    result = evaluate_fixture_context(make_input(target_competition_tier="unknown"))
    assert result.status is ModuleStatus.OK
    assert result.target_competition_tier == "unknown"
    assert result.fixture_priority is FixturePriority.CRITICAL


@pytest.mark.parametrize(("previous", "next_value", "expected_confidence", "reasons"), [
    (None, 7.0, 0.9, ("previous_rest_anchor_unavailable", "fixture_congestion")),
    (7.0, None, 0.9, ("next_rest_anchor_unavailable", "fixture_congestion")),
    (None, None, 0.8, (
        "previous_rest_anchor_unavailable", "next_rest_anchor_unavailable", "fixture_congestion",
    )),
])
def test_null_rest_anchors_remain_operational_and_only_reduce_confidence(
    previous, next_value, expected_confidence, reasons,
):
    result = evaluate_fixture_context(make_input(
        previous_rest_days=previous,
        next_rest_days=next_value,
    ))
    assert result.status is ModuleStatus.OK
    assert result.confidence == expected_confidence
    assert result.reason_codes == reasons


def test_opening_weekend_both_null_and_zero_windows_remains_ok():
    result = evaluate_fixture_context(make_input(
        weighted_trailing_congestion_21d=0.0,
        weighted_leading_congestion_21d=0.0,
        trailing_fixtures_considered=0,
        leading_fixtures_considered=0,
        previous_rest_days=None,
        next_rest_days=None,
        schedule_context_as_of_utc=None,
    ))
    assert result.status is ModuleStatus.OK
    assert result.congestion_index == 0.0 and result.evidence == ()
    assert result.confidence == 0.5
    assert result.reason_codes == (
        "sparse_trailing_schedule",
        "sparse_leading_schedule",
        "previous_rest_anchor_unavailable",
        "next_rest_anchor_unavailable",
    )


@pytest.mark.parametrize(("hours", "freshness"), [
    (FRESH_24H, 1.0),
    (FRESH_24H + 0.01, 0.8),
    (FRESH_72H, 0.8),
    (FRESH_72H + 0.01, 0.5),
    (FRESH_168H, 0.5),
    (FRESH_168H + 0.01, 0.25),
])
def test_freshness_uses_approved_half_open_boundaries(hours, freshness):
    calculated = (
        __import__("pandas").Timestamp(BUILT_AT)
        + __import__("pandas").Timedelta(hours=hours)
    ).isoformat().replace("+00:00", "Z")
    result = evaluate_fixture_context(make_input(calculated_at=calculated))
    assert result.confidence == pytest.approx(round(0.5 * freshness + 0.5, 4))
    assert ("stale_feature_build" in result.reason_codes) is (hours > FRESH_72H)


def test_future_feature_build_fails_instead_of_clamping():
    with pytest.raises(FeatureV2ValidationError, match="later"):
        evaluate_fixture_context(make_input(feature_built_at="2026-08-03T00:00:00Z"))


@pytest.mark.parametrize(("count", "expected"), [(0, 0.7), (1, 0.75), (5, 0.95), (6, 1.0), (9, 1.0)])
def test_sample_coverage_normalizes_at_six_and_clamps(count, expected):
    result = evaluate_fixture_context(make_input(
        weighted_trailing_congestion_21d=float(count),
        weighted_leading_congestion_21d=0.0,
        trailing_fixtures_considered=count,
        leading_fixtures_considered=0,
        schedule_context_as_of_utc=None,
    ))
    assert result.confidence == expected


@pytest.mark.parametrize(("congestion", "emits"), [
    (CONGESTION_EVIDENCE_THRESHOLD - 0.0001, False),
    (CONGESTION_EVIDENCE_THRESHOLD, True),
])
def test_fixture_congestion_evidence_threshold_is_strictly_pinned(congestion, emits):
    result = evaluate_fixture_context(make_input(
        weighted_trailing_congestion_21d=3.5,
        weighted_leading_congestion_21d=congestion - 3.5,
        trailing_fixtures_considered=3,
        leading_fixtures_considered=3,
    ))
    assert (len(result.evidence) == 1) is emits
    assert ("fixture_congestion" in result.reason_codes) is emits
    assert "REST_ADVANTAGE" not in {item.code for item in result.evidence}


def test_reason_order_replay_and_replacement_are_deterministic():
    item = make_input(
        calculated_at="2026-08-10T00:00:00Z",
        weighted_trailing_congestion_21d=2.5,
        weighted_leading_congestion_21d=2.5,
        trailing_fixtures_considered=2,
        leading_fixtures_considered=2,
        previous_rest_days=None,
        next_rest_days=None,
    )
    result = evaluate_fixture_context(item)
    assert result == evaluate_fixture_context(item)
    assert result.reason_codes == (
        "stale_feature_build",
        "sparse_trailing_schedule",
        "sparse_leading_schedule",
        "previous_rest_anchor_unavailable",
        "next_rest_anchor_unavailable",
    )
    assert tuple(reason for reason in REASON_ORDER if reason in result.reason_codes) == result.reason_codes


@pytest.mark.parametrize("updates", [
    {"trailing_fixtures_considered": -1},
    {"leading_fixtures_considered": 1.5},
    {"weighted_trailing_congestion_21d": float("nan")},
    {"weighted_leading_congestion_21d": -1.0},
    {"trailing_fixtures_considered": 2, "weighted_trailing_congestion_21d": 3.0},
    {"previous_rest_days": 0.0},
    {"next_rest_days": 366.0},
    {"league_position_band": "fifth"},
    {"target_competition_stage": "friendly"},
    {"target_competition_tier": "provider_cup"},
    {"leading_fixtures_considered": 1, "weighted_leading_congestion_21d": 1.0,
     "schedule_context_as_of_utc": None},
    {"league_position_band": "bottom", "standing_context_as_of_utc": None},
])
def test_nonfinite_contradictory_and_unknown_operational_inputs_fail_closed(updates):
    with pytest.raises(FeatureV2ValidationError):
        evaluate_fixture_context(make_input(**updates))


def test_unsupported_registry_and_competition_weight_versions_are_typed():
    with pytest.raises(UnsupportedFeatureContractError, match="registry"):
        evaluate_fixture_context(make_input(feature_registry_version="fi5-registry-v1"))
    with pytest.raises(UnsupportedFeatureContractError, match="competition weight"):
        evaluate_fixture_context(make_input(competition_weight_version="competition-weights-v2"))


def _build(tmp_path):
    base, context = sources(tmp_path / "source")
    root = tmp_path / "features"
    build_features_v2(
        base,
        context,
        root,
        feature_build_id="fi6c",
        built_at=BUILT_AT,
    )
    return root / "builds-v2/fi6c", base, context


def test_loader_accepts_exact_v2_row_and_preserves_merged_m3_values(tmp_path):
    build, base, context = _build(tmp_path)
    item = load_fixture_context_input(
        build, base, context,
        fixture_id="target", team_id="team_a", calculated_at=CALCULATED_AT,
    )
    result = evaluate_fixture_context(item)
    assert result.status is ModuleStatus.OK
    assert result.fixture_priority is FixturePriority.CRITICAL
    assert result.congestion_index == 3.0
    assert result.previous_rest_days == 16.0 and result.next_rest_days == 7.0
    assert result.schedule_context_as_of_utc == "2026-01-01T00:00:00Z"
    assert result.standing_context_as_of_utc == "2026-07-25T00:00:00Z"


def test_loader_missing_build_manifest_and_exact_row_emit_distinct_single_reasons(tmp_path):
    absent = load_fixture_context_input(
        tmp_path / "absent", None, None,
        fixture_id="target", team_id="team_a", calculated_at=CALCULATED_AT,
    )
    assert evaluate_fixture_context(absent).reason_codes == ("feature_build_unavailable",)
    directory = tmp_path / "empty"; directory.mkdir()
    missing_manifest = load_fixture_context_input(
        directory, None, None,
        fixture_id="target", team_id="team_a", calculated_at=CALCULATED_AT,
    )
    assert evaluate_fixture_context(missing_manifest).reason_codes == ("feature_manifest_unavailable",)

    build, base, context = _build(tmp_path / "built")
    missing_row = load_fixture_context_input(
        build, base, context,
        fixture_id="missing", team_id="team_a", calculated_at=CALCULATED_AT,
    )
    assert evaluate_fixture_context(missing_row).reason_codes == ("fixture_context_row_unavailable",)


@pytest.mark.parametrize(("field", "value"), [
    ("schema_version", 1),
    ("build_family", "canonical-features-v1"),
    ("feature_registry_version", "fi5-registry-v1"),
    ("feature_engine_version", "fi5-engine-v1"),
    ("cutoff_policy_version", "inclusive-cutoff-v1"),
])
def test_loader_rejects_unsupported_manifest_contract_before_validation(tmp_path, field, value):
    build = tmp_path / field
    build.mkdir()
    manifest = {
        "schema_version": 2,
        "build_family": "module-enablement-features-v2",
        "feature_registry_version": "fi5-registry-v2",
        "feature_engine_version": "fi5-engine-v2",
        "cutoff_policy_version": "strictly-before-kickoff-v2",
    }
    manifest[field] = value
    (build / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(UnsupportedFeatureContractError):
        load_fixture_context_input(
            build, object(), tmp_path,
            fixture_id="target", team_id="team_a", calculated_at=CALCULATED_AT,
        )


def test_loader_rejects_unversioned_root_and_never_uses_pointer(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    (root / "_features_v2_latest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(UnsupportedFeatureContractError, match="unversioned"):
        load_fixture_context_input(
            root, None, None,
            fixture_id="target", team_id="team_a", calculated_at=CALCULATED_AT,
        )


def test_loader_never_degrades_corrupt_supported_v2_to_missing_context(tmp_path):
    build, base, context = _build(tmp_path)
    dataset = build / "datasets/team_fixture_context_v2.parquet"
    payload = bytearray(dataset.read_bytes())
    payload[-1] ^= 1
    dataset.write_bytes(payload)
    with pytest.raises(FeatureV2ValidationError):
        load_fixture_context_input(
            build, base, context,
            fixture_id="target", team_id="team_a", calculated_at=CALCULATED_AT,
        )


def test_source_has_no_module_dependencies_prohibited_outputs_or_runtime_io():
    source = Path(__file__).parents[1] / "football_intelligence/modules/fixture_context.py"
    text = source.read_text(encoding="utf-8").casefold()
    prohibited = (
        "expectedminutes", "expected_minutes", "tacticalrole", "tactical_role",
        "rotation_probability", "late_cameo_risk", "player_id", "rest_advantage",
        "fixture difficulty", "fdr", "recommendation", "sportmonks", "requests",
        "httpx", "urllib", "tool_registry", "finalresponse", "orchestrat",
        "renderer", "fpl_ui", "datetime.now", "datetime.utcnow", "time.time",
    )
    assert not any(token in text for token in prohibited)
    summary = evaluate_fixture_context(make_input()).evidence[0].summary.casefold()
    advice = ("buy ", "sell ", "transfer ", "captain ", "bench ", "avoid ", "recommend")
    assert not any(token in summary for token in advice)
