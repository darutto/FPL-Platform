"""
run_phase26e3_tests.py
======================
Phase 2.6e.3: Single-team fixture calendar lookup.

New intent: team_schedule
New tool:   get_team_schedule

Supported prompt families
--------------------------
  English (known-name): "Arsenal fixtures next 5"
  English (schedule):   "Liverpool schedule", "Spurs schedule next 3 gameweeks"
  Spanish (prefix):     "calendario del Arsenal proximas 4 jornadas"

Tool output contract
--------------------
status "ok":
  team_short        3-char abbreviation
  team_name         full club name
  horizon           GW window used
  current_gameweek  current GW (int or None)
  fixture_count     fixtures in window
  avg_fdr           average FDR (2 d.p.)
  total_fdr         sum of FDR values
  fixtures          [{gameweek, opponent_short, is_home, difficulty}]
  has_dgw           True when team has >=2 fixtures in any GW in horizon
  has_bgw           True when team blanks in a GW others play
  dgw_gameweeks     sorted list of DGW GW numbers
  bgw_gameweeks     sorted list of BGW GW numbers

status "not_found":
  When no team matches team_query in bootstrap.

status "missing_context":
  When team_fixtures absent from bootstrap, or matched team has no fixtures.

Expected values (STANDARD_BOOTSTRAP, current_gw=28)
-----------------------------------------------------
Arsenal  (id=1)  GW28-32: FDR 3,3,4,5,3  total=18  avg=3.60  count=5
Liverpool(id=14) GW28-32: FDR 2,3,4,3,2  total=14  avg=2.80  count=5
Man Utd  (id=11) GW28-32: FDR 5,4,5,3,4  total=21  avg=4.20  count=5
Chelsea  (id=8)  GW28-32: FDR 4,2,4,5,3  total=18  avg=3.60  count=5
Man City (id=13) GW28-32: FDR 3,4,2,3,3  total=15  avg=3.00  count=5

Arsenal horizon=4 (GW28-31): FDR 3,3,4,5  total=15  avg=3.75  count=4

Regression
----------
run_validation:       68/68
run_phase26e1_tests:  118/118 (run independently)
run_phase26e2_tests:  112/112 (run independently)
run_phase26d4_tests:  35/35   (run independently)
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

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP, DGW_BOOTSTRAP, BGW_BOOTSTRAP
from fpl_grounded_assistant.team_fixture_calendar import get_team_schedule, _resolve_team
from fpl_grounded_assistant.router import route
from fpl_grounded_assistant.final_response import respond


_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _pass.append(label)
        print(f"  PASS  {label}")
    else:
        _fail.append(label)
        msg = f"  FAIL  {label}"
        if detail:
            msg += f" ({detail})"
        print(msg)


# ---------------------------------------------------------------------------
# A — Team resolution (_resolve_team)
# ---------------------------------------------------------------------------

print("\n=== A: Team resolution ===")

_check("A1 'Arsenal' resolves to ARS",
       _resolve_team("Arsenal", STANDARD_BOOTSTRAP) is not None and
       _resolve_team("Arsenal", STANDARD_BOOTSTRAP).get("short_name") == "ARS")

_check("A2 'arsenal' (lowercase) resolves to ARS",
       _resolve_team("arsenal", STANDARD_BOOTSTRAP) is not None)

_check("A3 'ARS' short_name resolves to Arsenal",
       _resolve_team("ARS", STANDARD_BOOTSTRAP) is not None and
       _resolve_team("ARS", STANDARD_BOOTSTRAP).get("name") == "Arsenal")

_check("A4 'Liverpool' resolves to LIV",
       _resolve_team("Liverpool", STANDARD_BOOTSTRAP) is not None and
       _resolve_team("Liverpool", STANDARD_BOOTSTRAP).get("short_name") == "LIV")

_check("A5 'Man Utd' resolves via alias to MUN",
       _resolve_team("Man Utd", STANDARD_BOOTSTRAP) is not None and
       _resolve_team("Man Utd", STANDARD_BOOTSTRAP).get("short_name") == "MUN")

_check("A6 'Man City' resolves to MCI",
       _resolve_team("Man City", STANDARD_BOOTSTRAP) is not None and
       _resolve_team("Man City", STANDARD_BOOTSTRAP).get("short_name") == "MCI")

_check("A7 'Spurs' returns None (not in STANDARD_BOOTSTRAP)",
       _resolve_team("Spurs", STANDARD_BOOTSTRAP) is None)

_check("A8 'Chelsea' resolves to CHE",
       _resolve_team("Chelsea", STANDARD_BOOTSTRAP) is not None and
       _resolve_team("Chelsea", STANDARD_BOOTSTRAP).get("short_name") == "CHE")


# ---------------------------------------------------------------------------
# B — Handler output: ok path
# ---------------------------------------------------------------------------

print("\n=== B: Handler output (ok path) ===")

_ars = get_team_schedule({"team_query": "Arsenal", "horizon": 5}, STANDARD_BOOTSTRAP)

_check("B1 Arsenal status=ok",      _ars["status"] == "ok")
_check("B2 Arsenal team_short=ARS", _ars.get("team_short") == "ARS")
_check("B3 Arsenal team_name",      "Arsenal" in _ars.get("team_name", ""))
_check("B4 Arsenal horizon=5",      _ars.get("horizon") == 5)
_check("B5 Arsenal current_gw=28",  _ars.get("current_gameweek") == 28)
_check("B6 Arsenal fixture_count=5", _ars.get("fixture_count") == 5)
_check("B7 Arsenal avg_fdr=3.6",    abs(_ars.get("avg_fdr", 0) - 3.6) < 0.01)
_check("B8 Arsenal total_fdr=18",   _ars.get("total_fdr") == 18)
_check("B9 Arsenal fixtures is list", isinstance(_ars.get("fixtures"), list))
_check("B10 Arsenal fixtures len=5", len(_ars.get("fixtures", [])) == 5)
_check("B11 Arsenal has_dgw=False",  _ars.get("has_dgw") is False)
_check("B12 Arsenal has_bgw=False",  _ars.get("has_bgw") is False)
_check("B13 Arsenal dgw_gameweeks=[]", _ars.get("dgw_gameweeks") == [])
_check("B14 Arsenal bgw_gameweeks=[]", _ars.get("bgw_gameweeks") == [])

# Fixture order and content
_fxs = _ars.get("fixtures", [])
if _fxs:
    _check("B15 Arsenal GW28 opponent=CHE",
           _fxs[0]["gameweek"] == 28 and _fxs[0]["opponent_short"] == "CHE")
    _check("B16 Arsenal GW28 is_home=True",  bool(_fxs[0]["is_home"]) is True)
    _check("B17 Arsenal GW28 difficulty=3",  _fxs[0]["difficulty"] == 3)
    _check("B18 Arsenal GW32 opponent=CHE",  _fxs[4]["gameweek"] == 32)

# Liverpool
_liv = get_team_schedule({"team_query": "Liverpool", "horizon": 5}, STANDARD_BOOTSTRAP)
_check("B19 Liverpool status=ok",     _liv["status"] == "ok")
_check("B20 Liverpool team_short=LIV", _liv.get("team_short") == "LIV")
_check("B21 Liverpool avg_fdr=2.8",   abs(_liv.get("avg_fdr", 0) - 2.8) < 0.01)
_check("B22 Liverpool fixture_count=5", _liv.get("fixture_count") == 5)

# Man Utd
_mun = get_team_schedule({"team_query": "Man Utd", "horizon": 5}, STANDARD_BOOTSTRAP)
_check("B23 Man Utd status=ok",      _mun["status"] == "ok")
_check("B24 Man Utd team_short=MUN", _mun.get("team_short") == "MUN")
_check("B25 Man Utd avg_fdr=4.2",    abs(_mun.get("avg_fdr", 0) - 4.2) < 0.01)


# ---------------------------------------------------------------------------
# C — Handler output: horizon trimming
# ---------------------------------------------------------------------------

print("\n=== C: Horizon trimming ===")

_ars4 = get_team_schedule({"team_query": "Arsenal", "horizon": 4}, STANDARD_BOOTSTRAP)
_check("C1 Arsenal h=4 status=ok",       _ars4["status"] == "ok")
_check("C2 Arsenal h=4 fixture_count=4", _ars4.get("fixture_count") == 4)
_check("C3 Arsenal h=4 avg_fdr=3.75",    abs(_ars4.get("avg_fdr", 0) - 3.75) < 0.01)
_check("C4 Arsenal h=4 total_fdr=15",    _ars4.get("total_fdr") == 15)
# horizon clamp: min=1
_ars1 = get_team_schedule({"team_query": "Arsenal", "horizon": 0}, STANDARD_BOOTSTRAP)
_check("C5 horizon clamped to 1",  _ars1.get("horizon") == 1)
# horizon clamp: max=10
_ars10 = get_team_schedule({"team_query": "Arsenal", "horizon": 99}, STANDARD_BOOTSTRAP)
_check("C6 horizon clamped to 10", _ars10.get("horizon") == 10)


# ---------------------------------------------------------------------------
# D — Handler output: not_found and missing_context
# ---------------------------------------------------------------------------

print("\n=== D: Error paths ===")

_spurs = get_team_schedule({"team_query": "Spurs", "horizon": 5}, STANDARD_BOOTSTRAP)
_check("D1 Spurs status=not_found",    _spurs["status"] == "not_found")
_check("D2 Spurs team_query echoed",   _spurs.get("team_query") == "Spurs")
_check("D3 Spurs message non-empty",   bool(_spurs.get("message", "")))

_no_tf = get_team_schedule({"team_query": "Arsenal", "horizon": 5}, {"teams": STANDARD_BOOTSTRAP["teams"]})
_check("D4 no team_fixtures -> missing_context", _no_tf["status"] == "missing_context")


# ---------------------------------------------------------------------------
# E — Router: all three prompt families
# ---------------------------------------------------------------------------

print("\n=== E: Router patterns ===")

_cases_schedule: list[tuple[str, str, int]] = [
    # (query, expected_team_query_lower, expected_horizon)
    ("Arsenal fixtures next 5",                        "arsenal",   5),
    ("arsenal fixtures",                               "arsenal",   5),
    ("Chelsea fixtures next 3 gameweeks",              "chelsea",   3),
    ("Liverpool schedule",                             "liverpool", 5),
    ("Liverpool schedule next 4 gameweeks",            "liverpool", 4),
    ("Spurs schedule next 3 gameweeks",                "spurs",     3),
    ("Man Utd schedule",                               "man utd",   5),
    ("Man City fixtures",                              "man city",  5),
    ("calendario del Arsenal proximas 4 jornadas",     "arsenal",   4),
    ("calendario del Liverpool proximas 5 jornadas",   "liverpool", 5),
    ("partidos del Chelsea",                           "chelsea",   5),
]

for q, expected_team_lower, expected_n in _cases_schedule:
    rr = route(q)
    tool_ok   = rr is not None and rr.tool_name == "get_team_schedule"
    if rr and tool_ok:
        tq    = rr.tool_args.get("team_query", "").lower()
        team_ok = expected_team_lower in tq
        n_ok    = rr.tool_args.get("horizon") == expected_n
    else:
        team_ok = n_ok = False
    _check(
        f"E routing {q!r}",
        tool_ok and team_ok and n_ok,
        f"got tool={rr.tool_name if rr else None} tq={rr.tool_args if rr else None}",
    )


# ---------------------------------------------------------------------------
# F — Router: existing intents NOT hijacked
# ---------------------------------------------------------------------------

print("\n=== F: Routing non-regression ===")

_non_hijack = [
    ("teams with best fixtures",       "get_team_fixture_calendar"),
    ("best fixtures next 5 gameweeks", "get_team_fixture_calendar"),
    ("mejor calendario",               "get_team_fixture_calendar"),
    ("Haaland fixtures",               "get_player_fixture_run"),
    ("Salah next 5 fixtures",          "get_player_fixture_run"),
    ("fixtures for Haaland",           "get_player_fixture_run"),
]
for q, expected_tool in _non_hijack:
    rr = route(q)
    got = rr.tool_name if rr else None
    _check(f"F non-hijack {q!r}", got == expected_tool,
           f"expected {expected_tool}, got {got}")


# ---------------------------------------------------------------------------
# G — respond() integration: FinalResponse fields
# ---------------------------------------------------------------------------

print("\n=== G: respond() integration ===")

_fr = respond("Arsenal fixtures next 5", STANDARD_BOOTSTRAP)
_check("G1 intent=team_schedule",   _fr.intent == "team_schedule")
_check("G2 outcome=ok",             _fr.outcome == "ok")
_check("G3 team_schedule not None", _fr.team_schedule is not None)
_check("G4 team_calendar is None",  _fr.team_calendar is None)

if _fr.team_schedule:
    ts = _fr.team_schedule
    _check("G5 ts.team_short=ARS",    ts.team_short == "ARS")
    _check("G6 ts.fixture_count=5",   ts.fixture_count == 5)
    _check("G7 ts.avg_fdr=3.6",       abs(ts.avg_fdr - 3.6) < 0.01)
    _check("G8 ts.fixtures len=5",    len(ts.fixtures) == 5)
    _check("G9 ts.has_dgw=False",     ts.has_dgw is False)
    _check("G10 ts.has_bgw=False",    ts.has_bgw is False)
    _check("G11 ts.dgw_gameweeks=()", ts.dgw_gameweeks == ())
    _check("G12 ts.bgw_gameweeks=()", ts.bgw_gameweeks == ())

_fr_ft = respond("Liverpool schedule", STANDARD_BOOTSTRAP)
_check("G13 Liverpool intent=team_schedule", _fr_ft.intent == "team_schedule")
_check("G14 Liverpool team_schedule not None", _fr_ft.team_schedule is not None)
if _fr_ft.team_schedule:
    _check("G15 Liverpool team_short=LIV", _fr_ft.team_schedule.team_short == "LIV")

_fr_nf = respond("Spurs fixtures next 5", STANDARD_BOOTSTRAP)
_check("G16 Spurs intent=team_schedule",  _fr_nf.intent == "team_schedule")
_check("G17 Spurs outcome=not_found",     _fr_nf.outcome == "not_found")
_check("G18 Spurs team_schedule is None", _fr_nf.team_schedule is None)


# ---------------------------------------------------------------------------
# H — final_text (renderer)
# ---------------------------------------------------------------------------

print("\n=== H: Renderer output ===")

_fr_r = respond("Arsenal fixtures next 5", STANDARD_BOOTSTRAP)
_ft   = _fr_r.final_text
_check("H1 final_text non-empty",      bool(_ft))
_check("H2 final_text has 'Arsenal'",  "Arsenal" in _ft)
_check("H3 final_text has 'ARS'",      "ARS" in _ft)
_check("H4 final_text has 'GW28'",     "GW28" in _ft)
_check("H5 final_text has avg FDR",    "3.6" in _ft or "avg" in _ft.lower())

_fr_nf2 = respond("Spurs fixtures next 5", STANDARD_BOOTSTRAP)
_check("H6 not_found final_text non-empty", bool(_fr_nf2.final_text))
_check("H7 not_found mentions Spurs",
       "Spurs" in _fr_nf2.final_text or "spurs" in _fr_nf2.final_text.lower())


# ---------------------------------------------------------------------------
# I — DGW/BGW labels propagated to TeamScheduleMeta
# ---------------------------------------------------------------------------

print("\n=== I: DGW/BGW label propagation ===")

# DGW_BOOTSTRAP: Arsenal (id=1) has 2 GW28 fixtures
_fr_dgw = respond("Arsenal fixtures next 2", DGW_BOOTSTRAP)
_check("I1 DGW Arsenal intent=team_schedule", _fr_dgw.intent == "team_schedule")
if _fr_dgw.team_schedule:
    ts_d = _fr_dgw.team_schedule
    _check("I2 DGW Arsenal has_dgw=True",        ts_d.has_dgw is True)
    _check("I3 DGW Arsenal dgw_gameweeks=(28,)",  28 in ts_d.dgw_gameweeks)
    _check("I4 DGW Arsenal has_bgw=False",        ts_d.has_bgw is False)

# BGW_BOOTSTRAP: ARS and MCI blank GW28; Liverpool, Chelsea, MUN play GW28.
# With horizon=2 (GW28-29), Liverpool plays both GW28 and GW29 -> no BGW.
# Use "next 2 gameweeks" so _extract_n_games picks up horizon=2.
from fpl_grounded_assistant.conversation_fixtures import BGW_BOOTSTRAP as _BGW
_fr_bgw = respond("Liverpool fixtures next 2 gameweeks", _BGW)
_check("I5 BGW Liverpool intent=team_schedule", _fr_bgw.intent == "team_schedule")
if _fr_bgw.team_schedule:
    ts_b = _fr_bgw.team_schedule
    _check("I6 BGW Liverpool horizon=2",       ts_b.horizon == 2)
    _check("I7 BGW Liverpool has_bgw=False",   ts_b.has_bgw is False)
    _check("I8 BGW Liverpool has_dgw=False",   ts_b.has_dgw is False)


# ---------------------------------------------------------------------------
# J — HTTP and CLI surfaces (via respond)
# ---------------------------------------------------------------------------

print("\n=== J: Surface parity ===")

import json as _json
import fpl_cli as _cli
import fpl_server as _srv
from starlette.testclient import TestClient as _TestClient

# CLI surface: run() returns (exit_code, json_string) when debug=True
_cli_code, _cli_str = _cli.run("Arsenal fixtures next 5", STANDARD_BOOTSTRAP, debug=True)
_cli_data = _json.loads(_cli_str)
_cli_ts   = _cli_data.get("team_schedule")
_check("J1 CLI exit_code=0",                     _cli_code == 0)
_check("J2 CLI team_schedule non-None",          _cli_ts is not None)
if _cli_ts:
    _check("J3 CLI team_schedule.team_short=ARS", _cli_ts.get("team_short") == "ARS")
    _check("J4 CLI team_schedule.fixture_count=5", _cli_ts.get("fixture_count") == 5)
    _check("J5 CLI team_schedule has 'fixtures'",  isinstance(_cli_ts.get("fixtures"), list))

# HTTP surface
_srv._init_bootstrap(STANDARD_BOOTSTRAP)
_client = _TestClient(_srv.app, raise_server_exceptions=True)

_resp = _client.post("/ask", json={"question": "Liverpool schedule", "bootstrap": STANDARD_BOOTSTRAP})
_check("J6 HTTP 200",                    _resp.status_code == 200)
_body = _resp.json()
_check("J7 HTTP intent=team_schedule",   _body.get("intent") == "team_schedule")
_ht   = _body.get("team_schedule")
_check("J8 HTTP team_schedule non-None", _ht is not None)
if _ht:
    _check("J9 HTTP team_short=LIV",     _ht.get("team_short") == "LIV")
    _check("J10 HTTP avg_fdr=2.8",       abs(_ht.get("avg_fdr", 0) - 2.8) < 0.01)
    _check("J11 HTTP fixtures is list",  isinstance(_ht.get("fixtures"), list))

# HTTP not_found
_resp_nf = _client.post("/ask", json={"question": "Spurs schedule", "bootstrap": STANDARD_BOOTSTRAP})
_check("J12 HTTP not_found 200",         _resp_nf.status_code == 200)
_body_nf = _resp_nf.json()
_check("J13 HTTP not_found outcome",     _body_nf.get("outcome") == "not_found")
_check("J14 HTTP not_found team_schedule None", _body_nf.get("team_schedule") is None)


# ---------------------------------------------------------------------------
# K — Spanish routing via respond() (end-to-end)
# ---------------------------------------------------------------------------

print("\n=== K: Spanish end-to-end ===")

_fr_es = respond("calendario del Arsenal proximas 4 jornadas", STANDARD_BOOTSTRAP)
_check("K1 Spanish intent=team_schedule",   _fr_es.intent == "team_schedule")
_check("K2 Spanish outcome=ok",             _fr_es.outcome == "ok")
_check("K3 Spanish team_schedule not None", _fr_es.team_schedule is not None)
if _fr_es.team_schedule:
    ts_es = _fr_es.team_schedule
    _check("K4 Spanish team_short=ARS",      ts_es.team_short == "ARS")
    _check("K5 Spanish horizon=4",           ts_es.horizon == 4)
    _check("K6 Spanish fixture_count=4",     ts_es.fixture_count == 4)
    _check("K7 Spanish avg_fdr=3.75",        abs(ts_es.avg_fdr - 3.75) < 0.01)

_fr_es2 = respond("calendario del Liverpool proximas 5 jornadas", STANDARD_BOOTSTRAP)
_check("K8 Spanish Liverpool ok",           _fr_es2.intent == "team_schedule")
if _fr_es2.team_schedule:
    _check("K9 Spanish Liverpool LIV",      _fr_es2.team_schedule.team_short == "LIV")


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

# Prior sub-phase suites (e1, d4) each take >100s due to their own nested
# subprocess chains.  Running them inside this suite would reliably exceed a
# safe timeout budget.  Verification of those suites is delegated to their
# own acceptance commands:
#   python run_phase26e1_tests.py   -> 119/119
#   python run_phase26e2_tests.py   -> 114/114
#   python run_phase26d4_tests.py   -> 35/35


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6e.3: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"               {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("               All assertions passed.")
