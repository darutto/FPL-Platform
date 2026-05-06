"""
run_phase26h_tests.py
=====================
Phase 2.6h: Transfer suggestion by position and price.

New intent: transfer_suggestion
New tool:   get_transfer_suggestion

Ranking: composite_score = form / avg_fdr (higher = better)
Position filter:  optional — if omitted, returns "ALL" positions
Price ceiling:    optional — now_cost <= max_price * 10 (FPL units)

Expected values (DIFFERENTIAL_BOOTSTRAP, horizon=5, current_gw=28)
-------------------------------------------------------------------
Available players in DIFFERENTIAL_BOOTSTRAP:
  Haaland (FWD, MCI, 14.5m, form 8.0, 52.3%)  MCI avg_fdr=3.0 composite=2.67
  Salah   (MID, LIV, 13.5m, form 9.5, 64.1%)  LIV avg_fdr=2.8 composite=3.39
  Raya    (GKP, ARS,  5.5m, form 6.0, 22.0%)  ARS avg_fdr=3.6 composite=1.67
  Palmer  (MID, CHE,  6.0m, form 7.0,  3.5%)  CHE avg_fdr=3.6 composite=1.94
  Mbeumo  (FWD, MUN,  7.5m, form 5.0,  8.2%)  MUN avg_fdr=4.2 composite=1.19

MID (no price): Salah #1 (3.39), Palmer #2 (1.94)
MID (under 8m): only Palmer #1
FWD:            Haaland #1 (2.67), Mbeumo #2 (1.19)
GKP:            Raya #1 (1.67)
ALL:            Salah #1 (3.39), Haaland #2 (2.67), Palmer #3 (1.94), Raya #4 (1.67), Mbeumo #5 (1.19)

Supported prompt families
--------------------------
  English position: "best midfielders to buy"
  English position + price: "best midfielders to buy under 8"
  English position suffix: "midfielders to buy", "midfielders to sign"
  English prefix: "who should I buy"
  Spanish prefix: "mejores delanteros para fichar"
  Spanish: "a quién fichar"

Collision-safe
--------------
  "should I sell Saka for Palmer"  -> transfer_advice    (sell+buy)
  "good differentials"             -> differential_picks (low ownership)
  "defenders with best fixtures"   -> position_fixture_run (FDR ranking)
  "Arsenal fixtures next 5"        -> team_schedule      (team calendar)
  "Haaland fixtures"               -> player_fixture_run (player schedule)

Regression
----------
run_validation:       74/74
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
from fpl_grounded_assistant.transfer_suggestion import (
    get_transfer_suggestion,
    _resolve_position,
    _team_avg_fdr,
    _difficulty_label,
)
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
# A — Unit helpers
# ---------------------------------------------------------------------------

print("\n=== A: Unit helpers ===")

_check("A1 resolve 'midfielders'->MID",  _resolve_position("midfielders") == "MID")
_check("A2 resolve 'delanteros'->FWD",   _resolve_position("delanteros")  == "FWD")
_check("A3 resolve 'defensa'->DEF",      _resolve_position("defensa")     == "DEF")
_check("A4 resolve 'portero'->GKP",      _resolve_position("portero")     == "GKP")
_check("A5 resolve unknown -> None",     _resolve_position("anything")    is None)

tf = DIFFERENTIAL_BOOTSTRAP.get("team_fixtures", {})
_check("A6 LIV avg_fdr=2.8", abs(_team_avg_fdr(14, tf, 28, 5) - 2.8) < 0.01)
_check("A7 MCI avg_fdr=3.0", abs(_team_avg_fdr(13, tf, 28, 5) - 3.0) < 0.01)
_check("A8 MUN avg_fdr=4.2", abs(_team_avg_fdr(11, tf, 28, 5) - 4.2) < 0.01)
_check("A9 missing team -> 3.0 (neutral)", _team_avg_fdr(999, tf, 28, 5) == 3.0)

_check("A10 2.8 -> easy",     _difficulty_label(2.8) == "easy")
_check("A11 3.0 -> moderate", _difficulty_label(3.0) == "moderate")
_check("A12 3.5 -> hard",     _difficulty_label(3.5) == "hard")
_check("A13 4.2 -> hard",     _difficulty_label(4.2) == "hard")


# ---------------------------------------------------------------------------
# B — Handler: position filter
# ---------------------------------------------------------------------------

print("\n=== B: Handler position filter ===")

_mid = get_transfer_suggestion(
    {"position_query": "midfielders", "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B1 MID status=ok",            _mid["status"] == "ok")
_check("B2 MID position='MID'",       _mid.get("position") == "MID")
_check("B3 MID position_label",       _mid.get("position_label") == "midfielders")
_check("B4 MID max_price=None",       _mid.get("max_price") is None)
_check("B5 MID picks is list",        isinstance(_mid.get("picks"), list))
_check("B6 MID picks all MID",        all(p["position"] == "MID" for p in _mid.get("picks", [])))
_check("B7 MID picks[0] = Salah",     _mid.get("picks", [{}])[0].get("web_name") == "Salah")
_check("B8 MID picks[1] = Palmer",
       len(_mid.get("picks", [])) >= 2 and _mid["picks"][1]["web_name"] == "Palmer")

# Composite scores
if len(_mid.get("picks", [])) >= 2:
    s1 = _mid["picks"][0]["composite_score"]
    s2 = _mid["picks"][1]["composite_score"]
    _check("B9 MID picks sorted descending", s1 >= s2)
    _check("B10 Salah composite ~3.39", abs(s1 - 9.5 / 2.8) < 0.01)
    _check("B11 Palmer composite ~1.94", abs(s2 - 7.0 / 3.6) < 0.02)

# FWD filter
_fwd = get_transfer_suggestion(
    {"position_query": "forwards", "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B12 FWD status=ok",           _fwd["status"] == "ok")
_check("B13 FWD picks all FWD",       all(p["position"] == "FWD" for p in _fwd.get("picks", [])))
_check("B14 FWD picks[0] = Haaland",  _fwd.get("picks", [{}])[0].get("web_name") == "Haaland")

# GKP filter
_gkp = get_transfer_suggestion(
    {"position_query": "goalkeeper", "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B15 GKP status=ok",           _gkp["status"] == "ok")
_check("B16 GKP position='GKP'",      _gkp.get("position") == "GKP")
_check("B17 GKP picks[0] = Raya",     _gkp.get("picks", [{}])[0].get("web_name") == "Raya")

# ALL (no position)
_all = get_transfer_suggestion(
    {"position_query": None, "max_price": None, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("B18 ALL status=ok",           _all["status"] == "ok")
_check("B19 ALL position='ALL'",      _all.get("position") == "ALL")
_check("B20 ALL picks has MID+FWD",
       len({p["position"] for p in _all.get("picks", [])}) > 1)


# ---------------------------------------------------------------------------
# C — Handler: price ceiling filter
# ---------------------------------------------------------------------------

print("\n=== C: Price ceiling ===")

_mid_8 = get_transfer_suggestion(
    {"position_query": "midfielders", "max_price": 8.0, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("C1 MID under 8 status=ok",    _mid_8["status"] == "ok")
_check("C2 MID under 8 max_price=8.0", _mid_8.get("max_price") == 8.0)
_check("C3 MID under 8 picks",         len(_mid_8.get("picks", [])) >= 1)
# Salah (13.5m = now_cost 135 > 80) should be excluded
_check("C4 Salah excluded",            not any(p["web_name"] == "Salah" for p in _mid_8.get("picks", [])))
_check("C5 Palmer included",           any(p["web_name"] == "Palmer" for p in _mid_8.get("picks", [])))
# All picks must be under ceiling
_check("C6 all picks <= 8.0m",         all(p.get("now_cost_m", 0) <= 8.0 for p in _mid_8.get("picks", [])))

# Tight ceiling — no player
_tight = get_transfer_suggestion(
    {"position_query": "midfielders", "max_price": 5.0, "horizon": 5},
    DIFFERENTIAL_BOOTSTRAP,
)
_check("C7 tight ceiling -> empty",    _tight["status"] == "empty")


# ---------------------------------------------------------------------------
# D — Handler: output fields
# ---------------------------------------------------------------------------

print("\n=== D: Output fields ===")

_p0 = _mid.get("picks", [{}])[0]
_check("D1 pick has now_cost",         "now_cost" in _p0)
_check("D2 pick has now_cost_m",       "now_cost_m" in _p0)
_check("D3 now_cost_m = now_cost/10",  abs(_p0.get("now_cost_m", 0) - _p0.get("now_cost", 0) / 10) < 0.01)
_check("D4 pick has form",             "form" in _p0)
_check("D5 pick has avg_fdr",          "avg_fdr" in _p0)
_check("D6 pick has difficulty_label", "difficulty_label" in _p0)
_check("D7 Salah LIV avg_fdr=2.8",    abs(_p0.get("avg_fdr", 0) - 2.8) < 0.01)
_check("D8 Salah label=easy",          _p0.get("difficulty_label") == "easy")
_check("D9 pick has composite_score",  "composite_score" in _p0)
_check("D10 pick has ownership",       "ownership" in _p0)
_check("D11 pick has rank=1",          _p0.get("rank") == 1)

# Missing context (no elements)
_no_el = get_transfer_suggestion(
    {"position_query": "midfielders", "horizon": 5},
    {"teams": STANDARD_BOOTSTRAP["teams"]},
)
_check("D12 no elements -> missing_context", _no_el["status"] == "missing_context")


# ---------------------------------------------------------------------------
# E — Router patterns
# ---------------------------------------------------------------------------

print("\n=== E: Router patterns ===")

_routing_cases = [
    # (query, has_position, expected_pos_lower, expected_max_price)
    ("best midfielders to buy",              True,  "midfielder",  None),
    ("best midfielders to buy under 8",      True,  "midfielder",  8.0),
    ("midfielders to buy",                   True,  "midfielder",  None),
    ("cheap forwards to buy",                True,  "forward",     None),
    ("cheap forwards to buy under 7.5",      True,  "forward",     7.5),
    ("defenders to sign",                    True,  "defender",    None),
    ("best defenders to transfer in",        True,  "defender",    None),
    ("mejores delanteros para fichar",       True,  "delantero",   None),
    ("who should i buy",                     False, None,          None),
    ("a quien fichar",                       False, None,          None),
]
for q, has_pos, exp_pos_lower, exp_price in _routing_cases:
    rr = route(q)
    tool_ok = rr is not None and rr.tool_name == "get_transfer_suggestion"
    if tool_ok and has_pos:
        pq = (rr.tool_args.get("position_query") or "").lower()
        pos_ok = exp_pos_lower is not None and exp_pos_lower in pq
    else:
        pos_ok = not has_pos or True
    if tool_ok and exp_price is not None:
        price_ok = rr.tool_args.get("max_price") is not None and abs(rr.tool_args["max_price"] - exp_price) < 0.01
    else:
        price_ok = exp_price is None
    _check(
        "E route " + repr(q[:50]),
        tool_ok and pos_ok and price_ok,
        "tool=%s args=%s" % (rr.tool_name if rr else None, rr.tool_args if rr else None),
    )


# ---------------------------------------------------------------------------
# F — Routing non-regression (collision checks)
# ---------------------------------------------------------------------------

print("\n=== F: Routing non-regression ===")

_non_hijack = [
    ("should i sell Saka for Palmer",           "get_transfer_advice"),
    ("good differentials",                      "get_differential_picks"),
    ("defenders with best fixtures next 5 gameweeks", "get_position_fixture_run"),
    ("best teams for midfielders",              "get_position_fixture_run"),
    ("Arsenal fixtures next 5",                "get_team_schedule"),
    ("Haaland fixtures",                        "get_player_fixture_run"),
    ("best fixtures next 5 gameweeks",          "get_team_fixture_calendar"),
    ("should i captain Haaland",                "get_captain_score"),
]
for q, exp_tool in _non_hijack:
    rr = route(q)
    got = rr.tool_name if rr else None
    _check("F non-hijack " + repr(q), got == exp_tool,
           "expected %s, got %s" % (exp_tool, got))


# ---------------------------------------------------------------------------
# G — respond() integration
# ---------------------------------------------------------------------------

print("\n=== G: respond() integration ===")

_fr_mid = respond("best midfielders to buy", DIFFERENTIAL_BOOTSTRAP)
_check("G1 intent=transfer_suggestion", _fr_mid.intent == "transfer_suggestion")
_check("G2 outcome=ok",                 _fr_mid.outcome == "ok")
_check("G3 transfer_suggestion not None", _fr_mid.transfer_suggestion is not None)
_check("G4 differential is None",       _fr_mid.differential is None)
_check("G5 fixture_run is None",        _fr_mid.fixture_run is None)

if _fr_mid.transfer_suggestion:
    ts = _fr_mid.transfer_suggestion
    _check("G6 position='MID'",         ts.position == "MID")
    _check("G7 picks non-empty",        len(ts.picks) > 0)
    _check("G8 picks[0]=Salah",         ts.picks[0].web_name == "Salah")
    _check("G9 picks[0].avg_fdr=2.8",   abs(ts.picks[0].avg_fdr - 2.8) < 0.01)
    _check("G10 picks[0].label=easy",   ts.picks[0].difficulty_label == "easy")
    _check("G11 now_cost_m = cost/10",  abs(ts.picks[0].now_cost_m - ts.picks[0].now_cost / 10) < 0.01)

_fr_price = respond("best midfielders to buy under 8", DIFFERENTIAL_BOOTSTRAP)
_check("G12 price-filtered intent ok", _fr_price.intent == "transfer_suggestion")
if _fr_price.transfer_suggestion:
    _check("G13 max_price=8.0",         _fr_price.transfer_suggestion.max_price == 8.0)
    _check("G14 price-filtered pick",
           all(p.now_cost_m <= 8.0 for p in _fr_price.transfer_suggestion.picks))

_fr_es = respond("mejores delanteros para fichar", DIFFERENTIAL_BOOTSTRAP)
_check("G15 Spanish intent ok",        _fr_es.intent == "transfer_suggestion")
if _fr_es.transfer_suggestion:
    _check("G16 Spanish position=FWD",  _fr_es.transfer_suggestion.position == "FWD")
    _check("G17 Spanish picks[0]=Haaland",
           _fr_es.transfer_suggestion.picks[0].web_name == "Haaland" if _fr_es.transfer_suggestion.picks else False)


# ---------------------------------------------------------------------------
# H — Renderer output
# ---------------------------------------------------------------------------

print("\n=== H: Renderer output ===")

_ft = _fr_mid.final_text
_check("H1 final_text non-empty",      bool(_ft))
_check("H2 has 'midfielders'",         "midfielders" in _ft)
_check("H3 has Salah",                 "Salah" in _ft)
_check("H4 has form",                  "form" in _ft.lower())
_check("H5 has avg FDR",               "avg FDR" in _ft)

_ft_price = _fr_price.final_text
_check("H6 price-filtered has '£8.0m'", "8.0m" in _ft_price or "8.0" in _ft_price)

_ft_empty = respond("best goalkeepers to buy under 4", DIFFERENTIAL_BOOTSTRAP).final_text
_check("H7 empty result non-empty text", bool(_ft_empty))


# ---------------------------------------------------------------------------
# I — Surface parity (CLI + HTTP)
# ---------------------------------------------------------------------------

print("\n=== I: Surface parity ===")

import fpl_cli as _cli
import fpl_server as _srv
from starlette.testclient import TestClient as _TestClient

_cli_code, _cli_str = _cli.run("best midfielders to buy", DIFFERENTIAL_BOOTSTRAP, debug=True)
_cli_data = json.loads(_cli_str)
_cli_ts   = _cli_data.get("transfer_suggestion")
_check("I1 CLI exit_code=0",              _cli_code == 0)
_check("I2 CLI transfer_suggestion",      _cli_ts is not None)
if _cli_ts:
    _check("I3 CLI position='MID'",       _cli_ts.get("position") == "MID")
    _check("I4 CLI picks is list",        isinstance(_cli_ts.get("picks"), list))
    if _cli_ts.get("picks"):
        _p = _cli_ts["picks"][0]
        _check("I5 CLI pick has avg_fdr",     "avg_fdr" in _p)
        _check("I6 CLI pick has now_cost_m",  "now_cost_m" in _p)

_srv._init_bootstrap(DIFFERENTIAL_BOOTSTRAP)
_client = _TestClient(_srv.app, raise_server_exceptions=True)
_resp = _client.post(
    "/ask",
    json={"question": "best midfielders to buy", "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_check("I7 HTTP 200",                     _resp.status_code == 200)
_body = _resp.json()
_check("I8 HTTP intent=transfer_suggestion", _body.get("intent") == "transfer_suggestion")
_ht = _body.get("transfer_suggestion")
_check("I9 HTTP transfer_suggestion",     _ht is not None)
if _ht:
    _check("I10 HTTP position='MID'",     _ht.get("position") == "MID")
    _check("I11 HTTP picks[0]=Salah",
           _ht.get("picks", [{}])[0].get("web_name") == "Salah")

# Price-filtered HTTP
_resp_p = _client.post(
    "/ask",
    json={"question": "best midfielders to buy under 8", "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_check("I12 HTTP price-filtered 200",     _resp_p.status_code == 200)
_body_p = _resp_p.json()
_ht_p   = _body_p.get("transfer_suggestion")
if _ht_p:
    _check("I13 HTTP price picks[0]=Palmer",
           _ht_p.get("picks", [{}])[0].get("web_name") == "Palmer")

# Backward-compat: existing fields unaffected
_resp_diff = _client.post(
    "/ask",
    json={"question": "good differentials", "bootstrap": DIFFERENTIAL_BOOTSTRAP},
)
_check("I14 differentials unaffected",    _resp_diff.json().get("intent") == "differential_picks")
_check("I15 differentials no ts field",   _resp_diff.json().get("transfer_suggestion") is None)


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
print("Phase 2.6h: %d/%d assertions passed." % (len(_pass), len(_pass) + len(_fail)))
if _fail:
    print("               %d assertion(s) FAILED." % len(_fail))
    for f in _fail:
        print("  - " + f)
else:
    print("               All assertions passed.")
