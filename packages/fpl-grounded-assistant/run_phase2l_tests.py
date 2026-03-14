"""
run_phase2l_tests.py
====================
Standalone Phase 2l validator — no pytest dependency, one-file runner.

Phase 2l: Dispatcher coverage hardening and intent table formalization.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2l_tests.py

What is tested
--------------
New in Phase 2l:
    INTENT_MANIFEST              — formal intent table (5 entries)
    OUTCOME_* constants          — 6 unified outcome labels
    DispatchResult.outcome       — new field on frozen dataclass
    _compute_outcome             — unified outcome derivation (via dispatch)

Sections
--------
A  — INTENT_MANIFEST structure: keys, required fields, tool mappings,
     requires_* flags, example_phrasings non-empty
B  — OUTCOME_* constants: string values correct, all distinct
C  — DispatchResult.outcome field present; field count now 7
D  — outcome=ok for all 5 supported intents (successful dispatches)
E  — outcome=unsupported_intent for unroutable questions; safe DispatchResult
F  — outcome=missing_arguments when rank_candidates called without candidates_list;
     improved answer_text contains "candidates_list"
G  — outcome=not_found for non-existent player queries
H  — outcome=ambiguous when two players share web_name
I  — Phrasing coverage: captain_score intent
J  — Phrasing coverage: rank_candidates intent
K  — Phrasing coverage: current_gameweek intent
L  — Phrasing coverage: player_summary intent
M  — Phrasing coverage: player_resolve intent
N  — Unsupported phrasings negative tests (should not route)
O  — INTENT_MANIFEST example_phrasings all route to the expected tool
P  — Phase 2k regression: existing dispatch behaviour unchanged
Q  — Interface report

Fixture data (GW28 — same as Phase 2d/2e/2f/2g/2h/2k for regression parity)
-----------------------------------------------------------------------------
Same teams, elements, events as Phase 2k.
Ambiguous fixture adds two elements with web_name="Doe" for Section H.
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
_DOE_1 = {
    "id": 20, "first_name": "John",  "second_name": "Doe",
    "web_name": "Doe",  "team": 1,  "team_code": 3,  "element_type": 3,
    "status": "a", "now_cost": 60, "selected_by_percent": "1.0",
    "form": "3.0", "expected_goals": "0.10", "expected_assists": "0.10",
    "expected_goal_involvements": "0.20", "minutes": 900,
    "penalties_order": None, "direct_freekicks_order": None,
    "corners_and_indirect_freekicks_order": None,
}
_DOE_2 = {
    "id": 21, "first_name": "Jane",  "second_name": "Doe",
    "web_name": "Doe",  "team": 8,  "team_code": 8,  "element_type": 2,
    "status": "a", "now_cost": 45, "selected_by_percent": "0.5",
    "form": "2.0", "expected_goals": "0.05", "expected_assists": "0.05",
    "expected_goal_involvements": "0.10", "minutes": 900,
    "penalties_order": None, "direct_freekicks_order": None,
    "corners_and_indirect_freekicks_order": None,
}
_BS_AMBIGUOUS = {
    "elements":               _ELEMENTS + [_DOE_1, _DOE_2],
    "teams":                  _TEAMS,
    "events":                 _EVENTS,
    "element_types":          _ELEMENT_TYPES,
    "fixture_difficulty_map": _FDR_MAP,
}

# Candidates list for rank_captain_candidates
_CANDIDATES_LIST = [
    {"query": "Haaland"},
    {"query": "Salah"},
]

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
from fpl_grounded_assistant import (
    dispatch,
    DispatchResult,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
    SUPPORTED_INTENTS,
    _TOOL_TO_INTENT,
    INTENT_MANIFEST,
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
)
from fpl_grounded_assistant.router import route

# ---------------------------------------------------------------------------
# Section A — INTENT_MANIFEST structure
# ---------------------------------------------------------------------------
_section("A — INTENT_MANIFEST structure")

_EXPECTED_INTENT_KEYS = {
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
}
ok(set(INTENT_MANIFEST.keys()) == _EXPECTED_INTENT_KEYS,
   "A1 INTENT_MANIFEST has exactly the 5 supported intent keys")
ok(set(INTENT_MANIFEST.keys()) == SUPPORTED_INTENTS,
   "A2 INTENT_MANIFEST keys == SUPPORTED_INTENTS")

_REQUIRED_ENTRY_FIELDS = {"tool", "description", "requires_player_query",
                           "requires_candidates_list", "example_phrasings"}
for _intent_key, _entry in INTENT_MANIFEST.items():
    ok(set(_entry.keys()) >= _REQUIRED_ENTRY_FIELDS,
       f"A3 INTENT_MANIFEST[{_intent_key!r}] has all required fields")

# Tool values match _TOOL_TO_INTENT (reverse mapping check)
_EXPECTED_TOOL_MAP = {v: k for k, v in _TOOL_TO_INTENT.items()}
for _intent_key, _entry in INTENT_MANIFEST.items():
    ok(_entry["tool"] == _EXPECTED_TOOL_MAP.get(_intent_key),
       f"A4 INTENT_MANIFEST[{_intent_key!r}].tool matches _TOOL_TO_INTENT")

# requires_player_query flags
ok(INTENT_MANIFEST[INTENT_CAPTAIN_SCORE]["requires_player_query"]    is True,  "A5 captain_score requires_player_query=True")
ok(INTENT_MANIFEST[INTENT_RANK_CANDIDATES]["requires_player_query"]  is False, "A6 rank_candidates requires_player_query=False")
ok(INTENT_MANIFEST[INTENT_CURRENT_GAMEWEEK]["requires_player_query"] is False, "A7 current_gameweek requires_player_query=False")
ok(INTENT_MANIFEST[INTENT_PLAYER_SUMMARY]["requires_player_query"]   is True,  "A8 player_summary requires_player_query=True")
ok(INTENT_MANIFEST[INTENT_PLAYER_RESOLVE]["requires_player_query"]   is True,  "A9 player_resolve requires_player_query=True")

# requires_candidates_list flags
ok(INTENT_MANIFEST[INTENT_CAPTAIN_SCORE]["requires_candidates_list"]    is False, "A10 captain_score requires_candidates_list=False")
ok(INTENT_MANIFEST[INTENT_RANK_CANDIDATES]["requires_candidates_list"]  is True,  "A11 rank_candidates requires_candidates_list=True")
ok(INTENT_MANIFEST[INTENT_CURRENT_GAMEWEEK]["requires_candidates_list"] is False, "A12 current_gameweek requires_candidates_list=False")
ok(INTENT_MANIFEST[INTENT_PLAYER_SUMMARY]["requires_candidates_list"]   is False, "A13 player_summary requires_candidates_list=False")
ok(INTENT_MANIFEST[INTENT_PLAYER_RESOLVE]["requires_candidates_list"]   is False, "A14 player_resolve requires_candidates_list=False")

# example_phrasings non-empty list for every entry
for _intent_key, _entry in INTENT_MANIFEST.items():
    _ep = _entry.get("example_phrasings")
    ok(isinstance(_ep, list) and len(_ep) > 0,
       f"A15 INTENT_MANIFEST[{_intent_key!r}].example_phrasings is non-empty list")

# ---------------------------------------------------------------------------
# Section B — OUTCOME_* constants
# ---------------------------------------------------------------------------
_section("B — OUTCOME_* constants")

ok(OUTCOME_OK                 == "ok",                 "B1 OUTCOME_OK value")
ok(OUTCOME_UNSUPPORTED_INTENT == "unsupported_intent", "B2 OUTCOME_UNSUPPORTED_INTENT value")
ok(OUTCOME_NOT_FOUND          == "not_found",          "B3 OUTCOME_NOT_FOUND value")
ok(OUTCOME_AMBIGUOUS          == "ambiguous",          "B4 OUTCOME_AMBIGUOUS value")
ok(OUTCOME_MISSING_ARGUMENTS  == "missing_arguments",  "B5 OUTCOME_MISSING_ARGUMENTS value")
ok(OUTCOME_ERROR              == "error",              "B6 OUTCOME_ERROR value")

_all_outcome_values = [
    OUTCOME_OK, OUTCOME_UNSUPPORTED_INTENT, OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS, OUTCOME_MISSING_ARGUMENTS, OUTCOME_ERROR,
]
ok(len(set(_all_outcome_values)) == 6,
   "B7 all 6 OUTCOME_* constants are distinct strings")

# ---------------------------------------------------------------------------
# Section C — DispatchResult.outcome field and total field count
# ---------------------------------------------------------------------------
_section("C — DispatchResult.outcome field present; field count == 7")
import dataclasses as _dc
_fields = {f.name for f in _dc.fields(DispatchResult)}

ok("outcome" in _fields, "C1 DispatchResult.outcome field present")
ok(len(_fields) == 7,    "C2 DispatchResult has exactly 7 fields")

# Confirm all expected field names are present
for _fname in ("intent", "question", "selected_tool", "raw_output",
               "answer_text", "context_meta", "outcome"):
    ok(_fname in _fields, f"C3 field {_fname!r} present in DispatchResult")

# ---------------------------------------------------------------------------
# Section D — outcome=ok for all 5 supported intents (success path)
# ---------------------------------------------------------------------------
_section("D — outcome=ok for all 5 supported intents")

# D1: captain_score
_d1 = dispatch("should I captain Haaland", _BS)
ok(_d1.outcome == OUTCOME_OK,          "D1 captain_score outcome=ok")
ok(_d1.intent  == INTENT_CAPTAIN_SCORE, "D1 captain_score intent correct")

# D2: rank_candidates (with candidates_list)
_d2 = dispatch("top captains this week", _BS, candidates_list=_CANDIDATES_LIST)
ok(_d2.outcome == OUTCOME_OK,            "D2 rank_candidates outcome=ok")
ok(_d2.intent  == INTENT_RANK_CANDIDATES, "D2 rank_candidates intent correct")

# D3: current_gameweek
_d3 = dispatch("what gameweek is it", _BS)
ok(_d3.outcome == OUTCOME_OK,              "D3 current_gameweek outcome=ok")
ok(_d3.intent  == INTENT_CURRENT_GAMEWEEK, "D3 current_gameweek intent correct")

# D4: player_summary
_d4 = dispatch("summary for Salah", _BS)
ok(_d4.outcome == OUTCOME_OK,           "D4 player_summary outcome=ok")
ok(_d4.intent  == INTENT_PLAYER_SUMMARY, "D4 player_summary intent correct")

# D5: player_resolve
_d5 = dispatch("who is Haaland", _BS)
ok(_d5.outcome == OUTCOME_OK,           "D5 player_resolve outcome=ok")
ok(_d5.intent  == INTENT_PLAYER_RESOLVE, "D5 player_resolve intent correct")

# ---------------------------------------------------------------------------
# Section E — outcome=unsupported_intent for unroutable questions
# ---------------------------------------------------------------------------
_section("E — outcome=unsupported_intent for unroutable questions")

_unsupported_qs = [
    "Is Haaland fit to play?",
    "Transfer advice for Salah",
    "Latest FPL news",
    "Price of Saka?",
    "Should I sell De Bruyne?",
    "",
    "Hello there",
]
for _uq in _unsupported_qs:
    _ur = dispatch(_uq, _BS)
    ok(_ur.outcome       == OUTCOME_UNSUPPORTED_INTENT, f"E outcome=unsupported_intent for {_uq!r}")
    ok(_ur.intent        == INTENT_UNSUPPORTED,         f"E intent=unsupported for {_uq!r}")
    ok(_ur.selected_tool is None,                       f"E selected_tool=None for {_uq!r}")
    ok(len(_ur.answer_text) > 0,                        f"E answer_text non-empty for {_uq!r}")
    ok(_ur.raw_output.get("status") == "unsupported",   f"E raw_output status=unsupported for {_uq!r}")
    ok(_ur.raw_output.get("code")   == "unsupported_intent", f"E raw_output code=unsupported_intent for {_uq!r}")

# ---------------------------------------------------------------------------
# Section F — outcome=missing_arguments (rank_candidates without candidates_list)
# ---------------------------------------------------------------------------
_section("F — outcome=missing_arguments; improved answer_text for rank_candidates")

_f1 = dispatch("top captains this week", _BS)  # no candidates_list
ok(_f1.outcome == OUTCOME_MISSING_ARGUMENTS, "F1 outcome=missing_arguments")
ok(_f1.intent  == INTENT_RANK_CANDIDATES,    "F2 intent=rank_candidates")
ok("candidates_list" in _f1.answer_text,     "F3 answer_text mentions 'candidates_list'")
ok(len(_f1.answer_text) > 0,                 "F4 answer_text non-empty")

_f2 = dispatch("captain rankings", _BS)  # another ranking phrasing, no candidates_list
ok(_f2.outcome == OUTCOME_MISSING_ARGUMENTS, "F5 captain rankings also gives missing_arguments")
ok("candidates_list" in _f2.answer_text,     "F6 answer_text mentions 'candidates_list'")

# Confirm that WITH candidates_list the outcome is ok (not missing_arguments)
_f3 = dispatch("top captains this week", _BS, candidates_list=_CANDIDATES_LIST)
ok(_f3.outcome == OUTCOME_OK,                "F7 with candidates_list outcome=ok")

# ---------------------------------------------------------------------------
# Section G — outcome=not_found for unknown player queries
# ---------------------------------------------------------------------------
_section("G — outcome=not_found for unknown player queries")

_g1 = dispatch("should I captain xyznotaplayer999", _BS)
ok(_g1.outcome == OUTCOME_NOT_FOUND,         "G1 captain_score unknown player → not_found")
ok(_g1.intent  == INTENT_CAPTAIN_SCORE,      "G2 captain_score intent preserved even on not_found")

_g2 = dispatch("who is xyznotaplayer999", _BS)
ok(_g2.outcome == OUTCOME_NOT_FOUND,         "G3 player_resolve unknown player → not_found")
ok(_g2.intent  == INTENT_PLAYER_RESOLVE,     "G4 player_resolve intent preserved even on not_found")

_g3 = dispatch("summary for xyznotaplayer999", _BS)
ok(_g3.outcome == OUTCOME_NOT_FOUND,         "G5 player_summary unknown player → not_found")
ok(_g3.intent  == INTENT_PLAYER_SUMMARY,     "G6 player_summary intent preserved even on not_found")

# ---------------------------------------------------------------------------
# Section H — outcome=ambiguous when two players share web_name
# ---------------------------------------------------------------------------
_section("H — outcome=ambiguous (two players share web_name 'Doe')")

_h1 = dispatch("who is Doe", _BS_AMBIGUOUS)
ok(_h1.outcome == OUTCOME_AMBIGUOUS,      "H1 player_resolve ambiguous web_name → ambiguous")
ok(_h1.intent  == INTENT_PLAYER_RESOLVE,  "H2 intent=player_resolve preserved")

_h2 = dispatch("summary for Doe", _BS_AMBIGUOUS)
ok(_h2.outcome == OUTCOME_AMBIGUOUS,      "H3 player_summary ambiguous web_name → ambiguous")
ok(_h2.intent  == INTENT_PLAYER_SUMMARY,  "H4 intent=player_summary preserved")

_h3 = dispatch("should I captain Doe", _BS_AMBIGUOUS)
ok(_h3.outcome == OUTCOME_AMBIGUOUS,      "H5 captain_score ambiguous web_name → ambiguous")
ok(_h3.intent  == INTENT_CAPTAIN_SCORE,   "H6 intent=captain_score preserved")

# ---------------------------------------------------------------------------
# Section I — Phrasing coverage: captain_score intent
# ---------------------------------------------------------------------------
_section("I — Phrasing coverage: captain_score")

_CAPTAIN_SCORE_PHRASINGS = [
    "should I captain Haaland",
    "should i captain salah",
    "captain score for Haaland",
    "captaincy for Salah",
    "get captain score for Haaland",
    "get the captain score for Salah",
    "what is the captain score for Haaland",
    "captain pick Salah",
    "should I pick Haaland as captain",
]
for _p in _CAPTAIN_SCORE_PHRASINGS:
    _rr = route(_p)
    ok(_rr is not None and _rr.tool_name == "get_captain_score",
       f"I route {_p!r} → get_captain_score")

# ---------------------------------------------------------------------------
# Section J — Phrasing coverage: rank_candidates intent
# ---------------------------------------------------------------------------
_section("J — Phrasing coverage: rank_candidates")

_RANK_PHRASINGS = [
    "top captains this week",
    "top captains",
    "captain rankings",
    "captain ranking",
    "rank my captains",
    "best captains",
    "rank captain candidates",
    "rank candidates",
    "give me captain rankings",
    "who should i captain",
    "show captain rankings",
    "show me captain rankings",
    "who are the top captains",
]
for _p in _RANK_PHRASINGS:
    _rr = route(_p)
    ok(_rr is not None and _rr.tool_name == "rank_captain_candidates",
       f"J route {_p!r} → rank_captain_candidates")

# ---------------------------------------------------------------------------
# Section K — Phrasing coverage: current_gameweek intent
# ---------------------------------------------------------------------------
_section("K — Phrasing coverage: current_gameweek")

_GW_PHRASINGS = [
    "what is the current gameweek",
    "current gameweek",
    "current gw",
    "what gameweek is it",
    "what gameweek are we in",
    "which gameweek are we in",
    "what gw",
    "which gw",
    "gameweek number",
]
for _p in _GW_PHRASINGS:
    _rr = route(_p)
    ok(_rr is not None and _rr.tool_name == "get_current_gameweek",
       f"K route {_p!r} → get_current_gameweek")

# ---------------------------------------------------------------------------
# Section L — Phrasing coverage: player_summary intent
# ---------------------------------------------------------------------------
_section("L — Phrasing coverage: player_summary")

_SUMMARY_PHRASINGS = [
    "give me a summary for Salah",
    "give me a summary of Haaland",
    "summary for Salah",
    "summary of Haaland",
    "stats for Haaland",
    "stats on Salah",
    "tell me about Saka",
    "details for Haaland",
    "get a summary for Saka",
    "show me stats for Haaland",
    "what are the stats for Salah",
]
for _p in _SUMMARY_PHRASINGS:
    _rr = route(_p)
    ok(_rr is not None and _rr.tool_name == "get_player_summary",
       f"L route {_p!r} → get_player_summary")

# ---------------------------------------------------------------------------
# Section M — Phrasing coverage: player_resolve intent
# ---------------------------------------------------------------------------
_section("M — Phrasing coverage: player_resolve")

_RESOLVE_PHRASINGS = [
    "who is Haaland",
    "who's Haaland",
    "find Salah",
    "find player Salah",
    "look up De Bruyne",
    "lookup Saka",
    "search for Haaland",
    "search Salah",
    "resolve Haaland",
    "info on Salah",
    "info for Haaland",
    "get info on Saka",
]
for _p in _RESOLVE_PHRASINGS:
    _rr = route(_p)
    ok(_rr is not None and _rr.tool_name == "resolve_player",
       f"M route {_p!r} → resolve_player")

# ---------------------------------------------------------------------------
# Section N — Unsupported phrasings must NOT route
# ---------------------------------------------------------------------------
_section("N — Unsupported phrasings return route()=None")

_NO_ROUTE_PHRASINGS = [
    "Is Haaland fit to play?",
    "Should I buy Salah?",
    "Latest FPL news",
    "Transfer advice",
    "Hello",
    "Is Saka injured?",
    "",
    "What is the best formation?",
    "Price prediction for Haaland",
]
for _p in _NO_ROUTE_PHRASINGS:
    _rr = route(_p)
    ok(_rr is None, f"N route {_p!r} → None (unroutable)")

# ---------------------------------------------------------------------------
# Section O — INTENT_MANIFEST example_phrasings route to correct tool
# ---------------------------------------------------------------------------
_section("O — INTENT_MANIFEST example_phrasings route to expected tool")

for _intent_key, _entry in INTENT_MANIFEST.items():
    _expected_tool = _entry["tool"]
    for _phrasing in _entry["example_phrasings"]:
        _rr = route(_phrasing)
        ok(_rr is not None and _rr.tool_name == _expected_tool,
           f"O phrasing {_phrasing!r} → {_expected_tool} (intent={_intent_key})")

# ---------------------------------------------------------------------------
# Section P — Phase 2k regression: existing dispatch behaviour unchanged
# ---------------------------------------------------------------------------
_section("P — Phase 2k regression")

# P1: captain_score basic properties preserved
_p1 = dispatch("should I captain Haaland", _BS)
ok(_p1.intent        == INTENT_CAPTAIN_SCORE,     "P1 intent=captain_score")
ok(_p1.selected_tool == "get_captain_score",       "P2 selected_tool=get_captain_score")
ok(_p1.raw_output.get("status") == "ok",           "P3 raw_output status=ok")
ok(len(_p1.answer_text) > 0,                       "P4 answer_text non-empty")
ok(_p1.question      == "should I captain Haaland", "P5 question preserved")

# P2: unsupported returns safe result
_p2 = dispatch("Is Haaland fit?", _BS)
ok(_p2.intent        == INTENT_UNSUPPORTED, "P6 unsupported intent=unsupported")
ok(_p2.selected_tool is None,               "P7 unsupported selected_tool=None")
ok(len(_p2.answer_text) > 0,               "P8 unsupported answer_text non-empty")

# P3: context_meta propagation (assembled context)
_CTX_META = {
    "gw_resolved_via":  "bootstrap",
    "fixture_count":    4,
    "team_count":       5,
    "blank_gw_teams":   [11],
    "assembled_at":     "2026-03-14T00:00:00",
}
_CTX = {
    "bootstrap":              _BS,
    "gameweek":               28,
    "fixtures":               [],
    "fixture_difficulty_map": _FDR_MAP,
    "meta":                   _CTX_META,
}
_p3 = dispatch("should I captain Haaland", _CTX)
ok(_p3.context_meta == _CTX_META, "P9 context_meta propagated from assembled context")

# P4: supported intents frozenset unchanged
ok(INTENT_UNSUPPORTED not in SUPPORTED_INTENTS, "P10 INTENT_UNSUPPORTED not in SUPPORTED_INTENTS")
ok(len(SUPPORTED_INTENTS) == 5,                 "P11 SUPPORTED_INTENTS has 5 members")

# ---------------------------------------------------------------------------
# Section Q — Interface report
# ---------------------------------------------------------------------------
_section("Q — Interface report")

print()
print("  Phase 2l exports:")
print(f"    INTENT_MANIFEST keys:  {sorted(INTENT_MANIFEST.keys())}")
print(f"    OUTCOME_OK:            {OUTCOME_OK!r}")
print(f"    OUTCOME_NOT_FOUND:     {OUTCOME_NOT_FOUND!r}")
print(f"    OUTCOME_AMBIGUOUS:     {OUTCOME_AMBIGUOUS!r}")
print(f"    OUTCOME_MISSING_ARGS:  {OUTCOME_MISSING_ARGUMENTS!r}")
print(f"    OUTCOME_UNSUPPORTED:   {OUTCOME_UNSUPPORTED_INTENT!r}")
print(f"    OUTCOME_ERROR:         {OUTCOME_ERROR!r}")
print()
print("  DispatchResult fields (7):")
for _f in _dc.fields(DispatchResult):
    print(f"    {_f.name}: {_f.type}")
print()
print("  Sample ok dispatch (captain_score):")
_q_disp = dispatch("should I captain Salah", _BS)
print(f"    intent:   {_q_disp.intent}")
print(f"    outcome:  {_q_disp.outcome}")
print(f"    tool:     {_q_disp.selected_tool}")
print(f"    answer:   {_q_disp.answer_text[:80]}...")
print()
print("  Sample unsupported dispatch:")
_q_uns = dispatch("Is Salah injured?", _BS)
print(f"    intent:   {_q_uns.intent}")
print(f"    outcome:  {_q_uns.outcome}")
print(f"    answer:   {_q_uns.answer_text}")
print()
print("  Sample missing_arguments dispatch (no candidates_list):")
_q_miss = dispatch("top captains this week", _BS)
print(f"    intent:   {_q_miss.intent}")
print(f"    outcome:  {_q_miss.outcome}")
print(f"    answer:   {_q_miss.answer_text}")
print()
print("  Intentionally deferred:")
_deferred = [
    "LLM-based intent classification",
    "Multi-turn conversation memory",
    "Pronoun resolution ('What about his form?')",
    "Combined intents ('Who is Salah and what gameweek is it?')",
    "Broad fuzzy matching beyond existing keyword patterns",
    "UI integration",
]
for _d in _deferred:
    print(f"    - {_d}")

ok(True, "Q interface report printed")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print(f"Phase 2l dispatcher tests: {_passed}/{_passed + _failed} PASS")
if _failed == 0:
    print("ALL ASSERTIONS PASS")
else:
    print(f"FAILURES: {_failed}")
    sys.exit(1)


