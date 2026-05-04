"""
run_phase26e4_tests.py
======================
Phase 2.6e.4: Position-filtered fixture calendar ranking.

New intent: position_fixture_run
New tool:   get_position_fixture_run

The tool delegates entirely to get_team_fixture_calendar and adds two fields:
  position        canonical FPL code: "GKP", "DEF", "MID", "FWD"
  position_label  human-readable:     "goalkeepers", "defenders", "midfielders", "forwards"

The team ranking is identical to team_fixture_calendar for the same mode/horizon.
Position is purely a context label — it does not filter which teams appear.

Supported prompt families
--------------------------
  English inline:  "defenders with best fixtures next 5 gameweeks"
                   "forwards with worst fixtures next 3 gameweeks"
  English prefix:  "best teams for midfielders"
                   "worst teams for goalkeepers next 4 gameweeks"
  Spanish prefix:  "mejores equipos para delanteros proximas 4 jornadas"
                   "peores equipos para defensas"
                   "equipos con mejor calendario para porteros"

Position aliases (sample)
--------------------------
English: goalkeeper/s, defender/s, midfielder/s, forward/s, striker/s, gkp, def, mid, fwd
Spanish: portero/s, defensa/s/or/ores, centrocampista/s, medio/s, delantero/s, atacante/s

Expected values (STANDARD_BOOTSTRAP, current_gw=28, mode=easiest, horizon=5)
------------------------------------------------------------------------------
Ranking: LIV 2.8, MCI 3.0, ARS/CHE 3.6 (tied, sorted by short_name), MUN 4.2
teams[0].team_short = "LIV"  (same as team_fixture_calendar easiest)

Regression
----------
run_validation:       71/71
run_phase26e1_tests:  118/118  (run independently)
run_phase26d4_tests:  35/35    (run independently)
"""
from __future__ import annotations

import json
import os
import sys

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

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP, DGW_BOOTSTRAP
from fpl_grounded_assistant.position_fixture_run import get_position_fixture_run, _resolve_position
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
# A — Position alias resolution
# ---------------------------------------------------------------------------

print("\n=== A: Position alias resolution ===")

for alias, expected in [
    ("defenders",      "DEF"),
    ("defender",       "DEF"),
    ("def",            "DEF"),
    ("defensa",        "DEF"),
    ("defensas",       "DEF"),
    ("midfielders",    "MID"),
    ("midfielder",     "MID"),
    ("mid",            "MID"),
    ("centrocampista", "MID"),
    ("medio",          "MID"),
    ("forwards",       "FWD"),
    ("forward",        "FWD"),
    ("striker",        "FWD"),
    ("delantero",      "FWD"),
    ("atacantes",      "FWD"),
    ("goalkeeper",     "GKP"),
    ("goalkeepers",    "GKP"),
    ("gkp",            "GKP"),
    ("portero",        "GKP"),
    ("porteros",       "GKP"),
]:
    got = _resolve_position(alias)
    _check(f"A alias '{alias}'->{expected}", got == expected, f"got {got}")

_check("A unknown returns None", _resolve_position("unknown") is None)
_check("A empty returns None",   _resolve_position("") is None)


# ---------------------------------------------------------------------------
# B — Handler: ok path
# ---------------------------------------------------------------------------

print("\n=== B: Handler output (ok path) ===")

_def = get_position_fixture_run(
    {"position_query": "defenders", "mode": "easiest", "horizon": 5},
    STANDARD_BOOTSTRAP,
)
_check("B1 DEF status=ok",          _def["status"] == "ok")
_check("B2 DEF position='DEF'",     _def.get("position") == "DEF")
_check("B3 DEF position_label",     _def.get("position_label") == "defenders")
_check("B4 DEF mode=easiest",       _def.get("mode") == "easiest")
_check("B5 DEF horizon=5",          _def.get("horizon") == 5)
_check("B6 DEF top_n>0",            _def.get("top_n", 0) > 0)
_check("B7 DEF teams is list",      isinstance(_def.get("teams"), list))
_check("B8 DEF teams[0]=LIV",       _def.get("teams", [{}])[0].get("team_short") == "LIV")
_check("B9 DEF teams[0] avg=2.8",   abs(_def.get("teams", [{}])[0].get("avg_fdr", 0) - 2.8) < 0.01)

# MID easiest — same ranking
_mid = get_position_fixture_run(
    {"position_query": "midfielders", "mode": "easiest", "horizon": 5},
    STANDARD_BOOTSTRAP,
)
_check("B10 MID status=ok",         _mid["status"] == "ok")
_check("B11 MID position='MID'",    _mid.get("position") == "MID")
_check("B12 MID position_label",    _mid.get("position_label") == "midfielders")
_check("B13 MID teams[0]=LIV",      _mid.get("teams", [{}])[0].get("team_short") == "LIV")

# FWD hardest
_fwd_h = get_position_fixture_run(
    {"position_query": "forwards", "mode": "hardest", "horizon": 5},
    STANDARD_BOOTSTRAP,
)
_check("B14 FWD hardest status=ok",  _fwd_h["status"] == "ok")
_check("B15 FWD hardest mode",       _fwd_h.get("mode") == "hardest")
_check("B16 FWD hardest teams[0]=MUN", _fwd_h.get("teams", [{}])[0].get("team_short") == "MUN")

# Spanish alias
_del = get_position_fixture_run(
    {"position_query": "delanteros", "mode": "easiest", "horizon": 5},
    STANDARD_BOOTSTRAP,
)
_check("B17 delanteros->FWD",       _del.get("position") == "FWD")
_check("B18 delanteros label",      _del.get("position_label") == "forwards")

# GKP
_gkp = get_position_fixture_run(
    {"position_query": "goalkeeper", "mode": "easiest", "horizon": 5},
    STANDARD_BOOTSTRAP,
)
_check("B19 GKP position='GKP'",    _gkp.get("position") == "GKP")
_check("B20 GKP label",             _gkp.get("position_label") == "goalkeepers")


# ---------------------------------------------------------------------------
# C — Handler: error paths
# ---------------------------------------------------------------------------

print("\n=== C: Error paths ===")

_inv = get_position_fixture_run(
    {"position_query": "attaquant", "mode": "easiest", "horizon": 5},
    STANDARD_BOOTSTRAP,
)
_check("C1 invalid_position status",    _inv["status"] == "invalid_position")
_check("C2 invalid_position echoed",    _inv.get("position_query") == "attaquant")
_check("C3 invalid_position message",   bool(_inv.get("message", "")))

_no_tf = get_position_fixture_run(
    {"position_query": "defenders", "mode": "easiest", "horizon": 5},
    {"teams": STANDARD_BOOTSTRAP["teams"]},
)
_check("C4 no team_fixtures -> missing_context", _no_tf["status"] == "missing_context")


# ---------------------------------------------------------------------------
# D — Handler: horizon and position do not change team ranking
# ---------------------------------------------------------------------------

print("\n=== D: Ranking parity with team_fixture_calendar ===")

from fpl_grounded_assistant.team_fixture_calendar import get_team_fixture_calendar

_tfc = get_team_fixture_calendar(STANDARD_BOOTSTRAP, mode="easiest", horizon=5)
_pfr = get_position_fixture_run(
    {"position_query": "defenders", "mode": "easiest", "horizon": 5},
    STANDARD_BOOTSTRAP,
)

_check("D1 same number of teams", len(_tfc.get("teams", [])) == len(_pfr.get("teams", [])))
_check("D2 same rank-1 team",
       _tfc.get("teams", [{}])[0].get("team_short") == _pfr.get("teams", [{}])[0].get("team_short"))
for i, (t_tfc, t_pfr) in enumerate(zip(_tfc.get("teams", []), _pfr.get("teams", []))):
    _check(f"D3.{i+1} rank{i+1} avg_fdr matches",
           abs(t_tfc.get("avg_fdr", -1) - t_pfr.get("avg_fdr", -2)) < 0.001)


# ---------------------------------------------------------------------------
# E — Router: all prompt families
# ---------------------------------------------------------------------------

print("\n=== E: Router patterns ===")

_router_cases: list[tuple[str, str, int]] = [
    # (query, expected_position_query_lower, expected_horizon)
    ("defenders with best fixtures next 5 gameweeks",       "defender",        5),
    ("defenders with best fixtures",                        "defender",        5),
    ("forwards with worst fixtures next 3 gameweeks",       "forward",         3),
    ("best teams for midfielders",                          "midfielder",      5),
    ("best teams for midfielders next 4 gameweeks",         "midfielder",      4),
    ("worst teams for goalkeepers next 3 gameweeks",        "goalkeeper",      3),
    ("mejores equipos para delanteros proximas 4 jornadas", "delantero",       4),
    ("peores equipos para defensas",                        "defensa",         5),
    ("equipos con mejor calendario para porteros",          "portero",         5),
    ("best fixture run for defenders",                      "defender",        5),
    ("hardest fixtures for midfielders",                    "midfielder",      5),
]

for q, expected_pos_lower, expected_n in _router_cases:
    rr = route(q)
    tool_ok = rr is not None and rr.tool_name == "get_position_fixture_run"
    if rr and tool_ok:
        pq    = rr.tool_args.get("position_query", "").lower()
        pos_ok = expected_pos_lower in pq
        n_ok   = rr.tool_args.get("horizon") == expected_n
    else:
        pos_ok = n_ok = False
    q_label = repr(q[:55])
    _check(
        "E routing " + q_label,
        tool_ok and pos_ok and n_ok,
        "got tool=%s args=%s" % (rr.tool_name if rr else None, rr.tool_args if rr else None),
    )


# ---------------------------------------------------------------------------
# F — Router non-regression
# ---------------------------------------------------------------------------

print("\n=== F: Routing non-regression ===")

_non_hijack = [
    ("teams with best fixtures",       "get_team_fixture_calendar"),
    ("best fixtures next 5 gameweeks", "get_team_fixture_calendar"),
    ("mejor calendario",               "get_team_fixture_calendar"),
    ("Arsenal fixtures next 5",        "get_team_schedule"),
    ("Liverpool schedule",             "get_team_schedule"),
    ("Haaland fixtures",               "get_player_fixture_run"),
    ("Salah next 5 fixtures",          "get_player_fixture_run"),
]
for q, exp_tool in _non_hijack:
    rr = route(q)
    got = rr.tool_name if rr else None
    _check("F non-hijack " + repr(q), got == exp_tool, "expected %s, got %s" % (exp_tool, got))


# ---------------------------------------------------------------------------
# G — respond() integration: FinalResponse fields
# ---------------------------------------------------------------------------

print("\n=== G: respond() integration ===")

_fr = respond("defenders with best fixtures next 5 gameweeks", STANDARD_BOOTSTRAP)
_check("G1 intent=position_fixture_run", _fr.intent == "position_fixture_run")
_check("G2 outcome=ok",                  _fr.outcome == "ok")
_check("G3 position_fixture_run not None", _fr.position_fixture_run is not None)
_check("G4 team_calendar is None",        _fr.team_calendar is None)
_check("G5 team_schedule is None",        _fr.team_schedule is None)

if _fr.position_fixture_run:
    pf = _fr.position_fixture_run
    _check("G6 pf.position='DEF'",     pf.position == "DEF")
    _check("G7 pf.position_label",     pf.position_label == "defenders")
    _check("G8 pf.mode=easiest",       pf.mode == "easiest")
    _check("G9 pf.horizon=5",          pf.horizon == 5)
    _check("G10 pf.teams non-empty",   len(pf.teams) > 0)
    _check("G11 pf.teams[0]=LIV",      pf.teams[0].team_short == "LIV")

# Note: unknown position words (e.g. "attaquant") are not in _POSITION_WORDS,
# so the router returns None -> unsupported_intent.  invalid_position is a
# handler-level guard tested directly in section C; not reachable via routing.

_fr_es = respond("mejores equipos para delanteros proximas 4 jornadas", STANDARD_BOOTSTRAP)
_check("G15 Spanish intent=position_fixture_run", _fr_es.intent == "position_fixture_run")
_check("G16 Spanish outcome=ok",                  _fr_es.outcome == "ok")
if _fr_es.position_fixture_run:
    _check("G17 Spanish position='FWD'",  _fr_es.position_fixture_run.position == "FWD")
    _check("G18 Spanish horizon=4",       _fr_es.position_fixture_run.horizon == 4)


# ---------------------------------------------------------------------------
# H — Renderer output
# ---------------------------------------------------------------------------

print("\n=== H: Renderer output ===")

_ft = _fr.final_text
_check("H1 final_text non-empty",      bool(_ft))
_check("H2 final_text has 'defenders'", "defenders" in _ft)
_check("H3 final_text has GW28",        "GW28" in _ft)
_check("H4 final_text has avg",         "avg" in _ft.lower() or "2.8" in _ft)

# H5: unsupported returns a non-empty final_text too
_fr_unk = respond("best teams for attaquant", STANDARD_BOOTSTRAP)
_check("H5 unknown pos final_text non-empty", bool(_fr_unk.final_text))


# ---------------------------------------------------------------------------
# I — DGW label propagated through position wrapper
# ---------------------------------------------------------------------------

print("\n=== I: DGW label propagation ===")

_fr_dgw = respond("defenders with best fixtures next 2 gameweeks", DGW_BOOTSTRAP)
_check("I1 DGW intent=position_fixture_run", _fr_dgw.intent == "position_fixture_run")
if _fr_dgw.position_fixture_run:
    pf_d = _fr_dgw.position_fixture_run
    _check("I2 DGW some team has has_dgw=True",
           any(t.has_dgw for t in pf_d.teams))
    if pf_d.teams:
        _check("I3 DGW dgw_gameweeks non-empty for first team",
               len(pf_d.teams[0].dgw_gameweeks) > 0)


# ---------------------------------------------------------------------------
# J — HTTP and CLI surface parity
# ---------------------------------------------------------------------------

print("\n=== J: Surface parity ===")

import fpl_cli as _cli
import fpl_server as _srv
from starlette.testclient import TestClient as _TestClient

# CLI
_cli_code, _cli_str = _cli.run(
    "defenders with best fixtures next 5 gameweeks", STANDARD_BOOTSTRAP, debug=True
)
_cli_data = json.loads(_cli_str)
_cli_pf   = _cli_data.get("position_fixture_run")
_check("J1 CLI exit_code=0",                  _cli_code == 0)
_check("J2 CLI position_fixture_run non-None", _cli_pf is not None)
if _cli_pf:
    _check("J3 CLI position='DEF'",           _cli_pf.get("position") == "DEF")
    _check("J4 CLI teams is list",            isinstance(_cli_pf.get("teams"), list))
    _check("J5 CLI teams[0]=LIV",             _cli_pf.get("teams", [{}])[0].get("team_short") == "LIV")

# HTTP
_srv._init_bootstrap(STANDARD_BOOTSTRAP)
_client = _TestClient(_srv.app, raise_server_exceptions=True)

_resp = _client.post(
    "/ask",
    json={"question": "best teams for midfielders", "bootstrap": STANDARD_BOOTSTRAP},
)
_check("J6 HTTP 200",                      _resp.status_code == 200)
_body = _resp.json()
_check("J7 HTTP intent=position_fixture_run", _body.get("intent") == "position_fixture_run")
_ht = _body.get("position_fixture_run")
_check("J8 HTTP position_fixture_run non-None", _ht is not None)
if _ht:
    _check("J9 HTTP position='MID'",            _ht.get("position") == "MID")
    _check("J10 HTTP position_label",           _ht.get("position_label") == "midfielders")
    _check("J11 HTTP teams is list",            isinstance(_ht.get("teams"), list))
    _check("J12 HTTP teams[0]=LIV",             _ht.get("teams", [{}])[0].get("team_short") == "LIV")

# HTTP unsupported (unknown position word not in router) -> unsupported_intent
_resp_unk = _client.post(
    "/ask",
    json={"question": "best teams for attaquant", "bootstrap": STANDARD_BOOTSTRAP},
)
_check("J13 HTTP unknown pos 200",         _resp_unk.status_code == 200)
_body_unk = _resp_unk.json()
_check("J14 HTTP unknown pos unsupported", _body_unk.get("outcome") == "unsupported_intent")
_check("J15 HTTP unknown pos pfr=None",    _body_unk.get("position_fixture_run") is None)


# ---------------------------------------------------------------------------
# K — Regression
# ---------------------------------------------------------------------------

print("\n=== K: Regression ===")

from run_validation import run_all_scenarios

results = run_all_scenarios()
total  = len(results)
passed = sum(1 for r in results if r.get("pass"))
_check(f"K1 validation corpus {passed}/{total} PASS", passed == total,
       f"{total - passed} scenario(s) failed")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6e.4: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"               {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("               All assertions passed.")
