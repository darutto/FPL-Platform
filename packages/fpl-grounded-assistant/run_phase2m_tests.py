"""
run_phase2m_tests.py
====================
Standalone Phase 2m validator — no pytest dependency, one-file runner.

Phase 2m: Minimal LLM adapter.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2m_tests.py

What is tested
--------------
New in Phase 2m:
    AdapterResponse          — frozen dataclass with 4 fields
    adapt()                  — model-facing entrypoint wrapping dispatch()

    Sections
    --------
A  — AdapterResponse dataclass: field names, count, frozen
B  — adapt() outcome=ok for all 5 supported intents → supported=True
C  — adapt() for unsupported questions → supported=False
D  — adapt() for recognised-but-unresolvable: not_found, ambiguous,
     missing_arguments → all supported=True
E  — response_text == dispatch_result.answer_text for all outcomes
F  — user_message preserved in AdapterResponse and dispatch_result.question
G  — dispatch_result is a DispatchResult instance on every adapt() call
H  — adapt() never raises (edge cases: empty string, whitespace)
I  — supported semantics match OUTCOME_UNSUPPORTED_INTENT exactly
J  — Phase 2l/2k regression: dispatch() still works; outcome constants intact
K  — Interface report

Fixture data (GW28 — same as prior slices for regression parity)
-----------------------------------------------------------------
Haaland (MCI, FWD, pen1) · Salah (LIV, MID, pen1) · Saka (ARS, MID, doubt)
De Bruyne (MCI, MID, injured)
Ambiguous bootstrap adds two "Doe" elements.
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
    print(f"\n--- Section {name} ---")


def ok(condition: bool, label: str) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {label}")


# ---------------------------------------------------------------------------
# Shared test fixtures (GW28)
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

_BS = {
    "elements":               _ELEMENTS,
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}

# Ambiguous bootstrap: two elements sharing web_name "Doe"
_BS_AMBIGUOUS = {
    "elements": _ELEMENTS + [
        {"id": 20, "first_name": "John",  "second_name": "Doe",
         "web_name": "Doe",  "team": 1,  "team_code": 3,  "element_type": 3,
         "status": "a", "now_cost": 60, "selected_by_percent": "1.0",
         "form": "3.0", "expected_goals": "0.10", "expected_assists": "0.10",
         "expected_goal_involvements": "0.20", "minutes": 900,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 21, "first_name": "Jane",  "second_name": "Doe",
         "web_name": "Doe",  "team": 8,  "team_code": 8,  "element_type": 2,
         "status": "a", "now_cost": 45, "selected_by_percent": "0.5",
         "form": "2.0", "expected_goals": "0.05", "expected_assists": "0.05",
         "expected_goal_involvements": "0.10", "minutes": 900,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
    ],
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}

_CANDIDATES_LIST = [{"query": "Haaland"}, {"query": "Salah"}]

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
from fpl_grounded_assistant import (
    adapt,
    AdapterResponse,
    DispatchResult,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
)

# ---------------------------------------------------------------------------
# Section A — AdapterResponse dataclass: field names, count, frozen
# ---------------------------------------------------------------------------
_section("A — AdapterResponse dataclass structure")

import dataclasses as _dc
_ar_fields = {f.name for f in _dc.fields(AdapterResponse)}

ok("user_message"    in _ar_fields, "A1 user_message field present")
ok("dispatch_result" in _ar_fields, "A2 dispatch_result field present")
ok("supported"       in _ar_fields, "A3 supported field present")
ok("response_text"   in _ar_fields, "A4 response_text field present")
ok(len(_ar_fields) == 4,            "A5 exactly 4 fields")

# frozen=True: reassignment must raise
_ar_probe = adapt("what gameweek is it", _BS)
try:
    _ar_probe.supported = False  # type: ignore[misc]
    ok(False, "A6 AdapterResponse is frozen (should have raised)")
except Exception:
    ok(True, "A6 AdapterResponse is frozen (reassignment raises)")

# ---------------------------------------------------------------------------
# Section B — adapt() outcome=ok for all 5 supported intents → supported=True
# ---------------------------------------------------------------------------
_section("B — adapt() supported=True for all 5 intents (outcome=ok)")

# B1: captain_score
_b1 = adapt("should I captain Haaland", _BS)
ok(_b1.supported,                              "B1 captain_score supported=True")
ok(_b1.dispatch_result.outcome == OUTCOME_OK,  "B1 captain_score outcome=ok")
ok(_b1.dispatch_result.intent == INTENT_CAPTAIN_SCORE, "B1 captain_score intent correct")

# B2: rank_candidates
_b2 = adapt("top captains this week", _BS, candidates_list=_CANDIDATES_LIST)
ok(_b2.supported,                               "B2 rank_candidates supported=True")
ok(_b2.dispatch_result.outcome == OUTCOME_OK,   "B2 rank_candidates outcome=ok")
ok(_b2.dispatch_result.intent == INTENT_RANK_CANDIDATES, "B2 rank_candidates intent correct")

# B3: current_gameweek
_b3 = adapt("what gameweek is it", _BS)
ok(_b3.supported,                                  "B3 current_gameweek supported=True")
ok(_b3.dispatch_result.outcome == OUTCOME_OK,      "B3 current_gameweek outcome=ok")
ok(_b3.dispatch_result.intent == INTENT_CURRENT_GAMEWEEK, "B3 current_gameweek intent correct")

# B4: player_summary
_b4 = adapt("summary for Salah", _BS)
ok(_b4.supported,                              "B4 player_summary supported=True")
ok(_b4.dispatch_result.outcome == OUTCOME_OK,  "B4 player_summary outcome=ok")
ok(_b4.dispatch_result.intent == INTENT_PLAYER_SUMMARY, "B4 player_summary intent correct")

# B5: player_resolve
_b5 = adapt("who is Haaland", _BS)
ok(_b5.supported,                              "B5 player_resolve supported=True")
ok(_b5.dispatch_result.outcome == OUTCOME_OK,  "B5 player_resolve outcome=ok")
ok(_b5.dispatch_result.intent == INTENT_PLAYER_RESOLVE, "B5 player_resolve intent correct")

# ---------------------------------------------------------------------------
# Section C — adapt() for unsupported questions → supported=False
# ---------------------------------------------------------------------------
_section("C — adapt() supported=False for unsupported questions")

_unsupported_qs = [
    "Is Haaland fit to play?",
    "Transfer advice for Salah",
    "Latest FPL news",
    "Price of Saka?",
    "Should I sell De Bruyne?",
    "",
    "Hello",
]
for _uq in _unsupported_qs:
    _ar = adapt(_uq, _BS)
    ok(not _ar.supported,                                       f"C supported=False for {_uq!r}")
    ok(_ar.dispatch_result.outcome == OUTCOME_UNSUPPORTED_INTENT, f"C outcome=unsupported_intent for {_uq!r}")
    ok(_ar.dispatch_result.intent == INTENT_UNSUPPORTED,          f"C intent=unsupported for {_uq!r}")
    ok(len(_ar.response_text) > 0,                              f"C response_text non-empty for {_uq!r}")

# ---------------------------------------------------------------------------
# Section D — supported=True for recognised-but-unresolvable outcomes
# ---------------------------------------------------------------------------
_section("D — adapt() supported=True even when execution cannot complete")

# D1: not_found — recognised intent, player doesn't exist
_d1 = adapt("should I captain xyznotaplayer999", _BS)
ok(_d1.supported,                                        "D1 not_found supported=True")
ok(_d1.dispatch_result.outcome == OUTCOME_NOT_FOUND,     "D1 not_found outcome=not_found")
ok(_d1.dispatch_result.intent == INTENT_CAPTAIN_SCORE,   "D1 not_found intent preserved")

_d2 = adapt("who is xyznotaplayer999", _BS)
ok(_d2.supported,                                        "D2 not_found resolve supported=True")
ok(_d2.dispatch_result.outcome == OUTCOME_NOT_FOUND,     "D2 not_found resolve outcome")

_d3 = adapt("summary for xyznotaplayer999", _BS)
ok(_d3.supported,                                        "D3 not_found summary supported=True")
ok(_d3.dispatch_result.outcome == OUTCOME_NOT_FOUND,     "D3 not_found summary outcome")

# D4: ambiguous — recognised intent, player name is ambiguous
_d4 = adapt("who is Doe", _BS_AMBIGUOUS)
ok(_d4.supported,                                        "D4 ambiguous supported=True")
ok(_d4.dispatch_result.outcome == OUTCOME_AMBIGUOUS,     "D4 ambiguous outcome=ambiguous")
ok(_d4.dispatch_result.intent == INTENT_PLAYER_RESOLVE,  "D4 ambiguous intent preserved")

_d5 = adapt("should I captain Doe", _BS_AMBIGUOUS)
ok(_d5.supported,                                        "D5 ambiguous captain supported=True")
ok(_d5.dispatch_result.outcome == OUTCOME_AMBIGUOUS,     "D5 ambiguous captain outcome")

# D6: missing_arguments — recognised intent, missing required input
_d6 = adapt("top captains this week", _BS)  # no candidates_list
ok(_d6.supported,                                            "D6 missing_args supported=True")
ok(_d6.dispatch_result.outcome == OUTCOME_MISSING_ARGUMENTS, "D6 missing_args outcome")
ok(_d6.dispatch_result.intent == INTENT_RANK_CANDIDATES,     "D6 missing_args intent preserved")

# ---------------------------------------------------------------------------
# Section E — response_text == dispatch_result.answer_text for all outcomes
# ---------------------------------------------------------------------------
_section("E — response_text mirrors dispatch_result.answer_text")

_e_cases = [
    adapt("should I captain Haaland", _BS),                       # ok
    adapt("Is Haaland fit?", _BS),                                 # unsupported
    adapt("should I captain xyznotaplayer999", _BS),               # not_found
    adapt("who is Doe", _BS_AMBIGUOUS),                            # ambiguous
    adapt("top captains this week", _BS),                          # missing_args
    adapt("top captains this week", _BS, candidates_list=_CANDIDATES_LIST),  # rank ok
]
for _i, _ec in enumerate(_e_cases):
    ok(_ec.response_text == _ec.dispatch_result.answer_text,
       f"E{_i+1} response_text == dispatch_result.answer_text")

# ---------------------------------------------------------------------------
# Section F — user_message preserved verbatim
# ---------------------------------------------------------------------------
_section("F — user_message preserved verbatim in AdapterResponse")

_f_messages = [
    "should I captain Haaland",
    "Is Haaland fit to play?",
    "top captains this week",
    "",
    "  whitespace  ",
]
for _msg in _f_messages:
    _far = adapt(_msg, _BS)
    ok(_far.user_message == _msg,
       f"F user_message preserved for {_msg!r}")
    ok(_far.dispatch_result.question == _msg,
       f"F dispatch_result.question preserved for {_msg!r}")

# ---------------------------------------------------------------------------
# Section G — dispatch_result is always a DispatchResult instance
# ---------------------------------------------------------------------------
_section("G — dispatch_result is always a DispatchResult instance")

_g_cases = [
    adapt("should I captain Haaland", _BS),
    adapt("Is Haaland fit?", _BS),
    adapt("top captains this week", _BS),
    adapt("who is Doe", _BS_AMBIGUOUS),
    adapt("summary for xyznotaplayer999", _BS),
]
for _i, _gc in enumerate(_g_cases):
    ok(isinstance(_gc.dispatch_result, DispatchResult),
       f"G{_i+1} dispatch_result is DispatchResult")

# ---------------------------------------------------------------------------
# Section H — adapt() never raises (edge cases)
# ---------------------------------------------------------------------------
_section("H — adapt() never raises on edge inputs")

_h_edge_cases = [
    ("", _BS),
    ("   ", _BS),
    ("?", _BS),
    ("!!!", _BS),
    ("a" * 500, _BS),  # very long input
]
for _msg, _bs in _h_edge_cases:
    try:
        _har = adapt(_msg, _bs)
        ok(isinstance(_har, AdapterResponse),
           f"H adapt() returns AdapterResponse for edge input {_msg[:20]!r}")
    except Exception as _exc:
        ok(False, f"H adapt() raised {type(_exc).__name__} for edge input {_msg[:20]!r}")

# ---------------------------------------------------------------------------
# Section I — supported semantics: only OUTCOME_UNSUPPORTED_INTENT → False
# ---------------------------------------------------------------------------
_section("I — supported flag semantics match OUTCOME_UNSUPPORTED_INTENT exactly")

# All non-unsupported outcomes must yield supported=True
_i_supported_cases = [
    adapt("should I captain Haaland", _BS),                           # OUTCOME_OK
    adapt("should I captain xyznotaplayer999", _BS),                   # OUTCOME_NOT_FOUND
    adapt("who is Doe", _BS_AMBIGUOUS),                                # OUTCOME_AMBIGUOUS
    adapt("top captains this week", _BS),                              # OUTCOME_MISSING_ARGUMENTS
    adapt("top captains this week", _BS, candidates_list=_CANDIDATES_LIST),  # OUTCOME_OK
]
for _ic in _i_supported_cases:
    ok(_ic.supported is True,
       f"I supported=True when outcome={_ic.dispatch_result.outcome!r}")
    ok(_ic.dispatch_result.outcome != OUTCOME_UNSUPPORTED_INTENT,
       f"I outcome is not unsupported_intent when supported=True")

# All unsupported questions must yield supported=False
_i_unsupported_cases = [
    adapt("Is Haaland fit?", _BS),
    adapt("Transfer advice", _BS),
    adapt("", _BS),
]
for _ic in _i_unsupported_cases:
    ok(_ic.supported is False,
       f"I supported=False when outcome={_ic.dispatch_result.outcome!r}")
    ok(_ic.dispatch_result.outcome == OUTCOME_UNSUPPORTED_INTENT,
       f"I outcome=unsupported_intent when supported=False")

# ---------------------------------------------------------------------------
# Section J — Phase 2l/2k regression
# ---------------------------------------------------------------------------
_section("J — Phase 2l/2k regression: dispatch() and OUTCOME_* intact")

# dispatch() is still importable and returns DispatchResult directly
from fpl_grounded_assistant import dispatch
_j1 = dispatch("should I captain Haaland", _BS)
ok(isinstance(_j1, DispatchResult),              "J1 dispatch() still returns DispatchResult")
ok(_j1.outcome == OUTCOME_OK,                    "J2 dispatch() outcome=ok for known player")
ok(_j1.intent == INTENT_CAPTAIN_SCORE,           "J3 dispatch() intent=captain_score")

# OUTCOME_* constants still correct
ok(OUTCOME_OK == "ok",                           "J4 OUTCOME_OK value unchanged")
ok(OUTCOME_UNSUPPORTED_INTENT == "unsupported_intent", "J5 OUTCOME_UNSUPPORTED_INTENT unchanged")
ok(OUTCOME_NOT_FOUND == "not_found",             "J6 OUTCOME_NOT_FOUND unchanged")
ok(OUTCOME_AMBIGUOUS == "ambiguous",             "J7 OUTCOME_AMBIGUOUS unchanged")
ok(OUTCOME_MISSING_ARGUMENTS == "missing_arguments", "J8 OUTCOME_MISSING_ARGUMENTS unchanged")

# adapt() result is consistent with underlying dispatch()
_j2a = adapt("who is Salah", _BS)
_j2b = dispatch("who is Salah", _BS)
ok(_j2a.dispatch_result.intent  == _j2b.intent,       "J9 adapt intent == dispatch intent")
ok(_j2a.dispatch_result.outcome == _j2b.outcome,      "J10 adapt outcome == dispatch outcome")
ok(_j2a.response_text           == _j2b.answer_text,  "J11 adapt response_text == dispatch answer_text")

# ---------------------------------------------------------------------------
# Section K — Interface report
# ---------------------------------------------------------------------------
_section("K — Interface report")

print()
print("  Phase 2m exports:")
print(f"    adapt()          → AdapterResponse")
print(f"    AdapterResponse  fields: {sorted(_ar_fields)}")
print()
print("  AdapterResponse semantics:")
print(f"    supported=True   → intent was recognised (any outcome except unsupported_intent)")
print(f"    supported=False  → intent not recognised (outcome=unsupported_intent)")
print()
print("  Sample adapt() calls:")

_k_ok = adapt("should I captain Salah", _BS)
print(f"    [ok]           user_message: {_k_ok.user_message!r}")
print(f"                   supported:    {_k_ok.supported}")
print(f"                   outcome:      {_k_ok.dispatch_result.outcome}")
print(f"                   response:     {_k_ok.response_text[:80]}...")

_k_unsup = adapt("Is Salah injured?", _BS)
print(f"    [unsupported]  user_message: {_k_unsup.user_message!r}")
print(f"                   supported:    {_k_unsup.supported}")
print(f"                   outcome:      {_k_unsup.dispatch_result.outcome}")
print(f"                   response:     {_k_unsup.response_text}")

_k_nf = adapt("should I captain xyznotaplayer", _BS)
print(f"    [not_found]    user_message: {_k_nf.user_message!r}")
print(f"                   supported:    {_k_nf.supported}")
print(f"                   outcome:      {_k_nf.dispatch_result.outcome}")
print(f"                   response:     {_k_nf.response_text[:80]}")

_k_miss = adapt("top captains this week", _BS)
print(f"    [missing_args] user_message: {_k_miss.user_message!r}")
print(f"                   supported:    {_k_miss.supported}")
print(f"                   outcome:      {_k_miss.dispatch_result.outcome}")
print(f"                   response:     {_k_miss.response_text}")

print()
print("  Intentionally deferred:")
_deferred = [
    "LLM-based intent classification",
    "Multi-turn conversation memory",
    "Pronoun resolution ('What about his form?')",
    "Combined intents ('Who is Salah and what gameweek is it?')",
    "Freeform response generation",
    "UI integration",
]
for _d in _deferred:
    print(f"    - {_d}")

ok(True, "K interface report printed")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print(f"Phase 2m adapter tests: {_passed}/{_passed + _failed} PASS")
if _failed == 0:
    print("ALL ASSERTIONS PASS")
else:
    print(f"FAILURES: {_failed}")
    sys.exit(1)


