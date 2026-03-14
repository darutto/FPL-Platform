"""
run_phase2d_tests.py
====================
Standalone Phase 2d validator — no pytest dependency, one-file runner.

Phase 2d: Auto-derivation of fixture_difficulty from bootstrap["fixture_difficulty_map"].

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2d_tests.py

FDR source
----------
get_fixture_difficulty_map(fixtures, bootstrap) — canonical rule from
captaincy-showdown/src/services/captaincyDataService.ts::getFixtureDifficulty.
FDR = opponent team's ``strength`` (1–5). Defaults to 3 (neutral) for
teams not in the strength map.

Fixture used for BOOTSTRAP_2D
------------------------------
GW28:
  Arsenal (1, strength=4) home vs Man City (13, strength=5) → FDR: ARS=5, MCI=4
  Liverpool (14, strength=5) home vs Chelsea (8, strength=4) → FDR: LIV=4, CHE=5
  Man Utd (11) — blank GW, not in fixture_difficulty_map

Derived fixture_difficulty_map: {1: 5, 13: 4, 14: 4, 8: 5}

Sections
--------
A  — get_fixture_difficulty_map unit tests (pure function, no network)
B  — _derive_fixture_difficulty helper unit tests
C  — tool_get_captain_score: fully auto-derived (map present, no candidate_inputs)
D  — tool_get_captain_score: partial (team in map, some inputs from map some from element)
E  — tool_get_captain_score: fixture_difficulty explicit override (map present but ignored)
F  — tool_get_captain_score: map absent → fixture_difficulty still required (2c regression)
G  — tool_get_captain_score: team not in map → fixture_difficulty required
H  — tool_rank_captain_candidates: fully auto-derived with map
I  — tool_rank_captain_candidates: blank-GW candidate in rankings (partial failure)
J  — derived_fields includes fixture_difficulty when auto-derived
K  — fpl_api_client exports get_fixtures and get_fixture_difficulty_map
L  — Spec validation: runner accepts query-only when map in bootstrap
M  — Harness e2e with fully auto-derived path
N  — Safety regression (ambiguous/not_found unchanged)
O  — Phase 2c regression (all 2c tests pass with 2d bootstrap)

Expected result: 140+ assertions, all PASS.
"""
from __future__ import annotations

import copy
import os
import sys

# ---------------------------------------------------------------------------
# Path setup  (mirrors pytest.ini pythonpath entries)
# ---------------------------------------------------------------------------
_HERE    = os.path.dirname(os.path.abspath(__file__))
_PKGS    = os.path.dirname(_HERE)
_SIBLING = lambda name: os.path.join(_PKGS, name)

for _pkg in [
    _HERE,
    _SIBLING("fpl-data-core"),
    _SIBLING("fpl-api-client"),
    _SIBLING("fpl-player-registry"),
    _SIBLING("fpl-query-tools"),
    _SIBLING("fpl-tool-contract"),
    _SIBLING("fpl-tool-runner"),
    _SIBLING("fpl-captain-engine"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
_passed = 0
_failed = 0
_current_section = ""


def _section(name: str) -> None:
    global _current_section
    _current_section = name
    print(f"\n  [{name}]")


def ok(label: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"    PASS  {label}")
    else:
        _failed += 1
        print(f"    FAIL  {label}")


def approx_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    """Return True if |a - b| <= tol."""
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Shared teams (same as Phase 2c)
_TEAMS = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
]

_EVENTS = [
    {"id": 27, "is_current": False, "is_next": False, "finished": True},
    {"id": 28, "is_current": True,  "is_next": False, "finished": False},
    {"id": 29, "is_current": False, "is_next": True,  "finished": False},
]

_ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP"},
    {"id": 2, "singular_name_short": "DEF"},
    {"id": 3, "singular_name_short": "MID"},
    {"id": 4, "singular_name_short": "FWD"},
]

# Elements with 'minutes' (same as Phase 2c BOOTSTRAP_2C elements)
# xgi_per_90 derived values:
#   Haaland:   1.70 / (1800/90) = 0.085
#   Salah:     1.45 / (2250/90) = 0.058
#   Saka:      0.85 / (900/90)  = 0.085   [chance=75 → risk=25.0]
#   De Bruyne: 0.60 / (270/90)  = 0.200   [injured → risk=100.0]
#   Johnson A: 0.15 / (450/90)  = 0.030   [team 8 = Chelsea, FDR=5]
#   Johnson G: 0.07 / (360/90)  = 0.0175  [team 11 = Man Utd, blank GW]
_ELEMENTS_2D = [
    {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",   "team": 13, "team_code": 43, "element_type": 4,
     "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
     "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
     "expected_goal_involvements": "1.70", "minutes": 1800},
    {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",     "team": 14, "team_code": 1,  "element_type": 3,
     "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
     "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
     "expected_goal_involvements": "1.45", "minutes": 2250},
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",      "team": 1,  "team_code": 3,  "element_type": 3,
     "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
     "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
     "expected_goal_involvements": "0.85", "minutes": 900,
     "chance_of_playing_this_round": 75},
    {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne", "team": 13, "team_code": 43, "element_type": 3,
     "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
     "form": "0.0", "expected_goals": "0.20", "expected_assists": "0.40",
     "expected_goal_involvements": "0.60", "minutes": 270},
    {"id": 6,  "first_name": "Adam",    "second_name": "Johnson",
     "web_name": "Johnson",   "team": 8,  "team_code": 8,  "element_type": 3,
     "status": "a", "now_cost": 50,  "selected_by_percent": "0.5",
     "form": "2.0", "expected_goals": "0.10", "expected_assists": "0.05",
     "expected_goal_involvements": "0.15", "minutes": 450},
    {"id": 7,  "first_name": "Glen",    "second_name": "Johnson",
     "web_name": "Johnson",   "team": 11, "team_code": 12, "element_type": 2,
     "status": "a", "now_cost": 45,  "selected_by_percent": "0.3",
     "form": "1.5", "expected_goals": "0.05", "expected_assists": "0.02",
     "expected_goal_involvements": "0.07", "minutes": 360},
    {"id": 8,  "first_name": "Test",    "second_name": "Player",
     "web_name": "TPlayer",   "team": 1,  "element_type": 1,
     "status": "u"},
]

# GW28 fixtures used to build the difficulty map
# Arsenal (1) home vs Man City (13): ARS FDR = MCI strength = 5, MCI FDR = ARS strength = 4
# Liverpool (14) home vs Chelsea (8): LIV FDR = CHE strength = 4, CHE FDR = LIV strength = 5
# Man Utd (11) has a blank gameweek — NOT in fixtures
_FIXTURES_GW28 = [
    {"team_h": 1,  "team_a": 13, "event": 28},
    {"team_h": 14, "team_a": 8,  "event": 28},
]

# Expected fixture_difficulty_map derived from FIXTURES_GW28 + _TEAMS
# {team_id: fdr}
_EXPECTED_FDR_MAP = {1: 5, 13: 4, 14: 4, 8: 5}

# Pre-computed FDR map injected into BOOTSTRAP_2D
_FDR_MAP = {1: 5, 13: 4, 14: 4, 8: 5}

# Base bootstrap without FDR map (for 2c regression / missing-map tests)
BOOTSTRAP_2D_NO_MAP = {
    "elements":      _ELEMENTS_2D,
    "teams":         _TEAMS,
    "events":        _EVENTS,
    "element_types": _ELEMENT_TYPES,
}

# Full Phase 2d bootstrap: includes fixture_difficulty_map
BOOTSTRAP_2D = {
    "elements":             _ELEMENTS_2D,
    "teams":                _TEAMS,
    "events":               _EVENTS,
    "element_types":        _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}

# Pre-computed expected scores with all-derived inputs (BOOTSTRAP_2D):
# Formula: form_score*0.4 + fixture_score*0.3 + xgi_score*0.2 + minutes_score*0.1
#   form_score    = min((form/10)*100, 100)
#   fixture_score = (6-fdr)*20
#   xgi_score     = xgi*50
#   minutes_score = 100 - risk
#
# Haaland: 80*0.4 + 40*0.3 + 4.25*0.2 + 100*0.1 = 32+12+0.85+10 = 54.85
# Salah:   95*0.4 + 40*0.3 + 2.9*0.2  + 100*0.1 = 38+12+0.58+10 = 60.58
# Saka:    55*0.4 + 20*0.3 + 4.25*0.2 + 75*0.1  = 22+6+0.85+7.5 = 36.35
# De Bru:  0*0.4  + 40*0.3 + 10*0.2   + 0*0.1   = 0+12+2+0      = 14.0
_SCORE_HAALAND = 54.85   # team 13, FDR=4
_SCORE_SALAH   = 60.58   # team 14, FDR=4
_SCORE_SAKA    = 36.35   # team 1,  FDR=5, chance=75
_SCORE_DEBRUYNE = 14.0   # team 13, FDR=4, injured


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
try:
    from fpl_api_client import get_fixtures as _api_get_fixtures
    from fpl_api_client import get_fixture_difficulty_map as _api_get_fdr_map
    from fpl_api_client.fpl_client import FIXTURES_URL
    from fpl_tool_contract.tools import (
        _derive_fixture_difficulty,
        _derive_candidate_inputs,
        _find_element,
        tool_get_captain_score,
        tool_rank_captain_candidates,
    )
    from fpl_tool_runner import run_tool, TOOL_REGISTRY
    from fpl_tool_runner.specs import (
        TOOL_SPECS,
        GET_CAPTAIN_SCORE_SPEC,
        RANK_CAPTAIN_CANDIDATES_SPEC,
    )
    from fpl_grounded_assistant import ask, route, RouteResult
    _imports_ok = True
except Exception as e:
    _imports_ok = False
    print(f"  IMPORT ERROR: {e}")

ok("imports succeeded", _imports_ok)
if not _imports_ok:
    sys.exit(1)


# ===========================================================================
# Section A — get_fixture_difficulty_map unit tests (pure function)
# ===========================================================================
_section("A: get_fixture_difficulty_map (pure function)")

# A1-A4: basic derivation from fixtures + teams
_fdr_result = _api_get_fdr_map(_FIXTURES_GW28, bootstrap=BOOTSTRAP_2D_NO_MAP)
ok("A1 returns dict", isinstance(_fdr_result, dict))
ok("A2 Arsenal (home vs MCI strength=5) → FDR=5", _fdr_result.get(1) == 5)
ok("A3 Man City (away at ARS strength=4) → FDR=4", _fdr_result.get(13) == 4)
ok("A4 Liverpool (home vs CHE strength=4) → FDR=4", _fdr_result.get(14) == 4)
ok("A5 Chelsea (away at LIV strength=5) → FDR=5",  _fdr_result.get(8) == 5)
ok("A6 Man Utd (blank GW) not in map",   11 not in _fdr_result)

# A7: can call with explicit teams list (no bootstrap needed)
_fdr_teams_only = _api_get_fdr_map(_FIXTURES_GW28, teams=_TEAMS)
ok("A7 works with teams= kwarg instead of bootstrap", _fdr_teams_only.get(1) == 5)

# A8: empty fixtures → empty map
_fdr_empty = _api_get_fdr_map([], teams=_TEAMS)
ok("A8 empty fixtures → empty map", _fdr_empty == {})

# A9: unknown opponent team → defaults to 3
_mystery_fixture = [{"team_h": 1, "team_a": 99, "event": 28}]  # team 99 not in teams
_fdr_mystery = _api_get_fdr_map(_mystery_fixture, teams=_TEAMS)
ok("A9 unknown opponent team → FDR defaults to 3",
   _fdr_mystery.get(1) == 3 and _fdr_mystery.get(99) == 4)  # team 99 has ARS(4) as opponent

# A10: FIXTURES_URL constant exported
ok("A10 FIXTURES_URL contains '?event='", "?event=" in FIXTURES_URL)

# A11: result matches pre-computed expected map
ok("A11 result matches expected FDR map", _fdr_result == _EXPECTED_FDR_MAP)


# ===========================================================================
# Section B — _derive_fixture_difficulty helper unit tests
# ===========================================================================
_section("B: _derive_fixture_difficulty")

# B1-B4: lookup from bootstrap with map
ok("B1 team 13 (MCI) → FDR=4",  _derive_fixture_difficulty(13, BOOTSTRAP_2D) == 4)
ok("B2 team 14 (LIV) → FDR=4",  _derive_fixture_difficulty(14, BOOTSTRAP_2D) == 4)
ok("B3 team 1  (ARS) → FDR=5",  _derive_fixture_difficulty(1,  BOOTSTRAP_2D) == 5)
ok("B4 team 8  (CHE) → FDR=5",  _derive_fixture_difficulty(8,  BOOTSTRAP_2D) == 5)

# B5: blank GW team not in map → returns None
ok("B5 team 11 (MUN, blank GW) → None",
   _derive_fixture_difficulty(11, BOOTSTRAP_2D) is None)

# B6: map absent from bootstrap → returns None
ok("B6 no fixture_difficulty_map in bootstrap → None",
   _derive_fixture_difficulty(13, BOOTSTRAP_2D_NO_MAP) is None)

# B7: team_id None → returns None
ok("B7 team_id=None → None", _derive_fixture_difficulty(None, BOOTSTRAP_2D) is None)

# B8: map present but unknown team → returns None
_bs_partial_map = {**BOOTSTRAP_2D_NO_MAP, "fixture_difficulty_map": {99: 3}}
ok("B8 team not in partial map → None",
   _derive_fixture_difficulty(13, _bs_partial_map) is None)


# ===========================================================================
# Section C — tool_get_captain_score: fully auto-derived (map present)
# ===========================================================================
_section("C: tool_get_captain_score fully auto-derived (BOOTSTRAP_2D)")

# C1-C6: Haaland (team 13, FDR=4, form=8.0, xgi=0.085, risk=0.0)
_r_haaland = tool_get_captain_score("Haaland", BOOTSTRAP_2D)
ok("C1 Haaland status=ok",             _r_haaland["status"] == "ok")
ok("C2 Haaland score ≈ 54.85",
   approx_equal(_r_haaland["captain_score"], _SCORE_HAALAND))
ok("C3 Haaland fixture_difficulty=4 (from map)",
   _r_haaland["score_inputs"]["fixture_difficulty"] == 4)
ok("C4 Haaland fixture_difficulty in derived_fields",
   "fixture_difficulty" in _r_haaland["derived_fields"])
ok("C5 Haaland form in derived_fields",
   "form" in _r_haaland["derived_fields"])
ok("C6 Haaland minutes_risk in derived_fields",
   "minutes_risk" in _r_haaland["derived_fields"])

# C7-C10: Salah (team 14, FDR=4, form=9.5, xgi=0.058, risk=0.0)
_r_salah = tool_get_captain_score("Salah", BOOTSTRAP_2D)
ok("C7 Salah status=ok",  _r_salah["status"] == "ok")
ok("C8 Salah score ≈ 60.58",
   approx_equal(_r_salah["captain_score"], _SCORE_SALAH))
ok("C9 Salah fixture_difficulty=4", _r_salah["score_inputs"]["fixture_difficulty"] == 4)
ok("C10 Salah fixture_difficulty in derived_fields",
   "fixture_difficulty" in _r_salah["derived_fields"])

# C11-C14: Saka (team 1, FDR=5, form=5.5, xgi=0.085, risk=25.0 via chance=75)
_r_saka = tool_get_captain_score("Saka", BOOTSTRAP_2D)
ok("C11 Saka status=ok",  _r_saka["status"] == "ok")
ok("C12 Saka score ≈ 36.35",
   approx_equal(_r_saka["captain_score"], _SCORE_SAKA))
ok("C13 Saka fixture_difficulty=5 (home vs MCI)", _r_saka["score_inputs"]["fixture_difficulty"] == 5)
ok("C14 Saka minutes_risk=25.0 (from chance=75)",
   approx_equal(_r_saka["score_inputs"]["minutes_risk"], 25.0))

# C15-C17: De Bruyne (team 13, FDR=4, injured → risk=100.0, score=14.0)
_r_kdb = tool_get_captain_score("De Bruyne", BOOTSTRAP_2D)
ok("C15 De Bruyne status=ok",  _r_kdb["status"] == "ok")
ok("C16 De Bruyne score ≈ 14.0",
   approx_equal(_r_kdb["captain_score"], _SCORE_DEBRUYNE))
ok("C17 De Bruyne minutes_risk=100.0 (injured)",
   approx_equal(_r_kdb["score_inputs"]["minutes_risk"], 100.0))

# C18: no candidate_inputs needed — fully auto-derived
_r_no_inputs = tool_get_captain_score("Haaland", BOOTSTRAP_2D, None)
ok("C18 candidate_inputs=None succeeds when map present",
   _r_no_inputs["status"] == "ok")

# C19: derived_fields sorted alphabetically
ok("C19 derived_fields sorted",
   _r_haaland["derived_fields"] == sorted(_r_haaland["derived_fields"]))


# ===========================================================================
# Section D — Override: explicit fixture_difficulty overrides map
# ===========================================================================
_section("D: explicit fixture_difficulty override (map present but ignored)")

# D1-D5: Haaland with explicit FDR=2 (overrides map's 4)
_r_override = tool_get_captain_score("Haaland", BOOTSTRAP_2D,
                                     {"fixture_difficulty": 2})
# Expected with fdr=2: 80*0.4 + 80*0.3 + 4.25*0.2 + 100*0.1 = 32+24+0.85+10 = 66.85
ok("D1 override FDR=2 → status=ok", _r_override["status"] == "ok")
ok("D2 override FDR=2 used in score_inputs",
   _r_override["score_inputs"]["fixture_difficulty"] == 2)
ok("D3 override score > auto-derived (easier fixture)",
   _r_override["captain_score"] > _r_haaland["captain_score"])
ok("D4 fixture_difficulty NOT in derived_fields (explicit override)",
   "fixture_difficulty" not in _r_override["derived_fields"])
ok("D5 form still in derived_fields (not overridden)",
   "form" in _r_override["derived_fields"])

# D6: override only FDR, other inputs still auto-derived
ok("D6 minutes_risk still derived (0.0 for status=a)",
   approx_equal(_r_override["score_inputs"]["minutes_risk"], 0.0))


# ===========================================================================
# Section E — Map absent: fixture_difficulty still required (2c regression)
# ===========================================================================
_section("E: map absent → fixture_difficulty required (regression)")

# E1-E3: no map in bootstrap → validation error if fdr not provided
_r_no_map = tool_get_captain_score("Haaland", BOOTSTRAP_2D_NO_MAP)
ok("E1 no map + no fdr → status=error", _r_no_map["status"] == "error")
ok("E2 no map + no fdr → code=missing_argument",
   _r_no_map["code"] == "missing_argument")
ok("E3 error message mentions fixture_difficulty",
   "fixture_difficulty" in _r_no_map["message"])

# E4-E5: no map + explicit FDR → ok
_r_explicit_fdr = tool_get_captain_score("Haaland", BOOTSTRAP_2D_NO_MAP,
                                         {"fixture_difficulty": 2})
ok("E4 no map + explicit FDR → status=ok", _r_explicit_fdr["status"] == "ok")
ok("E5 explicit FDR in score_inputs", _r_explicit_fdr["score_inputs"]["fixture_difficulty"] == 2)


# ===========================================================================
# Section F — Blank GW: team not in map → FDR required
# ===========================================================================
_section("F: team not in fixture_difficulty_map (blank GW)")

# Glen Johnson (team 11 = Man Utd, blank GW — not in _FDR_MAP)
# With map present but team 11 absent: fixture_difficulty not in derived
_r_glen_no_fdr = tool_get_captain_score("7", BOOTSTRAP_2D)   # id=7 is Glen Johnson
ok("F1 Glen Johnson (blank GW, no FDR) → error", _r_glen_no_fdr["status"] == "error")
ok("F2 Glen Johnson error code=missing_argument",
   _r_glen_no_fdr.get("code") == "missing_argument")
ok("F3 Glen Johnson error mentions fixture_difficulty",
   "fixture_difficulty" in _r_glen_no_fdr["message"])

# Glen Johnson with explicit FDR → ok
_r_glen_fdr = tool_get_captain_score("7", BOOTSTRAP_2D, {"fixture_difficulty": 3})
ok("F4 Glen Johnson + explicit FDR → ok", _r_glen_fdr["status"] == "ok")
ok("F5 Glen Johnson fixture_difficulty NOT in derived (explicit)",
   "fixture_difficulty" not in _r_glen_fdr["derived_fields"])

# F6: fixture_difficulty_map={} (empty) → equivalent to absent
_bs_empty_map = {**BOOTSTRAP_2D_NO_MAP, "fixture_difficulty_map": {}}
_r_empty_map = tool_get_captain_score("Haaland", _bs_empty_map)
ok("F6 empty fixture_difficulty_map → FDR not derived → error",
   _r_empty_map["status"] == "error")


# ===========================================================================
# Section G — tool_rank_captain_candidates with map
# ===========================================================================
_section("G: tool_rank_captain_candidates fully auto-derived")

_candidates_2d = [
    {"query": "Haaland"},
    {"query": "Salah"},
    {"query": "Saka"},
    {"query": "De Bruyne"},
]
_r_rank = tool_rank_captain_candidates(_candidates_2d, BOOTSTRAP_2D)
ok("G1 rankings status=ok",     _r_rank["status"] == "ok")
ok("G2 rankings total=4",        _r_rank["total"] == 4)
ok("G3 rankings error_count=0",  _r_rank["error_count"] == 0)

# Ranking order: Salah (60.58) > Haaland (54.85) > Saka (36.35) > De Bruyne (14.0)
_rc = _r_rank["ranked_candidates"]
ok("G4 rank 1 = Salah",    _rc[0]["web_name"] == "Salah")
ok("G5 rank 2 = Haaland",  _rc[1]["web_name"] == "Haaland")
ok("G6 rank 3 = Saka",     _rc[2]["web_name"] == "Saka")
ok("G7 rank 4 = De Bruyne", _rc[3]["web_name"] == "De Bruyne")

ok("G8 Salah score ≈ 60.58", approx_equal(_rc[0]["captain_score"], _SCORE_SALAH))
ok("G9 Haaland score ≈ 54.85", approx_equal(_rc[1]["captain_score"], _SCORE_HAALAND))

ok("G10 Salah FDR=4 in score_inputs",
   _rc[0]["score_inputs"]["fixture_difficulty"] == 4)
ok("G11 fixture_difficulty in Salah derived_fields",
   "fixture_difficulty" in _rc[0]["derived_fields"])
ok("G12 fixture_difficulty in Haaland derived_fields",
   "fixture_difficulty" in _rc[1]["derived_fields"])


# ===========================================================================
# Section H — Rankings with blank-GW candidate (partial failure)
# ===========================================================================
_section("H: rankings with blank-GW candidate (no FDR)")

# Glen Johnson (team 11, blank GW) has no FDR in map → error in rankings
_candidates_mixed = [
    {"query": "Salah"},          # FDR=4 from map → ok
    {"query": "7"},              # Glen Johnson, blank GW → error (missing FDR)
    {"query": "Haaland"},        # FDR=4 from map → ok
    {"query": "7", "fixture_difficulty": 3},  # Glen Johnson + explicit FDR → ok
]
_r_mixed = tool_rank_captain_candidates(_candidates_mixed, BOOTSTRAP_2D)
ok("H1 mixed status=ok",       _r_mixed["status"] == "ok")
ok("H2 mixed total=3",         _r_mixed["total"] == 3)    # Salah, Haaland, Glen+explicit
ok("H3 mixed error_count=1",   _r_mixed["error_count"] == 1)

_rc_mixed = _r_mixed["ranked_candidates"]
# ok results first (top 3 by score), then error
ok("H4 first ok result is Salah or Haaland",
   _rc_mixed[0]["web_name"] in ("Salah", "Haaland"))
ok("H5 error candidate at end has status=error",
   _rc_mixed[3]["status"] == "error")
ok("H6 error candidate mentions fixture_difficulty",
   "fixture_difficulty" in _rc_mixed[3]["message"])

# Glen Johnson with explicit FDR in the rankings → ok, not error
_glen_ok = next(
    (c for c in _rc_mixed
     if c.get("status") == "ok" and c.get("web_name") == "Johnson"),
    None,
)
ok("H7 Glen Johnson with explicit FDR scored successfully", _glen_ok is not None)
ok("H8 Glen Johnson FDR=3 in score_inputs",
   _glen_ok is not None and _glen_ok["score_inputs"]["fixture_difficulty"] == 3)


# ===========================================================================
# Section I — derived_fields contract
# ===========================================================================
_section("I: derived_fields contract")

# I1: all four fields derived when map present + full element
ok("I1 all four fields in Haaland derived_fields",
   set(_r_haaland["derived_fields"]) == {"fixture_difficulty", "form", "minutes_risk", "xgi_per_90"})

# I2: derived_fields is sorted alphabetically
ok("I2 derived_fields sorted alphabetically",
   _r_haaland["derived_fields"] == ["fixture_difficulty", "form", "minutes_risk", "xgi_per_90"])

# I3: when fixture_difficulty explicitly provided, it's NOT in derived_fields
ok("I3 explicit FDR not in derived_fields", "fixture_difficulty" not in _r_override["derived_fields"])

# I4: when form explicitly overridden, it's NOT in derived_fields
_r_form_override = tool_get_captain_score("Haaland", BOOTSTRAP_2D, {"form": 5.0})
ok("I4 explicit form not in derived_fields",
   "form" not in _r_form_override["derived_fields"])
ok("I5 fixture_difficulty still in derived_fields (not overridden)",
   "fixture_difficulty" in _r_form_override["derived_fields"])

# I6: per-candidate derived_fields in rankings
ok("I6 Salah ranking entry has derived_fields key", "derived_fields" in _rc[0])


# ===========================================================================
# Section J — fpl_api_client exports (Phase 2d additions)
# ===========================================================================
_section("J: fpl_api_client exports")

import fpl_api_client as _fac
ok("J1 get_fixtures exported",              hasattr(_fac, "get_fixtures"))
ok("J2 get_fixture_difficulty_map exported", hasattr(_fac, "get_fixture_difficulty_map"))
ok("J3 get_bootstrap still exported",        hasattr(_fac, "get_bootstrap"))
ok("J4 get_players still exported",          hasattr(_fac, "get_players"))
ok("J5 get_teams still exported",            hasattr(_fac, "get_teams"))
ok("J6 FIXTURES_URL constant present",       "?event=" in FIXTURES_URL)

# J7: get_fixture_difficulty_map is callable and pure (no network call needed)
_map_from_export = _fac.get_fixture_difficulty_map(_FIXTURES_GW28, teams=_TEAMS)
ok("J7 exported get_fixture_difficulty_map computes same result",
   _map_from_export == _EXPECTED_FDR_MAP)


# ===========================================================================
# Section K — Spec validation: runner accepts query-only
# ===========================================================================
_section("K: spec validation — query-only with map in bootstrap")

# K1: GET_CAPTAIN_SCORE_SPEC required is now just ["query"]
_captain_required = set(GET_CAPTAIN_SCORE_SPEC.parameters.get("required", []))
ok("K1 GET_CAPTAIN_SCORE_SPEC required == {'query'}",
   _captain_required == {"query"})

# K2: fixture_difficulty is still in properties (optional, not removed)
ok("K2 fixture_difficulty still in parameters.properties",
   "fixture_difficulty" in GET_CAPTAIN_SCORE_SPEC.parameters["properties"])

# K3: RANK_CAPTAIN_CANDIDATES_SPEC candidates items required == ["query"]
_item_required = set(
    GET_CAPTAIN_SCORE_SPEC.parameters["properties"].get("fixture_difficulty", {})
    .get("description", "")
    and
    # Just check the _CANDIDATE_ITEM_SCHEMA via the spec
    RANK_CAPTAIN_CANDIDATES_SPEC.parameters["properties"]["candidates"]["items"].get("required", [])
)
ok("K3 candidate item required == {'query'}",
   set(RANK_CAPTAIN_CANDIDATES_SPEC.parameters["properties"]["candidates"]["items"]["required"]) == {"query"})

# K4-K5: runner dispatches successfully with only query + map in bootstrap
_r_runner = run_tool("get_captain_score", {"query": "Haaland"}, BOOTSTRAP_2D)
ok("K4 runner: query-only with map → status=ok", _r_runner["status"] == "ok")
ok("K5 runner: auto-derived FDR=4", _r_runner["score_inputs"]["fixture_difficulty"] == 4)

# K6: runner: missing required arg (query) → error
_r_no_query = run_tool("get_captain_score", {}, BOOTSTRAP_2D)
ok("K6 runner: missing query → error", _r_no_query["status"] == "error")

# K7: runner: no map + no fdr → missing_argument error
_r_no_fdr = run_tool("get_captain_score", {"query": "Haaland"}, BOOTSTRAP_2D_NO_MAP)
ok("K7 runner: no map + no fdr → missing_argument error",
   _r_no_fdr["status"] == "error" and _r_no_fdr.get("code") == "missing_argument")


# ===========================================================================
# Section L — Harness e2e with fully auto-derived path
# ===========================================================================
_section("L: harness e2e with fully auto-derived path")

from fpl_grounded_assistant import ask, route

# L1-L3: captain score via harness (no candidate_inputs)
_h_result = ask("captain_score", {"query": "Haaland"}, BOOTSTRAP_2D)
ok("L1 harness captain_score status=ok", _h_result["status"] == "ok")
ok("L2 harness FDR auto-derived = 4", _h_result["score_inputs"]["fixture_difficulty"] == 4)
ok("L3 harness fixture_difficulty in derived_fields",
   "fixture_difficulty" in _h_result["derived_fields"])

# L4-L6: captain score via harness with explicit override
_h_override = ask("captain_score",
                  {"query": "Haaland", "candidate_inputs": {"fixture_difficulty": 1}},
                  BOOTSTRAP_2D)
ok("L4 harness explicit FDR=1 override → ok", _h_override["status"] == "ok")
ok("L5 harness explicit FDR=1 in score_inputs",
   _h_override["score_inputs"]["fixture_difficulty"] == 1)
ok("L6 harness fixture_difficulty NOT in derived_fields (overridden)",
   "fixture_difficulty" not in _h_override["derived_fields"])

# L7-L10: rankings via harness (no fixture_difficulty in candidates)
_h_rank = ask("rank_captain_candidates",
              {"candidates": [{"query": "Salah"}, {"query": "Haaland"}, {"query": "Saka"}]},
              BOOTSTRAP_2D)
ok("L7 harness rankings status=ok",  _h_rank["status"] == "ok")
ok("L8 harness rankings total=3",    _h_rank["total"] == 3)
ok("L9 harness rank 1 = Salah",      _h_rank["ranked_candidates"][0]["web_name"] == "Salah")
ok("L10 harness all FDR in derived", all(
    "fixture_difficulty" in c["derived_fields"]
    for c in _h_rank["ranked_candidates"]
    if c.get("status") == "ok"
))


# ===========================================================================
# Section M — Safety regression (ambiguous/not_found unchanged)
# ===========================================================================
_section("M: safety regression")

# M1: ambiguous name → ambiguous (unchanged)
_r_amb = tool_get_captain_score("Johnson", BOOTSTRAP_2D)
ok("M1 ambiguous name → status=ambiguous", _r_amb["status"] == "ambiguous")

# M2: not found → not_found (unchanged)
_r_nf = tool_get_captain_score("Cantona", BOOTSTRAP_2D)
ok("M2 not found → status=not_found", _r_nf["status"] == "not_found")

# M3: empty candidates → error (unchanged)
_r_empty = tool_rank_captain_candidates([], BOOTSTRAP_2D)
ok("M3 empty candidates → status=error", _r_empty["status"] == "error")

# M4: ambiguous in rankings → in non_ok at end (unchanged)
_r_amb_rank = tool_rank_captain_candidates(
    [{"query": "Salah"}, {"query": "Johnson"}], BOOTSTRAP_2D
)
ok("M4 rankings with ambiguous → error_count=1", _r_amb_rank["error_count"] == 1)
ok("M5 rankings with ambiguous → total=1",        _r_amb_rank["total"] == 1)

# M6: map present but player not found → not_found, not FDR error
_r_nf2 = tool_get_captain_score("Zidane", BOOTSTRAP_2D)
ok("M6 map present + not_found player → not_found (not missing_arg)",
   _r_nf2["status"] == "not_found")


# ===========================================================================
# Section N — Phase 2c regression (2c tests pass with 2d bootstrap)
# ===========================================================================
_section("N: Phase 2c regression")

# N1-N3: 2c bootstrap path still works (map absent)
_r_2c = tool_get_captain_score("Haaland", BOOTSTRAP_2D_NO_MAP,
                               {"fixture_difficulty": 2})
ok("N1 2c path (map absent + explicit FDR) → ok", _r_2c["status"] == "ok")
ok("N2 2c path: fixture_difficulty NOT in derived_fields",
   "fixture_difficulty" not in _r_2c["derived_fields"])
ok("N3 2c path: form in derived_fields", "form" in _r_2c["derived_fields"])

# N4: _derive_candidate_inputs still derives form, minutes_risk, xgi_per_90
_el = _find_element(1, BOOTSTRAP_2D)  # Haaland
_d = _derive_candidate_inputs(_el)
ok("N4 form derived from element", approx_equal(_d["form"], 8.0))
ok("N5 minutes_risk derived from status=a", approx_equal(_d["minutes_risk"], 0.0))
ok("N6 xgi_per_90 derived (1.70/(1800/90))", approx_equal(_d["xgi_per_90"], 0.085))

# N7-N8: ranking with no map + explicit FDR (2c style)
_r_rank_2c = tool_rank_captain_candidates(
    [{"query": "Haaland", "fixture_difficulty": 2},
     {"query": "Salah",   "fixture_difficulty": 2}],
    BOOTSTRAP_2D_NO_MAP,
)
ok("N7 2c ranking path: status=ok", _r_rank_2c["status"] == "ok")
ok("N8 2c ranking path: total=2",   _r_rank_2c["total"] == 2)

# N9: 2c spec regression — runner still accepts fixture_difficulty as explicit arg
_r_runner_2c = run_tool(
    "get_captain_score",
    {"query": "Haaland", "fixture_difficulty": 3},
    BOOTSTRAP_2D_NO_MAP,
)
ok("N9 runner with explicit fixture_difficulty → ok", _r_runner_2c["status"] == "ok")

# N10: form override still suppresses form from derived_fields
_r_form_ovr = tool_get_captain_score("Haaland", BOOTSTRAP_2D, {"form": 6.0})
ok("N10 form override → form not in derived_fields",
   "form" not in _r_form_ovr["derived_fields"])
ok("N11 form override value used in score", _r_form_ovr["score_inputs"]["form"] == 6.0)


# ===========================================================================
# Section O — Score correctness verification
# ===========================================================================
_section("O: score correctness verification")

# Verify all four main scores to high precision
ok(f"O1 Haaland score = {_SCORE_HAALAND}",
   approx_equal(_r_haaland["captain_score"], _SCORE_HAALAND, tol=0.01))
ok(f"O2 Salah score = {_SCORE_SALAH}",
   approx_equal(_r_salah["captain_score"], _SCORE_SALAH, tol=0.01))
ok(f"O3 Saka score = {_SCORE_SAKA}",
   approx_equal(_r_saka["captain_score"], _SCORE_SAKA, tol=0.01))
ok(f"O4 De Bruyne score = {_SCORE_DEBRUYNE}",
   approx_equal(_r_kdb["captain_score"], _SCORE_DEBRUYNE, tol=0.01))

# O5: rankings order is consistent with individual scores
ok("O5 Salah ranked above Haaland (60.58 > 54.85)",
   _rc[0]["captain_score"] > _rc[1]["captain_score"])
ok("O6 Haaland ranked above Saka (54.85 > 36.35)",
   _rc[1]["captain_score"] > _rc[2]["captain_score"])
ok("O7 Saka ranked above De Bruyne (36.35 > 14.0)",
   _rc[2]["captain_score"] > _rc[3]["captain_score"])

# O8: scores are deterministic — calling again gives same result
_r_haaland_2 = tool_get_captain_score("Haaland", BOOTSTRAP_2D)
ok("O8 deterministic: same score on repeat call",
   _r_haaland_2["captain_score"] == _r_haaland["captain_score"])

# O9: bootstrap dict not mutated by tool call
ok("O9 bootstrap not mutated",
   set(BOOTSTRAP_2D.keys()) == {"elements", "teams", "events", "element_types", "fixture_difficulty_map"})


# ===========================================================================
# Final summary
# ===========================================================================
print(f"\n{'='*60}")
print(f"Phase 2d results: {_passed} PASS, {_failed} FAIL")
if _failed == 0:
    print("ALL PASS ✓")
else:
    print(f"FAILURES: {_failed}")
print(f"{'='*60}\n")

sys.exit(0 if _failed == 0 else 1)


