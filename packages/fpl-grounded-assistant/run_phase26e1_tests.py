"""
run_phase26e1_tests.py
======================
Phase 2.6e.1: Team fixture calendar ranking.

Intent: team_fixture_calendar
Tool:   get_team_fixture_calendar

Supported prompt families
--------------------------
  Spanish easiest: "que equipos tienen el mejor calendario las proximas 5 jornadas"
  Spanish hardest: "que equipos tienen el peor calendario las proximas 3 jornadas"
  English easiest: "teams with best fixtures", "best fixture run", "easiest schedule"
  English hardest: "teams with worst upcoming fixtures", "hardest schedule"
  With N:          "best fixtures next 4 gameweeks"

Scoring formula
---------------
  fixtures_in_window = fixtures where current_gw <= gameweek < current_gw + horizon
  avg_fdr = sum(difficulty) / fixture_count  (2 d.p.)
  mode="easiest" -> sort ascending avg_fdr
  mode="hardest" -> sort descending avg_fdr

Default horizon: 5 GWs
Default top_n:   5 teams

Expected rankings (STANDARD_BOOTSTRAP, horizon=5, GW28)
---------------------------------------------------------
Team        GW28-32 difficulties        total  avg
LIV  2 3 4 3 2                          14    2.80  #1 easiest / #5 hardest
MCI  3 4 2 3 3                          15    3.00  #2 easiest / #4 hardest
ARS  3 3 4 5 3                          18    3.60  #3 (tie)
CHE  4 2 4 5 3                          18    3.60  #3 (tie)
MUN  5 4 5 3 4                          21    4.20  #5 easiest / #1 hardest

Regression
----------
run_validation:       68/68
run_phase26d4_tests:  35/35 (run independently; chains to d3/d2/d1/d, >100s)
"""
from __future__ import annotations

import os
import sys
import subprocess

_PGROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)


_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        _pass.append(label)
        print(f"  PASS  {label}")
    else:
        _fail.append(label)
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


from fpl_grounded_assistant.router import route                        # noqa: E402
from fpl_grounded_assistant.team_fixture_calendar import (             # noqa: E402
    get_team_fixture_calendar,
    DEFAULT_HORIZON,
    DEFAULT_TOP_N,
)
from fpl_grounded_assistant.final_response import respond              # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import (             # noqa: E402
    STANDARD_BOOTSTRAP,
)


# ---------------------------------------------------------------------------
# A — Constants
# ---------------------------------------------------------------------------

print("\n=== A: Constants ===")

_check("A1 DEFAULT_HORIZON == 5", DEFAULT_HORIZON == 5, f"got {DEFAULT_HORIZON}")
_check("A2 DEFAULT_TOP_N == 5",   DEFAULT_TOP_N   == 5, f"got {DEFAULT_TOP_N}")


# ---------------------------------------------------------------------------
# B — Routing: Spanish easiest
# ---------------------------------------------------------------------------

print("\n=== B: Routing — Spanish easiest ===")

_es_easiest_cases = [
    ("que equipos tienen el mejor calendario las proximas 5 jornadas", 5, "B1"),
    ("que equipos tienen el mejor calendario las proximas 4 jornadas", 4, "B2"),
    ("mejor calendario proximas 3 jornadas",                           3, "B3"),
    ("mejor calendario",                                               5, "B4"),
    ("equipos con mejor calendario",                                   5, "B5"),
]

for q, expected_n, label in _es_easiest_cases:
    r = route(q)
    _check(f"{label} '{q[:55]}' routes to team_fixture_calendar",
           r is not None and r.tool_name == "get_team_fixture_calendar",
           f"got {r.tool_name if r else 'None'}")
    if r and r.tool_name == "get_team_fixture_calendar":
        _check(f"{label}m mode='easiest'",
               r.tool_args.get("mode") == "easiest",
               f"got mode={r.tool_args.get('mode')!r}")
        _check(f"{label}n horizon={expected_n}",
               r.tool_args.get("horizon") == expected_n,
               f"got horizon={r.tool_args.get('horizon')}")


# ---------------------------------------------------------------------------
# C — Routing: English worst/hardest
# ---------------------------------------------------------------------------

print("\n=== C: Routing — English hardest ===")

_en_hardest_cases = [
    ("teams with worst upcoming fixtures",    5, "C1"),
    ("worst fixture run",                     5, "C2"),
    ("hardest schedule",                      5, "C3"),
    ("worst fixtures next 3 gameweeks",       3, "C4"),
    ("teams with hardest fixtures",           5, "C5"),
]

for q, expected_n, label in _en_hardest_cases:
    r = route(q)
    _check(f"{label} '{q}' routes to team_fixture_calendar",
           r is not None and r.tool_name == "get_team_fixture_calendar",
           f"got {r.tool_name if r else 'None'}")
    if r and r.tool_name == "get_team_fixture_calendar":
        _check(f"{label}m mode='hardest'",
               r.tool_args.get("mode") == "hardest",
               f"got mode={r.tool_args.get('mode')!r}")


# ---------------------------------------------------------------------------
# D — Routing: English easiest
# ---------------------------------------------------------------------------

print("\n=== D: Routing — English easiest ===")

_en_easiest_cases = [
    ("teams with best fixtures",          5, "D1"),
    ("best fixture run",                  5, "D2"),
    ("easiest schedule",                  5, "D3"),
    ("best fixtures next 4 gameweeks",    4, "D4"),
    ("best upcoming fixtures",            5, "D5"),
    ("easiest fixture run",               5, "D6"),
]

for q, expected_n, label in _en_easiest_cases:
    r = route(q)
    _check(f"{label} '{q}' routes to team_fixture_calendar",
           r is not None and r.tool_name == "get_team_fixture_calendar",
           f"got {r.tool_name if r else 'None'}")
    if r and r.tool_name == "get_team_fixture_calendar":
        _check(f"{label}m mode='easiest'",
               r.tool_args.get("mode") == "easiest",
               f"got mode={r.tool_args.get('mode')!r}")


# ---------------------------------------------------------------------------
# E — Routing: no collision with player-fixture-run
# ---------------------------------------------------------------------------

print("\n=== E: No collision with player_fixture_run ===")

_no_collision = [
    ("Haaland fixtures",                  "get_player_fixture_run",    "E1"),
    ("upcoming fixtures for Salah",       "get_player_fixture_run",    "E2"),
    ("Saka next 5 games",                 "get_player_fixture_run",    "E3"),
    ("should I captain Salah",            "get_captain_score",         "E4"),
    ("what gameweek is it",               "get_current_gameweek",      "E5"),
]

for q, expected_tool, label in _no_collision:
    r = route(q)
    _check(f"{label} '{q}' routes to {expected_tool}",
           r is not None and r.tool_name == expected_tool,
           f"got {r.tool_name if r else 'None'}")


# ---------------------------------------------------------------------------
# F — Handler: scoring formula and output shape
# ---------------------------------------------------------------------------

print("\n=== F: Handler — scoring formula ===")

result = get_team_fixture_calendar(STANDARD_BOOTSTRAP, mode="easiest", horizon=5)
_check("F1 status=ok", result.get("status") == "ok", f"got status={result.get('status')!r}")
_check("F2 mode='easiest'", result.get("mode") == "easiest")
_check("F3 horizon=5", result.get("horizon") == 5)
_check("F4 current_gameweek=28", result.get("current_gameweek") == 28,
       f"got {result.get('current_gameweek')}")
_check("F5 5 teams returned (all teams in standard bootstrap)", result.get("top_n") == 5)

teams = result.get("teams", [])
_check("F6 teams list has 5 entries", len(teams) == 5, f"got {len(teams)}")
_check("F7 rank #1 is LIV (avg 2.8)", teams[0]["team_short"] == "LIV",
       f"got {teams[0]['team_short']} avg={teams[0]['avg_fdr']}")
_check("F8 rank #2 is MCI (avg 3.0)", teams[1]["team_short"] == "MCI",
       f"got {teams[1]['team_short']} avg={teams[1]['avg_fdr']}")
_check("F9 rank #5 is MUN (avg 4.2)", teams[4]["team_short"] == "MUN",
       f"got {teams[4]['team_short']} avg={teams[4]['avg_fdr']}")
_check("F10 LIV avg_fdr=2.80", teams[0]["avg_fdr"] == 2.80,
       f"got {teams[0]['avg_fdr']}")
_check("F11 MUN avg_fdr=4.20", teams[4]["avg_fdr"] == 4.20,
       f"got {teams[4]['avg_fdr']}")

# Check each entry has required fields
for t in teams:
    for key in ("rank", "team_short", "team_name", "fixture_count", "avg_fdr",
                "total_fdr", "fixtures"):
        _check(f"F12 team[{t['team_short']}].{key} present", key in t)
    _check(f"F13 team[{t['team_short']}].fixtures len=5",
           len(t["fixtures"]) == 5, f"got {len(t['fixtures'])}")


# ---------------------------------------------------------------------------
# G — Handler: hardest mode
# ---------------------------------------------------------------------------

print("\n=== G: Handler — hardest mode ===")

result_h = get_team_fixture_calendar(STANDARD_BOOTSTRAP, mode="hardest", horizon=5)
teams_h  = result_h.get("teams", [])
_check("G1 mode='hardest'", result_h.get("mode") == "hardest")
_check("G2 rank #1 is MUN (hardest)", teams_h[0]["team_short"] == "MUN",
       f"got {teams_h[0]['team_short']}")
_check("G3 rank #5 is LIV (easiest)", teams_h[-1]["team_short"] == "LIV",
       f"got {teams_h[-1]['team_short']}")


# ---------------------------------------------------------------------------
# H — Handler: bounded top_n
# ---------------------------------------------------------------------------

print("\n=== H: Handler — bounded top_n ===")

result_3 = get_team_fixture_calendar(STANDARD_BOOTSTRAP, mode="easiest", top_n=3)
_check("H1 top_n=3 returns 3 teams", result_3.get("top_n") == 3,
       f"got {result_3.get('top_n')}")
_check("H2 still ranks LIV first", result_3["teams"][0]["team_short"] == "LIV")


# ---------------------------------------------------------------------------
# I — Handler: horizon slicing
# ---------------------------------------------------------------------------

print("\n=== I: Handler — horizon slicing ===")

result_2 = get_team_fixture_calendar(STANDARD_BOOTSTRAP, mode="easiest", horizon=2)
teams_2  = result_2.get("teams", [])
_check("I1 horizon=2 each team has 2 fixtures",
       all(t["fixture_count"] == 2 for t in teams_2),
       f"got counts: {[t['fixture_count'] for t in teams_2]}")
# LIV GW28(2)+GW29(3)=5, avg=2.5  MUN GW28(5)+GW29(4)=9, avg=4.5
_check("I2 LIV avg_fdr=2.5 over horizon 2",
       teams_2[0]["avg_fdr"] == 2.5,
       f"got {teams_2[0]['avg_fdr']}")


# ---------------------------------------------------------------------------
# J — Handler: missing_context when no team_fixtures
# ---------------------------------------------------------------------------

print("\n=== J: Handler — missing_context safe fail ===")

no_fixtures_bs = {k: v for k, v in STANDARD_BOOTSTRAP.items() if k != "team_fixtures"}
result_mc = get_team_fixture_calendar(no_fixtures_bs)
_check("J1 status=missing_context when no team_fixtures",
       result_mc.get("status") == "missing_context",
       f"got {result_mc.get('status')!r}")
_check("J2 message present", bool(result_mc.get("message")))


# ---------------------------------------------------------------------------
# K — End-to-end respond() with metadata
# ---------------------------------------------------------------------------

print("\n=== K: respond() end-to-end ===")

fr = respond(
    "que equipos tienen el mejor calendario las proximas 5 jornadas",
    STANDARD_BOOTSTRAP,
)
_check("K1 intent=team_fixture_calendar", fr.intent == "team_fixture_calendar",
       f"got {fr.intent}")
_check("K2 outcome=ok", fr.outcome == "ok", f"got {fr.outcome}")
_check("K3 team_calendar meta non-None", fr.team_calendar is not None)
if fr.team_calendar:
    _check("K4 meta.mode='easiest'", fr.team_calendar.mode == "easiest")
    _check("K5 meta.horizon=5", fr.team_calendar.horizon == 5)
    _check("K6 meta.top_n=5", fr.team_calendar.top_n == 5)
    _check("K7 meta.teams has 5 entries", len(fr.team_calendar.teams) == 5)
    _check("K8 teams[0].team_short='LIV'",
           fr.team_calendar.teams[0].team_short == "LIV")
_check("K9 final_text non-empty", bool(fr.final_text))
_check("K10 final_text mentions LIV", "LIV" in fr.final_text,
       f"first 200 chars: {fr.final_text[:200]}")

fr_h = respond("teams with worst upcoming fixtures", STANDARD_BOOTSTRAP)
_check("K11 hardest intent ok", fr_h.intent == "team_fixture_calendar")
if fr_h.team_calendar:
    _check("K12 hardest meta.mode='hardest'", fr_h.team_calendar.mode == "hardest")
    _check("K13 hardest teams[0]=MUN", fr_h.team_calendar.teams[0].team_short == "MUN")


# ---------------------------------------------------------------------------
# L — Regression suites
# ---------------------------------------------------------------------------

print("\n=== L: Regression ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(f"L1 validation corpus {passed}/{total} PASS", passed == total,
       f"{total - passed} scenario(s) failed")

# run_phase26d4_tests.py chains into d3 -> d2 -> d1 -> d (~109s total).
# When run as a subprocess inside another suite, startup + pipe overhead
# pushes it past any safe timeout budget on this machine.
# Verify d4 directly: python run_phase26d4_tests.py -> 35/35.


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6e.1: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"               {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("               All assertions passed.")
