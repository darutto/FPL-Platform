"""Causal FI-7c existing-intent evidence enrichment tests."""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant import existing_intent_evidence as enrichment
from fpl_grounded_assistant import final_response
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.orchestrator import OrchestratorResult


def _evidence(index: int, subject: str = "player") -> dict:
    return {
        "code": "MINUTES_CONFIDENCE_HIGH",
        "label": f"Evidence {index}",
        "subject_type": "player",
        "subject_id": subject,
        "fixture_id": "fixture-1",
        "impact": 1.0,
        "direction": "positive",
        "confidence": 0.8,
        "basis": "observed",
        "summary": f"Signal {index}",
        "source_features": ["m1", "m2", "m3"],
        "model_version": "controlled-v1",
        "calculated_at": "2026-08-01T12:00:00Z",
    }


def _raw(tool: str) -> dict:
    if tool == "get_captain_score":
        return {"status": "ok", "player_id": 3, "web_name": "Saka", "captain_score": 8.0}
    if tool == "compare_players":
        return {
            "status": "ok",
            "player_a": {"player_id": 3, "web_name": "Saka"},
            "player_b": {"player_id": 2, "web_name": "Salah"},
        }
    return {
        "status": "ok",
        "player_out": {"player_id": 3, "web_name": "Saka"},
        "player_in": {"player_id": 2, "web_name": "Salah"},
    }


def _orch(tool: str) -> OrchestratorResult:
    return OrchestratorResult(
        question="controlled",
        tool_chosen=tool,
        tool_args={},
        tool_output=_raw(tool),
        answer_text=f"unchanged {tool}",
        llm_used=True,
        model="controlled",
        outcome="ok",
    )


@pytest.fixture(autouse=True)
def _flags_and_server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FOOTBALL_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    yield
    fpl_server._sessions.clear()


def test_adapter_preserves_player_and_module_order_deduplicates_and_globally_caps(monkeypatch):
    calls: list[str] = []
    first = [_evidence(i, "player-3") for i in range(8)]
    second = [deepcopy(first[0]), _evidence(8, "player-2")]

    def controlled(name, args, bootstrap):
        assert name == "get_player_intelligence"
        calls.append(args["player"])
        return {"status": "ok", "evidence": first if args["player"] == "3" else second}

    monkeypatch.setattr(
        "fpl_grounded_assistant.football_intelligence_runtime.run_football_intelligence_tool",
        controlled,
    )
    result = enrichment.enrich_existing_intent_evidence(
        "compare_players", _raw("compare_players"), STANDARD_BOOTSTRAP
    )
    assert calls == ["3", "2"]
    assert result == first
    assert len(result) == 8
    assert [item["source_features"] for item in result] == [["m1", "m2", "m3"]] * 8


def test_adapter_prefers_id_caches_duplicate_and_uses_fallback_only_when_absent(monkeypatch):
    calls: list[str] = []
    resolver_calls: list[str] = []

    def controlled(name, args, bootstrap):
        calls.append(args["player"])
        return {"status": "ok", "evidence": [_evidence(1, args["player"])]}

    def resolver(query, bootstrap):
        resolver_calls.append(query)
        return {"status": "ok", "player_id": 3}

    monkeypatch.setattr(
        "fpl_grounded_assistant.football_intelligence_runtime.run_football_intelligence_tool",
        controlled,
    )
    monkeypatch.setattr("fpl_tool_contract.tool_resolve_player", resolver)

    duplicate = _raw("compare_players")
    duplicate["player_b"] = {"player_id": 3, "web_name": "ignored"}
    assert enrichment.enrich_existing_intent_evidence(
        "compare_players", duplicate, STANDARD_BOOTSTRAP
    ) == [_evidence(1, "3")]
    assert calls == ["3"]
    assert resolver_calls == []

    calls.clear()
    fallback = _raw("get_transfer_advice")
    fallback["player_out"] = {"web_name": "Saka"}
    enrichment.enrich_existing_intent_evidence(
        "get_transfer_advice", fallback, STANDARD_BOOTSTRAP
    )
    assert resolver_calls == ["Saka"]
    assert calls == ["3", "2"]


def test_adapter_skips_ambiguous_and_failed_player_but_keeps_other_evidence(monkeypatch):
    monkeypatch.setattr(
        "fpl_tool_contract.tool_resolve_player",
        lambda query, bootstrap: {"status": "ambiguous"},
    )
    calls: list[str] = []

    def controlled(name, args, bootstrap):
        calls.append(args["player"])
        return {"status": "partial", "evidence": [_evidence(2, args["player"])]}

    monkeypatch.setattr(
        "fpl_grounded_assistant.football_intelligence_runtime.run_football_intelligence_tool",
        controlled,
    )
    raw = _raw("compare_players")
    raw["player_a"] = {"web_name": "Ambiguous"}
    result = enrichment.enrich_existing_intent_evidence(
        "compare_players", raw, STANDARD_BOOTSTRAP
    )
    assert calls == ["2"]
    assert result == [_evidence(2, "2")]


def test_adapter_contains_runtime_failure_and_rejects_ineligible_or_non_ok(monkeypatch):
    calls: list[str] = []

    def fail_once(name, args, bootstrap):
        calls.append(args["player"])
        raise RuntimeError("controlled")

    monkeypatch.setattr(
        "fpl_grounded_assistant.football_intelligence_runtime.run_football_intelligence_tool",
        fail_once,
    )
    assert enrichment.enrich_existing_intent_evidence(
        "get_captain_score", _raw("get_captain_score"), STANDARD_BOOTSTRAP
    ) is None
    assert enrichment.enrich_existing_intent_evidence(
        "get_player_summary", {"status": "ok"}, STANDARD_BOOTSTRAP
    ) is None
    assert enrichment.enrich_existing_intent_evidence(
        "get_captain_score", {"status": "ambiguous"}, STANDARD_BOOTSTRAP
    ) is None
    duplicate = _raw("compare_players")
    duplicate["player_b"] = {"player_id": 3, "web_name": "Saka"}
    assert enrichment.enrich_existing_intent_evidence(
        "compare_players", duplicate, STANDARD_BOOTSTRAP
    ) is None
    assert calls == ["3", "3"]  # one captain request, one duplicate-player request


@pytest.mark.parametrize(
    "tool", ["get_captain_score", "compare_players", "get_transfer_advice"]
)
def test_stateless_http_ask_copies_only_finalized_evidence(monkeypatch, tool):
    bundle = [_evidence(1, tool)]
    calls: list[str] = []
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: _orch(tool),
    )

    def controlled(selected, raw, bootstrap):
        calls.append(selected)
        return deepcopy(bundle)

    monkeypatch.setattr(enrichment, "enrich_existing_intent_evidence", controlled)
    monkeypatch.setattr(
        "fpl_grounded_assistant.harness.ask_v2",
        lambda question, bootstrap, **kwargs: ask_v2(
            question, bootstrap, orch_client=object(), **kwargs
        ),
    )
    response = TestClient(fpl_server.app).post(
        "/ask",
        json={"question": "controlled"},
        headers={"X-User-Id": f"fi7c-{tool}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["final_text"] == f"unchanged {tool}"
    assert body["outcome"] == "ok"
    assert body["supported"] is True
    assert body["evidence"] == bundle
    assert calls == [tool]


def test_flag_off_keeps_adapter_unreachable_and_evidence_absent(monkeypatch):
    monkeypatch.delenv("FOOTBALL_INTELLIGENCE_ENABLED", raising=False)
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: _orch("get_captain_score"),
    )
    monkeypatch.setattr(
        enrichment,
        "enrich_existing_intent_evidence",
        lambda *args, **kwargs: pytest.fail("adapter must be unreachable with flag OFF"),
    )
    result = ask_v2("controlled", STANDARD_BOOTSTRAP, orch_client=object())
    assert result["answer_text"] == "unchanged get_captain_score"
    assert "evidence" not in result


def test_session_single_intent_attaches_evidence_once_without_changing_response(monkeypatch):
    bundle = [_evidence(3, "captain")]
    calls: list[str] = []
    monkeypatch.setattr(final_response, "_try_football_intelligence_response", lambda *a, **k: None)

    def controlled(tool, raw, bootstrap):
        calls.append(tool)
        return deepcopy(bundle)

    monkeypatch.setattr(enrichment, "enrich_existing_intent_evidence", controlled)
    result = final_response.respond("captain score for Saka", STANDARD_BOOTSTRAP)
    assert result.intent == "captain_score"
    assert result.outcome == "ok"
    assert [item.code for item in result.evidence or ()] == ["MINUTES_CONFIDENCE_HIGH"]
    assert calls == ["get_captain_score"]


def test_multi_intent_keeps_evidence_on_eligible_child_and_never_parent(monkeypatch):
    bundle = [_evidence(4, "captain")]
    monkeypatch.setattr(final_response, "_try_football_intelligence_response", lambda *a, **k: None)
    monkeypatch.setattr(
        enrichment,
        "enrich_existing_intent_evidence",
        lambda tool, raw, bootstrap: deepcopy(bundle) if tool == "get_captain_score" else None,
    )
    result = final_response.respond(
        "captain score for Saka and what gameweek is it?", STANDARD_BOOTSTRAP
    )
    assert result.intent == "multi_intent"
    assert result.evidence is None
    assert len(result.sub_responses or ()) == 2
    assert (result.sub_responses or ())[0].evidence is not None
    assert (result.sub_responses or ())[1].evidence is None


def test_fi_probe_suppresses_existing_intent_enrichment(monkeypatch):
    calls: list[dict] = []

    def controlled_ask_v2(*args, **kwargs):
        calls.append(kwargs)
        return {"selected_tool": "get_captain_score"}

    monkeypatch.setattr("fpl_grounded_assistant.harness.ask_v2", controlled_ask_v2)
    monkeypatch.setattr(
        enrichment,
        "enrich_existing_intent_evidence",
        lambda *args, **kwargs: pytest.fail("FI probe must not enrich existing intent"),
    )
    assert final_response._try_football_intelligence_response(
        "controlled",
        STANDARD_BOOTSTRAP,
        client=object(),
        candidate_inputs=None,
        candidates_list=None,
        api_key=None,
        classifier_client=None,
    ) is None
    assert len(calls) == 1
    assert calls[0]["_enrich_existing_intents"] is False
