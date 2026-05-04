"""
run_phase26f_tests.py
=====================
Phase 2.6f: Team FDR context enrichment on player fixture run.

Existing intent: player_fixture_run (UNCHANGED)
Enriched tool output: team_fdr_context block nested in get_player_fixture_run response
No new routing — data enrichment only.

New fields
----------
get_player_fixture_run output (status="ok") gains:

  team_fdr_context: {
      avg_fdr:          float   -- average FDR across the returned fixtures (2 d.p.)
      difficulty_label: str     -- "easy" | "moderate" | "hard"
      gw_from:          int     -- first GW in the fixture list
      gw_to:            int     -- last GW in the fixture list
  }

  team_fdr_context is None when fixtures is empty.

difficulty_label thresholds
---------------------------
  avg_fdr < 3.0  -> "easy"
  avg_fdr < 3.5  -> "moderate"
  avg_fdr >= 3.5 -> "hard"

Expected values (STANDARD_BOOTSTRAP, GW28, horizon=5)
------------------------------------------------------
  Salah   (LIV) GW28-32: FDR 2,3,4,3,2  total=14  avg=2.8  label="easy"
  Haaland (MCI) GW28-32: FDR 3,4,2,3,3  total=15  avg=3.0  label="moderate"
  Saka    (ARS) GW28-32: FDR 3,3,4,5,3  total=18  avg=3.6  label="hard"

FinalResponse.fixture_run.team_fdr_context carries the TeamFDRContext dataclass.
Renderer appends one line: "{team} have an/a {label} run over GW{X}-GW{Y}, avg FDR {avg}."
CLI debug payload["fixture_run"]["team_fdr_context"] carries the dict.
HTTP response body["fixture_run"]["team_fdr_context"] carries the dict.

Regression
----------
run_validation:       71/71
run_phase26e4_tests:  110/110 (run independently)
run_phase26d4_tests:  35/35   (run independently)
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

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.player_fixture_run import (
    get_player_fixture_run,
    _compute_team_fdr_context,
)
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
# A — _compute_team_fdr_context unit tests
# ---------------------------------------------------------------------------

print("\n=== A: _compute_team_fdr_context ===")

_empty = _compute_team_fdr_context([])
_check("A1 empty fixtures -> None", _empty is None)

# avg 2.0 -> easy
_fx_easy = [
    {"gameweek": 28, "difficulty": 2},
    {"gameweek": 29, "difficulty": 2},
]
_ctx_easy = _compute_team_fdr_context(_fx_easy)
_check("A2 avg 2.0 -> easy label",    _ctx_easy is not None and _ctx_easy["difficulty_label"] == "easy")
_check("A3 avg 2.0 value",            _ctx_easy is not None and abs(_ctx_easy["avg_fdr"] - 2.0) < 0.01)
_check("A4 gw_from=28",               _ctx_easy is not None and _ctx_easy["gw_from"] == 28)
_check("A5 gw_to=29",                 _ctx_easy is not None and _ctx_easy["gw_to"] == 29)

# avg 3.0 -> moderate (boundary: 3.0 is NOT "easy", must be "moderate")
_fx_mod = [
    {"gameweek": 28, "difficulty": 3},
    {"gameweek": 29, "difficulty": 3},
]
_ctx_mod = _compute_team_fdr_context(_fx_mod)
_check("A6 avg 3.0 -> moderate",      _ctx_mod is not None and _ctx_mod["difficulty_label"] == "moderate")

# avg 3.5 -> hard (boundary: 3.5 is "hard")
_fx_hard = [
    {"gameweek": 28, "difficulty": 3},
    {"gameweek": 29, "difficulty": 4},
]
_ctx_hard = _compute_team_fdr_context(_fx_hard)
_check("A7 avg 3.5 -> hard",          _ctx_hard is not None and _ctx_hard["difficulty_label"] == "hard")

# avg 4.0 -> hard
_fx_vhard = [{"gameweek": 28, "difficulty": 4}, {"gameweek": 29, "difficulty": 4}]
_ctx_vhard = _compute_team_fdr_context(_fx_vhard)
_check("A8 avg 4.0 -> hard",          _ctx_vhard is not None and _ctx_vhard["difficulty_label"] == "hard")

# single fixture
_fx_single = [{"gameweek": 30, "difficulty": 2}]
_ctx_single = _compute_team_fdr_context(_fx_single)
_check("A9 single fixture gw_from==gw_to", _ctx_single is not None and _ctx_single["gw_from"] == _ctx_single["gw_to"] == 30)


# ---------------------------------------------------------------------------
# B — Handler output: team_fdr_context fields present and correct
# ---------------------------------------------------------------------------

print("\n=== B: Handler output ===")

# Salah (LIV): avg 2.8 -> easy
_r_salah = get_player_fixture_run("Salah", STANDARD_BOOTSTRAP)
_check("B1 Salah status=ok",          _r_salah["status"] == "ok")
_ctx_salah = _r_salah.get("team_fdr_context")
_check("B2 Salah ctx non-None",       _ctx_salah is not None)
if _ctx_salah:
    _check("B3 Salah avg_fdr=2.8",    abs(_ctx_salah["avg_fdr"] - 2.8) < 0.01)
    _check("B4 Salah label=easy",     _ctx_salah["difficulty_label"] == "easy")
    _check("B5 Salah gw_from=28",     _ctx_salah["gw_from"] == 28)
    _check("B6 Salah gw_to=32",       _ctx_salah["gw_to"] == 32)

# Haaland (MCI): avg 3.0 -> moderate
_r_haal = get_player_fixture_run("Haaland", STANDARD_BOOTSTRAP)
_check("B7 Haaland status=ok",        _r_haal["status"] == "ok")
_ctx_haal = _r_haal.get("team_fdr_context")
_check("B8 Haaland ctx non-None",     _ctx_haal is not None)
if _ctx_haal:
    _check("B9 Haaland avg_fdr=3.0",  abs(_ctx_haal["avg_fdr"] - 3.0) < 0.01)
    _check("B10 Haaland label=moderate", _ctx_haal["difficulty_label"] == "moderate")

# Saka (ARS): avg 3.6 -> hard
_r_saka = get_player_fixture_run("Saka", STANDARD_BOOTSTRAP)
_check("B11 Saka status=ok",          _r_saka["status"] == "ok")
_ctx_saka = _r_saka.get("team_fdr_context")
if _ctx_saka:
    _check("B12 Saka avg_fdr=3.6",    abs(_ctx_saka["avg_fdr"] - 3.6) < 0.01)
    _check("B13 Saka label=hard",     _ctx_saka["difficulty_label"] == "hard")

# Raya (ARS): same team as Saka — context must match
_r_raya = get_player_fixture_run("Raya", STANDARD_BOOTSTRAP)
_check("B14 Raya status=ok",          _r_raya["status"] == "ok")
_ctx_raya = _r_raya.get("team_fdr_context")
if _ctx_raya and _ctx_saka:
    _check("B15 Raya ctx matches Saka", _ctx_raya["avg_fdr"] == _ctx_saka["avg_fdr"])


# ---------------------------------------------------------------------------
# C — Missing team graceful None
# ---------------------------------------------------------------------------

print("\n=== C: Missing team -> None ===")

# Bootstrap without team_fixtures
_no_tf_out = get_player_fixture_run("Salah", {
    **STANDARD_BOOTSTRAP,
    "team_fixtures": {},
})
_check("C1 no team_fixtures status=missing_context",
       _no_tf_out["status"] == "missing_context")
_check("C2 no team_fixtures ctx absent",
       "team_fdr_context" not in _no_tf_out)

# Bootstrap with team_fixtures but team 14 (LIV) missing
_partial_tf = get_player_fixture_run("Salah", {
    **STANDARD_BOOTSTRAP,
    "team_fixtures": {k: v for k, v in STANDARD_BOOTSTRAP["team_fixtures"].items()
                      if k != 14},
})
_check("C3 missing team -> missing_context",
       _partial_tf["status"] == "missing_context")


# ---------------------------------------------------------------------------
# D — FinalResponse.fixture_run.team_fdr_context (TeamFDRContext dataclass)
# ---------------------------------------------------------------------------

print("\n=== D: FinalResponse metadata ===")

_fr_salah = respond("Salah fixtures", STANDARD_BOOTSTRAP)
_check("D1 intent=player_fixture_run", _fr_salah.intent == "player_fixture_run")
_check("D2 outcome=ok",               _fr_salah.outcome == "ok")
_check("D3 fixture_run not None",     _fr_salah.fixture_run is not None)

if _fr_salah.fixture_run:
    fr_ctx = _fr_salah.fixture_run.team_fdr_context
    _check("D4 team_fdr_context not None",      fr_ctx is not None)
    if fr_ctx:
        _check("D5 avg_fdr=2.8",               abs(fr_ctx.avg_fdr - 2.8) < 0.01)
        _check("D6 difficulty_label=easy",      fr_ctx.difficulty_label == "easy")
        _check("D7 gw_from=28",                fr_ctx.gw_from == 28)
        _check("D8 gw_to=32",                  fr_ctx.gw_to == 32)

_fr_haal = respond("Haaland fixtures", STANDARD_BOOTSTRAP)
if _fr_haal.fixture_run and _fr_haal.fixture_run.team_fdr_context:
    _check("D9 Haaland moderate",
           _fr_haal.fixture_run.team_fdr_context.difficulty_label == "moderate")

_fr_saka = respond("Saka fixtures", STANDARD_BOOTSTRAP)
if _fr_saka.fixture_run and _fr_saka.fixture_run.team_fdr_context:
    _check("D10 Saka hard",
           _fr_saka.fixture_run.team_fdr_context.difficulty_label == "hard")


# ---------------------------------------------------------------------------
# E — Renderer: context summary line appended
# ---------------------------------------------------------------------------

print("\n=== E: Renderer output ===")

_ft_salah = _fr_salah.final_text
_check("E1 final_text non-empty",          bool(_ft_salah))
_check("E2 contains fixture list",         "GW28" in _ft_salah)
_check("E3 contains LIV team",             "LIV" in _ft_salah)
_check("E4 context line present",          "avg FDR" in _ft_salah)
_check("E5 context label 'easy'",          "easy" in _ft_salah)
_check("E6 context avg value 2.8",         "2.8" in _ft_salah)
_check("E7 gw range in context",           "GW28" in _ft_salah and "GW32" in _ft_salah)
_check("E8 'an easy' grammar",             "an easy" in _ft_salah)

_ft_haal = _fr_haal.final_text
_check("E9 Haaland 'moderate' in text",    "moderate" in _ft_haal)
_check("E10 Haaland avg FDR 3.0 in text",  "3.0" in _ft_haal)

_ft_saka = _fr_saka.final_text
_check("E11 Saka 'hard' in text",          "hard" in _ft_saka)

# not-found still works (no context line)
_fr_nf = respond("nonexistentplayer fixtures", STANDARD_BOOTSTRAP)
_check("E12 not_found still renders",      bool(_fr_nf.final_text))
_check("E13 not_found no ctx",             _fr_nf.fixture_run is None)


# ---------------------------------------------------------------------------
# F — CLI and HTTP surface parity
# ---------------------------------------------------------------------------

print("\n=== F: Surface parity ===")

import fpl_cli as _cli
import fpl_server as _srv
from starlette.testclient import TestClient as _TestClient

# CLI
_cli_code, _cli_str = _cli.run("Salah fixtures", STANDARD_BOOTSTRAP, debug=True)
_cli_data = json.loads(_cli_str)
_cli_fr   = _cli_data.get("fixture_run")
_check("F1 CLI exit_code=0",                  _cli_code == 0)
_check("F2 CLI fixture_run non-None",         _cli_fr is not None)
if _cli_fr:
    _cli_ctx = _cli_fr.get("team_fdr_context")
    _check("F3 CLI team_fdr_context non-None", _cli_ctx is not None)
    if _cli_ctx:
        _check("F4 CLI avg_fdr=2.8",           abs(_cli_ctx.get("avg_fdr", 0) - 2.8) < 0.01)
        _check("F5 CLI label=easy",            _cli_ctx.get("difficulty_label") == "easy")
        _check("F6 CLI gw_from=28",            _cli_ctx.get("gw_from") == 28)
        _check("F7 CLI gw_to=32",              _cli_ctx.get("gw_to") == 32)

# HTTP
_srv._init_bootstrap(STANDARD_BOOTSTRAP)
_client = _TestClient(_srv.app, raise_server_exceptions=True)
_resp = _client.post(
    "/ask",
    json={"question": "Haaland fixtures", "bootstrap": STANDARD_BOOTSTRAP},
)
_check("F8 HTTP 200",                         _resp.status_code == 200)
_body = _resp.json()
_check("F9 HTTP intent=player_fixture_run",   _body.get("intent") == "player_fixture_run")
_http_fr = _body.get("fixture_run")
_check("F10 HTTP fixture_run non-None",       _http_fr is not None)
if _http_fr:
    _http_ctx = _http_fr.get("team_fdr_context")
    _check("F11 HTTP team_fdr_context non-None", _http_ctx is not None)
    if _http_ctx:
        _check("F12 HTTP avg_fdr=3.0",         abs(_http_ctx.get("avg_fdr", 0) - 3.0) < 0.01)
        _check("F13 HTTP label=moderate",       _http_ctx.get("difficulty_label") == "moderate")

# HTTP backward-compat: existing fixture fields still present
if _http_fr:
    _check("F14 HTTP web_name still present",  "web_name" in _http_fr)
    _check("F15 HTTP fixtures still present",  "fixtures" in _http_fr)
    _check("F16 HTTP horizon still present",   "horizon" in _http_fr)


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
print("Phase 2.6f: %d/%d assertions passed." % (len(_pass), len(_pass) + len(_fail)))
if _fail:
    print("               %d assertion(s) FAILED." % len(_fail))
    for f in _fail:
        print("  - " + f)
else:
    print("               All assertions passed.")
