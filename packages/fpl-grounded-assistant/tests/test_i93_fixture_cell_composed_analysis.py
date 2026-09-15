"""
i93 (i78-B) -- the /fixtures cell tap composes calendar + players in ONE
round, keeps its calendar card, and never talks buy/sell.

Layers, each asserted from what was produced:

* orchestrator -- a model response with TWO tool_use blocks in the
  adversarial order (get_team_snapshot FIRST, get_fixture_outlook second)
  executes both in the single-round path (no loop), records both in
  ``tool_calls_trace``, and hands BOTH outputs to the synthesis call;
* harness      -- the singular slot of that composed turn is the CALENDAR
  call (selected_tool / tool_input / raw_output), so ``fixture_outlook`` is
  populated and the adapter's intent is ``fixture_outlook`` -- the exact
  condition the UI renders ``FixtureOutlookCard`` on;
* framing      -- ``opportunity_framing.transaction_hits`` catches a
  synthesis text that uses the forbidden vocabulary, and does not flag
  honest match prose; the system prompt carries the MATCH_COMPOSITION rule;
* catalog      -- get_fixture_outlook instructs the parallel snapshot call
  without touching the i101 target_gw instruction.

Deterministic: fake provider clients only, no network.
"""
from __future__ import annotations

import json
import os as _os
import sys as _sys
from types import SimpleNamespace as NS

import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant import harness, harness_adapter, provider_client  # noqa: E402
from fpl_grounded_assistant.final_response import (  # noqa: E402
    COMPOSITION_PRIMARY_TOOLS,
    composed_primary_call,
)
from fpl_grounded_assistant.opportunity_framing import (  # noqa: E402
    TRANSACTION_STEMS,
    obeys_opportunity_framing,
    transaction_hits,
)
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_OK,
    PROVIDER_OPENAI,
    _SYSTEM_PROMPT,
    ask_orchestrated,
)
from fpl_grounded_assistant.tool_schema_registry import get_tool_schema  # noqa: E402

QUESTION = "Arsenal vs BHA (a domicilio), J5: ¿qué tal pinta ofensivamente para el Arsenal?"
SYNTHESIS = (
    "J5: Arsenal a domicilio ante Brighton — dificultad ofensiva 3/5 (media); "
    "ventaja Arsenal. Oportunidad: Saka (forma 7.5, xG 2.88) y Ødegaard (xA 1.3) "
    "llegan finos a este cruce."
)


# ---------------------------------------------------------------------------
# Bootstrap: two teams, six Arsenal players, current GW 4, fixtures J4..J6
# ---------------------------------------------------------------------------

def _el(pid: int, name: str, team: int, etype: int, pts: int, form: float, xg: float, xa: float) -> dict:
    return {"id": pid, "web_name": name, "first_name": name, "second_name": name, "team": team,
            "element_type": etype, "total_points": pts, "form": str(form),
            "expected_goals": str(xg), "expected_assists": str(xa), "minutes": 300,
            "status": "a", "news": "", "now_cost": 80, "ict_index": "20.0",
            "selected_by_percent": "10.0", "points_per_game": str(pts / 4)}


def _fx(gw: int, opp: int, is_home: bool, difficulty: int) -> dict:
    return {"gameweek": gw, "opponent_team": opp, "is_home": is_home, "difficulty": difficulty}


def _bootstrap() -> dict:
    return {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS", "strength_overall_home": 5, "strength_overall_away": 5},
            {"id": 2, "name": "Brighton", "short_name": "BHA", "strength_overall_home": 2, "strength_overall_away": 2},
        ],
        "element_types": [{"id": 1, "singular_name_short": "GKP"}, {"id": 2, "singular_name_short": "DEF"},
                          {"id": 3, "singular_name_short": "MID"}, {"id": 4, "singular_name_short": "FWD"}],
        "elements": [
            _el(1, "Saka", 1, 3, 30, 7.5, 2.88, 0.43),
            _el(2, "Raya", 1, 1, 29, 7.2, 0.0, 0.01),
            _el(3, "Calafiori", 1, 2, 28, 7.0, 0.6, 0.59),
            _el(4, "Ødegaard", 1, 3, 27, 6.8, 1.01, 1.3),
            _el(5, "Gabriel", 1, 2, 24, 6.0, 0.51, 0.06),
            _el(6, "Havertz", 1, 4, 20, 5.0, 1.9, 0.2),
            _el(7, "Mitoma", 2, 3, 22, 5.5, 1.1, 0.7),
        ],
        "events": [{"id": 4, "is_current": True, "is_next": False, "finished": False},
                   {"id": 5, "is_current": False, "is_next": True, "finished": False}],
        "team_fixtures": {
            1: [_fx(4, 2, True, 2), _fx(5, 2, False, 3), _fx(6, 2, True, 2)],
            2: [_fx(4, 1, False, 4), _fx(5, 1, True, 4), _fx(6, 1, False, 4)],
        },
        # get_team_snapshot reads upcoming fixtures from this injection
        # instead of the network.
        "_gw_fixtures": {
            "5": [{"event": 5, "team_h": 2, "team_a": 1, "team_h_difficulty": 4, "team_a_difficulty": 3,
                   "finished": False, "kickoff_time": "2026-09-20T14:00:00Z"}],
            "6": [{"event": 6, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4,
                   "finished": False, "kickoff_time": "2026-09-27T14:00:00Z"}],
        },
    }


# ---------------------------------------------------------------------------
# Fake OpenAI client: round 1 = TWO function calls, snapshot FIRST; round 2 = text
# ---------------------------------------------------------------------------

def _two_tool_response(order: tuple[str, str]) -> object:
    calls = {
        "get_team_snapshot": NS(type="function_call", call_id="oai-snap", name="get_team_snapshot",
                                arguments=json.dumps({"team_name": "Arsenal", "top_n_players": 5})),
        "get_fixture_outlook": NS(type="function_call", call_id="oai-out", name="get_fixture_outlook",
                                  arguments=json.dumps({"axis": "attack", "team_query": "Arsenal", "target_gw": 5})),
    }
    return NS(output=[NS(type="reasoning", id="r-1"), calls[order[0]], calls[order[1]]], output_text="")


def _text_response(text: str) -> object:
    return NS(output_text="", output=[NS(type="message", content=[NS(type="output_text", text=text)])])


class _Client:
    def __init__(self, responses: list[object]) -> None:
        self.responses = self
        self.queue = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.queue.pop(0)


@pytest.fixture(autouse=True)
def _single_round(monkeypatch):
    """Prod shape: the loop is OFF (i57: /healthz loop_enabled=false)."""
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)


def _run_composed(order=("get_team_snapshot", "get_fixture_outlook"), synthesis=SYNTHESIS):
    client = _Client([_two_tool_response(order), _text_response(synthesis)])
    result = ask_orchestrated(QUESTION, _bootstrap(), provider=PROVIDER_OPENAI, client=client,
                              api_key="test-key", _eval_client=None)
    return result, client


# ---------------------------------------------------------------------------
# Orchestrator: both tools run in one round, both outputs reach the synthesis
# ---------------------------------------------------------------------------

def test_two_tools_in_one_response_both_execute_without_the_loop():
    result, client = _run_composed()
    assert result.outcome == OUTCOME_OK
    assert [e["name"] for e in result.tool_calls_trace] == ["get_team_snapshot", "get_fixture_outlook"]
    assert [e["round"] for e in result.tool_calls_trace] == [1, 1]
    assert result.tool_call_count == 2
    assert len(client.calls) == 2  # one tool round + one synthesis call, no third
    # Both outputs are real tool executions, not stubs.
    snap, outlook = (e["output"] for e in result.tool_calls_trace)
    assert [p["web_name"] for p in snap["top_players"]][:2] == ["Saka", "Raya"]
    assert outlook["status"] == "ok" and outlook["verdict_scope"] == "match"
    assert [g["gameweek"] for g in outlook["series"]] == [5]


def test_synthesis_call_receives_both_tool_outputs():
    _result, client = _run_composed()
    follow_up = json.dumps(client.calls[1].get("input") or client.calls[1].get("messages"), default=str)
    assert "Saka" in follow_up and "top_players" in follow_up      # snapshot payload
    assert "verdict_scope" in follow_up and "series" in follow_up  # outlook payload


def test_orchestrator_singular_slot_is_still_the_first_call():
    """Pinned: the orchestrator itself keeps executed[0]. The composition fix
    lives one layer up (harness), so this contract stays byte-identical for
    every other multi-tool turn."""
    result, _client = _run_composed()
    assert result.tool_chosen == "get_team_snapshot"
    assert result.tool_output == result.tool_calls_trace[0]["output"]


# ---------------------------------------------------------------------------
# composed_primary_call
# ---------------------------------------------------------------------------

def _t(name: str, success: bool = True, tag: str = "") -> dict:
    return {"round": 1, "tool_call_id": tag or name, "name": name, "args": {},
            "output": {"status": "ok" if success else "error", "tag": tag}, "success": success}


def test_primary_is_the_calendar_call_whatever_the_order():
    assert composed_primary_call([_t("get_team_snapshot"), _t("get_fixture_outlook")])["name"] == "get_fixture_outlook"
    assert composed_primary_call([_t("get_fixture_outlook"), _t("get_team_snapshot")])["name"] == "get_fixture_outlook"


def test_primary_is_none_for_single_tool_and_for_multi_tool_without_a_primary():
    assert composed_primary_call([_t("get_fixture_outlook")]) is None
    assert composed_primary_call([_t("get_fixture_outlook"), _t("get_fixture_outlook", tag="2")]) is None
    assert composed_primary_call([_t("get_team_snapshot"), _t("get_player_snapshot")]) is None
    assert composed_primary_call([]) is None
    assert composed_primary_call(None) is None


def test_primary_prefers_the_last_successful_calendar_call():
    trace = [_t("get_team_snapshot"), _t("get_fixture_outlook", success=False, tag="bad"),
             _t("get_fixture_outlook", tag="good")]
    assert composed_primary_call(trace)["output"]["tag"] == "good"
    only_bad = [_t("get_team_snapshot"), _t("get_fixture_outlook", success=False, tag="bad")]
    assert composed_primary_call(only_bad)["output"]["tag"] == "bad"


def test_primary_tools_set_is_exactly_the_calendar_tool():
    assert COMPOSITION_PRIMARY_TOOLS == frozenset({"get_fixture_outlook"})


# ---------------------------------------------------------------------------
# Harness: the composed turn keeps its calendar card
# ---------------------------------------------------------------------------

def _ask_v2_with(monkeypatch, orch_result):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch_result)
    return harness.ask_v2(QUESTION, _bootstrap(), orch_client=object())


def test_composed_turn_snapshot_first_keeps_the_calendar_card(monkeypatch):
    orch_result, _client = _run_composed(order=("get_team_snapshot", "get_fixture_outlook"))
    out = _ask_v2_with(monkeypatch, orch_result)
    assert out["selected_tool"] == "get_fixture_outlook"
    assert out["tool_input"] == {"axis": "attack", "team_query": "Arsenal", "target_gw": 5}
    assert out["raw_output"]["verdict_scope"] == "match"
    assert out["fixture_outlook"] is not None
    assert [t.team_short for t in out["fixture_outlook"].teams] == ["ARS"]
    assert out["routing_trace"]["tool_sequence"] == ["get_team_snapshot", "get_fixture_outlook"]
    assert out["routing_trace"]["composed_primary_tool"] == "get_fixture_outlook"
    assert out["answer_text"] == SYNTHESIS
    # The UI renders FixtureOutlookCard on intent == fixture_outlook AND a
    # non-empty fixture_outlook; the intent half is decided here, from the
    # primary call. (The other half -- fpl_server.AskResponse carrying
    # fixture_outlook at all -- is NOT wired today, for single-tool turns
    # either: found while building i93, reported as its own card.)
    from fpl_server import AskRequest
    resp = harness_adapter.to_ask_response(out, AskRequest(question=QUESTION))
    assert resp.intent == "fixture_outlook"
    # A composed turn is a real multi-tool turn: no atomic card on top (i58 gate).
    assert out.get("generic_card") is None


def test_composed_turn_calendar_first_is_unchanged(monkeypatch):
    orch_result, _client = _run_composed(order=("get_fixture_outlook", "get_team_snapshot"))
    out = _ask_v2_with(monkeypatch, orch_result)
    assert out["selected_tool"] == "get_fixture_outlook"
    assert out["fixture_outlook"] is not None
    assert out["routing_trace"]["composed_primary_tool"] == "get_fixture_outlook"


def test_non_composed_multi_tool_turn_keeps_the_orchestrator_slot(monkeypatch):
    """Two tools, neither a composition primary: the slot stays executed[0]
    (no behaviour change for every other multi-tool turn)."""
    from fpl_grounded_assistant.orchestrator import OrchestratorResult
    trace = (_t("get_team_snapshot"), _t("get_player_snapshot"))
    orch_result = OrchestratorResult(
        question=QUESTION, tool_chosen="get_team_snapshot", tool_args={"team_name": "Arsenal"},
        tool_output=trace[0]["output"], answer_text="x", llm_used=True, model="m",
        outcome=OUTCOME_OK, tool_call_count=2, tool_calls_trace=trace, synthesis_turn=True,
    )
    out = _ask_v2_with(monkeypatch, orch_result)
    assert out["selected_tool"] == "get_team_snapshot"
    assert "composed_primary_tool" not in out["routing_trace"]


# ---------------------------------------------------------------------------
# Framing: the rule is checkable on the produced text
# ---------------------------------------------------------------------------

def test_honest_match_prose_is_not_flagged():
    assert transaction_hits(SYNTHESIS) == []
    assert obeys_opportunity_framing(
        "Hay que comprobar si Ødegaard está comprometido con el cruce; ventaja Arsenal."
    )


@pytest.mark.parametrize("text, stem", [
    ("Cómpralo esta semana, es urgente", "compra"),
    ("Deberías vender a Raya", "vend"),
    ("Ficha a Saka antes del deadline", "ficha"),
    ("Traspásalo ya", "traspas"),
    ("Peligro: Brighton concede poco", "peligr"),
    ("Buy Saka, sell Raya", "buy"),
    ("Bring in Havertz", "bring in"),
])
def test_forbidden_vocabulary_is_caught(text, stem):
    hits = transaction_hits(text)
    assert hits, text
    assert any(h.startswith(stem + ":") for h in hits), hits
    assert not obeys_opportunity_framing(text)


def test_a_synthesis_that_breaks_the_rule_is_detected_end_to_end():
    """The check runs on the answer_text the orchestrator actually produced,
    not on the instruction: a model that ignores MATCH_COMPOSITION is caught."""
    bad = "Saka (forma 7.5) es una oportunidad: cómpralo y vende a Raya antes de la J5."
    result, _client = _run_composed(synthesis=bad)
    assert result.answer_text == bad
    assert transaction_hits(result.answer_text) == ["compra:compralo", "vend:vende"]


def test_transaction_stems_stay_a_closed_denylist():
    assert "compr" not in TRANSACTION_STEMS and "fich" not in TRANSACTION_STEMS
    assert {"compra", "vend", "ficha", "traspas", "peligr", "urgent", "buy", "sell"} <= set(TRANSACTION_STEMS)


def test_system_prompt_carries_the_composition_rule():
    assert "MATCH_COMPOSITION" in _SYSTEM_PROMPT
    assert "get_fixture_outlook AND get_team_snapshot" in _SYSTEM_PROMPT
    assert "2-3 of that team's top_players" in _SYSTEM_PROMPT
    assert "comprar/vender/fichar/traspasar/urgente/peligro" in _SYSTEM_PROMPT
    # Untouched neighbours the loop prompt derives from.
    assert "single_source_per_turn" in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def test_catalog_instructs_the_parallel_snapshot_call_and_keeps_target_gw():
    desc = get_tool_schema("get_fixture_outlook").description
    assert "ALSO call get_team_snapshot(team_name=<the same team>, top_n_players=5) in the SAME response" in desc
    assert "never invent a name or a stat" in desc
    assert "never as buy/sell/transfer advice" in desc
    # i101's instruction is intact, not rewritten.
    assert "pass target_gw=5" in desc and "Do NOT compute horizon" in desc
    snap = get_tool_schema("get_team_snapshot").description
    assert "Pairs with get_fixture_outlook for a ONE MATCH question" in snap
