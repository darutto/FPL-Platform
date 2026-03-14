"""
run_phase2b_tests.py
=====================
Standalone validator for Phase 2b:
  - Formula deduplication: fpl_captain_engine.calculate_captain_score is the
    canonical source; tool contract uses it directly (no inline copy).
  - Parity: all Phase 2a numeric results are bit-for-bit identical via the
    canonical path.
  - Centralised candidate_inputs validation: structured errors for missing /
    incomplete inputs, consistent across tool_get_captain_score and
    tool_rank_captain_candidates.
  - top-N rankings: tool_rank_captain_candidates scores, ranks, and returns
    a sorted list; partial failures are included at the end.
  - End-to-end: ranking questions route and render through ask().

No pytest required — plain Python asserts only.
Run from the fpl-grounded-assistant package directory::

    python run_phase2b_tests.py

All sibling packages must be on sys.path (see path setup below).

Formula verification (Phase 2b parity cross-check)
----------------------------------------------------
Canonical engine produces unrounded floats; tool layer adds round(..., 2).

Haaland: form=8.0, fdr=2, xgi=1.7, risk=5.0
  form_score    = (8.0/10)*100 = 80.0
  fixture_score = (6-2)*20     = 80.0
  xgi_score     = 1.7*50       = 85.0
  minutes_score = 100-5        = 95.0
  raw total     = 80*0.4 + 80*0.3 + 85*0.2 + 95*0.1 = 82.5
  rounded       = 82.5

Salah: form=9.5, fdr=2, xgi=1.45, risk=5.0
  form_score    = (9.5/10)*100 = 95.0
  fixture_score = (6-2)*20     = 80.0
  xgi_score     = 1.45*50      = 72.5
  minutes_score = 100-5        = 95.0
  raw total     = 95*0.4 + 80*0.3 + 72.5*0.2 + 95*0.1
                = 38 + 24 + 14.5 + 9.5 = 86.0
  rounded       = 86.0

Saka: form=5.5, fdr=3, xgi=0.85, risk=20.0
  form_score    = (5.5/10)*100 = 55.0
  fixture_score = (6-3)*20     = 60.0
  xgi_score     = 0.85*50      = 42.5
  minutes_score = 100-20       = 80.0
  raw total     = 55*0.4 + 60*0.3 + 42.5*0.2 + 80*0.1
                = 22 + 18 + 8.5 + 8 = 56.5
  rounded       = 56.5
"""
from __future__ import annotations

import copy
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
for _sibling in (
    "fpl-data-core",
    "fpl-api-client",
    "fpl-player-registry",
    "fpl-query-tools",
    "fpl-tool-contract",
    "fpl-tool-runner",
    "fpl-captain-engine/python",
):
    _p = (_HERE.parent / _sibling).resolve()
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ---------------------------------------------------------------------------
# Shared bootstrap fixture (same as conftest.py)
# ---------------------------------------------------------------------------
_RAW_ELEMENTS = [
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
]
_TEAMS = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12},
]
_EVENTS = [
    {"id": 27, "is_current": False, "is_next": False, "finished": True},
    {"id": 28, "is_current": True,  "is_next": False, "finished": False},
    {"id": 29, "is_current": False, "is_next": True,  "finished": False},
]
BOOTSTRAP = {
    "elements":      _RAW_ELEMENTS,
    "teams":         _TEAMS,
    "events":        _EVENTS,
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
}
BS = copy.deepcopy(BOOTSTRAP)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from fpl_captain_engine import calculate_captain_score                 # canonical
from fpl_tool_contract import tool_get_captain_score, tool_rank_captain_candidates
from fpl_tool_runner import run_tool, TOOL_SPECS
from fpl_grounded_assistant.router import route
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.harness import ask

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
_pass = 0
_fail = 0
_errors: list[str] = []

def check(label: str, condition: bool) -> None:
    global _pass, _fail
    if condition:
        _pass += 1
    else:
        _fail += 1
        _errors.append(f"FAIL: {label}")
        print(f"  FAIL: {label}")


# ===========================================================================
# Section A — Formula parity: canonical engine vs. tool contract
# ===========================================================================
print("\n=== A: Formula parity (engine vs. tool contract) ===")

# A1 — Haaland parity: raw engine (unrounded) then round matches tool output
_haaland_raw = calculate_captain_score(8.0, 2, 1.7, 5.0)
check("A1: engine produces 82.5 before rounding", _haaland_raw == 82.5)

_haaland_tool = tool_get_captain_score(
    "Haaland", BS,
    {"form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 1.7, "minutes_risk": 5.0},
)
check("A2: tool produces 82.5 (round of engine)", _haaland_tool["captain_score"] == 82.5)
check("A3: engine==tool after round", round(_haaland_raw, 2) == _haaland_tool["captain_score"])

# A4 — Salah parity
_salah_raw = calculate_captain_score(9.5, 2, 1.45, 5.0)
check("A4: engine Salah = 86.0", _salah_raw == 86.0)
_salah_tool = tool_get_captain_score(
    "Salah", BS,
    {"form": 9.5, "fixture_difficulty": 2, "xgi_per_90": 1.45, "minutes_risk": 5.0},
)
check("A5: tool Salah = 86.0", _salah_tool["captain_score"] == 86.0)
check("A6: engine==tool Salah", round(_salah_raw, 2) == _salah_tool["captain_score"])

# A7 — Saka parity
_saka_raw = calculate_captain_score(5.5, 3, 0.85, 20.0)
check("A7: engine Saka = 56.5", _saka_raw == 56.5)
_saka_tool = tool_get_captain_score(
    "Saka", BS,
    {"form": 5.5, "fixture_difficulty": 3, "xgi_per_90": 0.85, "minutes_risk": 20.0},
)
check("A8: tool Saka = 56.5", _saka_tool["captain_score"] == 56.5)

# A9 — Edge: FDR=1 (easiest), max fixture score
_max_fixture_raw = calculate_captain_score(0.0, 1, 0.0, 0.0)
check("A9: engine FDR=1,form=0,xgi=0,risk=0 = 30.0",
      _max_fixture_raw == 30.0)

# A10 — Edge: FDR=5 (hardest), 0 fixture score
_hardest_raw = calculate_captain_score(10.0, 5, 2.0, 0.0)
check("A10: engine FDR=5,form=10,xgi=2,risk=0 = 0*0.3+100*0.4+100*0.2+100*0.1=70.0",
      _hardest_raw == 70.0)

# A11 — Rounding: a value that needs rounding (form=3.333)
_rounded_raw = calculate_captain_score(3.333, 3, 0.666, 50.0)
_rounded_tool = tool_get_captain_score(
    "Saka", BS,
    {"form": 3.333, "fixture_difficulty": 3, "xgi_per_90": 0.666, "minutes_risk": 50.0},
)
check("A11: tool rounds to 2dp", _rounded_tool["captain_score"] == round(_rounded_raw, 2))


# ===========================================================================
# Section B — Centralised candidate_inputs validation
# ===========================================================================
print("\n=== B: candidate_inputs validation ===")

# B1 — None inputs
_b1 = tool_get_captain_score("Haaland", BS, None)   # type: ignore[arg-type]
check("B1: None inputs → status=error", _b1["status"] == "error")
check("B2: None inputs → code=missing_argument", _b1["code"] == "missing_argument")

# B3 — Empty dict
_b3 = tool_get_captain_score("Haaland", BS, {})
check("B3: empty dict → status=error", _b3["status"] == "error")
check("B4: empty dict → code=missing_argument", _b3["code"] == "missing_argument")

# B5 — Missing single key
_b5 = tool_get_captain_score(
    "Haaland", BS,
    {"form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 1.7},  # missing minutes_risk
)
check("B5: missing minutes_risk → status=error", _b5["status"] == "error")
check("B6: missing minutes_risk → code=missing_argument", _b5["code"] == "missing_argument")
check("B7: missing key named in message",
      "minutes_risk" in _b5.get("message", ""))

# B8 — Valid inputs after validation
_b8 = tool_get_captain_score(
    "Haaland", BS,
    {"form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 1.7, "minutes_risk": 5.0},
)
check("B8: valid inputs → status=ok", _b8["status"] == "ok")

# B9 — Validation runs before resolution: bad inputs + non-existent player → error, not not_found
_b9 = tool_get_captain_score("Cantona", BS, {})
check("B9: bad inputs + bad player → error (not not_found)", _b9["status"] == "error")


# ===========================================================================
# Section C — tool_get_captain_score parity with Phase 2a values
# ===========================================================================
print("\n=== C: tool_get_captain_score parity with Phase 2a ===")

_c_haaland = tool_get_captain_score(
    "Haaland", BS,
    {"form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 1.7, "minutes_risk": 5.0},
)
check("C1: Haaland score=82.5 (Phase 2a parity)", _c_haaland["captain_score"] == 82.5)
check("C2: Haaland web_name preserved", _c_haaland["web_name"] == "Haaland")
check("C3: Haaland score_inputs intact",
      _c_haaland["score_inputs"]["form"] == 8.0
      and _c_haaland["score_inputs"]["fixture_difficulty"] == 2)

_c_salah = tool_get_captain_score(
    "Salah", BS,
    {"form": 9.5, "fixture_difficulty": 2, "xgi_per_90": 1.45, "minutes_risk": 5.0},
)
check("C4: Salah score=86.0 (Phase 2a parity)", _c_salah["captain_score"] == 86.0)

# Haaland FDR=3 parity
_c_h_hard = tool_get_captain_score(
    "Haaland", BS,
    {"form": 8.0, "fixture_difficulty": 3, "xgi_per_90": 1.7, "minutes_risk": 5.0},
)
check("C5: Haaland FDR=3 → 76.5 (Phase 2a parity)", _c_h_hard["captain_score"] == 76.5)

# C6 — ambiguous still safe
_c_amb = tool_get_captain_score(
    "Johnson", BS,
    {"form": 5.0, "fixture_difficulty": 2, "xgi_per_90": 0.5, "minutes_risk": 10.0},
)
check("C6: Johnson ambiguous → status=ambiguous", _c_amb["status"] == "ambiguous")
check("C7: Johnson ambiguous → no captain_score key",
      "captain_score" not in _c_amb)

# C8 — not_found still safe
_c_nf = tool_get_captain_score(
    "Cantona", BS,
    {"form": 5.0, "fixture_difficulty": 2, "xgi_per_90": 0.5, "minutes_risk": 10.0},
)
check("C8: Cantona not_found → status=not_found", _c_nf["status"] == "not_found")


# ===========================================================================
# Section D — tool_rank_captain_candidates contract
# ===========================================================================
print("\n=== D: tool_rank_captain_candidates contract ===")

_three_candidates = [
    {"query": "Salah",   "form": 9.5, "fixture_difficulty": 2,
     "xgi_per_90": 1.45, "minutes_risk": 5.0},
    {"query": "Haaland", "form": 8.0, "fixture_difficulty": 2,
     "xgi_per_90": 1.7,  "minutes_risk": 5.0},
    {"query": "Saka",    "form": 5.5, "fixture_difficulty": 3,
     "xgi_per_90": 0.85, "minutes_risk": 20.0},
]

_d_result = tool_rank_captain_candidates(_three_candidates, BS)
check("D1: 3-candidate ranking → status=ok", _d_result["status"] == "ok")
check("D2: total=3", _d_result["total"] == 3)
check("D3: error_count=0", _d_result["error_count"] == 0)
check("D4: 3 entries in ranked_candidates",
      len(_d_result["ranked_candidates"]) == 3)

# D5 — Correct order: Salah(86.0) > Haaland(82.5) > Saka(56.5)
_ranks = _d_result["ranked_candidates"]
check("D5: rank1 is Salah", _ranks[0]["web_name"] == "Salah")
check("D6: rank1 score=86.0", _ranks[0]["captain_score"] == 86.0)
check("D7: rank2 is Haaland", _ranks[1]["web_name"] == "Haaland")
check("D8: rank2 score=82.5", _ranks[1]["captain_score"] == 82.5)
check("D9: rank3 is Saka", _ranks[2]["web_name"] == "Saka")
check("D10: rank3 score=56.5", _ranks[2]["captain_score"] == 56.5)

# D11 — rank fields set correctly
check("D11: rank fields 1/2/3",
      _ranks[0]["rank"] == 1
      and _ranks[1]["rank"] == 2
      and _ranks[2]["rank"] == 3)

# D12 — index fields preserve original positions
check("D12: index fields 0/1/2",
      _ranks[0]["index"] == 0
      and _ranks[1]["index"] == 1
      and _ranks[2]["index"] == 2)

# D13 — score_inputs present
check("D13: score_inputs present on rank1",
      "score_inputs" in _ranks[0]
      and _ranks[0]["score_inputs"]["fixture_difficulty"] == 2)

# D14 — Partial failures included at end
_with_failure = [
    {"query": "Haaland", "form": 8.0, "fixture_difficulty": 2,
     "xgi_per_90": 1.7, "minutes_risk": 5.0},
    {"query": "Cantona",  "form": 5.0, "fixture_difficulty": 2,
     "xgi_per_90": 0.5,  "minutes_risk": 10.0},
    {"query": "Johnson",  "form": 5.0, "fixture_difficulty": 2,
     "xgi_per_90": 0.5,  "minutes_risk": 10.0},
]
_d14 = tool_rank_captain_candidates(_with_failure, BS)
check("D14: partial failures → status=ok", _d14["status"] == "ok")
check("D15: total=1 (only Haaland resolved)", _d14["total"] == 1)
check("D16: error_count=2 (Cantona+Johnson)", _d14["error_count"] == 2)
check("D17: 3 total entries in ranked_candidates",
      len(_d14["ranked_candidates"]) == 3)
check("D18: first entry is Haaland (ok)", _d14["ranked_candidates"][0]["status"] == "ok")
check("D19: non-ok entries follow ok entries",
      all(e["status"] != "ok" for e in _d14["ranked_candidates"][1:]))

# D20 — Cantona entry is not_found
_cantona_entry = next(
    (e for e in _d14["ranked_candidates"] if e.get("query") == "Cantona"), None
)
check("D20: Cantona entry is not_found",
      _cantona_entry is not None and _cantona_entry["status"] == "not_found")

# D21 — Johnson entry is ambiguous
_johnson_entry = next(
    (e for e in _d14["ranked_candidates"] if e.get("query") == "Johnson"), None
)
check("D21: Johnson entry is ambiguous",
      _johnson_entry is not None and _johnson_entry["status"] == "ambiguous")

# D22 — Empty list → error
_d22 = tool_rank_captain_candidates([], BS)
check("D22: empty list → status=error", _d22["status"] == "error")
check("D23: empty list → code=missing_argument", _d22["code"] == "missing_argument")

# D24 — Missing query in candidate
_d24 = tool_rank_captain_candidates(
    [{"form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 1.7, "minutes_risk": 5.0}],
    BS,
)
check("D24: candidate missing query → status=ok, error_count=1",
      _d24["status"] == "ok" and _d24["error_count"] == 1)

# D25 — Candidate missing scoring input
_d25 = tool_rank_captain_candidates(
    [{"query": "Haaland", "form": 8.0, "fixture_difficulty": 2, "xgi_per_90": 1.7}],
    BS,
)
check("D25: missing minutes_risk → error_count=1",
      _d25["error_count"] == 1)

# D26 — Single candidate, all valid
_d26 = tool_rank_captain_candidates(
    [{"query": "Salah", "form": 9.5, "fixture_difficulty": 2,
      "xgi_per_90": 1.45, "minutes_risk": 5.0}],
    BS,
)
check("D26: single valid candidate → rank=1, score=86.0",
      _d26["total"] == 1
      and _d26["ranked_candidates"][0]["rank"] == 1
      and _d26["ranked_candidates"][0]["captain_score"] == 86.0)


# ===========================================================================
# Section E — Runner dispatch for rank_captain_candidates
# ===========================================================================
print("\n=== E: Runner dispatch for rank_captain_candidates ===")

# E1 — Tool is registered
_e_registry_names = run_tool.__module__   # just checking we can import
from fpl_tool_runner import TOOL_REGISTRY
check("E1: rank_captain_candidates registered",
      "rank_captain_candidates" in TOOL_REGISTRY.list_tools())

# E2 — 5 tools total
check("E2: 5 tools in TOOL_SPECS", len(TOOL_SPECS) == 5)

# E3 — run_tool dispatch
_e3 = run_tool(
    "rank_captain_candidates",
    {"candidates": [
        {"query": "Haaland", "form": 8.0, "fixture_difficulty": 2,
         "xgi_per_90": 1.7, "minutes_risk": 5.0},
        {"query": "Salah",   "form": 9.5, "fixture_difficulty": 2,
         "xgi_per_90": 1.45, "minutes_risk": 5.0},
    ]},
    BS,
)
check("E3: run_tool rank → status=ok", _e3["status"] == "ok")
check("E4: run_tool rank → total=2", _e3["total"] == 2)
check("E5: run_tool rank → Salah ranks 1st",
      _e3["ranked_candidates"][0]["web_name"] == "Salah")

# E6 — Missing 'candidates' arg → error
_e6 = run_tool("rank_captain_candidates", {}, BS)
check("E6: missing candidates arg → status=error", _e6["status"] == "error")
check("E7: missing candidates arg → code=missing_argument",
      _e6["code"] == "missing_argument")


# ===========================================================================
# Section F — Renderer for rank_captain_candidates
# ===========================================================================
print("\n=== F: Renderer for rank_captain_candidates ===")

# F1 — ok result renders ranked list
_f1_raw = tool_rank_captain_candidates(_three_candidates, BS)
_f1_text = render("rank_captain_candidates", _f1_raw)
check("F1: ok renders non-empty string", len(_f1_text) > 0)
check("F2: ok renders Salah in first position",
      "Salah" in _f1_text)
check("F3: ok renders score 86.0",
      "86.0" in _f1_text)
check("F4: ok renders ranking header", "ranked" in _f1_text.lower() or "Captain" in _f1_text)

# F5 — error (empty list) renders graceful message
_f5_raw = tool_rank_captain_candidates([], BS)
_f5_text = render("rank_captain_candidates", _f5_raw)
check("F5: empty list renders non-empty error string", len(_f5_text) > 0)
check("F6: empty list references missing_argument",
      "candidate" in _f5_text.lower() or "missing" in _f5_text.lower())

# F7 — partial failure mentions unresolved count
_f7_raw = tool_rank_captain_candidates(_with_failure, BS)
_f7_text = render("rank_captain_candidates", _f7_raw)
check("F7: partial failures noted in render text",
      "could not be resolved" in _f7_text or "2" in _f7_text)

# F8 — single candidate ranked and rendered
_f8_raw = tool_rank_captain_candidates(
    [{"query": "Haaland", "form": 8.0, "fixture_difficulty": 2,
      "xgi_per_90": 1.7, "minutes_risk": 5.0}],
    BS,
)
_f8_text = render("rank_captain_candidates", _f8_raw)
check("F8: single candidate render contains '1.'", "1." in _f8_text)
check("F9: single candidate render contains Haaland", "Haaland" in _f8_text)


# ===========================================================================
# Section G — Harness e2e for rank_captain_candidates
# ===========================================================================
print("\n=== G: Harness e2e for rank_captain_candidates ===")

_g_candidates = [
    {"query": "Salah",   "form": 9.5, "fixture_difficulty": 2,
     "xgi_per_90": 1.45, "minutes_risk": 5.0},
    {"query": "Haaland", "form": 8.0, "fixture_difficulty": 2,
     "xgi_per_90": 1.7,  "minutes_risk": 5.0},
    {"query": "Saka",    "form": 5.5, "fixture_difficulty": 3,
     "xgi_per_90": 0.85, "minutes_risk": 20.0},
]

# G1 — "top captains" question routes correctly
_g1_route = route("top captains this week")
check("G1: 'top captains this week' routes to rank_captain_candidates",
      _g1_route is not None and _g1_route.tool_name == "rank_captain_candidates")

# G2 — "captain rankings" routes correctly
_g2_route = route("captain rankings")
check("G2: 'captain rankings' routes to rank_captain_candidates",
      _g2_route is not None and _g2_route.tool_name == "rank_captain_candidates")

# G3 — "rank candidates" routes correctly
_g3_route = route("rank captain candidates")
check("G3: 'rank captain candidates' routes correctly",
      _g3_route is not None and _g3_route.tool_name == "rank_captain_candidates")

# G4 — "who are the top captains" routes correctly
_g4_route = route("who are the top captains")
check("G4: 'who are the top captains' routes correctly",
      _g4_route is not None and _g4_route.tool_name == "rank_captain_candidates")

# G5 — ask() with candidates_list
_g5 = ask("top captains this week", BS, candidates_list=_g_candidates)
check("G5: ask() selected_tool = rank_captain_candidates",
      _g5["selected_tool"] == "rank_captain_candidates")
check("G6: ask() raw_output status=ok", _g5["raw_output"]["status"] == "ok")
check("G7: ask() total=3", _g5["raw_output"]["total"] == 3)
check("G8: ask() answer_text non-empty", len(_g5["answer_text"]) > 0)
check("G9: ask() answer_text mentions Salah", "Salah" in _g5["answer_text"])

# G10 — ask() without candidates_list → graceful degradation
_g10 = ask("top captains this week", BS)
check("G10: ask() without candidates_list → selected_tool still rank",
      _g10["selected_tool"] == "rank_captain_candidates")
check("G11: ask() without candidates_list → raw_output status=error",
      _g10["raw_output"]["status"] == "error")
check("G12: ask() without candidates_list → answer_text references candidate",
      "candidate" in _g10["answer_text"].lower())

# G13 — ranking intent does NOT trigger on single-player captain score question
_g13_route = route("should I captain Haaland")
check("G13: 'should I captain Haaland' routes to get_captain_score (not rank)",
      _g13_route is not None and _g13_route.tool_name == "get_captain_score")

# G14 — Ranking intent with "rank my captains"
_g14_route = route("rank my captains")
check("G14: 'rank my captains' routes to rank_captain_candidates",
      _g14_route is not None and _g14_route.tool_name == "rank_captain_candidates")


# ===========================================================================
# Section H — Safety regression (Phase 2a guarantees intact)
# ===========================================================================
print("\n=== H: Safety regression ===")

# H1 — ambiguous query for captain score
_h1 = ask("should I captain Johnson",
          BS,
          candidate_inputs={"form": 5.0, "fixture_difficulty": 2,
                            "xgi_per_90": 0.5, "minutes_risk": 10.0})
check("H1: Johnson captain score → ambiguous",
      _h1["raw_output"]["status"] == "ambiguous")
check("H2: Johnson answer has no cost/ownership",
      "£" not in _h1["answer_text"] and "%" not in _h1["answer_text"])

# H3 — not_found query for captain score
_h3 = ask("captain score for Cantona",
          BS,
          candidate_inputs={"form": 5.0, "fixture_difficulty": 2,
                            "xgi_per_90": 0.5, "minutes_risk": 10.0})
check("H3: Cantona captain score → not_found",
      _h3["raw_output"]["status"] == "not_found")

# H4 — Johnson resolution: ambiguous via direct tool
_h4 = tool_get_captain_score(
    "Johnson", BS,
    {"form": 5.0, "fixture_difficulty": 2, "xgi_per_90": 0.5, "minutes_risk": 10.0},
)
check("H4: tool_get_captain_score Johnson → ambiguous", _h4["status"] == "ambiguous")
check("H5: no data leaked in ambiguous response", "captain_score" not in _h4)

# H6 — ranking question answer_text contains no "£" (no data leak on error entries)
_h6 = ask("top captains this week", BS, candidates_list=_with_failure)
check("H6: partial-failure ranking answer has no cost data",
      "£" not in _h6["answer_text"])


# ===========================================================================
# Section I — Phase 2a regression (all prior Phase 2a assertions must hold)
# ===========================================================================
print("\n=== I: Phase 2a regression ===")

# I1 — resolve_player still works
_i1 = run_tool("resolve_player", {"query": "Haaland"}, BS)
check("I1: resolve_player Haaland ok", _i1["status"] == "ok")

# I2 — get_player_summary still works
_i2 = run_tool("get_player_summary", {"query": "Salah"}, BS)
check("I2: get_player_summary Salah ok", _i2["status"] == "ok")
check("I3: get_player_summary Salah cost_m present", "cost_m" in _i2)

# I4 — gameweek still works
_i4 = run_tool("get_current_gameweek", {}, BS)
check("I4: get_current_gameweek ok", _i4["status"] == "ok")
check("I5: gameweek=28", _i4["gameweek"] == 28)

# I6 — captain score ask() e2e still works
_i6 = ask(
    "captain score for Haaland", BS,
    candidate_inputs={"form": 8.0, "fixture_difficulty": 2,
                      "xgi_per_90": 1.7, "minutes_risk": 5.0},
)
check("I6: captain score e2e ok", _i6["raw_output"]["status"] == "ok")
check("I7: captain score e2e score=82.5", _i6["raw_output"]["captain_score"] == 82.5)

# I8 — KDB alias still works
_i8 = ask("who is KDB", BS)
check("I8: KDB alias resolves ok", _i8["raw_output"]["status"] == "ok")
check("I9: KDB resolves to De Bruyne", _i8["raw_output"]["web_name"] == "De Bruyne")

# I10 — casing preserved
_i10 = ask("Who is Salah", BS)
check("I10: query casing preserved in output",
      _i10["raw_output"].get("query") == "Salah")

# I11 — unrecognised query still returns sentinel
_i11 = ask("Is the moon made of cheese?", BS)
check("I11: unrecognised query → selected_tool=None", _i11["selected_tool"] is None)


# ===========================================================================
# Section J — Schema contract for rank_captain_candidates spec
# ===========================================================================
print("\n=== J: Schema contract for RANK_CAPTAIN_CANDIDATES_SPEC ===")

from fpl_tool_runner import RANK_CAPTAIN_CANDIDATES_SPEC

check("J1: spec name = rank_captain_candidates",
      RANK_CAPTAIN_CANDIDATES_SPEC.name == "rank_captain_candidates")
check("J2: spec parameters type = object",
      RANK_CAPTAIN_CANDIDATES_SPEC.parameters["type"] == "object")
check("J3: spec required includes 'candidates'",
      "candidates" in RANK_CAPTAIN_CANDIDATES_SPEC.parameters.get("required", []))
check("J4: candidates param is array",
      RANK_CAPTAIN_CANDIDATES_SPEC.parameters["properties"]["candidates"]["type"] == "array")

_j_openai = RANK_CAPTAIN_CANDIDATES_SPEC.to_openai()
check("J5: to_openai() has type=function",
      _j_openai.get("type") == "function")
check("J6: to_openai() function.name correct",
      _j_openai["function"]["name"] == "rank_captain_candidates")

_j_anthropic = RANK_CAPTAIN_CANDIDATES_SPEC.to_anthropic()
check("J7: to_anthropic() has input_schema",
      "input_schema" in _j_anthropic)
check("J8: to_anthropic() name correct",
      _j_anthropic["name"] == "rank_captain_candidates")


# ===========================================================================
# Section K — No _calculate_captain_score inline function in tools.py
# ===========================================================================
print("\n=== K: No inline formula duplication ===")

import fpl_tool_contract.tools as _tools_module
check("K1: _calculate_captain_score NOT in tools module",
      not hasattr(_tools_module, "_calculate_captain_score"))
check("K2: calculate_captain_score IS imported from fpl_captain_engine",
      hasattr(_tools_module, "calculate_captain_score"))

# K3 — engine imported under canonical name
from fpl_captain_engine import calculate_captain_score as _canonical
check("K3: tools module uses same function object as fpl_captain_engine",
      _tools_module.calculate_captain_score is _canonical)


# ===========================================================================
# Summary
# ===========================================================================
_total = _pass + _fail
print(f"\n{'='*50}")
print(f"Phase 2b: {_pass}/{_total} PASS")
if _errors:
    print("\nFailed assertions:")
    for e in _errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("All assertions PASS")


