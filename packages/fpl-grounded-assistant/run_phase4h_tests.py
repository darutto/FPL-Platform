"""
run_phase4h_tests.py
====================
Phase 4h: HTTP session support validation.

Validates the three new session endpoints in ``fpl_server``:
  POST   /session               -- create a session
  POST   /session/{id}/ask      -- multi-turn question within a session
  DELETE /session/{id}          -- clear and remove a session

Also validates that the existing stateless POST /ask endpoint is unchanged.

All tests use STANDARD_BOOTSTRAP or AMBIGUOUS_BOOTSTRAP injected via
``fpl_server._init_bootstrap()``.  No live network, no LLM calls.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase4h_tests.py

Sections
--------
A  -- Import and server shape (session registry, new models, new endpoints)
B  -- POST /session: session creation
C  -- POST /session/{id}/ask: multi-turn session behavior
D  -- POST /session/{id}/ask: debug mode + resolver metadata
E  -- DELETE /session/{id}: session lifecycle
F  -- HTTP contract (404, 422, 503 paths)
G  -- Stateless /ask regression (existing endpoint unchanged)
H  -- FinalResponse contract invariants through session path
I  -- Edge cases
"""
from __future__ import annotations

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

from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
)

import fpl_server
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()

from fastapi.testclient import TestClient

_passed = 0
_failed = 0


def _section(name: str) -> None:
    print(f"\n  [{name}]")


def ok(label: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"    PASS  {label}")
    else:
        _failed += 1
        print(f"    FAIL  {label}")


def eq(label: str, actual: object, expected: object) -> None:
    ok(f"{label}  (got {actual!r})", actual == expected)


_client = TestClient(fpl_server.app, raise_server_exceptions=True)


# ===========================================================================
# Section A -- Import and server shape
# ===========================================================================
_section("A -- Import and server shape")

ok("A1  fpl_server imports without error", True)
ok("A2  _sessions dict exists",            hasattr(fpl_server, "_sessions"))
ok("A3  _sessions is initially empty (after _clear_sessions)",
   isinstance(fpl_server._sessions, dict) and len(fpl_server._sessions) == 0)
ok("A4  _clear_sessions is callable",      callable(fpl_server._clear_sessions))

ok("A5  CreateSessionResponse defined",    hasattr(fpl_server, "CreateSessionResponse"))
ok("A6  SessionAskResponse defined",       hasattr(fpl_server, "SessionAskResponse"))
ok("A7  ClearSessionResponse defined",     hasattr(fpl_server, "ClearSessionResponse"))

_csf = fpl_server.CreateSessionResponse.model_fields
ok("A8  CreateSessionResponse has 'session_id'", "session_id" in _csf)

_saf = fpl_server.SessionAskResponse.model_fields
for _f in ("session_id", "final_text", "outcome", "supported", "intent",
           "review_passed", "llm_used", "rewritten_question", "debug"):
    ok(f"A9.{_f}  SessionAskResponse has '{_f}'", _f in _saf)

ok("A10 SessionAskResponse 'rewritten_question' defaults to None",
   _saf["rewritten_question"].default is None)
ok("A11 SessionAskResponse 'debug' defaults to None",
   _saf["debug"].default is None)

_clf = fpl_server.ClearSessionResponse.model_fields
ok("A12 ClearSessionResponse has 'status'",     "status"     in _clf)
ok("A13 ClearSessionResponse has 'session_id'", "session_id" in _clf)

_routes = {r.path for r in fpl_server.app.routes}
ok("A14 POST /session route registered",            "/session"                  in _routes)
ok("A15 POST /session/{session_id}/ask route",      "/session/{session_id}/ask" in _routes)
ok("A16 DELETE /session/{session_id} route",        "/session/{session_id}"     in _routes)


# ===========================================================================
# Section B -- POST /session: session creation
# ===========================================================================
_section("B -- POST /session: session creation")

fpl_server._clear_sessions()

_rb1 = _client.post("/session")
ok("B1  POST /session returns 200",       _rb1.status_code == 200)
ok("B2  response is JSON",                _rb1.headers["content-type"].startswith("application/json"))

_jb1 = _rb1.json()
ok("B3  response has 'session_id'",       "session_id" in _jb1)
ok("B4  session_id is non-empty string",
   isinstance(_jb1.get("session_id"), str) and len(_jb1["session_id"]) > 0)

_sid1 = _jb1["session_id"]
ok("B5  session stored in _sessions",     _sid1 in fpl_server._sessions)

_rb2 = _client.post("/session")
_sid2 = _rb2.json().get("session_id")
ok("B6  second session has different id", _sid1 != _sid2)
ok("B7  both sessions stored",
   _sid1 in fpl_server._sessions and _sid2 in fpl_server._sessions)

ok("B8  session_id has UUID4 shape (36 chars)",  len(_sid1) == 36)
ok("B9  session_id has 4 hyphens",               _sid1.count("-") == 4)
ok("B10 _bootstrap still set after create",      fpl_server._bootstrap is not None)


# ===========================================================================
# Section C -- POST /session/{id}/ask: multi-turn session behavior
# ===========================================================================
_section("C -- POST /session/{id}/ask: multi-turn behavior")

fpl_server._clear_sessions()
_sid_c = _client.post("/session").json()["session_id"]

_rc1 = _client.post(f"/session/{_sid_c}/ask",
                    json={"question": "should I captain Haaland"})
ok("C1  first turn returns 200",                  _rc1.status_code == 200)
_jc1 = _rc1.json()
ok("C2  first turn has session_id",               _jc1.get("session_id") == _sid_c)
ok("C3  first turn final_text non-empty",         len(_jc1.get("final_text", "")) > 0)
ok("C4  first turn outcome 'ok'",                 _jc1.get("outcome") == OUTCOME_OK)
ok("C5  first turn intent captain_score",         _jc1.get("intent") == INTENT_CAPTAIN_SCORE)
ok("C6  first turn supported True",               _jc1.get("supported") is True)

_rc2 = _client.post(f"/session/{_sid_c}/ask",
                    json={"question": "should I captain him"})
ok("C7  pronoun follow-up returns 200",           _rc2.status_code == 200)
_jc2 = _rc2.json()
ok("C8  pronoun follow-up has session_id",        _jc2.get("session_id") == _sid_c)
ok("C9  pronoun follow-up final_text non-empty",  len(_jc2.get("final_text", "")) > 0)
ok("C10 pronoun follow-up outcome 'ok'",          _jc2.get("outcome") == OUTCOME_OK)
ok("C11 pronoun follow-up intent captain_score",  _jc2.get("intent") == INTENT_CAPTAIN_SCORE)

_rc3 = _client.post(f"/session/{_sid_c}/ask",
                    json={"question": "what is the current gameweek"})
ok("C12 third turn returns 200",                  _rc3.status_code == 200)
ok("C13 third turn intent current_gameweek",
   _rc3.json().get("intent") == INTENT_CURRENT_GAMEWEEK)

_sid_fresh = _client.post("/session").json()["session_id"]
_rc_fresh = _client.post(f"/session/{_sid_fresh}/ask",
                         json={"question": "should I captain him"})
ok("C14 fresh session pronoun follow-up → 200",   _rc_fresh.status_code == 200)
ok("C15 fresh session final_text non-empty",
   len(_rc_fresh.json().get("final_text", "")) > 0)

_rc4 = _client.post(f"/session/{_sid_c}/ask",
                    json={"question": "should I captain him"})
ok("C16 fourth turn original session → 200",      _rc4.status_code == 200)
ok("C17 fourth turn outcome 'ok' (context preserved)",
   _rc4.json().get("outcome") == OUTCOME_OK)

for _f in ("session_id", "final_text", "outcome", "supported", "intent",
           "review_passed", "llm_used"):
    ok(f"C18.{_f}  response has '{_f}'", _f in _jc2)

ok("C19 rewritten_question None in non-debug mode", _jc2.get("rewritten_question") is None)
ok("C20 debug None in non-debug mode",              _jc2.get("debug") is None)


# ===========================================================================
# Section D -- debug mode + resolver metadata
# ===========================================================================
_section("D -- debug mode + resolver metadata")

fpl_server._clear_sessions()
_sid_d = _client.post("/session").json()["session_id"]

_rd1 = _client.post(f"/session/{_sid_d}/ask",
                    json={"question": "should I captain Haaland", "debug": True})
ok("D1  first turn debug → 200",          _rd1.status_code == 200)
_jd1 = _rd1.json()
ok("D2  debug bundle present",            _jd1.get("debug") is not None)

_bd1 = _jd1.get("debug") or {}
ok("D3  bundle has 'response_text'",      "response_text" in _bd1)
ok("D4  bundle has 'llm_text'",           "llm_text"      in _bd1)
ok("D5  bundle has 'violations'",         "violations"    in _bd1)
ok("D6  bundle has 'prompt_used'",        "prompt_used"   in _bd1)
ok("D7  bundle has 'model'",              "model"         in _bd1)
ok("D8  first turn rewritten_question None (no prev context)",
   _jd1.get("rewritten_question") is None)

_rd2 = _client.post(f"/session/{_sid_d}/ask",
                    json={"question": "should I captain him", "debug": True})
ok("D9  pronoun follow-up debug → 200",   _rd2.status_code == 200)
_jd2 = _rd2.json()
ok("D10 debug bundle present on follow-up", _jd2.get("debug") is not None)

_bd2 = _jd2.get("debug") or {}
ok("D11 debug bundle has 'resolver' key", "resolver" in _bd2)

_rdbg = _bd2.get("resolver") or {}
ok("D12 resolver has 'resolver_used'",       "resolver_used"       in _rdbg)
ok("D13 resolver has 'resolver_source'",     "resolver_source"     in _rdbg)
ok("D14 resolver has 'resolver_confidence'", "resolver_confidence" in _rdbg)
ok("D15 resolver has 'rewritten_question'",  "rewritten_question"  in _rdbg)
ok("D16 resolver has 'fallback_reason'",     "fallback_reason"     in _rdbg)

ok("D17 resolver_used True for pronoun follow-up",  _rdbg.get("resolver_used") is True)
ok("D18 resolver_source is 'fallback_regex'",
   _rdbg.get("resolver_source") == "fallback_regex")
ok("D19 fallback_reason is 'llm_unavailable'",
   _rdbg.get("fallback_reason") == "llm_unavailable")

ok("D20 rewritten_question at top level when resolver used",
   _jd2.get("rewritten_question") is not None)
ok("D21 top-level rewritten_question contains 'Haaland'",
   "Haaland" in (_jd2.get("rewritten_question") or ""))

_rd_nd = _client.post(f"/session/{_sid_d}/ask",
                      json={"question": "should I captain him"})
_jd_nd = _rd_nd.json()
ok("D22 no debug → debug field None",               _jd_nd.get("debug") is None)
ok("D23 no debug → rewritten_question None",        _jd_nd.get("rewritten_question") is None)


# ===========================================================================
# Section E -- DELETE /session/{id}: session lifecycle
# ===========================================================================
_section("E -- DELETE /session/{id}: session lifecycle")

fpl_server._clear_sessions()
_sid_e = _client.post("/session").json()["session_id"]

_client.post(f"/session/{_sid_e}/ask",
             json={"question": "should I captain Haaland"})

_re_del = _client.delete(f"/session/{_sid_e}")
ok("E1  DELETE returns 200",              _re_del.status_code == 200)
_jed = _re_del.json()
ok("E2  response has 'status'",           "status"     in _jed)
ok("E3  response has 'session_id'",       "session_id" in _jed)
ok("E4  status is 'cleared'",             _jed.get("status") == "cleared")
ok("E5  response session_id matches",     _jed.get("session_id") == _sid_e)
ok("E6  session removed from _sessions",  _sid_e not in fpl_server._sessions)

_re_after = _client.post(f"/session/{_sid_e}/ask",
                         json={"question": "should I captain Haaland"})
ok("E7  ask on cleared session → 404",    _re_after.status_code == 404)

_re_del2 = _client.delete(f"/session/{_sid_e}")
ok("E8  double DELETE → 404",             _re_del2.status_code == 404)

_sid_e2 = _client.post("/session").json()["session_id"]
_client.post(f"/session/{_sid_e2}/ask",
             json={"question": "should I captain Salah"})
_re_del3 = _client.delete(f"/session/{_sid_e2}")
ok("E9  second lifecycle cycle DELETE → 200", _re_del3.status_code == 200)
ok("E10 second cycle session removed",         _sid_e2 not in fpl_server._sessions)


# ===========================================================================
# Section F -- HTTP contract
# ===========================================================================
_section("F -- HTTP contract")

fpl_server._clear_sessions()

_rf_unk = _client.post("/session/00000000-0000-0000-0000-000000000000/ask",
                       json={"question": "should I captain Haaland"})
ok("F1  unknown session_id on ask → 404",    _rf_unk.status_code == 404)

_rf_del = _client.delete("/session/00000000-0000-0000-0000-000000000000")
ok("F2  unknown session_id on delete → 404", _rf_del.status_code == 404)

_sid_f = _client.post("/session").json()["session_id"]
_rf_miss = _client.post(f"/session/{_sid_f}/ask", json={})
ok("F3  missing question → 422",             _rf_miss.status_code == 422)

_rf_type = _client.post(f"/session/{_sid_f}/ask", json={"question": 12345})
ok("F4  numeric question → 422",             _rf_type.status_code == 422)

_rf_extra = _client.post(f"/session/{_sid_f}/ask",
                         json={"question": "should I captain Haaland", "unknown": "x"})
ok("F5  extra fields ignored → 200",         _rf_extra.status_code == 200)

ok("F6  session ask content-type is application/json",
   _rf_extra.headers["content-type"].startswith("application/json"))

_rf_get = _client.get(f"/session/{_sid_f}/ask")
ok("F7  GET /session/{id}/ask not valid (404 or 405)",
   _rf_get.status_code in (404, 405))

_rf_ndb = _client.post(f"/session/{_sid_f}/ask",
                       json={"question": "should I captain Haaland", "debug": False})
ok("F8  debug=False explicit → 200",         _rf_ndb.status_code == 200)
ok("F9  debug=False → debug field None",     _rf_ndb.json().get("debug") is None)

_saved_bs = fpl_server._bootstrap
fpl_server._bootstrap = None
_rf_503 = _client.post(f"/session/{_sid_f}/ask",
                       json={"question": "should I captain Haaland"})
ok("F10 no bootstrap → 503",                 _rf_503.status_code == 503)
fpl_server._bootstrap = _saved_bs

_INTENT_CASES_F = [
    ("should I captain Haaland",     INTENT_CAPTAIN_SCORE),
    ("rank captains",                INTENT_RANK_CANDIDATES),
    ("what is the current gameweek", INTENT_CURRENT_GAMEWEEK),
    ("tell me about Salah",          INTENT_PLAYER_SUMMARY),
    ("find player Haaland",          INTENT_PLAYER_RESOLVE),
]
for _i, (_q, _exp_intent) in enumerate(_INTENT_CASES_F, 11):
    _rf_i = _client.post(f"/session/{_sid_f}/ask", json={"question": _q})
    _jf_i = _rf_i.json()
    ok(f"F{_i}a  {_exp_intent} via session → 200",     _rf_i.status_code == 200)
    ok(f"F{_i}b  {_exp_intent} intent correct",         _jf_i.get("intent") == _exp_intent)


# ===========================================================================
# Section G -- Stateless /ask regression
# ===========================================================================
_section("G -- Stateless /ask regression")

_rg1 = _client.post("/ask", json={"question": "should I captain Haaland"})
ok("G1  /ask still returns 200",       _rg1.status_code == 200)
ok("G2  /ask final_text non-empty",    len(_rg1.json().get("final_text", "")) > 0)
ok("G3  /ask outcome 'ok'",            _rg1.json().get("outcome") == OUTCOME_OK)
ok("G4  /ask supported True",          _rg1.json().get("supported") is True)

_rg_dbg = _client.post("/ask", json={"question": "should I captain Haaland", "debug": True})
ok("G5  /ask debug returns 200",       _rg_dbg.status_code == 200)
_jg_dbg = _rg_dbg.json()
ok("G6  /ask debug bundle present",    _jg_dbg.get("debug") is not None)
ok("G7  stateless /ask debug has no 'resolver' key",
   "resolver" not in (_jg_dbg.get("debug") or {}))

ok("G8  /ask response has no session_id", "session_id" not in _rg1.json())

_INTENT_CASES_G = [
    ("should I captain Haaland",     INTENT_CAPTAIN_SCORE),
    ("rank captains",                INTENT_RANK_CANDIDATES),
    ("what is the current gameweek", INTENT_CURRENT_GAMEWEEK),
    ("tell me about Salah",          INTENT_PLAYER_SUMMARY),
    ("find player Haaland",          INTENT_PLAYER_RESOLVE),
]
for _i, (_q, _exp) in enumerate(_INTENT_CASES_G, 1):
    _rg_i = _client.post("/ask", json={"question": _q})
    ok(f"G{_i + 8}a  {_exp} stateless → 200",         _rg_i.status_code == 200)
    ok(f"G{_i + 8}b  {_exp} intent correct stateless", _rg_i.json().get("intent") == _exp)

_rg_u = _client.post("/ask", json={"question": "what is the weather"})
ok("G14a stateless unsupported → 200",    _rg_u.status_code == 200)
ok("G14b stateless unsupported=False",    _rg_u.json().get("supported") is False)


# ===========================================================================
# Section H -- FinalResponse contract invariants through session path
# ===========================================================================
_section("H -- FinalResponse contract invariants")

fpl_server._clear_sessions()
_sid_h = _client.post("/session").json()["session_id"]

_H_QUERIES = [
    "should I captain Haaland",
    "rank captains",
    "what is the current gameweek",
    "tell me about Salah",
    "find player Haaland",
    "what is the weather today",
    "should I captain XYZ Unknown Player",
]

_h_responses = [
    _client.post(f"/session/{_sid_h}/ask",
                 json={"question": q, "debug": True}).json()
    for q in _H_QUERIES
]

ok("H1  all queries returned no server errors", True)

for _j, (_q, _rh) in enumerate(zip(_H_QUERIES, _h_responses), 1):
    ok(f"H2.{_j} final_text non-empty: {_q!r:.30}", len(_rh.get("final_text", "")) > 0)

for _j, (_q, _rh) in enumerate(zip(_H_QUERIES, _h_responses), 1):
    _exp = _rh.get("outcome") != OUTCOME_UNSUPPORTED_INTENT
    ok(f"H3.{_j} supported == (outcome != unsupported): {_q!r:.25}",
       _rh.get("supported") == _exp)

for _j, (_q, _rh) in enumerate(zip(_H_QUERIES, _h_responses), 1):
    if _rh.get("llm_used"):
        ok(f"H4.{_j} llm_used=True → review_passed=True: {_q!r:.22}",
           _rh.get("review_passed"))
    else:
        ok(f"H4.{_j} llm_used=False (deterministic): {_q!r:.24}", True)

for _j, (_q, _rh) in enumerate(zip(_H_QUERIES, _h_responses), 1):
    _bund = _rh.get("debug") or {}
    if not _rh.get("llm_used") and _bund:
        ok(f"H5.{_j} not llm_used → final_text==response_text: {_q!r:.20}",
           _rh.get("final_text") == _bund.get("response_text"))
    else:
        ok(f"H5.{_j} llm_used=True (skip check): {_q!r:.22}", True)

for _j, (_q, _rh) in enumerate(zip(_H_QUERIES, _h_responses), 1):
    ok(f"H6.{_j} session_id in response: {_q!r:.28}",
       _rh.get("session_id") == _sid_h)


# ===========================================================================
# Section I -- Edge cases
# ===========================================================================
_section("I -- Edge cases")

fpl_server._clear_sessions()
_sid_i = _client.post("/session").json()["session_id"]

_ri_empty = _client.post(f"/session/{_sid_i}/ask", json={"question": ""})
ok("I1  empty question in session → 200",        _ri_empty.status_code == 200)
ok("I2  empty question final_text non-empty",
   len(_ri_empty.json().get("final_text", "")) > 0)

_ri_ws = _client.post(f"/session/{_sid_i}/ask", json={"question": "   "})
ok("I3  whitespace question in session → 200",   _ri_ws.status_code == 200)
ok("I4  whitespace final_text non-empty",
   len(_ri_ws.json().get("final_text", "")) > 0)

_ri_u = _client.post(f"/session/{_sid_i}/ask", json={"question": "tell me a joke"})
ok("I5  unsupported in session → 200",           _ri_u.status_code == 200)
ok("I6  unsupported in session supported=False", _ri_u.json().get("supported") is False)

_ri_after_u = _client.post(f"/session/{_sid_i}/ask",
                           json={"question": "should I captain Haaland"})
ok("I7  session still works after unsupported",  _ri_after_u.status_code == 200)
ok("I8  session result correct after unsupported",
   _ri_after_u.json().get("outcome") == OUTCOME_OK)

fpl_server._init_bootstrap(AMBIGUOUS_BOOTSTRAP)
_sid_amb = _client.post("/session").json()["session_id"]
_ri_amb = _client.post(f"/session/{_sid_amb}/ask",
                       json={"question": "should I captain Haaland"})
ok("I9  ambiguous bootstrap in session → 200",   _ri_amb.status_code == 200)
ok("I10 ambiguous bootstrap final_text non-empty",
   len(_ri_amb.json().get("final_text", "")) > 0)
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)

_ri_sc = _client.post(f"/session/{_sid_i}/ask", json={"question": "?"})
ok("I11 single-char in session → 200",           _ri_sc.status_code == 200)
ok("I12 single-char final_text non-empty",
   len(_ri_sc.json().get("final_text", "")) > 0)

_ri_q1 = _client.post(f"/session/{_sid_i}/ask",
                      json={"question": "what is the current gameweek"})
_ri_q2 = _client.post(f"/session/{_sid_i}/ask",
                      json={"question": "what is the current gameweek"})
ok("I13 identical questions: same final_text",
   _ri_q1.json().get("final_text") == _ri_q2.json().get("final_text"))
ok("I14 identical questions: same outcome",
   _ri_q1.json().get("outcome") == _ri_q2.json().get("outcome"))

_ri_list = _client.get("/session")
ok("I15 GET /session not defined (404 or 405)",
   _ri_list.status_code in (404, 405))


# ===========================================================================
# Summary
# ===========================================================================
print()
print("=" * 60)
print(f"  Phase 4h: {_passed + _failed} assertions | {_passed} PASS | {_failed} FAIL")
print("=" * 60)

if _failed:
    sys.exit(1)
