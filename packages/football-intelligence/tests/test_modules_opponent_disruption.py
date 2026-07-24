from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

import football_intelligence.modules as modules
from football_intelligence.features.store_v2 import FeatureV2ValidationError
from football_intelligence.modules import (
    ModuleStatus,
    OpponentPersonnelDisruptionInput,
    OpponentPersonnelDisruptionResult,
    evaluate_opponent_personnel_disruption,
)
from football_intelligence.modules.contracts import ModuleResult
from football_intelligence.modules.opponent_disruption import MODEL_VERSION


def make_input(calculated_at: str = "2026-08-01T00:00:00Z"):
    return OpponentPersonnelDisruptionInput(
        fixture_id="fixture-1",
        team_id="team-1",
        calculated_at=calculated_at,
    )


def test_golden_non_operational_result_is_exact():
    item = make_input()
    result = evaluate_opponent_personnel_disruption(item)
    assert isinstance(result, OpponentPersonnelDisruptionResult)
    assert result.status is ModuleStatus.NOT_IMPLEMENTED
    assert result.model_version == MODEL_VERSION == "opponent-personnel-disruption-v1"
    assert result.feature_registry_version is None
    assert result.feature_build_id is None
    assert result.fixture_id == item.fixture_id
    assert result.team_id == item.team_id
    assert result.confidence == 0.0
    assert result.reason_codes == ("not_implemented",)
    assert result.evidence == ()
    assert result.status is not ModuleStatus.OK
    assert result.status is not ModuleStatus.MISSING_CONTEXT


def test_input_and_result_are_frozen_with_immutable_collections():
    item = make_input()
    result = evaluate_opponent_personnel_disruption(item)
    with pytest.raises(FrozenInstanceError):
        item.team_id = "other"
    with pytest.raises(FrozenInstanceError):
        result.confidence = 1.0
    assert isinstance(result.reason_codes, tuple)
    assert isinstance(result.evidence, tuple)


@pytest.mark.parametrize("calculated_at", [
    "2026-08-01T00:00:00",
    "2026-08-01T01:00:00+01:00",
    "not-a-timestamp",
])
def test_invalid_or_non_utc_timestamps_fail_typed(calculated_at):
    with pytest.raises(FeatureV2ValidationError, match="calculated_at"):
        make_input(calculated_at)


@pytest.mark.parametrize("calculated_at", [
    "2026-08-01T00:00:00Z",
    "2026-08-01T00:00:00+00:00",
])
def test_utc_timestamp_forms_are_accepted(calculated_at):
    assert make_input(calculated_at).calculated_at == calculated_at


def test_repeated_evaluation_is_identical_and_input_independent():
    item = make_input()
    assert (
        evaluate_opponent_personnel_disruption(item)
        == evaluate_opponent_personnel_disruption(item)
    )
    other = OpponentPersonnelDisruptionInput(
        fixture_id="fixture-2",
        team_id="team-2",
        calculated_at="2027-01-01T00:00:00Z",
    )
    result = evaluate_opponent_personnel_disruption(other)
    assert result.status is ModuleStatus.NOT_IMPLEMENTED
    assert result.confidence == 0.0
    assert result.reason_codes == ("not_implemented",)
    assert result.evidence == ()


def test_no_evidence_or_reserved_active_code_is_emitted():
    result = evaluate_opponent_personnel_disruption(make_input())
    assert result.evidence == ()
    assert "OPPONENT_UNIT_DISRUPTION" not in {
        item.code for item in result.evidence
    }


def test_result_has_only_the_shared_module_result_fields():
    result = evaluate_opponent_personnel_disruption(make_input())
    assert tuple(field.name for field in fields(result)) == tuple(
        field.name for field in fields(ModuleResult)
    )
    prohibited = {
        "affected_unit",
        "affected_flank",
        "usual_starter_missing",
        "replacement_player",
        "replacement_experience",
        "formation_change_probability",
        "unit_disruption_score",
        "benefiting_player_ids",
    }
    assert prohibited.isdisjoint(vars(result))
    assert all(not hasattr(result, name) for name in prohibited)


def test_package_exports_follow_existing_unambiguous_convention():
    assert modules.OpponentPersonnelDisruptionInput is OpponentPersonnelDisruptionInput
    assert modules.OpponentPersonnelDisruptionResult is OpponentPersonnelDisruptionResult
    assert (
        modules.evaluate_opponent_personnel_disruption
        is evaluate_opponent_personnel_disruption
    )
    assert not hasattr(modules, "MODEL_VERSION")


def test_source_boundary_excludes_active_dependencies_and_side_effects():
    source = (
        Path(__file__).parents[1]
        / "football_intelligence/modules/opponent_disruption.py"
    )
    text = source.read_text(encoding="utf-8").casefold()
    prohibited = (
        "requests",
        "httpx",
        "urllib",
        "socket",
        "sportmonks",
        "datetime.now",
        "datetime.utcnow",
        "time.time",
        "read_parquet",
        "parquet",
        "manifest",
        "pointer",
        "expected_minutes",
        "expectedminutesresult",
        "tactical_role",
        "tacticalroleresult",
        "fixture_context",
        "fixturecontextresult",
        "orchestrat",
        "renderer",
        "fpl_ui",
        "rotation_probability",
        "late_cameo_risk",
        "fdr",
    )
    assert not any(token in text for token in prohibited)
    advice = ("buy ", "sell ", "transfer ", "captain ", "recommend")
    assert not any(token in text for token in advice)
