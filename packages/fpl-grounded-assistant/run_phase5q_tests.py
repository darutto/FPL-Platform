"""
run_phase5q_tests.py
====================
Phase 5q: Ranked Captain Example Parity

Tests that verify:
  A  Example registry coverage — new scenarios present on all surfaces
  B  run_cli_scenario helper handles candidates_list
  C  CLI captain_ranking_debug example path — output and structure
  D  HTTP captain_ranking_structured example path — status and structure
  E  Session captain_ranking_structured example path — lifecycle and structure
  F  Shape identity across CLI, HTTP, and session for captain_ranking
  G  Non-ranking turns remain clean on all surfaces
  H  Regression — prior comparison and captain examples unchanged

Run::

    cd packages/fpl-grounded-assistant
    python run_phase5q_tests.py
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

from examples.cli_examples import CLI_SCENARIOS, run_cli_scenario          # noqa: E402
from examples.http_examples import HTTP_SCENARIOS, run_http_scenario        # noqa: E402
from examples.session_examples import (                                     # noqa: E402
    SESSION_FLOWS, run_session_flow, make_session_client,
)
import fpl_server                                                            # noqa: E402

_RANKING_CANDIDATES = [{"query": "Salah"}, {"query": "Haaland"}, {"query": "Saka"}]


# ===========================================================================
# Section A — Example registry coverage
# ===========================================================================
print("\n--- A: Example registry coverage ---")

_cli_ids   = [s["id"] for s in CLI_SCENARIOS]
_http_ids  = [s["id"] for s in HTTP_SCENARIOS]
_sess_ids  = [f["id"] for f in SESSION_FLOWS]

ok("A1 CLI has captain_ranking_debug scenario",
   "captain_ranking_debug" in _cli_ids, str(_cli_ids))
ok("A2 HTTP has captain_ranking_structured scenario",
   "captain_ranking_structured" in _http_ids, str(_http_ids))
ok("A3 session has captain_ranking_structured flow",
   "captain_ranking_structured" in _sess_ids, str(_sess_ids))

_cli_ranking_s = next((s for s in CLI_SCENARIOS if s["id"] == "captain_ranking_debug"), {})
ok("A4 CLI captain_ranking_debug has debug=True",
   _cli_ranking_s.get("debug") is True)
ok("A5 CLI captain_ranking_debug has candidates_list",
   "candidates_list" in _cli_ranking_s)
ok("A6 CLI captain_ranking_debug candidates_list is list of 3",
   isinstance(_cli_ranking_s.get("candidates_list"), list)
   and len(_cli_ranking_s.get("candidates_list", [])) == 3)

_http_ranking_s = next((s for s in HTTP_SCENARIOS if s["id"] == "captain_ranking_structured"), {})
ok("A7 HTTP captain_ranking_structured payload has candidates_list",
   "candidates_list" in _http_ranking_s.get("payload", {}))
ok("A8 HTTP captain_ranking_structured expected_outcome == ok",
   _http_ranking_s.get("expected_outcome") == "ok")

_sess_ranking_f = next((f for f in SESSION_FLOWS if f["id"] == "captain_ranking_structured"), {})
_sess_t1 = (_sess_ranking_f.get("turns") or [{}])[0]
ok("A9 session captain_ranking_structured turn has candidates_list",
   "candidates_list" in _sess_t1)
ok("A10 session candidates_list is list of 3",
   isinstance(_sess_t1.get("candidates_list"), list)
   and len(_sess_t1.get("candidates_list", [])) == 3)


# ===========================================================================
# Section B — run_cli_scenario helper handles candidates_list
# ===========================================================================
print("\n--- B: run_cli_scenario helper ---")

# run the scenario defined in the examples module directly
_b_exit, _b_out = run_cli_scenario(_cli_ranking_s)
ok("B1 exit code 0 for ranking scenario", _b_exit == 0, str(_b_exit))

_b_body: dict = {}
try:
    _b_body = json.loads(_b_out)
    ok("B2 output parses as JSON (debug=True)", True)
except json.JSONDecodeError as e:
    ok("B2 output parses as JSON (debug=True)", False, str(e))

ok("B3 captain_ranking key present in debug output",
   "captain_ranking" in _b_body, str(list(_b_body.keys())))
ok("B4 captain_ranking is list", isinstance(_b_body.get("captain_ranking"), list))
ok("B5 intent == rank_candidates",
   _b_body.get("intent") == "rank_candidates", str(_b_body.get("intent")))

# Confirm helper passes candidates_list for non-ranking scenario too (no crash)
_non_ranking_s = next(s for s in CLI_SCENARIOS if s["id"] == "supported_ok")
_nr_exit, _nr_out = run_cli_scenario(_non_ranking_s)
ok("B6 non-ranking scenario still works (no candidates_list key)", _nr_exit == 0)


# ===========================================================================
# Section C — CLI captain_ranking_debug example path
# ===========================================================================
print("\n--- C: CLI captain_ranking_debug example path ---")

_c_exit, _c_out = run_cli_scenario(_cli_ranking_s)
ok("C1 exit code 0", _c_exit == 0)

_c_body: dict = {}
try:
    _c_body = json.loads(_c_out)
    ok("C2 parses as JSON", True)
except json.JSONDecodeError as e:
    ok("C2 parses as JSON", False, str(e))

_c_ranking = _c_body.get("captain_ranking", [])
ok("C3 captain_ranking present",     "captain_ranking" in _c_body)
ok("C4 captain_ranking is list",     isinstance(_c_ranking, list))
ok("C5 3 entries",                   len(_c_ranking) == 3, str(len(_c_ranking)))
ok("C6 final_text present",          "final_text" in _c_body)
ok("C7 intent == rank_candidates",   _c_body.get("intent") == "rank_candidates")
ok("C8 outcome == ok",               _c_body.get("outcome") == "ok")

_c_first = _c_ranking[0] if _c_ranking else {}
ok("C9  first entry rank == 1",      _c_first.get("rank") == 1)
ok("C10 first entry web_name == Salah", _c_first.get("web_name") == "Salah")
ok("C11 first entry tier == safe",   _c_first.get("tier") == "safe")
ok("C12 first entry role_bonus == 5.0", _c_first.get("role_bonus") == 5.0)
ok("C13 first entry set_piece_notes is list",
   isinstance(_c_first.get("set_piece_notes"), list))
ok("C14 first entry exactly 7 keys",
   set(_c_first.keys()) == {"rank", "web_name", "team_short", "captain_score",
                             "tier", "role_bonus", "set_piece_notes"},
   str(set(_c_first.keys())))

# No captain key on ranking turn
ok("C15 no captain key on ranking debug output",
   "captain" not in _c_body, str(list(_c_body.keys())))


# ===========================================================================
# Section D — HTTP captain_ranking_structured example path
# ===========================================================================
print("\n--- D: HTTP captain_ranking_structured example path ---")

_d_status, _d_body = run_http_scenario(_http_ranking_s)
ok("D1 HTTP 200",                     _d_status == 200, str(_d_status))
ok("D2 supported == True",            _d_body.get("supported") is True)
ok("D3 outcome == ok",                _d_body.get("outcome") == "ok")

_d_ranking = _d_body.get("captain_ranking") or []
ok("D4 captain_ranking present",      "captain_ranking" in _d_body)
ok("D5 captain_ranking is list",      isinstance(_d_body.get("captain_ranking"), list))
ok("D6 3 entries",                    len(_d_ranking) == 3, str(len(_d_ranking)))

_d_first = _d_ranking[0] if _d_ranking else {}
ok("D7  first entry rank == 1",       _d_first.get("rank") == 1)
ok("D8  first entry web_name == Salah", _d_first.get("web_name") == "Salah")
ok("D9  first entry tier == safe",    _d_first.get("tier") == "safe")
ok("D10 first entry role_bonus == 5.0", _d_first.get("role_bonus") == 5.0)
ok("D11 first entry set_piece_notes is list",
   isinstance(_d_first.get("set_piece_notes"), list))
ok("D12 first entry exactly 7 keys",
   set(_d_first.keys()) == {"rank", "web_name", "team_short", "captain_score",
                             "tier", "role_bonus", "set_piece_notes"},
   str(set(_d_first.keys())))

# captain is null for ranking turn (Pydantic always serialises null fields)
ok("D13 captain is null for ranking turn",
   _d_body.get("captain") is None)


# ===========================================================================
# Section E — Session captain_ranking_structured example path
# ===========================================================================
print("\n--- E: Session captain_ranking_structured example path ---")

_e_client = make_session_client()
_e_result = run_session_flow(_sess_ranking_f, _e_client)

ok("E1 session created (200)",        _e_result.get("create_status") == 200)
ok("E2 1 turn processed",             len(_e_result.get("turns", [])) == 1)
ok("E3 turn HTTP 200",
   (_e_result.get("turns") or [{}])[0].get("status") == 200)

_e_turn_body = (_e_result.get("turns") or [{}])[0].get("body", {})
ok("E4 outcome == ok",                _e_turn_body.get("outcome") == "ok")
ok("E5 intent == rank_candidates",    _e_turn_body.get("intent") == "rank_candidates")

_e_ranking = _e_turn_body.get("captain_ranking") or []
ok("E6 captain_ranking present",      "captain_ranking" in _e_turn_body)
ok("E7 captain_ranking is list",      isinstance(_e_turn_body.get("captain_ranking"), list))
ok("E8 3 entries",                    len(_e_ranking) == 3, str(len(_e_ranking)))

_e_first = _e_ranking[0] if _e_ranking else {}
ok("E9  first entry rank == 1",       _e_first.get("rank") == 1)
ok("E10 first entry web_name == Salah", _e_first.get("web_name") == "Salah")
ok("E11 first entry tier == safe",    _e_first.get("tier") == "safe")
ok("E12 first entry role_bonus == 5.0", _e_first.get("role_bonus") == 5.0)
ok("E13 first entry set_piece_notes is list",
   isinstance(_e_first.get("set_piece_notes"), list))

# Session lifecycle
ok("E14 inspect HTTP 200",            _e_result.get("inspect_status") == 200)
ok("E15 turn_count == 1",
   _e_result.get("inspect_body", {}).get("turn_count") == 1)
ok("E16 clear HTTP 200",              _e_result.get("clear_status") == 200)
ok("E17 after-clear 404",             _e_result.get("after_clear_status") == 404)


# ===========================================================================
# Section F — Shape identity across CLI, HTTP, and session
# ===========================================================================
print("\n--- F: Shape identity CLI == HTTP == session ---")

_f_cli  = _c_body.get("captain_ranking", [])   # Section C
_f_http = _d_body.get("captain_ranking", [])   # Section D
_f_sess = _e_turn_body.get("captain_ranking", []) # Section E

ok("F1 CLI and HTTP list lengths equal",
   len(_f_cli) == len(_f_http),
   f"CLI={len(_f_cli)}, HTTP={len(_f_http)}")
ok("F2 CLI and session list lengths equal",
   len(_f_cli) == len(_f_sess),
   f"CLI={len(_f_cli)}, sess={len(_f_sess)}")

ok("F3 CLI first entry == HTTP first entry",
   bool(_f_cli) and bool(_f_http) and _f_cli[0] == _f_http[0],
   f"CLI: {_f_cli[0] if _f_cli else None}\nHTTP: {_f_http[0] if _f_http else None}")
ok("F4 CLI first entry == session first entry",
   bool(_f_cli) and bool(_f_sess) and _f_cli[0] == _f_sess[0],
   f"CLI: {_f_cli[0] if _f_cli else None}\nSESS: {_f_sess[0] if _f_sess else None}")

# Key sets are identical across surfaces
_expected_keys = {"rank", "web_name", "team_short", "captain_score",
                  "tier", "role_bonus", "set_piece_notes"}
ok("F5 CLI entry key set matches contract",
   all(set(e.keys()) == _expected_keys for e in _f_cli))
ok("F6 HTTP entry key set matches contract",
   all(set(e.keys()) == _expected_keys for e in _f_http))
ok("F7 session entry key set matches contract",
   all(set(e.keys()) == _expected_keys for e in _f_sess))


# ===========================================================================
# Section G — Non-ranking turns remain clean
# ===========================================================================
print("\n--- G: Non-ranking turns remain clean ---")

# CLI captain_debug: captain present, no captain_ranking key
_g_cap_exit, _g_cap_out = run_cli_scenario(
    next(s for s in CLI_SCENARIOS if s["id"] == "captain_debug")
)
_g_cap_body = json.loads(_g_cap_out)
ok("G1 CLI captain_debug — captain key present",
   "captain" in _g_cap_body)
ok("G2 CLI captain_debug — no captain_ranking key",
   "captain_ranking" not in _g_cap_body, str(list(_g_cap_body.keys())))

# CLI comparison_debug: comparison present, no captain_ranking key
_g_cmp_exit, _g_cmp_out = run_cli_scenario(
    next(s for s in CLI_SCENARIOS if s["id"] == "comparison_debug")
)
_g_cmp_body = json.loads(_g_cmp_out)
ok("G3 CLI comparison_debug — comparison key present",
   "comparison" in _g_cmp_body)
ok("G4 CLI comparison_debug — no captain_ranking key",
   "captain_ranking" not in _g_cmp_body, str(list(_g_cmp_body.keys())))

# HTTP captain_structured: captain not null, captain_ranking is null
_g_hs, _g_hb = run_http_scenario(
    next(s for s in HTTP_SCENARIOS if s["id"] == "captain_structured")
)
ok("G5 HTTP captain_structured — captain not null",
   _g_hb.get("captain") is not None)
ok("G6 HTTP captain_structured — captain_ranking is null",
   _g_hb.get("captain_ranking") is None)

# HTTP comparison_structured: comparison not null, captain_ranking is null
_g_hs2, _g_hb2 = run_http_scenario(
    next(s for s in HTTP_SCENARIOS if s["id"] == "comparison_structured")
)
ok("G7 HTTP comparison_structured — comparison not null",
   _g_hb2.get("comparison") is not None)
ok("G8 HTTP comparison_structured — captain_ranking is null",
   _g_hb2.get("captain_ranking") is None)

# Session captain_ranking turn: captain is null (not a single-player turn)
ok("G9 session ranking turn — captain is null",
   _e_turn_body.get("captain") is None)


# ===========================================================================
# Section H — Regression: prior examples unchanged
# ===========================================================================
print("\n--- H: Regression ---")

# CLI scenario IDs that must still be present
_required_cli = {
    "supported_ok", "supported_ambiguous", "supported_not_found",
    "supported_missing_arguments", "unsupported_intent",
    "comparison_direct", "comparison_not_found",
    "comparison_debug", "captain_debug",
}
ok("H1 all prior CLI scenarios still present",
   _required_cli.issubset(set(_cli_ids)),
   str(_required_cli - set(_cli_ids)))

# HTTP scenario IDs that must still be present
_required_http = {
    "supported_ok", "supported_ambiguous", "supported_not_found",
    "supported_missing_arguments", "unsupported_intent",
    "comparison_direct", "comparison_not_found",
    "comparison_structured", "captain_structured",
}
ok("H2 all prior HTTP scenarios still present",
   _required_http.issubset(set(_http_ids)),
   str(_required_http - set(_http_ids)))

# Session flow IDs that must still be present
_required_sess = {
    "create_ask_inspect_clear", "pronoun_follow_up",
    "comparison_direct", "comparison_followup",
    "comparison_structured", "captain_structured",
}
ok("H3 all prior session flows still present",
   _required_sess.issubset(set(_sess_ids)),
   str(_required_sess - set(_sess_ids)))

# Prior CLI examples still produce correct exit codes
for _s in CLI_SCENARIOS:
    if _s["id"] == "captain_ranking_debug":
        continue  # already tested
    _h_exit, _ = run_cli_scenario(_s)
    ok(f"H4 CLI {_s['id']} exit={_s['expected_exit']}",
       _h_exit == _s["expected_exit"],
       f"got {_h_exit}, expected {_s['expected_exit']}")

# Prior HTTP scenarios still return correct status codes
for _s in HTTP_SCENARIOS:
    if _s["id"] == "captain_ranking_structured":
        continue  # already tested
    _h_status, _ = run_http_scenario(_s)
    ok(f"H5 HTTP {_s['id']} status={_s['expected_status']}",
       _h_status == _s["expected_status"],
       f"got {_h_status}, expected {_s['expected_status']}")

# captain_debug CLI still has captain with expected tier
_h_cd_exit, _h_cd_out = run_cli_scenario(
    next(s for s in CLI_SCENARIOS if s["id"] == "captain_debug")
)
_h_cd_body = json.loads(_h_cd_out)
ok("H6 captain_debug captain.tier still == safe",
   _h_cd_body.get("captain", {}).get("tier") == "safe")

# comparison_debug CLI still has comparison with winner key
_h_cm_exit, _h_cm_out = run_cli_scenario(
    next(s for s in CLI_SCENARIOS if s["id"] == "comparison_debug")
)
_h_cm_body = json.loads(_h_cm_out)
ok("H7 comparison_debug comparison.winner key present",
   "winner" in _h_cm_body.get("comparison", {}))


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*60}")
print(f"Phase 5q results: {_passed}/{_passed+_failed} PASS")
print(f"{'='*60}")
if _failed:
    sys.exit(1)
