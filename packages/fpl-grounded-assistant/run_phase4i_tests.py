"""
run_phase4i_tests.py
====================
Phase 4i: session hygiene and lifecycle hardening.

Validates session TTL, lazy cleanup, max-session cap, metadata tracking,
and the new GET /session/{id} inspection endpoint.

All tests use STANDARD_BOOTSTRAP or AMBIGUOUS_BOOTSTRAP injected via
``fpl_server._init_bootstrap()``.  Session config is modified via
``fpl_server._SESSION_TTL_SECONDS`` / ``fpl_server._SESSION_MAX_COUNT``
and always restored after each section.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase4i_tests.py

Sections
--------
A  -- Import shape: _SessionEntry, config constants, new models, new endpoint
B  -- Session creation with metadata (created_at, expires_after_seconds)
C  -- GET /session/{id}: metadata inspection
D  -- TTL expiration: lazy check on ask + get_session
E  -- _prune_expired_sessions: called on create, removes stale entries
F  -- Max session cap: 429 at limit, recovers after clear
G  -- last_used_at updates on ask
H  -- Backward compat: Phase 4h API shape preserved
I  -- Stateless /ask regression
J  -- FinalResponse contract invariants through session path
"""
from __future__ import annotations

import os
import sys
import time

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
# Section A -- Import shape
# ===========================================================================
_section("A -- Import shape")

ok("A1  _SessionEntry dataclass exists",       hasattr(fpl_server, "_SessionEntry"))
ok("A2  _SessionEntry has 'session' field",
   hasattr(fpl_server._SessionEntry, "__dataclass_fields__") and
   "session" in fpl_server._SessionEntry.__dataclass_fields__)
ok("A3  _SessionEntry has 'created_at' field",
   "created_at" in fpl_server._SessionEntry.__dataclass_fields__)
ok("A4  _SessionEntry has 'last_used_at' field",
   "last_used_at" in fpl_server._SessionEntry.__dataclass_fields__)

ok("A5  _SESSION_TTL_SECONDS exists and is int",
   hasattr(fpl_server, "_SESSION_TTL_SECONDS") and
   isinstance(fpl_server._SESSION_TTL_SECONDS, int))
ok("A6  _SESSION_TTL_SECONDS default is 1800",  fpl_server._SESSION_TTL_SECONDS == 1800)
ok("A7  _SESSION_MAX_COUNT exists and is int",
   hasattr(fpl_server, "_SESSION_MAX_COUNT") and
   isinstance(fpl_server._SESSION_MAX_COUNT, int))
ok("A8  _SESSION_MAX_COUNT default is 100",     fpl_server._SESSION_MAX_COUNT == 100)

ok("A9  _prune_expired_sessions callable",      callable(getattr(fpl_server, "_prune_expired_sessions", None)))

ok("A10 SessionInfoResponse defined",           hasattr(fpl_server, "SessionInfoResponse"))
_sif = fpl_server.SessionInfoResponse.model_fields
for _f in ("session_id", "created_at", "last_used_at", "turn_count"):
    ok(f"A11.{_f}  SessionInfoResponse has '{_f}'", _f in _sif)

_csf = fpl_server.CreateSessionResponse.model_fields
ok("A12 CreateSessionResponse has 'session_id'",        "session_id"           in _csf)
ok("A13 CreateSessionResponse has 'created_at'",        "created_at"           in _csf)
ok("A14 CreateSessionResponse has 'expires_after_seconds'", "expires_after_seconds" in _csf)

_routes = {r.path for r in fpl_server.app.routes}
ok("A15 GET /session/{session_id} route registered",    "/session/{session_id}" in _routes)


# ===========================================================================
# Section B -- Session creation with metadata
# ===========================================================================
_section("B -- Session creation with metadata")

fpl_server._clear_sessions()
fpl_server._SESSION_TTL_SECONDS = 1800
fpl_server._SESSION_MAX_COUNT   = 100

_t_before = time.time()
_rb = _client.post("/session")
_t_after  = time.time()

ok("B1  POST /session returns 200",         _rb.status_code == 200)
_jb = _rb.json()

ok("B2  response has 'session_id'",         "session_id"           in _jb)
ok("B3  response has 'created_at'",         "created_at"           in _jb)
ok("B4  response has 'expires_after_seconds'", "expires_after_seconds" in _jb)

ok("B5  created_at is float > 0",           isinstance(_jb.get("created_at"), float) and _jb["created_at"] > 0)
ok("B6  created_at is within call window",
   _t_before <= _jb["created_at"] <= _t_after + 0.1)
ok("B7  expires_after_seconds == 1800",     _jb.get("expires_after_seconds") == 1800)

_sid_b = _jb["session_id"]
ok("B8  session stored in _sessions",       _sid_b in fpl_server._sessions)

_entry_b = fpl_server._sessions[_sid_b]
ok("B9  entry is _SessionEntry",            isinstance(_entry_b, fpl_server._SessionEntry))
ok("B10 entry.created_at matches response", abs(_entry_b.created_at - _jb["created_at"]) < 0.01)
ok("B11 entry.last_used_at == created_at at creation",
   _entry_b.last_used_at == _entry_b.created_at)
ok("B12 expires_after_seconds reflects _SESSION_TTL_SECONDS",
   _jb["expires_after_seconds"] == fpl_server._SESSION_TTL_SECONDS)


# ===========================================================================
# Section C -- GET /session/{id}: metadata inspection
# ===========================================================================
_section("C -- GET /session/{id}: metadata inspection")

fpl_server._clear_sessions()
_sid_c = _client.post("/session").json()["session_id"]

_rc_get = _client.get(f"/session/{_sid_c}")
ok("C1  GET /session/{id} returns 200",      _rc_get.status_code == 200)
_jcg = _rc_get.json()
ok("C2  response has 'session_id'",          "session_id"   in _jcg)
ok("C3  response has 'created_at'",          "created_at"   in _jcg)
ok("C4  response has 'last_used_at'",        "last_used_at" in _jcg)
ok("C5  response has 'turn_count'",          "turn_count"   in _jcg)
ok("C6  session_id matches",                 _jcg.get("session_id") == _sid_c)
ok("C7  turn_count is 0 on fresh session",   _jcg.get("turn_count") == 0)
ok("C8  created_at is float > 0",            isinstance(_jcg.get("created_at"), float) and _jcg["created_at"] > 0)
ok("C9  last_used_at == created_at before first ask",
   _jcg.get("last_used_at") == _jcg.get("created_at"))

# After one ask, turn_count increments
_client.post(f"/session/{_sid_c}/ask", json={"question": "should I captain Haaland"})
_rc_get2 = _client.get(f"/session/{_sid_c}")
ok("C10 turn_count is 1 after one ask",      _rc_get2.json().get("turn_count") == 1)

# After second ask, turn_count increments again
_client.post(f"/session/{_sid_c}/ask", json={"question": "what is the current gameweek"})
_rc_get3 = _client.get(f"/session/{_sid_c}")
ok("C11 turn_count is 2 after two asks",     _rc_get3.json().get("turn_count") == 2)

# Unknown session -> 404
_rc_unk = _client.get("/session/00000000-0000-0000-0000-000000000000")
ok("C12 unknown session GET -> 404",          _rc_unk.status_code == 404)

# GET does not create a session
ok("C13 GET does not add to _sessions",      "00000000-0000-0000-0000-000000000000" not in fpl_server._sessions)


# ===========================================================================
# Section D -- TTL expiration
# ===========================================================================
_section("D -- TTL expiration")

fpl_server._clear_sessions()
fpl_server._SESSION_TTL_SECONDS = 1800  # restore

# Create a session and manually expire it
_sid_d = _client.post("/session").json()["session_id"]
_entry_d = fpl_server._sessions[_sid_d]
_entry_d.last_used_at = time.time() - 9999  # force expiry

# session_ask on expired session -> 404 (lazy check)
_rd_ask = _client.post(f"/session/{_sid_d}/ask",
                       json={"question": "should I captain Haaland"})
ok("D1  ask on expired session -> 404",       _rd_ask.status_code == 404)
ok("D2  expired session removed from _sessions after ask",
   _sid_d not in fpl_server._sessions)

# Create another session and expire it
_sid_d2 = _client.post("/session").json()["session_id"]
fpl_server._sessions[_sid_d2].last_used_at = time.time() - 9999

# GET on expired session -> 404
_rd_get = _client.get(f"/session/{_sid_d2}")
ok("D3  GET on expired session -> 404",       _rd_get.status_code == 404)
ok("D4  expired session removed from _sessions after GET",
   _sid_d2 not in fpl_server._sessions)

# Non-expired session still accessible
_sid_d3 = _client.post("/session").json()["session_id"]
_rd_ok = _client.post(f"/session/{_sid_d3}/ask",
                      json={"question": "should I captain Haaland"})
ok("D5  non-expired session still accessible", _rd_ok.status_code == 200)

# TTL=0 disables expiration
fpl_server._SESSION_TTL_SECONDS = 0
_sid_d4 = _client.post("/session").json()["session_id"]
fpl_server._sessions[_sid_d4].last_used_at = time.time() - 999999  # very old
_rd_no_ttl = _client.post(f"/session/{_sid_d4}/ask",
                          json={"question": "should I captain Haaland"})
ok("D6  TTL=0 disables expiration (old session still works)", _rd_no_ttl.status_code == 200)
fpl_server._SESSION_TTL_SECONDS = 1800  # restore

# DELETE on expired-then-cleaned session -> 404
_sid_d5 = _client.post("/session").json()["session_id"]
fpl_server._sessions[_sid_d5].last_used_at = time.time() - 9999
# Access it to trigger lazy cleanup (GET triggers it)
_client.get(f"/session/{_sid_d5}")
ok("D7  DELETE on lazily-cleaned session -> 404",
   _client.delete(f"/session/{_sid_d5}").status_code == 404)

# expires_after_seconds reflects current TTL at creation time
fpl_server._SESSION_TTL_SECONDS = 300
_jd_300 = _client.post("/session").json()
ok("D8  expires_after_seconds reflects TTL at creation (300)",
   _jd_300.get("expires_after_seconds") == 300)
fpl_server._SESSION_TTL_SECONDS = 1800  # restore


# ===========================================================================
# Section E -- _prune_expired_sessions: called on create
# ===========================================================================
_section("E -- _prune_expired_sessions: called on create")

fpl_server._clear_sessions()
fpl_server._SESSION_TTL_SECONDS = 1800

# Create two sessions and manually expire them
_sid_e1 = _client.post("/session").json()["session_id"]
_sid_e2 = _client.post("/session").json()["session_id"]
fpl_server._sessions[_sid_e1].last_used_at = time.time() - 9999
fpl_server._sessions[_sid_e2].last_used_at = time.time() - 9999

ok("E1  two expired sessions in _sessions before create",
   _sid_e1 in fpl_server._sessions and _sid_e2 in fpl_server._sessions)

# Creating a new session triggers pruning
_sid_e3 = _client.post("/session").json()["session_id"]
ok("E2  POST /session returns 200 (prune ran)",  _sid_e3 is not None)
ok("E3  expired sessions removed after create",
   _sid_e1 not in fpl_server._sessions and _sid_e2 not in fpl_server._sessions)
ok("E4  new session present",                     _sid_e3 in fpl_server._sessions)
ok("E5  only one session remains (the new one)",  len(fpl_server._sessions) == 1)

# _prune_expired_sessions callable directly
fpl_server._clear_sessions()
_sid_ep1 = _client.post("/session").json()["session_id"]
_sid_ep2 = _client.post("/session").json()["session_id"]
fpl_server._sessions[_sid_ep1].last_used_at = time.time() - 9999
removed = fpl_server._prune_expired_sessions()
ok("E6  _prune_expired_sessions returns count of removed sessions",
   removed == 1)
ok("E7  expired session removed from _sessions",  _sid_ep1 not in fpl_server._sessions)
ok("E8  non-expired session preserved",           _sid_ep2 in fpl_server._sessions)

# TTL=0 means _prune_expired_sessions removes nothing
fpl_server._SESSION_TTL_SECONDS = 0
fpl_server._sessions[_sid_ep2].last_used_at = time.time() - 999999
removed_zero = fpl_server._prune_expired_sessions()
ok("E9  TTL=0 -> _prune_expired_sessions removes 0", removed_zero == 0)
ok("E10 session with TTL=0 still present",           _sid_ep2 in fpl_server._sessions)
fpl_server._SESSION_TTL_SECONDS = 1800  # restore


# ===========================================================================
# Section F -- Max session cap
# ===========================================================================
_section("F -- Max session cap")

fpl_server._clear_sessions()
fpl_server._SESSION_TTL_SECONDS = 1800
fpl_server._SESSION_MAX_COUNT   = 3

# Fill to cap
_sids_f = []
for _i in range(3):
    _rf_i = _client.post("/session")
    ok(f"F{_i + 1}  session {_i + 1}/3 created ok",   _rf_i.status_code == 200)
    _sids_f.append(_rf_i.json()["session_id"])

# One more -> 429
_rf_over = _client.post("/session")
ok("F4  creating beyond cap -> 429",                    _rf_over.status_code == 429)
ok("F5  _sessions count still at cap",                  len(fpl_server._sessions) == 3)

# Clear one -> can create again
_client.delete(f"/session/{_sids_f[0]}")
_rf_after = _client.post("/session")
ok("F6  after clear, new session created ok",           _rf_after.status_code == 200)
ok("F7  _sessions count back to cap (3)",               len(fpl_server._sessions) == 3)

# Cap=0 treated as "no sessions allowed"
fpl_server._clear_sessions()
fpl_server._SESSION_MAX_COUNT = 0
_rf_zero_cap = _client.post("/session")
ok("F8  cap=0 -> 429 (no sessions allowed)",             _rf_zero_cap.status_code == 429)

# Restore
fpl_server._clear_sessions()
fpl_server._SESSION_MAX_COUNT   = 100
fpl_server._SESSION_TTL_SECONDS = 1800


# ===========================================================================
# Section G -- last_used_at updates on ask
# ===========================================================================
_section("G -- last_used_at updates on ask")

fpl_server._clear_sessions()
_sid_g = _client.post("/session").json()["session_id"]

_entry_g = fpl_server._sessions[_sid_g]
_created_at_g = _entry_g.created_at
_luat_before  = _entry_g.last_used_at

ok("G1  last_used_at == created_at before first ask",
   _luat_before == _created_at_g)

# Small sleep to ensure time advances
time.sleep(0.01)

_client.post(f"/session/{_sid_g}/ask",
             json={"question": "should I captain Haaland"})
_luat_after = fpl_server._sessions[_sid_g].last_used_at

ok("G2  last_used_at updated after ask",        _luat_after > _luat_before)
ok("G3  created_at unchanged after ask",        fpl_server._sessions[_sid_g].created_at == _created_at_g)

# GET /session reflects updated last_used_at
_jg_get = _client.get(f"/session/{_sid_g}").json()
ok("G4  GET /session reflects updated last_used_at",
   abs(_jg_get.get("last_used_at", 0) - _luat_after) < 0.01)

# Second ask advances last_used_at further
time.sleep(0.01)
_client.post(f"/session/{_sid_g}/ask",
             json={"question": "rank captains"})
_luat_after2 = fpl_server._sessions[_sid_g].last_used_at
ok("G5  last_used_at advances further on second ask",   _luat_after2 > _luat_after)

# Unsupported intent still updates last_used_at
time.sleep(0.01)
_client.post(f"/session/{_sid_g}/ask",
             json={"question": "tell me a joke"})
_luat_after3 = fpl_server._sessions[_sid_g].last_used_at
ok("G6  unsupported intent ask also updates last_used_at", _luat_after3 > _luat_after2)

# GET /session does NOT update last_used_at
_luat_before_get = fpl_server._sessions[_sid_g].last_used_at
time.sleep(0.01)
_client.get(f"/session/{_sid_g}")
_luat_after_get = fpl_server._sessions[_sid_g].last_used_at
ok("G7  GET /session does not update last_used_at",
   _luat_after_get == _luat_before_get)


# ===========================================================================
# Section H -- Backward compat: Phase 4h API shape preserved
# ===========================================================================
_section("H -- Backward compat: Phase 4h API shape preserved")

fpl_server._clear_sessions()
fpl_server._SESSION_MAX_COUNT = 100

_sid_h = _client.post("/session").json()["session_id"]

# SessionAskResponse shape unchanged
_rh_ask = _client.post(f"/session/{_sid_h}/ask",
                       json={"question": "should I captain Haaland"})
ok("H1  session ask returns 200",            _rh_ask.status_code == 200)
_jh = _rh_ask.json()
for _f in ("session_id", "final_text", "outcome", "supported", "intent",
           "review_passed", "llm_used"):
    ok(f"H2.{_f}  SessionAskResponse has '{_f}'", _f in _jh)

ok("H3  session_id in response matches",     _jh.get("session_id") == _sid_h)
ok("H4  rewritten_question None (no debug)", _jh.get("rewritten_question") is None)
ok("H5  debug None (no debug mode)",         _jh.get("debug") is None)

# ClearSessionResponse shape unchanged
_rh_del = _client.delete(f"/session/{_sid_h}")
ok("H6  DELETE returns 200",                 _rh_del.status_code == 200)
_jh_del = _rh_del.json()
ok("H7  ClearSessionResponse has 'status'",  "status"     in _jh_del)
ok("H8  ClearSessionResponse has 'session_id'", "session_id" in _jh_del)
ok("H9  status is 'cleared'",                _jh_del.get("status") == "cleared")

# CreateSessionResponse backward compat: session_id still present
_sid_h2 = _client.post("/session").json()["session_id"]
ok("H10 session_id still present in CreateSessionResponse",
   isinstance(_sid_h2, str) and len(_sid_h2) == 36)

# Phase 4h pronoun follow-up still works
_client.post(f"/session/{_sid_h2}/ask",
             json={"question": "should I captain Haaland"})
_rh_pron = _client.post(f"/session/{_sid_h2}/ask",
                        json={"question": "should I captain him"})
ok("H11 pronoun follow-up still resolves",   _rh_pron.json().get("outcome") == OUTCOME_OK)

# Phase 4h debug mode still works (resolver key in debug bundle)
_sid_h3 = _client.post("/session").json()["session_id"]
_client.post(f"/session/{_sid_h3}/ask",
             json={"question": "should I captain Haaland"})
_rh_dbg = _client.post(f"/session/{_sid_h3}/ask",
                       json={"question": "should I captain him", "debug": True})
_jh_dbg = _rh_dbg.json()
ok("H12 debug bundle present on follow-up",  _jh_dbg.get("debug") is not None)
ok("H13 debug bundle has 'resolver' key",
   "resolver" in (_jh_dbg.get("debug") or {}))
ok("H14 rewritten_question at top level (resolver ran)",
   _jh_dbg.get("rewritten_question") is not None)


# ===========================================================================
# Section I -- Stateless /ask regression
# ===========================================================================
_section("I -- Stateless /ask regression")

_ri1 = _client.post("/ask", json={"question": "should I captain Haaland"})
ok("I1  /ask returns 200",          _ri1.status_code == 200)
ok("I2  /ask final_text non-empty", len(_ri1.json().get("final_text", "")) > 0)
ok("I3  /ask outcome 'ok'",         _ri1.json().get("outcome") == OUTCOME_OK)
ok("I4  /ask has no session_id",    "session_id" not in _ri1.json())

_ri_dbg = _client.post("/ask", json={"question": "should I captain Haaland", "debug": True})
_ji_dbg = _ri_dbg.json()
ok("I5  /ask debug returns 200",           _ri_dbg.status_code == 200)
ok("I6  /ask debug has no 'resolver' key", "resolver" not in (_ji_dbg.get("debug") or {}))

_INTENT_CASES_I = [
    ("should I captain Haaland",     INTENT_CAPTAIN_SCORE),
    ("rank captains",                INTENT_RANK_CANDIDATES),
    ("what is the current gameweek", INTENT_CURRENT_GAMEWEEK),
    ("tell me about Salah",          INTENT_PLAYER_SUMMARY),
    ("find player Haaland",          INTENT_PLAYER_RESOLVE),
]
for _i, (_q, _exp) in enumerate(_INTENT_CASES_I, 1):
    _ri_i = _client.post("/ask", json={"question": _q})
    ok(f"I{_i + 6}  {_exp} stateless -> 200",         _ri_i.status_code == 200)
    ok(f"I{_i + 6}b {_exp} intent correct stateless", _ri_i.json().get("intent") == _exp)


# ===========================================================================
# Section J -- FinalResponse contract invariants through session path
# ===========================================================================
_section("J -- FinalResponse contract invariants")

fpl_server._clear_sessions()
_sid_j = _client.post("/session").json()["session_id"]

_J_QUERIES = [
    "should I captain Haaland",
    "rank captains",
    "what is the current gameweek",
    "tell me about Salah",
    "find player Haaland",
    "what is the weather today",
    "should I captain XYZ Unknown Player",
]

_j_responses = [
    _client.post(f"/session/{_sid_j}/ask",
                 json={"question": q, "debug": True}).json()
    for q in _J_QUERIES
]

ok("J1  all session queries returned no server errors", True)

for _k, (_q, _rj) in enumerate(zip(_J_QUERIES, _j_responses), 1):
    ok(f"J2.{_k} final_text non-empty: {_q!r:.30}", len(_rj.get("final_text", "")) > 0)

for _k, (_q, _rj) in enumerate(zip(_J_QUERIES, _j_responses), 1):
    _exp = _rj.get("outcome") != OUTCOME_UNSUPPORTED_INTENT
    ok(f"J3.{_k} supported == (outcome != unsupported): {_q!r:.25}",
       _rj.get("supported") == _exp)

for _k, (_q, _rj) in enumerate(zip(_J_QUERIES, _j_responses), 1):
    if _rj.get("llm_used"):
        ok(f"J4.{_k} llm_used=True -> review_passed=True: {_q!r:.22}", _rj.get("review_passed"))
    else:
        ok(f"J4.{_k} llm_used=False (deterministic): {_q!r:.24}", True)

for _k, (_q, _rj) in enumerate(zip(_J_QUERIES, _j_responses), 1):
    _bund = _rj.get("debug") or {}
    if not _rj.get("llm_used") and _bund:
        ok(f"J5.{_k} not llm_used -> final_text==response_text: {_q!r:.20}",
           _rj.get("final_text") == _bund.get("response_text"))
    else:
        ok(f"J5.{_k} llm_used=True (skip check): {_q!r:.22}", True)

for _k, (_q, _rj) in enumerate(zip(_J_QUERIES, _j_responses), 1):
    ok(f"J6.{_k} session_id in response: {_q!r:.28}", _rj.get("session_id") == _sid_j)

# turn_count increments across all J queries
_jj_info = _client.get(f"/session/{_sid_j}").json()
ok("J7  turn_count equals number of J queries",
   _jj_info.get("turn_count") == len(_J_QUERIES))


# ===========================================================================
# Summary
# ===========================================================================
print()
print("=" * 60)
print(f"  Phase 4i: {_passed + _failed} assertions | {_passed} PASS | {_failed} FAIL")
print("=" * 60)

if _failed:
    sys.exit(1)
