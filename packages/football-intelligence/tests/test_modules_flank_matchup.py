from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

import football_intelligence.modules as modules
from football_intelligence.features.store_v2 import FeatureV2ValidationError
from football_intelligence.modules import (
    FlankMatchupInput,
    FlankMatchupResult,
    ModuleStatus,
    evaluate_flank_matchup,
)
from football_intelligence.modules.contracts import ModuleResult
from football_intelligence.modules.flank_matchup import MODEL_VERSION


def make_input(calculated_at: str = "2026-08-01T00:00:00Z") -> FlankMatchupInput:
    return FlankMatchupInput(
        fixture_id="fixture-1",
        team_id="team-1",
        player_id="player-1",
        calculated_at=calculated_at,
    )


def test_exact_non_operational_result_and_player_passthrough():
    item = make_input()
    result = evaluate_flank_matchup(item)
    assert isinstance(result, FlankMatchupResult)
    assert result.status is ModuleStatus.NOT_IMPLEMENTED
    assert result.status not in (ModuleStatus.OK, ModuleStatus.MISSING_CONTEXT)
    assert result.model_version == MODEL_VERSION == "flank-matchup-v1"
    assert result.feature_registry_version is None
    assert result.feature_build_id is None
    assert result.fixture_id == item.fixture_id
    assert result.team_id == item.team_id
    assert result.player_id == item.player_id
    assert result.confidence == 0.0
    assert result.reason_codes == ("not_implemented",)
    assert result.evidence == ()


def test_input_and_result_are_frozen():
    item = make_input()
    result = evaluate_flank_matchup(item)
    with pytest.raises(FrozenInstanceError):
        item.player_id = "other"
    with pytest.raises(FrozenInstanceError):
        result.player_id = "other"
    assert isinstance(result.reason_codes, tuple)
    assert isinstance(result.evidence, tuple)


@pytest.mark.parametrize(
    "calculated_at",
    [
        "2026-08-01T00:00:00",
        "2026-08-01T01:00:00+01:00",
        "2026-07-31T19:00:00-05:00",
        "not-a-timestamp",
        "2026-08-01T00:00:00+0000",
        "2026-08-01T00:00:00-00:00",
    ],
)
def test_invalid_naive_non_utc_or_malformed_timestamps_fail_typed(calculated_at):
    with pytest.raises(FeatureV2ValidationError, match="calculated_at"):
        make_input(calculated_at)


@pytest.mark.parametrize(
    "calculated_at",
    ["2026-08-01T00:00:00Z", "2026-08-01T00:00:00+00:00"],
)
def test_approved_utc_timestamp_forms_are_accepted(calculated_at):
    assert make_input(calculated_at).calculated_at == calculated_at


def test_deterministic_replay_preserves_only_explicit_subject_identifiers():
    item = make_input()
    first = evaluate_flank_matchup(item)
    assert first == evaluate_flank_matchup(item)
    other = FlankMatchupInput(
        fixture_id="fixture-2",
        team_id="team-2",
        player_id="player-2",
        calculated_at="2027-01-01T00:00:00Z",
    )
    second = evaluate_flank_matchup(other)
    assert second.player_id == "player-2"
    assert second.status is ModuleStatus.NOT_IMPLEMENTED
    assert second.confidence == 0.0
    assert second.reason_codes == ("not_implemented",)
    assert second.evidence == ()


def test_result_shape_is_module_result_plus_player_id_and_no_active_fields():
    assert tuple(field.name for field in fields(FlankMatchupResult)) == (
        *(field.name for field in fields(ModuleResult)),
        "player_id",
    )
    result = evaluate_flank_matchup(make_input())
    prohibited = {
        "attacker_flank",
        "opponent_defensive_flank",
        "flank_matchup_score",
        "supporting_signals",
        "limitations",
        "confidence_explanation",
    }
    assert prohibited.isdisjoint(vars(result))
    assert all(not hasattr(result, name) for name in prohibited)


def test_package_exports_are_exact_and_model_version_remains_private():
    assert modules.FlankMatchupInput is FlankMatchupInput
    assert modules.FlankMatchupResult is FlankMatchupResult
    assert modules.evaluate_flank_matchup is evaluate_flank_matchup
    assert "FlankMatchupInput" in modules.__all__
    assert "FlankMatchupResult" in modules.__all__
    assert "evaluate_flank_matchup" in modules.__all__
    assert not hasattr(modules, "MODEL_VERSION")


def test_source_boundary_excludes_active_dependencies_and_side_effects():
    source = (
        Path(__file__).parents[1] / "football_intelligence/modules/flank_matchup.py"
    )
    text = source.read_text(encoding="utf-8").casefold()
    prohibited = (
        "opponent_flank_weakness",
        "expected_minutes",
        "tactical_role",
        "fixture_context",
        "opponent_personnel_disruption",
        "registry_v2",
        "feature_loader",
        "feature_builder",
        "zonal",
        "compute_player_zone_shares",
        "sportmonks",
        "understat",
        "provider",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "persistence",
        "datetime.now",
        "datetime.utcnow",
        "time.time",
    )
    assert not any(token in text for token in prohibited)
