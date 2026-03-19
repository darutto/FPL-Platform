"""
run_phase5l_tests.py
====================
Phase 5l: Session Inspect Audit Snapshot.

Validates that GET /session/{id} now exposes a bounded operational summary
of recent session activity:

    last_intent          -- intent of the most recent turn (or None)
    last_player          -- last resolved single-player query (or None)
    last_comparison      -- {"player_a": ..., "player_b": ...} from the last
                           successful comparison turn (or None)
    last_resolver_source -- resolver path from the most recent turn, using the
                           same five-value vocabulary as ResolverDebug.resolver_source

These fields are additive and Optional (default None).  All prior inspect
fields are unchanged.  All ask-flow responses (stateless and session) are
unchanged.  Comparison scoring and routing are unchanged.

All tests are deterministic -- no live ANTHROPIC_API_KEY required.
The Phase 5f LLM comparison path is exercised via a lightweight mock client.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5l_tests.py

Sections
--------
A  -- Module shape: SessionInfoResponse has 4 new optional fields
B  -- Fresh session (0 turns): all new fields are None
C  -- After single player turn: last_intent, last_player, last_resolver_source populated
D  -- After direct comparison: last_intent, last_comparison, last_resolver_source="none"
E  -- After Phase 5c det. follow-up: last_resolver_source="comparison_followup"
F  -- After Phase 5f LLM follow-up: last_resolver_source="comparison_followup_llm"
G  -- last_comparison cleared after non-comparison turn
H  -- Boundedness: no history blob, turn transcript, or unbounded debug in inspect
I  -- Regression: ask responses, prior inspect fields, comparison output unchanged
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
_SIB  = lambda name: os.path.join(_PKGS, name)

for _pkg in [
    _HERE,
    _SIB("fpl-api-client"),
    _SIB("fpl-data-core"),
    _SIB("fpl-player-registry"),
    _SIB("fpl-query-tools"),
    _SIB("fpl-tool-contract"),
    _SIB("fpl-tool-runner"),
    _SIB("fpl-captain-engine"),
    _SIB("fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

_passed = 0
_failed = 0


def ok(label: str, expr: bool) -> None:
    global _passed, _failed
    if expr:
        _passed += 1
    else:
        _failed += 1
        print(f"FAIL  {label}")


def eq(label: str, got: object, want: object) -> None:
    if got != want:
        print(f"FAIL  {label}  got={got!r}  want={want!r}")
    ok(label, got == want)


from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    OUTCOME_OK,
    INTENT_COMPARE_PLAYERS,
    ConversationSession,
    ConversationState,
)

import fpl_server
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock LLM client  (same pattern as run_phase5f/5k_tests.py)
# ---------------------------------------------------------------------------

class _MockContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _MockMessage:
    def __init__(self, text: str) -> None:
        self.content = [_MockContent(text)]


class _MockMessages:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    def create(self, **kwargs):
        return _MockMessage(self._response_text)


class _MockClient:
    def __init__(self, response_json: str) -> None:
        self.messages = _MockMessages(response_json)


def _comp_json(is_followup: bool, new_player, confidence: float = 0.9, language: str = "en") -> str:
    return json.dumps({
        "is_comparison_followup": is_followup,
        "new_player": new_player,
        "confidence": confidence,
        "language": language,
    })


# ---------------------------------------------------------------------------
# Shared test client
# ---------------------------------------------------------------------------

_client = TestClient(fpl_server.app, raise_server_exceptions=True)


def _create_session() -> str:
    r = _client.post("/session")
    assert r.status_code == 200
    return r.json()["session_id"]


def _ask(sid: str, question: str, debug: bool = False) -> dict:
    r = _client.post(f"/session/{sid}/ask", json={"question": question, "debug": debug})
    assert r.status_code == 200, f"ask failed: {r.status_code} {r.text}"
    return r.json()


def _inspect(sid: str) -> dict:
    r = _client.get(f"/session/{sid}")
    assert r.status_code == 200, f"inspect failed: {r.status_code} {r.text}"
    return r.json()


# ===========================================================================
# Section A -- Module shape: SessionInfoResponse has new fields
# ===========================================================================

print("A  Module shape: SessionInfoResponse has 4 new optional fields")

from fpl_server import SessionInfoResponse

_a_info = SessionInfoResponse(
    session_id="test", created_at=0.0, last_used_at=0.0, turn_count=0
)
ok("A1  SessionInfoResponse is constructable with just base fields", True)
ok("A2  last_intent defaults to None",         _a_info.last_intent is None)
ok("A3  last_player defaults to None",         _a_info.last_player is None)
ok("A4  last_comparison defaults to None",     _a_info.last_comparison is None)
ok("A5  last_resolver_source defaults to None", _a_info.last_resolver_source is None)

_a_info_full = SessionInfoResponse(
    session_id="t", created_at=0.0, last_used_at=0.0, turn_count=1,
    last_intent="captain_score", last_player="Haaland",
    last_comparison=None, last_resolver_source="none",
)
eq("A6  last_intent writable",          _a_info_full.last_intent, "captain_score")
eq("A7  last_player writable",          _a_info_full.last_player, "Haaland")
eq("A8  last_resolver_source writable", _a_info_full.last_resolver_source, "none")


# ===========================================================================
# Section B -- Fresh session (0 turns): all new fields are None
# ===========================================================================

print("B  Fresh session: all new inspect fields are None")

fpl_server._clear_sessions()
_b_sid = _create_session()
_b_info = _inspect(_b_sid)

eq("B1  turn_count is 0",                   _b_info["turn_count"], 0)
eq("B2  last_intent is null",               _b_info.get("last_intent"), None)
eq("B3  last_player is null",               _b_info.get("last_player"), None)
eq("B4  last_comparison is null",           _b_info.get("last_comparison"), None)
eq("B5  last_resolver_source is null",      _b_info.get("last_resolver_source"), None)
# Base fields still present
ok("B6  session_id present",                "session_id" in _b_info)
ok("B7  created_at present",               "created_at" in _b_info)
ok("B8  last_used_at present",             "last_used_at" in _b_info)


# ===========================================================================
# Section C -- After single player turn: last_intent + last_player populated
# ===========================================================================

print("C  After single player turn: last_intent, last_player, last_resolver_source set")

fpl_server._clear_sessions()
_c_sid = _create_session()
_ask(_c_sid, "should I captain Haaland")
_c_info = _inspect(_c_sid)

eq("C1  turn_count is 1",                   _c_info["turn_count"], 1)
ok("C2  last_intent is set",                _c_info.get("last_intent") is not None)
eq("C3  last_intent is captain_score",      _c_info.get("last_intent"), "captain_score")
ok("C4  last_player contains Haaland",      "Haaland" in (_c_info.get("last_player") or ""))
eq("C5  last_comparison is null",           _c_info.get("last_comparison"), None)
eq("C6  last_resolver_source is none",      _c_info.get("last_resolver_source"), "none")


# ===========================================================================
# Section D -- After direct comparison: last_comparison, last_resolver_source="none"
# ===========================================================================

print("D  After direct comparison: last_comparison populated, last_resolver_source=\"none\"")

fpl_server._clear_sessions()
_d_sid = _create_session()
_ask(_d_sid, "compare Haaland and Salah")
_d_info = _inspect(_d_sid)

eq("D1  turn_count is 1",                   _d_info["turn_count"], 1)
eq("D2  last_intent is compare_players",    _d_info.get("last_intent"), "compare_players")
ok("D3  last_comparison is not null",       _d_info.get("last_comparison") is not None)
eq("D4  last_comparison player_a",         _d_info["last_comparison"].get("player_a"), "Haaland")
eq("D5  last_comparison player_b",         _d_info["last_comparison"].get("player_b"), "Salah")
eq("D6  last_resolver_source is none",     _d_info.get("last_resolver_source"), "none")
eq("D7  last_comparison has exactly 2 keys",
   set(_d_info["last_comparison"].keys()), {"player_a", "player_b"})


# ===========================================================================
# Section E -- After Phase 5c det. follow-up: last_resolver_source="comparison_followup"
# ===========================================================================

print("E  Phase 5c det. follow-up: last_resolver_source=\"comparison_followup\"")

fpl_server._clear_sessions()
_e_sid = _create_session()
_ask(_e_sid, "compare Haaland and Salah")
_ask(_e_sid, "And Saka?")
_e_info = _inspect(_e_sid)

eq("E1  turn_count is 2",                          _e_info["turn_count"], 2)
eq("E2  last_intent still compare_players",        _e_info.get("last_intent"), "compare_players")
ok("E3  last_comparison updated after follow-up",  _e_info.get("last_comparison") is not None)
eq("E4  last_comparison player_a still Haaland",   _e_info["last_comparison"]["player_a"], "Haaland")
ok("E5  last_comparison player_b contains Saka",
   "Saka" in (_e_info["last_comparison"].get("player_b") or ""))
eq("E6  last_resolver_source comparison_followup",
   _e_info.get("last_resolver_source"), "comparison_followup")

# "What about X?" also Phase 5c
fpl_server._clear_sessions()
_e2_sid = _create_session()
_ask(_e2_sid, "compare Haaland and Salah")
_ask(_e2_sid, "What about Palmer?")
_e2_info = _inspect(_e2_sid)
eq("E7  'What about X?' resolver_source comparison_followup",
   _e2_info.get("last_resolver_source"), "comparison_followup")


# ===========================================================================
# Section F -- After Phase 5f LLM follow-up: last_resolver_source="comparison_followup_llm"
# ===========================================================================

print("F  Phase 5f LLM follow-up: last_resolver_source=\"comparison_followup_llm\"")

# Phase 5f LLM follow-up goes through ConversationSession.respond() with resolver_client.
# The HTTP endpoint doesn't accept resolver_client, so we test via ConversationSession directly
# and verify ConversationState tracks the correct source.

_f_sess = ConversationSession()
_f_sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_f_mock = _MockClient(_comp_json(True, "Saka", confidence=0.95, language="es"))
_f_sess.respond("¿Y Saka?", STANDARD_BOOTSTRAP, resolver_client=_f_mock)

_f_state = _f_sess.state
eq("F1  last_resolver_source comparison_followup_llm",
   _f_state.last_resolver_source, "comparison_followup_llm")
eq("F2  last_intent compare_players (from history)",
   _f_state.history[-1][1], "compare_players")
ok("F3  last_comparison set after LLM follow-up", _f_state.last_comparison is not None)
eq("F4  last_comparison player_a Haaland",        _f_state.last_comparison[0], "Haaland")
ok("F5  last_comparison player_b contains Saka",
   "Saka" in (_f_state.last_comparison[1] or ""))

# "vs Palmer" variant
_f_sess2 = ConversationSession()
_f_sess2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_f_sess2.respond(
    "vs Palmer", STANDARD_BOOTSTRAP,
    resolver_client=_MockClient(_comp_json(True, "Palmer", confidence=0.88)),
)
eq("F6  'vs Palmer' resolver_source comparison_followup_llm",
   _f_sess2.state.last_resolver_source, "comparison_followup_llm")


# ===========================================================================
# Section G -- last_comparison cleared after non-comparison turn
# ===========================================================================

print("G  last_comparison cleared after non-comparison turn")

fpl_server._clear_sessions()
_g_sid = _create_session()
_ask(_g_sid, "compare Haaland and Salah")
_g_after_comp = _inspect(_g_sid)
ok("G1  last_comparison set after comparison",  _g_after_comp.get("last_comparison") is not None)

_ask(_g_sid, "should I captain Salah")
_g_after_player = _inspect(_g_sid)
eq("G2  last_comparison null after player turn", _g_after_player.get("last_comparison"), None)
eq("G3  last_intent updated to captain_score",   _g_after_player.get("last_intent"), "captain_score")
ok("G4  last_player set after player turn",      _g_after_player.get("last_player") is not None)
eq("G5  last_resolver_source none (direct player query)",
   _g_after_player.get("last_resolver_source"), "none")
eq("G6  turn_count is 2",                        _g_after_player["turn_count"], 2)


# ===========================================================================
# Section H -- Boundedness: inspect exposes summary, not full transcript
# ===========================================================================

print("H  Boundedness: inspect is summary only, no full transcript or debug blob")

fpl_server._clear_sessions()
_h_sid = _create_session()
_ask(_h_sid, "should I captain Haaland")
_ask(_h_sid, "should I captain Salah")
_ask(_h_sid, "compare Haaland and Salah")
_h_info = _inspect(_h_sid)

# Inspect returns a fixed, bounded set of keys — no unbounded transcript or debug
_h_keys = set(_h_info.keys())
_h_expected_keys = {
    "session_id", "created_at", "last_used_at", "turn_count",
    "last_intent", "last_player", "last_comparison", "last_resolver_source",
}
ok("H1  inspect keys match expected bounded set", _h_keys == _h_expected_keys)
ok("H2  no 'history' key in inspect",             "history" not in _h_keys)
ok("H3  no 'debug' key in inspect",               "debug" not in _h_keys)
ok("H4  no 'turns' key in inspect",               "turns" not in _h_keys)
ok("H5  no 'questions' key in inspect",           "questions" not in _h_keys)

# last_comparison dict has exactly 2 keys (player_a, player_b)
ok("H6  last_comparison is a dict with 2 keys",
   isinstance(_h_info.get("last_comparison"), dict)
   and set(_h_info["last_comparison"].keys()) == {"player_a", "player_b"})

eq("H7  turn_count correct after 3 turns",        _h_info["turn_count"], 3)


# ===========================================================================
# Section I -- Regression: ask responses and prior inspect fields unchanged
# ===========================================================================

print("I  Regression: ask responses and prior inspect fields unchanged")

fpl_server._clear_sessions()
_i_sid = _create_session()

# Stateless /ask response unchanged
_i_ask_r = _client.post("/ask", json={"question": "should I captain Haaland"})
eq("I1  stateless ask status 200",         _i_ask_r.status_code, 200)
_i_ask_body = _i_ask_r.json()
ok("I2  stateless ask has final_text",     "final_text" in _i_ask_body)
ok("I3  stateless ask has outcome",        "outcome" in _i_ask_body)
ok("I4  stateless ask has no last_intent", "last_intent" not in _i_ask_body)

# Session /ask response unchanged
_i_sess_r = _client.post(f"/session/{_i_sid}/ask", json={"question": "should I captain Haaland"})
eq("I5  session ask status 200",           _i_sess_r.status_code, 200)
_i_sess_body = _i_sess_r.json()
ok("I6  session ask has final_text",       "final_text" in _i_sess_body)
ok("I7  session ask has session_id",       "session_id" in _i_sess_body)
ok("I8  session ask has no last_intent",   "last_intent" not in _i_sess_body)
ok("I9  session ask debug is None by default", _i_sess_body.get("debug") is None)

# Comparison ask response unchanged
_i_comp_r = _client.post(f"/session/{_i_sid}/ask", json={"question": "compare Haaland and Salah"})
eq("I10 comparison ask status 200",        _i_comp_r.status_code, 200)
_i_comp_body = _i_comp_r.json()
ok("I11 comparison ask has comparison key", "comparison" in _i_comp_body)
ok("I12 comparison field not None",        _i_comp_body.get("comparison") is not None)
ok("I13 comparison has winner key",        "winner" in (_i_comp_body.get("comparison") or {}))

# Prior inspect fields still present and correct
_i_inspect = _inspect(_i_sid)
ok("I14 session_id in inspect",            "session_id" in _i_inspect)
ok("I15 created_at in inspect",            "created_at" in _i_inspect)
ok("I16 last_used_at in inspect",          "last_used_at" in _i_inspect)
ok("I17 turn_count in inspect",            "turn_count" in _i_inspect)
eq("I18 turn_count correct",              _i_inspect["turn_count"], 2)

# Comparison session flow: ComparisonMeta shape unchanged
_i_sess2 = ConversationSession()
_i_r = _i_sess2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("I19 comparison outcome ok",           _i_r.outcome, OUTCOME_OK)
ok("I20 comparison is not None",          _i_r.comparison is not None)
ok("I21 comparison has winner",           hasattr(_i_r.comparison, "winner"))
ok("I22 comparison has margin",           hasattr(_i_r.comparison, "margin"))
ok("I23 comparison has label",            hasattr(_i_r.comparison, "label"))
ok("I24 comparison has reasons",          hasattr(_i_r.comparison, "reasons"))
ok("I25 comparison has player_a",         hasattr(_i_r.comparison, "player_a"))
ok("I26 comparison has player_b",         hasattr(_i_r.comparison, "player_b"))


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5l: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
