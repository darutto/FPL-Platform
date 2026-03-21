"""
run_phase5o_tests.py
====================
Phase 5o: Structured Captain Debug and Example Parity

Tests that verify:
  A. run() debug=True includes captain payload for captain_score OK turns
  B. run() debug=True captain payload has correct keys and values (Salah)
  C. run() debug=True has no captain key for non-captain turns
  D. run() debug=False unchanged (plain text, no captain key)
  E. run_session() includes captain in turn dict for captain_score turns
  F. run_session() non-captain turns have no captain key
  G. _serial_captain shape matches HTTP _captain_meta_dict shape
  H. CLI scenario captain_debug: JSON output parses and includes captain payload
  I. HTTP scenario captain_structured: response body has captain payload
  J. Session scenario captain_structured: response body has captain payload
  K. Shape identity: CLI debug == HTTP == session for captain payload
  L. Regression: comparison debug/structured scenarios still work; session inspect unchanged

Run::

    cd packages/fpl-grounded-assistant
    python run_phase5o_tests.py
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


def ok(label: str, expr: bool, detail: str = "") -> None:
    global _passed, _failed
    if expr:
        _passed += 1
    else:
        _failed += 1
        msg = f"FAIL  {label}"
        if detail:
            msg += f"\n      {detail}"
        print(msg)


# ===========================================================================
# Imports
# ===========================================================================

from fpl_cli import run, run_session, _serial_captain  # noqa: E402
from fpl_grounded_assistant import STANDARD_BOOTSTRAP  # noqa: E402
import fpl_server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from examples.cli_examples import CLI_SCENARIOS, run_cli_scenario  # noqa: E402
from examples.http_examples import HTTP_SCENARIOS, run_http_scenario  # noqa: E402
from examples.session_examples import SESSION_FLOWS, run_session_flow, make_session_client  # noqa: E402


# ===========================================================================
# Section A -- run() debug=True includes captain payload
# ===========================================================================
print("\n--- A: run() debug=True includes captain payload ---")

exit_a, output_a = run("should I captain Salah", STANDARD_BOOTSTRAP, debug=True)
ok("A1  exit code 0", exit_a == 0, str(exit_a))

body_a: dict = {}
try:
    body_a = json.loads(output_a)
    ok("A2  output parses as JSON", True)
except json.JSONDecodeError as exc:
    ok("A2  output parses as JSON", False, str(exc))

ok("A3  captain key present in debug JSON",
   "captain" in body_a, str(list(body_a.keys())))
ok("A4  final_text still present",
   "final_text" in body_a, str(list(body_a.keys())))
ok("A5  outcome == ok",
   body_a.get("outcome") == "ok", repr(body_a.get("outcome")))
ok("A6  intent == captain_score",
   body_a.get("intent") == "captain_score", repr(body_a.get("intent")))
ok("A7  captain is a dict (not None)",
   isinstance(body_a.get("captain"), dict), str(type(body_a.get("captain"))))


# ===========================================================================
# Section B -- captain payload keys and values (Salah)
# ===========================================================================
print("\n--- B: run() debug=True captain payload keys and values ---")

capt_a = body_a.get("captain", {})

ok("B1  web_name key present",      "web_name" in capt_a,        str(list(capt_a.keys())))
ok("B2  team_short key present",    "team_short" in capt_a,      str(list(capt_a.keys())))
ok("B3  captain_score key present", "captain_score" in capt_a,   str(list(capt_a.keys())))
ok("B4  tier key present",          "tier" in capt_a,            str(list(capt_a.keys())))
ok("B5  role_bonus key present",    "role_bonus" in capt_a,      str(list(capt_a.keys())))
ok("B6  set_piece_notes key present", "set_piece_notes" in capt_a, str(list(capt_a.keys())))
ok("B7  exactly 6 keys",
   set(capt_a.keys()) == {"web_name", "team_short", "captain_score", "tier", "role_bonus", "set_piece_notes"},
   str(set(capt_a.keys())))

ok("B8  web_name == Salah",           capt_a.get("web_name") == "Salah",  repr(capt_a.get("web_name")))
ok("B9  team_short == LIV",           capt_a.get("team_short") == "LIV",  repr(capt_a.get("team_short")))
ok("B10 captain_score > 0",           isinstance(capt_a.get("captain_score"), (int, float)) and capt_a.get("captain_score", 0) > 0)
ok("B11 tier == safe",                capt_a.get("tier") == "safe",       repr(capt_a.get("tier")))
ok("B12 role_bonus == 5.0",           capt_a.get("role_bonus") == 5.0,    repr(capt_a.get("role_bonus")))
ok("B13 set_piece_notes is list",     isinstance(capt_a.get("set_piece_notes"), list))
ok("B14 set_piece_notes == ['penalty_taker_1']",
   capt_a.get("set_piece_notes") == ["penalty_taker_1"],
   repr(capt_a.get("set_piece_notes")))


# ===========================================================================
# Section C -- run() debug=True has no captain key for non-captain turns
# ===========================================================================
print("\n--- C: run() debug=True no captain for non-captain turns ---")

_, out_cmp = run("compare Haaland and Saka", STANDARD_BOOTSTRAP, debug=True)
body_cmp = json.loads(out_cmp)
ok("C1  comparison debug JSON has no captain key",
   "captain" not in body_cmp, str(list(body_cmp.keys())))
ok("C2  comparison debug JSON has comparison key",
   "comparison" in body_cmp, str(list(body_cmp.keys())))

_, out_gw = run("what is the current gameweek", STANDARD_BOOTSTRAP, debug=True)
body_gw = json.loads(out_gw)
ok("C3  gameweek debug JSON has no captain key",
   "captain" not in body_gw, str(list(body_gw.keys())))

_, out_nf = run("should I captain xyznotaplayer999", STANDARD_BOOTSTRAP, debug=True)
body_nf = json.loads(out_nf)
ok("C4  not_found captain debug JSON has no captain key",
   "captain" not in body_nf, str(list(body_nf.keys())))

_, out_uns = run("Is Haaland fit to play?", STANDARD_BOOTSTRAP, debug=True)
body_uns = json.loads(out_uns)
ok("C5  unsupported_intent debug JSON has no captain key",
   "captain" not in body_uns, str(list(body_uns.keys())))


# ===========================================================================
# Section D -- run() debug=False unchanged (plain text)
# ===========================================================================
print("\n--- D: run() debug=False unchanged ---")

exit_d, output_d = run("should I captain Salah", STANDARD_BOOTSTRAP, debug=False)
ok("D1  exit code 0", exit_d == 0, str(exit_d))
ok("D2  output is plain text (not JSON)",
   not output_d.strip().startswith("{"), output_d[:60])
ok("D3  output is non-empty", len(output_d.strip()) > 0)

try:
    json.loads(output_d)
    ok("D4  plain text output is not JSON", False, "parsed as JSON unexpectedly")
except json.JSONDecodeError:
    ok("D4  plain text output is not JSON", True)


# ===========================================================================
# Section E -- run_session() includes captain in turn dict
# ===========================================================================
print("\n--- E: run_session() captain in turn dict ---")

_sess_turns = run_session(
    ["should I captain Salah"],
    STANDARD_BOOTSTRAP,
)
ok("E1  run_session returns list",   isinstance(_sess_turns, list))
ok("E2  one turn result",            len(_sess_turns) == 1)

_t1 = _sess_turns[0] if _sess_turns else {}
ok("E3  turn has captain key",       "captain" in _t1, str(list(_t1.keys())))
ok("E4  turn captain is dict",       isinstance(_t1.get("captain"), dict))
ok("E5  turn captain.web_name",      _t1.get("captain", {}).get("web_name") == "Salah")
ok("E6  turn captain.tier",          _t1.get("captain", {}).get("tier") == "safe")
ok("E7  turn has final_text",        "final_text" in _t1)


# ===========================================================================
# Section F -- run_session() non-captain turns have no captain key
# ===========================================================================
print("\n--- F: run_session() non-captain turns no captain key ---")

_multi = run_session(
    ["should I captain Salah", "compare Haaland and Saka", "what is the current gameweek"],
    STANDARD_BOOTSTRAP,
)
ok("F1  three turns returned",         len(_multi) == 3)

_t_cap  = _multi[0] if len(_multi) > 0 else {}
_t_cmp  = _multi[1] if len(_multi) > 1 else {}
_t_gw   = _multi[2] if len(_multi) > 2 else {}

ok("F2  captain turn has captain key",    "captain" in _t_cap)
ok("F3  comparison turn has no captain",  "captain" not in _t_cmp,  str(list(_t_cmp.keys())))
ok("F4  comparison turn has comparison",  "comparison" in _t_cmp)
ok("F5  gameweek turn has no captain",    "captain" not in _t_gw,   str(list(_t_gw.keys())))


# ===========================================================================
# Section G -- _serial_captain matches _captain_meta_dict
# ===========================================================================
print("\n--- G: _serial_captain matches HTTP _captain_meta_dict ---")

from fpl_grounded_assistant.final_response import respond  # noqa: E402
from fpl_server import _captain_meta_dict                  # noqa: E402

_r = respond("should I captain Salah", STANDARD_BOOTSTRAP)
ok("G1  respond captain not None",       _r.captain is not None)

if _r.captain is not None:
    _cli_dict  = _serial_captain(_r.captain)
    _http_dict = _captain_meta_dict(_r.captain)
    ok("G2  CLI and HTTP dicts are equal",    _cli_dict == _http_dict,
       f"CLI: {_cli_dict}\nHTTP: {_http_dict}")
    ok("G3  both have exactly 6 keys",
       set(_cli_dict.keys()) == set(_http_dict.keys()) == {
           "web_name", "team_short", "captain_score", "tier", "role_bonus", "set_piece_notes"
       })
else:
    ok("G2  CLI and HTTP dicts are equal",    False, "captain was None — skip")
    ok("G3  both have exactly 6 keys",        False, "captain was None — skip")


# ===========================================================================
# Section H -- CLI scenario captain_debug
# ===========================================================================
print("\n--- H: CLI scenario captain_debug ---")

_cli_ids = [s["id"] for s in CLI_SCENARIOS]
ok("H1  captain_debug in CLI_SCENARIOS",  "captain_debug" in _cli_ids)

_capt_scenario = next((s for s in CLI_SCENARIOS if s["id"] == "captain_debug"), None)
ok("H2  scenario has debug=True",         _capt_scenario is not None and _capt_scenario.get("debug") is True)

if _capt_scenario:
    _h_exit, _h_out = run_cli_scenario(_capt_scenario)
    ok("H3  exit code matches expected",  _h_exit == _capt_scenario["expected_exit"])
    try:
        _h_body = json.loads(_h_out)
        ok("H4  output parses as JSON",   True)
    except json.JSONDecodeError:
        ok("H4  output parses as JSON",   False, _h_out[:80])
        _h_body = {}
    ok("H5  captain key present",         "captain" in _h_body, str(list(_h_body.keys())))
    ok("H6  captain.web_name == Salah",   _h_body.get("captain", {}).get("web_name") == "Salah")
    ok("H7  captain.tier == safe",        _h_body.get("captain", {}).get("tier") == "safe")
    ok("H8  captain.set_piece_notes is list",
       isinstance(_h_body.get("captain", {}).get("set_piece_notes"), list))
else:
    for label in ["H3", "H4", "H5", "H6", "H7", "H8"]:
        ok(f"{label}  (skipped — scenario not found)", False)


# ===========================================================================
# Section I -- HTTP scenario captain_structured
# ===========================================================================
print("\n--- I: HTTP scenario captain_structured ---")

_http_ids = [s["id"] for s in HTTP_SCENARIOS]
ok("I1  captain_structured in HTTP_SCENARIOS",  "captain_structured" in _http_ids)

_capt_http = next((s for s in HTTP_SCENARIOS if s["id"] == "captain_structured"), None)
ok("I2  scenario expected_outcome == ok",
   _capt_http is not None and _capt_http.get("expected_outcome") == "ok")

if _capt_http:
    _i_status, _i_body = run_http_scenario(_capt_http)
    ok("I3  HTTP 200",                    _i_status == 200, str(_i_status))
    ok("I4  supported == True",           _i_body.get("supported") is True)
    ok("I5  outcome == ok",               _i_body.get("outcome") == "ok")
    ok("I6  captain key present",         "captain" in _i_body, str(list(_i_body.keys())))
    _i_capt = _i_body.get("captain", {})
    ok("I7  captain.web_name == Salah",   _i_capt.get("web_name") == "Salah")
    ok("I8  captain.team_short == LIV",   _i_capt.get("team_short") == "LIV")
    ok("I9  captain.tier == safe",        _i_capt.get("tier") == "safe")
    ok("I10 captain.role_bonus == 5.0",   _i_capt.get("role_bonus") == 5.0)
    ok("I11 captain.set_piece_notes == ['penalty_taker_1']",
       _i_capt.get("set_piece_notes") == ["penalty_taker_1"])
else:
    for label in ["I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10", "I11"]:
        ok(f"{label}  (skipped — scenario not found)", False)


# ===========================================================================
# Section J -- Session scenario captain_structured
# ===========================================================================
print("\n--- J: Session scenario captain_structured ---")

_sess_ids = [f["id"] for f in SESSION_FLOWS]
ok("J1  captain_structured in SESSION_FLOWS",  "captain_structured" in _sess_ids)

_capt_flow = next((f for f in SESSION_FLOWS if f["id"] == "captain_structured"), None)
ok("J2  flow has one turn",
   _capt_flow is not None and len(_capt_flow.get("turns", [])) == 1)

if _capt_flow:
    _j_client = make_session_client()
    _j_result = run_session_flow(_capt_flow, _j_client)
    ok("J3  session created",      _j_result.get("create_status") == 200)
    ok("J4  turn HTTP 200",        len(_j_result.get("turns", [])) == 1 and
       _j_result["turns"][0]["status"] == 200)
    ok("J5  inspect HTTP 200",     _j_result.get("inspect_status") == 200)
    ok("J6  clear HTTP 200",       _j_result.get("clear_status") == 200)
    ok("J7  after clear HTTP 404", _j_result.get("after_clear_status") == 404)

    _j_turn_body = _j_result["turns"][0]["body"] if _j_result.get("turns") else {}
    ok("J8  captain key in turn body",   "captain" in _j_turn_body, str(list(_j_turn_body.keys())))
    _j_capt = _j_turn_body.get("captain", {})
    ok("J9  captain.web_name == Salah",  _j_capt.get("web_name") == "Salah")
    ok("J10 captain.tier == safe",       _j_capt.get("tier") == "safe")
    ok("J11 captain.role_bonus == 5.0",  _j_capt.get("role_bonus") == 5.0)
    ok("J12 captain.set_piece_notes == ['penalty_taker_1']",
       _j_capt.get("set_piece_notes") == ["penalty_taker_1"])
else:
    for label in ["J3", "J4", "J5", "J6", "J7", "J8", "J9", "J10", "J11", "J12"]:
        ok(f"{label}  (skipped — flow not found)", False)


# ===========================================================================
# Section K -- Shape identity across all three surfaces
# ===========================================================================
print("\n--- K: Shape identity across CLI, HTTP, session ---")

# Collect captain dicts from each surface (using Salah)
_k_cli_dict  = capt_a                           # from Section A (CLI debug)
_k_http_dict = _i_body.get("captain", {})       # from Section I (HTTP)
_k_sess_dict = _j_turn_body.get("captain", {})  # from Section J (session)

_expected_keys = {"web_name", "team_short", "captain_score", "tier", "role_bonus", "set_piece_notes"}

ok("K1  CLI captain has 6 expected keys",
   set(_k_cli_dict.keys()) == _expected_keys, str(set(_k_cli_dict.keys())))
ok("K2  HTTP captain has 6 expected keys",
   set(_k_http_dict.keys()) == _expected_keys, str(set(_k_http_dict.keys())))
ok("K3  session captain has 6 expected keys",
   set(_k_sess_dict.keys()) == _expected_keys, str(set(_k_sess_dict.keys())))
ok("K4  CLI == HTTP captain dict",
   _k_cli_dict == _k_http_dict, f"CLI: {_k_cli_dict}\nHTTP: {_k_http_dict}")
ok("K5  CLI == session captain dict",
   _k_cli_dict == _k_sess_dict, f"CLI: {_k_cli_dict}\nSESS: {_k_sess_dict}")


# ===========================================================================
# Section L -- Regression
# ===========================================================================
print("\n--- L: Regression ---")

# comparison_debug scenario still works
_cmp_debug_s = next((s for s in CLI_SCENARIOS if s["id"] == "comparison_debug"), None)
ok("L1  comparison_debug still in CLI_SCENARIOS", _cmp_debug_s is not None)
if _cmp_debug_s:
    _l_exit, _l_out = run_cli_scenario(_cmp_debug_s)
    _l_body = json.loads(_l_out) if _l_out.strip().startswith("{") else {}
    ok("L2  comparison_debug still works",       _l_exit == 0)
    ok("L3  comparison_debug has comparison key", "comparison" in _l_body)
    ok("L4  comparison_debug has no captain key", "captain" not in _l_body)

# comparison_structured HTTP scenario still works
_cmp_http_s = next((s for s in HTTP_SCENARIOS if s["id"] == "comparison_structured"), None)
ok("L5  comparison_structured still in HTTP_SCENARIOS", _cmp_http_s is not None)
if _cmp_http_s:
    _l_status, _l_body_http = run_http_scenario(_cmp_http_s)
    ok("L6  comparison_structured HTTP 200",       _l_status == 200)
    ok("L7  comparison_structured has comparison",  "comparison" in _l_body_http)
    ok("L8  comparison_structured captain is None", _l_body_http.get("captain") is None)

# session comparison_structured still works
_cmp_sess_f = next((f for f in SESSION_FLOWS if f["id"] == "comparison_structured"), None)
ok("L9  comparison_structured still in SESSION_FLOWS", _cmp_sess_f is not None)
if _cmp_sess_f:
    _l_s_client = make_session_client()
    _l_s_result = run_session_flow(_cmp_sess_f, _l_s_client)
    _l_s_turn = _l_s_result.get("turns", [{}])[0].get("body", {})
    ok("L10 session comparison turn has comparison",  "comparison" in _l_s_turn)
    ok("L11 session comparison turn captain is None", _l_s_turn.get("captain") is None)

# existing CLI scenarios count unchanged (or greater)
ok("L12 CLI_SCENARIOS has >= 9 entries",      len(CLI_SCENARIOS) >= 9)
ok("L13 HTTP_SCENARIOS has >= 9 entries",     len(HTTP_SCENARIOS) >= 9)
ok("L14 SESSION_FLOWS has >= 5 entries",      len(SESSION_FLOWS) >= 5)


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*60}")
print(f"Phase 5o results: {_passed}/{_passed+_failed} PASS")
print(f"{'='*60}")
if _failed:
    sys.exit(1)
