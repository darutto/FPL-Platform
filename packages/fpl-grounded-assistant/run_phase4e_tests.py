"""
run_phase4e_tests.py
====================
Phase 4e: minimal multi-turn conversation state.

Validates ``ConversationState``, ``resolve_pronouns``, and
``ConversationSession`` in ``fpl_grounded_assistant.conversation_state``.
No live network calls, no LLM calls.

Sections
--------
A  -- imports and module structure
B  -- ConversationState: initial state
C  -- ConversationState: update_from_response — ok + player intent stores query
D  -- ConversationState: update_from_response — non-ok outcomes do not store
E  -- ConversationState: update_from_response — non-player intents do not store
F  -- ConversationState: clear()
G  -- resolve_pronouns: no state (last_player_query is None)
H  -- resolve_pronouns: pronouns substituted when state is set
I  -- resolve_pronouns: word-boundary safety (no false matches)
J  -- resolve_pronouns: multi-word references
K  -- resolve_pronouns: case-insensitive matching
L  -- ConversationSession: construction and initial state
M  -- ConversationSession: turn 1 updates last_player_query on ok
N  -- ConversationSession: turn 2 follow-up resolved correctly
O  -- ConversationSession: non-ok turn does not update player context
P  -- ConversationSession: clear() resets state
Q  -- ConversationSession: stateless respond() unchanged
R  -- FinalResponse contract invariants preserved through session

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner;../fpl-player-registry;../fpl-captain-engine;\\
    ../fpl-data-core;../fpl-tool-contract;../fpl-query-tools;\\
    ../fpl-api-client;../fpl-pipeline;. python run_phase4e_tests.py
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
# Imports
# ---------------------------------------------------------------------------
from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    # outcome / intent constants
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_RANK_CANDIDATES,
    INTENT_UNSUPPORTED,
    # new Phase 4e exports
    ConversationState,
    ConversationSession,
    resolve_pronouns,
    _PRONOUNS,
    # unchanged stateless interface
    respond,
    FinalResponse,
)

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
_passed = 0
_failed = 0


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
# Helpers — minimal FinalResponse stubs for isolated state tests
# ---------------------------------------------------------------------------

def _make_response(outcome: str, intent: str) -> FinalResponse:
    """Build a minimal FinalResponse for state-update unit tests."""
    return FinalResponse(
        final_text="stub",
        outcome=outcome,
        supported=(outcome != OUTCOME_UNSUPPORTED_INTENT),
        intent=intent,
        review_passed=True,
        llm_used=False,
        debug=None,
    )


# ===========================================================================
# Section A -- imports and module structure
# ===========================================================================
_section("A -- imports and module structure")

ok("A1  ConversationState imported",  True)
ok("A2  ConversationSession imported", True)
ok("A3  resolve_pronouns imported",   True)
ok("A4  _PRONOUNS is a tuple",        isinstance(_PRONOUNS, tuple))
ok("A5  _PRONOUNS is non-empty",      len(_PRONOUNS) > 0)
ok("A6  _PRONOUNS contains 'him'",    "him"  in _PRONOUNS)
ok("A7  _PRONOUNS contains 'her'",    "her"  in _PRONOUNS)
ok("A8  _PRONOUNS contains 'he'",     "he"   in _PRONOUNS)
ok("A9  _PRONOUNS contains 'they'",   "they" in _PRONOUNS)
ok("A10 _PRONOUNS contains 'the player'",  "the player"  in _PRONOUNS)
ok("A11 _PRONOUNS contains 'this player'", "this player" in _PRONOUNS)


# ===========================================================================
# Section B -- ConversationState: initial state
# ===========================================================================
_section("B -- ConversationState: initial state")

_b_state = ConversationState()
ok("B1  ConversationState() constructs without error", True)
ok("B2  last_player_query is None initially", _b_state.last_player_query is None)
eq("B3  turn_count is 0 initially",           _b_state.turn_count, 0)
ok("B4  has update_from_response method",     callable(_b_state.update_from_response))
ok("B5  has clear method",                    callable(_b_state.clear))


# ===========================================================================
# Section C -- ConversationState: update stores query on ok + player intent
# ===========================================================================
_section("C -- update_from_response: ok + player intent stores query")

_PLAYER_INTENTS = (INTENT_CAPTAIN_SCORE, INTENT_PLAYER_SUMMARY, INTENT_PLAYER_RESOLVE)

for _intent in _PLAYER_INTENTS:
    _s = ConversationState()
    _r = _make_response(OUTCOME_OK, _intent)
    _s.update_from_response(_r, "Haaland")
    eq(f"C1.{_intent}  last_player_query updated", _s.last_player_query, "Haaland")
    eq(f"C2.{_intent}  turn_count incremented",    _s.turn_count, 1)


# ===========================================================================
# Section D -- ConversationState: non-ok outcomes do not store player
# ===========================================================================
_section("D -- update_from_response: non-ok outcomes do not store")

for _outcome in (OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS, OUTCOME_MISSING_ARGUMENTS,
                 OUTCOME_UNSUPPORTED_INTENT):
    _s = ConversationState()
    _r = _make_response(_outcome, INTENT_CAPTAIN_SCORE)
    _s.update_from_response(_r, "Haaland")
    ok(f"D1.{_outcome}  last_player_query stays None",
       _s.last_player_query is None)
    eq(f"D2.{_outcome}  turn_count still incremented",
       _s.turn_count, 1)


# ===========================================================================
# Section E -- ConversationState: non-player intents do not store player
# ===========================================================================
_section("E -- update_from_response: non-player intents do not store")

for _intent in (INTENT_RANK_CANDIDATES, INTENT_UNSUPPORTED):
    _s = ConversationState()
    _r = _make_response(OUTCOME_OK, _intent)
    _s.update_from_response(_r, "Haaland")
    ok(f"E1.{_intent}  last_player_query stays None",
       _s.last_player_query is None)
    eq(f"E2.{_intent}  turn_count incremented",
       _s.turn_count, 1)


# ===========================================================================
# Section F -- ConversationState: clear()
# ===========================================================================
_section("F -- ConversationState: clear()")

_f_state = ConversationState()
_f_state.update_from_response(_make_response(OUTCOME_OK, INTENT_CAPTAIN_SCORE), "Salah")
_f_state.update_from_response(_make_response(OUTCOME_OK, INTENT_CAPTAIN_SCORE), "Salah")

ok("F1  state non-empty before clear", _f_state.last_player_query is not None)
ok("F2  turn_count non-zero before clear", _f_state.turn_count > 0)

_f_state.clear()
ok("F3  last_player_query is None after clear", _f_state.last_player_query is None)
eq("F4  turn_count is 0 after clear",           _f_state.turn_count, 0)

# State is reusable after clear
_f_state.update_from_response(_make_response(OUTCOME_OK, INTENT_CAPTAIN_SCORE), "Mane")
eq("F5  state accepts updates after clear", _f_state.last_player_query, "Mane")


# ===========================================================================
# Section G -- resolve_pronouns: no state → question unchanged
# ===========================================================================
_section("G -- resolve_pronouns: no state (last_player_query is None)")

_g_state = ConversationState()  # last_player_query = None

_g_questions = [
    "should I captain him?",
    "tell me about her",
    "stats for the player",
    "who is he?",
    "what gameweek is it?",
    "should I captain Haaland",
]
for _q in _g_questions:
    eq(f"G1.{_q[:25]}  unchanged",
       resolve_pronouns(_q, _g_state), _q)


# ===========================================================================
# Section H -- resolve_pronouns: pronouns substituted when state is set
# ===========================================================================
_section("H -- resolve_pronouns: substitution with state set")

_h_state = ConversationState()
_h_state.last_player_query = "Haaland"

_h_cases = [
    ("should I captain him?",    "should I captain Haaland?"),
    ("captain score for him",    "captain score for Haaland"),
    ("tell me about him",        "tell me about Haaland"),
    ("stats for him",            "stats for Haaland"),
    ("who is he?",               "who is Haaland?"),
    ("should I pick her",        "should I pick Haaland"),
    ("captain score for her",    "captain score for Haaland"),
    ("tell me about the player", "tell me about Haaland"),
]
for _q, _expected in _h_cases:
    eq(f"H1.{_q[:30]}",
       resolve_pronouns(_q, _h_state), _expected)


# ===========================================================================
# Section I -- resolve_pronouns: word-boundary safety
# ===========================================================================
_section("I -- resolve_pronouns: word-boundary safety")

_i_state = ConversationState()
_i_state.last_player_query = "Haaland"

# "him" must NOT match inside "Birmingham"
eq("I1  'him' not matched inside 'Birmingham'",
   resolve_pronouns("Birmingham striker", _i_state),
   "Birmingham striker")

# "her" must NOT match inside "Hereford"
eq("I2  'her' not matched inside 'Hereford'",
   resolve_pronouns("Hereford player", _i_state),
   "Hereford player")

# "he" must NOT match inside "Hector"
eq("I3  'he' not matched inside 'Hector'",
   resolve_pronouns("Hector Bellerin stats", _i_state),
   "Hector Bellerin stats")

# Standalone pronoun still works after the boundary tests
eq("I4  standalone 'him' still resolves",
   resolve_pronouns("tell me about him", _i_state),
   "tell me about Haaland")

# Question with no pronouns at all — unchanged
eq("I5  no pronoun → unchanged",
   resolve_pronouns("should I captain Salah", _i_state),
   "should I captain Salah")


# ===========================================================================
# Section J -- resolve_pronouns: multi-word references
# ===========================================================================
_section("J -- resolve_pronouns: multi-word references")

_j_state = ConversationState()
_j_state.last_player_query = "Salah"

_j_cases = [
    ("captain score for the player",   "captain score for Salah"),
    ("tell me about this player",       "tell me about Salah"),
    ("stats for that player",           "stats for Salah"),
    ("should I captain the player",     "should I captain Salah"),
]
for _q, _expected in _j_cases:
    eq(f"J1.{_q[:35]}",
       resolve_pronouns(_q, _j_state), _expected)


# ===========================================================================
# Section K -- resolve_pronouns: case-insensitive matching
# ===========================================================================
_section("K -- resolve_pronouns: case-insensitive matching")

_k_state = ConversationState()
_k_state.last_player_query = "Haaland"

eq("K1  'HIM' resolved",
   resolve_pronouns("should I captain HIM?", _k_state),
   "should I captain Haaland?")
eq("K2  'Him' resolved",
   resolve_pronouns("captain score for Him", _k_state),
   "captain score for Haaland")
eq("K3  'HE' resolved",
   resolve_pronouns("who is HE?", _k_state),
   "who is Haaland?")
eq("K4  'The Player' resolved",
   resolve_pronouns("tell me about The Player", _k_state),
   "tell me about Haaland")


# ===========================================================================
# Section L -- ConversationSession: construction and initial state
# ===========================================================================
_section("L -- ConversationSession: construction and initial state")

_l_sess = ConversationSession()
ok("L1  ConversationSession() constructs without error", True)
ok("L2  has state attribute",         hasattr(_l_sess, "state"))
ok("L3  state is ConversationState",  isinstance(_l_sess.state, ConversationState))
ok("L4  last_player_query is None",   _l_sess.last_player_query is None)
eq("L5  turn_count is 0",             _l_sess.turn_count, 0)
ok("L6  has respond method",          callable(_l_sess.respond))
ok("L7  has clear method",            callable(_l_sess.clear))

# Pre-built state injection
_l_pre = ConversationState()
_l_pre.last_player_query = "Salah"
_l_sess2 = ConversationSession(state=_l_pre)
eq("L8  injected state preserved", _l_sess2.last_player_query, "Salah")


# ===========================================================================
# Section M -- ConversationSession: turn 1 updates last_player_query on ok
# ===========================================================================
_section("M -- ConversationSession: turn 1 updates state on ok")

_m_sess = ConversationSession()
_m_r1 = _m_sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP)

ok("M1  FinalResponse returned",           isinstance(_m_r1, FinalResponse))
eq("M2  outcome is ok",                    _m_r1.outcome, OUTCOME_OK)
eq("M3  intent is captain_score",          _m_r1.intent, INTENT_CAPTAIN_SCORE)
ok("M4  last_player_query now set",        _m_sess.last_player_query is not None)
eq("M5  last_player_query is 'Haaland'",   _m_sess.last_player_query, "Haaland")
eq("M6  turn_count is 1",                  _m_sess.turn_count, 1)
ok("M7  final_text non-empty",             len(_m_r1.final_text) > 0)
ok("M8  supported is True",               _m_r1.supported is True)


# ===========================================================================
# Section N -- ConversationSession: turn 2 follow-up resolved correctly
# ===========================================================================
_section("N -- ConversationSession: turn 2 follow-up via pronoun resolution")

_n_sess = ConversationSession()
# Turn 1 — establish player context
_n_r1 = _n_sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
eq("N1  turn 1 outcome ok",  _n_r1.outcome, OUTCOME_OK)
eq("N2  context stored",     _n_sess.last_player_query, "Haaland")

# Turn 2 — pronoun follow-up
_n_r2 = _n_sess.respond("should I captain him?", STANDARD_BOOTSTRAP)
ok("N3  FinalResponse returned for follow-up",   isinstance(_n_r2, FinalResponse))
ok("N4  follow-up still supported",              _n_r2.supported is True)
eq("N5  follow-up outcome ok",                   _n_r2.outcome, OUTCOME_OK)
eq("N6  follow-up intent is captain_score",      _n_r2.intent, INTENT_CAPTAIN_SCORE)
ok("N7  follow-up final_text non-empty",         len(_n_r2.final_text) > 0)
eq("N8  turn_count is 2",                        _n_sess.turn_count, 2)

# Turn 2b — player summary follow-up
_n_sess2 = ConversationSession()
_n_sess2.respond("should I captain Salah", STANDARD_BOOTSTRAP)
_n_r2b = _n_sess2.respond("tell me about him", STANDARD_BOOTSTRAP)
ok("N9  summary follow-up supported",   _n_r2b.supported is True)
eq("N10 summary follow-up intent",      _n_r2b.intent, INTENT_PLAYER_SUMMARY)


# ===========================================================================
# Section O -- ConversationSession: non-ok turn does not update player context
# ===========================================================================
_section("O -- ConversationSession: non-ok turns do not update context")

# not_found: player not in bootstrap
_o_sess = ConversationSession()
_o_r1 = _o_sess.respond("should I captain xyznotaplayer999", STANDARD_BOOTSTRAP)
eq("O1  outcome is not_found",          _o_r1.outcome, OUTCOME_NOT_FOUND)
ok("O2  last_player_query stays None",  _o_sess.last_player_query is None)
eq("O3  turn_count still incremented",  _o_sess.turn_count, 1)

# unsupported: no player context stored
_o_sess2 = ConversationSession()
_o_r2 = _o_sess2.respond("Is Haaland fit to play?", STANDARD_BOOTSTRAP)
eq("O4  outcome is unsupported",        _o_r2.outcome, OUTCOME_UNSUPPORTED_INTENT)
ok("O5  last_player_query stays None",  _o_sess2.last_player_query is None)

# missing_arguments: ranking without candidates
_o_sess3 = ConversationSession()
_o_r3 = _o_sess3.respond("top captains this week", STANDARD_BOOTSTRAP)
eq("O6  outcome is missing_arguments",  _o_r3.outcome, OUTCOME_MISSING_ARGUMENTS)
ok("O7  last_player_query stays None",  _o_sess3.last_player_query is None)


# ===========================================================================
# Section P -- ConversationSession: clear() resets state
# ===========================================================================
_section("P -- ConversationSession: clear() resets state")

_p_sess = ConversationSession()
_p_sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok("P1  state set before clear",  _p_sess.last_player_query is not None)
ok("P2  turn_count > 0",          _p_sess.turn_count > 0)

_p_sess.clear()
ok("P3  last_player_query None after clear", _p_sess.last_player_query is None)
eq("P4  turn_count 0 after clear",           _p_sess.turn_count, 0)

# Session still usable after clear
_p_r2 = _p_sess.respond("should I captain Salah", STANDARD_BOOTSTRAP)
ok("P5  session usable after clear",      isinstance(_p_r2, FinalResponse))
eq("P6  context updated again after clear", _p_sess.last_player_query, "Salah")


# ===========================================================================
# Section Q -- ConversationSession: stateless respond() unchanged
# ===========================================================================
_section("Q -- stateless respond() unchanged")

# Direct respond() call — no session, no state
_q_r = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok("Q1  stateless respond() returns FinalResponse", isinstance(_q_r, FinalResponse))
eq("Q2  stateless outcome ok",   _q_r.outcome, OUTCOME_OK)
ok("Q3  stateless final_text",   len(_q_r.final_text) > 0)
ok("Q4  stateless supported",    _q_r.supported is True)

# Session respond() and stateless respond() return equivalent results
_q_sess = ConversationSession()
_q_sr = _q_sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
eq("Q5  session outcome matches stateless",  _q_sr.outcome,  _q_r.outcome)
eq("Q6  session intent matches stateless",   _q_sr.intent,   _q_r.intent)
eq("Q7  session supported matches stateless", _q_sr.supported, _q_r.supported)


# ===========================================================================
# Section R -- FinalResponse contract invariants through session
# ===========================================================================
_section("R -- FinalResponse contract invariants through session")

_r_sess = ConversationSession()
_r_responses = [
    _r_sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP),
    _r_sess.respond("should I captain him?",    STANDARD_BOOTSTRAP),  # follow-up
    _r_sess.respond("tell me about him",         STANDARD_BOOTSTRAP),  # follow-up
    _r_sess.respond("Is Haaland fit to play?",   STANDARD_BOOTSTRAP),  # unsupported
    _r_sess.respond("top captains this week",    STANDARD_BOOTSTRAP),  # missing args
]

ok("R1  all turns return FinalResponse",
   all(isinstance(r, FinalResponse) for r in _r_responses))

ok("R2  all final_text fields are non-empty strings",
   all(isinstance(r.final_text, str) and len(r.final_text) > 0
       for r in _r_responses))

ok("R3  supported == (outcome != unsupported_intent) for all",
   all(r.supported == (r.outcome != OUTCOME_UNSUPPORTED_INTENT)
       for r in _r_responses))

ok("R4  all review_passed are True (deterministic mode, no LLM)",
   all(r.review_passed is True for r in _r_responses))

ok("R5  all llm_used are False (no API key in test)",
   all(r.llm_used is False for r in _r_responses))

ok("R6  all outcomes are non-empty strings",
   all(isinstance(r.outcome, str) and len(r.outcome) > 0
       for r in _r_responses))

ok("R7  all intents are non-empty strings",
   all(isinstance(r.intent, str) and len(r.intent) > 0
       for r in _r_responses))

eq("R8  turn_count equals number of respond() calls",
   _r_sess.turn_count, len(_r_responses))


# ===========================================================================
# Final summary
# ===========================================================================
print(f"\n{'=' * 60}")
total = _passed + _failed
print(f"{'PASS' if _failed == 0 else 'FAIL'}  {_passed}/{total} assertions")
if _failed:
    print(f"  {_failed} assertion(s) failed — see FAIL lines above")
print("=" * 60)

sys.exit(0 if _failed == 0 else 1)
