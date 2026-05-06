"""
run_phase26j_tests.py
=====================
Phase 2.6j: No-position club-filtered transfer suggestion.

Extension of Phase 2.6i: _try_route_transfer_suggestion gains Form 4 that
routes queries with a known team token + buy intent but *no position word*.

Form 4 fires when:
  A) explicit buy suffix ("to buy", "para fichar", etc.), OR
  B) explicit buy prefix ("who should I buy", "a quién fichar"), OR
  C) lead word (best/cheap/…) + price ceiling (no buy suffix needed)

  … AND a known team token is present in the query.

No handler/metadata/serializer changes — position=ALL already works.

Expected values (DIFFERENTIAL_BOOTSTRAP, horizon=5, current_gw=28)
-------------------------------------------------------------------
Available players by team:
  LIV: Salah  (MID, 13.5m, form 9.5, composite 3.39)
  MCI: Haaland (FWD, 14.5m, form 8.0, composite 2.67)
  CHE: Palmer  (MID,  6.0m, form 7.0, composite 1.94)
  ARS: Raya    (GKP,  5.5m, form 6.0, composite 1.67)
  MUN: Mbeumo  (FWD,  7.5m, form 5.0, composite 1.19)

"best Liverpool players to buy"   -> position=ALL, team=LIV, picks[0]=Salah
"best Arsenal players under 8"    -> position=ALL, team=ARS, price=8.0, picks[0]=Raya
"jugadores del Arsenal para fichar" -> position=ALL, team=ARS, picks[0]=Raya

Routing collision checks
------------------------
"best Arsenal schedule"           -> team_schedule       (no buy suffix/price)
"Arsenal fixtures next 5"         -> team_schedule       (caught before form 4)
"best teams for Arsenal defenders" -> None/position_fixture_run (no buy suffix)
"should I sell Saka for Palmer"   -> transfer_advice     (caught before form 4)
"good differentials"              -> differential_picks  (no team token)
"best Arsenal midfielders to buy" -> transfer_suggestion form 3 (position present)

Regression
----------
run_validation:       80/80
run_phase26i_tests:   87/87    (run independently)
run_phase26h_tests:   110/110  (run independently)
run_phase26e4_tests:  110/110  (run independently)
run_phase26f_tests:   67/67    (run independently)
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

from fpl_grounded_assistant.conversation_fixtures import DIFFERENTIAL_BOOTSTRAP
from fpl_grounded_assistant.transfer_suggestion import get_transfer_suggestion
from fpl_grounded_assistant.router import route
from fpl_grounded_assistant.final_response import respond

_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _pass.append(label)
        print("  PASS  " + label)
    else:
        _fail.append(label)
        msg = "  FAIL  " + label
        if detail:
            msg += " (" + detail + ")"
        print(msg)


# ---------------------------------------------------------------------------
# A — Routing: form 4 fires for no-position club queries
# ---------------------------------------------------------------------------

print("\n=== A: Form 4 routing ===")

_form4_cases = [
    # (query, expected_team_lower, expected_price)
    ("best Liverpool players to buy",        "liverpool",      None),
    ("best Arsenal players to buy",          "arsenal",        None),
    ("best Arsenal players under 8",         "arsenal",        8.0),
    ("best Man City players to buy",         "man city",       None),
    ("jugadores del Arsenal para fichar",    "arsenal",        None),
    ("jugadores del Liverpool para fichar",  "liverpool",      None),
    ("best Chelsea players under 7",         "chelsea",        7.0),
    ("best Liverpool players under 10",      "liverpool",      10.0),
    ("Arsenal players to buy",              "arsenal",        None),
]
for q, exp_team_lower, exp_price in _form4_cases:
    rr = route(q)
    tool_ok  = rr is not None and rr.tool_name == "get_transfer_suggestion"
    tq       = (rr.tool_args.get("team_query") or "").lower() if rr else ""
    pos      = (rr.tool_args.get("position_query") or "ALL") if rr else "?"
    mp       = rr.tool_args.get("max_price") if rr else None
    team_ok  = exp_team_lower in tq if tq else False
    price_ok = (exp_price is None) or (mp is not None and abs(mp - exp_price) < 0.01)
    pos_ok   = pos in (None, "ALL")   # position_query must be None (→ ALL)
    _check(
        "A form4 " + repr(q[:50]),
        tool_ok and team_ok and price_ok and pos_ok,
        "tool=%s tq=%s pos=%s price=%s" % (rr.tool_name if rr else None, tq[:15], pos, mp),
    )


# ---------------------------------------------------------------------------
# B — Routing: form 4 does NOT fire when no buy intent
# ---------------------------------------------------------------------------

print("\n=== B: Form 4 collision safety ===")

_safe_cases = [
    # (query, expected_tool_or_None)
    ("best Arsenal schedule",                "get_team_schedule"),
    ("Arsenal fixtures next 5",             "get_team_schedule"),
    ("should i sell Saka for Palmer",        "get_transfer_advice"),
    ("good differentials",                   "get_differential_picks"),
    ("best teams for Arsenal defenders",     None),          # fixture intent, no buy suffix
    ("best Arsenal midfielders to buy",      "get_transfer_suggestion"),  # form 3 still works
    ("defenders with best fixtures",         "get_position_fixture_run"),
    ("Haaland fixtures",                     "get_player_fixture_run"),
    ("best fixtures next 5 gameweeks",       "get_team_fixture_calendar"),
]
for q, exp_tool in _safe_cases:
    rr  = route(q)
    got = rr.tool_name if rr else None
    _check(
        "B safe " + repr(q[:50]),
        got == exp_tool,
        "expected %s got %s" % (exp_tool, got),
    )

# Form 3 still routes correctly (position word present → form 3 not form 4)
rr_f3 = route("best Liverpool midfielders to buy")
if rr_f3 and rr_f3.tool_name == "get_transfer_suggestion":
    _check("B form3 position still set",
           rr_f3.tool_args.get("position_query") == "midfielder",
           "got %s" % rr_f3.tool_args.get("position_query"))


# ---------------------------------------------------------------------------
# C — Handler: position=ALL, team filter applied
# ---------------------------------------------------------------------------

print("\n=== C: Handler position=ALL ===")

_r_liv = get_transfer_suggestion(
    {"position_query": None, "team_query": "Liverpool",
     "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("C1 LIV ALL status=ok",       _r_liv["status"] == "ok")
_check("C2 LIV position=ALL",        _r_liv.get("position") == "ALL")
_check("C3 LIV team_short=LIV",      _r_liv.get("team_short") == "LIV")
_check("C4 LIV picks all from LIV",
       all(p["team_short"] == "LIV" for p in _r_liv.get("picks", [])))
_check("C5 LIV picks[0]=Salah",      _r_liv.get("picks", [{}])[0].get("web_name") == "Salah")

_r_ars = get_transfer_suggestion(
    {"position_query": None, "team_query": "Arsenal",
     "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("C6 ARS ALL status=ok",       _r_ars["status"] == "ok")
_check("C7 ARS position=ALL",        _r_ars.get("position") == "ALL")
_check("C8 ARS team_short=ARS",      _r_ars.get("team_short") == "ARS")
_check("C9 ARS picks[0]=Raya",       _r_ars.get("picks", [{}])[0].get("web_name") == "Raya")

_r_ars_p = get_transfer_suggestion(
    {"position_query": None, "team_query": "Arsenal",
     "max_price": 8.0, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("C10 ARS ALL<8 status=ok",    _r_ars_p["status"] == "ok")
_check("C11 ARS ALL<8 picks[0]=Raya", _r_ars_p.get("picks", [{}])[0].get("web_name") == "Raya")
_check("C12 ARS ALL<8 price filter",
       all(p.get("now_cost_m", 0) <= 8.0 for p in _r_ars_p.get("picks", [])))

# Mixed positions when team filter applied: ARS has Raya (GKP), Saka (unavail)
_check("C13 ARS ALL includes GKP",
       any(p["position"] == "GKP" for p in _r_ars.get("picks", [])))


# ---------------------------------------------------------------------------
# D — respond() integration: FinalResponse metadata
# ---------------------------------------------------------------------------

print("\n=== D: FinalResponse metadata ===")

_fr_liv = respond("best Liverpool players to buy", DIFFERENTIAL_BOOTSTRAP)
_check("D1 intent=transfer_suggestion",  _fr_liv.intent == "transfer_suggestion")
_check("D2 outcome=ok",                  _fr_liv.outcome == "ok")
_check("D3 ts not None",                 _fr_liv.transfer_suggestion is not None)
if _fr_liv.transfer_suggestion:
    ts = _fr_liv.transfer_suggestion
    _check("D4 position='ALL'",          ts.position == "ALL")
    _check("D5 team_short='LIV'",        ts.team_short == "LIV")
    _check("D6 team_name has Liverpool", "Liverpool" in (ts.team_name or ""))
    _check("D7 picks[0]=Salah",
           ts.picks[0].web_name == "Salah" if ts.picks else False)

_fr_ars = respond("best Arsenal players under 8", DIFFERENTIAL_BOOTSTRAP)
_check("D8 Arsenal price intent ok",     _fr_ars.intent == "transfer_suggestion")
if _fr_ars.transfer_suggestion:
    ts2 = _fr_ars.transfer_suggestion
    _check("D9 position='ALL'",          ts2.position == "ALL")
    _check("D10 team_short='ARS'",       ts2.team_short == "ARS")
    _check("D11 max_price=8.0",          ts2.max_price == 8.0)
    _check("D12 picks[0]=Raya",
           ts2.picks[0].web_name == "Raya" if ts2.picks else False)

_fr_es = respond("jugadores del Arsenal para fichar", DIFFERENTIAL_BOOTSTRAP)
_check("D13 Spanish intent ok",          _fr_es.intent == "transfer_suggestion")
if _fr_es.transfer_suggestion:
    _check("D14 Spanish team_short=ARS", _fr_es.transfer_suggestion.team_short == "ARS")
    _check("D15 Spanish position=ALL",   _fr_es.transfer_suggestion.position == "ALL")


# ---------------------------------------------------------------------------
# E — Renderer includes team in header
# ---------------------------------------------------------------------------

print("\n=== E: Renderer output ===")

_ft_liv = _fr_liv.final_text
_check("E1 final_text non-empty",        bool(_ft_liv))
_check("E2 contains LIV in header",      "LIV" in _ft_liv)
_check("E3 contains Salah",              "Salah" in _ft_liv)
_check("E4 says 'all positions'",        "all positions" in _ft_liv.lower())

_ft_ars = _fr_ars.final_text
_check("E5 Arsenal price header",        "ARS" in _ft_ars)
_check("E6 Arsenal Raya in output",      "Raya" in _ft_ars)


# ---------------------------------------------------------------------------
# F — Surface parity (CLI + HTTP)
# ---------------------------------------------------------------------------

print("\n=== F: Surface parity ===")

import fpl_cli as _cli
import fpl_server as _srv
from starlette.testclient import TestClient as _TestClient

_cli_code, _cli_str = _cli.run(
    "best Liverpool players to buy", DIFFERENTIAL_BOOTSTRAP, debug=True
)
_cli_data = json.loads(_cli_str)
_cli_ts   = _cli_data.get("transfer_suggestion")
_check("F1 CLI exit_code=0",              _cli_code == 0)
_check("F2 CLI ts non-None",              _cli_ts is not None)
if _cli_ts:
    _check("F3 CLI position=ALL",         _cli_ts.get("position") == "ALL")
    _check("F4 CLI team_short=LIV",       _cli_ts.get("team_short") == "LIV")
    _check("F5 CLI picks[0]=Salah",
           _cli_ts.get("picks", [{}])[0].get("web_name") == "Salah")

_srv._init_bootstrap(DIFFERENTIAL_BOOTSTRAP)
_client = _TestClient(_srv.app, raise_server_exceptions=True)

_resp = _client.post(
    "/ask",
    json={"question": "jugadores del Arsenal para fichar",
          "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_check("F6 HTTP 200",                     _resp.status_code == 200)
_body = _resp.json()
_check("F7 HTTP intent=transfer_suggestion", _body.get("intent") == "transfer_suggestion")
_ht = _body.get("transfer_suggestion")
_check("F8 HTTP ts non-None",             _ht is not None)
if _ht:
    _check("F9 HTTP position=ALL",        _ht.get("position") == "ALL")
    _check("F10 HTTP team_short=ARS",     _ht.get("team_short") == "ARS")
    _check("F11 HTTP picks[0]=Raya",
           _ht.get("picks", [{}])[0].get("web_name") == "Raya")

# Existing position-filtered routes unchanged
_resp_pos = _client.post(
    "/ask",
    json={"question": "best Liverpool midfielders to buy",
          "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_body_pos = _resp_pos.json()
_ht_pos   = _body_pos.get("transfer_suggestion")
_check("F12 position-filtered still works", _body_pos.get("intent") == "transfer_suggestion")
if _ht_pos:
    _check("F13 position still MID",       _ht_pos.get("position") == "MID")
    _check("F14 team still LIV",           _ht_pos.get("team_short") == "LIV")


# ---------------------------------------------------------------------------
# G — Regression
# ---------------------------------------------------------------------------

print("\n=== G: Regression ===")

from run_validation import run_all_scenarios

results = run_all_scenarios()
total  = len(results)
passed = sum(1 for r in results if r.get("pass"))
_check("G1 validation corpus " + str(passed) + "/" + str(total) + " PASS",
       passed == total,
       str(total - passed) + " scenario(s) failed")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("Phase 2.6j: %d/%d assertions passed." % (len(_pass), len(_pass) + len(_fail)))
if _fail:
    print("               %d assertion(s) FAILED." % len(_fail))
    for f in _fail:
        print("  - " + f)
else:
    print("               All assertions passed.")
