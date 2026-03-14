"""
run_phase2f_tests.py
====================
Standalone Phase 2f validator — no pytest dependency, one-file runner.

Phase 2f: Context-native harness integration.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2f_tests.py

What is tested
--------------
ask() now transparently accepts either:
  (a) a raw FPL bootstrap dict  — existing behaviour unchanged
  (b) a full assembled context dict from assemble_captain_context()

Detection is automatic (nested "bootstrap" key present → assembled context).
When assembled context is passed, result["context_meta"] is populated.
When raw bootstrap is passed, "context_meta" key is absent (backwards compat).
No assembly logic lives in the harness.

Sections
--------
A  — _is_assembled_context detection helper
B  — _resolve_bootstrap_and_meta extraction helper
C  — ask() with assembled context: basic shape
D  — ask() with assembled context: captain score
E  — ask() with assembled context: ranking
F  — ask() with assembled context: context_meta in return dict
G  — ask() with raw bootstrap: backward compat (no context_meta key)
H  — ask() with raw bootstrap + fixture_difficulty_map: backward compat
I  — Unrecognised query: context_meta present/absent correctly
J  — candidate_inputs override still works with assembled context
K  — candidates_list override still works with assembled context
L  — Blank-GW team safety preserved with assembled context
M  — Safety regression: ambiguous / not_found unchanged
N  — Phase 2e regression: assemble_captain_context + ask(ctx) end-to-end
O  — Phase 2d regression: scores unchanged
P  — Interface report: what changed vs what is preserved

Expected result: 100+ assertions, all PASS.

Fixture data (GW28)
-------------------
Arsenal (1, str=4) home vs Man City (13, str=5) → FDR: ARS=5, MCI=4
Liverpool (14, str=5) home vs Chelsea (8, str=4) → FDR: LIV=4, CHE=5
Man Utd (11, str=3) — blank GW
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
# Shared test fixtures (same as Phase 2e/2d for regression parity)
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

_FDR_MAP = {1: 5, 13: 4, 14: 4, 8: 5}

# Raw bootstrap WITHOUT FDR map
_BOOTSTRAP_BASE = {
    "elements":      _ELEMENTS,
    "teams":         _TEAMS,
    "events":        _EVENTS,
    "element_types": _ELEMENT_TYPES,
}

# Raw bootstrap WITH FDR map (Phase 2d style)
_BOOTSTRAP_WITH_MAP = {
    "elements":               _ELEMENTS,
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}

# Expected scores (unchanged from Phase 2d/2e)
_SCORE_HAALAND  = 54.85
_SCORE_SALAH    = 60.58
_SCORE_SAKA     = 36.35
_SCORE_DEBRUYNE = 14.0

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
print("Phase 2f — Context-native harness integration")
print("=" * 52)

try:
    from fpl_grounded_assistant import ask
    from fpl_grounded_assistant.harness import (
        _is_assembled_context,
        _resolve_bootstrap_and_meta,
    )
    from fpl_pipeline import assemble_captain_context
    _imports_ok = True
except Exception as e:
    _imports_ok = False
    print(f"  IMPORT ERROR: {e}")

ok("imports succeeded", _imports_ok)
if not _imports_ok:
    sys.exit(1)


# ---------------------------------------------------------------------------
# Build a reusable assembled context (injected — no network)
# ---------------------------------------------------------------------------
def _make_ctx():
    """Return a fresh assembled context dict with injected bootstrap + fixtures."""
    return assemble_captain_context(
        bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
        fixtures=_FIXTURES_GW28,
    )


# ===========================================================================
# Section A — _is_assembled_context detection helper
# ===========================================================================
_section("A: _is_assembled_context detection")

ok("A1  assembled context → True",
   _is_assembled_context(_make_ctx()))
ok("A2  raw bootstrap (no map) → False",
   not _is_assembled_context(copy.deepcopy(_BOOTSTRAP_BASE)))
ok("A3  raw bootstrap with map → False",
   not _is_assembled_context(copy.deepcopy(_BOOTSTRAP_WITH_MAP)))
ok("A4  empty dict → False",
   not _is_assembled_context({}))
ok("A5  dict with 'bootstrap' key that is not a dict → False",
   not _is_assembled_context({"bootstrap": "not-a-dict"}))
ok("A6  dict with 'bootstrap' = None → False",
   not _is_assembled_context({"bootstrap": None}))
ok("A7  dict with 'bootstrap' = {} (empty dict) → True",
   _is_assembled_context({"bootstrap": {}}))


# ===========================================================================
# Section B — _resolve_bootstrap_and_meta extraction helper
# ===========================================================================
_section("B: _resolve_bootstrap_and_meta extraction")

_ctx_b = _make_ctx()
_bs_b, _meta_b = _resolve_bootstrap_and_meta(_ctx_b)

ok("B1  from assembled context: bootstrap is nested bootstrap",
   _bs_b is _ctx_b["bootstrap"])
ok("B2  from assembled context: meta is ctx meta",
   _meta_b is _ctx_b["meta"])
ok("B3  meta is a dict",         isinstance(_meta_b, dict))

# From raw bootstrap
_raw_bs = copy.deepcopy(_BOOTSTRAP_BASE)
_bs_raw, _meta_raw = _resolve_bootstrap_and_meta(_raw_bs)
ok("B4  from raw bootstrap: bootstrap returned unchanged",
   _bs_raw is _raw_bs)
ok("B5  from raw bootstrap: meta is None",
   _meta_raw is None)

# From raw bootstrap with map
_raw_bs_map = copy.deepcopy(_BOOTSTRAP_WITH_MAP)
_bs_map, _meta_map = _resolve_bootstrap_and_meta(_raw_bs_map)
ok("B6  raw bootstrap with map: returns bootstrap unchanged",
   _bs_map is _raw_bs_map)
ok("B7  raw bootstrap with map: meta is None",
   _meta_map is None)


# ===========================================================================
# Section C — ask() with assembled context: basic shape
# ===========================================================================
_section("C: ask() with assembled context — basic shape")

_ctx_c = _make_ctx()
_c_result = ask("captain score for Haaland", _ctx_c)

ok("C1  returns a dict",            isinstance(_c_result, dict))
ok("C2  selected_tool present",     "selected_tool" in _c_result)
ok("C3  tool_input present",        "tool_input"    in _c_result)
ok("C4  raw_output present",        "raw_output"    in _c_result)
ok("C5  answer_text present",       "answer_text"   in _c_result)
ok("C6  context_meta present",      "context_meta"  in _c_result)
ok("C7  selected_tool is captain",
   _c_result["selected_tool"] == "get_captain_score")
ok("C8  raw_output status ok",      _c_result["raw_output"]["status"] == "ok")
ok("C9  context_meta is a dict",    isinstance(_c_result["context_meta"], dict))


# ===========================================================================
# Section D — ask() with assembled context: captain score
# ===========================================================================
_section("D: ask() with assembled context — captain score")

_ctx_d = _make_ctx()

_d_haaland  = ask("captain score for Haaland",   _ctx_d)
_d_salah    = ask("captain score for Salah",      _ctx_d)
_d_saka     = ask("captain score for Saka",       _ctx_d)
_d_debruyne = ask("captain score for De Bruyne",  _ctx_d)

ok("D1  Haaland status ok",         _d_haaland["raw_output"]["status"] == "ok")
ok("D2  Haaland score ~54.85",
   approx_equal(_d_haaland["raw_output"]["captain_score"], _SCORE_HAALAND))
ok("D3  Salah status ok",           _d_salah["raw_output"]["status"] == "ok")
ok("D4  Salah score ~60.58",
   approx_equal(_d_salah["raw_output"]["captain_score"], _SCORE_SALAH))
ok("D5  Saka status ok",            _d_saka["raw_output"]["status"] == "ok")
ok("D6  Saka score ~36.35",
   approx_equal(_d_saka["raw_output"]["captain_score"], _SCORE_SAKA))
ok("D7  De Bruyne status ok",       _d_debruyne["raw_output"]["status"] == "ok")
ok("D8  De Bruyne score ~14.0",
   approx_equal(_d_debruyne["raw_output"]["captain_score"], _SCORE_DEBRUYNE))


# ===========================================================================
# Section E — ask() with assembled context: ranking
# ===========================================================================
_section("E: ask() with assembled context — ranking")

_ctx_e = _make_ctx()
_candidates = [
    {"query": "Haaland"},
    {"query": "Salah"},
    {"query": "Saka"},
    {"query": "De Bruyne"},
]

_e_result = ask("rank my captain candidates", _ctx_e, candidates_list=_candidates)

ok("E1  selected_tool is ranking",
   _e_result["selected_tool"] == "rank_captain_candidates")
ok("E2  raw_output status ok",      _e_result["raw_output"]["status"] == "ok")
ok("E3  ranked_candidates present", "ranked_candidates" in _e_result["raw_output"])
ok("E4  context_meta present",      "context_meta" in _e_result)

_ranked = _e_result["raw_output"]["ranked_candidates"]
_ok_ranked = [r for r in _ranked if r.get("status") == "ok"]
ok("E5  4 ok entries",              len(_ok_ranked) == 4)

_scores = [r["captain_score"] for r in _ok_ranked]
ok("E6  sorted descending",         _scores == sorted(_scores, reverse=True))
ok("E7  first is Salah",            _ok_ranked[0]["web_name"] == "Salah")
ok("E8  second is Haaland",         _ok_ranked[1]["web_name"] == "Haaland")
ok("E9  Salah score ~60.58",
   approx_equal(_ok_ranked[0]["captain_score"], _SCORE_SALAH))
ok("E10 Haaland score ~54.85",
   approx_equal(_ok_ranked[1]["captain_score"], _SCORE_HAALAND))


# ===========================================================================
# Section F — context_meta content when assembled context passed
# ===========================================================================
_section("F: context_meta content in return dict")

_ctx_f = _make_ctx()
_f_result = ask("captain score for Salah", _ctx_f)
_meta_f = _f_result["context_meta"]

ok("F1  context_meta has 'gw_resolved_via'",  "gw_resolved_via"  in _meta_f)
ok("F2  context_meta has 'fixture_count'",     "fixture_count"    in _meta_f)
ok("F3  context_meta has 'team_count'",        "team_count"       in _meta_f)
ok("F4  context_meta has 'blank_gw_teams'",    "blank_gw_teams"   in _meta_f)
ok("F5  context_meta has 'assembled_at'",      "assembled_at"     in _meta_f)
ok("F6  blank_gw_teams contains Man Utd (11)", 11 in _meta_f["blank_gw_teams"])
ok("F7  fixture_count == 2",                   _meta_f["fixture_count"] == 2)
ok("F8  team_count == 5",                      _meta_f["team_count"] == 5)
ok("F9  gw_resolved_via == 'bootstrap'",       _meta_f["gw_resolved_via"] == "bootstrap")


# ===========================================================================
# Section G — ask() with raw bootstrap: backward compatibility
# ===========================================================================
_section("G: ask() with raw bootstrap — backward compatibility (no context_meta)")

_g_result = ask("captain score for Haaland", copy.deepcopy(_BOOTSTRAP_WITH_MAP))

ok("G1  returns a dict",            isinstance(_g_result, dict))
ok("G2  selected_tool present",     "selected_tool" in _g_result)
ok("G3  tool_input present",        "tool_input"    in _g_result)
ok("G4  raw_output present",        "raw_output"    in _g_result)
ok("G5  answer_text present",       "answer_text"   in _g_result)
ok("G6  context_meta ABSENT",       "context_meta" not in _g_result)
ok("G7  raw_output status ok",      _g_result["raw_output"]["status"] == "ok")
ok("G8  score matches Phase 2d",
   approx_equal(_g_result["raw_output"]["captain_score"], _SCORE_HAALAND))


# ===========================================================================
# Section H — ask() raw bootstrap without FDR map: backward compat
# ===========================================================================
_section("H: ask() with raw bootstrap without map — backwards compatible")

_h_result = ask("captain score for Haaland",
                 copy.deepcopy(_BOOTSTRAP_BASE),
                 candidate_inputs={"fixture_difficulty": 4})

ok("H1  no context_meta key",       "context_meta" not in _h_result)
ok("H2  raw_output status ok",      _h_result["raw_output"]["status"] == "ok")
ok("H3  score computed with explicit FDR=4",
   approx_equal(_h_result["raw_output"]["captain_score"], _SCORE_HAALAND))


# ===========================================================================
# Section I — Unrecognised query: context_meta present when ctx passed
# ===========================================================================
_section("I: Unrecognised query — context_meta present/absent correctly")

_ctx_i = _make_ctx()
_i_ctx_result = ask("something completely unrelated", _ctx_i)
ok("I1  unrecognised with ctx: context_meta still present",
   "context_meta" in _i_ctx_result)
ok("I2  unrecognised with ctx: selected_tool is None",
   _i_ctx_result["selected_tool"] is None)
ok("I3  unrecognised with ctx: raw_output code is unrecognised_query",
   _i_ctx_result["raw_output"]["code"] == "unrecognised_query")

_i_raw_result = ask("something completely unrelated", copy.deepcopy(_BOOTSTRAP_WITH_MAP))
ok("I4  unrecognised with raw bootstrap: context_meta absent",
   "context_meta" not in _i_raw_result)
ok("I5  unrecognised with raw bootstrap: selected_tool is None",
   _i_raw_result["selected_tool"] is None)


# ===========================================================================
# Section J — candidate_inputs override still works with assembled context
# ===========================================================================
_section("J: candidate_inputs override with assembled context")

_ctx_j = _make_ctx()
# Force FDR=2 (easy fixture) for Haaland via explicit override
_j_result = ask(
    "captain score for Haaland",
    _ctx_j,
    candidate_inputs={"fixture_difficulty": 2},
)

ok("J1  status ok",                 _j_result["raw_output"]["status"] == "ok")
ok("J2  context_meta present",      "context_meta" in _j_result)
# With FDR=2: fixture_score=(6-2)*20=80; score = 80*0.4 + 80*0.3 + 4.25*0.2 + 100*0.1
# = 32 + 24 + 0.85 + 10 = 66.85
ok("J3  explicit FDR override applied (score differs from default)",
   not approx_equal(_j_result["raw_output"]["captain_score"], _SCORE_HAALAND))
ok("J4  overridden score is higher (FDR=2 is easier than FDR=4)",
   _j_result["raw_output"]["captain_score"] > _SCORE_HAALAND)


# ===========================================================================
# Section K — candidates_list override still works with assembled context
# ===========================================================================
_section("K: candidates_list with assembled context")

_ctx_k = _make_ctx()
_k_result = ask(
    "rank my captain candidates",
    _ctx_k,
    candidates_list=[
        {"query": "Salah",   "fixture_difficulty": 2},  # explicit override
        {"query": "Haaland"},                            # auto-derived
    ],
)

ok("K1  status ok",                 _k_result["raw_output"]["status"] == "ok")
ok("K2  context_meta present",      "context_meta" in _k_result)
ok("K3  2 entries returned",
   _k_result["raw_output"]["total"] == 2)
_k_ranked = [r for r in _k_result["raw_output"]["ranked_candidates"]
             if r.get("status") == "ok"]
ok("K4  both entries ok",           len(_k_ranked) == 2)
# Salah with FDR=2 (easier) should beat Haaland with FDR=4
ok("K5  Salah (FDR=2 override) ranks first",
   _k_ranked[0]["web_name"] == "Salah")


# ===========================================================================
# Section L — Blank-GW team safety preserved with assembled context
# ===========================================================================
_section("L: Blank-GW team safety — assembled context")

_ctx_l = _make_ctx()

ok("L1  Man Utd in meta blank_gw_teams",
   11 in _ctx_l["meta"]["blank_gw_teams"])

# Johnson on Man Utd → blank GW → FDR cannot be auto-derived → error
_l_error = ask("captain score for Johnson", _ctx_l)
ok("L2  blank-GW player returns error (not crash)",
   isinstance(_l_error, dict))
ok("L3  status is error (missing FDR)",
   _l_error["raw_output"]["status"] == "error")
ok("L4  context_meta still present even on error response",
   "context_meta" in _l_error)
ok("L5  blank_gw_teams accessible from error result meta",
   11 in _l_error["context_meta"]["blank_gw_teams"])


# ===========================================================================
# Section M — Safety regression: ambiguous / not_found unchanged
# ===========================================================================
_section("M: Safety regression — ambiguous and not_found")

# Use an assembled context with two Johnsons to test ambiguity
_AMBIGUOUS_ELEMENTS = [
    *_ELEMENTS,
    {"id": 7, "first_name": "Adam", "second_name": "Johnson",
     "web_name": "Johnson", "team": 8, "team_code": 8, "element_type": 3,
     "status": "a", "now_cost": 50, "selected_by_percent": "0.5",
     "form": "2.0", "expected_goals": "0.10", "expected_assists": "0.05",
     "expected_goal_involvements": "0.15", "minutes": 450},
]
_AMBIGUOUS_BS = {
    "elements":               _AMBIGUOUS_ELEMENTS,
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}
_ctx_m_ambiguous = assemble_captain_context(
    bootstrap=_AMBIGUOUS_BS,
    fixtures=_FIXTURES_GW28,
)

_m_ambiguous = ask("captain score for Johnson", _ctx_m_ambiguous)
ok("M1  ambiguous returns ambiguous status",
   _m_ambiguous["raw_output"]["status"] == "ambiguous")
ok("M2  no captain_score key in ambiguous output",
   "captain_score" not in _m_ambiguous["raw_output"])
ok("M3  context_meta present even in ambiguous result",
   "context_meta" in _m_ambiguous)

# not_found
_ctx_m_notfound = _make_ctx()
_m_notfound = ask("captain score for Rashford", _ctx_m_notfound)
ok("M4  not_found returns not_found status",
   _m_notfound["raw_output"]["status"] == "not_found")
ok("M5  no captain_score in not_found output",
   "captain_score" not in _m_notfound["raw_output"])
ok("M6  context_meta present even in not_found result",
   "context_meta" in _m_notfound)


# ===========================================================================
# Section N — Phase 2e regression: assemble_captain_context + ask(ctx) e2e
# ===========================================================================
_section("N: Phase 2e regression — assemble_captain_context + ask(ctx)")

# This reproduces the exact Phase 2e workflow but using ask(ctx) instead of ask(ctx["bootstrap"])
_ctx_n = assemble_captain_context(
    bootstrap=copy.deepcopy(_BOOTSTRAP_BASE),
    fixtures=_FIXTURES_GW28,
)

_n_haaland = ask("captain score for Haaland", _ctx_n)
_n_salah   = ask("captain score for Salah",   _ctx_n)

ok("N1  Haaland status ok",         _n_haaland["raw_output"]["status"] == "ok")
ok("N2  Haaland score unchanged",
   approx_equal(_n_haaland["raw_output"]["captain_score"], _SCORE_HAALAND))
ok("N3  Salah status ok",           _n_salah["raw_output"]["status"] == "ok")
ok("N4  Salah score unchanged",
   approx_equal(_n_salah["raw_output"]["captain_score"], _SCORE_SALAH))
ok("N5  context_meta present in Haaland result", "context_meta" in _n_haaland)
ok("N6  context_meta present in Salah result",   "context_meta" in _n_salah)
ok("N7  context_meta is same meta object",
   _n_haaland["context_meta"] is _n_salah["context_meta"])


# ===========================================================================
# Section O — Phase 2d regression: scores unchanged with raw bootstrap
# ===========================================================================
_section("O: Phase 2d regression — raw bootstrap pass-through unchanged")

_bs_o = copy.deepcopy(_BOOTSTRAP_WITH_MAP)
_o_h = ask("captain score for Haaland",  _bs_o)
_o_s = ask("captain score for Salah",    _bs_o)
_o_k = ask("captain score for Saka",     _bs_o)
_o_d = ask("captain score for De Bruyne", _bs_o)

ok("O1  Haaland score unchanged",
   approx_equal(_o_h["raw_output"]["captain_score"], _SCORE_HAALAND))
ok("O2  Salah score unchanged",
   approx_equal(_o_s["raw_output"]["captain_score"], _SCORE_SALAH))
ok("O3  Saka score unchanged",
   approx_equal(_o_k["raw_output"]["captain_score"], _SCORE_SAKA))
ok("O4  De Bruyne score unchanged",
   approx_equal(_o_d["raw_output"]["captain_score"], _SCORE_DEBRUYNE))
ok("O5  no context_meta in raw-bootstrap results",
   "context_meta" not in _o_h
   and "context_meta" not in _o_s
   and "context_meta" not in _o_k
   and "context_meta" not in _o_d)


# ===========================================================================
# Section P — Interface report: what changed vs what is preserved
# ===========================================================================
_section("P: Interface report — what changed vs what is preserved")

# Parameter name preserved (keyword callers still work)
_p_kw = ask(
    question="captain score for Salah",
    bootstrap=copy.deepcopy(_BOOTSTRAP_WITH_MAP),
)
ok("P1  keyword arg 'bootstrap=' still accepted",
   _p_kw["raw_output"]["status"] == "ok")

# Positional call with assembled context works
_ctx_p = _make_ctx()
_p_pos = ask("captain score for Salah", _ctx_p)
ok("P2  positional call with assembled context works",
   _p_pos["raw_output"]["status"] == "ok")

# Return dict still has the same 4 keys as before when raw bootstrap passed
_p_raw_keys = set(ask("captain score for Salah",
                       copy.deepcopy(_BOOTSTRAP_WITH_MAP)).keys())
ok("P3  raw bootstrap result has exactly 4 core keys",
   _p_raw_keys == {"selected_tool", "tool_input", "raw_output", "answer_text"})

# Return dict gains 5th key when assembled context passed
_p_ctx_keys = set(ask("captain score for Salah", _make_ctx()).keys())
ok("P4  assembled context result has 5 keys (adds context_meta)",
   _p_ctx_keys == {"selected_tool", "tool_input", "raw_output", "answer_text",
                   "context_meta"})

# No assembly logic in harness (harness does not import assemble_captain_context)
import fpl_grounded_assistant.harness as _h_mod
ok("P5  harness module does not import fpl_pipeline (no assembly logic inside)",
   not hasattr(_h_mod, "assemble_captain_context")
   and "fpl_pipeline" not in getattr(_h_mod, "__file__", ""))

# _is_assembled_context is exported (testable)
ok("P6  _is_assembled_context accessible from harness module",
   callable(_h_mod._is_assembled_context))

# _resolve_bootstrap_and_meta is exported (testable)
ok("P7  _resolve_bootstrap_and_meta accessible from harness module",
   callable(_h_mod._resolve_bootstrap_and_meta))


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'=' * 52}")
print(f"Phase 2f — Results: {_passed} passed, {_failed} failed")
print(f"{'=' * 52}")

if _failed == 0:
    print("\nAll assertions PASS.")
else:
    print(f"\n{_failed} assertion(s) FAILED — see FAIL lines above.")
    sys.exit(1)


