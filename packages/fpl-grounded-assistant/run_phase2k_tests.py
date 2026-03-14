"""
run_phase2k_tests.py
====================
Standalone Phase 2k validator — no pytest dependency, one-file runner.

Phase 2k: Minimal model-facing dispatcher.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2k_tests.py

What is tested
--------------
New ``dispatcher.py`` module:

    dispatch(question, bootstrap, candidate_inputs=None, candidates_list=None)
    → DispatchResult(intent, question, selected_tool, raw_output, answer_text,
                     context_meta)

Intent constants and registry:
    INTENT_CAPTAIN_SCORE / INTENT_RANK_CANDIDATES / INTENT_CURRENT_GAMEWEEK
    INTENT_PLAYER_SUMMARY / INTENT_PLAYER_RESOLVE / INTENT_UNSUPPORTED
    SUPPORTED_INTENTS (frozenset of the 5 supported intents)

Sections
--------
A  — INTENT_* constants: values correct
B  — SUPPORTED_INTENTS: frozenset, correct membership
C  — _TOOL_TO_INTENT: maps all 5 tools; falls back for unknown
D  — DispatchResult dataclass: 6 fields, frozen
E  — Unsupported questions: safe DispatchResult, no exception
F  — captain_score intent: end-to-end dispatch
G  — rank_candidates intent: end-to-end dispatch
H  — current_gameweek intent: end-to-end dispatch
I  — player_summary intent: end-to-end dispatch
J  — player_resolve intent: end-to-end dispatch
K  — DispatchResult fields for an ok tool response
L  — context_meta=None when raw bootstrap passed
M  — context_meta populated when assembled context passed
N  — raw_output not mutated by dispatch
O  — unsupported raw_output structure
P  — not_found player handled safely (no exception)
Q  — Phase 2j regression: Why clause present in captain dispatch
R  — Phase 2i regression: [tier] bracket in ranked dispatch
S  — selected_tool matches intent for all 5 supported intents
T  — Phase 2a/2b regression: resolve_player and gameweek still work
U  — Interface report

Expected result: 80+ assertions, all PASS.

Fixture data (GW28 — same as Phase 2d/2e/2f/2g/2h for regression parity)
--------------------------------------------------------------------------
Arsenal (1, str=4) home vs Man City (13, str=5) → FDR: ARS=5, MCI=4
Liverpool (14, str=5) home vs Chelsea (8, str=4) → FDR: LIV=4, CHE=5
Man Utd (11, str=3) — blank GW
fixture_difficulty_map = {1: 5, 13: 4, 14: 4, 8: 5}

Haaland (MCI, FWD, penalties_order=1) → effective_score=59.85 → tier=safe
Salah   (LIV, MID, penalties_order=1) → effective_score=65.58 → tier=safe
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

# Assembled context (simulates Phase 2f ctx dict)
_CTX_META = {
    "gw_resolved_via":  "bootstrap",
    "fixture_count":    4,
    "team_count":       5,
    "blank_gw_teams":   [11],
    "assembled_at":     "2026-03-14T00:00:00",
}
_CTX = {
    "bootstrap":             _BS,
    "gameweek":              28,
    "fixtures":              [],
    "fixture_difficulty_map": _FDR_MAP,
    "meta":                  _CTX_META,
}

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
)

# ---------------------------------------------------------------------------
# Section A — INTENT_* constants
# ---------------------------------------------------------------------------
_section("A — INTENT_* constants")
ok(INTENT_CAPTAIN_SCORE    == "captain_score",    "A1 INTENT_CAPTAIN_SCORE value")
ok(INTENT_RANK_CANDIDATES  == "rank_candidates",  "A2 INTENT_RANK_CANDIDATES value")
ok(INTENT_CURRENT_GAMEWEEK == "current_gameweek", "A3 INTENT_CURRENT_GAMEWEEK value")
ok(INTENT_PLAYER_SUMMARY   == "player_summary",   "A4 INTENT_PLAYER_SUMMARY value")
ok(INTENT_PLAYER_RESOLVE   == "player_resolve",   "A5 INTENT_PLAYER_RESOLVE value")
ok(INTENT_UNSUPPORTED      == "unsupported",      "A6 INTENT_UNSUPPORTED value")

# ---------------------------------------------------------------------------
# Section B — SUPPORTED_INTENTS
# ---------------------------------------------------------------------------
_section("B — SUPPORTED_INTENTS frozenset")
ok(isinstance(SUPPORTED_INTENTS, frozenset),         "B1 SUPPORTED_INTENTS is frozenset")
ok(len(SUPPORTED_INTENTS) == 5,                      "B2 5 supported intents")
ok(INTENT_CAPTAIN_SCORE    in SUPPORTED_INTENTS,     "B3 captain_score in set")
ok(INTENT_RANK_CANDIDATES  in SUPPORTED_INTENTS,     "B4 rank_candidates in set")
ok(INTENT_CURRENT_GAMEWEEK in SUPPORTED_INTENTS,     "B5 current_gameweek in set")
ok(INTENT_PLAYER_SUMMARY   in SUPPORTED_INTENTS,     "B6 player_summary in set")
ok(INTENT_PLAYER_RESOLVE   in SUPPORTED_INTENTS,     "B7 player_resolve in set")
ok(INTENT_UNSUPPORTED      not in SUPPORTED_INTENTS, "B8 unsupported NOT in set")

# ---------------------------------------------------------------------------
# Section C — _TOOL_TO_INTENT map
# ---------------------------------------------------------------------------
_section("C — _TOOL_TO_INTENT map")
ok(_TOOL_TO_INTENT.get("get_captain_score")       == INTENT_CAPTAIN_SCORE,    "C1 get_captain_score → captain_score")
ok(_TOOL_TO_INTENT.get("rank_captain_candidates") == INTENT_RANK_CANDIDATES,  "C2 rank_captain_candidates → rank_candidates")
ok(_TOOL_TO_INTENT.get("get_current_gameweek")    == INTENT_CURRENT_GAMEWEEK, "C3 get_current_gameweek → current_gameweek")
ok(_TOOL_TO_INTENT.get("get_player_summary")      == INTENT_PLAYER_SUMMARY,   "C4 get_player_summary → player_summary")
ok(_TOOL_TO_INTENT.get("resolve_player")          == INTENT_PLAYER_RESOLVE,   "C5 resolve_player → player_resolve")
ok(_TOOL_TO_INTENT.get("unknown_tool") is None,                               "C6 unknown_tool not in map")
ok(len(_TOOL_TO_INTENT) == 5,                                                 "C7 map has exactly 5 entries")

# ---------------------------------------------------------------------------
# Section D — DispatchResult dataclass
# ---------------------------------------------------------------------------
_section("D — DispatchResult dataclass")
import dataclasses as _dc
_fields = {f.name for f in _dc.fields(DispatchResult)}
ok("intent"        in _fields, "D1 intent field present")
ok("question"      in _fields, "D2 question field present")
ok("selected_tool" in _fields, "D3 selected_tool field present")
ok("raw_output"    in _fields, "D4 raw_output field present")
ok("answer_text"   in _fields, "D5 answer_text field present")
ok("context_meta"  in _fields, "D6 context_meta field present")
ok(len(_fields) == 6,          "D7 exactly 6 fields")

# Test frozen=True prevents attribute reassignment
_dr_test = DispatchResult(
    intent="captain_score", question="test?", selected_tool="get_captain_score",
    raw_output={}, answer_text="test", context_meta=None,
)
try:
    _dr_test.intent = "other"  # type: ignore[misc]
    ok(False, "D8 DispatchResult is frozen (should have raised)")
except Exception:
    ok(True, "D8 DispatchResult is frozen (reassignment raises)")

# ---------------------------------------------------------------------------
# Section E — Unsupported questions
# ---------------------------------------------------------------------------
_section("E — Unsupported questions return safe DispatchResult")

_unsupported_qs = [
    "Is Haaland fit to play?",
    "Transfer advice for Salah",
    "Latest FPL news",
    "Price of Saka?",
    "",
    "Hello there",
]
for _uq in _unsupported_qs:
    _ur = dispatch(_uq, _BS)
    ok(_ur.intent        == INTENT_UNSUPPORTED, f"E intent=unsupported for {repr(_uq)!r}")
    ok(_ur.selected_tool is None,               f"E selected_tool=None for {repr(_uq)!r}")
    ok(len(_ur.answer_text) > 0,                f"E answer_text non-empty for {repr(_uq)!r}")
    ok(_ur.question      == _uq,                f"E question preserved for {repr(_uq)!r}")

# ---------------------------------------------------------------------------
# Section F — captain_score intent
# ---------------------------------------------------------------------------
_section("F — captain_score intent dispatches correctly")
_rf = dispatch("should I captain Haaland", _BS)
ok(_rf.intent        == INTENT_CAPTAIN_SCORE,    "F1 intent=captain_score")
ok(_rf.selected_tool == "get_captain_score",     "F2 selected_tool=get_captain_score")
ok(_rf.raw_output.get("status") == "ok",         "F3 raw_output status=ok")
ok("Haaland" in _rf.answer_text,                 "F4 Haaland in answer_text")
ok(_rf.context_meta is None,                     "F5 context_meta=None (raw bootstrap)")
ok(_rf.question == "should I captain Haaland",   "F6 question preserved")

# Phase 2h: Haaland + penalties_order=1 → tier=safe
ok(_rf.raw_output.get("tier") == "safe",         "F7 Haaland tier=safe (role bonus active)")

# ---------------------------------------------------------------------------
# Section G — rank_candidates intent
# ---------------------------------------------------------------------------
_section("G — rank_candidates intent dispatches correctly")
_candidates = [{"query": "Haaland"}, {"query": "Salah"}]
_rg = dispatch("top captains this week", _BS, candidates_list=_candidates)
ok(_rg.intent        == INTENT_RANK_CANDIDATES,      "G1 intent=rank_candidates")
ok(_rg.selected_tool == "rank_captain_candidates",   "G2 selected_tool=rank_captain_candidates")
ok(_rg.raw_output.get("status") == "ok",             "G3 raw_output status=ok")
ok(len(_rg.answer_text) > 0,                         "G4 answer_text non-empty")
ok("Haaland" in _rg.answer_text or "Salah" in _rg.answer_text, "G5 player in answer_text")
ok(_rg.context_meta is None,                         "G6 context_meta=None (raw bootstrap)")

# ---------------------------------------------------------------------------
# Section H — current_gameweek intent
# ---------------------------------------------------------------------------
_section("H — current_gameweek intent dispatches correctly")
_rh = dispatch("what is the current gameweek", _BS)
ok(_rh.intent        == INTENT_CURRENT_GAMEWEEK,  "H1 intent=current_gameweek")
ok(_rh.selected_tool == "get_current_gameweek",   "H2 selected_tool=get_current_gameweek")
ok(_rh.raw_output.get("status") == "ok",          "H3 raw_output status=ok")
ok("28" in _rh.answer_text,                       "H4 GW 28 in answer_text")
ok(_rh.context_meta is None,                      "H5 context_meta=None (raw bootstrap)")

# ---------------------------------------------------------------------------
# Section I — player_summary intent
# ---------------------------------------------------------------------------
_section("I — player_summary intent dispatches correctly")
_ri = dispatch("give me a summary for Salah", _BS)
ok(_ri.intent        == INTENT_PLAYER_SUMMARY,   "I1 intent=player_summary")
ok(_ri.selected_tool == "get_player_summary",    "I2 selected_tool=get_player_summary")
ok(_ri.raw_output.get("status") == "ok",         "I3 raw_output status=ok")
ok("Salah" in _ri.answer_text,                   "I4 Salah in answer_text")

# ---------------------------------------------------------------------------
# Section J — player_resolve intent
# ---------------------------------------------------------------------------
_section("J — player_resolve intent dispatches correctly")
_rj = dispatch("who is Haaland", _BS)
ok(_rj.intent        == INTENT_PLAYER_RESOLVE,  "J1 intent=player_resolve")
ok(_rj.selected_tool == "resolve_player",       "J2 selected_tool=resolve_player")
ok(_rj.raw_output.get("status") == "ok",        "J3 raw_output status=ok")
ok("Haaland" in _rj.answer_text,                "J4 Haaland in answer_text")

# ---------------------------------------------------------------------------
# Section K — DispatchResult fields for ok response
# ---------------------------------------------------------------------------
_section("K — DispatchResult fields for ok tool response")
_rk = dispatch("captain score for Salah", _BS)
ok(isinstance(_rk, DispatchResult),                 "K1 returns DispatchResult instance")
ok(_rk.intent == INTENT_CAPTAIN_SCORE,              "K2 intent is captain_score")
ok(isinstance(_rk.question, str),                   "K3 question is str")
ok(isinstance(_rk.selected_tool, str),              "K4 selected_tool is str")
ok(isinstance(_rk.raw_output, dict),                "K5 raw_output is dict")
ok(isinstance(_rk.answer_text, str),                "K6 answer_text is str")
ok(len(_rk.answer_text) > 0,                        "K7 answer_text non-empty")
ok(_rk.context_meta is None,                        "K8 context_meta None for raw bootstrap")
ok(_rk.raw_output.get("captain_score") is not None, "K9 captain_score in raw_output")
ok(_rk.raw_output.get("tier") is not None,          "K10 tier in raw_output")
ok(_rk.raw_output.get("role_signals") is not None,  "K11 role_signals in raw_output")

# ---------------------------------------------------------------------------
# Section L — context_meta=None when raw bootstrap passed
# ---------------------------------------------------------------------------
_section("L — context_meta=None when raw bootstrap passed")
ok(dispatch("who is Saka", _BS).context_meta is None,                       "L1 resolve: context_meta=None")
ok(dispatch("what is the current gameweek", _BS).context_meta is None,      "L2 gameweek: context_meta=None")
ok(dispatch("captain score for De Bruyne", _BS).context_meta is None,       "L3 captain: context_meta=None")

# ---------------------------------------------------------------------------
# Section M — context_meta populated when assembled context passed
# ---------------------------------------------------------------------------
_section("M — context_meta populated when assembled context passed")
_rm = dispatch("who is Haaland", _CTX)
ok(_rm.context_meta is not None,                  "M1 context_meta is not None")
ok(isinstance(_rm.context_meta, dict),            "M2 context_meta is dict")
ok("blank_gw_teams" in _rm.context_meta,          "M3 blank_gw_teams present in meta")
ok(_rm.context_meta["blank_gw_teams"] == [11],    "M4 blank_gw_teams=[11] (Man Utd)")
ok("assembled_at" in _rm.context_meta,            "M5 assembled_at present in meta")
ok(_rm.intent == INTENT_PLAYER_RESOLVE,           "M6 intent still correct with assembled ctx")
ok(_rm.raw_output.get("status") == "ok",          "M7 raw_output ok with assembled ctx")

# ---------------------------------------------------------------------------
# Section N — raw_output not mutated by dispatch
# ---------------------------------------------------------------------------
_section("N — raw_output not mutated by dispatch()")
_bs_copy = copy.deepcopy(_BS)
_rn = dispatch("should I captain Salah", _bs_copy)
# The captain_score call should not mutate the bootstrap's elements list
ok(_bs_copy["elements"][1]["web_name"] == "Salah",  "N1 bootstrap elements unchanged after dispatch")
ok(len(_bs_copy["elements"]) == 4,                  "N2 bootstrap element count unchanged")

# Verify DispatchResult raw_output is not the same object as any internal dict
# (we check by modifying our copy and confirming result is unaffected)
_rn2 = dispatch("captain score for Haaland", _BS)
_original_score = _rn2.raw_output.get("captain_score")
# Modifying the returned raw_output does not affect a subsequent dispatch call
_rn2.raw_output["captain_score"] = 9999.0
_rn3 = dispatch("captain score for Haaland", _BS)
ok(_rn3.raw_output.get("captain_score") == _original_score, "N3 subsequent dispatch unaffected by mutation of previous result")

# ---------------------------------------------------------------------------
# Section O — unsupported raw_output structure
# ---------------------------------------------------------------------------
_section("O — unsupported raw_output structure")
_ro = dispatch("Is Saka fit to play?", _BS)
ok(_ro.raw_output.get("status") == "unsupported",          "O1 status=unsupported")
ok(_ro.raw_output.get("code")   == "unsupported_intent",   "O2 code=unsupported_intent")
ok(_ro.raw_output.get("question") == "Is Saka fit to play?", "O3 question preserved in raw_output")

# ---------------------------------------------------------------------------
# Section P — not_found player handled safely
# ---------------------------------------------------------------------------
_section("P — not_found player handled safely (no exception)")
_rp = dispatch("should I captain ZZZ_UNKNOWN_PLAYER_999", _BS)
ok(_rp.intent == INTENT_CAPTAIN_SCORE,           "P1 intent=captain_score (question was routed)")
ok(_rp.raw_output.get("status") == "not_found",  "P2 raw_output status=not_found")
ok(len(_rp.answer_text) > 0,                     "P3 answer_text non-empty for not_found")
ok(_rp.selected_tool == "get_captain_score",     "P4 selected_tool=get_captain_score")

# ---------------------------------------------------------------------------
# Section Q — Phase 2j regression: Why clause in captain dispatch
# ---------------------------------------------------------------------------
_section("Q — Phase 2j regression: Why clause present in captain answer")
_rq = dispatch("should I captain Haaland", _BS)
ok("Why:" in _rq.answer_text,                           "Q1 Why: clause present")
ok("Penalty taker" in _rq.answer_text,                  "Q2 Penalty taker reason present (pen1 + role_bonus)")
ok("Strong recent form" in _rq.answer_text,             "Q3 Strong recent form reason (form=8.0)")

# Salah: strong form + penalty taker + safe
_rq_salah = dispatch("captain score for Salah", _BS)
ok("Why:" in _rq_salah.answer_text,                     "Q4 Why: clause present for Salah")
ok("Penalty taker" in _rq_salah.answer_text or "Strong recent form" in _rq_salah.answer_text,
   "Q5 at least one reason present for Salah")

# ---------------------------------------------------------------------------
# Section R — Phase 2i regression: [tier] bracket in ranked dispatch
# ---------------------------------------------------------------------------
_section("R — Phase 2i regression: [tier] bracket in ranked list")
_rr = dispatch("top captains this week", _BS, candidates_list=[{"query": "Haaland"}, {"query": "Salah"}])
ok("[safe]" in _rr.answer_text,  "R1 [safe] bracket in ranked output")
ok("· pen"  in _rr.answer_text,  "R2 · pen suffix in ranked output (penalty takers)")

# ---------------------------------------------------------------------------
# Section S — selected_tool matches intent for all 5 intents
# ---------------------------------------------------------------------------
_section("S — selected_tool matches intent for all 5 supported intents")
_s_map = [
    ("should I captain Saka",              INTENT_CAPTAIN_SCORE,    "get_captain_score"),
    ("top captains this week",             INTENT_RANK_CANDIDATES,  "rank_captain_candidates"),
    ("what is the current gameweek",       INTENT_CURRENT_GAMEWEEK, "get_current_gameweek"),
    ("give me a summary for Salah",        INTENT_PLAYER_SUMMARY,   "get_player_summary"),
    ("who is Haaland",                     INTENT_PLAYER_RESOLVE,   "resolve_player"),
]
for _q, _exp_intent, _exp_tool in _s_map:
    _extra = {"candidates_list": [{"query": "Saka"}]} if _exp_intent == INTENT_RANK_CANDIDATES else {}
    _rs = dispatch(_q, _BS, **_extra)
    ok(_rs.intent        == _exp_intent, f"S intent={_exp_intent} for {repr(_q)!r}")
    ok(_rs.selected_tool == _exp_tool,   f"S tool={_exp_tool} for {repr(_q)!r}")

# ---------------------------------------------------------------------------
# Section T — Phase 2a/2b regression: existing tools still work
# ---------------------------------------------------------------------------
_section("T — Phase 2a/2b regression: resolve_player and gameweek intact")
_rt_resolve = dispatch("who is De Bruyne", _BS)
ok(_rt_resolve.raw_output.get("status") == "ok",           "T1 resolve_player ok for De Bruyne")
ok("De Bruyne" in _rt_resolve.answer_text,                 "T2 De Bruyne in resolve answer_text")

_rt_gw = dispatch("current gameweek", _BS)
ok(_rt_gw.raw_output.get("status") == "ok",                "T3 get_current_gameweek ok")
ok("28" in _rt_gw.answer_text,                             "T4 GW 28 in gameweek answer_text")

# ---------------------------------------------------------------------------
# Section U — Interface report
# ---------------------------------------------------------------------------
_section("U — Interface report")

print()
print("  Dispatcher entrypoints:")
print("    dispatch(question, bootstrap, candidate_inputs=None, candidates_list=None) → DispatchResult")
print()
print("  Supported intents (v1 heuristic):")
for _i in sorted(SUPPORTED_INTENTS):
    _tool = next((t for t, v in _TOOL_TO_INTENT.items() if v == _i), "?")
    print(f"    {_i:<22} → {_tool}")
print()
print(f"  INTENT_UNSUPPORTED: {INTENT_UNSUPPORTED!r} (returned for unrecognised questions)")
print()
print("  Unsupported answer text snippet:")
_sample_unsupported = dispatch("Is Saka injured?", _BS)
print(f"    {_sample_unsupported.answer_text[:80]}...")
print()
print("  Sample captain dispatch (Haaland, GW28, with role signals):")
_sample = dispatch("should I captain Haaland", _BS)
print(f"    intent:       {_sample.intent}")
print(f"    selected_tool:{_sample.selected_tool}")
print(f"    answer_text:  {_sample.answer_text}")
print()
print("  Sample unsupported dispatch:")
_sample_u = dispatch("transfer advice for Salah", _BS)
print(f"    intent:        {_sample_u.intent}")
print(f"    selected_tool: {_sample_u.selected_tool}")
print(f"    answer_text:   {_sample_u.answer_text}")
print()
print("  Intentionally deferred:")
print("    - LLM-based intent classification")
print("    - Multi-turn conversation memory")
print("    - Pronoun resolution ('What about his form?')")
print("    - Combined intents ('Who is Salah and what gameweek is it?')")
print("    - Broad fuzzy matching beyond existing keyword patterns")
print("    - UI integration")

# ---------------------------------------------------------------------------
# Final tally
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print(f"Phase 2k dispatcher tests: {_passed}/{_passed + _failed} PASS", end="")
if _failed:
    print(f"  ({_failed} FAIL)")
else:
    print("\nALL ASSERTIONS PASS")


