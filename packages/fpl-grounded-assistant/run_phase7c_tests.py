"""
run_phase7c_tests.py
====================
Phase 7c: Transfer + Chip Debug and Example Parity -- test suite.

Target: ~95 assertions across 10 sections.

Sections
--------
A  CLI transfer_debug scenario -- JSON includes transfer payload (10)
B  CLI chip_debug scenario -- JSON includes chip payload (10)
C  HTTP transfer_structured scenario -- response body has transfer (10)
D  HTTP chip_structured scenario -- response body has chip (8)
E  Session transfer_structured flow -- transfer in session ask body (8)
F  Session chip_structured flow -- chip in session ask body (8)
G  Multi-intent session flow -- transfer and chip in sub_responses (10)
H  Absence / null field behavior -- no cross-contamination (10)
I  Shape parity -- CLI debug keys == HTTP keys == session keys (11)
J  Regression -- earlier structured scenarios unaffected (10)
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


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import fpl_server
from fastapi.testclient import TestClient
from fpl_grounded_assistant import STANDARD_BOOTSTRAP

from examples.cli_examples import CLI_SCENARIOS, run_cli_scenario
from examples.http_examples import HTTP_SCENARIOS, run_http_scenario
from examples.session_examples import SESSION_FLOWS, run_session_flow, make_session_client


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def check(cond: bool, label: str) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
        print(f"  FAIL: {label}")


def section(name: str) -> None:
    print(f"\n--- {name} ---")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

BS = STANDARD_BOOTSTRAP
fpl_server._init_bootstrap(BS)
_client = TestClient(fpl_server.app, raise_server_exceptions=True)

_TRANSFER_KEYS = {"player_out", "player_in", "recommendation", "score_delta",
                  "price_delta", "reasons"}
_CHIP_KEYS     = {"chip", "recommendation", "gw", "signal_value", "signal_label"}
_VALID_TRANSFER_RECS = {"transfer_in", "marginal_transfer_in", "hold"}
_VALID_CHIP_RECS     = {"conditions_favorable", "conditions_marginal",
                        "conditions_unfavorable", "missing_context"}


# ===========================================================================
# Section A -- CLI transfer_debug scenario (10)
# ===========================================================================

section("A -- CLI transfer_debug scenario")

_s_transfer_debug = next(
    (s for s in CLI_SCENARIOS if s["id"] == "transfer_debug"), None
)
check(_s_transfer_debug is not None,
      "A1: transfer_debug scenario exists in CLI_SCENARIOS")

if _s_transfer_debug:
    _exit_a, _out_a = run_cli_scenario(_s_transfer_debug)
    check(_exit_a == 0,
          "A2: transfer_debug exit_code == 0")
    _body_a: dict = {}
    try:
        _body_a = json.loads(_out_a)
    except Exception:
        pass
    check(isinstance(_body_a, dict),
          "A3: transfer_debug output is valid JSON")
    check("transfer" in _body_a,
          "A4: transfer key present in debug JSON")
    check(_body_a.get("intent") == "transfer_advice",
          "A5: intent == transfer_advice")
    check(_body_a.get("outcome") == "ok",
          "A6: outcome == ok")
    _t_a = _body_a.get("transfer") or {}
    check(set(_t_a.keys()) == _TRANSFER_KEYS,
          "A7: transfer dict has exactly the expected keys")
    check(_t_a.get("player_out") not in ("", None),
          "A8: transfer.player_out non-empty")
    check(_t_a.get("player_in") not in ("", None),
          "A9: transfer.player_in non-empty")
    check(_t_a.get("recommendation") in _VALID_TRANSFER_RECS,
          "A10: transfer.recommendation in valid vocab")
else:
    for i in range(2, 11):
        check(False, f"A{i}: skipped — transfer_debug scenario missing")


# ===========================================================================
# Section B -- CLI chip_debug scenario (10)
# ===========================================================================

section("B -- CLI chip_debug scenario")

_s_chip_debug = next(
    (s for s in CLI_SCENARIOS if s["id"] == "chip_debug"), None
)
check(_s_chip_debug is not None,
      "B1: chip_debug scenario exists in CLI_SCENARIOS")

if _s_chip_debug:
    _exit_b, _out_b = run_cli_scenario(_s_chip_debug)
    check(_exit_b == 0,
          "B2: chip_debug exit_code == 0")
    _body_b: dict = {}
    try:
        _body_b = json.loads(_out_b)
    except Exception:
        pass
    check(isinstance(_body_b, dict),
          "B3: chip_debug output is valid JSON")
    check("chip" in _body_b,
          "B4: chip key present in debug JSON")
    check(_body_b.get("intent") == "chip_advice",
          "B5: intent == chip_advice")
    check(_body_b.get("outcome") == "ok",
          "B6: outcome == ok")
    _c_b = _body_b.get("chip") or {}
    check(set(_c_b.keys()) == _CHIP_KEYS,
          "B7: chip dict has exactly the expected keys")
    check(_c_b.get("chip") == "triple_captain",
          "B8: chip.chip == triple_captain")
    check(_c_b.get("recommendation") in _VALID_CHIP_RECS,
          "B9: chip.recommendation in valid vocab")
    check("signal_value" in _c_b and "signal_label" in _c_b,
          "B10: chip signal fields present")
else:
    for i in range(2, 11):
        check(False, f"B{i}: skipped — chip_debug scenario missing")


# ===========================================================================
# Section C -- HTTP transfer_structured scenario (10)
# ===========================================================================

section("C -- HTTP transfer_structured scenario")

_s_transfer_http = next(
    (s for s in HTTP_SCENARIOS if s["id"] == "transfer_structured"), None
)
check(_s_transfer_http is not None,
      "C1: transfer_structured scenario exists in HTTP_SCENARIOS")

if _s_transfer_http:
    _status_c, _body_c = run_http_scenario(_s_transfer_http)
    check(_status_c == 200,
          "C2: HTTP status 200")
    check(_body_c.get("supported") is True,
          "C3: supported == True")
    check(_body_c.get("outcome") == "ok",
          "C4: outcome == ok")
    check(_body_c.get("transfer") is not None,
          "C5: transfer not null in response body")
    _t_c = _body_c.get("transfer") or {}
    check(set(_t_c.keys()) == _TRANSFER_KEYS,
          "C6: HTTP transfer dict has exactly the expected keys")
    check(_t_c.get("player_out") not in ("", None),
          "C7: transfer.player_out non-empty")
    check(_t_c.get("player_in") not in ("", None),
          "C8: transfer.player_in non-empty")
    check(_t_c.get("recommendation") in _VALID_TRANSFER_RECS,
          "C9: transfer.recommendation in valid vocab")
    check(isinstance(_t_c.get("reasons"), list),
          "C10: transfer.reasons is a list")
else:
    for i in range(2, 11):
        check(False, f"C{i}: skipped — transfer_structured scenario missing")


# ===========================================================================
# Section D -- HTTP chip_structured scenario (8)
# ===========================================================================

section("D -- HTTP chip_structured scenario")

_s_chip_http = next(
    (s for s in HTTP_SCENARIOS if s["id"] == "chip_structured"), None
)
check(_s_chip_http is not None,
      "D1: chip_structured scenario exists in HTTP_SCENARIOS")

if _s_chip_http:
    _status_d, _body_d = run_http_scenario(_s_chip_http)
    check(_status_d == 200,
          "D2: HTTP status 200")
    check(_body_d.get("outcome") == "ok",
          "D3: outcome == ok")
    check(_body_d.get("chip") is not None,
          "D4: chip not null in response body")
    _c_d = _body_d.get("chip") or {}
    check(set(_c_d.keys()) == _CHIP_KEYS,
          "D5: HTTP chip dict has exactly the expected keys")
    check(_c_d.get("chip") == "triple_captain",
          "D6: chip.chip == triple_captain")
    check(_c_d.get("recommendation") in _VALID_CHIP_RECS,
          "D7: chip.recommendation in valid vocab")
    check((_c_d.get("signal_value") is None) == (_c_d.get("signal_label") is None),
          "D8: signal_value and signal_label both null or both present")
else:
    for i in range(2, 9):
        check(False, f"D{i}: skipped — chip_structured scenario missing")


# ===========================================================================
# Section E -- Session transfer_structured flow (8)
# ===========================================================================

section("E -- Session transfer_structured flow")

_sess_client = make_session_client()

_flow_transfer = next(
    (f for f in SESSION_FLOWS if f["id"] == "transfer_structured"), None
)
check(_flow_transfer is not None,
      "E1: transfer_structured flow exists in SESSION_FLOWS")

if _flow_transfer:
    _res_e = run_session_flow(_flow_transfer, _sess_client)
    check(_res_e.get("create_status") == 200,
          "E2: session create succeeded")
    _turns_e = _res_e.get("turns", [])
    check(len(_turns_e) == 1,
          "E3: one turn in transfer flow")
    _turn_e = _turns_e[0] if _turns_e else {}
    check(_turn_e.get("status") == 200,
          "E4: turn status 200")
    _body_e = _turn_e.get("body", {})
    check(_body_e.get("transfer") is not None,
          "E5: transfer not null in session ask body")
    _t_e = _body_e.get("transfer") or {}
    check(_t_e.get("player_out") not in ("", None),
          "E6: session transfer.player_out non-empty")
    check(_t_e.get("recommendation") in _VALID_TRANSFER_RECS,
          "E7: session transfer.recommendation in valid vocab")
    check(_res_e.get("clear_status") == 200 and
          _res_e.get("after_clear_status") == 404,
          "E8: session lifecycle clean (clear → 404)")
else:
    for i in range(2, 9):
        check(False, f"E{i}: skipped — transfer_structured flow missing")


# ===========================================================================
# Section F -- Session chip_structured flow (8)
# ===========================================================================

section("F -- Session chip_structured flow")

_flow_chip = next(
    (f for f in SESSION_FLOWS if f["id"] == "chip_structured"), None
)
check(_flow_chip is not None,
      "F1: chip_structured flow exists in SESSION_FLOWS")

if _flow_chip:
    _sess_client2 = make_session_client()
    _res_f = run_session_flow(_flow_chip, _sess_client2)
    check(_res_f.get("create_status") == 200,
          "F2: session create succeeded")
    _turns_f = _res_f.get("turns", [])
    _turn_f = _turns_f[0] if _turns_f else {}
    check(_turn_f.get("status") == 200,
          "F3: turn status 200")
    _body_f = _turn_f.get("body", {})
    check(_body_f.get("chip") is not None,
          "F4: chip not null in session ask body")
    _c_f = _body_f.get("chip") or {}
    check(_c_f.get("chip") == "triple_captain",
          "F5: session chip.chip == triple_captain")
    check(_c_f.get("recommendation") in _VALID_CHIP_RECS,
          "F6: session chip.recommendation in valid vocab")
    check(set(_c_f.keys()) == _CHIP_KEYS,
          "F7: session chip dict keys match expected set")
    check(_res_f.get("clear_status") == 200,
          "F8: session lifecycle clean")
else:
    for i in range(2, 9):
        check(False, f"F{i}: skipped — chip_structured flow missing")


# ===========================================================================
# Section G -- Multi-intent session flow: transfer + chip in sub_responses (10)
# ===========================================================================

section("G -- Multi-intent session: transfer + chip sub_responses")

_flow_multi = next(
    (f for f in SESSION_FLOWS if f["id"] == "multi_intent_transfer_and_chip"), None
)
check(_flow_multi is not None,
      "G1: multi_intent_transfer_and_chip flow exists in SESSION_FLOWS")

if _flow_multi:
    _sess_client3 = make_session_client()
    _res_g = run_session_flow(_flow_multi, _sess_client3)
    _turns_g = _res_g.get("turns", [])
    _turn_g = _turns_g[0] if _turns_g else {}
    check(_turn_g.get("status") == 200,
          "G2: turn status 200")
    _body_g = _turn_g.get("body", {})
    check(_body_g.get("intent") == "multi_intent",
          "G3: top-level intent == multi_intent")
    _subs_g = _body_g.get("sub_responses") or []
    check(len(_subs_g) == 2,
          "G4: two sub-responses")
    _transfer_sub = next(
        (s for s in _subs_g if s.get("intent") == "transfer_advice"), None
    )
    _chip_sub = next(
        (s for s in _subs_g if s.get("intent") == "chip_advice"), None
    )
    check(_transfer_sub is not None,
          "G5: transfer_advice sub-response present")
    check(_chip_sub is not None,
          "G6: chip_advice sub-response present")
    check(_transfer_sub is not None and _transfer_sub.get("transfer") is not None,
          "G7: transfer sub-response has transfer dict")
    check(_chip_sub is not None and _chip_sub.get("chip") is not None,
          "G8: chip sub-response has chip dict")
    # Top-level transfer/chip should be null for multi-intent (metadata lives in sub_responses)
    check(_body_g.get("transfer") is None,
          "G9: top-level transfer is null for multi-intent turn")
    check(_body_g.get("chip") is None,
          "G10: top-level chip is null for multi-intent turn")
else:
    for i in range(2, 11):
        check(False, f"G{i}: skipped — multi_intent_transfer_and_chip flow missing")


# ===========================================================================
# Section H -- Absence / null field behavior (10)
# ===========================================================================

section("H -- Absence / null field behavior")

# Captain turn: neither transfer nor chip present in HTTP response
_resp_capt = _client.post("/ask", json={"question": "should I captain Salah"})
_body_capt = _resp_capt.json() if _resp_capt.status_code == 200 else {}
check(_body_capt.get("transfer") is None,
      "H1: transfer null for captain /ask")
check(_body_capt.get("chip") is None,
      "H2: chip null for captain /ask")

# Transfer turn: chip null
_resp_xfer = _client.post("/ask", json={"question": "should I sell Saka for Salah"})
_body_xfer = _resp_xfer.json() if _resp_xfer.status_code == 200 else {}
check(_body_xfer.get("transfer") is not None,
      "H3: transfer present for transfer /ask")
check(_body_xfer.get("chip") is None,
      "H4: chip null for transfer /ask")

# Chip turn: transfer null
_resp_chip = _client.post("/ask", json={"question": "should I bench boost now"})
_body_chip = _resp_chip.json() if _resp_chip.status_code == 200 else {}
check(_body_chip.get("chip") is not None,
      "H5: chip present for chip /ask")
check(_body_chip.get("transfer") is None,
      "H6: transfer null for chip /ask")

# CLI: non-debug transfer turn — no 'transfer' key in plain text
from fpl_cli import run as _cli_run
_exit_h7, _out_h7 = _cli_run("should I sell Saka for Salah", BS, debug=False)
check("transfer" not in _out_h7,
      "H7: no 'transfer' literal in plain-text CLI output")

# CLI: non-debug chip turn — no 'chip' key in plain text
_exit_h8, _out_h8 = _cli_run("should I use triple captain this week", BS, debug=False)
check("chip_advice" not in _out_h8 and not _out_h8.startswith("{"),
      "H8: non-debug chip output is plain text (not JSON)")

# Not-found transfer: transfer null
_resp_nf = _client.post("/ask", json={"question": "should I sell Saka for UnknownXYZ"})
_body_nf = _resp_nf.json() if _resp_nf.status_code == 200 else {}
check(_body_nf.get("transfer") is None,
      "H9: transfer null for not_found transfer /ask")

# Gameweek turn: neither transfer nor chip
_resp_gw = _client.post("/ask", json={"question": "what gameweek is it"})
_body_gw = _resp_gw.json() if _resp_gw.status_code == 200 else {}
check(_body_gw.get("transfer") is None and _body_gw.get("chip") is None,
      "H10: transfer and chip both null for gameweek /ask")


# ===========================================================================
# Section I -- Shape parity: CLI == HTTP == session keys (11)
# ===========================================================================

section("I -- Shape parity: CLI == HTTP == session keys")

# -- Transfer key parity --
from fpl_cli import run_session as _cli_run_session
_turns_i_xfer = _cli_run_session(["should I sell Saka for Salah"], BS)
_t_cli_keys   = set((_turns_i_xfer[0].get("transfer") or {}).keys())
_t_http_keys  = set((_body_xfer.get("transfer") or {}).keys())

check(_t_cli_keys == _TRANSFER_KEYS,
      "I1: CLI session transfer keys match expected set")
check(_t_http_keys == _TRANSFER_KEYS,
      "I2: HTTP /ask transfer keys match expected set")
check(_t_cli_keys == _t_http_keys,
      "I3: CLI session transfer keys == HTTP transfer keys")

# Transfer keys from /session/{id}/ask
fpl_server._clear_sessions()
_sess_i = _client.post("/session")
_sid_i  = _sess_i.json()["session_id"]
_resp_i_sess_xfer = _client.post(
    f"/session/{_sid_i}/ask",
    json={"question": "should I sell Saka for Salah"},
)
_body_i_sess_xfer = _resp_i_sess_xfer.json() if _resp_i_sess_xfer.status_code == 200 else {}
_t_sess_keys = set((_body_i_sess_xfer.get("transfer") or {}).keys())
check(_t_sess_keys == _TRANSFER_KEYS,
      "I4: session /ask transfer keys match expected set")
check(_t_sess_keys == _t_http_keys,
      "I5: session /ask transfer keys == HTTP /ask transfer keys")

# -- Chip key parity --
_turns_i_chip = _cli_run_session(["should I use triple captain this week"], BS)
_c_cli_keys   = set((_turns_i_chip[0].get("chip") or {}).keys())
_c_http_keys  = set((_body_chip.get("chip") or {}).keys())

check(_c_cli_keys == _CHIP_KEYS,
      "I6: CLI session chip keys match expected set")
check(_c_http_keys == _CHIP_KEYS,
      "I7: HTTP /ask chip keys match expected set")
check(_c_cli_keys == _c_http_keys,
      "I8: CLI session chip keys == HTTP chip keys")

_resp_i_sess_chip = _client.post(
    f"/session/{_sid_i}/ask",
    json={"question": "should I bench boost now"},
)
_body_i_sess_chip = _resp_i_sess_chip.json() if _resp_i_sess_chip.status_code == 200 else {}
_c_sess_keys = set((_body_i_sess_chip.get("chip") or {}).keys())
check(_c_sess_keys == _CHIP_KEYS,
      "I9: session /ask chip keys match expected set")
check(_c_sess_keys == _c_http_keys,
      "I10: session /ask chip keys == HTTP /ask chip keys")

_client.delete(f"/session/{_sid_i}")
check(True, "I11: section I cleanup")


# ===========================================================================
# Section J -- Regression: earlier structured scenarios unaffected (10)
# ===========================================================================

section("J -- Regression: earlier structured scenarios unaffected")

# CLI: captain_debug still works
_s_cap_debug = next((s for s in CLI_SCENARIOS if s["id"] == "captain_debug"), None)
if _s_cap_debug:
    _exit_j1, _out_j1 = run_cli_scenario(_s_cap_debug)
    _body_j1: dict = {}
    try:
        _body_j1 = json.loads(_out_j1)
    except Exception:
        pass
    check(_exit_j1 == 0 and "captain" in _body_j1,
          "J1: CLI captain_debug still produces captain key in JSON")
else:
    check(False, "J1: captain_debug scenario missing from CLI_SCENARIOS")

# CLI: comparison_debug still works
_s_comp_debug = next((s for s in CLI_SCENARIOS if s["id"] == "comparison_debug"), None)
if _s_comp_debug:
    _exit_j2, _out_j2 = run_cli_scenario(_s_comp_debug)
    _body_j2: dict = {}
    try:
        _body_j2 = json.loads(_out_j2)
    except Exception:
        pass
    check(_exit_j2 == 0 and "comparison" in _body_j2,
          "J2: CLI comparison_debug still produces comparison key in JSON")
else:
    check(False, "J2: comparison_debug scenario missing from CLI_SCENARIOS")

# HTTP: captain_structured still works
_s_cap_http = next((s for s in HTTP_SCENARIOS if s["id"] == "captain_structured"), None)
if _s_cap_http:
    _st_j3, _body_j3 = run_http_scenario(_s_cap_http)
    check(_st_j3 == 200 and _body_j3.get("captain") is not None,
          "J3: HTTP captain_structured still has captain in body")
else:
    check(False, "J3: captain_structured scenario missing from HTTP_SCENARIOS")

# HTTP: comparison_structured still works
_s_comp_http = next((s for s in HTTP_SCENARIOS if s["id"] == "comparison_structured"), None)
if _s_comp_http:
    _st_j4, _body_j4 = run_http_scenario(_s_comp_http)
    check(_st_j4 == 200 and _body_j4.get("comparison") is not None,
          "J4: HTTP comparison_structured still has comparison in body")
else:
    check(False, "J4: comparison_structured scenario missing from HTTP_SCENARIOS")

# Session: captain_structured still works
_sess_client_j = make_session_client()
_flow_cap_sess = next((f for f in SESSION_FLOWS if f["id"] == "captain_structured"), None)
if _flow_cap_sess:
    _res_j5 = run_session_flow(_flow_cap_sess, _sess_client_j)
    _body_j5 = (_res_j5.get("turns") or [{}])[0].get("body", {})
    check(_res_j5.get("create_status") == 200 and _body_j5.get("captain") is not None,
          "J5: session captain_structured still has captain in turn body")
else:
    check(False, "J5: captain_structured flow missing from SESSION_FLOWS")

# All pre-7c HTTP_SCENARIOS produce expected HTTP status (count >= 10 pre-7c scenarios)
_pre_7c_http = [s for s in HTTP_SCENARIOS if s["id"] not in
                {"transfer_structured", "chip_structured"}]
_http_all_pass = all(
    run_http_scenario(s)[0] == s["expected_status"]
    for s in _pre_7c_http
)
check(_http_all_pass,
      "J6: all pre-7c HTTP_SCENARIOS produce expected HTTP status")

# All pre-7c CLI_SCENARIOS produce expected exit code (count >= 9 pre-7c scenarios)
_pre_7c_cli = [s for s in CLI_SCENARIOS if s["id"] not in
               {"transfer_debug", "chip_debug"}]
_cli_all_pass = all(
    run_cli_scenario(s)[0] == s["expected_exit"]
    for s in _pre_7c_cli
)
check(_cli_all_pass,
      "J7: all pre-7c CLI_SCENARIOS produce expected exit code")

# All pre-7c SESSION_FLOWS lifecycle passes
_pre_7c_sess = [f for f in SESSION_FLOWS if f["id"] not in
                {"transfer_structured", "chip_structured", "multi_intent_transfer_and_chip"}]
_sess_client_j2 = make_session_client()
_sess_all_pass = True
for _flow_j in _pre_7c_sess:
    _r = run_session_flow(_flow_j, _sess_client_j2)
    if not (
        _r.get("create_status") == 200
        and _r.get("clear_status") == 200
        and _r.get("after_clear_status") == 404
        and all(t["status"] == 200 for t in _r.get("turns", []))
    ):
        _sess_all_pass = False
        break
check(_sess_all_pass,
      "J8: all pre-7c SESSION_FLOWS lifecycle passes")

# Scenario count checks: examples grew by expected amount
check(sum(1 for s in CLI_SCENARIOS if s["id"] in {"transfer_debug", "chip_debug"}) == 2,
      "J9: exactly 2 new CLI scenarios added (transfer_debug, chip_debug)")
check(sum(1 for s in HTTP_SCENARIOS if s["id"] in {"transfer_structured", "chip_structured"}) == 2,
      "J10: exactly 2 new HTTP scenarios added (transfer_structured, chip_structured)")


# ===========================================================================
# Summary
# ===========================================================================

total = _PASS + _FAIL
print(f"\n{'='*50}")
print(f"Phase 7c: {_PASS}/{total} PASS")
if _FAIL:
    print(f"          {_FAIL} FAIL")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
