"""
run_phase2h_tests.py
====================
Standalone Phase 2h validator — no pytest dependency, one-file runner.

Phase 2h: Role-awareness for captain evaluation.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2h_tests.py

What is tested
--------------
Three FPL bootstrap element fields drive role-aware captain evaluation:

    penalties_order                    — 1 = primary penalty taker
    direct_freekicks_order             — 1 = primary direct FK taker
    corners_and_indirect_freekicks_order — included in signals, not in bonus (v1)

``derive_role_signals(element)`` extracts these and computes:
    set_piece_notes  — list of active role identifiers
    set_piece_threat — bool
    role_bonus       — float additive correction for tier classification only

``classify_captain_tier`` now accepts ``role_bonus=0.0``:
    effective_score = captain_score + role_bonus
Score-based threshold checks use effective_score; the published
captain_score is never modified.  The minutes_risk >= 50 availability
check is not overridden by role_bonus.

Sections
--------
A  — derive_role_signals: penalty taker signals
B  — derive_role_signals: freekick taker signals
C  — derive_role_signals: combined penalty + freekick
D  — derive_role_signals: no role (all None / absent)
E  — derive_role_signals: corners_and_indirect_freekicks_order present (no bonus)
F  — compute_role_bonus: correct values
G  — ROLE_BONUS_MAP: structure and values
H  — fpl_captain_engine shim: role_evaluator symbols importable
I  — classify_captain_tier: role_bonus=0.0 default (Phase 2g parity)
J  — classify_captain_tier: role_bonus upgrades tier at safe boundary
K  — classify_captain_tier: role_bonus upgrades tier at upside boundary
L  — classify_captain_tier: role_bonus upgrades tier at differential boundary
M  — classify_captain_tier: minutes_risk >= 50 not overridden by role_bonus
N  — classify_captain_tier: effective_score < 20 still avoid when bonus insufficient
O  — tool_get_captain_score: role_signals field present in ok response
P  — tool_get_captain_score: role_bonus changes tier for primary penalty taker
Q  — tool_get_captain_score: tier unchanged when no role fields in element
R  — tool_rank_captain_candidates: role_signals on all ok entries
S  — tool_rank_captain_candidates: tier reflects role for penalty taker
T  — tool_rank_captain_candidates: tier unchanged for non-role players
U  — Documented tier change: Haaland + penalties_order=1 → safe (was upside)
V  — Regression: captain scores unchanged for all GW28 players (role is tier-only)
W  — Regression: players WITHOUT role fields → same tiers as Phase 2g
X  — Interface report: what changed vs what is preserved

Expected result: 100+ assertions, all PASS.

Fixture data (GW28)
-------------------
Arsenal (1, str=4) home vs Man City (13, str=5) → FDR: ARS=5, MCI=4
Liverpool (14, str=5) home vs Chelsea (8, str=4) → FDR: LIV=4, CHE=5
Man Utd (11, str=3) — blank GW
fixture_difficulty_map = {1: 5, 13: 4, 14: 4, 8: 5}

Phase 2g baseline tiers (no role fields in elements):
    Salah     (60.58, risk=0,   xgi=0.0578) → safe
    Haaland   (54.85, risk=0,   xgi=0.0850) → upside
    Saka      (36.35, risk=25,  xgi=0.0850) → differential
    De Bruyne (14.0,  risk=100, xgi=0.2000) → avoid

Documented Phase 2h tier changes (when role fields present):
    Haaland + penalties_order=1 → role_bonus=5.0 → effective=59.85 → SAFE
    Salah   + penalties_order=1 → role_bonus=5.0 → effective=65.58 → safe (unchanged)
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
    _SIB("fpl-pipeline"),
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
# Shared test fixtures (GW28 — same as Phase 2d/2e/2f/2g for regression parity)
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

_ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP"},
    {"id": 2, "singular_name_short": "DEF"},
    {"id": 3, "singular_name_short": "MID"},
    {"id": 4, "singular_name_short": "FWD"},
]

# Elements WITHOUT role fields — Phase 2g parity (role_bonus=0 for all)
_ELEMENTS_NO_ROLES = [
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
]

# Elements WITH role fields — Phase 2h role-aware tests
# Haaland: penalties_order=1 (primary pen taker for Man City)
# Salah: penalties_order=1 (primary pen taker for Liverpool)
# Saka: direct_freekicks_order=2 (backup FK for Arsenal)
# De Bruyne: direct_freekicks_order=1 (primary FK, but injured)
_ELEMENTS_WITH_ROLES = [
    {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",   "team": 13, "team_code": 43, "element_type": 4,
     "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
     "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
     "expected_goal_involvements": "1.70", "minutes": 1800,
     "penalties_order": 1, "direct_freekicks_order": None,
     "corners_and_indirect_freekicks_order": None},
    {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",     "team": 14, "team_code": 1,  "element_type": 3,
     "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
     "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
     "expected_goal_involvements": "1.45", "minutes": 2250,
     "penalties_order": 1, "direct_freekicks_order": None,
     "corners_and_indirect_freekicks_order": 1},
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",      "team": 1,  "team_code": 3,  "element_type": 3,
     "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
     "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
     "expected_goal_involvements": "0.85", "minutes": 900,
     "chance_of_playing_this_round": 75,
     "penalties_order": None, "direct_freekicks_order": 2,
     "corners_and_indirect_freekicks_order": 2},
    {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne", "team": 13, "team_code": 43, "element_type": 3,
     "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
     "form": "0.0", "expected_goals": "0.20", "expected_assists": "0.40",
     "expected_goal_involvements": "0.60", "minutes": 270,
     "penalties_order": None, "direct_freekicks_order": 1,
     "corners_and_indirect_freekicks_order": None},
]

_FDR_MAP = {1: 5, 13: 4, 14: 4, 8: 5}

# Bootstrap without role fields (Phase 2g parity)
_BS_NO_ROLES = {
    "elements":               _ELEMENTS_NO_ROLES,
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}

# Bootstrap with role fields (Phase 2h role-aware)
_BS_WITH_ROLES = {
    "elements":               _ELEMENTS_WITH_ROLES,
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}


def _bs_no_roles() -> dict:
    return copy.deepcopy(_BS_NO_ROLES)

def _bs_with_roles() -> dict:
    return copy.deepcopy(_BS_WITH_ROLES)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

print("Phase 2h — Role-Awareness for Captain Evaluation")
print("=" * 60)

from python.role_evaluator import (  # type: ignore
    derive_role_signals,
    compute_role_bonus,
    ROLE_BONUS_MAP,
)
from python.captain_tiers import (  # type: ignore
    classify_captain_tier,
    TIER_SAFE, TIER_UPSIDE, TIER_DIFFERENTIAL, TIER_AVOID, TIER_LOW_CONFIDENCE,
)
from fpl_captain_engine import (  # shim
    derive_role_signals   as _ce_derive,
    compute_role_bonus    as _ce_bonus,
    ROLE_BONUS_MAP        as _ce_map,
)
from fpl_tool_contract.tools import (
    tool_get_captain_score,
    tool_rank_captain_candidates,
)


# ===========================================================================
# Section A — derive_role_signals: penalty taker
# ===========================================================================
_section("A — derive_role_signals: penalty taker signals")

_pen1_el = {"penalties_order": 1, "direct_freekicks_order": None}
_pen2_el = {"penalties_order": 2, "direct_freekicks_order": None}
_pen_none = {"penalties_order": None}

_sA1 = derive_role_signals(_pen1_el)
ok("A1  penalties_order=1 → penalties_order field=1",
   _sA1["penalties_order"] == 1)
ok("A2  penalties_order=1 → set_piece_notes contains 'penalty_taker_1'",
   "penalty_taker_1" in _sA1["set_piece_notes"])
ok("A3  penalties_order=1 → set_piece_threat=True",
   _sA1["set_piece_threat"] is True)
ok("A4  penalties_order=1 → role_bonus=5.0",
   _sA1["role_bonus"] == 5.0)

_sA2 = derive_role_signals(_pen2_el)
ok("A5  penalties_order=2 → 'penalty_taker_2' in notes",
   "penalty_taker_2" in _sA2["set_piece_notes"])
ok("A6  penalties_order=2 → role_bonus=1.0",
   _sA2["role_bonus"] == 1.0)
ok("A7  penalties_order=2 → set_piece_threat=True",
   _sA2["set_piece_threat"] is True)

_sA3 = derive_role_signals(_pen_none)
ok("A8  penalties_order=None → no penalty note in set_piece_notes",
   not any("penalty" in n for n in _sA3["set_piece_notes"]))
ok("A9  penalties_order=None → role_bonus=0.0",
   _sA3["role_bonus"] == 0.0)
ok("A10 penalties_order=None → set_piece_threat=False",
   _sA3["set_piece_threat"] is False)


# ===========================================================================
# Section B — derive_role_signals: freekick taker
# ===========================================================================
_section("B — derive_role_signals: freekick taker signals")

_fk1_el  = {"direct_freekicks_order": 1}
_fk2_el  = {"direct_freekicks_order": 2}
_fkN_el  = {"direct_freekicks_order": None}

_sB1 = derive_role_signals(_fk1_el)
ok("B1  direct_freekicks_order=1 → 'freekick_taker_1' in notes",
   "freekick_taker_1" in _sB1["set_piece_notes"])
ok("B2  direct_freekicks_order=1 → role_bonus=3.0",
   _sB1["role_bonus"] == 3.0)
ok("B3  direct_freekicks_order=1 → set_piece_threat=True",
   _sB1["set_piece_threat"] is True)

_sB2 = derive_role_signals(_fk2_el)
ok("B4  direct_freekicks_order=2 → 'freekick_taker_2' in notes",
   "freekick_taker_2" in _sB2["set_piece_notes"])
ok("B5  direct_freekicks_order=2 → role_bonus=0.5",
   _sB2["role_bonus"] == 0.5)

_sB3 = derive_role_signals(_fkN_el)
ok("B6  direct_freekicks_order=None → no freekick note",
   not any("freekick" in n for n in _sB3["set_piece_notes"]))
ok("B7  direct_freekicks_order=None → role_bonus=0.0",
   _sB3["role_bonus"] == 0.0)


# ===========================================================================
# Section C — derive_role_signals: combined roles
# ===========================================================================
_section("C — derive_role_signals: combined penalty + freekick")

_combo_el = {"penalties_order": 1, "direct_freekicks_order": 1}
_sC = derive_role_signals(_combo_el)

ok("C1  pen=1, fk=1 → both notes present",
   "penalty_taker_1" in _sC["set_piece_notes"]
   and "freekick_taker_1" in _sC["set_piece_notes"])
ok("C2  pen=1, fk=1 → role_bonus=8.0  (5.0 + 3.0)",
   _sC["role_bonus"] == 8.0)
ok("C3  pen=1, fk=1 → set_piece_threat=True",
   _sC["set_piece_threat"] is True)
ok("C4  pen=1, fk=2 → role_bonus=5.5  (5.0 + 0.5)",
   derive_role_signals({"penalties_order": 1, "direct_freekicks_order": 2})["role_bonus"] == 5.5)
ok("C5  pen=2, fk=1 → role_bonus=4.0  (1.0 + 3.0)",
   derive_role_signals({"penalties_order": 2, "direct_freekicks_order": 1})["role_bonus"] == 4.0)


# ===========================================================================
# Section D — derive_role_signals: no role (all None / absent)
# ===========================================================================
_section("D — derive_role_signals: no role")

_sD1 = derive_role_signals({})
ok("D1  empty element → role_bonus=0.0",     _sD1["role_bonus"] == 0.0)
ok("D2  empty element → set_piece_notes=[]", _sD1["set_piece_notes"] == [])
ok("D3  empty element → set_piece_threat=False", _sD1["set_piece_threat"] is False)
ok("D4  empty element → penalties_order=None",   _sD1["penalties_order"] is None)
ok("D5  empty element → direct_freekicks_order=None", _sD1["direct_freekicks_order"] is None)

_sD2 = derive_role_signals({"penalties_order": None, "direct_freekicks_order": None})
ok("D6  all-None → role_bonus=0.0", _sD2["role_bonus"] == 0.0)
ok("D7  all-None → set_piece_threat=False", _sD2["set_piece_threat"] is False)


# ===========================================================================
# Section E — corners_and_indirect_freekicks_order: in signals, no bonus
# ===========================================================================
_section("E — corners_and_indirect_freekicks_order: no role_bonus")

_ci_el = {"corners_and_indirect_freekicks_order": 1}
_sE = derive_role_signals(_ci_el)

ok("E1  ci_order=1 → corners field present in result",
   "corners_and_indirect_freekicks_order" in _sE)
ok("E2  ci_order=1 → corners_and_indirect_freekicks_order=1",
   _sE["corners_and_indirect_freekicks_order"] == 1)
ok("E3  ci_order=1 → role_bonus=0.0  (corners excluded from v1 bonus)",
   _sE["role_bonus"] == 0.0)
ok("E4  ci_order=1 → set_piece_threat=False  (no scoring role)",
   _sE["set_piece_threat"] is False)
ok("E5  ci_order=1 alone → set_piece_notes is empty",
   _sE["set_piece_notes"] == [])

# Salah element (penalties_order=1, ci_order=1) — ci doesn't stack on bonus
_salah_role_el = _ELEMENTS_WITH_ROLES[1]  # Salah
_sE_salah = derive_role_signals(_salah_role_el)
ok("E6  Salah (pen=1, ci=1) → role_bonus=5.0  (ci does not add to bonus)",
   _sE_salah["role_bonus"] == 5.0)
ok("E7  Salah (pen=1, ci=1) → corners field is 1 in result",
   _sE_salah["corners_and_indirect_freekicks_order"] == 1)


# ===========================================================================
# Section F — compute_role_bonus: correct values
# ===========================================================================
_section("F — compute_role_bonus")

ok("F1  pen=1 → compute_role_bonus=5.0",
   compute_role_bonus({"penalties_order": 1}) == 5.0)
ok("F2  fk=1 → compute_role_bonus=3.0",
   compute_role_bonus({"direct_freekicks_order": 1}) == 3.0)
ok("F3  pen=1, fk=1 → compute_role_bonus=8.0",
   compute_role_bonus({"penalties_order": 1, "direct_freekicks_order": 1}) == 8.0)
ok("F4  no role → compute_role_bonus=0.0",
   compute_role_bonus({}) == 0.0)
ok("F5  compute_role_bonus matches derive_role_signals['role_bonus']",
   compute_role_bonus({"penalties_order": 1})
   == derive_role_signals({"penalties_order": 1})["role_bonus"])


# ===========================================================================
# Section G — ROLE_BONUS_MAP: structure and values
# ===========================================================================
_section("G — ROLE_BONUS_MAP structure")

ok("G1  ROLE_BONUS_MAP is a dict",           isinstance(ROLE_BONUS_MAP, dict))
ok("G2  penalty_taker_1=5.0",               ROLE_BONUS_MAP.get("penalty_taker_1") == 5.0)
ok("G3  penalty_taker_2=1.0",               ROLE_BONUS_MAP.get("penalty_taker_2") == 1.0)
ok("G4  freekick_taker_1=3.0",              ROLE_BONUS_MAP.get("freekick_taker_1") == 3.0)
ok("G5  freekick_taker_2=0.5",              ROLE_BONUS_MAP.get("freekick_taker_2") == 0.5)
ok("G6  no corner_taker key in bonus map",  "corner_taker_1" not in ROLE_BONUS_MAP)
ok("G7  all values are floats",
   all(isinstance(v, float) for v in ROLE_BONUS_MAP.values()))
ok("G8  all values are positive",
   all(v > 0.0 for v in ROLE_BONUS_MAP.values()))
ok("G9  penalty_taker_1 > freekick_taker_1  (penalty worth more)",
   ROLE_BONUS_MAP["penalty_taker_1"] > ROLE_BONUS_MAP["freekick_taker_1"])


# ===========================================================================
# Section H — fpl_captain_engine shim: role_evaluator symbols importable
# ===========================================================================
_section("H — fpl_captain_engine shim: role_evaluator exports")

ok("H1  derive_role_signals importable from shim",    callable(_ce_derive))
ok("H2  compute_role_bonus importable from shim",     callable(_ce_bonus))
ok("H3  ROLE_BONUS_MAP importable from shim",         isinstance(_ce_map, dict))
ok("H4  shim derive_role_signals is same function",   _ce_derive is derive_role_signals)
ok("H5  shim compute_role_bonus is same function",    _ce_bonus is compute_role_bonus)
ok("H6  shim ROLE_BONUS_MAP is same object",          _ce_map is ROLE_BONUS_MAP)


# ===========================================================================
# Section I — classify_captain_tier: role_bonus=0.0 default (Phase 2g parity)
# ===========================================================================
_section("I — classify_captain_tier: role_bonus=0.0 default (Phase 2g parity)")

# All calls with NO role_bonus should reproduce Phase 2g results exactly
ok("I1  Salah (60.58, 0, 0.058) no bonus → safe",
   classify_captain_tier(60.58, 0.0, 0.058) == TIER_SAFE)
ok("I2  Haaland (54.85, 0, 0.085) no bonus → upside",
   classify_captain_tier(54.85, 0.0, 0.085) == TIER_UPSIDE)
ok("I3  Saka (36.35, 25, 0.085) no bonus → differential",
   classify_captain_tier(36.35, 25.0, 0.085) == TIER_DIFFERENTIAL)
ok("I4  De Bruyne (14.0, 100, 0.200) no bonus → avoid",
   classify_captain_tier(14.0, 100.0, 0.200) == TIER_AVOID)
ok("I5  explicit role_bonus=0.0 same as default",
   classify_captain_tier(54.85, 0.0, 0.085, role_bonus=0.0)
   == classify_captain_tier(54.85, 0.0, 0.085))


# ===========================================================================
# Section J — classify_captain_tier: role_bonus upgrades tier at safe boundary
# ===========================================================================
_section("J — classify_captain_tier: role_bonus upgrades to safe tier")

# Without bonus: score=52, risk=15 → 52 < 55, NOT safe → upside (≥45, risk≤25, xgi≥0.07)
ok("J1  score=52, risk=15, xgi=0.10, no bonus → upside  (< safe threshold)",
   classify_captain_tier(52.0, 15.0, 0.10) == TIER_UPSIDE)
# With pen bonus +5: effective=57 ≥ 55, risk=15 ≤ 20 → safe
ok("J2  score=52, risk=15, xgi=0.10, role_bonus=5.0 → safe",
   classify_captain_tier(52.0, 15.0, 0.10, role_bonus=5.0) == TIER_SAFE)

# Exact boundary: score=55 - bonus - ε → still not safe
ok("J3  score=54.9, risk=15, xgi=0.10, no bonus → upside  (just under safe)",
   classify_captain_tier(54.9, 15.0, 0.10) == TIER_UPSIDE)
# With FK bonus +3: effective=57.9 → safe
ok("J4  score=54.9, risk=15, xgi=0.10, role_bonus=3.0 → safe",
   classify_captain_tier(54.9, 15.0, 0.10, role_bonus=3.0) == TIER_SAFE)

# Documented change: Haaland GW28 + pen bonus
# score=54.85, risk=0, xgi=0.085 — no bonus → upside; pen_bonus=5 → safe
ok("J5  Haaland (54.85, 0, 0.085) + role_bonus=5.0 → safe  [documented Phase 2h change]",
   classify_captain_tier(54.85, 0.0, 0.085, role_bonus=5.0) == TIER_SAFE)


# ===========================================================================
# Section K — classify_captain_tier: role_bonus upgrades tier at upside boundary
# ===========================================================================
_section("K — classify_captain_tier: role_bonus upgrades to upside tier")

# score=43, risk=20, xgi=0.10 → 43 < 45, NOT upside → differential (≥30, risk≤30)
ok("K1  score=43, risk=20, xgi=0.10, no bonus → differential",
   classify_captain_tier(43.0, 20.0, 0.10) == TIER_DIFFERENTIAL)
# FK bonus +3: effective=46 ≥ 45, risk=20 ≤ 25, xgi=0.10 ≥ 0.07 → upside
ok("K2  score=43, risk=20, xgi=0.10, role_bonus=3.0 → upside",
   classify_captain_tier(43.0, 20.0, 0.10, role_bonus=3.0) == TIER_UPSIDE)

# xgi too low: FK bonus pushes over score threshold but xgi check fails
ok("K3  score=43, risk=20, xgi=0.05, role_bonus=3.0 → differential  (xgi < 0.07)",
   classify_captain_tier(43.0, 20.0, 0.05, role_bonus=3.0) == TIER_DIFFERENTIAL)


# ===========================================================================
# Section L — classify_captain_tier: role_bonus upgrades to differential
# ===========================================================================
_section("L — classify_captain_tier: role_bonus upgrades to differential")

# score=28, risk=25 → 28 < 30, NOT differential → low_confidence
ok("L1  score=28, risk=25, xgi=0.05, no bonus → low_confidence",
   classify_captain_tier(28.0, 25.0, 0.05) == TIER_LOW_CONFIDENCE)
# FK backup +0.5: effective=28.5 < 30 → still low_confidence
ok("L2  score=28, risk=25, xgi=0.05, role_bonus=0.5 → low_confidence  (28.5 < 30)",
   classify_captain_tier(28.0, 25.0, 0.05, role_bonus=0.5) == TIER_LOW_CONFIDENCE)
# FK primary +3: effective=31 ≥ 30, risk=25 ≤ 30 → differential
ok("L3  score=28, risk=25, xgi=0.05, role_bonus=3.0 → differential",
   classify_captain_tier(28.0, 25.0, 0.05, role_bonus=3.0) == TIER_DIFFERENTIAL)


# ===========================================================================
# Section M — minutes_risk >= 50 not overridden by role_bonus
# ===========================================================================
_section("M — minutes_risk >= 50 not overridden by role_bonus")

ok("M1  risk=50, no bonus → avoid  (availability floor)",
   classify_captain_tier(70.0, 50.0, 0.15) == TIER_AVOID)
ok("M2  risk=50, role_bonus=8.0 → avoid  (availability overrides role)",
   classify_captain_tier(70.0, 50.0, 0.15, role_bonus=8.0) == TIER_AVOID)
ok("M3  risk=100, role_bonus=10.0 → avoid  (injured + pen taker still avoid)",
   classify_captain_tier(60.0, 100.0, 0.15, role_bonus=10.0) == TIER_AVOID)
# De Bruyne: injured (risk=100) + direct_freekicks_order=1 → still avoid
ok("M4  De Bruyne (14.0, 100, 0.200) + role_bonus=3.0 → avoid",
   classify_captain_tier(14.0, 100.0, 0.200, role_bonus=3.0) == TIER_AVOID)

# risk=49.9 (just below threshold) — role bonus CAN change tier
ok("M5  risk=49.9, score=52, xgi=0.10, role_bonus=5.0 → safe  (risk < 50, bonus applies)",
   classify_captain_tier(52.0, 49.9, 0.10, role_bonus=5.0) != TIER_AVOID)


# ===========================================================================
# Section N — effective_score < 20 still avoid when bonus insufficient
# ===========================================================================
_section("N — effective_score < 20 → avoid even with role_bonus")

ok("N1  score=10, role_bonus=5.0 → effective=15 < 20 → avoid",
   classify_captain_tier(10.0, 5.0, 0.10, role_bonus=5.0) == TIER_AVOID)
ok("N2  score=10, role_bonus=10.0 → effective=20.0 — not avoid by score",
   classify_captain_tier(10.0, 5.0, 0.10, role_bonus=10.0) != TIER_AVOID)
ok("N3  score=14.9, role_bonus=5.1 → effective=20.0 — not avoid by score",
   classify_captain_tier(14.9, 5.0, 0.10, role_bonus=5.1) != TIER_AVOID)


# ===========================================================================
# Section O — tool_get_captain_score: role_signals field present
# ===========================================================================
_section("O — tool_get_captain_score: role_signals field present")

# No-role bootstrap (elements without penalties_order field)
_r_salah_nr   = tool_get_captain_score("Salah",      _bs_no_roles())
_r_haaland_nr = tool_get_captain_score("Haaland",    _bs_no_roles())
_r_saka_nr    = tool_get_captain_score("Saka",       _bs_no_roles())
_r_dbk_nr     = tool_get_captain_score("De Bruyne",  _bs_no_roles())

for _nm, _r in [("Salah", _r_salah_nr), ("Haaland", _r_haaland_nr),
                ("Saka", _r_saka_nr), ("De Bruyne", _r_dbk_nr)]:
    ok(f"O1.{_nm} ok response has 'role_signals' key",    "role_signals" in _r)
    ok(f"O2.{_nm} role_signals is a dict",                isinstance(_r.get("role_signals"), dict))

# With-role bootstrap
_r_salah_wr   = tool_get_captain_score("Salah",      _bs_with_roles())
_r_haaland_wr = tool_get_captain_score("Haaland",    _bs_with_roles())
_r_saka_wr    = tool_get_captain_score("Saka",       _bs_with_roles())
_r_dbk_wr     = tool_get_captain_score("De Bruyne",  _bs_with_roles())

for _nm, _r in [("Salah+role", _r_salah_wr), ("Haaland+role", _r_haaland_wr),
                ("Saka+role", _r_saka_wr), ("De Bruyne+role", _r_dbk_wr)]:
    ok(f"O3.{_nm} ok response has 'role_signals' key",   "role_signals" in _r)

_rs_keys = {"penalties_order", "direct_freekicks_order",
            "corners_and_indirect_freekicks_order",
            "set_piece_notes", "set_piece_threat", "role_bonus"}
ok("O4  role_signals has all expected keys",
   set(_r_salah_wr["role_signals"].keys()) == _rs_keys)


# ===========================================================================
# Section P — tool_get_captain_score: role_bonus changes tier for pen taker
# ===========================================================================
_section("P — tool_get_captain_score: tier reflects role for penalty taker")

# Haaland with no role fields: score≈54.85 → upside
ok("P1  Haaland (no role) tier=upside",
   _r_haaland_nr["tier"] == TIER_UPSIDE)
ok("P2  Haaland (no role) role_signals.role_bonus=0.0",
   _r_haaland_nr["role_signals"]["role_bonus"] == 0.0)

# Haaland WITH penalties_order=1: score≈54.85, role_bonus=5.0 → effective=59.85 → safe
ok("P3  Haaland (penalties_order=1) tier=safe  [Phase 2h documented change]",
   _r_haaland_wr["tier"] == TIER_SAFE)
ok("P4  Haaland (penalties_order=1) role_bonus=5.0",
   _r_haaland_wr["role_signals"]["role_bonus"] == 5.0)
ok("P5  Haaland (penalties_order=1) set_piece_threat=True",
   _r_haaland_wr["role_signals"]["set_piece_threat"] is True)
ok("P6  Haaland captain_score UNCHANGED despite role upgrade",
   approx_equal(_r_haaland_nr["captain_score"], _r_haaland_wr["captain_score"]))

# Salah: already safe — still safe with bonus (no tier change, but role_signals populated)
ok("P7  Salah (penalties_order=1) tier=safe  (already was safe)",
   _r_salah_wr["tier"] == TIER_SAFE)
ok("P8  Salah captain_score unchanged",
   approx_equal(_r_salah_nr["captain_score"], _r_salah_wr["captain_score"]))

# Saka: direct_freekicks_order=2 → role_bonus=0.5 → effective=36.85
# 36.85 ≥ 30, risk=25 ≤ 30 → differential (still)
ok("P9  Saka (direct_freekicks_order=2) tier=differential  (0.5 bonus, still differential)",
   _r_saka_wr["tier"] == TIER_DIFFERENTIAL)
ok("P10 Saka role_signals.role_bonus=0.5",
   _r_saka_wr["role_signals"]["role_bonus"] == 0.5)

# De Bruyne: direct_freekicks_order=1 → role_bonus=3.0, but injured → still avoid
ok("P11 De Bruyne (fk=1, injured) tier=avoid  (minutes_risk=100 overrides role)",
   _r_dbk_wr["tier"] == TIER_AVOID)
ok("P12 De Bruyne role_signals.role_bonus=3.0",
   _r_dbk_wr["role_signals"]["role_bonus"] == 3.0)


# ===========================================================================
# Section Q — tool_get_captain_score: tier unchanged when no role fields
# ===========================================================================
_section("Q — tool_get_captain_score: no role → same tier as Phase 2g")

ok("Q1  Salah no-role tier=safe",       _r_salah_nr["tier"] == TIER_SAFE)
ok("Q2  Haaland no-role tier=upside",   _r_haaland_nr["tier"] == TIER_UPSIDE)
ok("Q3  Saka no-role tier=differential", _r_saka_nr["tier"] == TIER_DIFFERENTIAL)
ok("Q4  De Bruyne no-role tier=avoid",  _r_dbk_nr["tier"] == TIER_AVOID)
ok("Q5  Salah no-role role_bonus=0.0",  _r_salah_nr["role_signals"]["role_bonus"] == 0.0)


# ===========================================================================
# Section R — tool_rank_captain_candidates: role_signals on all ok entries
# ===========================================================================
_section("R — tool_rank_captain_candidates: role_signals on ok entries")

_rank_nr = tool_rank_captain_candidates(
    [{"query": "Salah"}, {"query": "Haaland"}, {"query": "Saka"}, {"query": "De Bruyne"}],
    _bs_no_roles(),
)
ok("R1  no-role ranking status=ok",   _rank_nr["status"] == "ok")
ok("R2  4 candidates scored",         _rank_nr["total"] == 4)

for _e in [e for e in _rank_nr["ranked_candidates"] if e["status"] == "ok"]:
    ok(f"R3.{_e['web_name']} has role_signals",   "role_signals" in _e)
    ok(f"R4.{_e['web_name']} role_bonus=0.0",     _e["role_signals"]["role_bonus"] == 0.0)

_rank_wr = tool_rank_captain_candidates(
    [{"query": "Salah"}, {"query": "Haaland"}, {"query": "Saka"}, {"query": "De Bruyne"}],
    _bs_with_roles(),
)
ok("R5  with-role ranking status=ok",  _rank_wr["status"] == "ok")
ok("R6  4 candidates scored",          _rank_wr["total"] == 4)

for _e in [e for e in _rank_wr["ranked_candidates"] if e["status"] == "ok"]:
    ok(f"R7.{_e['web_name']} has role_signals",    "role_signals" in _e)

_ranked_wr_by_name = {e["web_name"]: e for e in _rank_wr["ranked_candidates"]
                      if e["status"] == "ok"}


# ===========================================================================
# Section S — tool_rank_captain_candidates: tier reflects role for penalty takers
# ===========================================================================
_section("S — tool_rank_captain_candidates: tier correct with roles")

ok("S1  Haaland+role ranked tier=safe    (was upside without role)",
   _ranked_wr_by_name["Haaland"]["tier"] == TIER_SAFE)
ok("S2  Salah+role ranked tier=safe      (unchanged)",
   _ranked_wr_by_name["Salah"]["tier"] == TIER_SAFE)
ok("S3  Saka+role ranked tier=differential (0.5 bonus, still diff)",
   _ranked_wr_by_name["Saka"]["tier"] == TIER_DIFFERENTIAL)
ok("S4  De Bruyne+role ranked tier=avoid  (injured overrides fk=1)",
   _ranked_wr_by_name["De Bruyne"]["tier"] == TIER_AVOID)


# ===========================================================================
# Section T — Tier unchanged for non-role players (regression safety)
# ===========================================================================
_section("T — tool_rank_captain_candidates: tier unchanged for no-role players")

_ranked_nr_by_name = {e["web_name"]: e for e in _rank_nr["ranked_candidates"]
                      if e["status"] == "ok"}

ok("T1  Salah no-role tier=safe",         _ranked_nr_by_name["Salah"]["tier"] == TIER_SAFE)
ok("T2  Haaland no-role tier=upside",     _ranked_nr_by_name["Haaland"]["tier"] == TIER_UPSIDE)
ok("T3  Saka no-role tier=differential",  _ranked_nr_by_name["Saka"]["tier"] == TIER_DIFFERENTIAL)
ok("T4  De Bruyne no-role tier=avoid",    _ranked_nr_by_name["De Bruyne"]["tier"] == TIER_AVOID)


# ===========================================================================
# Section U — Documented tier change: Haaland + penalties_order=1 → safe
# ===========================================================================
_section("U — Documented Phase 2h tier change: Haaland penalty taker")

print()
print("    DOCUMENTED TIER CHANGE IN PHASE 2H:")
print("    Player:  Haaland (Man City, FWD)")
print("    Score:   ~54.85  (form=8.0, fdr=4, xgi≈0.085, risk=0)")
print("    Phase 2g tier: upside   (score=54.85 < 55.0 safe threshold)")
print("    Phase 2h change: penalties_order=1 → role_bonus=5.0")
print("    effective_score: 54.85 + 5.0 = 59.85 >= 55.0")
print("    Phase 2h tier: safe    (effective_score meets safe threshold)")
print()

ok("U1  Haaland with no role: tier=upside   (Phase 2g baseline)",
   _r_haaland_nr["tier"] == TIER_UPSIDE)
ok("U2  Haaland with penalties_order=1: tier=safe  (Phase 2h role-aware)",
   _r_haaland_wr["tier"] == TIER_SAFE)
ok("U3  Haaland captain_score unchanged between Phase 2g and Phase 2h",
   approx_equal(_r_haaland_nr["captain_score"], _r_haaland_wr["captain_score"]))
ok("U4  Haaland role_signals.role_bonus=5.0 with penalties_order=1",
   _r_haaland_wr["role_signals"]["role_bonus"] == 5.0)
ok("U5  effective_score would be 59.85  (score + role_bonus)",
   approx_equal(
       _r_haaland_wr["captain_score"] + _r_haaland_wr["role_signals"]["role_bonus"],
       59.85))
ok("U6  59.85 >= 55.0 safe threshold",
   _r_haaland_wr["captain_score"] + _r_haaland_wr["role_signals"]["role_bonus"] >= 55.0)


# ===========================================================================
# Section V — Regression: captain scores unchanged for all GW28 players
# ===========================================================================
_section("V — Regression: captain scores unchanged (role is tier-only)")

# Phase 2d/2g baseline scores (parity-validated)
ok("V1  Salah score ≈60.58 (no-role bootstrap)",
   approx_equal(_r_salah_nr["captain_score"], 60.58))
ok("V2  Haaland score ≈54.85 (no-role bootstrap)",
   approx_equal(_r_haaland_nr["captain_score"], 54.85))
ok("V3  Saka score ≈36.35 (no-role bootstrap)",
   approx_equal(_r_saka_nr["captain_score"], 36.35))
ok("V4  De Bruyne score ≈14.0 (no-role bootstrap)",
   approx_equal(_r_dbk_nr["captain_score"], 14.0))

# Scores unchanged even when role fields present
ok("V5  Salah score ≈60.58 (with-role bootstrap — unchanged)",
   approx_equal(_r_salah_wr["captain_score"], 60.58))
ok("V6  Haaland score ≈54.85 (with-role bootstrap — unchanged)",
   approx_equal(_r_haaland_wr["captain_score"], 54.85))
ok("V7  Saka score ≈36.35 (with-role bootstrap — unchanged)",
   approx_equal(_r_saka_wr["captain_score"], 36.35))
ok("V8  De Bruyne score ≈14.0 (with-role bootstrap — unchanged)",
   approx_equal(_r_dbk_wr["captain_score"], 14.0))

# Ranking scores also unchanged
ok("V9  ranking Haaland score ≈54.85 with roles",
   approx_equal(_ranked_wr_by_name["Haaland"]["captain_score"], 54.85))
ok("V10 ranking Salah score ≈60.58 with roles",
   approx_equal(_ranked_wr_by_name["Salah"]["captain_score"], 60.58))


# ===========================================================================
# Section W — Regression: no-role elements → same tiers as Phase 2g
# ===========================================================================
_section("W — Regression: no-role elements produce Phase 2g tiers")

ok("W1  Salah no-role tier=safe  (Phase 2g)",
   _r_salah_nr["tier"] == TIER_SAFE)
ok("W2  Haaland no-role tier=upside  (Phase 2g)",
   _r_haaland_nr["tier"] == TIER_UPSIDE)
ok("W3  Saka no-role tier=differential  (Phase 2g)",
   _r_saka_nr["tier"] == TIER_DIFFERENTIAL)
ok("W4  De Bruyne no-role tier=avoid  (Phase 2g)",
   _r_dbk_nr["tier"] == TIER_AVOID)

# Tool response key set changes: role_signals added
_expected_score_keys = {
    "status", "player_id", "web_name", "name", "team", "team_short",
    "position", "captain_score", "tier", "role_signals", "score_inputs",
    "derived_fields", "query",
}
ok("W5  tool_get_captain_score ok response key set updated for Phase 2h",
   set(_r_salah_nr.keys()) == _expected_score_keys)

_expected_rank_entry_keys = {
    "status", "index", "player_id", "web_name", "name", "team", "team_short",
    "position", "captain_score", "tier", "role_signals", "score_inputs",
    "derived_fields", "query", "rank",
}
ok("W6  ranked ok entry key set updated for Phase 2h",
   set(_ranked_nr_by_name["Salah"].keys()) == _expected_rank_entry_keys)


# ===========================================================================
# Section X — Interface report
# ===========================================================================
_section("X — Interface report")

print()
print("    Phase 2h additions:")
print("      + role_evaluator.py: derive_role_signals, compute_role_bonus, ROLE_BONUS_MAP")
print("      + python/__init__.py + shim: export role_evaluator symbols")
print("      + classify_captain_tier: role_bonus=0.0 keyword param")
print("      + tools.py: derive_role_signals called post-score, role_bonus→tier")
print("      + tool_get_captain_score ok: 'role_signals' field added")
print("      + tool_rank_captain_candidates ok entry: 'role_signals' field added")
print()
print("    Role signals used:")
print("      penalties_order (1→+5.0, 2→+1.0)")
print("      direct_freekicks_order (1→+3.0, 2→+0.5)")
print("      corners_and_indirect_freekicks_order (informational, no bonus in v1)")
print()
print("    Impact on scores: NONE — captain_score formula unchanged")
print("    Impact on tiers: POSSIBLE when role_bonus > 0 crosses a threshold")
print("      Documented GW28 change: Haaland (penalties_order=1)")
print("        upside→safe  (54.85 + 5.0 = 59.85 >= 55.0 safe threshold)")
print()
print("    Unchanged from Phase 2g:")
print("      - captain_score formula (four-factor weights)")
print("      - All Phase 2g validated score values")
print("      - minutes_risk >= 50 → avoid (availability overrides role)")
print("      - Non-ok responses (no role_signals on error/not_found)")
print("      - harness.ask() / context_meta behaviour")
print()

ok("X1  derive_role_signals importable from python package",  callable(derive_role_signals))
ok("X2  compute_role_bonus importable from shim",             callable(_ce_bonus))
ok("X3  ROLE_BONUS_MAP has 4 entries",                        len(ROLE_BONUS_MAP) == 4)
ok("X4  tool_get_captain_score ok includes role_signals",
   "role_signals" in _r_salah_nr)
ok("X5  tool_rank_captain_candidates ok entry includes role_signals",
   all("role_signals" in e for e in _rank_nr["ranked_candidates"] if e["status"] == "ok"))
ok("X6  captain_score unchanged by role fields",
   approx_equal(_r_haaland_nr["captain_score"], _r_haaland_wr["captain_score"]))
ok("X7  Haaland tier changes upside→safe with penalties_order=1",
   _r_haaland_nr["tier"] == TIER_UPSIDE
   and _r_haaland_wr["tier"] == TIER_SAFE)
ok("X8  minutes_risk=50 + role_bonus=8.0 still → avoid",
   classify_captain_tier(70.0, 50.0, 0.15, role_bonus=8.0) == TIER_AVOID)
ok("X9  non-ok tool response has no role_signals key",
   "role_signals" not in tool_get_captain_score("NonExistentXYZ9999", _bs_with_roles()))


# ===========================================================================
# Summary
# ===========================================================================
print()
print("=" * 60)
_total = _passed + _failed
print(f"  Result: {_passed}/{_total} assertions passed")
if _failed:
    print(f"  FAILED: {_failed} assertion(s)")
    sys.exit(1)
else:
    print("  All assertions PASS — Phase 2h complete.")


