"""
run_phase2a_tests.py
=====================
Standalone validator for Phase 2a:
  - Router robustness (casing fix + new phrasings + captain score intent)
  - Captain scoring tool contract (tool_get_captain_score)
  - Captain scoring tool runner (get_captain_score spec + dispatch)
  - End-to-end grounded assistant (KDB alias, captain score via ask())
  - Safety regression (ambiguous/not_found guarantees intact)

No pytest required — plain Python asserts only.
Run from the fpl-grounded-assistant package directory::

    python run_phase2a_tests.py

All six upstream sibling packages must be on sys.path (see path setup below).

Captain score formula verification
------------------------------------
Haaland with form=8.0, fdr=2, xgi_per_90=1.7, minutes_risk=5.0:
  form_score    = (8.0/10)*100 = 80.0
  fixture_score = (6-2)*20     = 80.0
  xgi_score     = 1.7*50       = 85.0
  minutes_score = 100-5        = 95.0
  total         = 80*0.4 + 80*0.3 + 85*0.2 + 95*0.1
                = 32 + 24 + 17 + 9.5 = 82.5
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
):
    _p = (_HERE.parent / _sibling).resolve()
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ---------------------------------------------------------------------------
# Bootstrap fixture
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
_BOOTSTRAP = {
    "elements": _RAW_ELEMENTS, "teams": _TEAMS, "events": _EVENTS,
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
}

_HAALAND_INPUTS = {
    "form": 8.0, "fixture_difficulty": 2,
    "xgi_per_90": 1.7, "minutes_risk": 5.0,
}  # expected captain_score = 82.5

def _bs():
    return copy.deepcopy(_BOOTSTRAP)


# ---------------------------------------------------------------------------
# Test harness helpers
# ---------------------------------------------------------------------------
_PASSED = 0
_FAILED = 0
_ERRORS: list[str] = []


def check(label: str, condition: bool) -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {label}")
    else:
        _FAILED += 1
        _ERRORS.append(label)
        print(f"  FAIL  {label}")


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# A. Router — casing preservation
# ---------------------------------------------------------------------------
section("A. Router — original casing preserved")

try:
    from fpl_grounded_assistant import route

    r = route("Who is KDB?")
    check("A1  'Who is KDB?' → resolve_player",    r is not None and r.tool_name == "resolve_player")
    check("A2  query preserves 'KDB' (not 'kdb')", r is not None and r.tool_args.get("query") == "KDB")

    r = route("Tell me about De Bruyne")
    check("A3  'De Bruyne' casing preserved",       r is not None and r.tool_args.get("query") == "De Bruyne")

    r = route("Give me a summary for Salah")
    check("A4  'Salah' casing preserved",           r is not None and r.tool_args.get("query") == "Salah")

    r = route("Should I captain Haaland")
    check("A5  captain query casing preserved",     r is not None and r.tool_args.get("query") == "Haaland")

except Exception:
    traceback.print_exc()
    check("A — router import/execution failed", False)


# ---------------------------------------------------------------------------
# B. Router — new phrasings
# ---------------------------------------------------------------------------
section("B. Router — new phrasings")

r = route("Show me stats for Haaland")
check("B1  'show me stats for' → get_player_summary",  r is not None and r.tool_name == "get_player_summary")

r = route("What are the stats for Salah")
check("B2  'what are the stats for' → get_player_summary", r is not None and r.tool_name == "get_player_summary")

r = route("Can you find De Bruyne")
check("B3  'can you find' → resolve_player",           r is not None and r.tool_name == "resolve_player")

r = route("Show me Salah")
check("B4  'show me' (without stats) → resolve_player", r is not None and r.tool_name == "resolve_player")

r = route("Get me a summary of Haaland")
check("B5  'get me a summary of' → get_player_summary", r is not None and r.tool_name == "get_player_summary")


# ---------------------------------------------------------------------------
# C. Router — captain score intent
# ---------------------------------------------------------------------------
section("C. Router — captain score intent detection")

for phrase, label in [
    ("Should I captain Haaland", "should i captain"),
    ("Captain score for Salah",  "captain score for"),
    ("Get captain score for De Bruyne", "get captain score for"),
    ("Captaincy score for Haaland", "captaincy score for"),
]:
    r = route(phrase)
    check(f"C  '{label}' → get_captain_score",
          r is not None and r.tool_name == "get_captain_score")

r = route("Should I captain Haaland")
check("C5  captain intent extracts player query 'Haaland'",
      r is not None and r.tool_args.get("query") == "Haaland")

r = route("Captain score for KDB")
check("C6  'Captain score for KDB' preserves casing 'KDB'",
      r is not None and r.tool_args.get("query") == "KDB")


# ---------------------------------------------------------------------------
# D. Captain score tool contract
# ---------------------------------------------------------------------------
section("D. Captain score tool contract — tool_get_captain_score")

from fpl_tool_contract import tool_get_captain_score

r = tool_get_captain_score("Haaland", _bs(), _HAALAND_INPUTS)
check("D1  ok status",             r["status"] == "ok")
check("D2  player_id == 1",        r["player_id"] == 1)
check("D3  captain_score == 82.5", r["captain_score"] == 82.5)
check("D4  score_inputs present",  isinstance(r.get("score_inputs"), dict))
check("D5  score_inputs complete",
      all(k in r["score_inputs"] for k in ("form", "fixture_difficulty", "xgi_per_90", "minutes_risk")))
check("D6  web_name present",      "web_name" in r)
check("D7  position present",      r["position"] == "FWD")

r = tool_get_captain_score("KDB", _bs(), _HAALAND_INPUTS)
check("D8  KDB alias resolves ok", r["status"] == "ok" and r["player_id"] == 4)

r = tool_get_captain_score("Johnson", _bs(), _HAALAND_INPUTS)
check("D9  ambiguous propagated",  r["status"] == "ambiguous")
check("D10 ambiguous has no score", "captain_score" not in r)

r = tool_get_captain_score("Cantona", _bs(), _HAALAND_INPUTS)
check("D11 not_found propagated",  r["status"] == "not_found")
check("D12 not_found has no score", "captain_score" not in r)


# ---------------------------------------------------------------------------
# E. Captain score tool runner
# ---------------------------------------------------------------------------
section("E. Captain score tool runner — run_tool dispatch")

from fpl_tool_runner import run_tool, TOOL_REGISTRY, TOOL_SPECS, GET_CAPTAIN_SCORE_SPEC

check("E1  get_captain_score in registry",    "get_captain_score" in TOOL_REGISTRY.list_tools())
check("E2  4 tools registered",               len(TOOL_REGISTRY.list_tools()) == 4)
check("E3  TOOL_SPECS has 4 entries",         len(TOOL_SPECS) == 4)
check("E4  GET_CAPTAIN_SCORE_SPEC exported",
      GET_CAPTAIN_SCORE_SPEC is not None and GET_CAPTAIN_SCORE_SPEC.name == "get_captain_score")

captain_args = {"query": "Haaland", **_HAALAND_INPUTS}
r = run_tool("get_captain_score", captain_args, _bs())
check("E5  run_tool ok for Haaland",     r["status"] == "ok")
check("E6  captain_score == 82.5",       r["captain_score"] == 82.5)

captain_args_kdb = {"query": "KDB", **_HAALAND_INPUTS}
r = run_tool("get_captain_score", captain_args_kdb, _bs())
check("E7  run_tool KDB alias ok",       r["status"] == "ok" and r["player_id"] == 4)

r = run_tool("get_captain_score", {"query": "Haaland"}, _bs())
check("E8  missing_argument error",      r["status"] == "error" and r["code"] == "missing_argument")
check("E9  error message names field",   "form" in r["message"])

r = run_tool("get_captain_score", {"query": "Johnson", **_HAALAND_INPUTS}, _bs())
check("E10 ambiguous via runner",        r["status"] == "ambiguous")

# to_openai_tools and to_anthropic_tools should reflect 4 tools
check("E11 to_openai_tools has 4",       len(TOOL_REGISTRY.to_openai_tools()) == 4)
check("E12 to_anthropic_tools has 4",    len(TOOL_REGISTRY.to_anthropic_tools()) == 4)


# ---------------------------------------------------------------------------
# F. End-to-end via ask() — KDB alias
# ---------------------------------------------------------------------------
section("F. End-to-end ask() — KDB alias resolves correctly")

from fpl_grounded_assistant import ask

result = ask("Who is KDB?", _bs())
check("F1  selected_tool == resolve_player",   result["selected_tool"] == "resolve_player")
check("F2  raw_output status == ok",           result["raw_output"]["status"] == "ok")
check("F3  player_id == 4 (De Bruyne)",        result["raw_output"]["player_id"] == 4)
check("F4  answer contains 'De Bruyne'",
      "De Bruyne" in result["answer_text"] or "de bruyne" in result["answer_text"].lower())
check("F5  tool_input query is 'KDB' (original case)",
      result["tool_input"].get("query") == "KDB")


# ---------------------------------------------------------------------------
# G. End-to-end via ask() — captain score
# ---------------------------------------------------------------------------
section("G. End-to-end ask() — captain score")

result = ask("Should I captain Haaland?", _bs(), candidate_inputs=_HAALAND_INPUTS)
check("G1  selected_tool == get_captain_score",   result["selected_tool"] == "get_captain_score")
check("G2  raw_output status == ok",              result["raw_output"]["status"] == "ok")
check("G3  captain_score == 82.5",                result["raw_output"]["captain_score"] == 82.5)
check("G4  answer contains score '82.5'",         "82.5" in result["answer_text"])
check("G5  answer contains team 'MCI'",           "MCI" in result["answer_text"])

# Without candidate_inputs → graceful missing_argument degradation
result = ask("Should I captain Haaland?", _bs())
check("G6  missing inputs → error status",        result["raw_output"]["status"] == "error")
check("G7  missing inputs → answer is helpful",
      "candidate inputs" in result["answer_text"].lower()
      or "match data" in result["answer_text"].lower()
      or "form" in result["answer_text"].lower())

# KDB via captain score
result = ask("Captain score for KDB", _bs(), candidate_inputs=_HAALAND_INPUTS)
check("G8  KDB captain score ok",                 result["raw_output"]["status"] == "ok")
check("G9  KDB player_id == 4",                   result["raw_output"]["player_id"] == 4)


# ---------------------------------------------------------------------------
# H. Safety — ambiguous/not_found remain safe through captain score path
# ---------------------------------------------------------------------------
section("H. Safety — ambiguous/not_found via captain score path")

result = ask("Should I captain Johnson?", _bs(), candidate_inputs=_HAALAND_INPUTS)
check("H1  ambiguous status preserved",            result["raw_output"]["status"] == "ambiguous")
check("H2  answer mentions 'multiple' or disambiguate",
      any(kw in result["answer_text"].lower()
          for kw in ("multiple", "disambiguate", "full name")))
check("H3  no captain_score in ambiguous answer",  "82.5" not in result["answer_text"])
check("H4  no player stats in ambiguous answer",
      "captain_score" not in result["answer_text"])

result = ask("Should I captain Cantona?", _bs(), candidate_inputs=_HAALAND_INPUTS)
check("H5  not_found status preserved",            result["raw_output"]["status"] == "not_found")
check("H6  answer mentions query term",            "cantona" in result["answer_text"].lower())
check("H7  no score in not_found answer",          "82.5" not in result["answer_text"])


# ---------------------------------------------------------------------------
# I. Phase 1h regression — existing 5 questions still work
# ---------------------------------------------------------------------------
section("I. Phase 1h regression — 5 original questions")

checks = [
    ("Who is Salah?",                    None,                "resolve_player",      "ok"),
    ("Give me a summary for Haaland",    None,                "get_player_summary",  "ok"),
    ("What is the current gameweek?",    None,                "get_current_gameweek","ok"),
    ("Who is Johnson?",                  None,                "resolve_player",      "ambiguous"),
    ("Who is Cantona?",                  None,                "resolve_player",      "not_found"),
]
for q, ci, expected_tool, expected_status in checks:
    res = ask(q, _bs(), ci)
    check(
        f"I  '{q[:40]}' → {expected_tool}/{expected_status}",
        res["selected_tool"] == expected_tool
        and res["raw_output"]["status"] == expected_status,
    )


# ---------------------------------------------------------------------------
# J. Schema contract — captain score spec
# ---------------------------------------------------------------------------
section("J. Captain score spec schema contract")

check("J1  parameters has 'query'",
      "query" in GET_CAPTAIN_SCORE_SPEC.parameters.get("properties", {}))
check("J2  parameters has 'form'",
      "form" in GET_CAPTAIN_SCORE_SPEC.parameters.get("properties", {}))
check("J3  all 5 fields required",
      set(GET_CAPTAIN_SCORE_SPEC.parameters["required"])
      == {"query", "form", "fixture_difficulty", "xgi_per_90", "minutes_risk"})
check("J4  output_schema non-empty",
      isinstance(GET_CAPTAIN_SCORE_SPEC.output_schema, dict)
      and len(GET_CAPTAIN_SCORE_SPEC.output_schema) > 0)

openai_d = GET_CAPTAIN_SCORE_SPEC.to_openai()
check("J5  to_openai type == 'function'",       openai_d["type"] == "function")
check("J6  to_openai name == 'get_captain_score'",
      openai_d["function"]["name"] == "get_captain_score")

anthropic_d = GET_CAPTAIN_SCORE_SPEC.to_anthropic()
check("J7  to_anthropic has 'input_schema'",    "input_schema" in anthropic_d)
check("J8  to_anthropic name correct",          anthropic_d["name"] == "get_captain_score")


# ---------------------------------------------------------------------------
# K. Formula edge cases
# ---------------------------------------------------------------------------
section("K. Captain score formula edge cases")

from fpl_tool_contract import tool_get_captain_score as _tcs

# Max possible score: best form (10+), easiest fixture (1), max xgi, no risk
r = _tcs("Haaland", _bs(), {"form": 10, "fixture_difficulty": 1, "xgi_per_90": 2.0, "minutes_risk": 0})
check("K1  max inputs capped at 100.0",         r["captain_score"] <= 100.0)

# Min possible score: zero everything
r = _tcs("Haaland", _bs(), {"form": 0, "fixture_difficulty": 5, "xgi_per_90": 0, "minutes_risk": 100})
check("K2  min inputs produce score >= 0.0",    r["captain_score"] >= 0.0)

# Exact arithmetic: Haaland with fixture_difficulty=3 (neutral)
# form_score=80, fixture_score=60, xgi_score=85, minutes_score=95
# total = 32 + 18 + 17 + 9.5 = 76.5
r = _tcs("Haaland", _bs(), {"form": 8.0, "fixture_difficulty": 3, "xgi_per_90": 1.7, "minutes_risk": 5.0})
check("K3  arithmetic correct for FDR=3 (expected 76.5)", r["captain_score"] == 76.5)

# Salah: form=9.5, fdr=2, xgi=1.45, risk=5
# form_score=95, fixture_score=80, xgi_score=72.5, minutes_score=95
# total = 38 + 24 + 14.5 + 9.5 = 86.0
salah_inputs = {"form": 9.5, "fixture_difficulty": 2, "xgi_per_90": 1.45, "minutes_risk": 5.0}
r = _tcs("Salah", _bs(), salah_inputs)
check("K4  Salah arithmetic correct (expected 86.0)", r["captain_score"] == 86.0)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total = _PASSED + _FAILED
print(f"\n{'='*60}")
print(f"  Phase 2a — router robustness + captain score")
print(f"  {_PASSED}/{total} assertions PASS")
if _FAILED:
    print(f"\n  FAILED ({_FAILED}):")
    for e in _ERRORS:
        print(f"    • {e}")
print(f"{'='*60}\n")

sys.exit(0 if _FAILED == 0 else 1)


