"""
run_phase2c_tests.py
====================
Standalone Phase 2c validator — no pytest dependency, one-file runner.

Phase 2c: Auto-derivation of captain scoring inputs from bootstrap elements.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2c_tests.py

Sections
--------
A  — _derive_candidate_inputs unit tests (helpers)
B  — _find_element unit tests
C  — tool_get_captain_score: fully auto-derived path (BOOTSTRAP_2C with minutes)
D  — tool_get_captain_score: partial auto-derivation (existing bootstrap, no minutes)
E  — tool_get_captain_score: manual override path (regression)
F  — tool_get_captain_score: fixture_difficulty still required (error path)
G  — tool_rank_captain_candidates: auto-derived path
H  — tool_rank_captain_candidates: partial auto + explicit overrides
I  — derived_fields contract
J  — Spec validation: runner accepts query+fixture_difficulty without form/xgi/risk
K  — Harness e2e with auto-derived path
L  — Safety regression (ambiguous/not_found unchanged)
M  — Phase 2b regression (all 5 tools, ranking, partial failures)

Expected result: 100+ assertions, all PASS.
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


def approx_equal(a: float, b: float, tol: float = 1e-4) -> bool:
    """Return True if |a - b| <= tol."""
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Base elements (same as conftest.py — no 'minutes' field)
_BASE_ELEMENTS = [
    {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",   "team": 13, "team_code": 43, "element_type": 4,
     "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
     "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
     "expected_goal_involvements": "1.70"},
    {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",     "team": 14, "team_code": 1,  "element_type": 3,
     "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
     "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
     "expected_goal_involvements": "1.45"},
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",      "team": 1,  "team_code": 3,  "element_type": 3,
     "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
     "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
     "expected_goal_involvements": "0.85"},
    {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne", "team": 13, "team_code": 43, "element_type": 3,
     "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
     "form": "0.0", "expected_goals": "0.20", "expected_assists": "0.40",
     "expected_goal_involvements": "0.60"},
    {"id": 6,  "first_name": "Adam",    "second_name": "Johnson",
     "web_name": "Johnson",   "team": 8,  "team_code": 8,  "element_type": 3,
     "status": "a", "now_cost": 50,  "selected_by_percent": "0.5",
     "form": "2.0", "expected_goals": "0.10", "expected_assists": "0.05",
     "expected_goal_involvements": "0.15"},
    {"id": 7,  "first_name": "Glen",    "second_name": "Johnson",
     "web_name": "Johnson",   "team": 11, "team_code": 12, "element_type": 2,
     "status": "a", "now_cost": 45,  "selected_by_percent": "0.3",
     "form": "1.5", "expected_goals": "0.05", "expected_assists": "0.02",
     "expected_goal_involvements": "0.07"},
    {"id": 8,  "first_name": "Test",    "second_name": "Player",
     "web_name": "TPlayer",   "team": 1,  "element_type": 1,
     "status": "u"},
]

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

# Base bootstrap — NO 'minutes' field (same as conftest.py)
BOOTSTRAP = {
    "elements":      _BASE_ELEMENTS,
    "teams":         _TEAMS,
    "events":        _EVENTS,
    "element_types": _ELEMENT_TYPES,
}

# Phase 2c bootstrap — adds 'minutes' field to each element, enabling xgi_per_90
# derivation.  Also adds one element with chance_of_playing_this_round for that test.
# Derived xgi_per_90 values:
#   Haaland:   1.70 / (1800/90) = 1.70 / 20  = 0.085
#   Salah:     1.45 / (2250/90) = 1.45 / 25  = 0.058
#   Saka:      0.85 / (900/90)  = 0.85 / 10  = 0.085
#   De Bruyne: 0.60 / (270/90)  = 0.60 / 3   = 0.20
_ELEMENTS_2C = [
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
     "chance_of_playing_this_round": 75},     # <-- chance overrides status-based risk
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

BOOTSTRAP_2C = {
    "elements":      _ELEMENTS_2C,
    "teams":         _TEAMS,
    "events":        _EVENTS,
    "element_types": _ELEMENT_TYPES,
}


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
try:
    from fpl_tool_contract.tools import (
        _STATUS_TO_MINUTES_RISK,
        _derive_candidate_inputs,
        _find_element,
        tool_get_captain_score,
        tool_rank_captain_candidates,
    )
    from fpl_tool_runner import run_tool, TOOL_REGISTRY
    from fpl_tool_runner.specs import TOOL_SPECS, GET_CAPTAIN_SCORE_SPEC, RANK_CAPTAIN_CANDIDATES_SPEC
    from fpl_grounded_assistant import ask, route, RouteResult
    _imports_ok = True
except Exception as e:
    _imports_ok = False
    print(f"  IMPORT ERROR: {e}")

ok("imports succeeded", _imports_ok)
if not _imports_ok:
    sys.exit(1)


# ===========================================================================
# Section A — _derive_candidate_inputs unit tests
# ===========================================================================
_section("A: _derive_candidate_inputs")

# A1: full element (with minutes) — all three derivable
_el_full = {
    "form": "8.0",
    "status": "a",
    "expected_goal_involvements": "1.70",
    "minutes": 1800,
}
_d = _derive_candidate_inputs(_el_full)
ok("A1 form derived", "form" in _d and approx_equal(_d["form"], 8.0))
ok("A2 minutes_risk derived for status=a", "minutes_risk" in _d and approx_equal(_d["minutes_risk"], 0.0))
ok("A3 xgi_per_90 derived (1.70/(1800/90))", "xgi_per_90" in _d and approx_equal(_d["xgi_per_90"], 0.085, tol=1e-3))

# A4: element without minutes field — form + minutes_risk but NOT xgi_per_90
_el_no_mins = {"form": "9.5", "status": "a", "expected_goal_involvements": "1.45"}
_d2 = _derive_candidate_inputs(_el_no_mins)
ok("A4 form derived (no minutes element)", "form" in _d2)
ok("A5 minutes_risk derived (no minutes element)", "minutes_risk" in _d2)
ok("A6 xgi_per_90 NOT derived when minutes absent", "xgi_per_90" not in _d2)

# A7: status codes → minutes_risk
ok("A7 status=a → risk 0.0",   approx_equal(_derive_candidate_inputs({"status": "a"}).get("minutes_risk", -1), 0.0))
ok("A8 status=d → risk 30.0",  approx_equal(_derive_candidate_inputs({"status": "d"}).get("minutes_risk", -1), 30.0))
ok("A9 status=i → risk 100.0", approx_equal(_derive_candidate_inputs({"status": "i"}).get("minutes_risk", -1), 100.0))
ok("A10 status=s → risk 100.0", approx_equal(_derive_candidate_inputs({"status": "s"}).get("minutes_risk", -1), 100.0))
ok("A11 status=u → risk 100.0", approx_equal(_derive_candidate_inputs({"status": "u"}).get("minutes_risk", -1), 100.0))
ok("A12 unknown status → risk 50.0 (conservative)", approx_equal(_derive_candidate_inputs({"status": "x"}).get("minutes_risk", -1), 50.0))

# A13: chance_of_playing_this_round overrides status-based risk
_el_chance = {"status": "d", "chance_of_playing_this_round": 75}
_d3 = _derive_candidate_inputs(_el_chance)
ok("A13 chance_of_playing=75 → risk=25.0 (overrides d→30)", approx_equal(_d3["minutes_risk"], 25.0))

# A14: element with no 'form' field → form not in derived
_el_no_form = {"status": "a"}
ok("A14 form not derived when element has no 'form' key", "form" not in _derive_candidate_inputs(_el_no_form))

# A15: form as string "8.0" → float 8.0
ok("A15 form string → float", approx_equal(_derive_candidate_inputs({"form": "8.0"}).get("form", -1), 8.0))

# A16: minutes=0 → xgi_per_90 NOT derived (division by zero protection)
_el_zero_mins = {"expected_goal_involvements": "1.0", "minutes": 0}
ok("A16 minutes=0 → xgi_per_90 not derived", "xgi_per_90" not in _derive_candidate_inputs(_el_zero_mins))

# A17: empty element → only minutes_risk from unknown status (50)
_d_empty = _derive_candidate_inputs({})
ok("A17 empty element → only minutes_risk key derived", list(_d_empty.keys()) == ["minutes_risk"])
ok("A18 empty element → minutes_risk=50.0 (unknown status)", approx_equal(_d_empty["minutes_risk"], 50.0))


# ===========================================================================
# Section B — _find_element unit tests
# ===========================================================================
_section("B: _find_element")

_bs = copy.deepcopy(BOOTSTRAP)
ok("B1 find Haaland (id=1)", _find_element(1, _bs) is not None and _find_element(1, _bs)["web_name"] == "Haaland")
ok("B2 find Salah (id=2)", _find_element(2, _bs) is not None and _find_element(2, _bs)["web_name"] == "Salah")
ok("B3 not found → None", _find_element(999, _bs) is None)
ok("B4 empty bootstrap → None", _find_element(1, {"elements": []}) is None)
ok("B5 missing elements key → None", _find_element(1, {}) is None)


# ===========================================================================
# Section C — tool_get_captain_score: fully auto-derived path (BOOTSTRAP_2C)
# ===========================================================================
_section("C: tool_get_captain_score fully auto-derived (BOOTSTRAP_2C)")

_bs2c = copy.deepcopy(BOOTSTRAP_2C)

# C1: Haaland — provide only fixture_difficulty; form, minutes_risk, xgi_per_90 all auto-derived
_r = tool_get_captain_score("Haaland", _bs2c, {"fixture_difficulty": 2})
ok("C1 status ok",            _r["status"] == "ok")
ok("C2 player_id correct",    _r["player_id"] == 1)
ok("C3 captain_score correct (66.85)", approx_equal(_r["captain_score"], 66.85, tol=0.01))
ok("C4 derived_fields contains form",          "form" in _r["derived_fields"])
ok("C5 derived_fields contains minutes_risk",  "minutes_risk" in _r["derived_fields"])
ok("C6 derived_fields contains xgi_per_90",    "xgi_per_90" in _r["derived_fields"])
ok("C7 derived_fields does NOT contain fixture_difficulty", "fixture_difficulty" not in _r["derived_fields"])
ok("C8 score_inputs form = 8.0",   approx_equal(_r["score_inputs"]["form"], 8.0))
ok("C9 score_inputs fixture_difficulty = 2", _r["score_inputs"]["fixture_difficulty"] == 2)
ok("C10 score_inputs minutes_risk = 0.0",    approx_equal(_r["score_inputs"]["minutes_risk"], 0.0))
ok("C11 score_inputs xgi_per_90 ≈ 0.085",   approx_equal(_r["score_inputs"]["xgi_per_90"], 0.085, tol=1e-3))

# C12: Salah — same pattern
_r2 = tool_get_captain_score("Salah", _bs2c, {"fixture_difficulty": 2})
ok("C12 Salah captain_score correct (72.58)", approx_equal(_r2["captain_score"], 72.58, tol=0.01))

# C13: Saka — status=d (risk=30), but has chance_of_playing=75 → risk=25
# form=5.5, fdr=2, xgi=0.085, risk=25
# score = 55*0.4 + 80*0.3 + 4.25*0.2 + 75*0.1 = 22 + 24 + 0.85 + 7.5 = 54.35
import math
_expected_saka = round(55*0.4 + 80*0.3 + (0.085*50)*0.2 + (100-25)*0.1, 2)
_r3 = tool_get_captain_score("Saka", _bs2c, {"fixture_difficulty": 2})
ok("C13 Saka risk uses chance_of_playing (25 not 30)", approx_equal(_r3["score_inputs"]["minutes_risk"], 25.0))
ok("C14 Saka captain_score matches chance-adjusted risk", approx_equal(_r3["captain_score"], _expected_saka, tol=0.01))

# C15: De Bruyne — status=i → risk=100
_r4 = tool_get_captain_score("De Bruyne", _bs2c, {"fixture_difficulty": 2})
ok("C15 De Bruyne status=i → minutes_risk=100.0", approx_equal(_r4["score_inputs"]["minutes_risk"], 100.0))
ok("C16 De Bruyne captain_score correct (26.0)", approx_equal(_r4["captain_score"], 26.0, tol=0.01))

# C17: fixture_difficulty NOT in derived_fields
ok("C17 fixture_difficulty never in derived_fields", "fixture_difficulty" not in _r4["derived_fields"])


# ===========================================================================
# Section D — tool_get_captain_score: partial auto-derivation (BOOTSTRAP, no minutes)
# ===========================================================================
_section("D: tool_get_captain_score partial auto (base BOOTSTRAP, no minutes)")

_bsb = copy.deepcopy(BOOTSTRAP)

# D1: provide fixture_difficulty + xgi_per_90; form and minutes_risk auto-derived
_r5 = tool_get_captain_score("Haaland", _bsb, {"fixture_difficulty": 2, "xgi_per_90": 0.5})
ok("D1 status ok",            _r5["status"] == "ok")
ok("D2 captain_score correct (71.0)", approx_equal(_r5["captain_score"], 71.0, tol=0.01))
ok("D3 form auto-derived in derived_fields",         "form" in _r5["derived_fields"])
ok("D4 minutes_risk auto-derived in derived_fields", "minutes_risk" in _r5["derived_fields"])
ok("D5 xgi_per_90 NOT in derived_fields (was explicit)", "xgi_per_90" not in _r5["derived_fields"])
ok("D6 fixture_difficulty NOT in derived_fields",        "fixture_difficulty" not in _r5["derived_fields"])

# D7: provide only fixture_difficulty (no xgi_per_90 and no minutes in bootstrap)
_r6 = tool_get_captain_score("Haaland", _bsb, {"fixture_difficulty": 2})
ok("D7 status error when xgi_per_90 missing and not derivable", _r6["status"] == "error")
ok("D8 error code missing_argument", _r6["code"] == "missing_argument")
ok("D9 error message mentions xgi_per_90",  "'xgi_per_90'" in _r6["message"])

# D10: Saka — form=5.5 auto, risk=30 auto (status=d, no chance field), fdr+xgi explicit
_r7 = tool_get_captain_score("Saka", _bsb, {"fixture_difficulty": 2, "xgi_per_90": 0.2})
ok("D10 Saka form auto-derived = 5.5",    approx_equal(_r7["score_inputs"]["form"], 5.5))
ok("D11 Saka risk auto-derived = 30 (no chance field in base bootstrap)",
   approx_equal(_r7["score_inputs"]["minutes_risk"], 30.0))


# ===========================================================================
# Section E — tool_get_captain_score: fully explicit override (regression)
# ===========================================================================
_section("E: tool_get_captain_score fully explicit override (regression)")

# E1: provide all 4 explicitly → none auto-derived, derived_fields empty
_explicit_ci = {"form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 0.5, "minutes_risk": 10.0}
_r8 = tool_get_captain_score("Haaland", _bsb, _explicit_ci)
ok("E1 status ok",                _r8["status"] == "ok")
ok("E2 captain_score = 70.0",     approx_equal(_r8["captain_score"], 70.0, tol=0.01))
ok("E3 derived_fields is empty",  _r8["derived_fields"] == [])

# E2: explicit form override takes precedence over auto-derived form
_r9 = tool_get_captain_score("Haaland", _bs2c, {"form": 5.0, "fixture_difficulty": 2})
ok("E4 form override=5.0 used (not auto-derived 8.0)", approx_equal(_r9["score_inputs"]["form"], 5.0))
ok("E5 captain_score with form=5.0 correct (54.85)", approx_equal(_r9["captain_score"], 54.85, tol=0.01))
ok("E6 form NOT in derived_fields when explicitly supplied", "form" not in _r9["derived_fields"])

# E3: explicit minutes_risk override takes precedence over auto-derived
_r10 = tool_get_captain_score("Haaland", _bs2c, {"fixture_difficulty": 2, "minutes_risk": 50.0})
ok("E7 minutes_risk override=50 used", approx_equal(_r10["score_inputs"]["minutes_risk"], 50.0))
ok("E8 minutes_risk NOT in derived_fields when explicitly supplied", "minutes_risk" not in _r10["derived_fields"])


# ===========================================================================
# Section F — tool_get_captain_score: fixture_difficulty always required
# ===========================================================================
_section("F: fixture_difficulty always required")

# F1: no candidate_inputs at all (BOOTSTRAP_2C) → error on fixture_difficulty
_rf1 = tool_get_captain_score("Haaland", _bs2c, None)
ok("F1 None candidate_inputs → error",  _rf1["status"] == "error")
ok("F2 error code missing_argument",    _rf1["code"] == "missing_argument")
ok("F3 message mentions fixture_difficulty", "fixture_difficulty" in _rf1["message"])

# F2: empty candidate_inputs dict → error
_rf2 = tool_get_captain_score("Haaland", _bs2c, {})
ok("F4 empty candidate_inputs → error",    _rf2["status"] == "error")
ok("F5 error mentions fixture_difficulty", "fixture_difficulty" in _rf2["message"])

# F3: provide form+xgi+risk but NOT fixture_difficulty → still error
_rf3 = tool_get_captain_score("Haaland", _bs2c, {"form": 8.0, "xgi_per_90": 0.5, "minutes_risk": 0.0})
ok("F6 missing fixture_difficulty → error",     _rf3["status"] == "error")
ok("F7 fixture_difficulty named in error message", "'fixture_difficulty'" in _rf3["message"])


# ===========================================================================
# Section G — tool_rank_captain_candidates: auto-derived path (BOOTSTRAP_2C)
# ===========================================================================
_section("G: tool_rank_captain_candidates auto-derived path")

# G1: candidates with only query + fixture_difficulty
_candidates_minimal = [
    {"query": "Haaland",   "fixture_difficulty": 2},
    {"query": "Salah",     "fixture_difficulty": 2},
    {"query": "De Bruyne", "fixture_difficulty": 2},
]
_rg1 = tool_rank_captain_candidates(_candidates_minimal, copy.deepcopy(BOOTSTRAP_2C))
ok("G1 status ok",                     _rg1["status"] == "ok")
ok("G2 total = 3",                     _rg1["total"] == 3)
ok("G3 error_count = 0",               _rg1["error_count"] == 0)
ok("G4 ranked_candidates has 3 items", len(_rg1["ranked_candidates"]) == 3)

# G5-G8: ranking order (Salah 72.58 > Haaland 66.85 > De Bruyne 26.0)
_rc = _rg1["ranked_candidates"]
ok("G5 rank 1 = Salah (highest score)",     _rc[0]["web_name"] == "Salah")
ok("G6 rank 2 = Haaland",                   _rc[1]["web_name"] == "Haaland")
ok("G7 rank 3 = De Bruyne (lowest score)",  _rc[2]["web_name"] == "De Bruyne")
ok("G8 Salah score ≈ 72.58",                approx_equal(_rc[0]["captain_score"], 72.58, tol=0.01))
ok("G9 Haaland score ≈ 66.85",              approx_equal(_rc[1]["captain_score"], 66.85, tol=0.01))
ok("G10 De Bruyne score ≈ 26.0",            approx_equal(_rc[2]["captain_score"], 26.0, tol=0.01))

# G11: derived_fields in each ok result
ok("G11 Haaland has form in derived_fields",      "form" in _rc[1]["derived_fields"])
ok("G12 Salah has xgi_per_90 in derived_fields",  "xgi_per_90" in _rc[0]["derived_fields"])


# ===========================================================================
# Section H — tool_rank_captain_candidates: partial auto + explicit overrides
# ===========================================================================
_section("H: tool_rank_captain_candidates partial + override")

# H1: mixed candidates — some with explicit overrides, some fully auto-derived
_candidates_mixed = [
    {"query": "Haaland",   "fixture_difficulty": 2, "form": 5.0},   # form override
    {"query": "Salah",     "fixture_difficulty": 2},                 # all 3 auto
    {"query": "Saka",      "fixture_difficulty": 2, "minutes_risk": 0.0},  # risk override
]
_rh1 = tool_rank_captain_candidates(_candidates_mixed, copy.deepcopy(BOOTSTRAP_2C))
ok("H1 status ok",   _rh1["status"] == "ok")
ok("H2 total = 3",   _rh1["total"] == 3)

_hc = _rh1["ranked_candidates"]
# Find each player in results
_h_haaland   = next(c for c in _hc if c["web_name"] == "Haaland")
_h_salah     = next(c for c in _hc if c["web_name"] == "Salah")
_h_saka      = next(c for c in _hc if c["web_name"] == "Saka")

ok("H3 Haaland form override=5.0 used",      approx_equal(_h_haaland["score_inputs"]["form"], 5.0))
ok("H4 Haaland form NOT in derived_fields",  "form" not in _h_haaland["derived_fields"])
ok("H5 Salah form auto-derived",             "form" in _h_salah["derived_fields"])
ok("H6 Saka minutes_risk override=0 used",   approx_equal(_h_saka["score_inputs"]["minutes_risk"], 0.0))
ok("H7 Saka minutes_risk NOT in derived",    "minutes_risk" not in _h_saka["derived_fields"])

# H8: candidate with all 4 explicit → derived_fields empty
_candidates_all_explicit = [
    {"query": "Haaland", "fixture_difficulty": 2, "form": 8.0, "xgi_per_90": 0.5, "minutes_risk": 10.0},
]
_rh2 = tool_rank_captain_candidates(_candidates_all_explicit, copy.deepcopy(BOOTSTRAP_2C))
ok("H8 all explicit → derived_fields empty",
   _rh2["ranked_candidates"][0]["derived_fields"] == [])


# ===========================================================================
# Section I — derived_fields contract
# ===========================================================================
_section("I: derived_fields contract")

_ri1 = tool_get_captain_score("Salah", copy.deepcopy(BOOTSTRAP_2C), {"fixture_difficulty": 3})
ok("I1 derived_fields is a list",          isinstance(_ri1["derived_fields"], list))
ok("I2 derived_fields sorted alphabetically",
   _ri1["derived_fields"] == sorted(_ri1["derived_fields"]))
ok("I3 all 3 auto-derivable fields in derived_fields",
   set(_ri1["derived_fields"]) >= {"form", "minutes_risk", "xgi_per_90"})
ok("I4 fixture_difficulty absent from derived_fields",
   "fixture_difficulty" not in _ri1["derived_fields"])

# I5: when form explicitly provided → NOT in derived_fields
_ri2 = tool_get_captain_score("Salah", copy.deepcopy(BOOTSTRAP_2C), {"fixture_difficulty": 3, "form": 7.0})
ok("I5 explicit form → not in derived_fields", "form" not in _ri2["derived_fields"])
ok("I6 minutes_risk still in derived_fields (not supplied)", "minutes_risk" in _ri2["derived_fields"])


# ===========================================================================
# Section J — Spec validation: runner accepts query+fixture_difficulty only
# ===========================================================================
_section("J: runner spec validation")

# J1: required fields for get_captain_score are now only ["query", "fixture_difficulty"]
_cs_spec = GET_CAPTAIN_SCORE_SPEC
ok("J1 GET_CAPTAIN_SCORE_SPEC required = ['query', 'fixture_difficulty']",
   set(_cs_spec.parameters["required"]) == {"query", "fixture_difficulty"})

# J2: required fields for each candidate item are ["query", "fixture_difficulty"]
_rank_spec = RANK_CAPTAIN_CANDIDATES_SPEC
_item_schema = _rank_spec.parameters["properties"]["candidates"]["items"]
ok("J2 candidate item required = ['query', 'fixture_difficulty']",
   set(_item_schema["required"]) == {"query", "fixture_difficulty"})

# J3: runner dispatches get_captain_score with only query+fixture_difficulty
_bs2c_copy = copy.deepcopy(BOOTSTRAP_2C)
_rj3 = run_tool("get_captain_score", {"query": "Haaland", "fixture_difficulty": 2}, _bs2c_copy)
ok("J3 runner dispatches with query+fixture_difficulty only → ok", _rj3["status"] == "ok")

# J4: runner still rejects missing query
_rj4 = run_tool("get_captain_score", {"fixture_difficulty": 2}, copy.deepcopy(BOOTSTRAP_2C))
ok("J4 runner rejects missing query", _rj4["status"] == "error" and _rj4["code"] == "missing_argument")

# J5: runner still rejects missing fixture_difficulty
_rj5 = run_tool("get_captain_score", {"query": "Haaland"}, copy.deepcopy(BOOTSTRAP_2C))
ok("J5 runner rejects missing fixture_difficulty", _rj5["status"] == "error")

# J6: runner passes explicit form override through correctly
_rj6 = run_tool("get_captain_score",
                {"query": "Haaland", "fixture_difficulty": 2, "form": 5.0},
                copy.deepcopy(BOOTSTRAP_2C))
ok("J6 explicit form override passes through runner", approx_equal(_rj6["score_inputs"]["form"], 5.0))

# J7: 5 tools still registered
ok("J7 5 tools registered", len(TOOL_REGISTRY.list_tools()) >= 5)


# ===========================================================================
# Section K — Harness e2e with auto-derived path
# ===========================================================================
_section("K: harness e2e auto-derived path")

_bs2c_k = copy.deepcopy(BOOTSTRAP_2C)

# K1: captain score question with only fixture_difficulty in candidate_inputs
_rk1 = ask("captain score for Salah", _bs2c_k, candidate_inputs={"fixture_difficulty": 2})
ok("K1 selected_tool = get_captain_score",       _rk1["selected_tool"] == "get_captain_score")
ok("K2 raw_output status = ok",                  _rk1["raw_output"]["status"] == "ok")
ok("K3 answer_text contains Salah",              "Salah" in _rk1["answer_text"])
ok("K4 answer_text contains score",              any(c.isdigit() for c in _rk1["answer_text"]))
ok("K5 derived_fields in raw_output",            "derived_fields" in _rk1["raw_output"])
ok("K6 form auto-derived",                       "form" in _rk1["raw_output"]["derived_fields"])

# K7: ranking question with minimal candidates list
_bs2c_k2 = copy.deepcopy(BOOTSTRAP_2C)
_minimal_cands = [
    {"query": "Haaland",   "fixture_difficulty": 2},
    {"query": "Salah",     "fixture_difficulty": 2},
]
_rk7 = ask("who should i captain", _bs2c_k2, candidates_list=_minimal_cands)
ok("K7 selected_tool = rank_captain_candidates", _rk7["selected_tool"] == "rank_captain_candidates")
ok("K8 raw_output status = ok",                  _rk7["raw_output"]["status"] == "ok")
ok("K9 total = 2",                               _rk7["raw_output"]["total"] == 2)
ok("K10 answer_text mentions at least one player name",
   "Haaland" in _rk7["answer_text"] or "Salah" in _rk7["answer_text"])


# ===========================================================================
# Section L — Safety regression (ambiguous/not_found)
# ===========================================================================
_section("L: safety regression")

_bsl = copy.deepcopy(BOOTSTRAP)

# L1: ambiguous query → ambiguous status (not scored)
_rl1 = tool_get_captain_score("Johnson", _bsl, {"fixture_difficulty": 2})
ok("L1 ambiguous query → ambiguous status", _rl1["status"] == "ambiguous")
ok("L2 ambiguous response has message",     "message" in _rl1)

# L3: not_found query
_rl3 = tool_get_captain_score(999, _bsl, {"fixture_difficulty": 2})
ok("L3 not_found query → not_found status", _rl3["status"] == "not_found")

# L4: ambiguous candidate in ranking → appended at end as error
_rrank = tool_rank_captain_candidates(
    [
        {"query": "Haaland", "fixture_difficulty": 2, "form": 8.0, "xgi_per_90": 0.5, "minutes_risk": 0.0},
        {"query": "Johnson", "fixture_difficulty": 2},  # ambiguous — both Johnsons
    ],
    _bsl,
)
ok("L4 ambiguous in ranking → error_count=1", _rrank["error_count"] == 1)
ok("L5 total=1 (only Haaland scored)",         _rrank["total"] == 1)
ok("L6 ranked list has 2 entries total",       len(_rrank["ranked_candidates"]) == 2)
ok("L7 second entry is ambiguous",             _rrank["ranked_candidates"][1]["status"] == "ambiguous")

# L8: not_found candidate
_rnf = tool_rank_captain_candidates(
    [{"query": "Haaland", "fixture_difficulty": 2, "form": 8.0, "xgi_per_90": 0.5, "minutes_risk": 0.0},
     {"query": "nobody",  "fixture_difficulty": 2}],
    _bsl,
)
ok("L8 not_found in ranking → error_count=1", _rnf["error_count"] == 1)
ok("L9 not_found entry status=not_found",      _rnf["ranked_candidates"][1]["status"] == "not_found")


# ===========================================================================
# Section M — Phase 2b regression (all prior functionality unchanged)
# ===========================================================================
_section("M: Phase 2b regression")

_bsm = copy.deepcopy(BOOTSTRAP)

# M1: explicit full candidate_inputs still works (Phase 2a-style call)
_rm1 = tool_get_captain_score(
    "Haaland", _bsm,
    {"form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 0.5, "minutes_risk": 0.0},
)
ok("M1 explicit all 4 inputs → ok",    _rm1["status"] == "ok")
ok("M2 captain_score = 74.0",          approx_equal(_rm1["captain_score"], 74.0, tol=0.01))
ok("M3 derived_fields = [] (all explicit)", _rm1["derived_fields"] == [])

# M4: Phase 2b rank tool with explicit inputs still works
_rm4 = tool_rank_captain_candidates(
    [
        {"query": "Haaland",   "form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 0.5, "minutes_risk": 0.0},
        {"query": "Salah",     "form": 9.5, "fixture_difficulty": 2, "xgi_per_90": 0.8, "minutes_risk": 0.0},
    ],
    _bsm,
)
ok("M4 ranking with all explicit → ok",  _rm4["status"] == "ok")
ok("M5 total = 2",                       _rm4["total"] == 2)
ok("M6 Salah ranked above Haaland",      _rm4["ranked_candidates"][0]["web_name"] == "Salah")

# M7: empty candidates → error still works
_rm7 = tool_rank_captain_candidates([], _bsm)
ok("M7 empty candidates → error",  _rm7["status"] == "error")
ok("M8 error code = missing_argument", _rm7["code"] == "missing_argument")

# M9: runner dispatch for resolve_player still works
_rm9 = run_tool("resolve_player", {"query": "Salah"}, _bsm)
ok("M9 resolve_player still works",   _rm9["status"] == "ok")
ok("M10 player_id = 2",               _rm9["player_id"] == 2)

# M11: all 5 tool specs still present
ok("M11 5 tool specs in TOOL_SPECS",  len(TOOL_SPECS) >= 5)

# M12: get_captain_score spec has fixture_difficulty as required
ok("M12 fixture_difficulty in required", "fixture_difficulty" in GET_CAPTAIN_SCORE_SPEC.parameters["required"])

# M13: tool_runner canonical formula parity (Phase 2b)
# form=10, fdr=1, xgi=2, risk=0 → all maxed: 40+30+20+10 = 100
_rm13 = run_tool("get_captain_score",
    {"query": "Haaland", "form": 10.0, "fixture_difficulty": 1, "xgi_per_90": 2.0, "minutes_risk": 0.0},
    _bsm)
ok("M13 max-score parity: 100.0",  approx_equal(_rm13["captain_score"], 100.0, tol=0.01))

# M14: route() still returns None for unrecognised queries
_rm14 = route("this is an unrecognised query xyz")
ok("M14 unrecognised query → route=None", _rm14 is None)


# ===========================================================================
# Final summary
# ===========================================================================
_total = _passed + _failed
print(f"\n{'='*60}")
print(f"  Phase 2c results: {_passed}/{_total} PASS")
if _failed:
    print(f"  FAILURES: {_failed}")
print(f"{'='*60}\n")

sys.exit(0 if _failed == 0 else 1)


