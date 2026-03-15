"""
Phase 4f tests — LLM-assisted reference resolution
====================================================

Sections
--------
A  ReferenceResolution dataclass structure
B  build_resolver_prompt — pure function
C  _parse_resolver_response — pure function
D  _build_canonical_question — pure function
E  resolve_reference fallback (no LLM client available)
F  resolve_reference with mock LLM client (English follow-ups)
G  resolve_reference with mock LLM client (Spanish follow-ups)
H  ConversationSession.respond() — resolver_client kwarg integration
I  ConversationState.history tracking
J  FinalResponse contract — regression on 5 canonical scenarios
K  RESOLVER_SYSTEM_PROMPT content
L  Live LLM test (skipped if ANTHROPIC_API_KEY not set)

Run from packages/fpl-grounded-assistant/ with:
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\
    ../fpl-api-client:../fpl-pipeline:. python run_phase4f_tests.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import fields

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_current_section = ""


def _section(name: str) -> None:
    global _current_section
    _current_section = name
    print(f"\n[{name}]")


def _ok(label: str) -> None:
    global _pass
    _pass += 1
    print(f"  PASS  {label}")


def _fail_test(label: str, msg: str) -> None:
    global _fail
    _fail += 1
    print(f"  FAIL  {label} — {msg}")


def _assert(cond: bool, label: str, msg: str = "") -> None:
    if cond:
        _ok(label)
    else:
        _fail_test(label, msg or "condition was False")


def _assert_eq(actual, expected, label: str) -> None:
    if actual == expected:
        _ok(label)
    else:
        _fail_test(label, f"got {actual!r}, expected {expected!r}")


def _assert_is_none(val, label: str) -> None:
    _assert(val is None, label, f"expected None, got {val!r}")


def _assert_not_none(val, label: str) -> None:
    _assert(val is not None, label, "expected non-None, got None")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant import (
    # Phase 4f
    ReferenceResolution,
    resolve_reference,
    resolve_reference_llm,
    build_resolver_prompt,
    RESOLVER_SYSTEM_PROMPT,
    _CONFIDENCE_THRESHOLD,
    _INTENT_TO_CANONICAL,
    _parse_resolver_response,
    _build_canonical_question,
    # Phase 4e
    ConversationState,
    ConversationSession,
    resolve_pronouns,
    # Phase 3c
    FinalResponse,
    respond,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_UNSUPPORTED,
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
)

# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------

class _MockContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _MockMessage:
    def __init__(self, text: str) -> None:
        self.content = [_MockContent(text)]


class _MockMessages:
    def __init__(self, response_text: str, raises: bool = False) -> None:
        self._response_text = response_text
        self._raises = raises

    def create(self, **kwargs):
        if self._raises:
            raise RuntimeError("mock LLM error")
        return _MockMessage(self._response_text)


class _MockClient:
    """Minimal mock for an Anthropic client, returns preset JSON."""

    def __init__(self, response_json: str, raises: bool = False) -> None:
        self.messages = _MockMessages(response_json, raises=raises)


def _make_json_response(
    resolved_query,
    intent_guess,
    reference_source="explicit",
    confidence=0.9,
    language="en",
) -> str:
    return json.dumps({
        "resolved_query": resolved_query,
        "intent_guess": intent_guess,
        "reference_source": reference_source,
        "confidence": confidence,
        "language": language,
    })


# ===========================================================================
# Section A — ReferenceResolution dataclass structure
# ===========================================================================
_section("A: ReferenceResolution dataclass")

r = ReferenceResolution(
    resolved_query="Haaland",
    intent_guess=INTENT_CAPTAIN_SCORE,
    reference_source="pronoun",
    confidence=0.9,
    language="en",
    rewritten_question="should I captain Haaland",
)

field_names = {f.name for f in fields(ReferenceResolution)}
_assert("resolved_query" in field_names, "A1: has resolved_query field")
_assert("intent_guess" in field_names, "A2: has intent_guess field")
_assert("reference_source" in field_names, "A3: has reference_source field")
_assert("confidence" in field_names, "A4: has confidence field")
_assert("language" in field_names, "A5: has language field")
_assert("rewritten_question" in field_names, "A6: has rewritten_question field")
_assert_eq(len(field_names), 7, "A7: exactly 7 fields (6 original + fallback_reason from Phase 4g)")

# Frozen — should raise on attribute assignment
try:
    r.resolved_query = "Salah"  # type: ignore[misc]
    _fail_test("A8: is frozen dataclass", "no error on assignment")
except Exception:
    _ok("A8: is frozen dataclass")

r_none = ReferenceResolution(
    resolved_query=None,
    intent_guess=None,
    reference_source="none",
    confidence=0.0,
    language="unknown",
    rewritten_question="original",
)
_assert_is_none(r_none.resolved_query, "A9: resolved_query can be None")
_assert_is_none(r_none.intent_guess, "A10: intent_guess can be None")


# ===========================================================================
# Section B — build_resolver_prompt
# ===========================================================================
_section("B: build_resolver_prompt")

s = ConversationState()
s.last_player_query = "Haaland"

prompt_str = build_resolver_prompt("should I captain him?", s)
_assert(isinstance(prompt_str, str), "B1: returns string")

parsed_prompt = json.loads(prompt_str)
_assert_eq(parsed_prompt["current_question"], "should I captain him?", "B2: contains current_question")
_assert_eq(parsed_prompt["last_player"], "Haaland", "B3: contains last_player when set")
_assert("recent_history" not in parsed_prompt, "B4: no recent_history when history=None")

# Empty state -> last_player is null
s_empty = ConversationState()
p2 = json.loads(build_resolver_prompt("hello", s_empty))
_assert(p2["last_player"] is None, "B5: last_player is null when state empty")

# With history
hist = [("should I captain Haaland", INTENT_CAPTAIN_SCORE), ("tell me about him", INTENT_PLAYER_SUMMARY)]
p3 = json.loads(build_resolver_prompt("and him?", s, history=hist))
_assert("recent_history" in p3, "B6: recent_history present when history provided")
_assert_eq(len(p3["recent_history"]), 2, "B7: history entries count matches")

# History capped at 3
hist_long = [(f"q{i}", "captain_score") for i in range(6)]
p4 = json.loads(build_resolver_prompt("q?", s, history=hist_long))
_assert(len(p4["recent_history"]) <= 3, "B8: history capped at 3 entries")

# Spanish characters preserved (ensure_ascii=False)
s_es = ConversationState()
s_es.last_player_query = "Haaland"
p5_str = build_resolver_prompt("¿Y como capitán?", s_es)
_assert("¿Y como capitán?" in p5_str, "B9: Spanish characters preserved (ensure_ascii=False)")

# Re-parseable
p5 = json.loads(p5_str)
_assert_eq(p5["current_question"], "¿Y como capitán?", "B10: Spanish question in parsed JSON")


# ===========================================================================
# Section C — _parse_resolver_response
# ===========================================================================
_section("C: _parse_resolver_response")

valid_json = json.dumps({
    "resolved_query": "Haaland",
    "intent_guess": "captain_score",
    "reference_source": "pronoun",
    "confidence": 0.9,
    "language": "en",
})
_assert_not_none(_parse_resolver_response(valid_json), "C1: valid JSON -> dict")

_assert_is_none(_parse_resolver_response("not json"), "C2: invalid JSON -> None")
_assert_is_none(_parse_resolver_response("{"), "C3: malformed JSON -> None")

# Missing key
missing_key_json = json.dumps({"resolved_query": "H", "intent_guess": "captain_score", "reference_source": "pronoun", "confidence": 0.9})
_assert_is_none(_parse_resolver_response(missing_key_json), "C4: missing key -> None")

# Invalid intent_guess
bad_intent = json.dumps({"resolved_query": "H", "intent_guess": "INVALID", "reference_source": "pronoun", "confidence": 0.9, "language": "en"})
_assert_is_none(_parse_resolver_response(bad_intent), "C5: invalid intent_guess -> None")

# Invalid reference_source
bad_src = json.dumps({"resolved_query": "H", "intent_guess": "captain_score", "reference_source": "unknown_src", "confidence": 0.9, "language": "en"})
_assert_is_none(_parse_resolver_response(bad_src), "C6: invalid reference_source -> None")

# Invalid language
bad_lang = json.dumps({"resolved_query": "H", "intent_guess": "captain_score", "reference_source": "pronoun", "confidence": 0.9, "language": "fr"})
_assert_is_none(_parse_resolver_response(bad_lang), "C7: invalid language -> None")

# Confidence as int — should work
int_conf = json.dumps({"resolved_query": "H", "intent_guess": "captain_score", "reference_source": "pronoun", "confidence": 1, "language": "en"})
_assert_not_none(_parse_resolver_response(int_conf), "C8: confidence as int -> OK")

# null resolved_query — should work
null_rq = json.dumps({"resolved_query": None, "intent_guess": "current_gameweek", "reference_source": "none", "confidence": 0.9, "language": "en"})
_assert_not_none(_parse_resolver_response(null_rq), "C9: null resolved_query -> OK")

# null intent_guess — should work
null_intent = json.dumps({"resolved_query": "Salah", "intent_guess": None, "reference_source": "explicit", "confidence": 0.7, "language": "en"})
_assert_not_none(_parse_resolver_response(null_intent), "C10: null intent_guess -> OK")

# Non-dict JSON
_assert_is_none(_parse_resolver_response("[1, 2, 3]"), "C11: list JSON -> None")

# Whitespace around JSON
padded = "  " + valid_json + "  "
_assert_not_none(_parse_resolver_response(padded), "C12: whitespace-padded JSON -> OK")

# confidence as string — should fail
bad_conf = json.dumps({"resolved_query": "H", "intent_guess": "captain_score", "reference_source": "pronoun", "confidence": "high", "language": "en"})
_assert_is_none(_parse_resolver_response(bad_conf), "C13: string confidence -> None")


# ===========================================================================
# Section D — _build_canonical_question
# ===========================================================================
_section("D: _build_canonical_question")

_assert_eq(
    _build_canonical_question("Haaland", INTENT_CAPTAIN_SCORE, "¿Y él?"),
    "should I captain Haaland",
    "D1: captain_score + player -> canonical question",
)
_assert_eq(
    _build_canonical_question("Salah", INTENT_PLAYER_SUMMARY, "And him?"),
    "tell me about Salah",
    "D2: player_summary + player -> canonical question",
)
_assert_eq(
    _build_canonical_question("KDB", INTENT_PLAYER_RESOLVE, "¿Quién es?"),
    "who is KDB",
    "D3: player_resolve + player -> canonical question",
)
_assert_eq(
    _build_canonical_question(None, INTENT_RANK_CANDIDATES, "¿Los mejores?"),
    "top captains this week",
    "D4: rank_candidates -> canonical, no player needed",
)
_assert_eq(
    _build_canonical_question(None, INTENT_CURRENT_GAMEWEEK, "¿En qué jornada?"),
    "what is the current gameweek",
    "D5: current_gameweek -> canonical, no player needed",
)
_assert_eq(
    _build_canonical_question("Saka", None, "And Saka?"),
    "tell me about Saka",
    "D6: None intent + player -> summary fallback",
)
_assert_eq(
    _build_canonical_question(None, None, "¿Qué tal?"),
    "¿Qué tal?",
    "D7: None intent + None player -> original returned",
)
_assert_eq(
    _build_canonical_question(None, "unsupported", "¿Lo comprarías?"),
    "¿Lo comprarías?",
    "D8: unsupported + no player -> original returned",
)
# Player name casing preserved
q9 = _build_canonical_question("De Bruyne", INTENT_CAPTAIN_SCORE, "him?")
_assert("De Bruyne" in q9, "D9: player name casing preserved in output")

# rank_candidates ignores any player
_assert_eq(
    _build_canonical_question("Haaland", INTENT_RANK_CANDIDATES, "top?"),
    "top captains this week",
    "D10: rank_candidates always uses canonical (ignores player)",
)


# ===========================================================================
# Section E — resolve_reference fallback (no LLM)
# ===========================================================================
_section("E: resolve_reference fallback (no LLM)")

s_base = ConversationState()
s_base.last_player_query = "Haaland"

# No pronouns, no LLM -> original returned unchanged
e1 = resolve_reference("should I captain Salah", s_base, client=None)
_assert_eq(e1.rewritten_question, "should I captain Salah", "E1: no pronoun -> original unchanged")
_assert_eq(e1.reference_source, "none", "E2: reference_source == 'none'")
_assert_eq(e1.confidence, 0.0, "E3: confidence == 0.0 when no resolution")
_assert_is_none(e1.resolved_query, "E4: resolved_query is None when no resolution")

# English pronoun "him" -> Phase 4e fallback substitutes "Haaland"
e5 = resolve_reference("should I captain him?", s_base, client=None)
_assert(e5.rewritten_question != "should I captain him?", "E5: pronoun resolved -> question changed")
_assert_eq(e5.reference_source, "deterministic", "E6: reference_source == 'deterministic' for Phase 4e fallback")
_assert_eq(e5.confidence, 1.0, "E7: confidence == 1.0 for exact deterministic match")
# Should match what resolve_pronouns() produces
expected_pronouns = resolve_pronouns("should I captain him?", s_base)
_assert_eq(e5.rewritten_question, expected_pronouns, "E8: rewritten_question matches resolve_pronouns() output")

# Spanish pronoun "él" — Phase 4e does not handle this -> original returned
s_es2 = ConversationState()
s_es2.last_player_query = "Haaland"
e9 = resolve_reference("¿Y él?", s_es2, client=None)
_assert_eq(e9.rewritten_question, "¿Y él?", "E9: Spanish pronoun with no LLM -> original returned")

# No state (last_player_query=None) -> always returns original unchanged
s_empty2 = ConversationState()
e10 = resolve_reference("should I captain him?", s_empty2, client=None)
_assert_eq(e10.rewritten_question, "should I captain him?", "E10: no state -> original returned unchanged")

# Never raises
try:
    resolve_reference("some question", ConversationState(), client=None)
    _ok("E11: never raises")
except Exception as exc:
    _fail_test("E11: never raises", str(exc))

# Returns ReferenceResolution
_assert(isinstance(e1, ReferenceResolution), "E12: always returns ReferenceResolution")


# ===========================================================================
# Section F — resolve_reference with mock LLM client (English)
# ===========================================================================
_section("F: resolve_reference with mock client (English)")

s_f = ConversationState()
s_f.last_player_query = "Haaland"

# "And Salah?" — explicit player, captain intent
f1_json = _make_json_response("Salah", INTENT_CAPTAIN_SCORE, "explicit", 0.92, "en")
f1_client = _MockClient(f1_json)
f1 = resolve_reference("And Salah?", s_f, client=f1_client)
_assert_eq(f1.resolved_query, "Salah", "F1: resolved_query == 'Salah'")
_assert_eq(f1.intent_guess, INTENT_CAPTAIN_SCORE, "F2: intent_guess == captain_score")
_assert_eq(f1.rewritten_question, "should I captain Salah", "F3: rewritten_question is canonical English")
_assert_eq(f1.reference_source, "explicit", "F4: reference_source == 'explicit'")
_assert_eq(f1.language, "en", "F5: language == 'en'")
_assert(f1.confidence >= 0.9, "F6: confidence propagated from LLM output")

# "What about him?" — pronoun, summary intent
f7_json = _make_json_response("Haaland", INTENT_PLAYER_SUMMARY, "pronoun", 0.88, "en")
f7_client = _MockClient(f7_json)
f7 = resolve_reference("What about him?", s_f, client=f7_client)
_assert_eq(f7.resolved_query, "Haaland", "F7: pronoun resolved to last_player")
_assert_eq(f7.rewritten_question, "tell me about Haaland", "F8: rewritten to canonical summary question")
_assert_eq(f7.reference_source, "pronoun", "F9: reference_source == 'pronoun'")

# Invalid JSON from LLM -> deterministic fallback
f10_client = _MockClient("this is not json")
f10 = resolve_reference("should I captain him?", s_f, client=f10_client)
_assert_eq(f10.reference_source, "deterministic", "F10: invalid LLM JSON -> deterministic fallback")
_assert(f10.rewritten_question != "should I captain him?", "F11: pronoun still resolved via fallback")

# Low confidence -> deterministic fallback
f12_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.2, "en")
f12_client = _MockClient(f12_json)
f12 = resolve_reference("should I captain him?", s_f, client=f12_client)
_assert_eq(f12.reference_source, "deterministic", "F12: low confidence -> deterministic fallback")

# LLM raises -> deterministic fallback
f13_client = _MockClient("", raises=True)
f13 = resolve_reference("should I captain him?", s_f, client=f13_client)
_assert_eq(f13.reference_source, "deterministic", "F13: LLM raises -> deterministic fallback")

# rewritten_question routes correctly through the deterministic router
from fpl_grounded_assistant import route
rr1 = route(f1.rewritten_question)
_assert_not_none(rr1, "F14: LLM-rewritten question routes via deterministic router")
_assert_eq(rr1.tool_name, "get_captain_score", "F15: routes to correct tool")


# ===========================================================================
# Section G — resolve_reference with mock client (Spanish)
# ===========================================================================
_section("G: resolve_reference with mock client (Spanish)")

s_g = ConversationState()
s_g.last_player_query = "Haaland"

# "¿Y como capitán?" — ellipsis + captain intent
g1_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "ellipsis", 0.85, "es")
g1_client = _MockClient(g1_json)
g1 = resolve_reference("¿Y como capitán?", s_g, client=g1_client)
_assert_eq(g1.resolved_query, "Haaland", "G1: Spanish ellipsis resolves to last_player")
_assert_eq(g1.intent_guess, INTENT_CAPTAIN_SCORE, "G2: captain_score intent detected")
_assert_eq(g1.rewritten_question, "should I captain Haaland", "G3: rewritten to canonical English")
_assert_eq(g1.language, "es", "G4: language == 'es'")

# "¿Y Salah?" — explicit player
g5_json = _make_json_response("Salah", INTENT_PLAYER_SUMMARY, "explicit", 0.9, "es")
g5_client = _MockClient(g5_json)
g5 = resolve_reference("¿Y Salah?", s_g, client=g5_client)
_assert_eq(g5.resolved_query, "Salah", "G5: explicit player in Spanish question")
_assert_eq(g5.rewritten_question, "tell me about Salah", "G6: rewritten to English summary question")

# "¿Y él?" — Spanish pronoun
g7_json = _make_json_response("Haaland", INTENT_PLAYER_SUMMARY, "pronoun", 0.87, "es")
g7_client = _MockClient(g7_json)
g7 = resolve_reference("¿Y él?", s_g, client=g7_client)
_assert_eq(g7.resolved_query, "Haaland", "G7: Spanish pronoun él resolved via LLM")
_assert_eq(g7.language, "es", "G8: language detected as 'es'")

# "¿Lo comprarías?" — unsupported intent
g9_json = _make_json_response(None, "unsupported", "none", 0.8, "es")
g9_client = _MockClient(g9_json)
g9 = resolve_reference("¿Lo comprarías?", s_g, client=g9_client)
_assert_eq(g9.intent_guess, "unsupported", "G9: unsupported intent detected for purchase question")
_assert_eq(g9.rewritten_question, "¿Lo comprarías?", "G10: unsupported -> original returned (no valid canonical form)")

# "¿Y él?" with no LLM -> Phase 4e doesn't handle "él" -> original returned
g11 = resolve_reference("¿Y él?", s_g, client=None)
_assert_eq(g11.rewritten_question, "¿Y él?", "G11: Spanish pronoun with no LLM -> original returned")

# canonical rewritten question routes through deterministic router
rr_g = route(g1.rewritten_question)
_assert_not_none(rr_g, "G12: Spanish->canonical question routes deterministically")
_assert_eq(rr_g.tool_name, "get_captain_score", "G13: Spanish captain intent routes correctly")


# ===========================================================================
# Section H — ConversationSession.respond() with resolver_client
# ===========================================================================
_section("H: ConversationSession.respond() with resolver_client")

session_h = ConversationSession()

# Turn 1: direct question — no resolver needed
r_h1 = session_h.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
_assert(isinstance(r_h1, FinalResponse), "H1: respond() returns FinalResponse")
_assert_eq(r_h1.outcome, OUTCOME_OK, "H2: direct question -> outcome=ok")
_assert_eq(session_h.last_player_query, "Haaland", "H3: last_player_query updated after Turn 1")
_assert_eq(session_h.turn_count, 1, "H4: turn_count=1 after first turn")

# Turn 2: pronoun follow-up, no resolver_client -> Phase 4e fallback
r_h2 = session_h.respond("should I captain him?", STANDARD_BOOTSTRAP)
_assert(isinstance(r_h2, FinalResponse), "H5: pronoun follow-up returns FinalResponse")
_assert_eq(r_h2.outcome, OUTCOME_OK, "H6: pronoun follow-up (Haaland) -> outcome=ok")
_assert_eq(session_h.turn_count, 2, "H7: turn_count=2 after second turn")

# Turn 3: Spanish pronoun, with mock resolver_client
s_mock_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.87, "es")
session_h2 = ConversationSession()
r_h3a = session_h2.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
r_h3 = session_h2.respond("¿Y como capitán?", STANDARD_BOOTSTRAP, resolver_client=_MockClient(s_mock_json))
_assert(isinstance(r_h3, FinalResponse), "H8: Spanish follow-up with mock client returns FinalResponse")
_assert_eq(r_h3.outcome, OUTCOME_OK, "H9: Spanish->Haaland captain question -> outcome=ok")

# session.clear() resets everything
session_h2.clear()
_assert_is_none(session_h2.last_player_query, "H10: clear() resets last_player_query")
_assert_eq(session_h2.turn_count, 0, "H11: clear() resets turn_count")
_assert_eq(session_h2.state.history, [], "H12: clear() resets history")

# resolver_client kwarg consumed, not forwarded to respond()
session_h3 = ConversationSession()
try:
    session_h3.respond("should I captain Haaland", STANDARD_BOOTSTRAP, resolver_client=None)
    _ok("H13: resolver_client=None accepted without error")
except TypeError as e:
    _fail_test("H13: resolver_client=None accepted without error", str(e))

# Other kwargs forwarded correctly
r_h14 = session_h3.respond("should I captain Haaland", STANDARD_BOOTSTRAP,
                             resolver_client=None, include_debug=True)
_assert(r_h14.debug is not None, "H14: include_debug=True forwarded to respond()")


# ===========================================================================
# Section I — ConversationState.history tracking
# ===========================================================================
_section("I: ConversationState.history")

s_i = ConversationState()
_assert_eq(s_i.history, [], "I1: history starts empty")

# Simulate update_from_response with question_text
from fpl_grounded_assistant import FinalResponseDebug

def _make_final_response(outcome, intent):
    return FinalResponse(
        final_text="test",
        outcome=outcome,
        supported=(outcome != OUTCOME_UNSUPPORTED_INTENT),
        intent=intent,
        review_passed=True,
        llm_used=False,
        debug=None,
    )

s_i.update_from_response(_make_final_response(OUTCOME_OK, INTENT_CAPTAIN_SCORE), "Haaland", question_text="should I captain Haaland")
_assert_eq(len(s_i.history), 1, "I2: history has 1 entry after 1 update")
_assert_eq(s_i.history[0], ("should I captain Haaland", INTENT_CAPTAIN_SCORE), "I3: history entry is (question, intent) tuple")

s_i.update_from_response(_make_final_response(OUTCOME_OK, INTENT_PLAYER_SUMMARY), "Haaland", question_text="tell me about Haaland")
s_i.update_from_response(_make_final_response(OUTCOME_NOT_FOUND, INTENT_PLAYER_RESOLVE), None, question_text="who is xyz")
_assert_eq(len(s_i.history), 3, "I4: history grows to 3")

# 4th entry drops oldest
s_i.update_from_response(_make_final_response(OUTCOME_OK, INTENT_CAPTAIN_SCORE), "Salah", question_text="should I captain Salah")
_assert_eq(len(s_i.history), 3, "I5: history capped at 3 after 4th entry")
_assert_eq(s_i.history[2][0], "should I captain Salah", "I6: newest entry is last")
_assert_eq(s_i.history[0][0], "tell me about Haaland", "I7: oldest entry dropped after cap")

# clear() resets history
s_i.clear()
_assert_eq(s_i.history, [], "I8: clear() resets history to empty list")

# update_from_response without question_text -> no history change
s_i2 = ConversationState()
s_i2.update_from_response(_make_final_response(OUTCOME_OK, INTENT_CAPTAIN_SCORE), "Haaland")
_assert_eq(s_i2.history, [], "I9: update without question_text -> history unchanged")


# ===========================================================================
# Section J — FinalResponse contract regression
# ===========================================================================
_section("J: FinalResponse contract regression (5 canonical scenarios)")

_SCENARIOS = [
    {
        "id": "supported_ok",
        "question": "should I captain Haaland",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_outcome": OUTCOME_OK,
        "expected_supported": True,
    },
    {
        "id": "supported_ambiguous",
        "question": "who is Doe",
        "bootstrap": AMBIGUOUS_BOOTSTRAP,
        "expected_outcome": OUTCOME_AMBIGUOUS,
        "expected_supported": True,
    },
    {
        "id": "supported_not_found",
        "question": "should I captain xyznotaplayer999",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_outcome": OUTCOME_NOT_FOUND,
        "expected_supported": True,
    },
    {
        "id": "supported_missing_arguments",
        "question": "top captains this week",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_outcome": OUTCOME_MISSING_ARGUMENTS,
        "expected_supported": True,
    },
    {
        "id": "unsupported_intent",
        "question": "Is Haaland fit to play?",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_outcome": OUTCOME_UNSUPPORTED_INTENT,
        "expected_supported": False,
    },
]

for sc in _SCENARIOS:
    r = respond(sc["question"], sc["bootstrap"])
    _assert(isinstance(r, FinalResponse), f"J-{sc['id']}: returns FinalResponse")
    _assert_eq(r.outcome, sc["expected_outcome"], f"J-{sc['id']}: outcome == {sc['expected_outcome']}")
    _assert_eq(r.supported, sc["expected_supported"], f"J-{sc['id']}: supported == {sc['expected_supported']}")
    _assert(len(r.final_text) > 0, f"J-{sc['id']}: final_text is non-empty")
    # supported <-> outcome invariant
    _assert(
        r.supported == (r.outcome != OUTCOME_UNSUPPORTED_INTENT),
        f"J-{sc['id']}: supported <-> outcome invariant",
    )

# ConversationSession preserves contract
session_j = ConversationSession()
rj1 = session_j.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
_assert(isinstance(rj1, FinalResponse), "J-session: ConversationSession returns FinalResponse")
_assert_eq(rj1.outcome, OUTCOME_OK, "J-session: outcome=ok preserved via session")
_assert(len(rj1.final_text) > 0, "J-session: final_text non-empty via session")


# ===========================================================================
# Section K — RESOLVER_SYSTEM_PROMPT content
# ===========================================================================
_section("K: RESOLVER_SYSTEM_PROMPT content")

_assert("JSON" in RESOLVER_SYSTEM_PROMPT, "K1: prompt mentions JSON")
_assert("resolved_query" in RESOLVER_SYSTEM_PROMPT, "K2: prompt defines resolved_query field")
_assert("confidence" in RESOLVER_SYSTEM_PROMPT, "K3: prompt defines confidence field")
_assert("intent_guess" in RESOLVER_SYSTEM_PROMPT, "K4: prompt defines intent_guess field")
# Should contain Spanish pronoun guidance
_assert("él" in RESOLVER_SYSTEM_PROMPT or "lo" in RESOLVER_SYSTEM_PROMPT, "K5: prompt mentions Spanish pronouns")
# Should NOT be the presentation SYSTEM_PROMPT from llm_layer
_assert("Fantasy Premier League" in RESOLVER_SYSTEM_PROMPT, "K6: prompt identifies FPL context")
_assert("You do NOT answer FPL questions" in RESOLVER_SYSTEM_PROMPT, "K7: prompt explicitly forbids answering")

# _CONFIDENCE_THRESHOLD is numeric in valid range
_assert(isinstance(_CONFIDENCE_THRESHOLD, float), "K8: _CONFIDENCE_THRESHOLD is float")
_assert(0.0 <= _CONFIDENCE_THRESHOLD <= 1.0, "K9: _CONFIDENCE_THRESHOLD in [0, 1]")

# _INTENT_TO_CANONICAL covers all player intents
_assert(INTENT_CAPTAIN_SCORE in _INTENT_TO_CANONICAL, "K10: captain_score in canonical map")
_assert(INTENT_PLAYER_SUMMARY in _INTENT_TO_CANONICAL, "K11: player_summary in canonical map")
_assert(INTENT_PLAYER_RESOLVE in _INTENT_TO_CANONICAL, "K12: player_resolve in canonical map")
_assert(INTENT_RANK_CANDIDATES in _INTENT_TO_CANONICAL, "K13: rank_candidates in canonical map")
_assert(INTENT_CURRENT_GAMEWEEK in _INTENT_TO_CANONICAL, "K14: current_gameweek in canonical map")

# All canonical templates with {player} actually route through the router
from fpl_grounded_assistant import route as _route
for intent, template in _INTENT_TO_CANONICAL.items():
    if "{player}" in template:
        test_q = template.format(player="Haaland")
        rr = _route(test_q)
        _assert_not_none(rr, f"K15-{intent}: canonical template routes correctly ({test_q!r})")


# ===========================================================================
# Section L — Live LLM test (skipped without API key)
# ===========================================================================
_section("L: Live LLM test")

_api_key = os.environ.get("ANTHROPIC_API_KEY")
if not _api_key:
    print("  SKIP  L1..L5 — ANTHROPIC_API_KEY not set")
else:
    try:
        import anthropic
        live_client = anthropic.Anthropic(api_key=_api_key)

        s_live = ConversationState()
        s_live.last_player_query = "Haaland"

        # Simple English pronoun
        lr1 = resolve_reference_llm(
            "should I captain him?",
            s_live,
            client=live_client,
        )
        _assert_not_none(lr1, "L1: live LLM returns non-None for English pronoun")
        if lr1 is not None:
            _assert(lr1.confidence > 0.0, "L2: live LLM returns non-zero confidence")
            _assert(isinstance(lr1.rewritten_question, str), "L3: live LLM returns rewritten_question string")
            _assert(lr1.language in ("en", "es", "unknown"), "L4: live LLM returns valid language")

        # Spanish question
        lr2 = resolve_reference_llm("¿Y como capitán?", s_live, client=live_client)
        _assert_not_none(lr2, "L5: live LLM returns non-None for Spanish question")
        if lr2 is not None:
            _assert_eq(lr2.language, "es", "L6: live LLM detects Spanish language")

    except ImportError:
        print("  SKIP  L1..L6 — anthropic package not installed")
    except Exception as exc:
        _fail_test("L1", f"live LLM raised: {exc}")


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'='*60}")
total = _pass + _fail
print(f"Phase 4f: {_pass}/{total} assertions passed")
if _fail:
    print(f"  FAILURES: {_fail}")
    sys.exit(1)
else:
    print("  ALL PASS")
    sys.exit(0)
