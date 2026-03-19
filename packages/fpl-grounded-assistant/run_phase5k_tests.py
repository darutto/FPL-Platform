"""
run_phase5k_tests.py
====================
Phase 5k: Comparison Resolver Source Auditability.

Validates that successful comparison turns can be audited to tell how they
were resolved: direct question, deterministic follow-up rewrite (Phase 5c),
or LLM-assisted follow-up rewrite (Phase 5f).

The audit information is exposed through ``ResolverDebug.resolver_source``
in the debug bundle -- the same structured debug surface already used by
Phase 4g auditability.  The three comparison paths now produce distinct,
non-overlapping ``resolver_source`` values:

    "none"                    -- direct comparison (no resolver ran)
    "comparison_followup"     -- Phase 5c deterministic comparison follow-up
    "comparison_followup_llm" -- Phase 5f LLM comparison follow-up

Default user-facing behavior is unchanged.  Comparison output and
ComparisonMeta remain identical across all three paths.

All tests are deterministic -- no live ANTHROPIC_API_KEY required.
The Phase 5f path is exercised via a lightweight mock client.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5k_tests.py

Sections
--------
A  -- Module shape: ResolverDebug.resolver_source documented values
B  -- Direct comparison: resolver_source == "none", resolver_used == False
C  -- Phase 5c det. follow-up: resolver_source == "comparison_followup"
D  -- Phase 5f LLM follow-up: resolver_source == "comparison_followup_llm"
E  -- Non-comparison session turns: resolver_source values unchanged
F  -- Three paths are mutually distinguishable
G  -- HTTP /session/{id}/ask debug exposes correct resolver_source
H  -- Regression: comparison output, ComparisonMeta, and prior tests unaffected
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
    INTENT_COMPARE_PLAYERS,
    ConversationState,
    ConversationSession,
    ResolverDebug,
    ReferenceResolution,
    _CONFIDENCE_THRESHOLD,
)
from fpl_grounded_assistant.conversation_state import _make_resolver_debug


# ---------------------------------------------------------------------------
# Mock LLM client  (same pattern as run_phase5f_tests.py)
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


def _comp_json(is_followup: bool, new_player, confidence: float = 0.9, language: str = "en") -> str:
    return json.dumps({
        "is_comparison_followup": is_followup,
        "new_player": new_player,
        "confidence": confidence,
        "language": language,
    })


# ---------------------------------------------------------------------------
# Setup for HTTP section
# ---------------------------------------------------------------------------

import fpl_server
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()
from fastapi.testclient import TestClient


# ===========================================================================
# Section A -- Module shape: documented resolver_source values
# ===========================================================================

print("A  Module shape: ResolverDebug resolver_source documentation")

ok("A1  ResolverDebug is importable",             ResolverDebug is not None)
ok("A2  ResolverDebug has resolver_source field",
   hasattr(ResolverDebug(
       resolver_used=False, resolver_source="none",
       resolver_confidence=None, rewritten_question="q", fallback_reason=None,
   ), "resolver_source"))
ok("A3  ResolverDebug has resolver_used field",
   hasattr(ResolverDebug(
       resolver_used=False, resolver_source="none",
       resolver_confidence=None, rewritten_question="q", fallback_reason=None,
   ), "resolver_used"))
ok("A4  _make_resolver_debug is callable",        callable(_make_resolver_debug))
ok("A5  ReferenceResolution has reference_source", hasattr(
    ReferenceResolution(None, None, "none", 0.0, "en", "q"), "reference_source"
))


# ===========================================================================
# Section B -- Direct comparison: resolver_source == "none"
# ===========================================================================

print("B  Direct comparison: resolver_source == \"none\"")

_b_sess = ConversationSession()
_b_r = _b_sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP, include_debug=True)

ok("B1  direct comparison outcome ok",            _b_r.outcome == OUTCOME_OK)
ok("B2  direct comparison is comparison turn",    _b_r.comparison is not None)
ok("B3  debug bundle populated",                  _b_r.debug is not None)
ok("B4  resolver debug present",                  _b_r.debug is not None and _b_r.debug.resolver is not None)

_b_rdbg = _b_r.debug.resolver
eq("B5  resolver_source is none (no rewriting)",  _b_rdbg.resolver_source, "none")
eq("B6  resolver_used is False",                  _b_rdbg.resolver_used, False)
ok("B7  resolver_confidence is None",             _b_rdbg.resolver_confidence is None)
eq("B8  rewritten_question unchanged",            _b_rdbg.rewritten_question, "compare Haaland and Salah")


# ===========================================================================
# Section C -- Phase 5c det. follow-up: resolver_source == "comparison_followup"
# ===========================================================================

print("C  Phase 5c det. follow-up: resolver_source == \"comparison_followup\"")

_c_sess = ConversationSession()
_c_t1 = _c_sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP, include_debug=True)
_c_t2 = _c_sess.respond("And Saka?", STANDARD_BOOTSTRAP, include_debug=True)

eq("C1  turn 1 resolver_source none",             _c_t1.debug.resolver.resolver_source, "none")
ok("C2  turn 2 comparison is not None",           _c_t2.comparison is not None)
ok("C3  turn 2 debug present",                    _c_t2.debug is not None and _c_t2.debug.resolver is not None)

_c_rdbg = _c_t2.debug.resolver
eq("C4  turn 2 resolver_source comparison_followup",
   _c_rdbg.resolver_source, "comparison_followup")
eq("C5  turn 2 resolver_used True",               _c_rdbg.resolver_used, True)
ok("C6  turn 2 resolver_confidence is None",      _c_rdbg.resolver_confidence is None)
eq("C7  turn 2 rewritten_question",               _c_rdbg.rewritten_question, "compare Haaland and Saka")
ok("C8  Saka in final_text",                      "Saka" in _c_t2.final_text)

# "What about X?" is also Phase 5c det.
_c_sess2 = ConversationSession()
_c_sess2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_c_wa = _c_sess2.respond("What about Palmer?", STANDARD_BOOTSTRAP, include_debug=True)
eq("C9  'What about X?' resolver_source comparison_followup",
   _c_wa.debug.resolver.resolver_source, "comparison_followup")
eq("C10 'What about X?' resolver_used True",     _c_wa.debug.resolver.resolver_used, True)


# ===========================================================================
# Section D -- Phase 5f LLM follow-up: resolver_source == "comparison_followup_llm"
# ===========================================================================

print("D  Phase 5f LLM follow-up: resolver_source == \"comparison_followup_llm\"")

_d_sess = ConversationSession()
_d_t1 = _d_sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP, include_debug=True)
eq("D1  turn 1 resolver_source none",             _d_t1.debug.resolver.resolver_source, "none")

_d_mock = _MockClient(_comp_json(True, "Saka", confidence=0.95, language="es"))
_d_t2 = _d_sess.respond(
    "¿Y Saka?", STANDARD_BOOTSTRAP,
    include_debug=True, resolver_client=_d_mock,
)

ok("D2  turn 2 comparison is not None",           _d_t2.comparison is not None)
ok("D3  turn 2 debug present",                    _d_t2.debug is not None and _d_t2.debug.resolver is not None)

_d_rdbg = _d_t2.debug.resolver
eq("D4  turn 2 resolver_source comparison_followup_llm",
   _d_rdbg.resolver_source, "comparison_followup_llm")
eq("D5  turn 2 resolver_used True",               _d_rdbg.resolver_used, True)
ok("D6  turn 2 resolver_confidence is not None",  _d_rdbg.resolver_confidence is not None)
ok("D7  turn 2 resolver_confidence >= threshold", _d_rdbg.resolver_confidence >= _CONFIDENCE_THRESHOLD)
eq("D8  turn 2 rewritten_question",               _d_rdbg.rewritten_question, "compare Haaland and Saka")
ok("D9  Saka in final_text",                      "Saka" in _d_t2.final_text)

# "vs Palmer" LLM pattern
_d_sess3 = ConversationSession()
_d_sess3.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_d_vs = _d_sess3.respond(
    "vs Palmer", STANDARD_BOOTSTRAP,
    include_debug=True,
    resolver_client=_MockClient(_comp_json(True, "Palmer", confidence=0.88, language="en")),
)
eq("D10 'vs Palmer' resolver_source comparison_followup_llm",
   _d_vs.debug.resolver.resolver_source, "comparison_followup_llm")


# ===========================================================================
# Section E -- Non-comparison session turns: resolver_source values unchanged
# ===========================================================================

print("E  Non-comparison turns: resolver_source unaffected")

_e_sess = ConversationSession()
_e_t1 = _e_sess.respond("should I captain Haaland", STANDARD_BOOTSTRAP, include_debug=True)
_e_t2 = _e_sess.respond("should I captain him?", STANDARD_BOOTSTRAP, include_debug=True)

ok("E1  captain turn is NOT comparison",          _e_t1.comparison is None)
ok("E2  turn 1 debug present",                    _e_t1.debug is not None and _e_t1.debug.resolver is not None)
eq("E3  captain direct resolver_source none",     _e_t1.debug.resolver.resolver_source, "none")
eq("E4  pronoun turn resolver_source fallback_regex",
   _e_t2.debug.resolver.resolver_source, "fallback_regex")
eq("E5  pronoun turn resolver_used True",         _e_t2.debug.resolver.resolver_used, True)
ok("E6  pronoun resolver_source is NOT comparison_followup",
   _e_t2.debug.resolver.resolver_source not in ("comparison_followup", "comparison_followup_llm"))


# ===========================================================================
# Section F -- Three paths are mutually distinguishable
# ===========================================================================

print("F  Three paths mutually distinguishable")

_direct_src  = _b_rdbg.resolver_source         # "none"
_det_src     = _c_rdbg.resolver_source         # "comparison_followup"
_llm_src     = _d_rdbg.resolver_source         # "comparison_followup_llm"

eq("F1  direct path source",         _direct_src, "none")
eq("F2  det. follow-up source",      _det_src,    "comparison_followup")
eq("F3  LLM follow-up source",       _llm_src,    "comparison_followup_llm")
ok("F4  direct != det.",             _direct_src  != _det_src)
ok("F5  direct != LLM",              _direct_src  != _llm_src)
ok("F6  det. != LLM",                _det_src     != _llm_src)

# All three paths still produce valid comparison metadata
ok("F7  direct comparison is set",   _b_r.comparison is not None)
ok("F8  det. follow-up comparison",  _c_t2.comparison is not None)
ok("F9  LLM follow-up comparison",   _d_t2.comparison is not None)

# All three produce same ComparisonMeta structure (winner, margin, label, reasons, player_a, player_b)
ok("F10 direct has winner field",    hasattr(_b_r.comparison, "winner"))
ok("F11 det. has winner field",      hasattr(_c_t2.comparison, "winner"))
ok("F12 LLM has winner field",       hasattr(_d_t2.comparison, "winner"))


# ===========================================================================
# Section G -- HTTP /session/{id}/ask debug exposes correct resolver_source
# ===========================================================================

print("G  HTTP session debug exposes correct resolver_source")

fpl_server._clear_sessions()
_g_client = TestClient(fpl_server.app, raise_server_exceptions=True)

# Create session
_g_create = _g_client.post("/session")
eq("G1  create session status", _g_create.status_code, 200)
_g_sid = _g_create.json()["session_id"]

# Direct comparison with debug=True
_g_direct_resp = _g_client.post(
    f"/session/{_g_sid}/ask",
    json={"question": "compare Haaland and Salah", "debug": True},
)
eq("G2  direct comparison HTTP status", _g_direct_resp.status_code, 200)
_g_direct_body = _g_direct_resp.json()
ok("G3  direct has debug key",          "debug" in _g_direct_body)
ok("G4  debug has resolver key",        "resolver" in (_g_direct_body.get("debug") or {}))
_g_direct_resolver = (_g_direct_body.get("debug") or {}).get("resolver", {})
eq("G5  direct HTTP resolver_source none",
   _g_direct_resolver.get("resolver_source"), "none")
eq("G6  direct HTTP resolver_used False",
   _g_direct_resolver.get("resolver_used"), False)
ok("G7  direct HTTP comparison present",
   _g_direct_body.get("comparison") is not None)

# Det. follow-up with debug=True
_g_followup_resp = _g_client.post(
    f"/session/{_g_sid}/ask",
    json={"question": "And Saka?", "debug": True},
)
eq("G8  det. follow-up HTTP status",    _g_followup_resp.status_code, 200)
_g_fu_body = _g_followup_resp.json()
ok("G9  follow-up has debug.resolver",  "resolver" in (_g_fu_body.get("debug") or {}))
_g_fu_resolver = (_g_fu_body.get("debug") or {}).get("resolver", {})
eq("G10 follow-up HTTP resolver_source comparison_followup",
   _g_fu_resolver.get("resolver_source"), "comparison_followup")
eq("G11 follow-up HTTP resolver_used True",
   _g_fu_resolver.get("resolver_used"), True)
ok("G12 follow-up HTTP rewritten_question populated",
   bool(_g_fu_resolver.get("rewritten_question")))

# Clean up
_g_client.delete(f"/session/{_g_sid}")


# ===========================================================================
# Section H -- Regression: comparison output and prior tests unaffected
# ===========================================================================

print("H  Regression: comparison output and prior behavior unaffected")

# Default (non-debug) session turns still work unchanged
_h_sess = ConversationSession()
_h_t1 = _h_sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("H1  non-debug direct outcome ok",      _h_t1.outcome, OUTCOME_OK)
ok("H2  non-debug debug is None",          _h_t1.debug is None)
ok("H3  non-debug comparison is not None", _h_t1.comparison is not None)

_h_t2 = _h_sess.respond("And Saka?", STANDARD_BOOTSTRAP)
eq("H4  non-debug det. follow-up ok",      _h_t2.outcome, OUTCOME_OK)
ok("H5  det. follow-up Saka in text",      "Saka" in _h_t2.final_text)
ok("H6  det. follow-up comparison set",    _h_t2.comparison is not None)

# ComparisonMeta shape unchanged
_h_cm = _h_t2.comparison
ok("H7  ComparisonMeta has winner",        hasattr(_h_cm, "winner"))
ok("H8  ComparisonMeta has margin",        hasattr(_h_cm, "margin"))
ok("H9  ComparisonMeta has label",         hasattr(_h_cm, "label"))
ok("H10 ComparisonMeta has reasons",       hasattr(_h_cm, "reasons"))
ok("H11 ComparisonMeta has player_a",      hasattr(_h_cm, "player_a"))
ok("H12 ComparisonMeta has player_b",      hasattr(_h_cm, "player_b"))

# LLM follow-up via mock: comparison still works without debug
_h_sess2 = ConversationSession()
_h_sess2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_h_llm = _h_sess2.respond(
    "¿Y Saka?", STANDARD_BOOTSTRAP,
    resolver_client=_MockClient(_comp_json(True, "Saka", confidence=0.9, language="es")),
)
eq("H13 LLM follow-up non-debug outcome ok", _h_llm.outcome, OUTCOME_OK)
ok("H14 Saka in LLM follow-up text",         "Saka" in _h_llm.final_text)
ok("H15 LLM follow-up comparison set",       _h_llm.comparison is not None)

# _make_resolver_debug: comparison_followup mapping is independent of prior phase logic
_h_res_det = ReferenceResolution(
    resolved_query=None, intent_guess=None,
    reference_source="comparison_followup", confidence=1.0,
    language="en", rewritten_question="compare A and B", fallback_reason=None,
)
_h_rdbg_det = _make_resolver_debug(_h_res_det, "And B?", "compare A and B")
eq("H16 _make_resolver_debug: comparison_followup",
   _h_rdbg_det.resolver_source, "comparison_followup")
eq("H17 _make_resolver_debug: comparison_followup resolver_used",
   _h_rdbg_det.resolver_used, True)
ok("H18 _make_resolver_debug: comparison_followup confidence None",
   _h_rdbg_det.resolver_confidence is None)

_h_res_llm = ReferenceResolution(
    resolved_query="Saka", intent_guess=None,
    reference_source="comparison_followup_llm", confidence=0.92,
    language="es", rewritten_question="compare A and Saka", fallback_reason=None,
)
_h_rdbg_llm = _make_resolver_debug(_h_res_llm, "¿Y Saka?", "compare A and Saka")
eq("H19 _make_resolver_debug: comparison_followup_llm",
   _h_rdbg_llm.resolver_source, "comparison_followup_llm")
eq("H20 _make_resolver_debug: comparison_followup_llm resolver_used",
   _h_rdbg_llm.resolver_used, True)
ok("H21 _make_resolver_debug: comparison_followup_llm confidence set",
   _h_rdbg_llm.resolver_confidence is not None)

# "deterministic" still maps to "fallback_regex" (no regression)
_h_res_reg = ReferenceResolution(
    resolved_query="Haaland", intent_guess=None,
    reference_source="deterministic", confidence=1.0,
    language="en", rewritten_question="should I captain Haaland", fallback_reason=None,
)
_h_rdbg_reg = _make_resolver_debug(_h_res_reg, "should I captain him", "should I captain Haaland")
eq("H22 _make_resolver_debug: deterministic -> fallback_regex",
   _h_rdbg_reg.resolver_source, "fallback_regex")

# "none" still maps to "none"
_h_res_none = ReferenceResolution(
    resolved_query=None, intent_guess=None,
    reference_source="none", confidence=0.0,
    language="en", rewritten_question="compare Haaland and Salah", fallback_reason=None,
)
_h_rdbg_none = _make_resolver_debug(_h_res_none, "compare Haaland and Salah", "compare Haaland and Salah")
eq("H23 _make_resolver_debug: none -> none",
   _h_rdbg_none.resolver_source, "none")
eq("H24 _make_resolver_debug: none resolver_used False",
   _h_rdbg_none.resolver_used, False)


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5k: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
