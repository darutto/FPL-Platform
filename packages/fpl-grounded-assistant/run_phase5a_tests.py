"""
run_phase5a_tests.py
====================
Phase 5a: deterministic two-player captain comparison.

Validates that comparison routing, scoring, dispatch, and integration
all work correctly using STANDARD_BOOTSTRAP.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5a_tests.py

Sections
--------
A  -- Imports and module shape
B  -- Router detection (various phrasings → compare_players)
C  -- compare_players function (Haaland vs Salah, error paths)
D  -- dispatch() integration
E  -- Error cases (not_found, ambiguous player)
F  -- respond() integration
G  -- Single-player captain score regression
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


# ===========================================================================
# Section A -- Imports and module shape
# ===========================================================================

print("A  Imports and module shape")

from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    INTENT_COMPARE_PLAYERS,
    SUPPORTED_INTENTS,
    INTENT_MANIFEST,
    _TOOL_TO_INTENT,
    compare_players,
    dispatch,
    respond,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_UNSUPPORTED_INTENT,
)
from fpl_grounded_assistant.router import (
    route,
    _COMPARE_PREFIXES,
    _COMPARE_CONNECTORS,
    _try_route_comparison,
)
from fpl_grounded_assistant.comparison import (
    _derive_scoring_inputs,
    _score_one,
)

ok("A1  INTENT_COMPARE_PLAYERS value",          INTENT_COMPARE_PLAYERS == "compare_players")
ok("A2  INTENT_COMPARE_PLAYERS in SUPPORTED",   INTENT_COMPARE_PLAYERS in SUPPORTED_INTENTS)
ok("A3  compare_players in _TOOL_TO_INTENT",    "compare_players" in _TOOL_TO_INTENT)
eq("A4  _TOOL_TO_INTENT maps to intent",
   _TOOL_TO_INTENT["compare_players"], INTENT_COMPARE_PLAYERS)
ok("A5  INTENT_COMPARE_PLAYERS in MANIFEST",    INTENT_COMPARE_PLAYERS in INTENT_MANIFEST)
ok("A6  manifest has tool field",               INTENT_MANIFEST[INTENT_COMPARE_PLAYERS]["tool"] == "compare_players")
ok("A7  manifest has description",              bool(INTENT_MANIFEST[INTENT_COMPARE_PLAYERS].get("description")))
ok("A8  manifest has example_phrasings",        len(INTENT_MANIFEST[INTENT_COMPARE_PLAYERS]["example_phrasings"]) >= 3)
ok("A9  compare_players callable",              callable(compare_players))
ok("A10 _COMPARE_PREFIXES non-empty tuple",     isinstance(_COMPARE_PREFIXES, tuple) and len(_COMPARE_PREFIXES) >= 4)
ok("A11 _COMPARE_CONNECTORS non-empty tuple",   isinstance(_COMPARE_CONNECTORS, tuple) and len(_COMPARE_CONNECTORS) >= 2)
ok("A12 _try_route_comparison callable",        callable(_try_route_comparison))


# ===========================================================================
# Section B -- Router detection
# ===========================================================================

print("B  Router detection")

def _route_compare(q: str):
    r = route(q)
    if r is None or r.tool_name != "compare_players":
        return None
    return r.tool_args


# "compare X and Y"
_b1 = _route_compare("compare Haaland and Salah")
ok("B1  compare...and routed",              _b1 is not None)
ok("B2  query_a = Haaland",                 _b1 and _b1["query_a"] == "Haaland")
ok("B3  query_b = Salah",                   _b1 and _b1["query_b"] == "Salah")

# "compare X vs Y"
_b4 = _route_compare("compare Saka vs Salah")
ok("B4  compare...vs routed",               _b4 is not None)
ok("B5  query_a = Saka",                    _b4 and _b4["query_a"] == "Saka")
ok("B6  query_b = Salah",                   _b4 and _b4["query_b"] == "Salah")

# "X vs Y" bare
_b7 = _route_compare("Haaland vs Salah")
ok("B7  bare X vs Y routed",                _b7 is not None)
ok("B8  query_a = Haaland (bare vs)",       _b7 and _b7["query_a"] == "Haaland")
ok("B9  query_b = Salah (bare vs)",         _b7 and _b7["query_b"] == "Salah")

# "X versus Y"
_b10 = _route_compare("Haaland versus Salah")
ok("B10 X versus Y routed",                 _b10 is not None)

# "who is better X or Y"
_b11 = _route_compare("who is better Haaland or Salah")
ok("B11 who is better...or routed",         _b11 is not None)
ok("B12 query_a = Haaland (who is better)", _b11 and _b11["query_a"] == "Haaland")
ok("B13 query_b = Salah (who is better)",   _b11 and _b11["query_b"] == "Salah")

# "who is better, X or Y" (comma after better)
_b14 = _route_compare("who is better, Haaland or Salah")
ok("B14 who is better comma form routed",   _b14 is not None)

# Single-player captain question NOT routed as comparison
_b15 = route("should I captain Haaland")
ok("B15 single captain → get_captain_score", _b15 is not None and _b15.tool_name == "get_captain_score")

# "rank captains" NOT routed as comparison
_b16 = route("top captains this week")
ok("B16 top captains → rank not compare",   _b16 is not None and _b16.tool_name == "rank_captain_candidates")

# Unrelated question NOT routed as comparison
_b17 = route("what is the current gameweek")
ok("B17 gameweek → not compare",            _b17 is not None and _b17.tool_name == "get_current_gameweek")


# ===========================================================================
# Section C -- compare_players function
# ===========================================================================

print("C  compare_players function")

_c_result = compare_players("Haaland", "Salah", STANDARD_BOOTSTRAP)

eq("C1  status ok",                 _c_result["status"], "ok")
eq("C2  query_a preserved",         _c_result["query_a"], "Haaland")
eq("C3  query_b preserved",         _c_result["query_b"], "Salah")
ok("C4  player_a web_name present", bool(_c_result.get("player_a", {}).get("web_name")))
ok("C5  player_b web_name present", bool(_c_result.get("player_b", {}).get("web_name")))
ok("C6  player_a has captain_score",isinstance(_c_result["player_a"]["captain_score"], float))
ok("C7  player_b has captain_score",isinstance(_c_result["player_b"]["captain_score"], float))
ok("C8  player_a has tier",         bool(_c_result["player_a"].get("tier")))
ok("C9  player_b has tier",         bool(_c_result["player_b"].get("tier")))
ok("C10 player_a has reasons list", isinstance(_c_result["player_a"].get("reasons"), list))
ok("C11 player_b has reasons list", isinstance(_c_result["player_b"].get("reasons"), list))
ok("C12 player_a has score_inputs", isinstance(_c_result["player_a"].get("score_inputs"), dict))
ok("C13 player_b has score_inputs", isinstance(_c_result["player_b"].get("score_inputs"), dict))
ok("C14 score_inputs has form",     "form" in _c_result["player_a"]["score_inputs"])
ok("C15 score_inputs has fdr",      "fixture_difficulty" in _c_result["player_a"]["score_inputs"])
ok("C16 score_inputs has xgi_per_90","xgi_per_90" in _c_result["player_a"]["score_inputs"])
ok("C17 score_inputs has risk",     "minutes_risk" in _c_result["player_a"]["score_inputs"])
ok("C18 winner is string or None",  _c_result.get("winner") is None or isinstance(_c_result["winner"], str))
ok("C19 margin is float",           isinstance(_c_result.get("margin"), float))
ok("C20 recommendation non-empty",  bool(_c_result.get("recommendation")))

# Verify scores are distinct and match expected values from STANDARD_BOOTSTRAP
_score_h = _c_result["player_a"]["captain_score"]
_score_s = _c_result["player_b"]["captain_score"]
ok("C21 scores are distinct",       _score_h != _score_s)
ok("C22 Salah wins",                _c_result["winner"] == "Salah")
ok("C23 Haaland score ~54.85",      abs(_score_h - 54.85) < 0.5)
ok("C24 Salah score ~60.58",        abs(_score_s - 60.58) < 0.5)
ok("C25 margin ~5.73",              abs(_c_result["margin"] - 5.73) < 0.5)

# recommendation mentions both names
ok("C26 recommendation mentions Salah",   "Salah" in _c_result["recommendation"])
ok("C27 recommendation mentions Haaland", "Haaland" in _c_result["recommendation"])

# Symmetric comparison — same winner
_c_sym = compare_players("Salah", "Haaland", STANDARD_BOOTSTRAP)
eq("C28 symmetric status ok",       _c_sym["status"], "ok")
eq("C29 symmetric winner = Salah",  _c_sym["winner"], "Salah")

# Tied comparison — same player
_c_tied = compare_players("Haaland", "Haaland", STANDARD_BOOTSTRAP)
eq("C30 same-player status ok",     _c_tied["status"], "ok")
eq("C31 same-player winner = None", _c_tied["winner"], None)
eq("C32 same-player margin = 0.0",  _c_tied["margin"], 0.0)


# ===========================================================================
# Section D -- dispatch() integration
# ===========================================================================

print("D  dispatch() integration")

_d1 = dispatch("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("D1  intent = compare_players",  _d1.intent, INTENT_COMPARE_PLAYERS)
eq("D2  selected_tool",             _d1.selected_tool, "compare_players")
eq("D3  outcome ok",                _d1.outcome, OUTCOME_OK)
ok("D4  answer_text non-empty",     bool(_d1.answer_text))
ok("D5  raw_output status ok",      _d1.raw_output.get("status") == "ok")
ok("D6  raw_output has winner",     "winner" in _d1.raw_output)

_d2 = dispatch("Haaland vs Salah", STANDARD_BOOTSTRAP)
eq("D7  bare vs intent",            _d2.intent, INTENT_COMPARE_PLAYERS)
eq("D8  bare vs outcome ok",        _d2.outcome, OUTCOME_OK)

_d3 = dispatch("who is better, Haaland or Salah", STANDARD_BOOTSTRAP)
eq("D9  who is better intent",      _d3.intent, INTENT_COMPARE_PLAYERS)
eq("D10 who is better outcome ok",  _d3.outcome, OUTCOME_OK)


# ===========================================================================
# Section E -- Error cases
# ===========================================================================

print("E  Error cases")

# Player not found
_e1 = compare_players("Haaland", "NotARealPlayer99999", STANDARD_BOOTSTRAP)
eq("E1  not_found status",          _e1["status"], "not_found")
eq("E2  query_a preserved",         _e1["query_a"], "Haaland")
eq("E3  query_b preserved",         _e1["query_b"], "NotARealPlayer99999")
eq("E4  error_player = query_b",    _e1["error_player"], "NotARealPlayer99999")
ok("E5  message non-empty",         bool(_e1.get("message")))

# Player not found on left side
_e2 = compare_players("NotARealPlayer99999", "Salah", STANDARD_BOOTSTRAP)
eq("E6  not_found left status",     _e2["status"], "not_found")
eq("E7  error_player = query_a",    _e2["error_player"], "NotARealPlayer99999")

# dispatch with not_found
_e3 = dispatch("compare Haaland and NotARealPlayer99999", STANDARD_BOOTSTRAP)
eq("E8  dispatch not_found outcome",_e3.outcome, OUTCOME_NOT_FOUND)
eq("E9  dispatch not_found intent", _e3.intent, INTENT_COMPARE_PLAYERS)

# Unroutable question still returns unsupported
_e4 = dispatch("is Haaland fit to play?", STANDARD_BOOTSTRAP)
eq("E10 unrelated intent unsupported", _e4.outcome, OUTCOME_UNSUPPORTED_INTENT)


# ===========================================================================
# Section F -- respond() integration
# ===========================================================================

print("F  respond() integration")

_f1 = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
ok("F1  final_text non-empty",      bool(_f1.final_text))
ok("F2  supported True",            _f1.supported is True)
eq("F3  outcome ok",                _f1.outcome, OUTCOME_OK)
ok("F4  final_text mentions Salah", "Salah" in _f1.final_text)

_f2 = respond("Haaland vs Salah", STANDARD_BOOTSTRAP)
ok("F5  bare vs final_text non-empty", bool(_f2.final_text))
eq("F6  bare vs outcome ok",           _f2.outcome, OUTCOME_OK)

_f3 = respond("compare Haaland and NotARealPlayer99999", STANDARD_BOOTSTRAP)
ok("F7  not_found final_text non-empty", bool(_f3.final_text))
ok("F8  not_found supported True",       _f3.supported is True)   # intent recognised, player missing


# ===========================================================================
# Section G -- Single-player captain score regression
# ===========================================================================

print("G  Single-player regression")

_g1 = dispatch("should I captain Haaland", STANDARD_BOOTSTRAP)
ok("G1  captain score intent",      _g1.intent == "captain_score")
ok("G2  captain score outcome ok",  _g1.outcome == OUTCOME_OK)
ok("G3  captain score answer_text", bool(_g1.answer_text))

_g2 = dispatch("top captains this week", STANDARD_BOOTSTRAP)
ok("G4  rank candidates intent",    _g2.intent == "rank_candidates")

_g3 = dispatch("what is the current gameweek", STANDARD_BOOTSTRAP)
ok("G5  gameweek intent",           _g3.intent == "current_gameweek")

_g4 = dispatch("tell me about Salah", STANDARD_BOOTSTRAP)
ok("G6  player summary intent",     _g4.intent == "player_summary")

_g5 = dispatch("who is Haaland", STANDARD_BOOTSTRAP)
ok("G7  player resolve intent",     _g5.intent == "player_resolve")

# Single-player respond regression
_g6 = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok("G8  single respond ok",         _g6.outcome == OUTCOME_OK)
ok("G9  single respond non-empty",  bool(_g6.final_text))


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5a: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
