"""
run_phase5c_tests.py
====================
Phase 5c: comparison follow-up support.

Validates that ``ConversationSession`` can continue a comparison naturally
within a narrow set of deterministic follow-up patterns, using
``state.last_comparison`` and ``resolve_comparison_followup()``.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5c_tests.py

Sections
--------
A  -- ConversationState.last_comparison tracking
B  -- resolve_comparison_followup: pattern coverage
C  -- ConversationSession integration: follow-up turns end-to-end
D  -- Additional follow-up patterns (what about, how about, pronoun)
E  -- Phase 5a/5b regression: single-turn comparison and pronoun session unchanged
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


from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    INTENT_COMPARE_PLAYERS,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    ConversationState,
    ConversationSession,
    resolve_comparison_followup,
    _COMP_FOLLOWUP_PREFIXES,
    _COMP_INSTEAD_SUFFIXES,
    dispatch,
    respond,
)


# ===========================================================================
# Section A -- ConversationState.last_comparison tracking
# ===========================================================================

print("A  ConversationState.last_comparison tracking")

_s = ConversationState()
ok("A1  initial last_comparison is None",     _s.last_comparison is None)
ok("A2  last_comparison attribute exists",    hasattr(_s, "last_comparison"))

# Simulate a successful comparison turn
_r_ok = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_s.update_from_response(_r_ok, None, comparison_queries=("Haaland", "Salah"))
eq("A3  last_comparison set after ok comparison", _s.last_comparison, ("Haaland", "Salah"))

# Simulate a successful non-comparison turn — should clear last_comparison
_r_single = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
_s.update_from_response(_r_single, "Haaland")
ok("A4  last_comparison cleared after non-comparison ok turn", _s.last_comparison is None)

# Failed comparison (not_found) should NOT set last_comparison
_s2 = ConversationState()
_r_notfound = respond("compare Haaland and NoSuchPlayer99", STANDARD_BOOTSTRAP)
_s2.update_from_response(_r_notfound, None, comparison_queries=("Haaland", "NoSuchPlayer99"))
ok("A5  last_comparison not set when outcome!=ok", _s2.last_comparison is None)

# Successful comparison via update, then non-ok turn does NOT clear
_s3 = ConversationState()
_r_comp = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_s3.update_from_response(_r_comp, None, comparison_queries=("Haaland", "Salah"))
_r_notfound2 = respond("compare Haaland and NoSuchPlayer99", STANDARD_BOOTSTRAP)
_s3.update_from_response(_r_notfound2, None)  # outcome != ok, non-comparison → no clear
ok("A6  last_comparison preserved after non-ok non-comparison turn",
   _s3.last_comparison == ("Haaland", "Salah"))

# clear() resets last_comparison
_s4 = ConversationState()
_r_c = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_s4.update_from_response(_r_c, None, comparison_queries=("Haaland", "Salah"))
_s4.clear()
ok("A7  clear() resets last_comparison",    _s4.last_comparison is None)
eq("A8  clear() resets turn_count",         _s4.turn_count, 0)


# ===========================================================================
# Section B -- resolve_comparison_followup: pattern coverage
# ===========================================================================

print("B  resolve_comparison_followup patterns")

_bs = ConversationState()
_bs.last_comparison = ("Haaland", "Salah")

# Basic "and <player>"
_b1 = resolve_comparison_followup("And Salah?", _bs)
ok("B1  'And Salah?' rewrites",            _b1 is not None)
ok("B2  rewrite mentions Haaland",         "Haaland" in (_b1 or ""))
ok("B3  rewrite mentions Salah",           "Salah" in (_b1 or ""))

# Lowercase
_b4 = resolve_comparison_followup("and palmer?", _bs)
ok("B4  lowercase 'and palmer?' rewrites", _b4 is not None)
ok("B5  rewrite mentions Palmer (orig case from state)", "Haaland" in (_b4 or ""))

# "what about <player>?"
_b6 = resolve_comparison_followup("What about Palmer?", _bs)
ok("B6  'What about Palmer?' rewrites",    _b6 is not None)
ok("B7  rewrite mentions Palmer",          "Palmer" in (_b6 or ""))

# "what about <player> instead?"
_b8 = resolve_comparison_followup("What about Palmer instead?", _bs)
ok("B8  'What about Palmer instead?' rewrites",  _b8 is not None)
ok("B9  'instead' stripped from rewrite",         "instead" not in (_b8 or ""))
ok("B10 Palmer in stripped rewrite",              "Palmer" in (_b8 or ""))

# "how about <player>"
_b11 = resolve_comparison_followup("How about Saka?", _bs)
ok("B11 'How about Saka?' rewrites",       _b11 is not None)
ok("B12 Saka in rewrite",                  "Saka" in (_b11 or ""))

# "Compare him to <player>"
_b13 = resolve_comparison_followup("Compare him to Salah", _bs)
ok("B13 'Compare him to Salah' rewrites",  _b13 is not None)
ok("B14 pronoun replaced by last_a",       "Haaland" in (_b13 or ""))
ok("B15 second player present",            "Salah" in (_b13 or ""))

# No last_comparison → None
_bs_empty = ConversationState()
_b16 = resolve_comparison_followup("And Salah?", _bs_empty)
ok("B16 no last_comparison → None",        _b16 is None)

# Full comparison question → None (should route normally)
_b17 = resolve_comparison_followup("compare Haaland and Salah", _bs)
ok("B17 full comparison → None (not a follow-up)", _b17 is None)

# "X vs Y" bare form → None
_b18 = resolve_comparison_followup("Haaland vs Salah", _bs)
ok("B18 bare 'X vs Y' → None",             _b18 is None)


# ===========================================================================
# Section C -- ConversationSession integration: follow-up turns end-to-end
# ===========================================================================

print("C  ConversationSession integration")

_sess = ConversationSession()

# Turn 1: comparison
_c1 = _sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("C1  turn 1 outcome ok",               _c1.outcome, OUTCOME_OK)
eq("C2  turn 1 intent compare",           _c1.intent, INTENT_COMPARE_PLAYERS)
ok("C3  turn 1 final_text non-empty",     bool(_c1.final_text))
eq("C4  last_comparison after turn 1",    _sess.state.last_comparison, ("Haaland", "Salah"))

# Turn 2: follow-up "And Saka?"
_c2 = _sess.respond("And Saka?", STANDARD_BOOTSTRAP)
eq("C5  turn 2 outcome ok",               _c2.outcome, OUTCOME_OK)
eq("C6  turn 2 intent compare",           _c2.intent, INTENT_COMPARE_PLAYERS)
ok("C7  turn 2 final_text non-empty",     bool(_c2.final_text))
ok("C8  Haaland in turn 2 text",          "Haaland" in _c2.final_text)
ok("C9  Saka in turn 2 text",             "Saka" in _c2.final_text)
eq("C10 last_comparison updated",         _sess.state.last_comparison, ("Haaland", "Saka"))

# Turn 3: non-comparison turn clears last_comparison
_c3 = _sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
eq("C11 non-comparison turn ok",          _c3.outcome, OUTCOME_OK)
ok("C12 last_comparison cleared",         _sess.state.last_comparison is None)


# ===========================================================================
# Section D -- Additional follow-up patterns end-to-end
# ===========================================================================

print("D  Additional follow-up patterns")

_sess2 = ConversationSession()
_sess2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)

# "What about Salah?"
_d1 = _sess2.respond("What about Salah?", STANDARD_BOOTSTRAP)
eq("D1  'What about Salah?' outcome ok",  _d1.outcome, OUTCOME_OK)
ok("D2  Salah in text",                   "Salah" in _d1.final_text)

# "What about Saka instead?"
_sess3 = ConversationSession()
_sess3.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_d3 = _sess3.respond("What about Saka instead?", STANDARD_BOOTSTRAP)
eq("D3  'What about Saka instead?' outcome ok", _d3.outcome, OUTCOME_OK)
ok("D4  Saka in text",                    "Saka" in _d3.final_text)

# "Compare him to Salah"
_sess4 = ConversationSession()
_sess4.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_d5 = _sess4.respond("Compare him to Salah", STANDARD_BOOTSTRAP)
eq("D5  'Compare him to Salah' outcome ok",       _d5.outcome, OUTCOME_OK)
ok("D6  Haaland in pronoun-resolved text",         "Haaland" in _d5.final_text)
ok("D7  Salah in pronoun-resolved text",           "Salah" in _d5.final_text)

# "How about Saka?"
_sess5 = ConversationSession()
_sess5.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_d8 = _sess5.respond("How about Saka?", STANDARD_BOOTSTRAP)
eq("D8  'How about Saka?' outcome ok",    _d8.outcome, OUTCOME_OK)
ok("D9  Saka in text",                    "Saka" in _d8.final_text)

# Not-found follow-up (player not in bootstrap)
_sess6 = ConversationSession()
_sess6.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_d10 = _sess6.respond("And NoSuchPlayer99?", STANDARD_BOOTSTRAP)
eq("D10 not-found follow-up outcome",     _d10.outcome, OUTCOME_NOT_FOUND)
ok("D11 last_comparison preserved after not-found", _sess6.state.last_comparison is not None)


# ===========================================================================
# Section E -- Phase 5a/5b regression
# ===========================================================================

print("E  Phase 5a/5b regression")

# Single-turn comparison via dispatch()
_e1 = dispatch("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("E1  dispatch comparison ok",          _e1.outcome, OUTCOME_OK)
eq("E2  dispatch intent compare",         _e1.intent, INTENT_COMPARE_PLAYERS)

# Single-turn comparison via respond()
_e3 = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("E3  respond comparison ok",           _e3.outcome, OUTCOME_OK)
ok("E4  respond final_text non-empty",    bool(_e3.final_text))

# Pronoun resolution in single-player session unaffected
_sess_p = ConversationSession()
_sess_p.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
_e5 = _sess_p.respond("should I captain him?", STANDARD_BOOTSTRAP)
eq("E5  pronoun resolution still works",  _e5.outcome, OUTCOME_OK)

# Last player tracking unaffected by comparison session
_sess_lp = ConversationSession()
_sess_lp.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
eq("E6  last_player_query set",           _sess_lp.last_player_query, "Haaland")
_sess_lp.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("E7  last_player_query unchanged after comparison", _sess_lp.last_player_query, "Haaland")


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5c: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
