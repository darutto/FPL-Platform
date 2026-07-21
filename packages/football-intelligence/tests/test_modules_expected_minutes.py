from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from football_data_contract.enums import AvailabilityState
from football_intelligence.features.store_v2 import FeatureV2ValidationError, build_features_v2
from football_intelligence.modules import (
    AvailabilityInput,
    ModuleStatus,
    UnsupportedFeatureContractError,
    evaluate_expected_minutes,
    load_expected_minutes_input,
)
from football_intelligence.modules.expected_minutes import (
    AVAILABILITY_INPUT_VERSION,
    COEFFICIENT_VERSION,
    CONGESTION_DAMPING_PER_WEIGHTED_FIXTURE,
    MIN_CONGESTION_MULTIPLIER,
    MODEL_VERSION,
)

from test_features_v2 import sources


CALCULATED_AT = "2026-08-01T14:00:00Z"


def _input(tmp_path, *, availability=AvailabilityInput(state=AvailabilityState.AVAILABLE)):
    base, context = sources(tmp_path / "source")
    root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="fi6a", built_at=CALCULATED_AT)
    build = root / "builds-v2/fi6a"
    item = load_expected_minutes_input(
        build,
        base,
        context,
        fixture_id="target",
        team_id="team_a",
        player_id="player_1",
        calculated_at=CALCULATED_AT,
        availability=availability,
    )
    return item, build, base, context


def test_m1_golden_probabilities_evidence_and_versions(tmp_path):
    item, _, _, _ = _input(tmp_path)
    result = evaluate_expected_minutes(item)
    congestion_multiplier = 1.0 - 3.0 * CONGESTION_DAMPING_PER_WEIGHTED_FIXTURE
    expected_start = (14 / 21) * congestion_multiplier
    expected_cameo = (2 / 6) * congestion_multiplier
    expected_minutes = expected_start * 83.75 + expected_cameo * 17.5

    assert result.status is ModuleStatus.OK
    assert result.model_version == MODEL_VERSION == "expected-minutes-v1"
    assert result.coefficient_version == COEFFICIENT_VERSION == "expected-minutes-hand-tuned-v1"
    assert result.availability_input_version == AVAILABILITY_INPUT_VERSION == "availability-input-v1"
    assert result.start_probability == pytest.approx(expected_start)
    assert result.cameo_probability == pytest.approx(expected_cameo)
    assert result.expected_minutes == pytest.approx(expected_minutes)
    assert result.rotation_risk == pytest.approx(1 - expected_start)
    assert result.minutes_risk_v2 == pytest.approx(100 * (1 - expected_minutes / 90))
    assert result.confidence == 1.0 and result.reason_codes == ()
    assert tuple(value.code for value in result.evidence) == (
        "ROTATION_RISK", "CAMEO_RISK", "MINUTES_CONFIDENCE_HIGH",
    )
    assert all(value.model_version == MODEL_VERSION and value.calculated_at == CALCULATED_AT for value in result.evidence)


def test_m1_replay_is_identical_for_same_build_and_explicit_timestamp(tmp_path):
    item, _, _, _ = _input(tmp_path)
    assert evaluate_expected_minutes(item) == evaluate_expected_minutes(item)


def test_congestion_damping_is_causal_and_bounded(tmp_path):
    item, _, _, _ = _input(tmp_path)
    baseline = evaluate_expected_minutes(item)
    congested = evaluate_expected_minutes(
        type(item)(**{**item.__dict__, "weighted_trailing_congestion_21d": 40.0, "weighted_leading_congestion_21d": 40.0})
    )
    assert congested.start_probability < baseline.start_probability
    assert congested.expected_minutes < baseline.expected_minutes
    assert congested.start_probability == pytest.approx((14 / 21) * MIN_CONGESTION_MULTIPLIER)


def test_explicit_availability_input_reduces_minutes_and_emits_doubt(tmp_path):
    item, _, _, _ = _input(
        tmp_path,
        availability=AvailabilityInput(state=AvailabilityState.DOUBTFUL, chance_of_playing=0.5),
    )
    result = evaluate_expected_minutes(item)
    assert result.status is ModuleStatus.OK
    assert result.start_probability == pytest.approx((14 / 21) * 0.5 * 0.925)
    assert "availability_doubt" in result.reason_codes
    assert {"AVAILABILITY_DOUBT", "MINUTES_CONFIDENCE_LOW"}.issubset({value.code for value in result.evidence})


def test_availability_input_version_is_closed():
    with pytest.raises(ValueError, match="unsupported availability input version"):
        AvailabilityInput(state=AvailabilityState.AVAILABLE, version="availability-input-v2")
    with pytest.raises(ValueError, match="only for doubtful"):
        AvailabilityInput(state=AvailabilityState.AVAILABLE, chance_of_playing=1.0)


def test_module_statuses_are_distinct_and_results_are_frozen(tmp_path):
    assert ModuleStatus.MISSING_CONTEXT.value == "missing_context"
    assert ModuleStatus.NOT_IMPLEMENTED.value == "not_implemented"
    assert ModuleStatus.MISSING_CONTEXT is not ModuleStatus.NOT_IMPLEMENTED
    item, _, _, _ = _input(tmp_path)
    result = evaluate_expected_minutes(item)
    with pytest.raises(FrozenInstanceError):
        result.confidence = 0.0


def test_absent_build_and_absent_row_degrade_to_missing_context(tmp_path):
    missing_build = load_expected_minutes_input(
        tmp_path / "absent", None, None, fixture_id="target", team_id="team_a",
        player_id="player_1", calculated_at=CALCULATED_AT,
    )
    assert evaluate_expected_minutes(missing_build).status is ModuleStatus.MISSING_CONTEXT

    item, build, base, context = _input(tmp_path / "present")
    missing_row = load_expected_minutes_input(
        build, base, context, fixture_id=item.fixture_id, team_id=item.team_id,
        player_id="missing_player", calculated_at=CALCULATED_AT,
    )
    result = evaluate_expected_minutes(missing_row)
    assert result.status is ModuleStatus.MISSING_CONTEXT and result.evidence == ()


def test_v1_is_typed_unsupported_and_invalid_v2_escapes_validation(tmp_path):
    v1 = tmp_path / "v1"; v1.mkdir(); (v1 / "manifest.json").write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(UnsupportedFeatureContractError) as caught:
        load_expected_minutes_input(
            v1, object(), tmp_path, fixture_id="target", team_id="team_a",
            player_id="player_1", calculated_at=CALCULATED_AT,
        )
    assert caught.value.code == "unsupported_feature_contract"

    _, build, base, context = _input(tmp_path / "corrupt")
    dataset = build / "datasets/player_fixture_module_inputs.parquet"
    frame = pd.read_parquet(dataset); frame.loc[0, "starts_last_6"] = 99; frame.to_parquet(dataset, index=False)
    with pytest.raises(FeatureV2ValidationError, match="parquet hash mismatch"):
        load_expected_minutes_input(
            build, base, context, fixture_id="target", team_id="team_a",
            player_id="player_1", calculated_at=CALCULATED_AT,
        )


def test_missing_availability_and_congestion_reduce_confidence_without_fabrication(tmp_path):
    item, _, _, _ = _input(tmp_path, availability=AvailabilityInput())
    partial = type(item)(**{
        **item.__dict__,
        "weighted_trailing_congestion_21d": None,
        "weighted_leading_congestion_21d": None,
    })
    result = evaluate_expected_minutes(partial)
    assert result.status is ModuleStatus.OK and result.confidence == pytest.approx(0.6)
    assert result.reason_codes == ("availability_context_missing", "congestion_context_missing")
    assert "AVAILABILITY_DOUBT" not in {value.code for value in result.evidence}


def test_no_history_returns_no_scores_or_evidence(tmp_path):
    item, _, _, _ = _input(tmp_path)
    empty = type(item)(**{
        **item.__dict__,
        "weighted_start_share_last_6": None,
        "weighted_start_denominator_last_6": 0.0,
        "eligible_team_fixtures_last_6": 0,
        "cameo_appearances_last_6": 0,
        "mean_minutes_when_started_last_6": None,
        "mean_minutes_when_cameo_last_6": None,
    })
    result = evaluate_expected_minutes(empty)
    assert result.status is ModuleStatus.MISSING_CONTEXT
    assert result.start_probability is result.expected_minutes is result.minutes_risk_v2 is None
    assert result.evidence == () and result.reason_codes == ("insufficient_start_history",)


def test_direct_inputs_fail_closed_and_wrong_registry_is_not_missing_context(tmp_path):
    item, _, _, _ = _input(tmp_path)
    with pytest.raises(ValueError, match="present together"):
        type(item)(**{**item.__dict__, "feature_build_id": None})
    with pytest.raises(ValueError, match="congestion context"):
        type(item)(**{**item.__dict__, "weighted_leading_congestion_21d": None})
    wrong = type(item)(**{**item.__dict__, "feature_registry_version": "fi5-registry-v1"})
    with pytest.raises(UnsupportedFeatureContractError):
        evaluate_expected_minutes(wrong)
