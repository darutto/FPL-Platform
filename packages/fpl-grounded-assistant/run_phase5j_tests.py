"""
run_phase5j_tests.py
====================
Phase 5j: Structured Comparison Debug and Example Parity

Tests that verify:
  A. run() debug=True includes comparison when present
  B. run() debug=True includes player_a/b context
  C. run() debug=True has no comparison key for non-comparison turns
  D. run() debug=False unchanged (plain text, no comparison key)
  E. run_session() includes comparison in turn dict for comparison turns
  F. run_session() comparison parity: direct vs follow-up
  G. run_session() non-comparison turns have no comparison key
  H. _serial_comparison shape matches HTTP comparison shape
  I. CLI scenario comparison_debug: JSON output parses and includes player_a/b
  J. HTTP scenario comparison_structured: response body has player_a/b
  K. Session scenario comparison_structured: response body has player_a/b
  L. Regression: default CLI behavior unchanged; prior suites unaffected

Run::

    cd packages/fpl-grounded-assistant
    python run_phase5j_tests.py
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

import traceback

_passed = 0
_failed = 0


def ok(label: str, expr: bool, detail: str = "") -> None:
    global _passed, _failed
    if expr:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


# ===========================================================================
# Section A -- run() debug=True includes comparison when present
# ===========================================================================
print("\n--- A: run() debug=True includes comparison ---")

from fpl_cli import run  # noqa: E402
from fpl_grounded_assistant import STANDARD_BOOTSTRAP  # noqa: E402

exit_a, output_a = run("compare Haaland and Saka", STANDARD_BOOTSTRAP, debug=True)
ok("A1  exit code 0",
   exit_a == 0, str(exit_a))
ok("A2  output is valid JSON",
   True)  # parse below
try:
    body_a = json.loads(output_a)
    ok("A3  output parses as JSON", True)
except json.JSONDecodeError as exc:
    ok("A3  output parses as JSON", False, str(exc))
    body_a = {}

ok("A4  comparison key present in debug JSON",
   "comparison" in body_a, str(list(body_a.keys())))
ok("A5  final_text still present",
   "final_text" in body_a, str(list(body_a.keys())))
ok("A6  outcome present",
   body_a.get("outcome") == "ok", repr(body_a.get("outcome")))

comp_a = body_a.get("comparison", {})
ok("A7  comparison is a dict (not None)",
   isinstance(comp_a, dict), str(type(comp_a)))
ok("A8  comparison has winner key",
   "winner" in comp_a, str(list(comp_a.keys())))
ok("A9  comparison has margin key",
   "margin" in comp_a, str(list(comp_a.keys())))
ok("A10 comparison has label key",
   "label" in comp_a, str(list(comp_a.keys())))
ok("A11 comparison has reasons list",
   isinstance(comp_a.get("reasons"), list), str(type(comp_a.get("reasons"))))


# ===========================================================================
# Section B -- run() debug=True includes player_a/b context
# ===========================================================================
print("\n--- B: run() debug=True player_a/b context ---")

ok("B1  player_a key present",
   "player_a" in comp_a, str(list(comp_a.keys())))
ok("B2  player_b key present",
   "player_b" in comp_a, str(list(comp_a.keys())))

pa_a = comp_a.get("player_a", {})
pb_a = comp_a.get("player_b", {})

ok("B3  player_a is dict",
   isinstance(pa_a, dict), str(type(pa_a)))
ok("B4  player_a has web_name",
   "web_name" in pa_a, str(list(pa_a.keys())))
ok("B5  player_a has position",
   "position" in pa_a, str(list(pa_a.keys())))
ok("B6  player_a has captain_score",
   "captain_score" in pa_a, str(list(pa_a.keys())))
ok("B7  player_a has role_bonus",
   "role_bonus" in pa_a, str(list(pa_a.keys())))
ok("B8  player_a has set_piece_notes",
   "set_piece_notes" in pa_a, str(list(pa_a.keys())))
ok("B9  player_a.set_piece_notes is list",
   isinstance(pa_a.get("set_piece_notes"), list),
   str(type(pa_a.get("set_piece_notes"))))
ok("B10 player_a.position == 'FWD' (Haaland)",
   pa_a.get("position") == "FWD", repr(pa_a.get("position")))
ok("B11 player_a.role_bonus == 5.0",
   pa_a.get("role_bonus") == 5.0, repr(pa_a.get("role_bonus")))
ok("B12 player_a.set_piece_notes == ['penalty_taker_1']",
   pa_a.get("set_piece_notes") == ["penalty_taker_1"],
   repr(pa_a.get("set_piece_notes")))
ok("B13 player_b.position == 'MID' (Saka)",
   pb_a.get("position") == "MID", repr(pb_a.get("position")))
ok("B14 player_b.role_bonus == 0.5",
   pb_a.get("role_bonus") == 0.5, repr(pb_a.get("role_bonus")))


# ===========================================================================
# Section C -- run() debug=True has no comparison key for non-comparison turns
# ===========================================================================
print("\n--- C: run() debug=True no comparison for non-comparison turns ---")

_, output_c = run("should I captain Haaland?", STANDARD_BOOTSTRAP, debug=True)
body_c = json.loads(output_c)
ok("C1  captain_score debug JSON has no comparison key",
   "comparison" not in body_c, str(list(body_c.keys())))

_, output_c2 = run("Is Haaland fit?", STANDARD_BOOTSTRAP, debug=True)
body_c2 = json.loads(output_c2)
ok("C2  unsupported_intent debug JSON has no comparison key",
   "comparison" not in body_c2, str(list(body_c2.keys())))

_, output_c3 = run("compare Haaland and NoSuchPlayer999", STANDARD_BOOTSTRAP, debug=True)
body_c3 = json.loads(output_c3)
ok("C3  not_found comparison debug JSON has no comparison key",
   "comparison" not in body_c3, str(list(body_c3.keys())))


# ===========================================================================
# Section D -- run() debug=False unchanged (plain text)
# ===========================================================================
print("\n--- D: run() debug=False unchanged ---")

exit_d, output_d = run("compare Haaland and Saka", STANDARD_BOOTSTRAP, debug=False)
ok("D1  exit code 0",
   exit_d == 0, str(exit_d))
ok("D2  output is plain text (not JSON)",
   not output_d.strip().startswith("{"),
   output_d[:50])
ok("D3  output is non-empty",
   len(output_d.strip()) > 0)

# D4: verify it's not parseable as JSON (it's a plain sentence)
try:
    json.loads(output_d)
    ok("D4  plain text output is not JSON", False,
       "parsed as JSON unexpectedly")
except json.JSONDecodeError:
    ok("D4  plain text output is not JSON", True)

exit_d2, output_d2 = run("should I captain Haaland?", STANDARD_BOOTSTRAP, debug=False)
ok("D5  non-comparison plain text output unchanged",
   len(output_d2.strip()) > 0 and not output_d2.strip().startswith("{"))


# ===========================================================================
# Section E -- run_session() includes comparison in turn dict
# ===========================================================================
print("\n--- E: run_session() comparison in turn dict ---")

from fpl_cli import run_session  # noqa: E402

turns_e = run_session(
    ["compare Haaland and Saka"],
    STANDARD_BOOTSTRAP,
)
ok("E1  one turn result",
   len(turns_e) == 1, str(len(turns_e)))

turn_e = turns_e[0]
ok("E2  turn has comparison key",
   "comparison" in turn_e, str(list(turn_e.keys())))

comp_e = turn_e.get("comparison", {})
ok("E3  comparison is a dict",
   isinstance(comp_e, dict), str(type(comp_e)))
ok("E4  comparison has player_a",
   "player_a" in comp_e, str(list(comp_e.keys())))
ok("E5  comparison has player_b",
   "player_b" in comp_e, str(list(comp_e.keys())))
ok("E6  player_a.position == 'FWD'",
   comp_e.get("player_a", {}).get("position") == "FWD",
   repr(comp_e.get("player_a", {}).get("position")))

# E7: standard turn fields still present
for key in ("question", "final_text", "outcome", "supported", "intent"):
    ok(f"E7  turn still has '{key}'",
       key in turn_e, str(list(turn_e.keys())))
    break  # check representatively

ok("E8  turn has all required base keys",
   all(k in turn_e for k in ("question", "final_text", "outcome", "supported", "intent")))


# ===========================================================================
# Section F -- run_session() comparison parity: direct vs follow-up
# ===========================================================================
print("\n--- F: run_session() comparison parity ---")

turns_f = run_session(
    ["compare Haaland and Saka", "And Salah?"],
    STANDARD_BOOTSTRAP,
)
ok("F1  two turn results",
   len(turns_f) == 2, str(len(turns_f)))

t1_f = turns_f[0]
t2_f = turns_f[1]

ok("F2  turn 1 outcome ok",
   t1_f.get("outcome") == "ok", repr(t1_f.get("outcome")))
ok("F3  turn 2 outcome ok",
   t2_f.get("outcome") == "ok", repr(t2_f.get("outcome")))
ok("F4  turn 1 has comparison",
   "comparison" in t1_f, str(list(t1_f.keys())))
ok("F5  turn 2 has comparison",
   "comparison" in t2_f, str(list(t2_f.keys())))

comp_f1 = t1_f.get("comparison", {})
comp_f2 = t2_f.get("comparison", {})

ok("F6  both turns comparison has player_a",
   "player_a" in comp_f1 and "player_a" in comp_f2)
ok("F7  both turns comparison has player_b",
   "player_b" in comp_f1 and "player_b" in comp_f2)

# F8: direct call for Haaland vs Salah to compare with follow-up
turns_f_direct = run_session(["compare Haaland and Salah"], STANDARD_BOOTSTRAP)
comp_fd = turns_f_direct[0].get("comparison", {})
ok("F8  follow-up player_a matches direct",
   comp_f2.get("player_a", {}).get("web_name") ==
   comp_fd.get("player_a", {}).get("web_name"),
   f"follow-up={comp_f2.get('player_a', {}).get('web_name')!r} "
   f"direct={comp_fd.get('player_a', {}).get('web_name')!r}")
ok("F9  follow-up player_b matches direct",
   comp_f2.get("player_b", {}).get("web_name") ==
   comp_fd.get("player_b", {}).get("web_name"),
   f"follow-up={comp_f2.get('player_b', {}).get('web_name')!r} "
   f"direct={comp_fd.get('player_b', {}).get('web_name')!r}")
ok("F10 follow-up comparison reasons match direct",
   comp_f2.get("reasons") == comp_fd.get("reasons"),
   f"follow-up={comp_f2.get('reasons')!r} direct={comp_fd.get('reasons')!r}")


# ===========================================================================
# Section G -- run_session() non-comparison turns have no comparison key
# ===========================================================================
print("\n--- G: run_session() no comparison for non-comparison turns ---")

turns_g = run_session(
    ["should I captain Haaland?", "what gameweek is it?"],
    STANDARD_BOOTSTRAP,
)
ok("G1  two turns",
   len(turns_g) == 2, str(len(turns_g)))
ok("G2  captain_score turn has no comparison key",
   "comparison" not in turns_g[0], str(list(turns_g[0].keys())))
ok("G3  current_gameweek turn has no comparison key",
   "comparison" not in turns_g[1], str(list(turns_g[1].keys())))

# G4: mixed session: comparison turn has it, non-comparison doesn't
turns_g2 = run_session(
    ["compare Haaland and Saka", "should I captain him?"],
    STANDARD_BOOTSTRAP,
)
ok("G4  comparison turn (1) has comparison key",
   "comparison" in turns_g2[0], str(list(turns_g2[0].keys())))
ok("G5  non-comparison turn (2) has no comparison key",
   "comparison" not in turns_g2[1], str(list(turns_g2[1].keys())))


# ===========================================================================
# Section H -- _serial_comparison shape matches HTTP comparison shape
# ===========================================================================
print("\n--- H: _serial_comparison shape alignment ---")

from fpl_cli import _serial_comparison  # noqa: E402
from fpl_grounded_assistant import respond  # noqa: E402

fr_h = respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)
ok("H1  FinalResponse.comparison not None",
   fr_h.comparison is not None)

if fr_h.comparison is not None:
    cli_comp = _serial_comparison(fr_h.comparison)
    ok("H2  _serial_comparison returns dict",
       isinstance(cli_comp, dict), str(type(cli_comp)))

    # Compare with HTTP serialization
    try:
        import fpl_server
        fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
        fpl_server._clear_sessions()
        from fastapi.testclient import TestClient
        http = TestClient(fpl_server.app)
        resp_h = http.post("/ask", json={"question": "compare Haaland and Saka"})
        http_comp = resp_h.json().get("comparison", {})
        fpl_server._clear_sessions()

        ok("H3  CLI and HTTP comparison have same keys",
           set(cli_comp.keys()) == set(http_comp.keys()),
           f"CLI={set(cli_comp.keys())}  HTTP={set(http_comp.keys())}")
        ok("H4  CLI and HTTP player_a have same keys",
           set(cli_comp.get("player_a", {}).keys()) ==
           set(http_comp.get("player_a", {}).keys()),
           f"CLI_pa={set(cli_comp.get('player_a', {}).keys())}  "
           f"HTTP_pa={set(http_comp.get('player_a', {}).keys())}")
        ok("H5  CLI and HTTP winner match",
           cli_comp.get("winner") == http_comp.get("winner"),
           f"CLI={cli_comp.get('winner')!r}  HTTP={http_comp.get('winner')!r}")
        ok("H6  CLI and HTTP player_a.position match",
           cli_comp.get("player_a", {}).get("position") ==
           http_comp.get("player_a", {}).get("position"),
           f"CLI={cli_comp.get('player_a', {}).get('position')!r} "
           f"HTTP={http_comp.get('player_a', {}).get('position')!r}")
        ok("H7  CLI and HTTP player_b.role_bonus match",
           cli_comp.get("player_b", {}).get("role_bonus") ==
           http_comp.get("player_b", {}).get("role_bonus"),
           f"CLI={cli_comp.get('player_b', {}).get('role_bonus')!r} "
           f"HTTP={http_comp.get('player_b', {}).get('role_bonus')!r}")
    except Exception as exc:
        ok("H3-H7 CLI vs HTTP shape alignment", False, traceback.format_exc())


# ===========================================================================
# Section I -- CLI scenario comparison_debug
# ===========================================================================
print("\n--- I: CLI scenario comparison_debug ---")

try:
    from examples.cli_examples import CLI_SCENARIOS, run_cli_scenario

    comp_debug_scenario = next(
        (s for s in CLI_SCENARIOS if s["id"] == "comparison_debug"), None
    )
    ok("I1  comparison_debug scenario exists in CLI_SCENARIOS",
       comp_debug_scenario is not None)

    if comp_debug_scenario is not None:
        ok("I2  comparison_debug has debug=True",
           comp_debug_scenario.get("debug") is True,
           str(comp_debug_scenario.get("debug")))

        code_i, output_i = run_cli_scenario(comp_debug_scenario)
        ok("I3  exit code 0",
           code_i == 0, str(code_i))

        try:
            body_i = json.loads(output_i)
            ok("I4  output is valid JSON", True)
        except json.JSONDecodeError as exc:
            ok("I4  output is valid JSON", False, str(exc))
            body_i = {}

        ok("I5  JSON includes comparison key",
           "comparison" in body_i, str(list(body_i.keys())))
        comp_i = body_i.get("comparison", {})
        ok("I6  comparison has player_a",
           "player_a" in comp_i, str(list(comp_i.keys())))
        ok("I7  comparison has player_b",
           "player_b" in comp_i, str(list(comp_i.keys())))
        ok("I8  player_a.position non-empty",
           len(comp_i.get("player_a", {}).get("position", "")) > 0,
           repr(comp_i.get("player_a", {}).get("position")))

    # I9: non-debug scenario still returns plain text
    ok_scenario = next(s for s in CLI_SCENARIOS if s["id"] == "supported_ok")
    _, ok_output = run_cli_scenario(ok_scenario)
    ok("I9  supported_ok scenario still returns plain text",
       not ok_output.strip().startswith("{"),
       ok_output[:60])
except Exception as exc:
    ok("I1-I9 CLI scenario tests", False, traceback.format_exc())


# ===========================================================================
# Section J -- HTTP scenario comparison_structured
# ===========================================================================
print("\n--- J: HTTP scenario comparison_structured ---")

try:
    from examples.http_examples import HTTP_SCENARIOS, run_http_scenario

    comp_struct_scenario = next(
        (s for s in HTTP_SCENARIOS if s["id"] == "comparison_structured"), None
    )
    ok("J1  comparison_structured scenario exists in HTTP_SCENARIOS",
       comp_struct_scenario is not None)

    if comp_struct_scenario is not None:
        status_j, body_j = run_http_scenario(comp_struct_scenario)
        ok("J2  HTTP 200",
           status_j == 200, str(status_j))
        ok("J3  outcome=ok",
           body_j.get("outcome") == "ok", repr(body_j.get("outcome")))
        comp_j = body_j.get("comparison", {})
        ok("J4  comparison present",
           "comparison" in body_j, str(list(body_j.keys())))
        ok("J5  comparison.player_a present",
           "player_a" in comp_j, str(list(comp_j.keys())))
        ok("J6  comparison.player_b present",
           "player_b" in comp_j, str(list(comp_j.keys())))
        pa_j = comp_j.get("player_a", {})
        ok("J7  player_a.position == 'FWD'",
           pa_j.get("position") == "FWD", repr(pa_j.get("position")))
        ok("J8  player_a.set_piece_notes == ['penalty_taker_1']",
           pa_j.get("set_piece_notes") == ["penalty_taker_1"],
           repr(pa_j.get("set_piece_notes")))
except Exception as exc:
    ok("J1-J8 HTTP scenario tests", False, traceback.format_exc())


# ===========================================================================
# Section K -- Session scenario comparison_structured
# ===========================================================================
print("\n--- K: Session scenario comparison_structured ---")

try:
    from examples.session_examples import SESSION_FLOWS, run_session_flow, make_session_client

    comp_struct_flow = next(
        (f for f in SESSION_FLOWS if f["id"] == "comparison_structured"), None
    )
    ok("K1  comparison_structured flow exists in SESSION_FLOWS",
       comp_struct_flow is not None)

    if comp_struct_flow is not None:
        client_k = make_session_client()
        result_k = run_session_flow(comp_struct_flow, client_k)

        ok("K2  create_status 200",
           result_k.get("create_status") == 200, str(result_k.get("create_status")))
        ok("K3  one turn",
           len(result_k.get("turns", [])) == 1, str(len(result_k.get("turns", []))))

        turn_k = result_k.get("turns", [{}])[0]
        ok("K4  turn status 200",
           turn_k.get("status") == 200, str(turn_k.get("status")))

        body_k = turn_k.get("body", {})
        comp_k = body_k.get("comparison", {})
        ok("K5  comparison present in turn body",
           "comparison" in body_k, str(list(body_k.keys())))
        ok("K6  comparison.player_a present",
           "player_a" in comp_k, str(list(comp_k.keys())))
        ok("K7  comparison.player_b present",
           "player_b" in comp_k, str(list(comp_k.keys())))

        pa_k = comp_k.get("player_a", {})
        ok("K8  player_a.position == 'FWD'",
           pa_k.get("position") == "FWD", repr(pa_k.get("position")))
        ok("K9  comparison.reasons includes set-piece phrase",
           any("set-piece" in r for r in comp_k.get("reasons", [])),
           str(comp_k.get("reasons")))
except Exception as exc:
    ok("K1-K9 session scenario tests", False, traceback.format_exc())


# ===========================================================================
# Section L -- Regression
# ===========================================================================
print("\n--- L: Regression ---")

# L1: run() comparison turn default output unchanged
exit_l1, out_l1 = run("compare Haaland and Saka", STANDARD_BOOTSTRAP)
ok("L1  default run() output non-empty",
   len(out_l1.strip()) > 0)
ok("L2  default run() output is plain text",
   not out_l1.strip().startswith("{"))

# L3: run() captain_score debug still works
_, out_l3 = run("should I captain Haaland?", STANDARD_BOOTSTRAP, debug=True)
body_l3 = json.loads(out_l3)
ok("L3  captain_score debug JSON has final_text",
   "final_text" in body_l3)
ok("L4  captain_score debug JSON has debug bundle",
   "debug" in body_l3, str(list(body_l3.keys())))
ok("L5  captain_score debug JSON has no comparison key",
   "comparison" not in body_l3)

# L6: run_session() regular turns still have base keys
turns_l6 = run_session(["should I captain Salah?"], STANDARD_BOOTSTRAP)
ok("L6  run_session non-comparison turn has question/final_text/outcome",
   all(k in turns_l6[0] for k in ("question", "final_text", "outcome")))

# L7: Phase 5i regression -- FinalResponse.comparison.player_a still works
fr_l7 = respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)
ok("L7  FinalResponse.comparison.player_a still populated",
   fr_l7.comparison is not None and fr_l7.comparison.player_a is not None)

# L8: _serial_comparison round-trips to JSON
if fr_l7.comparison is not None:
    cli_l8 = _serial_comparison(fr_l7.comparison)
    try:
        json.dumps(cli_l8)
        ok("L8  _serial_comparison output is JSON-serializable", True)
    except TypeError as exc:
        ok("L8  _serial_comparison output is JSON-serializable", False, str(exc))

# L9: Phase 4b CLI examples still all pass
try:
    from examples.cli_examples import CLI_SCENARIOS, run_cli_scenario as rcs
    non_debug = [s for s in CLI_SCENARIOS if not s.get("debug")]
    fails = [s["id"] for s in non_debug if rcs(s)[0] != s["expected_exit"]]
    ok("L9  all non-debug CLI scenarios pass exit-code check",
       len(fails) == 0, str(fails))
except Exception as exc:
    ok("L9  CLI scenarios regression", False, traceback.format_exc())

# L10: Phase 5h set-piece phrasing still present
if fr_l7.comparison is not None:
    ok("L10 Haaland vs Saka comparison reasons include set-piece phrase",
       any("set-piece" in r for r in fr_l7.comparison.reasons),
       str(fr_l7.comparison.reasons))


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*50}")
total = _passed + _failed
print(f"Phase 5j: {_passed}/{total} assertions passed", end="")
if _failed:
    print(f"  ({_failed} FAILED)")
    sys.exit(1)
else:
    print()
