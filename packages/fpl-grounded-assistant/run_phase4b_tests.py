"""
run_phase4b_tests.py
====================
Phase 4b: CLI entrypoint validation.

Validates the ``fpl_cli.run()`` function -- the core logic of the thin external
interface introduced in Phase 4b.  All tests use STANDARD_BOOTSTRAP or
AMBIGUOUS_BOOTSTRAP (no network, no LLM calls).

The ``main()`` path (arg parsing + live assemble_captain_context()) is
intentionally not tested here -- live calls are covered by run_phase4a_tests.py.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine;\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools;\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase4b_tests.py

Sections
--------
A  -- Import and interface shape
B  -- Default mode (plain text output)
C  -- Debug mode (JSON output)
D  -- Exit codes
E  -- Unsupported intents
F  -- Supported intent coverage (all 5 intent types)
G  -- Contract invariants preserved end-to-end
H  -- Edge cases
"""
from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Path setup  (mirrors all other phase test runners)
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
_passed  = 0
_failed  = 0


def _section(name: str) -> None:
    print(f"\n  [{name}]")


def ok(label: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"    PASS  {label}")
    else:
        _failed += 1
        print(f"    FAIL  {label}")


def eq(label: str, actual: object, expected: object) -> None:
    ok(f"{label}  (got {actual!r})", actual == expected)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
)
from fpl_cli import run

# ===========================================================================
# Section A -- Import and interface shape
# ===========================================================================
_section("A -- Import and interface shape")

import inspect
_sig = inspect.signature(run)
_params = list(_sig.parameters.keys())

ok("A1  fpl_cli imports without error", True)
ok("A2  run is callable", callable(run))
ok("A3  run has 'question' parameter", "question" in _params)
ok("A4  run has 'bootstrap' parameter", "bootstrap" in _params)
ok("A5  run has 'debug' keyword parameter", "debug" in _params)
ok("A6  debug parameter is keyword-only",
   _sig.parameters["debug"].kind == inspect.Parameter.KEYWORD_ONLY)
ok("A7  debug default is False",
   _sig.parameters["debug"].default is False)
ok("A8  run returns tuple", True)  # tested live below

# Verify run() actually returns a tuple
_r0 = run("should I captain Haaland", STANDARD_BOOTSTRAP)
ok("A9  run() returns a 2-tuple", isinstance(_r0, tuple) and len(_r0) == 2)
ok("A10 run()[0] is int (exit code)", isinstance(_r0[0], int))
ok("A11 run()[1] is str (output)",  isinstance(_r0[1], str))

# ===========================================================================
# Section B -- Default mode (plain text output)
# ===========================================================================
_section("B -- Default mode (plain text output)")

_code_b1, _out_b1 = run("should I captain Haaland", STANDARD_BOOTSTRAP)

ok("B1  captain score query returns exit_code 0", _code_b1 == 0)
ok("B2  output is non-empty string", isinstance(_out_b1, str) and len(_out_b1) > 0)
ok("B3  output is NOT JSON (plain text mode)", not _out_b1.strip().startswith("{"))
ok("B4  output does not contain 'final_text' key literal", "\"final_text\"" not in _out_b1)

_code_b5, _out_b5 = run("what is the current gameweek", STANDARD_BOOTSTRAP)
ok("B5  gameweek query returns exit_code 0", _code_b5 == 0)
ok("B6  gameweek output is non-empty", len(_out_b5) > 0)
ok("B7  gameweek output is plain text", not _out_b5.strip().startswith("{"))

_code_b8, _out_b8 = run("tell me about Salah", STANDARD_BOOTSTRAP)
ok("B8  player summary query returns exit_code 0", _code_b8 == 0)
ok("B9  player summary output is non-empty", len(_out_b8) > 0)

_code_b10, _out_b10 = run("find player Haaland", STANDARD_BOOTSTRAP)
ok("B10 resolve player query returns exit_code 0", _code_b10 == 0)
ok("B11 resolve player output is non-empty", len(_out_b10) > 0)

# ===========================================================================
# Section C -- Debug mode (JSON output)
# ===========================================================================
_section("C -- Debug mode (JSON output)")

_code_c1, _out_c1 = run("should I captain Haaland", STANDARD_BOOTSTRAP, debug=True)

ok("C1  debug mode returns exit_code 0", _code_c1 == 0)
ok("C2  debug output is non-empty", len(_out_c1) > 0)
ok("C3  debug output starts with '{'", _out_c1.strip().startswith("{"))

try:
    _dbg = json.loads(_out_c1)
    ok("C4  debug output is valid JSON", True)
except json.JSONDecodeError:
    ok("C4  debug output is valid JSON", False)
    _dbg = {}

ok("C5  debug JSON has 'final_text' key",   "final_text"    in _dbg)
ok("C6  debug JSON has 'outcome' key",      "outcome"       in _dbg)
ok("C7  debug JSON has 'supported' key",    "supported"     in _dbg)
ok("C8  debug JSON has 'intent' key",       "intent"        in _dbg)
ok("C9  debug JSON has 'review_passed' key","review_passed" in _dbg)
ok("C10 debug JSON has 'llm_used' key",     "llm_used"      in _dbg)
ok("C11 debug JSON has 'debug' key (bundle populated)", "debug" in _dbg)

_bundle = _dbg.get("debug", {})
ok("C12 debug bundle has 'response_text'",  "response_text" in _bundle)
ok("C13 debug bundle has 'llm_text'",       "llm_text"      in _bundle)
ok("C14 debug bundle has 'violations'",     "violations"    in _bundle)
ok("C15 debug bundle has 'prompt_used'",    "prompt_used"   in _bundle)
ok("C16 debug bundle has 'model'",          "model"         in _bundle)
ok("C17 debug bundle 'violations' is list", isinstance(_bundle.get("violations"), list))

# final_text in debug JSON must match non-debug output
_code_nd, _out_nd = run("should I captain Haaland", STANDARD_BOOTSTRAP, debug=False)
ok("C18 debug final_text == non-debug output", _dbg.get("final_text") == _out_nd)

# debug=False vs debug=True should produce same exit codes
ok("C19 exit codes match between modes", _code_c1 == _code_nd)

# Unsupported intent in debug mode
_code_c20, _out_c20 = run("what is the weather", STANDARD_BOOTSTRAP, debug=True)
ok("C20 unsupported in debug mode returns valid JSON",
   _out_c20.strip().startswith("{") and len(_out_c20) > 0)

try:
    _dbg_u = json.loads(_out_c20)
    ok("C21 unsupported debug JSON is parseable", True)
except json.JSONDecodeError:
    ok("C21 unsupported debug JSON is parseable", False)
    _dbg_u = {}

ok("C22 unsupported debug JSON 'supported' is False", _dbg_u.get("supported") is False)

# ===========================================================================
# Section D -- Exit codes
# ===========================================================================
_section("D -- Exit codes")

_SUPPORTED_QUERIES = [
    "should I captain Haaland",
    "captain score for Salah",
    "what is the current gameweek",
    "tell me about Haaland",
    "find player Salah",
    "rank captains",
]

_UNSUPPORTED_QUERIES = [
    "what is the weather today",
    "tell me a joke",
    "how do I cook pasta",
    "who won the Champions League",
]

for _i, _q in enumerate(_SUPPORTED_QUERIES, 1):
    _c, _ = run(_q, STANDARD_BOOTSTRAP)
    ok(f"D{_i}  supported query exit_code=0: {_q!r:.40}", _c == 0)

for _i, _q in enumerate(_UNSUPPORTED_QUERIES, len(_SUPPORTED_QUERIES) + 1):
    _c, _ = run(_q, STANDARD_BOOTSTRAP)
    ok(f"D{_i}  unsupported query exit_code=1: {_q!r:.40}", _c == 1)

# ===========================================================================
# Section E -- Unsupported intents
# ===========================================================================
_section("E -- Unsupported intents")

_code_e1, _out_e1 = run("what is the weather today", STANDARD_BOOTSTRAP)
ok("E1  unsupported intent returns exit_code 1", _code_e1 == 1)
ok("E2  unsupported output is non-empty (graceful response)", len(_out_e1) > 0)
ok("E3  unsupported output is plain text", not _out_e1.strip().startswith("{"))

_code_e4, _out_e4 = run("tell me a joke", STANDARD_BOOTSTRAP)
ok("E4  another unsupported query exit_code 1", _code_e4 == 1)
ok("E5  another unsupported output is non-empty", len(_out_e4) > 0)

# Verify the unsupported response text is non-empty even for edge-case input
_code_e6, _out_e6 = run("?", STANDARD_BOOTSTRAP)
ok("E6  single-character query does not crash", True)
ok("E7  single-character query returns string output", isinstance(_out_e6, str))

_code_e8, _out_e8 = run("   ", STANDARD_BOOTSTRAP)
ok("E8  whitespace-only query does not crash", True)
ok("E9  whitespace-only query returns non-empty output", len(_out_e8) > 0)

# ===========================================================================
# Section F -- Supported intent coverage (all 5 intent types)
# ===========================================================================
_section("F -- Supported intent coverage")

from fpl_grounded_assistant import respond

def _intent_from_run(query, bootstrap=STANDARD_BOOTSTRAP):
    """Helper: call respond() directly to get the intent for a given query."""
    return respond(query, bootstrap).intent

# captain score
_f1_intent = _intent_from_run("should I captain Haaland")
ok("F1  captain score query resolves INTENT_CAPTAIN_SCORE",
   _f1_intent == INTENT_CAPTAIN_SCORE)

# rank candidates
_f2_intent = _intent_from_run("rank captains")
ok("F2  rank candidates query resolves INTENT_RANK_CANDIDATES",
   _f2_intent == INTENT_RANK_CANDIDATES)

# current gameweek
_f3_intent = _intent_from_run("what is the current gameweek")
ok("F3  gameweek query resolves INTENT_CURRENT_GAMEWEEK",
   _f3_intent == INTENT_CURRENT_GAMEWEEK)

# player summary
_f4_intent = _intent_from_run("tell me about Haaland")
ok("F4  player summary query resolves INTENT_PLAYER_SUMMARY",
   _f4_intent == INTENT_PLAYER_SUMMARY)

# resolve player
_f5_intent = _intent_from_run("find player Salah")
ok("F5  resolve player query resolves INTENT_PLAYER_RESOLVE",
   _f5_intent == INTENT_PLAYER_RESOLVE)

# unsupported
_f6_intent = _intent_from_run("what is the weather today")
ok("F6  unsupported query resolves INTENT_UNSUPPORTED",
   _f6_intent == INTENT_UNSUPPORTED)

# run() exit codes match intents
ok("F7  captain score run() exit_code=0",  run("should I captain Haaland",     STANDARD_BOOTSTRAP)[0] == 0)
ok("F8  rank candidates run() exit_code=0",run("rank captains",                 STANDARD_BOOTSTRAP)[0] == 0)
ok("F9  gameweek run() exit_code=0",       run("what is the current gameweek",  STANDARD_BOOTSTRAP)[0] == 0)
ok("F10 player summary run() exit_code=0", run("tell me about Haaland",         STANDARD_BOOTSTRAP)[0] == 0)
ok("F11 resolve player run() exit_code=0", run("find player Salah",             STANDARD_BOOTSTRAP)[0] == 0)
ok("F12 unsupported run() exit_code=1",    run("what is the weather today",     STANDARD_BOOTSTRAP)[0] == 1)

# ===========================================================================
# Section G -- Contract invariants preserved end-to-end
# ===========================================================================
_section("G -- Contract invariants preserved end-to-end")

def _respond(query, bootstrap=STANDARD_BOOTSTRAP):
    return respond(query, bootstrap, include_debug=True)

_SAMPLE_QUERIES = [
    "should I captain Haaland",
    "rank captains",
    "what is the current gameweek",
    "tell me about Salah",
    "find player Haaland",
    "what is the weather today",
]

_responses = [_respond(q) for q in _SAMPLE_QUERIES]

ok("G1  all sample queries return FinalResponse (no exception)", True)

for _j, (_q, _r) in enumerate(zip(_SAMPLE_QUERIES, _responses), 1):
    ok(f"G2.{_j} final_text non-empty: {_q!r:.35}", len(_r.final_text) > 0)

for _j, (_q, _r) in enumerate(zip(_SAMPLE_QUERIES, _responses), 1):
    # Invariant: supported == (outcome != OUTCOME_UNSUPPORTED_INTENT)
    _expected_supported = _r.outcome != OUTCOME_UNSUPPORTED_INTENT
    ok(f"G3.{_j} supported == (outcome != unsupported): {_q!r:.30}",
       _r.supported == _expected_supported)

for _j, (_q, _r) in enumerate(zip(_SAMPLE_QUERIES, _responses), 1):
    # Invariant: llm_used=True implies review_passed=True
    if _r.llm_used:
        ok(f"G4.{_j} llm_used=True -> review_passed=True: {_q!r:.28}", _r.review_passed)
    else:
        ok(f"G4.{_j} llm_used=False (review_passed={_r.review_passed}): {_q!r:.25}", True)

for _j, (_q, _r) in enumerate(zip(_SAMPLE_QUERIES, _responses), 1):
    # Invariant: when llm_used=False, final_text == response_text (debug bundle)
    if not _r.llm_used and _r.debug:
        ok(f"G5.{_j} not llm_used -> final_text == response_text: {_q!r:.25}",
           _r.final_text == _r.debug.response_text)
    else:
        ok(f"G5.{_j} llm_used=True (skipping fallback check): {_q!r:.28}", True)

# CLI output matches FinalResponse.final_text
for _j, _q in enumerate(_SAMPLE_QUERIES, 1):
    _expected_text = respond(_q, STANDARD_BOOTSTRAP).final_text
    _, _cli_out = run(_q, STANDARD_BOOTSTRAP, debug=False)
    ok(f"G6.{_j} CLI output == FinalResponse.final_text: {_q!r:.30}",
       _cli_out == _expected_text)

# ===========================================================================
# Section H -- Edge cases
# ===========================================================================
_section("H -- Edge cases")

# Ambiguous bootstrap
_code_h1, _out_h1 = run("should I captain Haaland", AMBIGUOUS_BOOTSTRAP)
ok("H1  captain query with ambiguous bootstrap does not crash", True)
ok("H2  ambiguous bootstrap returns string output", isinstance(_out_h1, str))
ok("H3  ambiguous bootstrap output is non-empty", len(_out_h1) > 0)

# Player not found
_code_h4, _out_h4 = run("should I captain Nonexistent Player XYZ", STANDARD_BOOTSTRAP)
ok("H4  player-not-found query does not crash", True)
ok("H5  player-not-found returns string output", isinstance(_out_h4, str))
ok("H6  player-not-found output is non-empty", len(_out_h4) > 0)
# not_found is still a supported intent response (supported=True)
ok("H7  player-not-found exit_code=0 (supported intent)", _code_h4 == 0)

# Debug mode with ambiguous bootstrap
_code_h8, _out_h8 = run("should I captain Haaland", AMBIGUOUS_BOOTSTRAP, debug=True)
ok("H8  debug mode with ambiguous bootstrap does not crash", True)
ok("H9  debug mode ambiguous output is valid JSON",
   len(_out_h8) > 0 and _out_h8.strip().startswith("{"))

# run() called twice in succession (no side effects)
_c1a, _o1a = run("should I captain Haaland", STANDARD_BOOTSTRAP)
_c1b, _o1b = run("should I captain Haaland", STANDARD_BOOTSTRAP)
ok("H10 successive calls produce same exit code", _c1a == _c1b)
ok("H11 successive calls produce same output",    _o1a == _o1b)

# debug bundle is populated when debug=True
_code_h12, _out_h12 = run("what is the current gameweek", STANDARD_BOOTSTRAP, debug=True)
try:
    _h12_json = json.loads(_out_h12)
    ok("H12 debug JSON includes 'debug' bundle", "debug" in _h12_json)
    ok("H13 debug bundle 'response_text' is non-empty",
       len(_h12_json.get("debug", {}).get("response_text", "")) > 0)
except json.JSONDecodeError:
    ok("H12 debug JSON parseable", False)
    ok("H13 debug bundle response_text non-empty", False)

# ===========================================================================
# Summary
# ===========================================================================
print()
print("=" * 60)
print(f"  Phase 4b: {_passed + _failed} assertions | {_passed} PASS | {_failed} FAIL")
print("=" * 60)

if _failed:
    sys.exit(1)
