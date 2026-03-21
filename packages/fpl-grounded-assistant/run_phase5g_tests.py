"""
run_phase5g_tests.py
====================
Phase 5g: Comparison follow-up explainability parity.

Validates that:
- ComparisonMeta is populated identically for direct comparison and all
  follow-up comparison paths (Phase 5c deterministic, Phase 5f LLM).
- Non-comparison turns and non-OK comparison outcomes have comparison=None.
- HTTP stateless /ask and session /session/{id}/ask serialize comparison.
- No regressions in existing comparison or follow-up behavior.

Run::

    cd packages/fpl-grounded-assistant
    python run_phase5g_tests.py

Sections
--------
A  -- ComparisonMeta shape and structure
B  -- FinalResponse.comparison populated for direct comparison
C  -- FinalResponse.comparison parity: Phase 5c deterministic follow-up
D  -- FinalResponse.comparison parity: Phase 5f LLM follow-up (mock client)
E  -- FinalResponse.comparison is None for non-comparison turns
F  -- FinalResponse.comparison is None for non-OK comparison outcomes
G  -- HTTP stateless /ask surfaces comparison in JSON body
H  -- HTTP session /session/{id}/ask surfaces comparison in JSON body
I  -- Regression: prior comparison behavior unchanged
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import fields

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
    INTENT_CAPTAIN_SCORE,
    ComparisonMeta,
    FinalResponse,
    respond,
    ConversationSession,
)
import fpl_server
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock LLM client for Phase 5f follow-up tests
# ---------------------------------------------------------------------------

class _MockContent:
    def __init__(self, text: str) -> None:
        self.text = text

class _MockMessage:
    def __init__(self, text: str) -> None:
        self.content = [_MockContent(text)]

class _MockMessages:
    def __init__(self, text: str) -> None:
        self._text = text
    def create(self, **kwargs):
        return _MockMessage(self._text)

class _MockClient:
    def __init__(self, text: str) -> None:
        self.messages = _MockMessages(text)


def _comp_json(is_followup: bool, new_player, confidence: float = 0.9, language: str = "en") -> str:
    return json.dumps({
        "is_comparison_followup": is_followup,
        "new_player": new_player,
        "confidence": confidence,
        "language": language,
    })


# ===========================================================================
# Section A -- ComparisonMeta shape
# ===========================================================================

print("A  ComparisonMeta shape")

_field_names = {f.name for f in fields(ComparisonMeta)}
ok("A1  ComparisonMeta has winner field",   "winner"  in _field_names)
ok("A2  ComparisonMeta has margin field",   "margin"  in _field_names)
ok("A3  ComparisonMeta has label field",    "label"   in _field_names)
ok("A4  ComparisonMeta has reasons field",  "reasons" in _field_names)
ok("A5  at least 4 fields (winner/margin/label/reasons; Phase 5i adds player_a/b)",
   len(_field_names) >= 4)

# Frozen
_cm = ComparisonMeta(winner="Salah", margin=5.73, label="moderate", reasons=("stronger form",))
try:
    _cm.winner = "Haaland"  # type: ignore[misc]
    ok("A6  ComparisonMeta is frozen", False)
except Exception:
    ok("A6  ComparisonMeta is frozen", True)

eq("A7  reasons is a tuple",             type(_cm.reasons), tuple)
ok("A8  winner can be None",             ComparisonMeta(winner=None, margin=0.0, label="narrow", reasons=()).winner is None)


# ===========================================================================
# Section B -- FinalResponse.comparison: direct comparison
# ===========================================================================

print("B  FinalResponse.comparison: direct comparison")

_b1 = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
ok("B1  comparison is not None",         _b1.comparison is not None)
ok("B2  comparison is ComparisonMeta",   isinstance(_b1.comparison, ComparisonMeta))
ok("B3  winner is Salah or Haaland",     _b1.comparison.winner in ("Salah", "Haaland"))
ok("B4  margin is positive float",       isinstance(_b1.comparison.margin, float) and _b1.comparison.margin >= 0.0)
ok("B5  label is valid string",          _b1.comparison.label in ("narrow", "moderate", "clear"))
ok("B6  reasons is tuple",               isinstance(_b1.comparison.reasons, tuple))
ok("B7  reasons elements are str",       all(isinstance(r, str) for r in _b1.comparison.reasons))
ok("B8  FinalResponse.comparison.winner set in final_text",
   (_b1.comparison.winner or "") in _b1.final_text)
ok("B9  label appears in final_text",    _b1.comparison.label in _b1.final_text)

# Salah wins the STANDARD_BOOTSTRAP comparison
eq("B10 expected winner is Salah",       _b1.comparison.winner, "Salah")
eq("B11 expected label moderate",        _b1.comparison.label, "moderate")
ok("B12 reasons non-empty",              len(_b1.comparison.reasons) > 0)


# ===========================================================================
# Section C -- Parity: Phase 5c deterministic follow-up
# ===========================================================================

print("C  Parity: Phase 5c deterministic follow-up")

_cs = ConversationSession()
_ct1 = _cs.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_ct2 = _cs.respond("And Saka?", STANDARD_BOOTSTRAP)

ok("C1  follow-up outcome ok",              _ct2.outcome == OUTCOME_OK)
ok("C2  follow-up intent compare_players",  _ct2.intent == INTENT_COMPARE_PLAYERS)
ok("C3  follow-up comparison not None",     _ct2.comparison is not None)
ok("C4  follow-up comparison is CompMeta",  isinstance(_ct2.comparison, ComparisonMeta))
ok("C5  follow-up winner is set",           _ct2.comparison.winner is not None)
ok("C6  follow-up label valid",             _ct2.comparison.label in ("narrow", "moderate", "clear"))
ok("C7  follow-up reasons is tuple",        isinstance(_ct2.comparison.reasons, tuple))
ok("C8  direct and follow-up CompMeta fields same type",
   type(_ct1.comparison) == type(_ct2.comparison))
ok("C9  parity: label field populated in both",
   _ct1.comparison.label is not None and _ct2.comparison.label is not None)
ok("C10 parity: reasons type same",
   isinstance(_ct1.comparison.reasons, tuple) and isinstance(_ct2.comparison.reasons, tuple))

# Direct Haaland vs Salah; follow-up Haaland vs Saka — different winners possibly, same structure
ok("C11 both finals_text mention respective players",
   "Haaland" in _ct2.final_text or "Saka" in _ct2.final_text)
ok("C12 turn 2 final_text has explanation quality (Advantages or clear/moderate/narrow)",
   any(kw in _ct2.final_text for kw in ("Advantages", "advantage", "narrow", "moderate", "clear")))


# ===========================================================================
# Section D -- Parity: Phase 5f LLM follow-up
# ===========================================================================

print("D  Parity: Phase 5f LLM follow-up")

_ds = ConversationSession()
_ds.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)

_d_client = _MockClient(_comp_json(True, "Saka", confidence=0.95, language="es"))
_dt = _ds.respond("¿Y Saka?", STANDARD_BOOTSTRAP, resolver_client=_d_client)

ok("D1  LLM follow-up outcome ok",          _dt.outcome == OUTCOME_OK)
ok("D2  LLM follow-up intent compare",      _dt.intent == INTENT_COMPARE_PLAYERS)
ok("D3  LLM follow-up comparison not None", _dt.comparison is not None)
ok("D4  LLM follow-up comparison CompMeta", isinstance(_dt.comparison, ComparisonMeta))
ok("D5  LLM follow-up winner is set",       _dt.comparison.winner is not None)
ok("D6  LLM follow-up label valid",         _dt.comparison.label in ("narrow", "moderate", "clear"))
ok("D7  LLM follow-up reasons is tuple",    isinstance(_dt.comparison.reasons, tuple))
ok("D8  LLM follow-up Saka in final_text",  "Saka" in _dt.final_text)
ok("D9  LLM follow-up has explanation quality",
   any(kw in _dt.final_text for kw in ("Advantages", "advantage", "narrow", "moderate", "clear")))

# Parity with direct: same structure as direct comparison
ok("D10 parity direct==LLMfollowup structure",
   type(_b1.comparison) == type(_dt.comparison))

# "vs Saka" elliptical English follow-up
_ds2 = ConversationSession()
_ds2.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_d2_client = _MockClient(_comp_json(True, "Saka", confidence=0.9, language="en"))
_dt2 = _ds2.respond("vs Saka", STANDARD_BOOTSTRAP, resolver_client=_d2_client)
ok("D11 vs-Saka follow-up comparison populated", _dt2.comparison is not None)
ok("D12 vs-Saka follow-up Saka in final_text",   "Saka" in _dt2.final_text)


# ===========================================================================
# Section E -- FinalResponse.comparison is None for non-comparison turns
# ===========================================================================

print("E  comparison is None for non-comparison turns")

ok("E1  captain_score → comparison None",
   respond("should I captain Haaland", STANDARD_BOOTSTRAP).comparison is None)
ok("E2  player_summary → comparison None",
   respond("tell me about Salah", STANDARD_BOOTSTRAP).comparison is None)
ok("E3  unsupported → comparison None",
   respond("Is Haaland fit?", STANDARD_BOOTSTRAP).comparison is None)
ok("E4  not_found captain → comparison None",
   respond("should I captain xyznotaplayer999", STANDARD_BOOTSTRAP).comparison is None)


# ===========================================================================
# Section F -- comparison is None for non-OK comparison outcomes
# ===========================================================================

print("F  comparison is None for non-OK comparison outcomes")

_f1 = respond("compare xyznotaplayer999 and Salah", STANDARD_BOOTSTRAP)
eq("F1  not_found comparison outcome",    _f1.outcome, OUTCOME_NOT_FOUND)
ok("F2  not_found comparison → None",     _f1.comparison is None)

_f3 = respond("compare Haaland and xyznotaplayer999", STANDARD_BOOTSTRAP)
eq("F3  not_found player_b outcome",      _f3.outcome, OUTCOME_NOT_FOUND)
ok("F4  not_found player_b → None",       _f3.comparison is None)


# ===========================================================================
# Section G -- HTTP stateless /ask surfaces comparison in JSON
# ===========================================================================

print("G  HTTP stateless /ask surfaces comparison")

fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()
_http_client = TestClient(fpl_server.app, raise_server_exceptions=True)

_g1 = _http_client.post("/ask", json={"question": "compare Haaland and Salah"})
eq("G1  HTTP /ask status 200",            _g1.status_code, 200)
_g1b = _g1.json()
ok("G2  comparison field present in JSON", "comparison" in _g1b)
ok("G3  comparison not None",             _g1b["comparison"] is not None)
_gc = _g1b["comparison"]
ok("G4  JSON comparison has winner key",  "winner" in _gc)
ok("G5  JSON comparison has margin key",  "margin" in _gc)
ok("G6  JSON comparison has label key",   "label" in _gc)
ok("G7  JSON comparison has reasons key", "reasons" in _gc)
ok("G8  JSON comparison.label valid",     _gc["label"] in ("narrow", "moderate", "clear"))
ok("G9  JSON comparison.reasons is list", isinstance(_gc["reasons"], list))
eq("G10 JSON comparison.winner is Salah", _gc["winner"], "Salah")

# Non-comparison request: comparison should be null in JSON
_g11 = _http_client.post("/ask", json={"question": "should I captain Haaland"})
eq("G11 captain HTTP /ask status 200",    _g11.status_code, 200)
ok("G12 captain comparison is null",      _g11.json().get("comparison") is None)


# ===========================================================================
# Section H -- HTTP session /session/{id}/ask surfaces comparison
# ===========================================================================

print("H  HTTP session /session/{id}/ask surfaces comparison")

fpl_server._clear_sessions()

_h_create = _http_client.post("/session")
eq("H1  create session status 200",       _h_create.status_code, 200)
_h_sid = _h_create.json()["session_id"]

# Direct comparison via session
_h2 = _http_client.post(
    f"/session/{_h_sid}/ask",
    json={"question": "compare Haaland and Salah"},
)
eq("H2  session /ask status 200",         _h2.status_code, 200)
_h2b = _h2.json()
ok("H3  session comparison in JSON",      "comparison" in _h2b)
ok("H4  session comparison not None",     _h2b["comparison"] is not None)
_hc = _h2b["comparison"]
eq("H5  session comparison winner",       _hc["winner"], "Salah")
ok("H6  session comparison label valid",  _hc["label"] in ("narrow", "moderate", "clear"))
ok("H7  session comparison reasons list", isinstance(_hc["reasons"], list))

# Follow-up via session: "And Saka?"
_h8 = _http_client.post(
    f"/session/{_h_sid}/ask",
    json={"question": "And Saka?"},
)
eq("H8  session follow-up status 200",    _h8.status_code, 200)
_h8b = _h8.json()
ok("H9  session follow-up comparison populated", _h8b["comparison"] is not None)
_hfc = _h8b["comparison"]
ok("H10 session follow-up label valid",   _hfc["label"] in ("narrow", "moderate", "clear"))
ok("H11 session follow-up reasons list",  isinstance(_hfc["reasons"], list))

# Non-comparison turn via session: comparison should be null
_h12 = _http_client.post(
    f"/session/{_h_sid}/ask",
    json={"question": "should I captain Haaland"},
)
eq("H12 captain via session status 200",  _h12.status_code, 200)
ok("H13 captain via session comparison null", _h12.json().get("comparison") is None)

fpl_server._clear_sessions()


# ===========================================================================
# Section I -- Regression
# ===========================================================================

print("I  Regression")

# final_text unchanged for direct comparison
_i1 = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
ok("I1  Salah in final_text",             "Salah" in _i1.final_text)
ok("I2  Haaland in final_text",           "Haaland" in _i1.final_text)
ok("I3  edges in final_text",             "edges" in _i1.final_text)
ok("I4  margin in final_text",            any(kw in _i1.final_text for kw in ("moderate", "narrow", "clear")))
ok("I5  Advantages in final_text",        "Advantages" in _i1.final_text or "advantage" in _i1.final_text.lower())

# Phase 5c follow-up: "What about X?" still works
_is = ConversationSession()
_is.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_i6 = _is.respond("What about Saka?", STANDARD_BOOTSTRAP)
eq("I6  'What about Saka?' outcome ok",   _i6.outcome, OUTCOME_OK)
ok("I7  'What about Saka?' has comparison", _i6.comparison is not None)
ok("I8  Saka in 'What about Saka?' text", "Saka" in _i6.final_text)

# FinalResponse field count (8 fields after Phase 5g)
_ir_fields = {f.name for f in fields(FinalResponse)}
ok("I9  FinalResponse has comparison field", "comparison" in _ir_fields)
ok("I10 FinalResponse has 8+ fields total",  len(_ir_fields) >= 8)

# Existing non-comparison fields unaffected
eq("I11 final_text type str",             type(_i1.final_text), str)
eq("I12 outcome type str",                type(_i1.outcome), str)
eq("I13 supported type bool",             type(_i1.supported), bool)
ok("I14 review_passed True for det mode", _i1.review_passed is True)
ok("I15 debug None without include_debug", _i1.debug is None)


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5g: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
