"""
run_phase1g_tests.py
=====================
Standalone validator for fpl-tool-runner (Phase 1g).

No pytest required — plain Python asserts only.
Run from the fpl-tool-runner package directory::

    python run_phase1g_tests.py

All five upstream sibling packages must be on sys.path (see path setup below).
"""
from __future__ import annotations

import copy
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup: add sibling packages so imports resolve without pip install
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
for _sibling in (
    "fpl-data-core",
    "fpl-api-client",
    "fpl-player-registry",
    "fpl-query-tools",
    "fpl-tool-contract",
):
    _p = (_HERE.parent / _sibling).resolve()
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Also add this package itself
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ---------------------------------------------------------------------------
# Shared bootstrap fixture (no pytest needed)
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
# Test runner helpers
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
    import fpl_tool_runner as pkg
    check("A1  package imports", pkg is not None)
    check("A2  ToolSpec present",       hasattr(pkg, "ToolSpec"))
    check("A3  ToolRegistry present",   hasattr(pkg, "ToolRegistry"))
    check("A4  TOOL_REGISTRY present",  hasattr(pkg, "TOOL_REGISTRY"))
    check("A5  TOOL_SPECS present",     hasattr(pkg, "TOOL_SPECS"))
    check("A6  run_tool callable",      callable(pkg.run_tool))
except Exception:
    traceback.print_exc()
    check("A — import failed", False)

# ---------------------------------------------------------------------------
# B. ToolSpec structure
# ---------------------------------------------------------------------------
section("B. ToolSpec structure — to_openai / to_anthropic")

from fpl_tool_runner import RESOLVE_PLAYER_SPEC, GET_PLAYER_SUMMARY_SPEC, GET_CURRENT_GAMEWEEK_SPEC, TOOL_SPECS, ToolSpec

openai_d  = RESOLVE_PLAYER_SPEC.to_openai()
anthropic_d = RESOLVE_PLAYER_SPEC.to_anthropic()

check("B1  to_openai has type+function keys",      set(openai_d.keys()) == {"type", "function"})
check("B2  to_openai type == 'function'",          openai_d["type"] == "function")
check("B3  to_openai function has name/desc/params",
      {"name","description","parameters"}.issubset(openai_d["function"].keys()))
check("B4  to_anthropic has name/desc/input_schema",
      {"name","description","input_schema"}.issubset(anthropic_d.keys()))
check("B5  to_openai name matches spec",           openai_d["function"]["name"] == "resolve_player")
check("B6  to_anthropic name matches spec",        anthropic_d["name"] == "resolve_player")

try:
    RESOLVE_PLAYER_SPEC.name = "tampered"  # type: ignore[misc]
    check("B7  spec is frozen (should raise)",     False)
except (AttributeError, TypeError):
    check("B7  spec is frozen",                    True)

# ---------------------------------------------------------------------------
# C. ToolRegistry introspection
# ---------------------------------------------------------------------------
section("C. ToolRegistry introspection")

from fpl_tool_runner import TOOL_REGISTRY, ToolRegistry

check("C1  TOOL_REGISTRY is ToolRegistry",    isinstance(TOOL_REGISTRY, ToolRegistry))
check("C2  list_tools returns 3",             len(TOOL_REGISTRY.list_tools()) == 3)
check("C3  resolve_player in list",           "resolve_player" in TOOL_REGISTRY.list_tools())
check("C4  get_spec returns ToolSpec",        isinstance(TOOL_REGISTRY.get_spec("resolve_player"), ToolSpec))
check("C5  to_openai_tools has 3 entries",    len(TOOL_REGISTRY.to_openai_tools()) == 3)
check("C6  to_anthropic_tools has 3 entries", len(TOOL_REGISTRY.to_anthropic_tools()) == 3)
check("C7  get_spec unknown returns None",    TOOL_REGISTRY.get_spec("nonexistent") is None)

# ---------------------------------------------------------------------------
# D. run_tool — resolve_player
# ---------------------------------------------------------------------------
section("D. run_tool — resolve_player")

from fpl_tool_runner import run_tool

r = run_tool("resolve_player", {"query": "Haaland"}, _bs())
check("D1  ok by name — status ok",          r["status"] == "ok")
check("D2  ok by name — player_id correct",  r["player_id"] == 1)

r = run_tool("resolve_player", {"query": "2"}, _bs())
check("D3  ok by numeric string — player_id=2", r["player_id"] == 2)

r = run_tool("resolve_player", {"query": "KDB"}, _bs())
check("D4  ok by alias — player_id=4",       r["status"] == "ok" and r["player_id"] == 4)

r = run_tool("resolve_player", {"query": "Johnson"}, _bs())
check("D5  ambiguous — status ambiguous",    r["status"] == "ambiguous")

r = run_tool("resolve_player", {"query": "Zidane"}, _bs())
check("D6  not_found — status not_found",    r["status"] == "not_found")

r = run_tool("resolve_player", {"query": "el Vikingo"}, _bs())
check("D7  query field preserved",           r.get("query") == "el Vikingo" and r["player_id"] == 1)

# ---------------------------------------------------------------------------
# E. run_tool — get_player_summary
# ---------------------------------------------------------------------------
section("E. run_tool — get_player_summary")

r = run_tool("get_player_summary", {"query": "Haaland"}, _bs())
check("E1  ok status",                       r["status"] == "ok")
check("E2  cost_m == 14.5",                  r["cost_m"] == 14.5)
check("E3  position == FWD",                 r["position"] == "FWD")

r = run_tool("get_player_summary", {"query": "1"}, _bs())
check("E4  numeric string resolves ok",      r["status"] == "ok")

r = run_tool("get_player_summary", {"query": "Johnson"}, _bs())
check("E5  ambiguous propagated",            r["status"] == "ambiguous")

r = run_tool("get_player_summary", {"query": "Cantona"}, _bs())
check("E6  not_found propagated",            r["status"] == "not_found")

# ---------------------------------------------------------------------------
# F. run_tool — get_current_gameweek
# ---------------------------------------------------------------------------
section("F. run_tool — get_current_gameweek")

r = run_tool("get_current_gameweek", {}, _bs())
check("F1  ok status",                       r["status"] == "ok")
check("F2  gameweek == 28",                  r["gameweek"] == 28)
check("F3  exactly two keys",                set(r.keys()) == {"status", "gameweek"})

bs_no_flags = {"events": [{"id": 1, "is_current": False, "is_next": False}],
               "elements": [], "teams": [], "element_types": []}
r = run_tool("get_current_gameweek", {}, bs_no_flags)
check("F4  not_found when no flags",         r["status"] == "not_found")

# ---------------------------------------------------------------------------
# G. run_tool — error handling
# ---------------------------------------------------------------------------
section("G. run_tool — error handling")

r = run_tool("nonexistent_tool", {}, _bs())
check("G1  unknown tool → status error",    r["status"] == "error")
check("G2  unknown tool → code unknown_tool", r["code"] == "unknown_tool")
check("G3  unknown tool → message non-empty", len(r.get("message", "")) > 5)

r = run_tool("resolve_player", {}, _bs())
check("G4  missing required arg → status error",      r["status"] == "error")
check("G5  missing required arg → code missing_argument", r["code"] == "missing_argument")
check("G6  missing arg → message names 'query'",      "query" in r["message"])

# ---------------------------------------------------------------------------
# H. Schema contract
# ---------------------------------------------------------------------------
section("H. Schema contract")

check("H1  resolve_player has 'query' property",
      "query" in RESOLVE_PLAYER_SPEC.parameters.get("properties", {}))
check("H2  resolve_player 'query' is required",
      "query" in RESOLVE_PLAYER_SPEC.parameters.get("required", []))
check("H3  get_current_gameweek no required args",
      GET_CURRENT_GAMEWEEK_SPEC.parameters.get("required", []) == [])
check("H4  all specs have non-empty output_schema",
      all(isinstance(s.output_schema, dict) and len(s.output_schema) > 0 for s in TOOL_SPECS))

# ---------------------------------------------------------------------------
# I. Public surface guard
# ---------------------------------------------------------------------------
section("I. Public surface guard")

import fpl_tool_runner as _pkg
_expected = {
    "ToolSpec", "ToolRegistry", "TOOL_REGISTRY", "TOOL_SPECS", "run_tool",
    "RESOLVE_PLAYER_SPEC", "GET_PLAYER_SUMMARY_SPEC", "GET_CURRENT_GAMEWEEK_SPEC",
}
check("I1  all expected exports present",    all(hasattr(_pkg, n) for n in _expected))
check("I2  TOOL_SPECS is list of 3",         isinstance(_pkg.TOOL_SPECS, list) and len(_pkg.TOOL_SPECS) == 3)
check("I3  all TOOL_SPECS are ToolSpec",     all(isinstance(s, _pkg.ToolSpec) for s in _pkg.TOOL_SPECS))

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total = _PASSED + _FAILED
print(f"\n{'='*60}")
print(f"  Phase 1g — fpl-tool-runner")
print(f"  {_PASSED}/{total} assertions PASS")
if _FAILED:
    print(f"\n  FAILED ({_FAILED}):")
    for e in _ERRORS:
        print(f"    • {e}")
print(f"{'='*60}\n")

sys.exit(0 if _FAILED == 0 else 1)


