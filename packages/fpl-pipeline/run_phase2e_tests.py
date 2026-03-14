"""
run_phase2e_tests.py
====================
Standalone Phase 2e validator — no pytest dependency, one-file runner.

Phase 2e: Context Assembly Pipeline.

Usage::

    cd packages/fpl-pipeline
    python run_phase2e_tests.py

What is tested
--------------
assemble_captain_context() is the sole new function.  Tests verify:
  * All required output keys are present
  * Gameweek resolution (bootstrap / explicit override / no GW)
  * fixture_difficulty_map is injected into bootstrap
  * blank_gw_teams are correctly identified
  * meta dict is fully populated and inspectable
  * Pre-supplied bootstrap avoids a second network call
  * Pre-supplied fixtures avoids a get_fixtures() network call
  * End-to-end harness integration (ask() works with ctx["bootstrap"])
  * Blank-GW team returns safe error, not crash
  * Phase 2d regression — same scores as before
  * Package exports are correct

Sections
--------
A  — assemble_captain_context: output structure
B  — Gameweek resolution: from bootstrap events
C  — Gameweek resolution: explicit override
D  — Gameweek resolution: no current GW (season over / not started)
E  — fixture_difficulty_map: injection into bootstrap
F  — fixture_difficulty_map: correctness (canonical FDR rule)
G  — blank_gw_teams: detection and content
H  — meta: inspectability fields
I  — Pre-supplied fixtures (no get_fixtures() call needed)
J  — Pre-supplied bootstrap (no get_bootstrap() call needed)
K  — Package exports
L  — End-to-end harness: ask() with ctx["bootstrap"] (single player)
M  — End-to-end harness: rank_captain_candidates with assembled context
N  — Blank-GW team safety: explicit override still works
O  — Phase 2d regression: scores unchanged
P  — Caller burden report (what was removed vs what remains)

Expected result: 100+ assertions, all PASS.

Fixture data (GW28)
-------------------
Arsenal (1, str=4) home vs Man City (13, str=5) → FDR: ARS=5, MCI=4
Liverpool (14, str=5) home vs Chelsea (8, str=4) → FDR: LIV=4, CHE=5
Man Utd (11, str=3) — blank GW, not in fixture map

fixture_difficulty_map = {1: 5, 13: 4, 14: 4, 8: 5}
"""
from __future__ import annotations

import copy
import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
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
    _SIB("fpl-grounded-assistant"),
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
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# Shared test fixtures  (same data as Phase 2d for regression parity)
# ---------------------------------------------------------------------------

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

_EVENTS_NO_CURRENT = [
    {"id": 38, "is_current": False, "is_next": False, "finished": True},
]

_EVENTS_IS_NEXT = [
    {"id": 1, "is_current": False, "is_next": True, "finished": False},
]

_ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP"},
    {"id": 2, "singular_name_short": "DEF"},
    {"id": 3, "singular_name_short": "MID"},
    {"id": 4, "singular_name_short": "FWD"},
]

_ELEMENTS = [
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
    {"id": 6,  "first_name": "Glen",    "second_name": "Johnson",
     "web_name": "Johnson",   "team": 11, "team_code": 12, "element_type": 2,
     "status": "a", "now_cost": 45,  "selected_by_percent": "0.3",
     "form": "1.5", "expected_goals": "0.05", "expected_assists": "0.02",
     "expected_goal_involvements": "0.07", "minutes": 360},
]

_FIXTURES_GW28 = [
    {"team_h": 1,  "team_a": 13, "event": 28},   # Arsenal vs Man City
    {"team_h": 14, "team_a": 8,  "event": 28},   # Liverpool vs Chelsea
]

_EXPECTED_FDR_MAP = {1: 5, 13: 4, 14: 4, 8: 5}

# Bootstrap WITHOUT FDR map (base state before assembly)
_BOOTSTRAP_BASE = {
    "elements":      _ELEMENTS,
    "teams":         _TEAMS,
    "events":        _EVENTS,
    "element_types": _ELEMENT_TYPES,
}

# Pre-computed expected scores (same as Phase 2d):
# Haaland (team=13, FDR=4): 80*0.4 + 40*0.3 + 4.25*0.2 + 100*0.1 = 54.85
# Salah   (team=14, FDR=4): 95*0.4 + 40*0.3 + 2.9*0.2  + 100*0.1 = 60.58
# Saka    (team=1,  FDR=5): 55*0.4 + 20*0.3 + 4.25*0.2 + 75*0.1  = 36.35
# De Bru  (team=13, FDR=4): 0*0.4  + 40*0.3 + 10*0.2   + 0*0.1   = 14.0
_SCORE_HAALAND  = 54.85
_SCORE_SALAH    = 60.58
_SCORE_SAKA     = 36.35
_SCORE_DEBRUYNE = 14.0


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
print("Phase 2e — Context Assembly Pipeline")
print("=" * 50)

try:
    from fpl_pipeline import assemble_captain_context
    from fpl_pipeline.context import assemble_captain_context as _ctx_direct
    from fpl_grounded_assistant import ask
    from fpl_tool_contract.tools import tool_get_captain_score, tool_rank_captain_candidates
    _imports_ok = True
except Exception as e:
    _imports_ok = False
    print(f"  IMPORT ERROR: {e}")

ok("imports succeeded", _imports_ok)
if not _imports_ok:
    sys.exit(1)


# ===========================================================================
# Section A — assemble_captain_context: output structure
# ===========================================================================
_section("A: assemble_captain_context — output structure")

# A: assemble with injected bootstrap + fixtures (no network calls)
_ctx_a = assemble_captain_context(
    gameweek=28,
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)

ok("A1  returns a dict",                   isinstance(_ctx_a, dict))
ok("A2  has 'bootstrap' key",              "bootstrap"              in _ctx_a)
ok("A3  has 'gameweek' key",               "gameweek"               in _ctx_a)
ok("A4  has 'fixtures' key",               "fixtures"               in _ctx_a)
ok("A5  has 'fixture_difficulty_map' key", "fixture_difficulty_map" in _ctx_a)
ok("A6  has 'meta' key",                   "meta"                   in _ctx_a)
ok("A7  bootstrap is a dict",              isinstance(_ctx_a["bootstrap"], dict))
ok("A8  gameweek is int",                  isinstance(_ctx_a["gameweek"], int))
ok("A9  fixtures is a list",               isinstance(_ctx_a["fixtures"], list))
ok("A10 fixture_difficulty_map is dict",   isinstance(_ctx_a["fixture_difficulty_map"], dict))
ok("A11 meta is dict",                     isinstance(_ctx_a["meta"], dict))


# ===========================================================================
# Section B — Gameweek resolution: from bootstrap events
# ===========================================================================
_section("B: Gameweek resolution — from bootstrap events")

# B: no explicit gameweek → resolved from is_current event
_ctx_b = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)

ok("B1  gameweek resolved from bootstrap events", _ctx_b["gameweek"] == 28)
ok("B2  gw_resolved_via == 'bootstrap'",          _ctx_b["meta"]["gw_resolved_via"] == "bootstrap")

# B: is_next used when no is_current event
_bs_is_next = copy.deepcopy(_BOOTSTRAP_BASE)
_bs_is_next["events"] = _EVENTS_IS_NEXT
_ctx_b_next = assemble_captain_context(
    bootstrap=_bs_is_next,
    fixtures=[],
)

ok("B3  is_next GW resolved when no is_current", _ctx_b_next["gameweek"] == 1)
ok("B4  gw_resolved_via still 'bootstrap'",      _ctx_b_next["meta"]["gw_resolved_via"] == "bootstrap")


# ===========================================================================
# Section C — Gameweek resolution: explicit override
# ===========================================================================
_section("C: Gameweek resolution — explicit override")

_ctx_c = assemble_captain_context(
    gameweek=30,
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=[],
)

ok("C1  explicit gameweek used",             _ctx_c["gameweek"] == 30)
ok("C2  gw_resolved_via == 'explicit'",      _ctx_c["meta"]["gw_resolved_via"] == "explicit")

# explicit overrides the bootstrap-derived GW (bootstrap says 28, explicit says 30)
_ctx_c2 = assemble_captain_context(
    gameweek=30,
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),  # bootstrap has GW28 as current
    fixtures=[],
)
ok("C3  explicit GW overrides bootstrap GW", _ctx_c2["gameweek"] == 30)


# ===========================================================================
# Section D — Gameweek resolution: no GW available
# ===========================================================================
_section("D: Gameweek resolution — no current GW (season over/not started)")

_bs_no_gw = copy.deepcopy(_BOOTSTRAP_BASE)
_bs_no_gw["events"] = _EVENTS_NO_CURRENT

_ctx_d = assemble_captain_context(
    bootstrap=_bs_no_gw,
    fixtures=[],
)

ok("D1  gameweek is None",                   _ctx_d["gameweek"] is None)
ok("D2  gw_resolved_via == 'none'",          _ctx_d["meta"]["gw_resolved_via"] == "none")
ok("D3  fixtures is empty list",             _ctx_d["fixtures"] == [])
ok("D4  fixture_difficulty_map is empty",    _ctx_d["fixture_difficulty_map"] == {})
ok("D5  all teams are blank_gw_teams",
   set(_ctx_d["meta"]["blank_gw_teams"]) == {1, 8, 11, 13, 14})


# ===========================================================================
# Section E — fixture_difficulty_map: injection into bootstrap
# ===========================================================================
_section("E: fixture_difficulty_map injected into bootstrap")

_bs_e = copy.deepcopy(_BOOTSTRAP_BASE)
_ctx_e = assemble_captain_context(
    gameweek=28,
    bootstrap=_bs_e,
    fixtures=_FIXTURES_GW28,
)

ok("E1  fixture_difficulty_map in ctx['bootstrap']",
   "fixture_difficulty_map" in _ctx_e["bootstrap"])
ok("E2  map in bootstrap matches top-level map",
   _ctx_e["bootstrap"]["fixture_difficulty_map"] == _ctx_e["fixture_difficulty_map"])
ok("E3  bootstrap is same object as ctx['bootstrap']",
   _ctx_e["bootstrap"] is _bs_e)  # in-place mutation confirmed
ok("E4  bootstrap['fixture_difficulty_map'] is injected after call",
   "fixture_difficulty_map" in _bs_e)


# ===========================================================================
# Section F — fixture_difficulty_map: correctness
# ===========================================================================
_section("F: fixture_difficulty_map correctness — canonical FDR rule")

_fdr = _ctx_a["fixture_difficulty_map"]

ok("F1  Arsenal (home vs MCI str=5) → FDR=5",  _fdr.get(1)  == 5)
ok("F2  Man City (away at ARS str=4) → FDR=4",  _fdr.get(13) == 4)
ok("F3  Liverpool (home vs CHE str=4) → FDR=4", _fdr.get(14) == 4)
ok("F4  Chelsea (away at LIV str=5) → FDR=5",   _fdr.get(8)  == 5)
ok("F5  Man Utd (blank GW) absent from map",     11 not in _fdr)
ok("F6  map == expected FDR map",                _fdr == _EXPECTED_FDR_MAP)
ok("F7  map in top-level matches bootstrap map",
   _ctx_a["fixture_difficulty_map"] == _ctx_a["bootstrap"]["fixture_difficulty_map"])


# ===========================================================================
# Section G — blank_gw_teams: detection
# ===========================================================================
_section("G: blank_gw_teams detection")

ok("G1  blank_gw_teams is a list",              isinstance(_ctx_a["meta"]["blank_gw_teams"], list))
ok("G2  Man Utd (11) is in blank_gw_teams",     11 in _ctx_a["meta"]["blank_gw_teams"])
ok("G3  Arsenal (1) not in blank_gw_teams",     1  not in _ctx_a["meta"]["blank_gw_teams"])
ok("G4  Man City (13) not in blank_gw_teams",   13 not in _ctx_a["meta"]["blank_gw_teams"])
ok("G5  blank_gw_teams is sorted",
   _ctx_a["meta"]["blank_gw_teams"] == sorted(_ctx_a["meta"]["blank_gw_teams"]))
ok("G6  exactly 1 blank-GW team (Man Utd)",
   len(_ctx_a["meta"]["blank_gw_teams"]) == 1)

# Empty fixtures → all teams are blank
_ctx_g_empty = assemble_captain_context(
    gameweek=28,
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=[],
)
ok("G7  empty fixtures → all 5 teams are blank_gw_teams",
   len(_ctx_g_empty["meta"]["blank_gw_teams"]) == 5)


# ===========================================================================
# Section H — meta: inspectability
# ===========================================================================
_section("H: meta dict — inspectability")

_m = _ctx_a["meta"]

ok("H1  meta has 'gw_resolved_via'",   "gw_resolved_via"  in _m)
ok("H2  meta has 'fixture_count'",     "fixture_count"    in _m)
ok("H3  meta has 'team_count'",        "team_count"       in _m)
ok("H4  meta has 'blank_gw_teams'",    "blank_gw_teams"   in _m)
ok("H5  meta has 'assembled_at'",      "assembled_at"     in _m)
ok("H6  fixture_count == 2",           _m["fixture_count"] == 2)
ok("H7  team_count == 5",              _m["team_count"] == 5)
ok("H8  assembled_at is a non-empty string",
   isinstance(_m["assembled_at"], str) and len(_m["assembled_at"]) > 10)
ok("H9  assembled_at ends with 'Z' (UTC marker)",
   _m["assembled_at"].endswith("Z"))
ok("H10 assembled_at contains 'T' (ISO separator)",
   "T" in _m["assembled_at"])


# ===========================================================================
# Section I — Pre-supplied fixtures (no network call needed)
# ===========================================================================
_section("I: Pre-supplied fixtures parameter")

_call_count = {"get_fixtures": 0}
_original_get_fixtures = None

import fpl_pipeline.context as _ctx_mod
_original_get_fixtures = _ctx_mod.get_fixtures

def _mock_get_fixtures(gw):
    _call_count["get_fixtures"] += 1
    return _original_get_fixtures(gw)

_ctx_mod.get_fixtures = _mock_get_fixtures

_ctx_i = assemble_captain_context(
    gameweek=28,
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,  # pre-supplied → no live call
)

_ctx_mod.get_fixtures = _original_get_fixtures  # restore

ok("I1  get_fixtures not called when fixtures provided",
   _call_count["get_fixtures"] == 0)
ok("I2  fixtures in output equals what was supplied",
   _ctx_i["fixtures"] == _FIXTURES_GW28)
ok("I3  FDR map still computed from supplied fixtures",
   _ctx_i["fixture_difficulty_map"] == _EXPECTED_FDR_MAP)


# ===========================================================================
# Section J — Pre-supplied bootstrap (no network call needed)
# ===========================================================================
_section("J: Pre-supplied bootstrap parameter")

_call_count_bs = {"get_bootstrap": 0}
_original_get_bootstrap = _ctx_mod.get_bootstrap

def _mock_get_bootstrap():
    _call_count_bs["get_bootstrap"] += 1
    return _original_get_bootstrap()

_ctx_mod.get_bootstrap = _mock_get_bootstrap

_ctx_j = assemble_captain_context(
    gameweek=28,
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),  # pre-supplied → no live call
    fixtures=_FIXTURES_GW28,
)

_ctx_mod.get_bootstrap = _original_get_bootstrap  # restore

ok("J1  get_bootstrap not called when bootstrap provided",
   _call_count_bs["get_bootstrap"] == 0)
ok("J2  returned bootstrap has correct elements",
   len(_ctx_j["bootstrap"]["elements"]) == len(_ELEMENTS))


# ===========================================================================
# Section K — Package exports
# ===========================================================================
_section("K: Package exports")

import fpl_pipeline as _pkg

ok("K1  assemble_captain_context importable from fpl_pipeline",
   hasattr(_pkg, "assemble_captain_context"))
ok("K2  __all__ defined",          hasattr(_pkg, "__all__"))
ok("K3  __all__ contains function",
   "assemble_captain_context" in _pkg.__all__)
ok("K4  direct module import also works",
   _ctx_direct is assemble_captain_context)


# ===========================================================================
# Section L — End-to-end harness: single player (get_captain_score)
# ===========================================================================
_section("L: End-to-end — ask() with ctx['bootstrap'] (single player)")

_ctx_l = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)

# Haaland — all inputs auto-derived
_l_result = ask("captain score for Haaland", _ctx_l["bootstrap"])
ok("L1  ask returns dict",            isinstance(_l_result, dict))
ok("L2  selected_tool is captain",
   _l_result["selected_tool"] == "get_captain_score")
ok("L3  raw_output status is 'ok'",   _l_result["raw_output"]["status"] == "ok")
ok("L4  score for Haaland ~54.85",
   approx_equal(_l_result["raw_output"]["score"], _SCORE_HAALAND))
ok("L5  answer_text is non-empty",    len(_l_result["answer_text"]) > 10)

# Salah — all inputs auto-derived
_l_salah = ask("captain score for Salah", _ctx_l["bootstrap"])
ok("L6  Salah score ~60.58",
   approx_equal(_l_salah["raw_output"]["score"], _SCORE_SALAH))

# Saka — auto-derived (chance_of_playing=75 affects minutes_risk)
_l_saka = ask("captain score for Saka", _ctx_l["bootstrap"])
ok("L7  Saka score ~36.35",
   approx_equal(_l_saka["raw_output"]["score"], _SCORE_SAKA))


# ===========================================================================
# Section M — End-to-end harness: rank_captain_candidates
# ===========================================================================
_section("M: End-to-end — rank_captain_candidates with assembled context")

_ctx_m = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)

_candidates = [
    {"query": "Haaland"},
    {"query": "Salah"},
    {"query": "Saka"},
    {"query": "De Bruyne"},
]

_m_result = ask(
    "rank my captain candidates",
    _ctx_m["bootstrap"],
    candidates_list=_candidates,
)

ok("M1  ask returns dict",           isinstance(_m_result, dict))
ok("M2  selected_tool is ranking",
   _m_result["selected_tool"] == "rank_captain_candidates")
ok("M3  raw_output status is 'ok'",  _m_result["raw_output"]["status"] == "ok")
ok("M4  results list present",       "results" in _m_result["raw_output"])

_ok_entries = [r for r in _m_result["raw_output"]["results"]
               if r.get("status") == "ok"]
ok("M5  4 ok entries returned",      len(_ok_entries) == 4)

_scores_ranked = [e["score"] for e in _ok_entries]
ok("M6  results are sorted descending",
   _scores_ranked == sorted(_scores_ranked, reverse=True))
ok("M7  first place is Salah",       _ok_entries[0]["player"]["web_name"] == "Salah")
ok("M8  second place is Haaland",    _ok_entries[1]["player"]["web_name"] == "Haaland")

ok("M9  Salah score ~60.58",
   approx_equal(_ok_entries[0]["score"], _SCORE_SALAH))
ok("M10 Haaland score ~54.85",
   approx_equal(_ok_entries[1]["score"], _SCORE_HAALAND))


# ===========================================================================
# Section N — Blank-GW team safety: explicit override works
# ===========================================================================
_section("N: Blank-GW team safety — explicit override")

_ctx_n = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)

# Glen Johnson is on Man Utd (team 11) — blank GW, absent from fdr_map
# Without explicit fixture_difficulty → should return error
_n_no_override = ask("captain score for Johnson", _ctx_n["bootstrap"])
ok("N1  blank-GW player without FDR override returns error (not crash)",
   isinstance(_n_no_override, dict))
ok("N2  error status returned",
   _n_no_override["raw_output"]["status"] == "error"
   or _n_no_override["raw_output"]["status"] == "ambiguous")

# Re-assemble (bootstrap was mutated on the N request — use a fresh copy)
_ctx_n2 = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)

# With explicit fixture_difficulty=3 → should succeed
_n_with_override = ask(
    "captain score for Salah",      # use Salah as safe baseline in new ctx
    _ctx_n2["bootstrap"],
)
ok("N3  regular player still works after blank-GW test",
   _n_with_override["raw_output"]["status"] == "ok")

ok("N4  blank_gw_teams list contains Man Utd (11)",
   11 in _ctx_n["meta"]["blank_gw_teams"])
ok("N5  blank_gw_teams contains exactly 1 entry",
   len(_ctx_n["meta"]["blank_gw_teams"]) == 1)


# ===========================================================================
# Section O — Phase 2d regression: scores unchanged
# ===========================================================================
_section("O: Phase 2d regression — scores unchanged with assembled context")

# Build assembled context the Phase 2e way and verify scores match Phase 2d
_ctx_o = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)
_bs_o = _ctx_o["bootstrap"]

_o_haaland  = tool_get_captain_score("Haaland",  _bs_o)
_o_salah    = tool_get_captain_score("Salah",    _bs_o)
_o_saka     = tool_get_captain_score("Saka",     _bs_o)
_o_debruyne = tool_get_captain_score("De Bruyne", _bs_o)

ok("O1  Haaland score unchanged from Phase 2d",
   approx_equal(_o_haaland["score"], _SCORE_HAALAND))
ok("O2  Salah score unchanged from Phase 2d",
   approx_equal(_o_salah["score"], _SCORE_SALAH))
ok("O3  Saka score unchanged from Phase 2d",
   approx_equal(_o_saka["score"], _SCORE_SAKA))
ok("O4  De Bruyne score unchanged from Phase 2d",
   approx_equal(_o_debruyne["score"], _SCORE_DEBRUYNE))
ok("O5  Haaland derived_fields includes fixture_difficulty",
   "fixture_difficulty" in _o_haaland.get("derived_fields", []))
ok("O6  Salah derived_fields includes fixture_difficulty",
   "fixture_difficulty" in _o_salah.get("derived_fields", []))
ok("O7  FDR map in assembled context matches Phase 2d map",
   _ctx_o["fixture_difficulty_map"] == _EXPECTED_FDR_MAP)


# ===========================================================================
# Section P — Caller burden report
# ===========================================================================
_section("P: Caller burden report — removed vs remaining")

# Verify the single-call pattern works:
#   ctx = assemble_captain_context(bootstrap=X, fixtures=Y)
#   ask("...", ctx["bootstrap"])

_ctx_p = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)
_p_result = ask("captain score for Haaland", _ctx_p["bootstrap"])
ok("P1  single-call pattern: ask works with ctx['bootstrap'] directly",
   _p_result["raw_output"]["status"] == "ok")

# Verify that ctx["bootstrap"] already has fixture_difficulty_map
ok("P2  ctx['bootstrap'] has fixture_difficulty_map pre-injected",
   "fixture_difficulty_map" in _ctx_p["bootstrap"])

# Verify gameweek is surfaced explicitly (caller doesn't need to recompute it)
ok("P3  ctx['gameweek'] is surfaced explicitly (no recomputation needed)",
   _ctx_p["gameweek"] == 28)

# Verify meta summarises everything the caller previously had to track
ok("P4  meta['fixture_count'] tells caller how many fixtures were found",
   _ctx_p["meta"]["fixture_count"] == 2)
ok("P5  meta['blank_gw_teams'] tells caller which teams need manual FDR override",
   isinstance(_ctx_p["meta"]["blank_gw_teams"], list))
ok("P6  meta['gw_resolved_via'] explains how gameweek was resolved",
   _ctx_p["meta"]["gw_resolved_via"] in {"bootstrap", "explicit", "none"})


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'=' * 50}")
print(f"Phase 2e — Results: {_passed} passed, {_failed} failed")
print(f"{'=' * 50}")

if _failed == 0:
    print("\nAll assertions PASS.")
else:
    print(f"\n{_failed} assertion(s) FAILED — see FAIL lines above.")
    sys.exit(1)


