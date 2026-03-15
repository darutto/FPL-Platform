"""
run_phase4j_tests.py
====================
Phase 4j: session interaction examples and operational docs.

Validates that SESSION_FLOWS and SESSION_EDGE_CASES in session_examples.py
correctly exercise the session lifecycle, that SESSION_CONTRACT.md exists and
documents the required operational sections, and that the stateless endpoints
remain unchanged.

All tests use STANDARD_BOOTSTRAP injected via ``fpl_server._init_bootstrap()``.
Server config (TTL, cap) is modified only inside edge-case sections and always
restored via try/finally.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase4j_tests.py

Sections
--------
A  -- Module shape: session_examples imports, SESSION_FLOWS, SESSION_EDGE_CASES
B  -- Full lifecycle flow (create_ask_inspect_clear) via run_session_flow
C  -- Pronoun follow-up flow via run_session_flow
D  -- SESSION_CONTRACT.md content: required operational sections
E  -- Edge case: session_not_found
F  -- Edge case: clear_missing_session
G  -- Edge case: ttl_expiry
H  -- Edge case: cap_reached
I  -- Stateless /ask regression
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
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
)

import fpl_server
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()

from fastapi.testclient import TestClient

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
    ok(label, got == want)


# ===========================================================================
# Section A -- Module shape
# ===========================================================================

print("A  Module shape")

from examples import session_examples  # noqa: E402

ok("A1  session_examples imported",                  True)
ok("A2  SESSION_FLOWS is a list",                    isinstance(session_examples.SESSION_FLOWS, list))
ok("A3  SESSION_FLOWS has 2 entries",                len(session_examples.SESSION_FLOWS) == 2)

_flow_ids = [f["id"] for f in session_examples.SESSION_FLOWS]
ok("A4  flow 'create_ask_inspect_clear' present",    "create_ask_inspect_clear" in _flow_ids)
ok("A5  flow 'pronoun_follow_up' present",           "pronoun_follow_up" in _flow_ids)

ok("A6  SESSION_EDGE_CASES is a list",               isinstance(session_examples.SESSION_EDGE_CASES, list))
ok("A7  SESSION_EDGE_CASES has 4 entries",           len(session_examples.SESSION_EDGE_CASES) == 4)

_ec_ids = [e["id"] for e in session_examples.SESSION_EDGE_CASES]
ok("A8  edge case 'session_not_found' present",      "session_not_found" in _ec_ids)
ok("A9  edge case 'clear_missing_session' present",  "clear_missing_session" in _ec_ids)
ok("A10 edge case 'ttl_expiry' present",             "ttl_expiry" in _ec_ids)
ok("A11 edge case 'cap_reached' present",            "cap_reached" in _ec_ids)

ok("A12 run_session_flow callable",                  callable(session_examples.run_session_flow))
ok("A13 run_edge_case callable",                     callable(session_examples.run_edge_case))
ok("A14 make_session_client callable",               callable(session_examples.make_session_client))

_sc_path = os.path.join(_HERE, "SESSION_CONTRACT.md")
ok("A15 SESSION_CONTRACT.md exists",                 os.path.isfile(_sc_path))

# ===========================================================================
# Section B -- Full lifecycle flow (create_ask_inspect_clear)
# ===========================================================================

print("B  Full lifecycle flow")

fpl_server._clear_sessions()
_b_client = session_examples.make_session_client()

_b_flow = next(f for f in session_examples.SESSION_FLOWS if f["id"] == "create_ask_inspect_clear")
_b_result = session_examples.run_session_flow(_b_flow, _b_client)

ok("B1  flow_id correct",                            _b_result["flow_id"] == "create_ask_inspect_clear")
ok("B2  create_status is 200",                       _b_result["create_status"] == 200)
ok("B3  session_id is non-empty string",             isinstance(_b_result.get("session_id"), str)
                                                     and len(_b_result["session_id"]) > 0)
ok("B4  create_body has session_id",                 "session_id" in _b_result.get("create_body", {}))
ok("B5  create_body has created_at",                 "created_at" in _b_result.get("create_body", {}))
ok("B6  create_body has expires_after_seconds",      "expires_after_seconds" in _b_result.get("create_body", {}))
ok("B7  two turns completed",                        len(_b_result.get("turns", [])) == 2)
ok("B8  turn 1 status 200",                         _b_result["turns"][0]["status"] == 200)
ok("B9  turn 1 final_text non-empty",               bool(_b_result["turns"][0]["body"].get("final_text")))
ok("B10 turn 2 status 200",                         _b_result["turns"][1]["status"] == 200)
ok("B11 turn 2 final_text non-empty",               bool(_b_result["turns"][1]["body"].get("final_text")))
ok("B12 inspect_status is 200",                      _b_result["inspect_status"] == 200)
ok("B13 inspect turn_count is 2",                   _b_result["inspect_body"].get("turn_count") == 2)
ok("B14 clear_status is 200",                        _b_result["clear_status"] == 200)
ok("B15 after_clear_status is 404",                  _b_result["after_clear_status"] == 404)

# ===========================================================================
# Section C -- Pronoun follow-up flow
# ===========================================================================

print("C  Pronoun follow-up flow")

fpl_server._clear_sessions()
_c_client = session_examples.make_session_client()

_c_flow = next(f for f in session_examples.SESSION_FLOWS if f["id"] == "pronoun_follow_up")
_c_result = session_examples.run_session_flow(_c_flow, _c_client)

ok("C1  create_status is 200",                       _c_result["create_status"] == 200)
ok("C2  two turns completed",                        len(_c_result.get("turns", [])) == 2)
ok("C3  turn 1 status 200",                         _c_result["turns"][0]["status"] == 200)
ok("C4  turn 1 outcome ok",                         _c_result["turns"][0]["body"].get("outcome") == OUTCOME_OK)
ok("C5  turn 1 supported",                          _c_result["turns"][0]["body"].get("supported") is True)
ok("C6  turn 2 status 200",                         _c_result["turns"][1]["status"] == 200)
ok("C7  turn 2 supported",                          _c_result["turns"][1]["body"].get("supported") is True)
ok("C8  turn 2 final_text non-empty",               bool(_c_result["turns"][1]["body"].get("final_text")))
ok("C9  inspect turn_count is 2",                   _c_result["inspect_body"].get("turn_count") == 2)
ok("C10 clear_status is 200",                        _c_result["clear_status"] == 200)
ok("C11 after_clear_status is 404",                  _c_result["after_clear_status"] == 404)

# ===========================================================================
# Section D -- SESSION_CONTRACT.md content
# ===========================================================================

print("D  SESSION_CONTRACT.md content")

with open(_sc_path, encoding="utf-8") as _f:
    _sc_text = _f.read()

ok("D1  document is non-empty",                      len(_sc_text) > 100)
ok("D2  contains TTL section",                       "TTL" in _sc_text or "ttl" in _sc_text.lower())
ok("D3  describes idle expiration",                  "_SESSION_TTL_SECONDS" in _sc_text)
ok("D4  describes lazy expiration behaviour",        "lazy" in _sc_text.lower() or "lazily" in _sc_text.lower())
ok("D5  contains max-count section",                 "_SESSION_MAX_COUNT" in _sc_text)
ok("D6  describes cap 429",                          "429" in _sc_text)
ok("D7  in-memory language present",                 "in-memory" in _sc_text.lower() or "in memory" in _sc_text.lower())
ok("D8  non-persistent language present",            "persist" in _sc_text.lower() or "restart" in _sc_text.lower())
ok("D9  single-instance language present",           "single" in _sc_text.lower() or "multi-instance" in _sc_text.lower())
ok("D10 deferred section present",                   "Deferred" in _sc_text or "deferred" in _sc_text)

# ===========================================================================
# Section E -- Edge case: session_not_found
# ===========================================================================

print("E  Edge case: session_not_found")

fpl_server._clear_sessions()
_e_client = session_examples.make_session_client()
_e_ec = next(e for e in session_examples.SESSION_EDGE_CASES if e["id"] == "session_not_found")
_e_result = session_examples.run_edge_case(_e_ec, _e_client)

ok("E1  edge_id correct",                            _e_result["edge_id"] == "session_not_found")
ok("E2  ask on missing session returns 404",         _e_result["ask_status"] == 404)
ok("E3  ask detail is non-empty string",             bool(_e_result.get("ask_detail")))
ok("E4  get on missing session returns 404",         _e_result["get_status"] == 404)
ok("E5  get detail is non-empty string",             bool(_e_result.get("get_detail")))

# ===========================================================================
# Section F -- Edge case: clear_missing_session
# ===========================================================================

print("F  Edge case: clear_missing_session")

fpl_server._clear_sessions()
_f_client = session_examples.make_session_client()
_f_ec = next(e for e in session_examples.SESSION_EDGE_CASES if e["id"] == "clear_missing_session")
_f_result = session_examples.run_edge_case(_f_ec, _f_client)

ok("F1  edge_id correct",                            _f_result["edge_id"] == "clear_missing_session")
ok("F2  delete on missing session returns 404",      _f_result["delete_status"] == 404)
ok("F3  delete detail is non-empty string",          bool(_f_result.get("delete_detail")))

# Idempotent double-clear: first clear 200, second 404
fpl_server._clear_sessions()
_f2_client = session_examples.make_session_client()
_f2_r_create = _f2_client.post("/session")
_f2_sid = _f2_r_create.json()["session_id"]
_f2_del1 = _f2_client.delete(f"/session/{_f2_sid}")
_f2_del2 = _f2_client.delete(f"/session/{_f2_sid}")
ok("F4  first clear returns 200",                    _f2_del1.status_code == 200)
ok("F5  second clear returns 404",                   _f2_del2.status_code == 404)

# ===========================================================================
# Section G -- Edge case: ttl_expiry
# ===========================================================================

print("G  Edge case: ttl_expiry")

fpl_server._clear_sessions()
_g_client = session_examples.make_session_client()
_g_ec = next(e for e in session_examples.SESSION_EDGE_CASES if e["id"] == "ttl_expiry")
_g_result = session_examples.run_edge_case(_g_ec, _g_client)

ok("G1  edge_id correct",                            _g_result["edge_id"] == "ttl_expiry")
ok("G2  ask on expired session returns 404",         _g_result["ask_status"] == 404)
ok("G3  ask detail mentions 'expired'",              "expired" in _g_result.get("ask_detail", "").lower())
ok("G4  get on expired session returns 404",         _g_result["get_status"] == 404)
ok("G5  TTL config restored after edge case",        fpl_server._SESSION_TTL_SECONDS == 1800)

# ===========================================================================
# Section H -- Edge case: cap_reached
# ===========================================================================

print("H  Edge case: cap_reached")

fpl_server._clear_sessions()
_h_client = session_examples.make_session_client()
_h_ec = next(e for e in session_examples.SESSION_EDGE_CASES if e["id"] == "cap_reached")
_h_result = session_examples.run_edge_case(_h_ec, _h_client)

ok("H1  edge_id correct",                            _h_result["edge_id"] == "cap_reached")
ok("H2  first two creates succeed (200)",            _h_result["create_1_status"] == 200
                                                     and _h_result["create_2_status"] == 200)
ok("H3  third create returns 429",                   _h_result["create_3_status"] == 429)
ok("H4  cap detail mentions cap",                    "cap" in _h_result.get("create_3_detail", "").lower()
                                                     or "Session cap" in _h_result.get("create_3_detail", ""))
ok("H5  create after clear succeeds (200)",          _h_result["create_after_clear_status"] == 200)
ok("H6  cap config restored after edge case",        fpl_server._SESSION_MAX_COUNT == 100)
ok("H7  sessions cleared after edge case",           len(fpl_server._sessions) == 0)

# ===========================================================================
# Section I -- Stateless /ask regression
# ===========================================================================

print("I  Stateless /ask regression")

fpl_server._clear_sessions()
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
_i_client = TestClient(fpl_server.app, raise_server_exceptions=True)

_i_ok = _i_client.post("/ask", json={"question": "should I captain Haaland"})
ok("I1  /ask returns 200",                           _i_ok.status_code == 200)
ok("I2  /ask final_text non-empty",                  bool(_i_ok.json().get("final_text")))
ok("I3  /ask outcome ok",                            _i_ok.json().get("outcome") == OUTCOME_OK)
ok("I4  /ask supported True",                        _i_ok.json().get("supported") is True)
ok("I5  /ask has no session_id field",               "session_id" not in _i_ok.json())
ok("I6  /ask has no rewritten_question field",       "rewritten_question" not in _i_ok.json())

_i_unsup = _i_client.post("/ask", json={"question": "Is Haaland fit to play?"})
ok("I7  unsupported returns 200 (HTTP contract)",    _i_unsup.status_code == 200)
ok("I8  unsupported outcome correct",               _i_unsup.json().get("outcome") == OUTCOME_UNSUPPORTED_INTENT)
ok("I9  unsupported supported=False",               _i_unsup.json().get("supported") is False)

_i_health = _i_client.get("/health")
ok("I10 /health returns 200",                        _i_health.status_code == 200)
ok("I11 /health status ok",                          _i_health.json().get("status") == "ok")

_i_debug = _i_client.post("/ask", json={"question": "should I captain Haaland", "debug": True})
ok("I12 /ask debug=True returns 200",                _i_debug.status_code == 200)
ok("I13 /ask debug bundle present when debug=True", _i_debug.json().get("debug") is not None)

# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 4j: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
