"""i102 -- the calendar card reaches the chat over HTTP.

Track D built ``FixtureOutlookMeta`` into ``FinalResponse`` and the UI
(``IntentRenderer`` mounts ``FixtureOutlookCard`` on ``response.fixture_outlook``)
but neither HTTP surface ever carried the field: ``harness_adapter.to_ask_response``
had no ``fixture_outlook=`` line (so ``POST /ask`` dropped it one layer before
``fpl_server``), and ``AskResponse`` / ``SessionAskResponse`` had no such field
(so the session path dropped it too). The compact calendar strip therefore
never rendered in the production chat on ANY get_fixture_outlook turn,
composed (i93) or not.

Two layers, tested separately so a mutation in one is not hidden by the other:

* layer 1 -- the adapter: the ``FixtureOutlookMeta`` on the ask_v2 dict lands
  on the ``AskResponse`` the adapter builds (no HTTP involved);
* layer 2 -- the HTTP contract: that dict reaches the JSON ``POST /ask`` and
  ``POST /session/{id}/ask`` serve, identical on both routes.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [
    _PKG,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

import fpl_server  # noqa: E402
from fpl_grounded_assistant import harness_adapter  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.final_response import FixtureOutlookMeta  # noqa: E402
from fpl_grounded_assistant.harness import ask_v2  # noqa: E402
from fpl_grounded_assistant.harness_adapter import _to_dict  # noqa: E402
from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402
from fpl_server import AskRequest  # noqa: E402

QUESTION = "¿Cómo pinta el calendario del Arsenal las próximas 5 jornadas?"
TOOL = "get_fixture_outlook"


def _outlook_payload() -> dict:
    """A get_fixture_outlook all-teams output with one team, as the tool emits it."""
    def gw(n, band, klass, opp, home, dgw=False):
        return {"gameweek": n, "band": band, "klass": klass, "is_dgw": dgw, "is_bgw": band is None,
                "fixtures": [] if band is None else [{"opponent_short": opp, "is_home": home, "band": band}]}
    return {
        "status": "ok", "axis": "attack", "horizon": 5, "current_gameweek": 5,
        "teams": [{
            "team_short": "ARS", "team_name": "Arsenal", "axis": "attack", "avg_band": 2.25,
            "verdict": "racha favorable J6-J8",
            "series": [gw(5, 3, "neutral", "MCI", False), gw(6, 2, "good", "BUR", True),
                       gw(7, 2, "good", "SUN", False), gw(8, 2, "good", "WOL", True), gw(9, None, "blank", "", False)],
            "runs": [{"type": "good", "start_gw": 6, "end_gw": 8, "length": 3, "intensity": "mild"}],
        }],
    }


def _outlook_result(payload: dict) -> OrchestratorResult:
    return OrchestratorResult(
        question=QUESTION,
        tool_chosen=TOOL,
        tool_args={"team_query": "Arsenal", "axis": "attack", "horizon": 5},
        tool_output=payload,
        answer_text="El Arsenal tiene una racha favorable J6-J8.",
        llm_used=True,
        model="stub-model",
        outcome=OUTCOME_OK,
        primary_input_tokens=900, primary_output_tokens=120, total_tokens=1020,
        tool_call_count=1,
        tool_calls_trace=({"round": 1, "tool_call_id": "call_0", "name": TOOL,
                           "args": {"team_query": "Arsenal", "axis": "attack", "horizon": 5},
                           "output": payload, "success": True},),
        synthesis_turn=True,
    )


@pytest.fixture
def stub_outlook_orchestrator(monkeypatch: pytest.MonkeyPatch):
    result = _outlook_result(_outlook_payload())
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    return result


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


# ---------------------------------------------------------------------------
# Layer 1 -- the adapter (no HTTP)
# ---------------------------------------------------------------------------

def test_adapter_carries_fixture_outlook_from_the_ask_v2_dict(stub_outlook_orchestrator):
    out = ask_v2(QUESTION, STANDARD_BOOTSTRAP)
    assert isinstance(out["fixture_outlook"], FixtureOutlookMeta), "precondition: i93/Track D build the meta"
    resp = harness_adapter.to_ask_response(out, AskRequest(question=QUESTION))
    assert resp.intent == "fixture_outlook"
    assert resp.fixture_outlook == _to_dict(out["fixture_outlook"])
    assert resp.fixture_outlook["teams"][0]["team_short"] == "ARS"
    assert [g["gameweek"] for g in resp.fixture_outlook["teams"][0]["series"]] == [5, 6, 7, 8, 9]


def test_adapter_leaves_fixture_outlook_null_on_other_turns(stub_outlook_orchestrator, monkeypatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    out = ask_v2("@gameweek", STANDARD_BOOTSTRAP)   # deterministic branch, no calendar
    resp = harness_adapter.to_ask_response(out, AskRequest(question="@gameweek"))
    assert resp.fixture_outlook is None


# ---------------------------------------------------------------------------
# Layer 2 -- the HTTP contract, both routes
# ---------------------------------------------------------------------------

def _expected() -> dict:
    out = ask_v2(QUESTION, STANDARD_BOOTSTRAP)
    return _to_dict(out["fixture_outlook"])


def test_post_ask_serves_fixture_outlook(server, stub_outlook_orchestrator):
    body = server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i102-ask"}).json()
    assert body["intent"] == "fixture_outlook"
    assert body["fixture_outlook"] == _expected()
    assert body["fixture_outlook"]["axis"] == "attack" and body["fixture_outlook"]["horizon"] == 5


def test_post_session_ask_serves_fixture_outlook(server, stub_outlook_orchestrator):
    sid = server.post("/session").json()["session_id"]
    body = server.post(f"/session/{sid}/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i102-sess"}).json()
    assert body["intent"] == "fixture_outlook"
    assert body["fixture_outlook"] == _expected()


def test_both_routes_serve_the_identical_calendar_payload(server, stub_outlook_orchestrator):
    ask = server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i102-a"}).json()
    sid = server.post("/session").json()["session_id"]
    sess = server.post(f"/session/{sid}/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i102-s"}).json()
    assert ask["fixture_outlook"] is not None
    assert ask["fixture_outlook"] == sess["fixture_outlook"]


def test_http_models_declare_the_field():
    assert "fixture_outlook" in fpl_server.AskResponse.model_fields
    assert "fixture_outlook" in fpl_server.SessionAskResponse.model_fields
