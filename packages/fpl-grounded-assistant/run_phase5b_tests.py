"""
run_phase5b_tests.py
====================
Phase 5b: comparison contract normalization.

Validates that ``compare_players`` is now a first-class citizen in the
tool-runner architecture — registered in ``TOOL_REGISTRY``, executable via
``run_tool()``, and rendered via the standard ``render()`` dispatch table —
with no special-case bypass remaining in ``dispatcher.py``.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5b_tests.py

Sections
--------
A  -- Tool registry: compare_players registered in TOOL_REGISTRY
B  -- run_tool() contract: compare_players callable via run_tool
C  -- ToolSpec contract: parameters, output_schema, to_openai, to_anthropic
D  -- Renderer contract: _render_compare_players in dispatch table
E  -- Dispatcher bypass removed: no _dispatch_comparison in dispatcher
F  -- dispatch() still works end-to-end through the normal path
G  -- Phase 5a regression: all comparison behavior intact
"""
from __future__ import annotations

import os
import sys

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

_passed = 0
_failed = 0


def ok(label: str, expr: bool) -> None:
    global _passed, _failed
    if expr:
        _passed += 1
    else:
        _failed += 1
        print(f"FAIL  {label}")


def eq(label: str, got: object, want: object) -> None:
    if got != want:
        print(f"FAIL  {label}  got={got!r}  want={want!r}")
    ok(label, got == want)


# Importing fpl_grounded_assistant triggers registration of compare_players
from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    INTENT_COMPARE_PLAYERS,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    compare_players,
    dispatch,
    respond,
)
from fpl_grounded_assistant.comparison import (
    COMPARE_PLAYERS_SPEC,
    _compare_players_handler,
)
from fpl_grounded_assistant.renderer import (
    _render_compare_players,
    _RENDERERS,
)
from fpl_tool_runner import TOOL_REGISTRY, run_tool
from fpl_tool_runner.specs import ToolSpec


# ===========================================================================
# Section A -- Tool registry
# ===========================================================================

print("A  Tool registry")

ok("A1  compare_players in TOOL_REGISTRY",      "compare_players" in TOOL_REGISTRY.list_tools())
ok("A2  TOOL_REGISTRY.get_spec returns ToolSpec",
   isinstance(TOOL_REGISTRY.get_spec("compare_players"), ToolSpec))
ok("A3  spec name is compare_players",           TOOL_REGISTRY.get_spec("compare_players").name == "compare_players")
ok("A4  compare_players in to_anthropic_tools",
   any(t["name"] == "compare_players" for t in TOOL_REGISTRY.to_anthropic_tools()))
ok("A5  compare_players in to_openai_tools",
   any(t["function"]["name"] == "compare_players" for t in TOOL_REGISTRY.to_openai_tools()))
ok("A6  COMPARE_PLAYERS_SPEC is a ToolSpec",     isinstance(COMPARE_PLAYERS_SPEC, ToolSpec))
eq("A7  COMPARE_PLAYERS_SPEC name",              COMPARE_PLAYERS_SPEC.name, "compare_players")
ok("A8  registered spec matches module spec",
   TOOL_REGISTRY.get_spec("compare_players") is COMPARE_PLAYERS_SPEC)


# ===========================================================================
# Section B -- run_tool() contract
# ===========================================================================

print("B  run_tool() contract")

_b1 = run_tool("compare_players", {"query_a": "Haaland", "query_b": "Salah"}, STANDARD_BOOTSTRAP)
eq("B1  run_tool status ok",        _b1["status"], "ok")
ok("B2  run_tool has player_a",     "player_a" in _b1)
ok("B3  run_tool has player_b",     "player_b" in _b1)
ok("B4  run_tool has winner",       "winner" in _b1)
ok("B5  run_tool has margin",       "margin" in _b1)
ok("B6  run_tool has recommendation","recommendation" in _b1)
eq("B7  winner = Salah",            _b1["winner"], "Salah")

# Missing query_a → runner error
_b8 = run_tool("compare_players", {"query_b": "Salah"}, STANDARD_BOOTSTRAP)
eq("B8  missing query_a status error", _b8["status"], "error")
eq("B9  missing query_a code",         _b8["code"], "missing_argument")

# Missing query_b → runner error
_b10 = run_tool("compare_players", {"query_a": "Haaland"}, STANDARD_BOOTSTRAP)
eq("B10 missing query_b status error", _b10["status"], "error")

# Not-found player
_b11 = run_tool("compare_players", {"query_a": "Haaland", "query_b": "NoSuchPlayer99"}, STANDARD_BOOTSTRAP)
eq("B11 not_found status",             _b11["status"], "not_found")

# Unknown tool still fails correctly (regression guard)
_b12 = run_tool("nonexistent_tool", {}, STANDARD_BOOTSTRAP)
eq("B12 unknown_tool error",           _b12["status"], "error")
eq("B13 unknown_tool code",            _b12["code"], "unknown_tool")


# ===========================================================================
# Section C -- ToolSpec contract
# ===========================================================================

print("C  ToolSpec contract")

ok("C1  spec description non-empty",        bool(COMPARE_PLAYERS_SPEC.description))
ok("C2  parameters type=object",            COMPARE_PLAYERS_SPEC.parameters.get("type") == "object")
ok("C3  query_a in parameters.properties",  "query_a" in COMPARE_PLAYERS_SPEC.parameters["properties"])
ok("C4  query_b in parameters.properties",  "query_b" in COMPARE_PLAYERS_SPEC.parameters["properties"])
ok("C5  required=[query_a, query_b]",
   set(COMPARE_PLAYERS_SPEC.parameters.get("required", [])) == {"query_a", "query_b"})
ok("C6  output_schema non-empty",           bool(COMPARE_PLAYERS_SPEC.output_schema))

_c_openai = COMPARE_PLAYERS_SPEC.to_openai()
ok("C7  to_openai type=function",           _c_openai.get("type") == "function")
ok("C8  to_openai function.name",           _c_openai["function"]["name"] == "compare_players")
ok("C9  to_openai function.parameters",     "parameters" in _c_openai["function"])

_c_anthropic = COMPARE_PLAYERS_SPEC.to_anthropic()
ok("C10 to_anthropic name",                 _c_anthropic.get("name") == "compare_players")
ok("C11 to_anthropic input_schema",         "input_schema" in _c_anthropic)

ok("C12 handler callable",                  callable(_compare_players_handler))
_c12_result = _compare_players_handler(
    {"query_a": "Haaland", "query_b": "Salah"}, STANDARD_BOOTSTRAP
)
eq("C13 handler returns ok",                _c12_result["status"], "ok")


# ===========================================================================
# Section D -- Renderer contract
# ===========================================================================

print("D  Renderer contract")

ok("D1  compare_players in _RENDERERS",     "compare_players" in _RENDERERS)
ok("D2  _render_compare_players callable",  callable(_render_compare_players))

# ok status → recommendation text
_d3 = run_tool("compare_players", {"query_a": "Haaland", "query_b": "Salah"}, STANDARD_BOOTSTRAP)
_d3_text = _render_compare_players(_d3)
ok("D3  ok renders recommendation",         bool(_d3_text))
ok("D4  ok text mentions Salah",            "Salah" in _d3_text)
ok("D5  ok text mentions Haaland",          "Haaland" in _d3_text)

# not_found status → message
_d6_raw = {"status": "not_found", "query_a": "Haaland", "query_b": "X",
           "error_player": "X", "message": "Player 'X' not found."}
_d6_text = _render_compare_players(_d6_raw)
ok("D6  not_found renders message",         "not found" in _d6_text.lower() or "X" in _d6_text)

# error status
_d7_raw = {"status": "error", "code": "test_code", "message": "Test error."}
_d7_text = _render_compare_players(_d7_raw)
ok("D7  error renders code+message",        "test_code" in _d7_text)


# ===========================================================================
# Section E -- Dispatcher bypass removed
# ===========================================================================

print("E  Dispatcher bypass removed")

import fpl_grounded_assistant.dispatcher as _disp

ok("E1  _dispatch_comparison does not exist",
   not hasattr(_disp, "_dispatch_comparison"))

# The dispatch source code should not contain the old bypass comment
import inspect as _inspect
_disp_src = _inspect.getsource(_disp.dispatch)
ok("E2  dispatch source has no _dispatch_comparison call",
   "_dispatch_comparison" not in _disp_src)
ok("E3  dispatch source has no 'handled directly' comment",
   "handled directly" not in _disp_src)


# ===========================================================================
# Section F -- dispatch() end-to-end through normal path
# ===========================================================================

print("F  dispatch() end-to-end")

_f1 = dispatch("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("F1  intent",            _f1.intent, INTENT_COMPARE_PLAYERS)
eq("F2  selected_tool",     _f1.selected_tool, "compare_players")
eq("F3  outcome ok",        _f1.outcome, OUTCOME_OK)
ok("F4  answer_text non-empty", bool(_f1.answer_text))
ok("F5  raw_output status ok",  _f1.raw_output.get("status") == "ok")
# answer_text now comes from renderer, should match recommendation
ok("F6  answer_text matches recommendation",
   _f1.answer_text == _f1.raw_output.get("recommendation", ""))

_f2 = dispatch("Haaland vs Salah", STANDARD_BOOTSTRAP)
eq("F7  bare vs outcome ok", _f2.outcome, OUTCOME_OK)

_f3 = dispatch("compare Haaland and NoSuchPlayer99", STANDARD_BOOTSTRAP)
eq("F8  not_found outcome",  _f3.outcome, OUTCOME_NOT_FOUND)
ok("F9  not_found answer_text non-empty", bool(_f3.answer_text))


# ===========================================================================
# Section G -- Phase 5a regression
# ===========================================================================

print("G  Phase 5a regression")

_g1 = compare_players("Haaland", "Salah", STANDARD_BOOTSTRAP)
eq("G1  compare status ok",     _g1["status"], "ok")
eq("G2  winner = Salah",        _g1["winner"], "Salah")
ok("G3  margin ~5.73",          abs(_g1["margin"] - 5.73) < 0.5)

_g4 = dispatch("should I captain Haaland", STANDARD_BOOTSTRAP)
ok("G4  captain score still ok", _g4.outcome == OUTCOME_OK)
ok("G5  captain score intent",   _g4.intent == "captain_score")

_g6 = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
ok("G6  respond ok",             _g6.outcome == OUTCOME_OK)
ok("G7  respond non-empty",      bool(_g6.final_text))
ok("G8  respond mentions Salah", "Salah" in _g6.final_text)


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5b: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
