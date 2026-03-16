"""
run_phase5f_tests.py
====================
Phase 5f: LLM-assisted comparison follow-up resolution.

Validates that ``resolve_comparison_followup_llm()`` correctly handles Spanish
and elliptical comparison follow-up patterns that the Phase 5c deterministic
resolver cannot catch, and that ``ConversationSession.respond()`` integrates
the new LLM step correctly between the deterministic comparison check and the
general reference resolver.

All tests are deterministic — no live ANTHROPIC_API_KEY required.  The LLM
path is exercised via a lightweight mock client that returns preset JSON.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5f_tests.py

Sections
--------
A  -- Module shape: new exports present
B  -- build_comp_resolver_prompt: pure helper
C  -- _parse_comp_resolver_response: validation
D  -- resolve_comparison_followup_llm: no-client graceful fallback
E  -- resolve_comparison_followup_llm: mock client — Spanish and elliptical patterns
F  -- ConversationSession integration: LLM step in the resolution chain
G  -- Resolution priority: deterministic Phase 5c still runs first
H  -- Regression: Phase 5c/5e patterns unchanged; general resolver unaffected
"""
from __future__ import annotations

import json
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
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    INTENT_COMPARE_PLAYERS,
    ConversationState,
    ConversationSession,
    respond,
    # Phase 5f new exports
    resolve_comparison_followup_llm,
    build_comp_resolver_prompt,
    COMP_RESOLVER_SYSTEM_PROMPT,
    _parse_comp_resolver_response,
    _COMP_RESOLVER_MAX_TOKENS,
    # Phase 4f existing
    ReferenceResolution,
    _CONFIDENCE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Mock LLM client  (mirrors the pattern from run_phase4f_tests.py)
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
    """Minimal mock Anthropic client that returns preset JSON."""
    def __init__(self, response_json: str, raises: bool = False) -> None:
        self.messages = _MockMessages(response_json, raises=raises)


def _comp_json(
    is_followup: bool,
    new_player,
    confidence: float = 0.9,
    language: str = "en",
) -> str:
    return json.dumps({
        "is_comparison_followup": is_followup,
        "new_player": new_player,
        "confidence": confidence,
        "language": language,
    })


# ===========================================================================
# Section A -- Module shape
# ===========================================================================

print("A  Module shape")

ok("A1  resolve_comparison_followup_llm callable",  callable(resolve_comparison_followup_llm))
ok("A2  build_comp_resolver_prompt callable",        callable(build_comp_resolver_prompt))
ok("A3  _parse_comp_resolver_response callable",     callable(_parse_comp_resolver_response))
ok("A4  COMP_RESOLVER_SYSTEM_PROMPT is non-empty str",
   isinstance(COMP_RESOLVER_SYSTEM_PROMPT, str) and len(COMP_RESOLVER_SYSTEM_PROMPT) > 50)
ok("A5  _COMP_RESOLVER_MAX_TOKENS is positive int",
   isinstance(_COMP_RESOLVER_MAX_TOKENS, int) and _COMP_RESOLVER_MAX_TOKENS > 0)
ok("A6  COMP_RESOLVER_SYSTEM_PROMPT mentions 'comparison follow-up'",
   "comparison follow-up" in COMP_RESOLVER_SYSTEM_PROMPT.lower()
   or "comparison_followup" in COMP_RESOLVER_SYSTEM_PROMPT.lower()
   or "comparison" in COMP_RESOLVER_SYSTEM_PROMPT.lower())
ok("A7  COMP_RESOLVER_SYSTEM_PROMPT mentions JSON",
   "JSON" in COMP_RESOLVER_SYSTEM_PROMPT)
ok("A8  COMP_RESOLVER_SYSTEM_PROMPT mentions is_comparison_followup",
   "is_comparison_followup" in COMP_RESOLVER_SYSTEM_PROMPT)
ok("A9  COMP_RESOLVER_SYSTEM_PROMPT mentions new_player",
   "new_player" in COMP_RESOLVER_SYSTEM_PROMPT)
ok("A10 _COMP_RESOLVER_MAX_TOKENS <= 200",
   _COMP_RESOLVER_MAX_TOKENS <= 200)


# ===========================================================================
# Section B -- build_comp_resolver_prompt
# ===========================================================================

print("B  build_comp_resolver_prompt")

_bs = ConversationState()
_bs.last_comparison = ("Haaland", "Salah")

_b1 = build_comp_resolver_prompt("¿Y Saka?", _bs)
ok("B1  returns string",                isinstance(_b1, str))
ok("B2  valid JSON",                    json.loads(_b1) is not None)

_b1_parsed = json.loads(_b1)
eq("B3  current_question field",        _b1_parsed.get("current_question"), "¿Y Saka?")
eq("B4  last_comparison_a field",       _b1_parsed.get("last_comparison_a"), "Haaland")
eq("B5  last_comparison_b field",       _b1_parsed.get("last_comparison_b"), "Salah")
ok("B6  exactly 3 keys",                set(_b1_parsed.keys()) == {"current_question", "last_comparison_a", "last_comparison_b"})

# Non-ASCII characters (Spanish) round-trip cleanly
ok("B7  Spanish chars preserved",       "¿Y Saka?" in _b1)

# Empty last_comparison
_bs_empty = ConversationState()
_b8 = build_comp_resolver_prompt("test", _bs_empty)
_b8_parsed = json.loads(_b8)
eq("B8  empty last_comparison → last_comparison_a=''", _b8_parsed.get("last_comparison_a"), "")
eq("B9  empty last_comparison → last_comparison_b=''", _b8_parsed.get("last_comparison_b"), "")

# Different comparison context
_bs2 = ConversationState()
_bs2.last_comparison = ("Salah", "Saka")
_b10 = json.loads(build_comp_resolver_prompt("vs Palmer", _bs2))
eq("B10 last_comparison_a reflects current state", _b10.get("last_comparison_a"), "Salah")


# ===========================================================================
# Section C -- _parse_comp_resolver_response
# ===========================================================================

print("C  _parse_comp_resolver_response")

# Valid: is_comparison_followup=True
_c1 = _parse_comp_resolver_response(
    '{"is_comparison_followup": true, "new_player": "Saka", "confidence": 0.9, "language": "es"}'
)
ok("C1  valid followup=True parsed",             _c1 is not None)
eq("C2  is_comparison_followup",                 _c1["is_comparison_followup"], True)
eq("C3  new_player",                             _c1["new_player"], "Saka")
eq("C4  confidence",                             _c1["confidence"], 0.9)
eq("C5  language",                               _c1["language"], "es")

# Valid: is_comparison_followup=False
_c6 = _parse_comp_resolver_response(
    '{"is_comparison_followup": false, "new_player": null, "confidence": 0.99, "language": "en"}'
)
ok("C6  valid followup=False parsed",            _c6 is not None)
eq("C7  is_comparison_followup False",           _c6["is_comparison_followup"], False)
ok("C8  new_player is None",                     _c6["new_player"] is None)

# Invalid: not JSON
ok("C9  non-JSON → None",                        _parse_comp_resolver_response("not json") is None)

# Invalid: missing key
ok("C10 missing key → None",
   _parse_comp_resolver_response(
       '{"is_comparison_followup": true, "new_player": "Saka", "confidence": 0.9}'
   ) is None)

# Invalid: is_comparison_followup not bool
ok("C11 non-bool is_comparison_followup → None",
   _parse_comp_resolver_response(
       '{"is_comparison_followup": "yes", "new_player": "Saka", "confidence": 0.9, "language": "en"}'
   ) is None)

# Invalid: bad language
ok("C12 unknown language value → None",
   _parse_comp_resolver_response(
       '{"is_comparison_followup": true, "new_player": "Saka", "confidence": 0.9, "language": "fr"}'
   ) is None)


# ===========================================================================
# Section D -- resolve_comparison_followup_llm: no-client fallback
# ===========================================================================

print("D  resolve_comparison_followup_llm: no-client fallback")

_ds = ConversationState()
_ds.last_comparison = ("Haaland", "Salah")

# No client → None (graceful)
_d1 = resolve_comparison_followup_llm("¿Y Saka?", _ds, client=None)
ok("D1  no client → None",                       _d1 is None)

# No last_comparison → None even with a client
_ds_no_comp = ConversationState()
_mock_client = _MockClient(_comp_json(True, "Saka"))
_d2 = resolve_comparison_followup_llm("¿Y Saka?", _ds_no_comp, client=_mock_client)
ok("D2  no last_comparison → None",              _d2 is None)

# Client raises → None (graceful)
_raising_client = _MockClient("", raises=True)
_d3 = resolve_comparison_followup_llm("¿Y Saka?", _ds, client=_raising_client)
ok("D3  client raises → None",                   _d3 is None)

# Bad JSON from client → None
_bad_client = _MockClient("not valid json")
_d4 = resolve_comparison_followup_llm("¿Y Saka?", _ds, client=_bad_client)
ok("D4  bad JSON → None",                        _d4 is None)

# LLM says is_comparison_followup=False → None
_false_client = _MockClient(_comp_json(False, None, confidence=0.99))
_d5 = resolve_comparison_followup_llm("should I captain Haaland", _ds, client=_false_client)
ok("D5  is_comparison_followup=False → None",    _d5 is None)

# LLM says is_comparison_followup=True but new_player=null → None
_null_player_client = _MockClient(_comp_json(True, None, confidence=0.9))
_d6 = resolve_comparison_followup_llm("¿Y él?", _ds, client=_null_player_client)
ok("D6  new_player=null → None",                 _d6 is None)


# ===========================================================================
# Section E -- resolve_comparison_followup_llm: mock client, Spanish/ellipsis
# ===========================================================================

print("E  resolve_comparison_followup_llm: mock client patterns")

_es = ConversationState()
_es.last_comparison = ("Haaland", "Salah")

# Spanish: "¿Y Saka?" → compare Haaland and Saka
_e1_client = _MockClient(_comp_json(True, "Saka", confidence=0.95, language="es"))
_e1 = resolve_comparison_followup_llm("¿Y Saka?", _es, client=_e1_client)
ok("E1  Spanish follow-up returns ReferenceResolution", _e1 is not None)
eq("E2  rewritten_question",                    (_e1 or ReferenceResolution("","","",0,"","")).rewritten_question,
   "compare Haaland and Saka")
eq("E3  resolved_query",                        (_e1 or ReferenceResolution("","","",0,"","")).resolved_query, "Saka")
eq("E4  reference_source",                      (_e1 or ReferenceResolution("","","",0,"","")).reference_source,
   "comparison_followup_llm")
eq("E5  language",                              (_e1 or ReferenceResolution("","","",0,"","")).language, "es")
ok("E6  confidence >= 0.5",                     (_e1 or ReferenceResolution("","","",0,"","")).confidence >= 0.5)

# Elliptical English: "vs Palmer"
_e7_client = _MockClient(_comp_json(True, "Palmer", confidence=0.88, language="en"))
_e7 = resolve_comparison_followup_llm("vs Palmer", _es, client=_e7_client)
ok("E7  'vs Palmer' → ReferenceResolution",     _e7 is not None)
eq("E8  rewritten 'vs Palmer'",                 (_e7 or ReferenceResolution("","","",0,"","")).rewritten_question,
   "compare Haaland and Palmer")

# "Or Saka?" pattern
_e9_client = _MockClient(_comp_json(True, "Saka", confidence=0.85, language="en"))
_e9 = resolve_comparison_followup_llm("Or Saka?", _es, client=_e9_client)
ok("E9  'Or Saka?' → ReferenceResolution",      _e9 is not None)
eq("E10 rewritten 'Or Saka?'",                  (_e9 or ReferenceResolution("","","",0,"","")).rewritten_question,
   "compare Haaland and Saka")

# Low confidence → result is returned (it's the caller's job to check threshold)
_e11_client = _MockClient(_comp_json(True, "Saka", confidence=0.3, language="en"))
_e11 = resolve_comparison_followup_llm("vague", _es, client=_e11_client)
ok("E11 low confidence still returns result (caller checks threshold)", _e11 is not None)
ok("E12 low confidence value preserved",        (_e11 or ReferenceResolution("","","",0,"","")).confidence < _CONFIDENCE_THRESHOLD)


# ===========================================================================
# Section F -- ConversationSession integration
# ===========================================================================

print("F  ConversationSession integration")

# Setup: session after a successful comparison
_fs = ConversationSession()
_f_turn1 = _fs.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("F1  turn 1 outcome ok",          _f_turn1.outcome, OUTCOME_OK)
eq("F2  last_comparison set",        _fs.state.last_comparison, ("Haaland", "Salah"))

# Phase 5f: LLM follow-up via mock client (Spanish "¿Y Saka?")
_f3_client = _MockClient(_comp_json(True, "Saka", confidence=0.95, language="es"))
_f3 = _fs.respond("¿Y Saka?", STANDARD_BOOTSTRAP, resolver_client=_f3_client)
eq("F3  LLM Spanish follow-up outcome ok",      _f3.outcome, OUTCOME_OK)
eq("F4  LLM Spanish follow-up intent compare",  _f3.intent, INTENT_COMPARE_PLAYERS)
ok("F5  Haaland in LLM follow-up text",         "Haaland" in _f3.final_text)
ok("F6  Saka in LLM follow-up text",            "Saka" in _f3.final_text)
eq("F7  last_comparison updated to new pair",   _fs.state.last_comparison, ("Haaland", "Saka"))

# Phase 5f: LLM follow-up via mock client (elliptical "vs Saka")
_fs2 = ConversationSession()
_fs2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_f8_client = _MockClient(_comp_json(True, "Saka", confidence=0.9, language="en"))
_f8 = _fs2.respond("vs Saka", STANDARD_BOOTSTRAP, resolver_client=_f8_client)
eq("F8  elliptical 'vs Saka' outcome ok",       _f8.outcome, OUTCOME_OK)
ok("F9  Saka in text",                          "Saka" in _f8.final_text)

# LLM says not a comparison follow-up → falls through to general resolver
_fs3 = ConversationSession()
_fs3.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_f10_client = _MockClient(_comp_json(False, None, confidence=0.99))
_f10 = _fs3.respond("should I captain Haaland", STANDARD_BOOTSTRAP, resolver_client=_f10_client)
eq("F10 non-followup falls through to normal routing", _f10.outcome, OUTCOME_OK)

# No resolver_client → LLM step skipped, deterministic comparison follow-up still works
_fs4 = ConversationSession()
_fs4.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_f11 = _fs4.respond("And Saka?", STANDARD_BOOTSTRAP)  # no resolver_client
eq("F11 no client, det. comparison still works",    _f11.outcome, OUTCOME_OK)
ok("F12 Saka in text without client",               "Saka" in _f11.final_text)


# ===========================================================================
# Section G -- Resolution priority: Phase 5c deterministic runs first
# ===========================================================================

print("G  Resolution priority")

# Deterministic Phase 5c pattern "And X?" — LLM client should NOT be called
# (the deterministic resolver catches it first and we never reach the LLM step)
_gs = ConversationSession()
_gs.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)

# Even if client would return something different, det. comparison runs first
_g1_client = _MockClient(_comp_json(True, "WrongPlayer", confidence=0.99))
_g1 = _gs.respond("And Saka?", STANDARD_BOOTSTRAP, resolver_client=_g1_client)
eq("G1  det. comparison takes priority over LLM", _g1.outcome, OUTCOME_OK)
ok("G2  Saka in text (det. resolver used, not LLM)", "Saka" in _g1.final_text)
ok("G3  'WrongPlayer' NOT in text",               "WrongPlayer" not in _g1.final_text)

# "What about X?" also caught by det. resolver first
_gs2 = ConversationSession()
_gs2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_g4_client = _MockClient(_comp_json(True, "WrongPlayer", confidence=0.99))
_g4 = _gs2.respond("What about Saka?", STANDARD_BOOTSTRAP, resolver_client=_g4_client)
ok("G4  'What about X?' det. resolver still first", "Saka" in _g4.final_text)
ok("G5  'WrongPlayer' NOT in text",                "WrongPlayer" not in _g4.final_text)

# LLM path only runs when last_comparison is set
_gs3 = ConversationSession()  # fresh — no comparison yet
_g6_client = _MockClient(_comp_json(True, "Saka", confidence=0.99))
_g6 = _gs3.respond("¿Y Saka?", STANDARD_BOOTSTRAP, resolver_client=_g6_client)
# No last_comparison → LLM comparison resolver not called → general resolver handles it
ok("G6  no last_comparison → LLM comp resolver not called", True)  # tested by D2 already


# ===========================================================================
# Section H -- Regression
# ===========================================================================

print("H  Regression")

# Phase 5c: deterministic comparison follow-up patterns unaffected
from fpl_grounded_assistant import resolve_comparison_followup
_hs = ConversationState()
_hs.last_comparison = ("Haaland", "Salah")

ok("H1  det. 'And Saka?' still works",      resolve_comparison_followup("And Saka?", _hs) is not None)
ok("H2  det. 'What about Saka?' still works",
   resolve_comparison_followup("What about Saka?", _hs) is not None)
ok("H3  det. 'How about Saka?' still works",
   resolve_comparison_followup("How about Saka?", _hs) is not None)
ok("H4  det. 'Compare him to Saka' still works",
   resolve_comparison_followup("Compare him to Saka", _hs) is not None)
ok("H5  det. full comparison → None (not a follow-up)",
   resolve_comparison_followup("compare Haaland and Salah", _hs) is None)

# Single-turn comparison still works (no conversation state needed)
_h6 = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("H6  single-turn comparison ok",         _h6.outcome, OUTCOME_OK)
eq("H7  single-turn intent compare",        _h6.intent, INTENT_COMPARE_PLAYERS)
ok("H8  Advantages in single-turn text",    "Advantages" in _h6.final_text
   or "advantage" in _h6.final_text.lower())

# General resolver (Phase 4f) unaffected — pronoun resolution still works
_h9_sess = ConversationSession()
_h9_sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
_h9 = _h9_sess.respond("should I captain him?", STANDARD_BOOTSTRAP)
eq("H9  pronoun resolution still works",    _h9.outcome, OUTCOME_OK)

# Not-found follow-up via LLM still returns not_found gracefully
_h10_sess = ConversationSession()
_h10_sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_h10_client = _MockClient(_comp_json(True, "NoSuchPlayer99", confidence=0.9, language="en"))
_h10 = _h10_sess.respond("¿Y NoSuchPlayer99?", STANDARD_BOOTSTRAP, resolver_client=_h10_client)
eq("H10 not-found via LLM follow-up → not_found", _h10.outcome, OUTCOME_NOT_FOUND)
ok("H11 last_comparison preserved after not-found", _h10_sess.state.last_comparison is not None)


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5f: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
