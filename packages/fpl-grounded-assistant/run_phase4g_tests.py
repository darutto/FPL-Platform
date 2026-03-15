"""
Phase 4g tests — resolver auditability and controlled session exposure
======================================================================

Sections
--------
A  ResolverDebug dataclass structure
B  ReferenceResolution.fallback_reason backward compat and defaults
C  resolve_reference() fallback_reason for all 3 paths
D  FinalResponseDebug.resolver is None for stateless respond()
E  ConversationSession.respond() with include_debug — resolver bundle populated
F  ResolverDebug content accuracy (source / confidence / fallback_reason)
G  run_session() multi-turn plain output
H  run_session() debug mode resolver metadata in output
I  FinalResponse contract regression — 5 canonical scenarios still pass

Run from packages/fpl-grounded-assistant/ with:
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine/python:\
    ../fpl-captain-engine:../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\
    ../fpl-api-client:../fpl-pipeline:. python run_phase4g_tests.py
"""
from __future__ import annotations

import json
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
    print(f"  FAIL  {label} -- {msg}")


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
    # Phase 4g
    ResolverDebug,
    FinalResponseDebug,
    # Phase 4f
    ReferenceResolution,
    resolve_reference,
    resolve_reference_llm,
    _CONFIDENCE_THRESHOLD,
    # Phase 4e
    ConversationState,
    ConversationSession,
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
    run_all_final_response,
)
from fpl_cli import run_session

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
# Section A -- ResolverDebug dataclass structure
# ===========================================================================
_section("A: ResolverDebug dataclass structure")

rd = ResolverDebug(
    resolver_used=True,
    resolver_source="fallback_regex",
    resolver_confidence=None,
    rewritten_question="should I captain Haaland?",
    fallback_reason="llm_unavailable",
)

field_names_a = {f.name for f in fields(ResolverDebug)}
_assert("resolver_used" in field_names_a, "A1: has resolver_used field")
_assert("resolver_source" in field_names_a, "A2: has resolver_source field")
_assert("resolver_confidence" in field_names_a, "A3: has resolver_confidence field")
_assert("rewritten_question" in field_names_a, "A4: has rewritten_question field")
_assert("fallback_reason" in field_names_a, "A5: has fallback_reason field")
_assert_eq(len(field_names_a), 5, "A6: exactly 5 fields")

# Frozen -- should raise on attribute assignment
try:
    rd.resolver_used = False  # type: ignore[misc]
    _fail_test("A7: is frozen dataclass", "no error on assignment")
except Exception:
    _ok("A7: is frozen dataclass")

_assert_eq(rd.resolver_used, True, "A8: resolver_used value correct")


# ===========================================================================
# Section B -- ReferenceResolution.fallback_reason backward compat and defaults
# ===========================================================================
_section("B: ReferenceResolution.fallback_reason backward compat and defaults")

# Old-style construction without fallback_reason should still work
r_old = ReferenceResolution(
    resolved_query="Haaland",
    intent_guess=INTENT_CAPTAIN_SCORE,
    reference_source="pronoun",
    confidence=0.9,
    language="en",
    rewritten_question="should I captain Haaland",
)
_assert_is_none(r_old.fallback_reason, "B1: fallback_reason defaults to None")

# New-style construction with explicit fallback_reason
r_new = ReferenceResolution(
    resolved_query="Haaland",
    intent_guess=INTENT_CAPTAIN_SCORE,
    reference_source="pronoun",
    confidence=0.9,
    language="en",
    rewritten_question="should I captain Haaland",
    fallback_reason="llm_unavailable",
)
_assert_eq(r_new.fallback_reason, "llm_unavailable", "B2: fallback_reason set correctly")

# low_confidence value
r_low = ReferenceResolution(
    resolved_query=None,
    intent_guess=None,
    reference_source="none",
    confidence=0.0,
    language="en",
    rewritten_question="original",
    fallback_reason="low_confidence",
)
_assert_eq(r_low.fallback_reason, "low_confidence", "B3: fallback_reason = low_confidence")

# None value
r_none_fr = ReferenceResolution(
    resolved_query=None,
    intent_guess=None,
    reference_source="none",
    confidence=0.0,
    language="en",
    rewritten_question="original",
    fallback_reason=None,
)
_assert_is_none(r_none_fr.fallback_reason, "B4: fallback_reason = None explicitly")

# Frozen invariant preserved after adding field
try:
    r_new.fallback_reason = "other"  # type: ignore[misc]
    _fail_test("B5: still frozen after adding fallback_reason", "no error on assignment")
except Exception:
    _ok("B5: still frozen after adding fallback_reason")

# Field count is now 7 (6 original + 1 new)
field_names_b = {f.name for f in fields(ReferenceResolution)}
_assert_eq(len(field_names_b), 7, "B6: ReferenceResolution has 7 fields now")
_assert("fallback_reason" in field_names_b, "B7: fallback_reason in fields")

# Deterministic path produces fallback_reason
s_b = ConversationState()
s_b.last_player_query = "Haaland"
res_b = resolve_reference("should I captain him?", s_b, client=None)
_assert(res_b.fallback_reason in ("llm_unavailable", None), "B8: fallback_reason is valid value for deterministic")

# No-state path -- also produces fallback_reason
s_b_empty = ConversationState()
res_b_empty = resolve_reference("should I captain him?", s_b_empty, client=None)
_assert(res_b_empty.fallback_reason in ("llm_unavailable", None), "B9: fallback_reason is valid value for no-state")

# LLM path -- fallback_reason should remain None
high_conf_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.9, "en")
client_b = _MockClient(high_conf_json)
res_b_llm = resolve_reference("should I captain him?", s_b, client=client_b)
_assert_is_none(res_b_llm.fallback_reason, "B10: LLM path leaves fallback_reason as None")


# ===========================================================================
# Section C -- resolve_reference() fallback_reason for all 3 paths
# ===========================================================================
_section("C: resolve_reference() fallback_reason for all 3 paths")

s_c = ConversationState()
s_c.last_player_query = "Haaland"

# Path 1: LLM high confidence -- fallback_reason = None
c_llm_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.85, "en")
c_llm_client = _MockClient(c_llm_json)
c_llm = resolve_reference("should I captain him?", s_c, client=c_llm_client)
_assert_is_none(c_llm.fallback_reason, "C1: LLM high confidence: fallback_reason = None")
_assert_eq(c_llm.reference_source, "pronoun", "C2: LLM high confidence: reference_source = pronoun")

# Path 1 variant: LLM moderate confidence above threshold
c_mod_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.6, "en")
c_mod_client = _MockClient(c_mod_json)
c_mod = resolve_reference("should I captain him?", s_c, client=c_mod_client)
_assert_is_none(c_mod.fallback_reason, "C3: LLM moderate confidence above threshold: fallback_reason = None")

# Path 2a: no client -- fallback_reason = llm_unavailable, deterministic runs
c_no_client = resolve_reference("should I captain him?", s_c, client=None)
_assert_eq(c_no_client.fallback_reason, "llm_unavailable", "C4: no client: fallback_reason = llm_unavailable")
_assert_eq(c_no_client.reference_source, "deterministic", "C5: no client: reference_source = deterministic")

# Path 2b: LLM raises -- fallback_reason = llm_unavailable, deterministic runs
c_raises_client = _MockClient("", raises=True)
c_raises = resolve_reference("should I captain him?", s_c, client=c_raises_client)
_assert_eq(c_raises.fallback_reason, "llm_unavailable", "C6: LLM raises: fallback_reason = llm_unavailable")
_assert_eq(c_raises.reference_source, "deterministic", "C7: LLM raises: reference_source = deterministic")

# Path 2c: LLM invalid JSON -- fallback_reason = llm_unavailable
c_bad_json_client = _MockClient("not json at all")
c_bad_json = resolve_reference("should I captain him?", s_c, client=c_bad_json_client)
_assert_eq(c_bad_json.fallback_reason, "llm_unavailable", "C8: LLM bad JSON: fallback_reason = llm_unavailable")

# Path 2d: LLM low confidence -- fallback_reason = low_confidence, deterministic runs
c_low_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.2, "en")
c_low_client = _MockClient(c_low_json)
c_low = resolve_reference("should I captain him?", s_c, client=c_low_client)
_assert_eq(c_low.fallback_reason, "low_confidence", "C9: low confidence: fallback_reason = low_confidence")
_assert_eq(c_low.reference_source, "deterministic", "C10: low confidence: reference_source = deterministic")

# Path 3: no client, no pronoun match -- fallback_reason = llm_unavailable, source = none
s_c2 = ConversationState()
s_c2.last_player_query = "Haaland"
c_no_pronoun = resolve_reference("should I captain Salah", s_c2, client=None)
_assert_eq(c_no_pronoun.fallback_reason, "llm_unavailable", "C11: no client, no pronoun: fallback_reason = llm_unavailable")
_assert_eq(c_no_pronoun.reference_source, "none", "C12: no client, no pronoun: reference_source = none")

# Path 3 with low confidence LLM and no pronoun match
s_c3 = ConversationState()
s_c3.last_player_query = "Haaland"
c_low_nopronoun_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.2, "en")
c_low_nopronoun_client = _MockClient(c_low_nopronoun_json)
c_low_nopronoun = resolve_reference("should I captain Salah", s_c3, client=c_low_nopronoun_client)
_assert_eq(c_low_nopronoun.fallback_reason, "low_confidence", "C13: low confidence no pronoun: fallback_reason = low_confidence")
_assert_eq(c_low_nopronoun.reference_source, "none", "C14: low confidence no pronoun: reference_source = none")

# Exactly at threshold -- LLM should be used (>= 0.5)
c_thresh_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", _CONFIDENCE_THRESHOLD, "en")
c_thresh_client = _MockClient(c_thresh_json)
c_thresh = resolve_reference("should I captain him?", s_c, client=c_thresh_client)
_assert_is_none(c_thresh.fallback_reason, "C15: exactly at threshold: fallback_reason = None (LLM used)")


# ===========================================================================
# Section D -- FinalResponseDebug.resolver is None for stateless respond()
# ===========================================================================
_section("D: FinalResponseDebug.resolver is None for stateless respond()")

r_d = respond("should I captain Haaland", STANDARD_BOOTSTRAP, include_debug=True)
_assert(isinstance(r_d, FinalResponse), "D1: stateless respond() returns FinalResponse")
_assert_not_none(r_d.debug, "D2: debug bundle populated when include_debug=True")
_assert_is_none(r_d.debug.resolver, "D3: debug.resolver is None for stateless respond()")

# Without include_debug -- debug is None
r_d_no_debug = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
_assert_is_none(r_d_no_debug.debug, "D4: debug is None without include_debug")

# FinalResponseDebug has resolver field
debug_field_names = {f.name for f in fields(FinalResponseDebug)}
_assert("resolver" in debug_field_names, "D5: FinalResponseDebug has resolver field")

# resolver field defaults to None
r_d2 = respond("should I captain Haaland", STANDARD_BOOTSTRAP, include_debug=True)
_assert_is_none(r_d2.debug.resolver, "D6: resolver field defaults to None")

# final_text is non-empty even with debug
_assert(len(r_d.final_text) > 0, "D7: final_text non-empty with include_debug")

# FinalResponse invariants still hold with include_debug
_assert_eq(r_d.outcome, OUTCOME_OK, "D8: outcome=ok for Haaland captain question")


# ===========================================================================
# Section E -- ConversationSession.respond() with include_debug
# ===========================================================================
_section("E: ConversationSession.respond() with include_debug")

session_e = ConversationSession()

# Turn 1: direct question -- resolver ran but made no change
r_e1 = session_e.respond("should I captain Haaland", STANDARD_BOOTSTRAP, include_debug=True)
_assert(isinstance(r_e1, FinalResponse), "E1: session respond() returns FinalResponse")
_assert_not_none(r_e1.debug, "E2: debug bundle populated")
_assert_not_none(r_e1.debug.resolver, "E3: resolver bundle populated for session turn")
_assert_eq(r_e1.debug.resolver.resolver_source, "none", "E4: first turn resolver_source = none")
_assert_eq(r_e1.debug.resolver.resolver_used, False, "E5: first turn resolver_used = False")

# Turn 2: pronoun follow-up -- deterministic resolver changes question
r_e2 = session_e.respond("should I captain him?", STANDARD_BOOTSTRAP, include_debug=True)
_assert(isinstance(r_e2, FinalResponse), "E6: session respond() returns FinalResponse for follow-up")
_assert_not_none(r_e2.debug, "E7: debug bundle populated for follow-up")
_assert_not_none(r_e2.debug.resolver, "E8: resolver bundle populated for follow-up")
_assert_eq(r_e2.debug.resolver.resolver_source, "fallback_regex", "E9: follow-up resolver_source = fallback_regex")
_assert_eq(r_e2.debug.resolver.resolver_used, True, "E10: follow-up resolver_used = True")
_assert_eq(r_e2.debug.resolver.rewritten_question, "should I captain Haaland?", "E11: rewritten_question = Haaland")
_assert_eq(r_e2.debug.resolver.fallback_reason, "llm_unavailable", "E12: fallback_reason = llm_unavailable (no client)")

# FinalResponse invariants still hold
_assert(len(r_e2.final_text) > 0, "E13: final_text non-empty for follow-up")
_assert_eq(r_e2.outcome, OUTCOME_OK, "E14: outcome=ok for pronoun follow-up (resolved to Haaland)")

# Turn with include_debug=False -- resolver is None
session_e2 = ConversationSession()
r_e_no_debug1 = session_e2.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
r_e_no_debug2 = session_e2.respond("should I captain him?", STANDARD_BOOTSTRAP)
_assert_is_none(r_e_no_debug2.debug, "E15: debug is None without include_debug")

# resolver_confidence is None for deterministic path
_assert_is_none(r_e2.debug.resolver.resolver_confidence, "E16: resolver_confidence = None for fallback_regex")

# Turn 3: unsupported question -- still has resolver bundle
r_e3 = session_e.respond("Is Haaland fit?", STANDARD_BOOTSTRAP, include_debug=True)
_assert_not_none(r_e3.debug, "E17: debug populated for unsupported intent")
_assert_not_none(r_e3.debug.resolver, "E18: resolver populated for unsupported intent")

# Session still works after debug calls
_assert(len(r_e1.final_text) > 0, "E19: Turn 1 final_text non-empty")
_assert(len(r_e3.final_text) > 0, "E20: Turn 3 final_text non-empty")


# ===========================================================================
# Section F -- ResolverDebug content accuracy
# ===========================================================================
_section("F: ResolverDebug content accuracy")

# LLM path with high confidence
s_f = ConversationState()
s_f.last_player_query = "Haaland"
f_llm_json = _make_json_response("Salah", INTENT_CAPTAIN_SCORE, "explicit", 0.9, "en")
f_session_llm = ConversationSession()
# First turn to establish state
f_session_llm.respond("should I captain Haaland", STANDARD_BOOTSTRAP)

# Create a session that uses a mock resolver_client
f_session2 = ConversationSession()
f_r1 = f_session2.respond("should I captain Haaland", STANDARD_BOOTSTRAP, include_debug=True)
_assert_eq(f_r1.debug.resolver.resolver_source, "none", "F1: initial question resolver_source = none")
_assert_eq(f_r1.debug.resolver.resolver_used, False, "F2: initial question resolver_used = False")
_assert_is_none(f_r1.debug.resolver.resolver_confidence, "F3: initial question resolver_confidence = None")
_assert_eq(f_r1.debug.resolver.fallback_reason, "llm_unavailable",
           "F4: initial question fallback_reason = llm_unavailable (no client provided)")
_assert_eq(f_r1.debug.resolver.rewritten_question, "should I captain Haaland", "F5: initial question rewritten_question = original")

# Turn 2 with mock LLM resolver returning high confidence
f_high_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.9, "en")
f_r2 = f_session2.respond("should I captain him?", STANDARD_BOOTSTRAP,
                           resolver_client=_MockClient(f_high_json), include_debug=True)
_assert_eq(f_r2.debug.resolver.resolver_source, "llm", "F6: LLM resolver_source = llm")
_assert_eq(f_r2.debug.resolver.resolver_used, True, "F7: LLM resolver_used = True")
_assert_not_none(f_r2.debug.resolver.resolver_confidence, "F8: LLM resolver_confidence is not None")
_assert_is_none(f_r2.debug.resolver.fallback_reason, "F9: LLM path fallback_reason = None")
_assert(f_r2.debug.resolver.resolver_confidence >= 0.9, "F10: LLM resolver_confidence value correct")

# Turn with low-confidence LLM -- falls back to deterministic
f_session3 = ConversationSession()
f_session3.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
f_low_json = _make_json_response("Haaland", INTENT_CAPTAIN_SCORE, "pronoun", 0.2, "en")
f_r3 = f_session3.respond("should I captain him?", STANDARD_BOOTSTRAP,
                           resolver_client=_MockClient(f_low_json), include_debug=True)
_assert_eq(f_r3.debug.resolver.resolver_source, "fallback_regex", "F11: low confidence falls to fallback_regex")
_assert_eq(f_r3.debug.resolver.fallback_reason, "low_confidence", "F12: low confidence fallback_reason = low_confidence")
_assert_is_none(f_r3.debug.resolver.resolver_confidence, "F13: fallback_regex resolver_confidence = None")

# No pronoun, no LLM client -- resolver_source = none
f_session4 = ConversationSession()
f_session4.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
f_r4 = f_session4.respond("should I captain Salah", STANDARD_BOOTSTRAP, include_debug=True)
_assert_eq(f_r4.debug.resolver.resolver_source, "none", "F14: no pronoun resolver_source = none")
_assert_eq(f_r4.debug.resolver.resolver_used, False, "F15: no pronoun resolver_used = False")
_assert_eq(f_r4.debug.resolver.fallback_reason, "llm_unavailable", "F16: no LLM client fallback_reason = llm_unavailable")

# rewritten_question equals original when resolver_used=False
_assert_eq(f_r4.debug.resolver.rewritten_question, "should I captain Salah",
           "F17: rewritten_question = original when resolver_used=False")

# LLM raises -- fallback_regex
f_session5 = ConversationSession()
f_session5.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
f_raises_client = _MockClient("", raises=True)
f_r5 = f_session5.respond("should I captain him?", STANDARD_BOOTSTRAP,
                           resolver_client=f_raises_client, include_debug=True)
_assert_eq(f_r5.debug.resolver.resolver_source, "fallback_regex", "F18: LLM raises falls to fallback_regex")
_assert_eq(f_r5.debug.resolver.fallback_reason, "llm_unavailable", "F19: LLM raises fallback_reason = llm_unavailable")

# rewritten_question reflects the resolution
_assert("Haaland" in f_r5.debug.resolver.rewritten_question, "F20: rewritten_question contains Haaland after resolution")


# ===========================================================================
# Section G -- run_session() multi-turn plain output
# ===========================================================================
_section("G: run_session() multi-turn plain output")

g_results = run_session(
    ["should I captain Haaland", "should I captain him?"],
    STANDARD_BOOTSTRAP,
)
_assert_eq(len(g_results), 2, "G1: run_session returns 2 results for 2 questions")
_assert_eq(g_results[0]["question"], "should I captain Haaland", "G2: first result question correct")
_assert(len(g_results[0]["final_text"]) > 0, "G3: first result final_text non-empty")
_assert_eq(g_results[0]["outcome"], OUTCOME_OK, "G4: first result outcome = ok")
_assert_eq(g_results[0]["supported"], True, "G5: first result supported = True")
_assert(g_results[0]["intent"] in (INTENT_CAPTAIN_SCORE,), "G6: first result intent = captain_score")
_assert_eq(g_results[1]["question"], "should I captain him?", "G7: second result question correct")
_assert(len(g_results[1]["final_text"]) > 0, "G8: second result final_text non-empty")

# No debug key when debug=False
_assert("debug" not in g_results[0], "G9: no debug key when debug=False first result")
_assert("debug" not in g_results[1], "G10: no debug key when debug=False second result")

# No rewritten_question key when debug=False
_assert("rewritten_question" not in g_results[0], "G11: no rewritten_question key when debug=False first")
_assert("rewritten_question" not in g_results[1], "G12: no rewritten_question key when debug=False second")

# Single-question session
g_single = run_session(["should I captain Haaland"], STANDARD_BOOTSTRAP)
_assert_eq(len(g_single), 1, "G13: single-question session returns 1 result")

# Empty session
g_empty = run_session([], STANDARD_BOOTSTRAP)
_assert_eq(len(g_empty), 0, "G14: empty session returns empty list")

# Unsupported intent still returns result
g_unsupported = run_session(["Is Haaland fit?"], STANDARD_BOOTSTRAP)
_assert_eq(len(g_unsupported), 1, "G15: unsupported intent returns result")


# ===========================================================================
# Section H -- run_session() debug mode resolver metadata in output
# ===========================================================================
_section("H: run_session() debug mode resolver metadata in output")

h_results = run_session(
    ["should I captain Haaland", "should I captain him?"],
    STANDARD_BOOTSTRAP,
    debug=True,
)
_assert_eq(len(h_results), 2, "H1: debug run_session returns 2 results")

# First result has debug key
_assert("debug" in h_results[0], "H2: debug key present in first result")
_assert(isinstance(h_results[0]["debug"], dict), "H3: debug value is dict")

# First turn resolver -- no rewrite
_assert("resolver" in h_results[0]["debug"], "H4: resolver key in debug bundle")
_assert_eq(h_results[0]["debug"]["resolver"]["resolver_source"], "none", "H5: first turn resolver_source = none")
_assert_eq(h_results[0]["debug"]["resolver"]["resolver_used"], False, "H6: first turn resolver_used = False")
_assert_is_none(h_results[0]["debug"]["resolver"]["resolver_confidence"], "H7: first turn resolver_confidence = None")

# First turn -- no rewritten_question in top-level (resolver_used=False)
_assert("rewritten_question" not in h_results[0], "H8: no rewritten_question key when resolver_used=False")

# Second result has debug key
_assert("debug" in h_results[1], "H9: debug key present in second result")

# Second turn resolver -- deterministic rewrite
_assert_eq(h_results[1]["debug"]["resolver"]["resolver_source"], "fallback_regex",
           "H10: second turn resolver_source = fallback_regex")
_assert_eq(h_results[1]["debug"]["resolver"]["resolver_used"], True,
           "H11: second turn resolver_used = True")
_assert_eq(h_results[1]["debug"]["resolver"]["fallback_reason"], "llm_unavailable",
           "H12: second turn fallback_reason = llm_unavailable")

# rewritten_question surfaced in top-level when resolver_used=True
_assert("rewritten_question" in h_results[1],
        "H13: rewritten_question in second result when resolver_used=True")
_assert_eq(h_results[1]["rewritten_question"], "should I captain Haaland?",
           "H14: rewritten_question = Haaland")

# debug bundle has standard fields
for key in ("response_text", "llm_text", "violations", "prompt_used", "model"):
    _assert(key in h_results[0]["debug"], f"H15: debug has {key} field")

# violations is a list
_assert(isinstance(h_results[0]["debug"]["violations"], list), "H16: violations is list")

# Final text non-empty in debug mode
_assert(len(h_results[0]["final_text"]) > 0, "H17: first result final_text non-empty in debug mode")
_assert(len(h_results[1]["final_text"]) > 0, "H18: second result final_text non-empty in debug mode")

# Outcome and supported still correct
_assert_eq(h_results[0]["outcome"], OUTCOME_OK, "H19: first result outcome = ok in debug mode")
_assert_eq(h_results[1]["outcome"], OUTCOME_OK, "H20: second result outcome = ok in debug mode (Haaland resolved)")


# ===========================================================================
# Section I -- FinalResponse contract regression (5 canonical scenarios)
# ===========================================================================
_section("I: FinalResponse contract regression (5 canonical scenarios)")

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
    _assert(isinstance(r, FinalResponse), f"I-{sc['id']}: returns FinalResponse")
    _assert_eq(r.outcome, sc["expected_outcome"], f"I-{sc['id']}: outcome == {sc['expected_outcome']}")
    _assert_eq(r.supported, sc["expected_supported"], f"I-{sc['id']}: supported == {sc['expected_supported']}")
    _assert(len(r.final_text) > 0, f"I-{sc['id']}: final_text is non-empty")
    _assert(
        r.supported == (r.outcome != OUTCOME_UNSUPPORTED_INTENT),
        f"I-{sc['id']}: supported <-> outcome invariant",
    )

# ConversationSession preserves contract
session_i = ConversationSession()
ri1 = session_i.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
_assert(isinstance(ri1, FinalResponse), "I-session: ConversationSession returns FinalResponse")
_assert_eq(ri1.outcome, OUTCOME_OK, "I-session: outcome=ok preserved via session")
_assert(len(ri1.final_text) > 0, "I-session: final_text non-empty via session")

# run_all_final_response still passes
fr_results = run_all_final_response(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)
_assert_eq(len(fr_results), 6, "I-fixtures: run_all_final_response returns 6 results")
for fixture, response in fr_results:
    _assert_eq(
        response.outcome,
        fixture.expected_outcome,
        f"I-fixture-{fixture.scenario_id}: outcome matches fixture",
    )
    _assert(len(response.final_text) > 0, f"I-fixture-{fixture.scenario_id}: final_text non-empty")

# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'='*60}")
total = _pass + _fail
print(f"Phase 4g: {_pass}/{total} assertions passed")
if _fail:
    print(f"  FAILURES: {_fail}")
    sys.exit(1)
else:
    print("  ALL PASS")
    sys.exit(0)
