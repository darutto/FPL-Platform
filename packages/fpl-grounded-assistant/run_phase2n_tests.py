"""
run_phase2n_tests.py
====================
Standalone Phase 2n validator — no pytest dependency, one-file runner.

Phase 2n: Contract documentation and conversation fixtures.

Usage::

    cd packages/fpl-grounded-assistant
    python run_phase2n_tests.py

What is tested
--------------
New in Phase 2n:
    ConversationFixture      — frozen dataclass with expected scenario values
    FIXTURE_DEFINITIONS      — tuple of 9 canonical scenarios
    STANDARD_BOOTSTRAP       — embedded GW28 bootstrap (same data as prior slices)
    AMBIGUOUS_BOOTSTRAP      — GW28 + two "Doe" elements with shared web_name
    run_all()                — executes all fixtures, returns (fixture, AdapterResponse) pairs

Sections
--------
A  — ConversationFixture dataclass: field names, count, frozen
B  — FIXTURE_DEFINITIONS: 9 scenarios, required IDs present, no duplicates
C  — STANDARD_BOOTSTRAP and AMBIGUOUS_BOOTSTRAP: structural validity
D  — run_all() returns one result per fixture, in definition order
E  — Fixture ok_captain_score: supported=True, outcome=ok, intent=captain_score
F  — Fixture ok_rank_candidates: supported=True, outcome=ok, intent=rank_candidates
G  — Fixture ok_current_gameweek: supported=True, outcome=ok, intent=current_gameweek
H  — Fixture ok_player_summary: supported=True, outcome=ok, intent=player_summary
I  — Fixture ok_player_resolve: supported=True, outcome=ok, intent=player_resolve
J  — Fixture not_found_captain: supported=True, outcome=not_found
K  — Fixture ambiguous_player: supported=True, outcome=ambiguous
L  — Fixture missing_candidates: supported=True, outcome=missing_arguments
M  — Fixture unsupported_question: supported=False, outcome=unsupported_intent
N  — Cross-fixture invariants (response_text non-empty, user_message preserved, etc.)
O  — Determinism: running fixtures twice yields identical outcomes
P  — Expected values match ConversationFixture declarations
Q  — Phase 2m/2l/2k regression: adapt(), dispatch(), OUTCOME_* still intact
R  — Interface report (pretty-print all fixture outputs)
"""
from __future__ import annotations

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
# Imports under test
# ---------------------------------------------------------------------------
from fpl_grounded_assistant import (
    ConversationFixture,
    FIXTURE_DEFINITIONS,
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    run_all,
    adapt,
    AdapterResponse,
    DispatchResult,
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
)

# ---------------------------------------------------------------------------
# Section A — ConversationFixture dataclass
# ---------------------------------------------------------------------------
_section("A — ConversationFixture dataclass structure")

import dataclasses as _dc
_cf_fields = {f.name for f in _dc.fields(ConversationFixture)}

ok("scenario_id"             in _cf_fields, "A1 scenario_id field present")
ok("description"             in _cf_fields, "A2 description field present")
ok("user_message"            in _cf_fields, "A3 user_message field present")
ok("expected_supported"      in _cf_fields, "A4 expected_supported field present")
ok("expected_outcome"        in _cf_fields, "A5 expected_outcome field present")
ok("expected_intent"         in _cf_fields, "A6 expected_intent field present")
ok("candidates_list"         in _cf_fields, "A7 candidates_list field present")
ok("use_ambiguous_bootstrap" in _cf_fields, "A8 use_ambiguous_bootstrap field present")
ok(len(_cf_fields) == 8,                    "A9 exactly 8 fields")

# frozen=True
_cf_probe = ConversationFixture(
    scenario_id="probe", description="probe", user_message="probe",
    expected_supported=True, expected_outcome="ok", expected_intent="captain_score",
)
try:
    _cf_probe.scenario_id = "other"  # type: ignore[misc]
    ok(False, "A10 ConversationFixture is frozen (should have raised)")
except Exception:
    ok(True, "A10 ConversationFixture is frozen (reassignment raises)")

# ---------------------------------------------------------------------------
# Section B — FIXTURE_DEFINITIONS: 9 scenarios, required IDs, no duplicates
# ---------------------------------------------------------------------------
_section("B — FIXTURE_DEFINITIONS: 9 required scenarios")

_REQUIRED_IDS = {
    "ok_captain_score",
    "ok_rank_candidates",
    "ok_current_gameweek",
    "ok_player_summary",
    "ok_player_resolve",
    "not_found_captain",
    "ambiguous_player",
    "missing_candidates",
    "unsupported_question",
}
_actual_ids = {f.scenario_id for f in FIXTURE_DEFINITIONS}

ok(len(FIXTURE_DEFINITIONS) == 9,                          "B1 exactly 9 fixture definitions")
ok(_actual_ids == _REQUIRED_IDS,                           "B2 all required scenario IDs present")
ok(len(_actual_ids) == len(FIXTURE_DEFINITIONS),           "B3 no duplicate scenario IDs")

for _f in FIXTURE_DEFINITIONS:
    ok(isinstance(_f, ConversationFixture),                f"B4 {_f.scenario_id!r} is ConversationFixture")
    ok(len(_f.description) > 0,                           f"B5 {_f.scenario_id!r} has non-empty description")
    ok(isinstance(_f.expected_supported, bool),            f"B6 {_f.scenario_id!r} expected_supported is bool")
    ok(_f.expected_outcome in ("ok", "not_found", "ambiguous",
                               "missing_arguments", "error", "unsupported_intent"),
       f"B7 {_f.scenario_id!r} expected_outcome is valid OUTCOME_* value")

# Ambiguous scenario uses ambiguous bootstrap
_amb_fixture = next(f for f in FIXTURE_DEFINITIONS if f.scenario_id == "ambiguous_player")
ok(_amb_fixture.use_ambiguous_bootstrap is True,           "B8 ambiguous_player uses ambiguous bootstrap")

# Rank ok fixture has candidates_list
_rank_ok = next(f for f in FIXTURE_DEFINITIONS if f.scenario_id == "ok_rank_candidates")
ok(_rank_ok.candidates_list is not None and len(_rank_ok.candidates_list) > 0,
   "B9 ok_rank_candidates has non-empty candidates_list")

# Missing candidates fixture has NO candidates_list
_miss = next(f for f in FIXTURE_DEFINITIONS if f.scenario_id == "missing_candidates")
ok(_miss.candidates_list is None, "B10 missing_candidates has candidates_list=None")

# ---------------------------------------------------------------------------
# Section C — STANDARD_BOOTSTRAP and AMBIGUOUS_BOOTSTRAP
# ---------------------------------------------------------------------------
_section("C — Bootstrap structure validity")

for _bs_name, _bs in [("STANDARD_BOOTSTRAP", STANDARD_BOOTSTRAP),
                       ("AMBIGUOUS_BOOTSTRAP", AMBIGUOUS_BOOTSTRAP)]:
    ok(isinstance(_bs, dict),                          f"C {_bs_name} is dict")
    ok("elements"      in _bs,                         f"C {_bs_name} has 'elements' key")
    ok("teams"         in _bs,                         f"C {_bs_name} has 'teams' key")
    ok("events"        in _bs,                         f"C {_bs_name} has 'events' key")
    ok("element_types" in _bs,                         f"C {_bs_name} has 'element_types' key")
    ok("fixture_difficulty_map" in _bs,                f"C {_bs_name} has 'fixture_difficulty_map' key")
    ok(len(_bs["elements"]) >= 4,                      f"C {_bs_name} has at least 4 elements")

ok(len(STANDARD_BOOTSTRAP["elements"]) == 4,           "C standard bootstrap has exactly 4 elements")
ok(len(AMBIGUOUS_BOOTSTRAP["elements"]) == 6,          "C ambiguous bootstrap has exactly 6 elements (4 + 2 Doe)")

_doe_elements = [e for e in AMBIGUOUS_BOOTSTRAP["elements"] if e["web_name"] == "Doe"]
ok(len(_doe_elements) == 2,                            "C ambiguous bootstrap has exactly 2 'Doe' elements")
ok(_doe_elements[0]["id"] != _doe_elements[1]["id"],   "C Doe elements have distinct IDs")

# Current GW is 28 in both bootstraps
_current_gw = next(e["id"] for e in STANDARD_BOOTSTRAP["events"] if e["is_current"])
ok(_current_gw == 28,                                  "C standard bootstrap current GW is 28")

# ---------------------------------------------------------------------------
# Section D — run_all() returns one result per fixture, in order
# ---------------------------------------------------------------------------
_section("D — run_all() result structure")

_results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)

ok(len(_results) == len(FIXTURE_DEFINITIONS),     "D1 run_all returns one result per fixture")
for _i, (_fix, _resp) in enumerate(_results):
    ok(isinstance(_fix, ConversationFixture),     f"D2 result[{_i}] first element is ConversationFixture")
    ok(isinstance(_resp, AdapterResponse),        f"D3 result[{_i}] second element is AdapterResponse")
    ok(_fix.scenario_id == FIXTURE_DEFINITIONS[_i].scenario_id,
       f"D4 result[{_i}] preserves fixture order ({_fix.scenario_id!r})")

# Helper to look up a result by scenario_id
_by_id = {f.scenario_id: r for f, r in _results}

# ---------------------------------------------------------------------------
# Section E — ok_captain_score
# ---------------------------------------------------------------------------
_section("E — Fixture: ok_captain_score")

_e = _by_id["ok_captain_score"]
ok(_e.supported,                                  "E1 supported=True")
ok(_e.dispatch_result.outcome == OUTCOME_OK,      "E2 outcome=ok")
ok(_e.dispatch_result.intent == INTENT_CAPTAIN_SCORE, "E3 intent=captain_score")
ok(_e.dispatch_result.selected_tool == "get_captain_score", "E4 selected_tool=get_captain_score")
ok("Haaland" in _e.response_text,                 "E5 response_text mentions Haaland")
ok("/100" in _e.response_text,                    "E6 response_text contains captain score")

# ---------------------------------------------------------------------------
# Section F — ok_rank_candidates
# ---------------------------------------------------------------------------
_section("F — Fixture: ok_rank_candidates")

_f = _by_id["ok_rank_candidates"]
ok(_f.supported,                                  "F1 supported=True")
ok(_f.dispatch_result.outcome == OUTCOME_OK,      "F2 outcome=ok")
ok(_f.dispatch_result.intent == INTENT_RANK_CANDIDATES, "F3 intent=rank_candidates")
ok(_f.dispatch_result.selected_tool == "rank_captain_candidates", "F4 selected_tool correct")
ok(len(_f.response_text) > 0,                    "F5 response_text non-empty")

# ---------------------------------------------------------------------------
# Section G — ok_current_gameweek
# ---------------------------------------------------------------------------
_section("G — Fixture: ok_current_gameweek")

_g = _by_id["ok_current_gameweek"]
ok(_g.supported,                                  "G1 supported=True")
ok(_g.dispatch_result.outcome == OUTCOME_OK,      "G2 outcome=ok")
ok(_g.dispatch_result.intent == INTENT_CURRENT_GAMEWEEK, "G3 intent=current_gameweek")
ok(_g.dispatch_result.selected_tool == "get_current_gameweek", "G4 selected_tool correct")
ok("28" in _g.response_text,                      "G5 response_text mentions GW28")

# ---------------------------------------------------------------------------
# Section H — ok_player_summary
# ---------------------------------------------------------------------------
_section("H — Fixture: ok_player_summary")

_h = _by_id["ok_player_summary"]
ok(_h.supported,                                  "H1 supported=True")
ok(_h.dispatch_result.outcome == OUTCOME_OK,      "H2 outcome=ok")
ok(_h.dispatch_result.intent == INTENT_PLAYER_SUMMARY, "H3 intent=player_summary")
ok(_h.dispatch_result.selected_tool == "get_player_summary", "H4 selected_tool correct")
ok("Salah" in _h.response_text,                   "H5 response_text mentions Salah")

# ---------------------------------------------------------------------------
# Section I — ok_player_resolve
# ---------------------------------------------------------------------------
_section("I — Fixture: ok_player_resolve")

_i = _by_id["ok_player_resolve"]
ok(_i.supported,                                  "I1 supported=True")
ok(_i.dispatch_result.outcome == OUTCOME_OK,      "I2 outcome=ok")
ok(_i.dispatch_result.intent == INTENT_PLAYER_RESOLVE, "I3 intent=player_resolve")
ok(_i.dispatch_result.selected_tool == "resolve_player", "I4 selected_tool correct")
ok("Haaland" in _i.response_text,                 "I5 response_text mentions Haaland")

# ---------------------------------------------------------------------------
# Section J — not_found_captain
# ---------------------------------------------------------------------------
_section("J — Fixture: not_found_captain")

_j = _by_id["not_found_captain"]
ok(_j.supported,                                  "J1 supported=True (intent was recognised)")
ok(_j.dispatch_result.outcome == OUTCOME_NOT_FOUND, "J2 outcome=not_found")
ok(_j.dispatch_result.intent == INTENT_CAPTAIN_SCORE, "J3 intent=captain_score preserved")
ok(len(_j.response_text) > 0,                    "J4 response_text non-empty")

# ---------------------------------------------------------------------------
# Section K — ambiguous_player
# ---------------------------------------------------------------------------
_section("K — Fixture: ambiguous_player")

_k = _by_id["ambiguous_player"]
ok(_k.supported,                                  "K1 supported=True (intent was recognised)")
ok(_k.dispatch_result.outcome == OUTCOME_AMBIGUOUS, "K2 outcome=ambiguous")
ok(_k.dispatch_result.intent == INTENT_PLAYER_RESOLVE, "K3 intent=player_resolve preserved")
ok(len(_k.response_text) > 0,                    "K4 response_text non-empty")

# ---------------------------------------------------------------------------
# Section L — missing_candidates
# ---------------------------------------------------------------------------
_section("L — Fixture: missing_candidates")

_l = _by_id["missing_candidates"]
ok(_l.supported,                                      "L1 supported=True (intent was recognised)")
ok(_l.dispatch_result.outcome == OUTCOME_MISSING_ARGUMENTS, "L2 outcome=missing_arguments")
ok(_l.dispatch_result.intent == INTENT_RANK_CANDIDATES, "L3 intent=rank_candidates preserved")
ok("candidates_list" in _l.response_text,             "L4 response_text mentions candidates_list")

# ---------------------------------------------------------------------------
# Section M — unsupported_question
# ---------------------------------------------------------------------------
_section("M — Fixture: unsupported_question")

_m = _by_id["unsupported_question"]
ok(not _m.supported,                                   "M1 supported=False")
ok(_m.dispatch_result.outcome == OUTCOME_UNSUPPORTED_INTENT, "M2 outcome=unsupported_intent")
ok(_m.dispatch_result.intent == INTENT_UNSUPPORTED,    "M3 intent=unsupported")
ok(_m.dispatch_result.selected_tool is None,           "M4 selected_tool=None")
ok(len(_m.response_text) > 0,                         "M5 response_text non-empty")

# ---------------------------------------------------------------------------
# Section N — Cross-fixture invariants
# ---------------------------------------------------------------------------
_section("N — Cross-fixture invariants hold for all 9 scenarios")

for _fix, _resp in _results:
    _sid = _fix.scenario_id
    ok(_resp.response_text == _resp.dispatch_result.answer_text,
       f"N response_text == answer_text for {_sid!r}")
    ok(_resp.user_message == _resp.dispatch_result.question,
       f"N user_message == question for {_sid!r}")
    ok(_resp.user_message == _fix.user_message,
       f"N user_message preserved for {_sid!r}")
    ok(len(_resp.response_text) > 0,
       f"N response_text non-empty for {_sid!r}")
    ok(isinstance(_resp.dispatch_result, DispatchResult),
       f"N dispatch_result is DispatchResult for {_sid!r}")
    ok((_resp.supported) == (_resp.dispatch_result.outcome != OUTCOME_UNSUPPORTED_INTENT),
       f"N supported semantics consistent for {_sid!r}")

# ---------------------------------------------------------------------------
# Section O — Determinism: run_all twice, outcomes are identical
# ---------------------------------------------------------------------------
_section("O — Determinism: run_all() twice → identical outcomes")

_results2 = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)
for (_f1, _r1), (_f2, _r2) in zip(_results, _results2):
    ok(_r1.dispatch_result.outcome == _r2.dispatch_result.outcome,
       f"O outcome stable: {_f1.scenario_id!r}")
    ok(_r1.supported == _r2.supported,
       f"O supported stable: {_f1.scenario_id!r}")
    ok(_r1.response_text == _r2.response_text,
       f"O response_text stable: {_f1.scenario_id!r}")

# ---------------------------------------------------------------------------
# Section P — Expected values match ConversationFixture declarations
# ---------------------------------------------------------------------------
_section("P — Actual outcomes match each fixture's declared expectations")

for _fix, _resp in _results:
    ok(_resp.supported == _fix.expected_supported,
       f"P supported matches expected for {_fix.scenario_id!r}")
    ok(_resp.dispatch_result.outcome == _fix.expected_outcome,
       f"P outcome matches expected for {_fix.scenario_id!r}")
    ok(_resp.dispatch_result.intent == _fix.expected_intent,
       f"P intent matches expected for {_fix.scenario_id!r}")

# ---------------------------------------------------------------------------
# Section Q — Phase 2m/2l/2k regression
# ---------------------------------------------------------------------------
_section("Q — Phase 2m/2l/2k regression")

# adapt() directly
_q1 = adapt("should I captain Salah", STANDARD_BOOTSTRAP)
ok(isinstance(_q1, AdapterResponse),                       "Q1 adapt() returns AdapterResponse")
ok(_q1.supported,                                          "Q2 adapt() supported=True for known player")
ok(_q1.dispatch_result.outcome == OUTCOME_OK,              "Q3 adapt() outcome=ok")

# dispatch() still importable
from fpl_grounded_assistant import dispatch
_q2 = dispatch("who is Haaland", STANDARD_BOOTSTRAP)
ok(isinstance(_q2, DispatchResult),                        "Q4 dispatch() returns DispatchResult")
ok(_q2.outcome == OUTCOME_OK,                              "Q5 dispatch() outcome=ok")

# OUTCOME_* constants unchanged
ok(OUTCOME_OK == "ok",                                     "Q6 OUTCOME_OK unchanged")
ok(OUTCOME_UNSUPPORTED_INTENT == "unsupported_intent",     "Q7 OUTCOME_UNSUPPORTED_INTENT unchanged")
ok(OUTCOME_NOT_FOUND == "not_found",                       "Q8 OUTCOME_NOT_FOUND unchanged")
ok(OUTCOME_AMBIGUOUS == "ambiguous",                       "Q9 OUTCOME_AMBIGUOUS unchanged")
ok(OUTCOME_MISSING_ARGUMENTS == "missing_arguments",       "Q10 OUTCOME_MISSING_ARGUMENTS unchanged")

# ---------------------------------------------------------------------------
# Section R — Interface report
# ---------------------------------------------------------------------------
_section("R — Interface report")

print()
print("  Phase 2n deliverables:")
print(f"    CONTRACT.md       — model-facing interface contract document")
print(f"    conversation_fixtures.py — {len(FIXTURE_DEFINITIONS)} executable scenarios")
print()
print("  Fixture scenario summary:")
_col_w = max(len(f.scenario_id) for f in FIXTURE_DEFINITIONS) + 2
print(f"  {'Scenario':<{_col_w}} {'supported':>9}  outcome")
print(f"  {'-'*_col_w} {'-'*9}  {'-------'}")
for _fix, _resp in _results:
    _sup = "True " if _resp.supported else "False"
    print(f"  {_fix.scenario_id:<{_col_w}} {_sup:>9}  {_resp.dispatch_result.outcome}")
print()
print("  Invariants verified across all 9 scenarios:")
print("    response_text == dispatch_result.answer_text")
print("    user_message  == dispatch_result.question")
print("    supported     == (outcome != OUTCOME_UNSUPPORTED_INTENT)")
print("    len(response_text) > 0")
print()
print("  Intentionally deferred:")
_deferred = [
    "LLM-based intent classification",
    "Multi-turn conversation memory",
    "Pronoun resolution",
    "Combined intents",
    "Freeform response generation",
    "UI integration",
]
for _d in _deferred:
    print(f"    - {_d}")

ok(True, "R interface report printed")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print(f"Phase 2n contract+fixtures tests: {_passed}/{_passed + _failed} PASS")
if _failed == 0:
    print("ALL ASSERTIONS PASS")
else:
    print(f"FAILURES: {_failed}")
    sys.exit(1)


