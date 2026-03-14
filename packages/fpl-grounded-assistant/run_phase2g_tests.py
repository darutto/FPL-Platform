"""
run_phase2g_tests.py
====================
Standalone Phase 2g validator — no pytest dependency, one-file runner.

Phase 2g: Tiered captain recommendation framing.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2g_tests.py

What is tested
--------------
A deterministic interpretation layer has been added on top of the existing
captain score and ranking outputs.  Each ok result now carries a ``"tier"``
field whose value is one of:

    safe · upside · differential · avoid · low_confidence

The tier is derived by ``classify_captain_tier(captain_score, minutes_risk,
xgi_per_90)`` from the new ``captain_tiers`` module.  The scoring engine is
unchanged; the tier is an interpretation layer only.

Sections
--------
A  — classify_captain_tier: unit tests against canonical examples
B  — classify_captain_tier: boundary / edge cases
C  — CAPTAIN_TIER_RULES: structure and priority ordering
D  — Tier constants: values and ALL_TIERS completeness
E  — fpl_captain_engine exports: all tier symbols importable from shim
F  — tool_get_captain_score: tier field present in ok response
G  — tool_get_captain_score: tier value correct for known inputs
H  — tool_get_captain_score: avoid tier when injured (minutes_risk=100)
I  — tool_rank_captain_candidates: tier field present on all ok entries
J  — tool_rank_captain_candidates: tier values correct for GW28 candidates
K  — tool_rank_captain_candidates: tier absent from non-ok (error) entries
L  — Tier does not affect rank ordering (score still determines rank)
M  — Regression: captain scores unchanged from Phase 2f baseline
N  — Regression: tool contract shape unchanged (tier is additive-only)
O  — Regression: avoid tier + error distinction (tier != tool status)
P  — Interface report: what changed vs what is preserved

Expected result: 100+ assertions, all PASS.

Fixture data (GW28)
-------------------
Arsenal (1, str=4) home vs Man City (13, str=5) → FDR: ARS=5, MCI=4
Liverpool (14, str=5) home vs Chelsea (8, str=4) → FDR: LIV=4, CHE=5
Man Utd (11, str=3) — blank GW
fixture_difficulty_map = {1: 5, 13: 4, 14: 4, 8: 5}

Captain score formula:
    form_score    = min(max((form / 10) * 100, 0.0), 100.0)
    fixture_score = min(max((6 - fdr) * 20, 0.0), 100.0)
    xgi_score     = min(max(xgi_per_90 * 50, 0.0), 100.0)
    minutes_score = min(max(100 - minutes_risk, 0.0), 100.0)
    total = form_score*0.4 + fixture_score*0.3 + xgi_score*0.2 + minutes_score*0.1
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
# Shared test fixtures (GW28 — same as Phase 2d/2e/2f for regression parity)
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

_ELEMENTS = [
    # Haaland: FWD, Man City, available, high form, good xGI per 90
    {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",   "team": 13, "team_code": 43, "element_type": 4,
     "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
     "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
     "expected_goal_involvements": "1.70", "minutes": 1800},
    # Salah: MID, Liverpool, available, very high form
    {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",     "team": 14, "team_code": 1,  "element_type": 3,
     "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
     "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
     "expected_goal_involvements": "1.45", "minutes": 2250},
    # Saka: MID, Arsenal, doubtful (75% chance), moderate form
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",      "team": 1,  "team_code": 3,  "element_type": 3,
     "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
     "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
     "expected_goal_involvements": "0.85", "minutes": 900,
     "chance_of_playing_this_round": 75},
    # De Bruyne: MID, Man City, injured
    {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne", "team": 13, "team_code": 43, "element_type": 3,
     "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
     "form": "0.0", "expected_goals": "0.20", "expected_assists": "0.40",
     "expected_goal_involvements": "0.60", "minutes": 270},
    # Johnson: DEF, Man Utd (blank GW), low xGI
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

_FDR_MAP = {1: 5, 13: 4, 14: 4, 8: 5}

# Bootstrap with FDR map (auto-derivation enabled for all non-blank-GW teams)
_BOOTSTRAP = {
    "elements":               _ELEMENTS,
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}


# ---------------------------------------------------------------------------
# Helper: fresh copy of bootstrap (mutations must not bleed between tests)
# ---------------------------------------------------------------------------

def _bs() -> dict:
    return copy.deepcopy(_BOOTSTRAP)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

print("Phase 2g — Tiered Captain Recommendation Framing")
print("=" * 60)

from python.captain_tiers import (  # type: ignore
    classify_captain_tier,
    CAPTAIN_TIER_RULES,
    TIER_SAFE,
    TIER_UPSIDE,
    TIER_DIFFERENTIAL,
    TIER_AVOID,
    TIER_LOW_CONFIDENCE,
    ALL_TIERS,
)
from fpl_captain_engine import (  # shim
    classify_captain_tier      as _ce_classify,
    CAPTAIN_TIER_RULES         as _ce_rules,
    TIER_SAFE                  as _ce_SAFE,
    TIER_UPSIDE                as _ce_UPSIDE,
    TIER_DIFFERENTIAL          as _ce_DIFF,
    TIER_AVOID                 as _ce_AVOID,
    TIER_LOW_CONFIDENCE        as _ce_LOW,
    ALL_TIERS                  as _ce_ALL,
)
from fpl_tool_contract.tools import (
    tool_get_captain_score,
    tool_rank_captain_candidates,
)


# ===========================================================================
# Section A — classify_captain_tier: canonical examples
# ===========================================================================
_section("A — classify_captain_tier: canonical examples")

# GW28 fixture data (Phase 2d reference values — scores already validated)
# Salah:     score≈60.58, risk=0,   xgi≈0.058 → safe
# Haaland:   score≈54.85, risk=0,   xgi≈0.085 → upside  (just below safe; big xGI)
# Saka:      score≈36.35, risk=25,  xgi≈0.085 → differential
# De Bruyne: score≈14.0,  risk=100, xgi≈0.200 → avoid   (injured)

ok("A1  Salah-like (60.58, 0, 0.058) → safe",
   classify_captain_tier(60.58, 0.0, 0.058) == TIER_SAFE)

ok("A2  Haaland-like (54.85, 0, 0.085) → upside",
   classify_captain_tier(54.85, 0.0, 0.085) == TIER_UPSIDE)

ok("A3  Saka-like (36.35, 25, 0.085) → differential",
   classify_captain_tier(36.35, 25.0, 0.085) == TIER_DIFFERENTIAL)

ok("A4  De Bruyne injured (14.0, 100, 0.200) → avoid",
   classify_captain_tier(14.0, 100.0, 0.200) == TIER_AVOID)

ok("A5  catch-all (28.0, 35, 0.04) → low_confidence",
   classify_captain_tier(28.0, 35.0, 0.04) == TIER_LOW_CONFIDENCE)

ok("A6  Returns str type",
   isinstance(classify_captain_tier(50.0, 10.0, 0.10), str))

ok("A7  Returns a value in ALL_TIERS",
   classify_captain_tier(50.0, 10.0, 0.10) in ALL_TIERS)


# ===========================================================================
# Section B — classify_captain_tier: boundary / edge cases
# ===========================================================================
_section("B — classify_captain_tier: boundary / edge cases")

# Avoid thresholds
ok("B1  minutes_risk=50 exactly → avoid",
   classify_captain_tier(60.0, 50.0, 0.10) == TIER_AVOID)
ok("B2  minutes_risk=49.9 does NOT trigger avoid by risk alone",
   classify_captain_tier(60.0, 49.9, 0.10) != TIER_AVOID)
ok("B3  captain_score=19.9 → avoid  (<20)",
   classify_captain_tier(19.9, 5.0, 0.05) == TIER_AVOID)
ok("B4  captain_score=20.0 does NOT trigger avoid by score alone",
   classify_captain_tier(20.0, 5.0, 0.05) != TIER_AVOID)

# Safe thresholds
ok("B5  score=55.0, risk=20.0 → safe  (boundary)",
   classify_captain_tier(55.0, 20.0, 0.05) == TIER_SAFE)
ok("B6  score=54.9, risk=20.0 is not safe",
   classify_captain_tier(54.9, 20.0, 0.05) != TIER_SAFE)
ok("B7  score=55.0, risk=20.1 is not safe",
   classify_captain_tier(55.0, 20.1, 0.05) != TIER_SAFE)

# Upside thresholds
ok("B8  score=45.0, risk=25.0, xgi=0.07 → upside  (boundary)",
   classify_captain_tier(45.0, 25.0, 0.07) == TIER_UPSIDE)
ok("B9  score=45.0, risk=25.0, xgi=0.069 → not upside  (xgi too low)",
   classify_captain_tier(45.0, 25.0, 0.069) != TIER_UPSIDE)
ok("B10 score=44.9, risk=25.0, xgi=0.10 → not upside  (score too low)",
   classify_captain_tier(44.9, 25.0, 0.10) != TIER_UPSIDE)
ok("B11 score=45.0, risk=25.1, xgi=0.10 → not upside  (risk too high)",
   classify_captain_tier(45.0, 25.1, 0.10) != TIER_UPSIDE)

# Differential thresholds
ok("B12 score=30.0, risk=30.0 → differential  (boundary)",
   classify_captain_tier(30.0, 30.0, 0.03) == TIER_DIFFERENTIAL)
ok("B13 score=29.9, risk=30.0 → not differential  (score too low)",
   classify_captain_tier(29.9, 30.0, 0.03) != TIER_DIFFERENTIAL)
ok("B14 score=30.0, risk=30.1 → not differential  (risk too high)",
   classify_captain_tier(30.0, 30.1, 0.03) != TIER_DIFFERENTIAL)

# Catch-all
ok("B15 score=25.0, risk=35.0 → low_confidence  (catch-all)",
   classify_captain_tier(25.0, 35.0, 0.03) == TIER_LOW_CONFIDENCE)

# Priority: avoid beats safe (risk=100 overrides high score)
ok("B16 avoid beats safe: score=80, risk=100 → avoid",
   classify_captain_tier(80.0, 100.0, 0.10) == TIER_AVOID)

# fixture_difficulty parameter is reserved/ignored — result unchanged
ok("B17 fixture_difficulty=None (default) works",
   classify_captain_tier(60.0, 0.0, 0.10) == TIER_SAFE)
ok("B18 fixture_difficulty=1 same result (not used in v1 logic)",
   classify_captain_tier(60.0, 0.0, 0.10, fixture_difficulty=1) == TIER_SAFE)
ok("B19 fixture_difficulty=5 same result (not used in v1 logic)",
   classify_captain_tier(60.0, 0.0, 0.10, fixture_difficulty=5) == TIER_SAFE)


# ===========================================================================
# Section C — CAPTAIN_TIER_RULES: structure and priority ordering
# ===========================================================================
_section("C — CAPTAIN_TIER_RULES: structure and priority ordering")

ok("C1  CAPTAIN_TIER_RULES is a dict", isinstance(CAPTAIN_TIER_RULES, dict))
ok("C2  Contains avoid tier",          TIER_AVOID in CAPTAIN_TIER_RULES)
ok("C3  Contains safe tier",           TIER_SAFE in CAPTAIN_TIER_RULES)
ok("C4  Contains upside tier",         TIER_UPSIDE in CAPTAIN_TIER_RULES)
ok("C5  Contains differential tier",   TIER_DIFFERENTIAL in CAPTAIN_TIER_RULES)
ok("C6  Contains low_confidence tier", TIER_LOW_CONFIDENCE in CAPTAIN_TIER_RULES)
ok("C7  Exactly 5 tiers",              len(CAPTAIN_TIER_RULES) == 5)

# Priority ordering
ok("C8  avoid priority=1",             CAPTAIN_TIER_RULES[TIER_AVOID]["priority"] == 1)
ok("C9  safe priority=2",              CAPTAIN_TIER_RULES[TIER_SAFE]["priority"] == 2)
ok("C10 upside priority=3",            CAPTAIN_TIER_RULES[TIER_UPSIDE]["priority"] == 3)
ok("C11 differential priority=4",      CAPTAIN_TIER_RULES[TIER_DIFFERENTIAL]["priority"] == 4)
ok("C12 low_confidence priority=5",    CAPTAIN_TIER_RULES[TIER_LOW_CONFIDENCE]["priority"] == 5)

# Threshold values from CAPTAIN_TIER_RULES match what classify_captain_tier uses
_avoid_t = CAPTAIN_TIER_RULES[TIER_AVOID]["thresholds"]
_safe_t  = CAPTAIN_TIER_RULES[TIER_SAFE]["thresholds"]
_up_t    = CAPTAIN_TIER_RULES[TIER_UPSIDE]["thresholds"]
_diff_t  = CAPTAIN_TIER_RULES[TIER_DIFFERENTIAL]["thresholds"]

ok("C13 avoid minutes_risk_min=50",    _avoid_t["minutes_risk_min"] == 50.0)
ok("C14 avoid captain_score_max=20",   _avoid_t["captain_score_max"] == 20.0)
ok("C15 safe captain_score_min=55",    _safe_t["captain_score_min"] == 55.0)
ok("C16 safe minutes_risk_max=20",     _safe_t["minutes_risk_max"] == 20.0)
ok("C17 upside captain_score_min=45",  _up_t["captain_score_min"] == 45.0)
ok("C18 upside minutes_risk_max=25",   _up_t["minutes_risk_max"] == 25.0)
ok("C19 upside xgi_per_90_min=0.07",   _up_t["xgi_per_90_min"] == 0.07)
ok("C20 differential score_min=30",    _diff_t["captain_score_min"] == 30.0)
ok("C21 differential risk_max=30",     _diff_t["minutes_risk_max"] == 30.0)
ok("C22 low_confidence thresholds={}",
   CAPTAIN_TIER_RULES[TIER_LOW_CONFIDENCE]["thresholds"] == {})

# Each rule has a non-empty description
for _tier, _rule in CAPTAIN_TIER_RULES.items():
    ok(f"C23-{_tier} has description string",
       isinstance(_rule.get("description"), str) and len(_rule["description"]) > 0)


# ===========================================================================
# Section D — Tier constants: values and ALL_TIERS completeness
# ===========================================================================
_section("D — Tier constants and ALL_TIERS")

ok("D1  TIER_SAFE='safe'",              TIER_SAFE == "safe")
ok("D2  TIER_UPSIDE='upside'",          TIER_UPSIDE == "upside")
ok("D3  TIER_DIFFERENTIAL='differential'", TIER_DIFFERENTIAL == "differential")
ok("D4  TIER_AVOID='avoid'",            TIER_AVOID == "avoid")
ok("D5  TIER_LOW_CONFIDENCE='low_confidence'", TIER_LOW_CONFIDENCE == "low_confidence")

ok("D6  ALL_TIERS is a tuple",          isinstance(ALL_TIERS, tuple))
ok("D7  ALL_TIERS has 5 members",       len(ALL_TIERS) == 5)
ok("D8  safe in ALL_TIERS",             TIER_SAFE in ALL_TIERS)
ok("D9  upside in ALL_TIERS",           TIER_UPSIDE in ALL_TIERS)
ok("D10 differential in ALL_TIERS",     TIER_DIFFERENTIAL in ALL_TIERS)
ok("D11 avoid in ALL_TIERS",            TIER_AVOID in ALL_TIERS)
ok("D12 low_confidence in ALL_TIERS",   TIER_LOW_CONFIDENCE in ALL_TIERS)
ok("D13 ALL_TIERS has no duplicates",   len(set(ALL_TIERS)) == 5)


# ===========================================================================
# Section E — fpl_captain_engine shim: all tier symbols importable
# ===========================================================================
_section("E — fpl_captain_engine shim exports")

ok("E1  classify_captain_tier importable from shim",
   callable(_ce_classify))
ok("E2  CAPTAIN_TIER_RULES importable from shim",
   isinstance(_ce_rules, dict) and len(_ce_rules) == 5)
ok("E3  TIER_SAFE importable from shim",           _ce_SAFE == "safe")
ok("E4  TIER_UPSIDE importable from shim",          _ce_UPSIDE == "upside")
ok("E5  TIER_DIFFERENTIAL importable from shim",    _ce_DIFF == "differential")
ok("E6  TIER_AVOID importable from shim",           _ce_AVOID == "avoid")
ok("E7  TIER_LOW_CONFIDENCE importable from shim",  _ce_LOW == "low_confidence")
ok("E8  ALL_TIERS importable from shim",
   isinstance(_ce_ALL, tuple) and len(_ce_ALL) == 5)
ok("E9  shim classify_captain_tier is same function",
   _ce_classify is classify_captain_tier)
ok("E10 shim CAPTAIN_TIER_RULES is same object",
   _ce_rules is CAPTAIN_TIER_RULES)


# ===========================================================================
# Section F — tool_get_captain_score: tier field present in ok response
# ===========================================================================
_section("F — tool_get_captain_score: tier field present")

_r_salah = tool_get_captain_score("Salah", _bs())
ok("F1  Salah result status=ok",        _r_salah["status"] == "ok")
ok("F2  Salah result has 'tier' key",   "tier" in _r_salah)
ok("F3  Salah tier is a string",        isinstance(_r_salah.get("tier"), str))
ok("F4  Salah tier is in ALL_TIERS",    _r_salah.get("tier") in ALL_TIERS)

_r_haaland = tool_get_captain_score("Haaland", _bs())
ok("F5  Haaland result status=ok",      _r_haaland["status"] == "ok")
ok("F6  Haaland result has 'tier' key", "tier" in _r_haaland)

_r_saka = tool_get_captain_score("Saka", _bs())
ok("F7  Saka result status=ok",         _r_saka["status"] == "ok")
ok("F8  Saka result has 'tier' key",    "tier" in _r_saka)

_r_dbk = tool_get_captain_score("De Bruyne", _bs())
ok("F9  De Bruyne result status=ok",    _r_dbk["status"] == "ok")
ok("F10 De Bruyne result has 'tier' key", "tier" in _r_dbk)


# ===========================================================================
# Section G — tool_get_captain_score: tier value correct for known inputs
# ===========================================================================
_section("G — tool_get_captain_score: tier values correct")

# Phase 2d baseline scores:
#   Salah:     ~60.58 → safe
#   Haaland:   ~54.85 → upside  (score just below safe; big xGI)
#   Saka:      ~36.35 → differential
#   De Bruyne: ~14.0  → avoid

ok("G1  Salah tier=safe",              _r_salah["tier"] == TIER_SAFE)
ok("G2  Haaland tier=upside",          _r_haaland["tier"] == TIER_UPSIDE)
ok("G3  Saka tier=differential",       _r_saka["tier"] == TIER_DIFFERENTIAL)
ok("G4  De Bruyne tier=avoid",         _r_dbk["tier"] == TIER_AVOID)

# Tier is derivable independently from score_inputs
_s = _r_salah
ok("G5  Salah tier derivable from score_inputs",
   classify_captain_tier(
       _s["captain_score"],
       _s["score_inputs"]["minutes_risk"],
       _s["score_inputs"]["xgi_per_90"],
   ) == _s["tier"])

_h = _r_haaland
ok("G6  Haaland tier derivable from score_inputs",
   classify_captain_tier(
       _h["captain_score"],
       _h["score_inputs"]["minutes_risk"],
       _h["score_inputs"]["xgi_per_90"],
   ) == _h["tier"])

_d = _r_dbk
ok("G7  De Bruyne tier derivable from score_inputs",
   classify_captain_tier(
       _d["captain_score"],
       _d["score_inputs"]["minutes_risk"],
       _d["score_inputs"]["xgi_per_90"],
   ) == _d["tier"])


# ===========================================================================
# Section H — tool_get_captain_score: avoid tier when injured
# ===========================================================================
_section("H — tool_get_captain_score: avoid tier for injured player")

ok("H1  De Bruyne is injured (minutes_risk=100)",
   _r_dbk["score_inputs"]["minutes_risk"] == 100.0)
ok("H2  De Bruyne tier=avoid",
   _r_dbk["tier"] == TIER_AVOID)
ok("H3  De Bruyne status=ok (tool resolves; tier handles recommendation)",
   _r_dbk["status"] == "ok")
# Tier 'avoid' and tool status 'ok' coexist — tier is a recommendation, not a
# resolution failure.
ok("H4  tier=avoid does not make status=error",
   _r_dbk["tier"] == TIER_AVOID and _r_dbk["status"] == "ok")


# ===========================================================================
# Section I — tool_rank_captain_candidates: tier field on all ok entries
# ===========================================================================
_section("I — tool_rank_captain_candidates: tier field present")

_rank_result = tool_rank_captain_candidates(
    [
        {"query": "Salah"},
        {"query": "Haaland"},
        {"query": "Saka"},
        {"query": "De Bruyne"},
    ],
    _bs(),
)

ok("I1  ranking result status=ok",     _rank_result["status"] == "ok")
ok("I2  4 candidates total",           _rank_result["total"] == 4)
ok("I3  0 errors",                     _rank_result["error_count"] == 0)

_ranked = _rank_result["ranked_candidates"]

ok("I4  ranked_candidates is a list",  isinstance(_ranked, list))
ok("I5  4 entries in ranked list",     len(_ranked) == 4)

for _idx, _entry in enumerate(_ranked):
    ok(f"I6.{_idx} entry[{_idx}] has 'tier'", "tier" in _entry)
    ok(f"I7.{_idx} entry[{_idx}] tier in ALL_TIERS",
       _entry.get("tier") in ALL_TIERS)


# ===========================================================================
# Section J — tool_rank_captain_candidates: tier values correct for GW28
# ===========================================================================
_section("J — tool_rank_captain_candidates: tier values correct")

_ranked_by_name = {e["web_name"]: e for e in _ranked}

ok("J1  Salah ranked entry tier=safe",
   _ranked_by_name["Salah"]["tier"] == TIER_SAFE)
ok("J2  Haaland ranked entry tier=upside",
   _ranked_by_name["Haaland"]["tier"] == TIER_UPSIDE)
ok("J3  Saka ranked entry tier=differential",
   _ranked_by_name["Saka"]["tier"] == TIER_DIFFERENTIAL)
ok("J4  De Bruyne ranked entry tier=avoid",
   _ranked_by_name["De Bruyne"]["tier"] == TIER_AVOID)

# Each ranked tier should be derivable from that entry's score_inputs
for _name, _entry in _ranked_by_name.items():
    _inputs = _entry["score_inputs"]
    _expected = classify_captain_tier(
        _entry["captain_score"],
        _inputs["minutes_risk"],
        _inputs["xgi_per_90"],
    )
    ok(f"J5.{_name} tier consistent with score_inputs",
       _entry["tier"] == _expected)


# ===========================================================================
# Section K — tool_rank_captain_candidates: tier absent from non-ok entries
# ===========================================================================
_section("K — tier absent from non-ok entries")

_rank_with_error = tool_rank_captain_candidates(
    [
        {"query": "Salah"},
        {"query": "NonExistentPlayerXYZ9999"},
        {"query": "Haaland"},
    ],
    _bs(),
)

ok("K1  rank result with error: status=ok",      _rank_with_error["status"] == "ok")
ok("K2  2 ok results",                            _rank_with_error["total"] == 2)
ok("K3  1 non-ok result",                         _rank_with_error["error_count"] == 1)

_non_ok = [e for e in _rank_with_error["ranked_candidates"] if e["status"] != "ok"]
ok("K4  exactly 1 non-ok entry",                  len(_non_ok) == 1)
ok("K5  non-ok entry has no 'tier' key",          "tier" not in _non_ok[0])
ok("K6  non-ok entry has status 'not_found'",     _non_ok[0]["status"] == "not_found")

_ok_entries = [e for e in _rank_with_error["ranked_candidates"] if e["status"] == "ok"]
ok("K7  ok entries all have tier",
   all("tier" in e for e in _ok_entries))


# ===========================================================================
# Section L — Tier does not affect rank ordering
# ===========================================================================
_section("L — Tier does not affect rank ordering")

_rank_all = tool_rank_captain_candidates(
    [
        {"query": "Salah"},
        {"query": "Haaland"},
        {"query": "Saka"},
        {"query": "De Bruyne"},
    ],
    _bs(),
)

_ok_ranked = [e for e in _rank_all["ranked_candidates"] if e["status"] == "ok"]
_scores_desc = [e["captain_score"] for e in _ok_ranked]
ok("L1  ok entries are sorted by score descending",
   _scores_desc == sorted(_scores_desc, reverse=True))

# Rank 1 = highest score player, regardless of tier
_rank1 = next(e for e in _ok_ranked if e["rank"] == 1)
ok("L2  rank 1 player has the highest captain_score",
   _rank1["captain_score"] == max(e["captain_score"] for e in _ok_ranked))

# All four should still have a tier
ok("L3  all 4 ok entries have tier",
   all("tier" in e for e in _ok_ranked))

# De Bruyne should have avoid tier and still appear in ranking (not filtered out)
_dbk_entry = _ranked_by_name.get("De Bruyne", {})
ok("L4  De Bruyne (avoid) still appears in ranking",
   _dbk_entry.get("tier") == TIER_AVOID and _dbk_entry.get("status") == "ok")


# ===========================================================================
# Section M — Regression: captain scores unchanged from Phase 2f baseline
# ===========================================================================
_section("M — Regression: captain scores unchanged")

# Phase 2d / 2f validated baseline scores (GW28, FDR from map)
# Salah:     form=9.5, fdr=4(LIV vs CHE → opp str=4), risk=0, xgi=1.45/25=0.0578
# Haaland:   form=8.0, fdr=4(MCI at ARS → opp str=4), risk=0, xgi=1.70/20=0.0850
# Saka:      form=5.5, fdr=5(ARS vs MCI → opp str=5), risk=25, xgi=0.85/10=0.0850
# De Bruyne: form=0.0, fdr=4(MCI at ARS → opp str=4), risk=100, xgi=0.60/3=0.2000

ok("M1  Salah score ≈60.58",
   approx_equal(_r_salah["captain_score"], 60.58))
ok("M2  Haaland score ≈54.85",
   approx_equal(_r_haaland["captain_score"], 54.85))
ok("M3  Saka score ≈36.35",
   approx_equal(_r_saka["captain_score"], 36.35))
ok("M4  De Bruyne score ≈14.0",
   approx_equal(_r_dbk["captain_score"], 14.0))

# Scores in ranking match individual lookups
ok("M5  ranking Salah score unchanged",
   approx_equal(_ranked_by_name["Salah"]["captain_score"], 60.58))
ok("M6  ranking Haaland score unchanged",
   approx_equal(_ranked_by_name["Haaland"]["captain_score"], 54.85))
ok("M7  ranking Saka score unchanged",
   approx_equal(_ranked_by_name["Saka"]["captain_score"], 36.35))
ok("M8  ranking De Bruyne score unchanged",
   approx_equal(_ranked_by_name["De Bruyne"]["captain_score"], 14.0))


# ===========================================================================
# Section N — Regression: tool contract shape unchanged (tier is additive)
# ===========================================================================
_section("N — Regression: tool contract shape unchanged")

_expected_score_keys = {
    "status", "player_id", "web_name", "name", "team", "team_short",
    "position", "captain_score", "tier", "score_inputs", "derived_fields", "query",
}
ok("N1  tool_get_captain_score ok response has expected keys",
   set(_r_salah.keys()) == _expected_score_keys)

_expected_rank_entry_keys = {
    "status", "index", "player_id", "web_name", "name", "team", "team_short",
    "position", "captain_score", "tier", "score_inputs", "derived_fields",
    "query", "rank",
}
ok("N2  ranked ok entry has expected keys",
   set(_ranked_by_name["Salah"].keys()) == _expected_rank_entry_keys)

ok("N3  score_inputs has 4 keys",
   set(_r_salah["score_inputs"].keys()) == {"form", "fixture_difficulty", "xgi_per_90", "minutes_risk"})
ok("N4  tier field follows captain_score in get_captain_score",
   list(_r_salah.keys()).index("tier") == list(_r_salah.keys()).index("captain_score") + 1)
ok("N5  tier field follows captain_score in ranked entry",
   list(_ranked_by_name["Salah"].keys()).index("tier") ==
   list(_ranked_by_name["Salah"].keys()).index("captain_score") + 1)

# Non-ok tool results do not gain tier
_not_found = tool_get_captain_score("NonExistentPlayerXYZ9999", _bs())
ok("N6  not_found result has no tier key",  "tier" not in _not_found)
ok("N7  not_found status preserved",        _not_found["status"] == "not_found")

# Ranked result shape unchanged
ok("N8  ranked result still has: status, ranked_candidates, total, error_count",
   set(_rank_result.keys()) >= {"status", "ranked_candidates", "total", "error_count"})


# ===========================================================================
# Section O — Regression: avoid tier + error distinction
# ===========================================================================
_section("O — Regression: avoid tier vs error status are independent")

# 'avoid' tier = recommendation label (player resolves fine, just risky to captain)
# 'error' status = tool failure (player not found, missing args, etc.)
# These must remain distinct — an injured player should not look like a resolution error.

ok("O1  injured player has status=ok",       _r_dbk["status"] == "ok")
ok("O2  injured player has tier=avoid",       _r_dbk["tier"] == TIER_AVOID)
ok("O3  not_found player has status=not_found, no tier",
   _not_found["status"] == "not_found" and "tier" not in _not_found)

# Verify all valid ALL_TIERS values can coexist with status=ok
ok("O4  ALL_TIERS contains avoid",            TIER_AVOID in ALL_TIERS)
ok("O5  'error' is not a valid tier value",   "error" not in ALL_TIERS)
ok("O6  'not_found' is not a valid tier",     "not_found" not in ALL_TIERS)
ok("O7  'ok' is not a valid tier",            "ok" not in ALL_TIERS)


# ===========================================================================
# Section P — Interface report: what changed vs what is preserved
# ===========================================================================
_section("P — Interface report")

print()
print("    Phase 2g additions:")
print("      + captain_tiers.py module (classify_captain_tier, CAPTAIN_TIER_RULES,")
print("        TIER_SAFE, TIER_UPSIDE, TIER_DIFFERENTIAL, TIER_AVOID,")
print("        TIER_LOW_CONFIDENCE, ALL_TIERS)")
print("      + python/__init__.py: exports all tier symbols")
print("      + fpl_captain_engine/__init__.py: shim re-exports all tier symbols")
print("      + tools.py import: classify_captain_tier added to fpl_captain_engine import")
print("      + tool_get_captain_score ok response: 'tier' field added after 'captain_score'")
print("      + tool_rank_captain_candidates ok entries: 'tier' field added after 'captain_score'")
print()
print("    Unchanged:")
print("      - Captain score formula (all four weights and sub-scores)")
print("      - All 2f / 2e / 2d validated captain score values")
print("      - Rank ordering (still by captain_score descending)")
print("      - Non-ok responses (no tier added to error/not_found/ambiguous entries)")
print("      - harness.ask() interface and context_meta behaviour")
print("      - TierClassifier / TieredCaptainSelector (premium/differential/outlier)")
print()

ok("P1  classify_captain_tier exported from python package",
   callable(classify_captain_tier))
ok("P2  classify_captain_tier exported from fpl_captain_engine shim",
   callable(_ce_classify))
ok("P3  tool_get_captain_score ok response includes 'tier'",
   "tier" in _r_salah)
ok("P4  tool_rank_captain_candidates ok entry includes 'tier'",
   all("tier" in e for e in _ranked))
ok("P5  tier vocab is 5-value set",
   set(ALL_TIERS) == {"safe", "upside", "differential", "avoid", "low_confidence"})
ok("P6  scoring unchanged — Salah score ≈60.58",
   approx_equal(_r_salah["captain_score"], 60.58))
ok("P7  non-ok entries have no tier",
   "tier" not in _non_ok[0])
ok("P8  CAPTAIN_TIER_RULES fully documents all thresholds",
   all("thresholds" in v for v in CAPTAIN_TIER_RULES.values()))


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
    print("  All assertions PASS — Phase 2g complete.")


