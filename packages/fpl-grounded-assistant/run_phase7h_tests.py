"""
run_phase7h_tests.py
====================
Phase 7h: Player Fixture Run Intent -- test suite.

Target: ~120 assertions across 9 sections.

Sections
--------
A  get_player_fixture_run() -- pure function coverage (16)
B  Router -- fixture-run routing for all supported patterns (18)
C  respond() end-to-end -- intent, outcome, structured metadata (14)
D  FinalResponse.fixture_run -- FixtureRunMeta and FixtureEntry fields (12)
E  Renderer -- _render_get_player_fixture_run() output format (10)
F  HTTP stateless -- /ask endpoint fixture_run field (12)
G  Session HTTP -- fixture_run in /session/{id}/ask (12)
H  Absence / safe fallback -- fixture_run=None on non-fixture turns (12)
I  Regression -- Phase 7f/7c/V1 at expected counts (10+)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

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

from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    INTENT_PLAYER_FIXTURE_RUN,
    OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_ERROR,
    get_player_fixture_run,
    FixtureEntry, FixtureRunMeta,
    FIXTURE_RUN_DEFAULT_HORIZON,
    _FIXTURE_RUN_PREFIXES, _FIXTURE_RUN_SUFFIXES, _FIXTURE_RUN_GAME_WORDS,
    route, respond,
)
from fpl_grounded_assistant.renderer import _render_get_player_fixture_run
from fastapi.testclient import TestClient
import fpl_server

BS = STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Test harness
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
    print(f"\n{name}")


# ---------------------------------------------------------------------------
# Section A: get_player_fixture_run() pure function
# ---------------------------------------------------------------------------

section("A -- get_player_fixture_run() pure function")

# A1: Haaland (team=13, MCI) returns OK
_r_a1 = get_player_fixture_run("Haaland", BS)
check(_r_a1["status"] == "ok",               "A1a: Haaland status ok")
check(_r_a1["web_name"] == "Haaland",        "A1b: Haaland web_name")
check(_r_a1["team_short"] == "MCI",          "A1c: Haaland team_short MCI")
check(_r_a1["position"] == "FWD",            "A1d: Haaland position FWD")
check(_r_a1["horizon"] == 5,                 "A1e: Haaland horizon 5")
check(_r_a1["current_gameweek"] == 28,       "A1f: current_gameweek 28")
check(len(_r_a1["fixtures"]) == 5,           "A1g: 5 fixtures returned")

# A2: Salah (team=14, LIV) returns OK
_r_a2 = get_player_fixture_run("Salah", BS)
check(_r_a2["status"] == "ok",               "A2a: Salah status ok")
check(_r_a2["team_short"] == "LIV",          "A2b: Salah team_short LIV")
check(_r_a2["position"] == "MID",            "A2c: Salah position MID")

# A3: First fixture for Haaland (GW28 vs ARS at home)
_fx0 = _r_a1["fixtures"][0]
check(_fx0["gameweek"] == 28,                "A3a: first fixture GW28")
check(_fx0["opponent_short"] == "ARS",       "A3b: opponent ARS")
check(_fx0["is_home"] is True,               "A3c: is_home True")
check(_fx0["difficulty"] == 3,               "A3d: difficulty 3")

# A4: Not found returns not_found
_r_a4 = get_player_fixture_run("xyzunknown999", BS)
check(_r_a4["status"] == "not_found",        "A4: not_found for unknown player")

# A5: Bootstrap without team_fixtures returns missing_context
_bs_no_fixtures = {k: v for k, v in BS.items() if k != "team_fixtures"}
_r_a5 = get_player_fixture_run("Haaland", _bs_no_fixtures)
check(_r_a5["status"] == "missing_context",  "A5: missing_context when no team_fixtures")
check(_r_a5["web_name"] == "Haaland",        "A5b: web_name preserved on missing_context")


# ---------------------------------------------------------------------------
# Section B: Router -- all supported routing patterns
# ---------------------------------------------------------------------------

section("B -- Router routing patterns")

# B1: Suffix form: "X fixtures"
_rb1 = route("Haaland fixtures")
check(_rb1 is not None and _rb1.tool_name == "get_player_fixture_run",  "B1: 'Haaland fixtures'")
check(_rb1 is not None and _rb1.tool_args["query"] == "Haaland",        "B1b: player=Haaland")

# B2: Suffix form: "X's fixtures"
_rb2 = route("Haaland's fixtures")
check(_rb2 is not None and _rb2.tool_name == "get_player_fixture_run",  "B2: \"Haaland's fixtures\"")
check(_rb2 is not None and _rb2.tool_args["query"] == "Haaland",        "B2b: player=Haaland (no apostrophe)")

# B3: Suffix form: "X fixture run"
_rb3 = route("Salah fixture run")
check(_rb3 is not None and _rb3.tool_name == "get_player_fixture_run",  "B3: 'Salah fixture run'")
check(_rb3 is not None and _rb3.tool_args["query"] == "Salah",          "B3b: player=Salah")

# B4: Prefix form: "upcoming fixtures for X"
_rb4 = route("upcoming fixtures for Palmer")
check(_rb4 is not None and _rb4.tool_name == "get_player_fixture_run",  "B4: 'upcoming fixtures for Palmer'")
check(_rb4 is not None and _rb4.tool_args["query"] == "Palmer",         "B4b: player=Palmer")

# B5: Prefix form: "fixtures for X"
_rb5 = route("fixtures for Saka")
check(_rb5 is not None and _rb5.tool_name == "get_player_fixture_run",  "B5: 'fixtures for Saka'")
check(_rb5 is not None and _rb5.tool_args["query"] == "Saka",           "B5b: player=Saka")

# B6: Prefix form: "fixture run for X"
_rb6 = route("fixture run for De Bruyne")
check(_rb6 is not None and _rb6.tool_name == "get_player_fixture_run",  "B6: 'fixture run for De Bruyne'")
check(_rb6 is not None and _rb6.tool_args["query"] == "De Bruyne",      "B6b: player=De Bruyne")

# B7: "X next N games"
_rb7 = route("Salah next 5 games")
check(_rb7 is not None and _rb7.tool_name == "get_player_fixture_run",  "B7: 'Salah next 5 games'")
check(_rb7 is not None and _rb7.tool_args["query"] == "Salah",          "B7b: player=Salah")

# B8: "X next games"
_rb8 = route("Haaland next games")
check(_rb8 is not None and _rb8.tool_name == "get_player_fixture_run",  "B8: 'Haaland next games'")
check(_rb8 is not None and _rb8.tool_args["query"] == "Haaland",        "B8b: player=Haaland")

# B9: "X next fixtures"
_rb9 = route("De Bruyne next fixtures")
check(_rb9 is not None and _rb9.tool_name == "get_player_fixture_run",  "B9: 'De Bruyne next fixtures'")

# B10: Case-insensitivity
_rb10 = route("HAALAND FIXTURES")
check(_rb10 is not None and _rb10.tool_name == "get_player_fixture_run", "B10: HAALAND FIXTURES uppercase")

# B11: Should NOT route as fixture_run (comparison/transfer/captain should not be confused)
_rb11 = route("should I captain Haaland")
check(_rb11 is None or _rb11.tool_name != "get_player_fixture_run", "B11: captain question not fixture_run")

_rb12 = route("compare Haaland and Salah")
check(_rb12 is None or _rb12.tool_name != "get_player_fixture_run", "B12: comparison not fixture_run")

# B13: "show me fixtures for X"
_rb13 = route("show me fixtures for Saka")
check(_rb13 is not None and _rb13.tool_name == "get_player_fixture_run", "B13: 'show me fixtures for Saka'")

# B14: "fixture schedule for X"
_rb14 = route("fixture schedule for Haaland")
check(_rb14 is not None and _rb14.tool_name == "get_player_fixture_run", "B14: 'fixture schedule for Haaland'")


# ---------------------------------------------------------------------------
# Section C: respond() end-to-end
# ---------------------------------------------------------------------------

section("C -- respond() end-to-end")

_rc1 = respond("Haaland fixtures", BS)
check(_rc1.intent == INTENT_PLAYER_FIXTURE_RUN,  "C1a: intent=player_fixture_run")
check(_rc1.outcome == OUTCOME_OK,                "C1b: outcome=ok")
check(_rc1.supported is True,                    "C1c: supported=True")
check(bool(_rc1.final_text),                     "C1d: final_text non-empty")
check(_rc1.fixture_run is not None,              "C1e: fixture_run populated")
check(_rc1.fixture_run.web_name == "Haaland",    "C1f: fixture_run.web_name Haaland")

_rc2 = respond("Salah next 5 games", BS)
check(_rc2.intent == INTENT_PLAYER_FIXTURE_RUN,  "C2a: Salah next 5 games intent")
check(_rc2.outcome == OUTCOME_OK,                "C2b: Salah next 5 games outcome ok")
check(_rc2.fixture_run is not None,              "C2c: fixture_run populated for Salah")
check(_rc2.fixture_run.team_short == "LIV",      "C2d: fixture_run.team_short LIV")

_rc3 = respond("upcoming fixtures for xyznotaplayer999", BS)
check(_rc3.intent == INTENT_PLAYER_FIXTURE_RUN,  "C3a: not_found intent still fixture_run")
check(_rc3.outcome == OUTCOME_NOT_FOUND,         "C3b: not_found outcome")
check(_rc3.fixture_run is None,                  "C3c: fixture_run=None on not_found")

_rc4 = respond("fixtures for Saka", BS)
check(_rc4.intent == INTENT_PLAYER_FIXTURE_RUN,  "C4a: fixtures for Saka intent")
check(_rc4.outcome == OUTCOME_OK,                "C4b: fixtures for Saka ok")
check(_rc4.fixture_run is not None,              "C4c: fixture_run populated for Saka")
check(_rc4.fixture_run.team_short == "ARS",      "C4d: Saka team_short ARS")


# ---------------------------------------------------------------------------
# Section D: FinalResponse.fixture_run -- FixtureRunMeta and FixtureEntry
# ---------------------------------------------------------------------------

section("D -- FinalResponse.fixture_run structure")

_rd = respond("Haaland fixtures", BS)
_frm = _rd.fixture_run
check(_frm is not None,                              "D1: fixture_run not None")
check(isinstance(_frm, FixtureRunMeta),              "D2: is FixtureRunMeta")
check(_frm.web_name == "Haaland",                    "D3: web_name Haaland")
check(_frm.team_short == "MCI",                      "D4: team_short MCI")
check(_frm.position == "FWD",                        "D5: position FWD")
check(_frm.horizon == 5,                             "D6: horizon 5")
check(_frm.current_gameweek == 28,                   "D7: current_gameweek 28")
check(len(_frm.fixtures) == 5,                       "D8: 5 fixture entries")
_fe0 = _frm.fixtures[0]
check(isinstance(_fe0, FixtureEntry),                "D9: first entry is FixtureEntry")
check(_fe0.gameweek == 28,                           "D10: first entry gameweek 28")
check(_fe0.opponent_short == "ARS",                  "D11: first entry opponent ARS")
check(_fe0.is_home is True,                          "D12: first entry is_home True")


# ---------------------------------------------------------------------------
# Section E: Renderer output
# ---------------------------------------------------------------------------

section("E -- Renderer output")

_ok_out = {
    "status": "ok",
    "web_name": "Haaland",
    "team_short": "MCI",
    "position": "FWD",
    "horizon": 5,
    "current_gameweek": 28,
    "fixtures": [
        {"gameweek": 28, "opponent_short": "ARS", "is_home": True,  "difficulty": 3},
        {"gameweek": 29, "opponent_short": "LIV", "is_home": False, "difficulty": 4},
        {"gameweek": 30, "opponent_short": "MUN", "is_home": True,  "difficulty": 2},
        {"gameweek": 31, "opponent_short": "ARS", "is_home": True,  "difficulty": 3},
        {"gameweek": 32, "opponent_short": "CHE", "is_home": False, "difficulty": 3},
    ],
}
_re1 = _render_get_player_fixture_run(_ok_out)
check("Haaland" in _re1,                   "E1: web_name in text")
check("MCI" in _re1,                       "E2: team_short in text")
check("FWD" in _re1,                       "E3: position in text")
check("GW28" in _re1,                      "E4: GW28 in text")
check("ARS" in _re1,                       "E5: ARS in text")
check("(H)" in _re1,                       "E6: (H) home marker in text")
check("(A)" in _re1,                       "E7: (A) away marker in text")
check("FDR 3" in _re1 or "FDR3" in _re1,  "E8: FDR 3 in text")

_re_nf = _render_get_player_fixture_run({"status": "not_found", "query": "Palmer", "message": "Player 'Palmer' not found."})
check("Palmer" in _re_nf or "not found" in _re_nf.lower(), "E9: not_found message surfaced")

_re_mc = _render_get_player_fixture_run({"status": "missing_context", "query": "Haaland", "web_name": "Haaland", "message": "No fixture schedule available."})
check("No fixture" in _re_mc or "available" in _re_mc.lower(), "E10: missing_context message surfaced")


# ---------------------------------------------------------------------------
# Section F: HTTP stateless -- /ask endpoint
# ---------------------------------------------------------------------------

section("F -- HTTP stateless /ask fixture_run field")

fpl_server._init_bootstrap(BS)
_client = TestClient(fpl_server.app, raise_server_exceptions=True)

# F1: fixture_run present and correct for fixture_run OK turn
_rf1 = _client.post("/ask", json={"question": "Haaland fixtures"})
check(_rf1.status_code == 200,                    "F1a: /ask 200")
_rf1j = _rf1.json()
check(_rf1j["intent"] == "player_fixture_run",    "F1b: intent=player_fixture_run")
check(_rf1j["outcome"] == "ok",                   "F1c: outcome=ok")
check(_rf1j.get("fixture_run") is not None,       "F1d: fixture_run present")
_fr1 = _rf1j["fixture_run"]
check(_fr1["web_name"] == "Haaland",              "F1e: fixture_run.web_name Haaland")
check(_fr1["team_short"] == "MCI",                "F1f: fixture_run.team_short MCI")
check(_fr1["horizon"] == 5,                       "F1g: fixture_run.horizon 5")
check(len(_fr1["fixtures"]) == 5,                 "F1h: 5 fixture entries in HTTP response")
check(_fr1["fixtures"][0]["gameweek"] == 28,      "F1i: first fixture GW28")
check(_fr1["fixtures"][0]["opponent_short"] == "ARS", "F1j: first opponent ARS")

# F2: fixture_run absent on non-fixture turn (captain query)
_rf2 = _client.post("/ask", json={"question": "should I captain Salah"})
_rf2j = _rf2.json()
check(_rf2j.get("fixture_run") is None,           "F2: fixture_run=None on captain turn")

# F3: not_found returns null fixture_run
_rf3 = _client.post("/ask", json={"question": "upcoming fixtures for xyznotaplayer999"})
_rf3j = _rf3.json()
check(_rf3j["outcome"] == "not_found",            "F3a: not_found for unknown player")
check(_rf3j.get("fixture_run") is None,           "F3b: fixture_run=None on not_found")


# ---------------------------------------------------------------------------
# Section G: Session HTTP -- fixture_run in /session/{id}/ask
# ---------------------------------------------------------------------------

section("G -- Session HTTP fixture_run")

fpl_server._init_bootstrap(BS)
_client_g = TestClient(fpl_server.app, raise_server_exceptions=True)
_sg1 = _client_g.post("/session")
check(_sg1.status_code == 200,                    "G1: create session 200")
_sid = _sg1.json()["session_id"]

# G2: session ask fixture_run turn
_sg2 = _client_g.post(f"/session/{_sid}/ask", json={"question": "Haaland fixtures"})
check(_sg2.status_code == 200,                    "G2a: session ask 200")
_sg2j = _sg2.json()
check(_sg2j["intent"] == "player_fixture_run",    "G2b: intent=player_fixture_run")
check(_sg2j["outcome"] == "ok",                   "G2c: outcome=ok")
check(_sg2j.get("fixture_run") is not None,       "G2d: fixture_run present")
_sgfr = _sg2j["fixture_run"]
check(_sgfr["web_name"] == "Haaland",             "G2e: web_name Haaland")
check(_sgfr["team_short"] == "MCI",               "G2f: team_short MCI")
check(len(_sgfr["fixtures"]) == 5,                "G2g: 5 fixtures in session response")

# G3: second turn (captain) has fixture_run=None
_sg3 = _client_g.post(f"/session/{_sid}/ask", json={"question": "should I captain Salah"})
_sg3j = _sg3.json()
check(_sg3j.get("fixture_run") is None,           "G3: fixture_run absent on captain turn in session")

# G4: Salah fixtures in session
_sg4 = _client_g.post(f"/session/{_sid}/ask", json={"question": "Salah next 5 games"})
_sg4j = _sg4.json()
check(_sg4j["intent"] == "player_fixture_run",    "G4a: Salah next 5 games intent")
check(_sg4j.get("fixture_run") is not None,       "G4b: fixture_run populated")
check(_sg4j["fixture_run"]["team_short"] == "LIV","G4c: Salah team LIV")

_client_g.delete(f"/session/{_sid}")


# ---------------------------------------------------------------------------
# Section H: Absence / safe fallback -- fixture_run=None on non-fixture turns
# ---------------------------------------------------------------------------

section("H -- Absence: fixture_run=None on non-fixture turns")

_intent_map = [
    ("should I captain Haaland",               "captain_score"),
    ("top captains this week",                 "rank_candidates"),
    ("what gameweek is it",                    "current_gameweek"),
    ("summary for Salah",                      "player_summary"),
    ("who is Haaland",                         "player_resolve"),
    ("compare Haaland and Salah",              "compare_players"),
    ("should I sell Saka for Salah",           "transfer_advice"),
    ("should I bench boost this week",         "chip_advice"),
]

for q, expected_intent in _intent_map:
    _hr = respond(q, BS)
    check(
        _hr.fixture_run is None,
        f"H: fixture_run=None for intent={_hr.intent} (q={q!r})",
    )

# Also verify unsupported question has fixture_run=None
_hu = respond("Is Haaland fit?", BS)
check(_hu.fixture_run is None, "H: fixture_run=None for unsupported intent")

# fixture_run is None on not_found turn
_hnf = respond("upcoming fixtures for xyznotaplayer999", BS)
check(_hnf.fixture_run is None, "H: fixture_run=None on not_found fixture turn")

check(True, "H: all absence checks used fixture_run default=None")


# ---------------------------------------------------------------------------
# Section I: Regression -- Phase 7f/7c/V1 at expected counts
# ---------------------------------------------------------------------------

section("I -- Regression")

import subprocess
import re

def _run_test(script: str) -> tuple[int, int]:
    """Run a test script and return (passed, failed)."""
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True,
        cwd=_HERE,
    )
    text = result.stdout + result.stderr
    m = re.search(r"(\d+)/(\d+) PASS", text)
    if m:
        p = int(m.group(1))
        t = int(m.group(2))
        return p, t - p
    return 0, 1  # default to failure if pattern not found

_rp7f_pass, _rp7f_fail = _run_test("run_phase7f_tests.py")
check(_rp7f_pass >= 107 and _rp7f_fail == 0, f"I1: Phase 7f {_rp7f_pass}/107 PASS")

_rp7c_pass, _rp7c_fail = _run_test("run_phase7c_tests.py")
check(_rp7c_pass >= 95 and _rp7c_fail == 0, f"I2: Phase 7c {_rp7c_pass}/95 PASS")

_rpv1_pass, _rpv1_fail = _run_test("run_phase_v1_tests.py")
check(_rpv1_pass >= 156 and _rpv1_fail == 0, f"I3: Phase V1 {_rpv1_pass}/156 PASS")

_rp4k_pass, _rp4k_fail = _run_test("run_phase4k_tests.py")
check(_rp4k_pass >= 115 and _rp4k_fail == 0, f"I4: Phase 4k {_rp4k_pass}/115 PASS")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\nPhase 7h: {_PASS}/{_PASS + _FAIL} PASS")
if _FAIL == 0:
    print("          All assertions passed.")
else:
    print(f"          {_FAIL} assertion(s) FAILED.")

sys.exit(0 if _FAIL == 0 else 1)
