"""
run_phase1h_tests.py
=====================
Standalone validator for fpl-grounded-assistant (Phase 1h).

No pytest required — plain Python asserts only.
Run from the fpl-grounded-assistant package directory::

    python run_phase1h_tests.py
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
_BOOTSTRAP = {
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
# A. Import smoke
# ---------------------------------------------------------------------------
section("A. Import smoke")

try:
    import fpl_grounded_assistant as pkg
    check("A1  package imports", pkg is not None)
    check("A2  ask callable",    callable(pkg.ask))
    check("A3  route/render/RouteResult present",
          all(hasattr(pkg, n) for n in ("route", "render", "RouteResult")))
except Exception:
    traceback.print_exc()
    check("A — import failed", False)

from fpl_grounded_assistant import ask, route, render, RouteResult

# ---------------------------------------------------------------------------
# B. Router — intent detection
# ---------------------------------------------------------------------------
section("B. Router — intent detection")

r = route("Who is Salah?")
check("B1  'Who is Salah?' → resolve_player",
      r is not None and r.tool_name == "resolve_player")

r = route("Give me a summary for Haaland")
check("B2  'summary for' → get_player_summary",
      r is not None and r.tool_name == "get_player_summary")

r = route("What is the current gameweek?")
check("B3  'current gameweek' → get_current_gameweek",
      r is not None and r.tool_name == "get_current_gameweek")

r = route("Tell me about Saka")
check("B4  'tell me about' → get_player_summary",
      r is not None and r.tool_name == "get_player_summary")

r = route("What's the current GW?")
check("B5  'current GW' → get_current_gameweek",
      r is not None and r.tool_name == "get_current_gameweek")

r = route("Hello, how are you?")
check("B6  unrecognised → None",    r is None)

# ---------------------------------------------------------------------------
# C. Router — player extraction
# ---------------------------------------------------------------------------
section("C. Router — player extraction")

r = route("Who is Salah?")
check("C1  'Who is Salah?' extracts 'salah'",
      r is not None and r.tool_args.get("query") == "salah")

r = route("Give me a summary for Haaland")
check("C2  'summary for Haaland' extracts 'haaland'",
      r is not None and r.tool_args.get("query") == "haaland")

r = route("Tell me about De Bruyne")
check("C3  'tell me about De Bruyne' extracts 'de bruyne'",
      r is not None and r.tool_args.get("query") == "de bruyne")

r = route("What is the current gameweek?")
check("C4  gameweek route has empty tool_args",
      r is not None and r.tool_args == {})

# ---------------------------------------------------------------------------
# D. Harness — "Who is Salah?"
# ---------------------------------------------------------------------------
section("D. Harness — 'Who is Salah?'")

result = ask("Who is Salah?", _bs())
check("D1  selected_tool == resolve_player",   result["selected_tool"] == "resolve_player")
check("D2  tool_input has 'query'",             "query" in result["tool_input"])
check("D3  raw_output status == ok",           result["raw_output"]["status"] == "ok")
check("D4  raw_output player_id == 2",         result["raw_output"]["player_id"] == 2)
check("D5  answer_text contains 'Salah'",
      "salah" in result["answer_text"].lower())

# ---------------------------------------------------------------------------
# E. Harness — "Give me a summary for Haaland"
# ---------------------------------------------------------------------------
section("E. Harness — 'Give me a summary for Haaland'")

result = ask("Give me a summary for Haaland", _bs())
check("E1  selected_tool == get_player_summary", result["selected_tool"] == "get_player_summary")
check("E2  raw_output status == ok",             result["raw_output"]["status"] == "ok")
check("E3  answer contains cost '14.5'",         "14.5" in result["answer_text"])
check("E4  answer contains position 'FWD'",      "FWD" in result["answer_text"])
check("E5  answer contains team 'MCI'",          "MCI" in result["answer_text"])

# ---------------------------------------------------------------------------
# F. Harness — "What is the current gameweek?"
# ---------------------------------------------------------------------------
section("F. Harness — 'What is the current gameweek?'")

result = ask("What is the current gameweek?", _bs())
check("F1  selected_tool == get_current_gameweek", result["selected_tool"] == "get_current_gameweek")
check("F2  tool_input == {}",                      result["tool_input"] == {})
check("F3  raw_output gameweek == 28",             result["raw_output"]["gameweek"] == 28)
check("F4  answer contains '28'",                  "28" in result["answer_text"])

# ---------------------------------------------------------------------------
# G. Harness — ambiguous player (Johnson)
# ---------------------------------------------------------------------------
section("G. Harness — ambiguous player (Johnson)")

result = ask("Who is Johnson?", _bs())
check("G1  raw_output status == ambiguous",    result["raw_output"]["status"] == "ambiguous")
text = result["answer_text"].lower()
check("G2  answer mentions 'multiple' or 'disambiguate' or 'full name'",
      any(kw in text for kw in ("multiple", "disambiguate", "full name")))
check("G3  answer does not leak cost values", "5.0" not in result["answer_text"] and "4.5" not in result["answer_text"])
check("G4  answer does not leak ownership values",
      "0.5%" not in result["answer_text"] and "0.3%" not in result["answer_text"])

# ---------------------------------------------------------------------------
# H. Harness — not-found player (Cantona)
# ---------------------------------------------------------------------------
section("H. Harness — not-found player (Cantona)")

result = ask("Who is Cantona?", _bs())
check("H1  raw_output status == not_found",  result["raw_output"]["status"] == "not_found")
check("H2  answer mentions query term",      "cantona" in result["answer_text"].lower())
check("H3  answer is non-empty string",
      isinstance(result["answer_text"], str) and len(result["answer_text"]) > 5)
check("H4  answer has no player stats",
      "£" not in result["answer_text"] and "FWD" not in result["answer_text"])

# ---------------------------------------------------------------------------
# I. Harness — unrecognised question
# ---------------------------------------------------------------------------
section("I. Harness — unrecognised question")

result = ask("Hello, how are you?", _bs())
check("I1  selected_tool is None",              result["selected_tool"] is None)
check("I2  raw_output code == unrecognised_query",
      result["raw_output"]["code"] == "unrecognised_query")
check("I3  answer_text non-empty",
      isinstance(result["answer_text"], str) and len(result["answer_text"]) > 10)

# ---------------------------------------------------------------------------
# J. Result structure contract
# ---------------------------------------------------------------------------
section("J. Result structure contract — all four keys present")

_QUESTIONS = [
    "Who is Salah?",
    "Who is Johnson?",
    "Who is Cantona?",
    "What is the current gameweek?",
    "Give me a summary for Haaland",
    "Hello, how are you?",
]
_REQUIRED_KEYS = {"selected_tool", "tool_input", "raw_output", "answer_text"}

all_keys_ok       = all(set(ask(q, _bs()).keys()) == _REQUIRED_KEYS for q in _QUESTIONS)
all_answer_str    = all(isinstance(ask(q, _bs())["answer_text"], str) for q in _QUESTIONS)
all_input_dict    = all(isinstance(ask(q, _bs())["tool_input"], dict) for q in _QUESTIONS)
all_output_dict   = all(isinstance(ask(q, _bs())["raw_output"], dict) for q in _QUESTIONS)

check("J1  all questions return exactly 4 keys", all_keys_ok)
check("J2  answer_text always str",              all_answer_str)
check("J3  tool_input always dict",              all_input_dict)
check("J4  raw_output always dict",              all_output_dict)

# ---------------------------------------------------------------------------
# K. Renderer safety
# ---------------------------------------------------------------------------
section("K. Renderer safety")

result = ask("Who is Johnson?", _bs())
check("K1  ambiguous answer has no 'player_id' field text",
      "player_id" not in result["answer_text"] and result["raw_output"]["status"] == "ambiguous")

result = ask("Give me a summary for Zidane", _bs())
check("K2  not_found answer has no 'cost_m' text",
      "cost_m" not in result["answer_text"] and result["raw_output"]["status"] == "not_found")

result = ask("Give me a summary for Haaland", _bs())
check("K3  ok answer is factually grounded (MCI, FWD)",
      "MCI" in result["answer_text"] and "FWD" in result["answer_text"])

# ---------------------------------------------------------------------------
# L. Public surface guard
# ---------------------------------------------------------------------------
section("L. Public surface guard")

import fpl_grounded_assistant as _pkg
check("L1  all exports importable",
      all(hasattr(_pkg, n) for n in ("ask", "route", "render", "RouteResult")))

try:
    r2 = RouteResult(tool_name="resolve_player", tool_args={"query": "x"})
    r2.tool_name = "tampered"  # type: ignore[misc]
    check("L2  RouteResult is frozen (should raise)", False)
except (AttributeError, TypeError):
    check("L2  RouteResult is frozen", True)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total = _PASSED + _FAILED
print(f"\n{'='*60}")
print(f"  Phase 1h — fpl-grounded-assistant")
print(f"  {_PASSED}/{total} assertions PASS")
if _FAILED:
    print(f"\n  FAILED ({_FAILED}):")
    for e in _ERRORS:
        print(f"    • {e}")
print(f"{'='*60}\n")

sys.exit(0 if _FAILED == 0 else 1)


