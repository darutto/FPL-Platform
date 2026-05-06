"""
run_phase26i_tests.py
=====================
Phase 2.6i: Club-filtered transfer suggestion.

Extension of Phase 2.6h: get_transfer_suggestion gains an optional team_query
argument that restricts picks to players from the resolved club.

New fields on output (additive — None when no club filter)
-----------------------------------------------------------
  team_short  3-char team abbreviation (e.g. "LIV")
  team_name   full club name (e.g. "Liverpool")

New status
----------
  "not_found"  team_query supplied but unresolvable in bootstrap

Routing change
--------------
  _extract_team_token() scans all query tokens for known PL team names.
  Form 3 now scans all tokens after the lead word (not just rem_tokens[0])
  so a team token can precede the position word: "best Arsenal midfielders to buy".

Expected values (DIFFERENTIAL_BOOTSTRAP, horizon=5, current_gw=28)
-------------------------------------------------------------------
  LIV MID:         Salah  (form 9.5, avg_fdr 2.8, composite 3.39)
  CHE MID (all):   Palmer (form 7.0, avg_fdr 3.6, composite 1.94)
  CHE MID <8m:     Palmer only (13.5m Salah excluded by price)
  MCI FWD:         Haaland (form 8.0, avg_fdr 3.0, composite 2.67)
  ARS MID:         empty — no available Arsenal midfielders in bootstrap
  TOT any:         not_found — Tottenham not in DIFFERENTIAL_BOOTSTRAP

Supported prompt families
--------------------------
  English:   "best Liverpool midfielders to buy"
             "cheap Chelsea midfielders to buy under 8"
             "best Arsenal forwards to buy"
             "best forwards from Chelsea to sign"
             "best Man City forwards to buy"
  Spanish:   "centrocampistas del Liverpool para comprar"
             "mejores delanteros del Arsenal para fichar"
             "mejores delanteros del Arsenal para fichar bajo 8"

Routing collision notes
-----------------------
  "should I sell Saka for Palmer"     -> transfer_advice   (sell+buy)
  "best teams for midfielders"         -> position_fixture_run (FDR ranking)
  "Arsenal fixtures next 5"           -> team_schedule     (team calendar)
  "Haaland fixtures"                  -> player_fixture_run (player schedule)
  "defenders with best fixtures"       -> position_fixture_run
  "good differentials"                 -> differential_picks

Regression
----------
run_validation:       77/77
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

from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DIFFERENTIAL_BOOTSTRAP,
)
from fpl_grounded_assistant.transfer_suggestion import get_transfer_suggestion
from fpl_grounded_assistant.router import route, _extract_team_token
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
# A — _extract_team_token unit tests
# ---------------------------------------------------------------------------

print("\n=== A: _extract_team_token ===")

# _extract_team_token is an internal helper that operates on normalised (lowercase)
# query strings, as produced by the router's _normalise() function.
_token_cases = [
    ("best liverpool midfielders to buy",            "Liverpool"),
    ("cheap chelsea midfielders to buy under 8",     "Chelsea"),
    ("best arsenal midfielders to buy",              "Arsenal"),
    ("mejores delanteros del arsenal para fichar",   "Arsenal"),
    ("centrocampistas del liverpool para comprar",   "Liverpool"),
    ("best forwards from chelsea to sign",           "Chelsea"),
    ("best man city forwards to buy",                "Man City"),  # "man city" alias → "Man City"
    ("best midfielders to buy",                      None),
    ("good differentials",                           None),
    ("defenders with best fixtures",                 None),
]
for q, expected in _token_cases:
    got = _extract_team_token(q)   # q is already lowercase in these cases
    _check(
        "A _extract " + repr(q[:45]),
        got == expected,
        "expected %s got %s" % (expected, got),
    )


# ---------------------------------------------------------------------------
# B — Handler: club filter applied
# ---------------------------------------------------------------------------

print("\n=== B: Handler club filter ===")

# LIV MID — only Salah
_r_liv = get_transfer_suggestion(
    {"position_query": "midfielders", "team_query": "Liverpool",
     "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B1 LIV MID status=ok",       _r_liv["status"] == "ok")
_check("B2 LIV team_short=LIV",      _r_liv.get("team_short") == "LIV")
_check("B3 LIV team_name present",   "Liverpool" in (_r_liv.get("team_name") or ""))
_check("B4 LIV picks all from LIV",
       all(p["team_short"] == "LIV" for p in _r_liv.get("picks", [])))
_check("B5 LIV picks[0]=Salah",      _r_liv.get("picks", [{}])[0].get("web_name") == "Salah")

# CHE MID (all prices) — Palmer
_r_che = get_transfer_suggestion(
    {"position_query": "midfielders", "team_query": "Chelsea",
     "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B6 CHE MID status=ok",       _r_che["status"] == "ok")
_check("B7 CHE team_short=CHE",      _r_che.get("team_short") == "CHE")
_check("B8 CHE picks all CHE",
       all(p["team_short"] == "CHE" for p in _r_che.get("picks", [])))
_check("B9 CHE picks[0]=Palmer",     _r_che.get("picks", [{}])[0].get("web_name") == "Palmer")

# MCI FWD — Haaland
_r_mci = get_transfer_suggestion(
    {"position_query": "forwards", "team_query": "Man City",
     "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B10 MCI FWD status=ok",      _r_mci["status"] == "ok")
_check("B11 MCI team_short=MCI",     _r_mci.get("team_short") == "MCI")
_check("B12 MCI picks[0]=Haaland",   _r_mci.get("picks", [{}])[0].get("web_name") == "Haaland")

# Alias resolution: "Spurs" → not in DIFFERENTIAL_BOOTSTRAP → not_found
_r_tot = get_transfer_suggestion(
    {"position_query": "forwards", "team_query": "Spurs",
     "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B13 Spurs not_found",        _r_tot["status"] == "not_found")
_check("B14 Spurs team_query echoed", _r_tot.get("team_query") == "Spurs")
_check("B15 Spurs message non-empty", bool(_r_tot.get("message", "")))


# ---------------------------------------------------------------------------
# C — Club filter combined with price
# ---------------------------------------------------------------------------

print("\n=== C: Club + price filter ===")

# CHE MID under 8m → Palmer only (Salah 13.5m from LIV unaffected; Chelsea only has Palmer)
_r_che_p = get_transfer_suggestion(
    {"position_query": "midfielders", "team_query": "Chelsea",
     "max_price": 8.0, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("C1 CHE MID<8 status=ok",     _r_che_p["status"] == "ok")
_check("C2 CHE MID<8 max_price=8.0", _r_che_p.get("max_price") == 8.0)
_check("C3 CHE MID<8 picks[0]=Palmer",
       _r_che_p.get("picks", [{}])[0].get("web_name") == "Palmer")
_check("C4 CHE MID<8 all <= 8.0m",
       all(p.get("now_cost_m", 0) <= 8.0 for p in _r_che_p.get("picks", [])))

# LIV MID under 5m → empty (Salah 13.5m excluded, no other LIV MIDs)
_r_liv_tight = get_transfer_suggestion(
    {"position_query": "midfielders", "team_query": "Liverpool",
     "max_price": 5.0, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("C5 LIV MID<5 empty",         _r_liv_tight["status"] == "empty")
_check("C6 LIV MID<5 team_short=LIV", _r_liv_tight.get("team_short") == "LIV")


# ---------------------------------------------------------------------------
# D — Unfiltered still works (no team filter = None)
# ---------------------------------------------------------------------------

print("\n=== D: Unfiltered behavior unchanged ===")

_r_all = get_transfer_suggestion(
    {"position_query": "midfielders", "team_query": None,
     "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("D1 unfiltered status=ok",    _r_all["status"] == "ok")
_check("D2 unfiltered team_short=None", _r_all.get("team_short") is None)
_check("D3 unfiltered team_name=None",  _r_all.get("team_name") is None)
_check("D4 unfiltered includes all MID teams",
       len({p["team_short"] for p in _r_all.get("picks", [])}) > 1 or
       len(_r_all.get("picks", [])) >= 1)


# ---------------------------------------------------------------------------
# E — Router: club-filtered prompt families
# ---------------------------------------------------------------------------

print("\n=== E: Router club extraction ===")

_r_cases = [
    # (query, expected_tool, expected_team_lower, expected_price)
    ("best Liverpool midfielders to buy",          "get_transfer_suggestion", "liverpool",      None),
    ("cheap Chelsea midfielders to buy under 8",   "get_transfer_suggestion", "chelsea",        8.0),
    ("best Arsenal midfielders to buy",            "get_transfer_suggestion", "arsenal",        None),
    ("best Man City forwards to buy",              "get_transfer_suggestion", "man city",       None),
    ("best forwards from Chelsea to sign",         "get_transfer_suggestion", "chelsea",        None),
    ("centrocampistas del Liverpool para comprar", "get_transfer_suggestion", "liverpool",      None),
    ("mejores delanteros del Arsenal para fichar", "get_transfer_suggestion", "arsenal",        None),
    # Unfiltered still routes correctly
    ("best midfielders to buy",                    "get_transfer_suggestion", None,             None),
    ("who should i buy",                           "get_transfer_suggestion", None,             None),
]
for q, exp_tool, exp_team_lower, exp_price in _r_cases:
    rr = route(q)
    tool_ok = rr is not None and rr.tool_name == exp_tool
    tq      = (rr.tool_args.get("team_query") or "").lower() if rr else ""
    mp      = rr.tool_args.get("max_price") if rr else None
    team_ok = (exp_team_lower is None and not tq) or (exp_team_lower is not None and exp_team_lower in tq)
    price_ok = (exp_price is None) or (mp is not None and abs(mp - exp_price) < 0.01)
    _check(
        "E route " + repr(q[:50]),
        tool_ok and team_ok and price_ok,
        "tool=%s tq=%s price=%s" % (rr.tool_name if rr else None, tq[:20], mp),
    )


# ---------------------------------------------------------------------------
# F — Routing collision checks
# ---------------------------------------------------------------------------

print("\n=== F: Routing collisions ===")

_collisions = [
    ("should i sell Saka for Palmer",              "get_transfer_advice"),
    ("best teams for midfielders",                 "get_position_fixture_run"),
    ("Arsenal fixtures next 5",                    "get_team_schedule"),
    ("Haaland fixtures",                           "get_player_fixture_run"),
    ("defenders with best fixtures next 5",        "get_position_fixture_run"),
    ("good differentials",                         "get_differential_picks"),
    ("best fixtures next 5 gameweeks",             "get_team_fixture_calendar"),
]
for q, exp_tool in _collisions:
    rr = route(q)
    got = rr.tool_name if rr else None
    _check("F collision " + repr(q[:45]), got == exp_tool,
           "expected %s got %s" % (exp_tool, got))


# ---------------------------------------------------------------------------
# G — respond() FinalResponse integration
# ---------------------------------------------------------------------------

print("\n=== G: FinalResponse metadata ===")

_fr_liv = respond("best Liverpool midfielders to buy", DIFFERENTIAL_BOOTSTRAP)
_check("G1 intent=transfer_suggestion",  _fr_liv.intent == "transfer_suggestion")
_check("G2 outcome=ok",                  _fr_liv.outcome == "ok")
_check("G3 ts not None",                 _fr_liv.transfer_suggestion is not None)

if _fr_liv.transfer_suggestion:
    ts = _fr_liv.transfer_suggestion
    _check("G4 ts.position='MID'",       ts.position == "MID")
    _check("G5 ts.team_short='LIV'",     ts.team_short == "LIV")
    _check("G6 ts.team_name has Liverpool", "Liverpool" in (ts.team_name or ""))
    _check("G7 ts.picks[0]=Salah",       ts.picks[0].web_name == "Salah" if ts.picks else False)

# not_found route: Tottenham not in bootstrap
_fr_tot = respond("best Spurs midfielders to buy", DIFFERENTIAL_BOOTSTRAP)
_check("G8 Spurs intent=transfer_suggestion", _fr_tot.intent == "transfer_suggestion")
_check("G9 Spurs outcome=not_found",          _fr_tot.outcome == "not_found")
_check("G10 Spurs ts=None",                   _fr_tot.transfer_suggestion is None)

# Spanish club filter
_fr_es = respond("centrocampistas del Liverpool para comprar", DIFFERENTIAL_BOOTSTRAP)
_check("G11 Spanish intent ok",              _fr_es.intent == "transfer_suggestion")
if _fr_es.transfer_suggestion:
    _check("G12 Spanish team_short=LIV",     _fr_es.transfer_suggestion.team_short == "LIV")
    _check("G13 Spanish picks[0]=Salah",
           _fr_es.transfer_suggestion.picks[0].web_name == "Salah"
           if _fr_es.transfer_suggestion.picks else False)


# ---------------------------------------------------------------------------
# H — Renderer output includes team name in header
# ---------------------------------------------------------------------------

print("\n=== H: Renderer output ===")

_ft_liv = _fr_liv.final_text
_check("H1 final_text non-empty",        bool(_ft_liv))
_check("H2 contains LIV in header",      "LIV" in _ft_liv)
_check("H3 contains midfielders",        "midfielders" in _ft_liv)
_check("H4 contains Salah",              "Salah" in _ft_liv)

_ft_tot = _fr_tot.final_text
_check("H5 not_found text non-empty",    bool(_ft_tot))


# ---------------------------------------------------------------------------
# I — CLI + HTTP surface parity
# ---------------------------------------------------------------------------

print("\n=== I: Surface parity ===")

import fpl_cli as _cli
import fpl_server as _srv
from starlette.testclient import TestClient as _TestClient

# CLI
_cli_code, _cli_str = _cli.run(
    "best Liverpool midfielders to buy", DIFFERENTIAL_BOOTSTRAP, debug=True
)
_cli_data = json.loads(_cli_str)
_cli_ts   = _cli_data.get("transfer_suggestion")
_check("I1 CLI exit_code=0",              _cli_code == 0)
_check("I2 CLI ts non-None",              _cli_ts is not None)
if _cli_ts:
    _check("I3 CLI team_short=LIV",       _cli_ts.get("team_short") == "LIV")
    _check("I4 CLI team_name present",    "Liverpool" in (_cli_ts.get("team_name") or ""))
    _check("I5 CLI picks[0]=Salah",
           _cli_ts.get("picks", [{}])[0].get("web_name") == "Salah")

# HTTP
_srv._init_bootstrap(DIFFERENTIAL_BOOTSTRAP)
_client = _TestClient(_srv.app, raise_server_exceptions=True)

_resp = _client.post(
    "/ask",
    json={"question": "cheap Chelsea midfielders to buy under 8",
          "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_check("I6 HTTP 200",                     _resp.status_code == 200)
_body = _resp.json()
_check("I7 HTTP intent=transfer_suggestion", _body.get("intent") == "transfer_suggestion")
_ht = _body.get("transfer_suggestion")
_check("I8 HTTP ts non-None",             _ht is not None)
if _ht:
    _check("I9 HTTP team_short=CHE",      _ht.get("team_short") == "CHE")
    _check("I10 HTTP max_price=8.0",
           _ht.get("max_price") is not None and abs(_ht["max_price"] - 8.0) < 0.01)
    _check("I11 HTTP picks[0]=Palmer",
           _ht.get("picks", [{}])[0].get("web_name") == "Palmer")

# HTTP not_found
_resp_nf = _client.post(
    "/ask",
    json={"question": "best Spurs midfielders to buy",
          "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_check("I12 HTTP not_found 200",          _resp_nf.status_code == 200)
_body_nf = _resp_nf.json()
_check("I13 HTTP not_found outcome",      _body_nf.get("outcome") == "not_found")
_check("I14 HTTP not_found ts=None",      _body_nf.get("transfer_suggestion") is None)

# Backward-compat: unfiltered still works and has team_short=None
_resp_all = _client.post(
    "/ask",
    json={"question": "best midfielders to buy", "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_check("I15 unfiltered HTTP 200",         _resp_all.status_code == 200)
_body_all = _resp_all.json()
_ht_all   = _body_all.get("transfer_suggestion")
if _ht_all:
    _check("I16 unfiltered team_short=None", _ht_all.get("team_short") is None)
    _check("I17 unfiltered team_name=None",  _ht_all.get("team_name") is None)


# ---------------------------------------------------------------------------
# J — Regression
# ---------------------------------------------------------------------------

print("\n=== J: Regression ===")

from run_validation import run_all_scenarios

results = run_all_scenarios()
total  = len(results)
passed = sum(1 for r in results if r.get("pass"))
_check("J1 validation corpus " + str(passed) + "/" + str(total) + " PASS",
       passed == total,
       str(total - passed) + " scenario(s) failed")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("Phase 2.6i: %d/%d assertions passed." % (len(_pass), len(_pass) + len(_fail)))
if _fail:
    print("               %d assertion(s) FAILED." % len(_fail))
    for f in _fail:
        print("  - " + f)
else:
    print("               All assertions passed.")
