"""FI-7b3 deterministic rendering and real-session evidence propagation."""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant import final_response
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.renderer import render


def _evidence(index: int) -> dict:
    return {
        "code": "MINUTES_CONFIDENCE_HIGH",
        "label": f"Minutes confidence {index}",
        "subject_type": "player",
        "subject_id": f"player-{index}",
        "fixture_id": "fixture-1",
        "impact": 1.0,
        "direction": "positive",
        "confidence": 0.9,
        "basis": "observed",
        "summary": f"Observed minutes signal {index}",
        "source_features": ["expected_minutes", f"signal_{index}"],
        "model_version": "expected-minutes-v1",
        "calculated_at": "2026-08-01T12:00:00Z",
    }


BOUNDED_EVIDENCE = [_evidence(index) for index in range(8)]

EXPECTED_MINUTES = {
    "status": "ok",
    "expected_minutes": 78.5,
    "start_probability": 0.86,
    "cameo_probability": 0.1,
    "rotation_risk": "low",
    "minutes_risk_v2": None,
    "confidence": 0.9,
    "reason_codes": ["availability_available"],
}

TACTICAL_ROLE = {
    "status": "ok",
    "primary_role": "right_winger",
    "role_distribution": {"right_winger": 0.75, "left_winger": 0.25},
    "primary_flank": "right",
    "flank_distribution": {"right": 0.75, "left": 0.25},
    "formation_depth": "advanced",
    "role_stability": 0.75,
    "role_change_detected": False,
    "out_of_position_score": 0.5,
    "confidence": 0.8,
    "reason_codes": ["role_stable"],
}

FIXTURE_CONTEXT = {
    "status": "ok",
    "fixture_priority": "high",
    "congestion_index": 7.0,
    "weighted_trailing_congestion_21d": 4.0,
    "weighted_leading_congestion_21d": 3.0,
    "previous_rest_days": 4.0,
    "next_rest_days": None,
    "target_competition_tier": "tier_1",
    "target_competition_stage": "league",
    "league_position_band": "top",
    "confidence": 0.85,
    "reason_codes": ["next_rest_anchor_unavailable"],
}

COMPOSITE = {
    "status": "ok",
    "fixture_id": "fixture-1",
    "modules": {
        "expected_minutes": EXPECTED_MINUTES,
        "tactical_role": TACTICAL_ROLE,
        "fixture_context": FIXTURE_CONTEXT,
    },
    "reason_codes": {
        "expected_minutes": EXPECTED_MINUTES["reason_codes"],
        "tactical_role": TACTICAL_ROLE["reason_codes"],
        "fixture_context": FIXTURE_CONTEXT["reason_codes"],
    },
    "evidence": BOUNDED_EVIDENCE,
}


@pytest.fixture(autouse=True)
def _isolated_server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    monkeypatch.setenv("FOOTBALL_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    yield
    fpl_server._sessions.clear()


def test_individual_renderers_have_fixed_fields_and_native_values():
    assert render("get_expected_minutes", EXPECTED_MINUTES).splitlines() == [
        "Status: ok",
        "Expected minutes: 78.5",
        "Start probability: 0.86",
        "Cameo probability: 0.1",
        "Rotation risk: low",
        "Minutes risk v2: unavailable",
        "Confidence: 0.9",
        "Reasons: availability_available",
    ]
    assert render("get_tactical_role", TACTICAL_ROLE).splitlines()[1:5] == [
        "Primary role: right_winger",
        'Role distribution: {"right_winger":0.75,"left_winger":0.25}',
        "Primary flank: right",
        'Flank distribution: {"right":0.75,"left":0.25}',
    ]
    fixture_lines = render("get_fixture_context", FIXTURE_CONTEXT).splitlines()
    assert fixture_lines[0] == "Status: ok"
    assert fixture_lines[6] == "Next rest days: unavailable"
    assert fixture_lines[7] == "Competition tier: tier_1"
    assert fixture_lines[8] == "Competition stage: league"
    assert fixture_lines[-1] == "Reasons: next_rest_anchor_unavailable"


def test_production_shaped_fixture_context_keys_render_in_direct_and_composite_outputs():
    direct = render("get_fixture_context", FIXTURE_CONTEXT)
    composite = render("get_player_intelligence", COMPOSITE)

    for rendered in (direct, composite):
        assert "Competition tier: tier_1" in rendered
        assert "Competition stage: league" in rendered
        assert "Competition tier: unavailable" not in rendered
        assert "Competition stage: unavailable" not in rendered


def test_composite_renderer_is_m1_m2_m3_ordered_and_replay_stable():
    rendered = render("get_player_intelligence", COMPOSITE)
    assert rendered.index("Expected minutes\n") < rendered.index("Tactical role\n")
    assert rendered.index("Tactical role\n") < rendered.index("Fixture context\n")
    assert rendered == render("get_player_intelligence", deepcopy(COMPOSITE))
    assert "advice" not in rendered.lower()
    assert "recommend" not in rendered.lower()


def test_composite_partial_keeps_every_section_and_native_missing_reason():
    partial = deepcopy(COMPOSITE)
    partial["status"] = "partial"
    partial["modules"].pop("tactical_role")
    partial["reason_codes"]["tactical_role"] = ["role_context_unavailable"]
    rendered = render("get_player_intelligence", partial)
    assert rendered.startswith("Status: partial\n")
    assert "Tactical role\nStatus: missing_context" in rendered
    assert "Reasons: role_context_unavailable" in rendered
    assert rendered.count("unavailable") >= 9


def test_missing_context_and_empty_reasons_do_not_fabricate_values():
    missing = {"status": "missing_context", "reason_codes": ["feature_build_unavailable"]}
    rendered = render("get_expected_minutes", missing)
    assert rendered.splitlines()[0] == "Status: missing_context"
    assert rendered.splitlines()[-1] == "Reasons: feature_build_unavailable"
    assert sum(line.endswith(": unavailable") for line in rendered.splitlines()) == 6

    all_missing = {
        "status": "missing_context",
        "modules": {},
        "reason_codes": {
            "expected_minutes": ["feature_build_unavailable"],
            "tactical_role": ["feature_build_unavailable"],
            "fixture_context": ["feature_build_unavailable"],
        },
    }
    composite = render("get_player_intelligence", all_missing)
    assert composite.count("Status: missing_context") == 4
    assert composite.count("Reasons: feature_build_unavailable") == 3


def test_successful_fi_harness_result_copies_evidence_without_transform(monkeypatch):
    result = OrchestratorResult(
        question="player intelligence for Saka",
        tool_chosen="get_player_intelligence",
        tool_args={"player": "Saka"},
        tool_output=deepcopy(COMPOSITE),
        answer_text="controlled",
        llm_used=True,
        model="controlled-model",
        outcome="ok",
    )
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: result,
    )
    response = ask_v2(
        "player intelligence for Saka",
        STANDARD_BOOTSTRAP,
        orch_client=object(),
    )
    assert response["evidence"] == BOUNDED_EVIDENCE
    assert response["evidence"] is result.tool_output["evidence"]


def _controlled_ask_v2(question: str, *args, **kwargs) -> dict:
    if question == "player intelligence for Saka":
        return {
            "selected_tool": "get_player_intelligence",
            "answer_text": render("get_player_intelligence", COMPOSITE),
            "outcome": "ok",
            "evidence": deepcopy(BOUNDED_EVIDENCE),
            "routing_trace": {
                "branch": "orchestrator",
                "orchestrator_outcome": "ok",
            },
            "tokens": {"total": 0},
        }
    return {
        "selected_tool": "get_current_gameweek",
        "answer_text": "unused controlled non-FI text",
        "outcome": "ok",
        "routing_trace": {"branch": "orchestrator", "orchestrator_outcome": "ok"},
    }


def _create_session(client: TestClient) -> str:
    response = client.post("/session")
    assert response.status_code == 200
    return response.json()["session_id"]


def test_f2_scenario_a_real_session_has_only_top_level_fi_evidence(monkeypatch):
    monkeypatch.setattr("fpl_grounded_assistant.harness.ask_v2", _controlled_ask_v2)
    client = TestClient(fpl_server.app)
    session_id = _create_session(client)

    first = client.post(
        f"/session/{session_id}/ask",
        json={"question": "player intelligence for Saka"},
    )
    second = client.post(
        f"/session/{session_id}/ask",
        json={"question": "player intelligence for Saka"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["evidence"] == BOUNDED_EVIDENCE
    assert body.get("sub_responses") in (None, [])
    assert second.json()["evidence"] == body["evidence"]
    assert isinstance(body["evidence"][0]["subject_type"], str)
    assert isinstance(body["evidence"][0]["source_features"], list)
    assert len(body["evidence"]) == 8


def test_f2_scenario_b_real_session_keeps_evidence_on_fi_child_only(monkeypatch):
    query = "player intelligence for Saka and what gameweek is it?"
    original_detect = final_response.detect_multi_intent

    def controlled_detect(value: str):
        if value == query:
            return ["player intelligence for Saka", "what gameweek is it?"]
        return original_detect(value)

    monkeypatch.setattr(final_response, "detect_multi_intent", controlled_detect)
    monkeypatch.setattr("fpl_grounded_assistant.harness.ask_v2", _controlled_ask_v2)
    client = TestClient(fpl_server.app)
    session_id = _create_session(client)
    response = client.post(f"/session/{session_id}/ask", json={"question": query})

    assert response.status_code == 200
    body = response.json()
    assert body.get("evidence") is None
    assert len(body["sub_responses"]) == 2
    assert body["sub_responses"][0]["evidence"] == BOUNDED_EVIDENCE
    assert body["sub_responses"][1]["intent"] == "current_gameweek"
    assert "evidence" not in body["sub_responses"][1]


def test_flag_off_does_not_enter_fi_harness(monkeypatch):
    monkeypatch.delenv("FOOTBALL_INTELLIGENCE_ENABLED", raising=False)
    monkeypatch.setattr(
        "fpl_grounded_assistant.harness.ask_v2",
        lambda *args, **kwargs: pytest.fail("FI harness must be unreachable with flag off"),
    )
    response = final_response.respond("what gameweek is it?", STANDARD_BOOTSTRAP)
    assert response.intent == "current_gameweek"
    assert response.evidence is None
