from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import json
from pathlib import Path

import pytest

import fpl_server
from football_data_contract import (
    EvidenceDirection,
    EvidenceItem,
    SignalBasis,
    SubjectType,
)
from fpl_grounded_assistant.final_response import FinalResponse
from fpl_grounded_assistant.harness_adapter import _to_dict, to_ask_response

AskRequest = fpl_server.AskRequest
AskResponse = fpl_server.AskResponse
_sub_response_dict = fpl_server._sub_response_dict


FIXTURES = json.loads(
    (Path(__file__).parents[1] / "http_contract_fixtures.json").read_text(
        encoding="utf-8"
    )
)["evidence_fixtures"]


def evidence_item() -> EvidenceItem:
    return EvidenceItem(
        code="ROLE_STABLE",
        label="Stable role",
        subject_type=SubjectType.PLAYER,
        subject_id="cp_1",
        fixture_id=None,
        impact=2.0,
        direction=EvidenceDirection.POSITIVE,
        confidence=0.8,
        basis=SignalBasis.OBSERVED,
        summary="Stable recent role.",
        source_features=("player_role_window_summary",),
        model_version="tactical-role-v1",
        calculated_at="2026-07-25T00:00:00Z",
    )


def final_response(**overrides: object) -> FinalResponse:
    values = {
        "final_text": "Grounded response.",
        "outcome": "ok",
        "supported": True,
        "intent": "player_summary",
        "review_passed": True,
        "llm_used": False,
        "debug": None,
    }
    values.update(overrides)
    return FinalResponse(**values)


def ask_v2_payload(evidence: tuple[EvidenceItem, ...] | None) -> dict[str, object]:
    return {
        "answer_text": "Grounded response.",
        "outcome": "ok",
        "selected_tool": "get_player_summary",
        "evidence": evidence,
        "routing_trace": {
            "branch": "route",
            "grounded": True,
            "classification_source": None,
            "classifier_confidence": None,
        },
    }


def test_final_response_adds_only_optional_frozen_evidence_field():
    item = evidence_item()
    result = final_response(evidence=(item,))
    assert [field.name for field in fields(FinalResponse)][-1] == "evidence"
    assert result.evidence == (item,)
    assert final_response().evidence is None
    with pytest.raises(FrozenInstanceError):
        result.evidence = None


def test_none_preserves_pre_fi7a_json_shape_and_fixture_contract():
    baseline = AskResponse(
        final_text="Grounded response.",
        outcome="ok",
        supported=True,
        intent="player_summary",
        review_passed=True,
        llm_used=False,
        route_source="deterministic",
    )
    payload = json.loads(baseline.model_dump_json())
    assert FIXTURES["without_evidence"]["expected"]["presence"] == "absent"
    assert "evidence" not in payload

    projected = to_ask_response(ask_v2_payload(None), AskRequest(question="Salah"))
    assert projected.model_dump_json() == baseline.model_dump_json()


def test_actual_pydantic_projection_serializes_exact_evidence_wire_shape():
    injected = final_response(evidence=(evidence_item(),))
    projected = to_ask_response(
        ask_v2_payload(injected.evidence),
        AskRequest(question="Salah"),
    )
    payload = json.loads(projected.model_dump_json())
    expected = FIXTURES["with_evidence"]["expected_wire"]
    assert payload["evidence"] == expected
    assert isinstance(payload["evidence"], list)
    assert set(payload["evidence"][0]) == {
        field.name for field in fields(EvidenceItem)
    }
    assert payload["evidence"][0]["subject_type"] == "player"
    assert payload["evidence"][0]["direction"] == "positive"
    assert payload["evidence"][0]["basis"] == "observed"
    assert payload["evidence"][0]["fixture_id"] is None
    assert isinstance(payload["evidence"][0]["source_features"], list)
    assert isinstance(payload["evidence"][0]["impact"], float)
    assert isinstance(payload["evidence"][0]["confidence"], float)


def test_generic_recursive_serializer_normalizes_enums_and_tuples():
    wire = _to_dict((evidence_item(),))
    assert wire == FIXTURES["with_evidence"]["expected_wire"]
    assert wire[0]["subject_type"] == "player"
    assert wire[0]["direction"] == "positive"
    assert wire[0]["basis"] == "observed"
    assert wire[0]["source_features"] == ["player_role_window_summary"]


def test_nested_final_response_evidence_survives_bounded_serializer():
    nested = final_response(evidence=(evidence_item(),))
    parent = final_response(
        intent="multi_intent",
        sub_responses=(nested,),
    )
    assert isinstance(parent.sub_responses, tuple)
    payload = [_sub_response_dict(item) for item in parent.sub_responses]
    assert payload[0]["evidence"] == FIXTURES["with_evidence"]["expected_wire"]


def test_nested_final_response_omits_evidence_when_none():
    payload = _sub_response_dict(final_response())
    assert "evidence" not in payload
