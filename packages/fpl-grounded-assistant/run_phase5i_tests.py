"""
run_phase5i_tests.py
====================
Phase 5i: Structured Comparison Player Context

Tests that verify:
  A. Module shape -- ComparisonPlayerContext importable, fields correct
  B. ComparisonPlayerContext populated for direct comparison
  C. Parity -- deterministic follow-up produces identical player context
  D. Parity -- LLM-assisted follow-up (mock client) produces identical player context
  E. Non-comparison turns still return comparison=None
  F. Non-OK comparison turns do not expose player context
  G. HTTP /ask serializes player_a/b in comparison dict
  H. HTTP session /ask serializes player_a/b in comparison dict
  I. Regression -- existing winner/margin/label/reasons fields unchanged
  J. Regression -- prior phase behaviour unchanged

Run::

    cd packages/fpl-grounded-assistant
    python run_phase5i_tests.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import fields as dc_fields

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

import traceback

_passed = 0
_failed = 0


def ok(label: str, expr: bool, detail: str = "") -> None:
    global _passed, _failed
    if expr:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


# ===========================================================================
# Section A -- Module shape
# ===========================================================================
print("\n--- A: Module shape ---")

try:
    from fpl_grounded_assistant import ComparisonPlayerContext
    ok("A1  ComparisonPlayerContext importable from package", True)
except ImportError as exc:
    ok("A1  ComparisonPlayerContext importable from package", False, str(exc))

try:
    from fpl_grounded_assistant import ComparisonPlayerContext as CPC
    field_names = {f.name for f in dc_fields(CPC)}
    ok("A2  ComparisonPlayerContext has 'web_name'",
       "web_name" in field_names, str(field_names))
    ok("A3  ComparisonPlayerContext has 'position'",
       "position" in field_names, str(field_names))
    ok("A4  ComparisonPlayerContext has 'captain_score'",
       "captain_score" in field_names, str(field_names))
    ok("A5  ComparisonPlayerContext has 'role_bonus'",
       "role_bonus" in field_names, str(field_names))
    ok("A6  ComparisonPlayerContext has 'set_piece_notes'",
       "set_piece_notes" in field_names, str(field_names))
    ok("A7  ComparisonPlayerContext has exactly 5 fields",
       len(field_names) == 5, str(field_names))
except Exception as exc:
    ok("A2-A7  ComparisonPlayerContext field checks", False, str(exc))

try:
    from fpl_grounded_assistant import ComparisonMeta
    cmp_field_names = {f.name for f in dc_fields(ComparisonMeta)}
    ok("A8  ComparisonMeta has 'player_a' field",
       "player_a" in cmp_field_names, str(cmp_field_names))
    ok("A9  ComparisonMeta has 'player_b' field",
       "player_b" in cmp_field_names, str(cmp_field_names))
    ok("A10 ComparisonMeta still has 'winner', 'margin', 'label', 'reasons'",
       {"winner", "margin", "label", "reasons"} <= cmp_field_names,
       str(cmp_field_names))
except Exception as exc:
    ok("A8-A10 ComparisonMeta field checks", False, str(exc))

# A11: ComparisonPlayerContext is frozen (immutable)
try:
    ctx = ComparisonPlayerContext(
        web_name="Test", position="MID",
        captain_score=10.0, role_bonus=5.0,
        set_piece_notes=("penalty_taker_1",),
    )
    try:
        ctx.web_name = "Changed"  # type: ignore[misc]
        ok("A11 ComparisonPlayerContext is frozen", False, "mutation succeeded unexpectedly")
    except (AttributeError, TypeError):
        ok("A11 ComparisonPlayerContext is frozen", True)
except Exception as exc:
    ok("A11 ComparisonPlayerContext is frozen", False, str(exc))

# A12: backward-compatible ComparisonMeta construction (no player_a/b)
try:
    old_meta = ComparisonMeta(winner="A", margin=3.0, label="moderate", reasons=("form",))
    ok("A12 ComparisonMeta constructable without player_a/b (backward compat)",
       old_meta.player_a is None and old_meta.player_b is None)
except Exception as exc:
    ok("A12 ComparisonMeta backward compat construction", False, str(exc))


# ===========================================================================
# Section B -- Direct comparison populates player_a / player_b
# ===========================================================================
print("\n--- B: Direct comparison player context ---")

from fpl_grounded_assistant import respond, STANDARD_BOOTSTRAP  # noqa: E402

fr_b = respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)

ok("B1  direct comparison outcome ok",
   fr_b.outcome == "ok", repr(fr_b.outcome))
ok("B2  comparison not None",
   fr_b.comparison is not None)

if fr_b.comparison is not None:
    pa = fr_b.comparison.player_a
    pb = fr_b.comparison.player_b

    ok("B3  player_a is ComparisonPlayerContext",
       isinstance(pa, ComparisonPlayerContext),
       str(type(pa)))
    ok("B4  player_b is ComparisonPlayerContext",
       isinstance(pb, ComparisonPlayerContext),
       str(type(pb)))

    if pa is not None:
        ok("B5  player_a.web_name non-empty str",
           isinstance(pa.web_name, str) and len(pa.web_name) > 0,
           repr(pa.web_name))
        ok("B6  player_a.position is 'FWD' (Haaland)",
           pa.position == "FWD",
           repr(pa.position))
        ok("B7  player_a.captain_score > 0",
           pa.captain_score > 0,
           repr(pa.captain_score))
        ok("B8  player_a.role_bonus == 5.0 (pen taker)",
           pa.role_bonus == 5.0,
           repr(pa.role_bonus))
        ok("B9  player_a.set_piece_notes == ('penalty_taker_1',)",
           pa.set_piece_notes == ("penalty_taker_1",),
           repr(pa.set_piece_notes))
        ok("B10 player_a.set_piece_notes is tuple",
           isinstance(pa.set_piece_notes, tuple))

    if pb is not None:
        ok("B11 player_b.web_name == 'Saka'",
           pb.web_name == "Saka",
           repr(pb.web_name))
        ok("B12 player_b.position is 'MID' (Saka)",
           pb.position == "MID",
           repr(pb.position))
        ok("B13 player_b.role_bonus == 0.5 (fk2 taker)",
           pb.role_bonus == 0.5,
           repr(pb.role_bonus))
        ok("B14 player_b.set_piece_notes == ('freekick_taker_2',)",
           pb.set_piece_notes == ("freekick_taker_2",),
           repr(pb.set_piece_notes))

    # B15: player_a.captain_score matches comparison-level data
    if pa is not None and pb is not None:
        raw_result_b = fr_b.comparison
        ok("B15 player_a.web_name consistent with winner/loser",
           pa.web_name in (raw_result_b.winner, pb.web_name) or raw_result_b.winner is None)


# ===========================================================================
# Section C -- Deterministic follow-up parity
# ===========================================================================
print("\n--- C: Deterministic follow-up parity ---")

from fpl_grounded_assistant import ConversationSession  # noqa: E402

session_c = ConversationSession()
_c1 = session_c.respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)
_c2 = session_c.respond("And Salah?", STANDARD_BOOTSTRAP)

ok("C1  follow-up outcome ok",
   _c2.outcome == "ok", repr(_c2.outcome))
ok("C2  follow-up comparison not None",
   _c2.comparison is not None)

if _c2.comparison is not None:
    ok("C3  follow-up player_a is ComparisonPlayerContext",
       isinstance(_c2.comparison.player_a, ComparisonPlayerContext),
       str(type(_c2.comparison.player_a)))
    ok("C4  follow-up player_b is ComparisonPlayerContext",
       isinstance(_c2.comparison.player_b, ComparisonPlayerContext),
       str(type(_c2.comparison.player_b)))

# Compare with direct call for same pair (Haaland vs Salah)
fr_direct_hs = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
if _c2.comparison is not None and fr_direct_hs.comparison is not None:
    ok("C5  follow-up player_a matches direct player_a web_name",
       _c2.comparison.player_a.web_name == fr_direct_hs.comparison.player_a.web_name
       if _c2.comparison.player_a and fr_direct_hs.comparison.player_a else True,
       f"follow-up={_c2.comparison.player_a.web_name!r} "
       f"direct={fr_direct_hs.comparison.player_a.web_name!r}")
    ok("C6  follow-up player_a.position matches direct",
       _c2.comparison.player_a.position == fr_direct_hs.comparison.player_a.position
       if _c2.comparison.player_a and fr_direct_hs.comparison.player_a else True)
    ok("C7  follow-up player_a.role_bonus matches direct",
       _c2.comparison.player_a.role_bonus == fr_direct_hs.comparison.player_a.role_bonus
       if _c2.comparison.player_a and fr_direct_hs.comparison.player_a else True)
    ok("C8  follow-up player_a.set_piece_notes matches direct",
       _c2.comparison.player_a.set_piece_notes == fr_direct_hs.comparison.player_a.set_piece_notes
       if _c2.comparison.player_a and fr_direct_hs.comparison.player_a else True)
    ok("C9  follow-up player_b matches direct player_b web_name",
       _c2.comparison.player_b.web_name == fr_direct_hs.comparison.player_b.web_name
       if _c2.comparison.player_b and fr_direct_hs.comparison.player_b else True,
       f"follow-up={_c2.comparison.player_b.web_name!r} "
       f"direct={fr_direct_hs.comparison.player_b.web_name!r}")


# ===========================================================================
# Section D -- LLM-assisted follow-up parity (mock client)
# ===========================================================================
print("\n--- D: LLM-assisted follow-up parity (mock) ---")

from fpl_grounded_assistant import (  # noqa: E402
    ConversationSession,
    STANDARD_BOOTSTRAP,
    _CONFIDENCE_THRESHOLD,
)


class _MockContent:
    def __init__(self, text: str):
        self.text = text


class _MockMessages:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def create(self, **_kwargs: object) -> object:
        class _Msg:
            content = [_MockContent(self._response_text)]
        return _Msg()


class _MockClient:
    def __init__(self, response_text: str):
        self.messages = _MockMessages(response_text)


_COMP_LLM_RESPONSE = json.dumps({
    "is_comparison_followup": True,
    "new_player": "Salah",
    "confidence": 0.97,
    "language": "es",
})

session_d = ConversationSession()
session_d._resolver_client = _MockClient(_COMP_LLM_RESPONSE)  # type: ignore[attr-defined]

# Seed comparison state then ask Spanish follow-up
_d1 = session_d.respond("compare Haaland and Saka", STANDARD_BOOTSTRAP,
                         resolver_client=_MockClient(_COMP_LLM_RESPONSE))
_d2 = session_d.respond("Y Salah?", STANDARD_BOOTSTRAP,
                         resolver_client=_MockClient(_COMP_LLM_RESPONSE))

ok("D1  LLM follow-up outcome ok",
   _d2.outcome == "ok", repr(_d2.outcome))
ok("D2  LLM follow-up comparison not None",
   _d2.comparison is not None)

if _d2.comparison is not None:
    ok("D3  LLM follow-up player_a is ComparisonPlayerContext",
       isinstance(_d2.comparison.player_a, ComparisonPlayerContext),
       str(type(_d2.comparison.player_a)))
    ok("D4  LLM follow-up player_b is ComparisonPlayerContext",
       isinstance(_d2.comparison.player_b, ComparisonPlayerContext),
       str(type(_d2.comparison.player_b)))

# Parity with direct call for same pair
fr_direct_d = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
if _d2.comparison is not None and fr_direct_d.comparison is not None:
    ok("D5  LLM follow-up player_a.position matches direct",
       _d2.comparison.player_a.position == fr_direct_d.comparison.player_a.position
       if _d2.comparison.player_a and fr_direct_d.comparison.player_a else True,
       f"{_d2.comparison.player_a.position!r} vs {fr_direct_d.comparison.player_a.position!r}")
    ok("D6  LLM follow-up player_a.role_bonus matches direct",
       _d2.comparison.player_a.role_bonus == fr_direct_d.comparison.player_a.role_bonus
       if _d2.comparison.player_a and fr_direct_d.comparison.player_a else True)
    ok("D7  LLM follow-up player_b.set_piece_notes matches direct",
       _d2.comparison.player_b.set_piece_notes == fr_direct_d.comparison.player_b.set_piece_notes
       if _d2.comparison.player_b and fr_direct_d.comparison.player_b else True,
       f"{_d2.comparison.player_b.set_piece_notes!r} vs {fr_direct_d.comparison.player_b.set_piece_notes!r}")


# ===========================================================================
# Section E -- Non-comparison turns still return comparison=None
# ===========================================================================
print("\n--- E: Non-comparison turns have no comparison ---")

fr_e1 = respond("should I captain Haaland?", STANDARD_BOOTSTRAP)
ok("E1  captain_score intent -- comparison is None",
   fr_e1.comparison is None, repr(fr_e1.comparison))

fr_e2 = respond("who is Salah?", STANDARD_BOOTSTRAP)
ok("E2  player_resolve intent -- comparison is None",
   fr_e2.comparison is None, repr(fr_e2.comparison))

fr_e3 = respond("what gameweek is it?", STANDARD_BOOTSTRAP)
ok("E3  current_gameweek intent -- comparison is None",
   fr_e3.comparison is None, repr(fr_e3.comparison))

fr_e4 = respond("is Haaland healthy?", STANDARD_BOOTSTRAP)
ok("E4  unsupported_intent -- comparison is None",
   fr_e4.comparison is None, repr(fr_e4.comparison))


# ===========================================================================
# Section F -- Non-OK comparison turns do not expose player context
# ===========================================================================
print("\n--- F: Non-OK comparison has no player context ---")

fr_f1 = respond("compare Haaland and NotARealPlayer999", STANDARD_BOOTSTRAP)
ok("F1  not_found comparison -- comparison is None",
   fr_f1.comparison is None, repr(fr_f1.comparison))

# F2: confirm final_text still non-empty for not_found
ok("F2  not_found final_text non-empty",
   len(fr_f1.final_text) > 0)


# ===========================================================================
# Section G -- HTTP /ask serializes player_a/b in comparison dict
# ===========================================================================
print("\n--- G: HTTP /ask serialization ---")

try:
    from fastapi.testclient import TestClient
    import fpl_server

    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._clear_sessions()
    http = TestClient(fpl_server.app)

    resp_g = http.post("/ask", json={"question": "compare Haaland and Saka"})
    ok("G1  /ask status 200",
       resp_g.status_code == 200, str(resp_g.status_code))

    body_g = resp_g.json()
    comp_g = body_g.get("comparison", {})

    ok("G2  comparison present in /ask body",
       "comparison" in body_g, str(list(body_g.keys())))
    ok("G3  player_a key in comparison",
       "player_a" in comp_g, str(list(comp_g.keys())))
    ok("G4  player_b key in comparison",
       "player_b" in comp_g, str(list(comp_g.keys())))

    pa_g = comp_g.get("player_a", {})
    pb_g = comp_g.get("player_b", {})

    ok("G5  player_a is dict",
       isinstance(pa_g, dict), str(type(pa_g)))
    ok("G6  player_a has web_name",
       "web_name" in pa_g, str(list(pa_g.keys())))
    ok("G7  player_a has position",
       "position" in pa_g, str(list(pa_g.keys())))
    ok("G8  player_a has captain_score",
       "captain_score" in pa_g, str(list(pa_g.keys())))
    ok("G9  player_a has role_bonus",
       "role_bonus" in pa_g, str(list(pa_g.keys())))
    ok("G10 player_a has set_piece_notes",
       "set_piece_notes" in pa_g, str(list(pa_g.keys())))
    ok("G11 player_a.set_piece_notes is list",
       isinstance(pa_g.get("set_piece_notes"), list),
       str(type(pa_g.get("set_piece_notes"))))
    ok("G12 player_b is dict",
       isinstance(pb_g, dict), str(type(pb_g)))
    ok("G13 player_b has position",
       "position" in pb_g, str(list(pb_g.keys())))

    # G14: existing top-level comparison fields still present
    for key in ("winner", "margin", "label", "reasons"):
        ok(f"G14 /ask comparison still has '{key}'",
           key in comp_g, str(list(comp_g.keys())))

    # G15: non-comparison /ask has no comparison player_a/b
    resp_g2 = http.post("/ask", json={"question": "should I captain Haaland?"})
    body_g2 = resp_g2.json()
    ok("G15 captain_score /ask has comparison=None",
       body_g2.get("comparison") is None,
       str(body_g2.get("comparison")))

    fpl_server._clear_sessions()
except Exception as exc:
    ok("G1-G15 HTTP /ask tests", False, traceback.format_exc())


# ===========================================================================
# Section H -- HTTP session /ask serializes player_a/b
# ===========================================================================
print("\n--- H: HTTP session /ask serialization ---")

try:
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._clear_sessions()
    http2 = TestClient(fpl_server.app)

    sess_resp = http2.post("/session")
    ok("H1  POST /session 200",
       sess_resp.status_code == 200, str(sess_resp.status_code))
    sid = sess_resp.json()["session_id"]

    turn_h = http2.post(f"/session/{sid}/ask",
                        json={"question": "compare Haaland and Saka"})
    ok("H2  session turn 200",
       turn_h.status_code == 200, str(turn_h.status_code))

    body_h = turn_h.json()
    comp_h = body_h.get("comparison", {})

    ok("H3  session comparison present",
       "comparison" in body_h, str(list(body_h.keys())))
    ok("H4  session player_a present",
       "player_a" in comp_h, str(list(comp_h.keys())))
    ok("H5  session player_b present",
       "player_b" in comp_h, str(list(comp_h.keys())))

    pa_h = comp_h.get("player_a", {})
    ok("H6  session player_a.position is 'FWD'",
       pa_h.get("position") == "FWD",
       repr(pa_h.get("position")))
    ok("H7  session player_a.set_piece_notes is list",
       isinstance(pa_h.get("set_piece_notes"), list),
       str(type(pa_h.get("set_piece_notes"))))

    # H8: follow-up turn also has player context
    turn_h2 = http2.post(f"/session/{sid}/ask",
                          json={"question": "And Salah?"})
    ok("H8  follow-up session turn 200",
       turn_h2.status_code == 200, str(turn_h2.status_code))
    body_h2 = turn_h2.json()
    comp_h2 = body_h2.get("comparison", {})
    ok("H9  follow-up session comparison present",
       "comparison" in body_h2, str(list(body_h2.keys())))
    ok("H10 follow-up session player_a present",
       "player_a" in comp_h2, str(list(comp_h2.keys())))

    fpl_server._clear_sessions()
except Exception as exc:
    ok("H1-H10 HTTP session tests", False, traceback.format_exc())


# ===========================================================================
# Section I -- Regression: existing winner/margin/label/reasons unchanged
# ===========================================================================
print("\n--- I: Regression ---")

fr_i = respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)
if fr_i.comparison is not None:
    ok("I1  winner is str or None",
       fr_i.comparison.winner is None or isinstance(fr_i.comparison.winner, str))
    ok("I2  margin >= 0",
       fr_i.comparison.margin >= 0, repr(fr_i.comparison.margin))
    ok("I3  label in valid set",
       fr_i.comparison.label in ("narrow", "moderate", "clear"),
       repr(fr_i.comparison.label))
    ok("I4  reasons is tuple",
       isinstance(fr_i.comparison.reasons, tuple))
    ok("I5  final_text non-empty",
       len(fr_i.final_text) > 0)

# I6: Phase 5h set-piece phrasing still present
if fr_i.comparison is not None:
    ok("I6  Haaland vs Saka still has set-piece reason",
       any("set-piece" in r for r in fr_i.comparison.reasons),
       str(fr_i.comparison.reasons))

# I7: Phase 5g parity check -- session follow-up comparison equals direct
session_i = ConversationSession()
_i1 = session_i.respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)
_i2 = session_i.respond("And Salah?", STANDARD_BOOTSTRAP)
fr_direct_i = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
if _i2.comparison is not None and fr_direct_i.comparison is not None:
    ok("I7  follow-up reasons match direct (5g parity preserved)",
       _i2.comparison.reasons == fr_direct_i.comparison.reasons,
       f"follow-up={_i2.comparison.reasons!r} direct={fr_direct_i.comparison.reasons!r}")

# I8: respond() still never raises
try:
    _unused = respond("", STANDARD_BOOTSTRAP)
    ok("I8  respond('') does not raise", True)
except Exception as exc:
    ok("I8  respond('') does not raise", False, str(exc))

# I9: comparison data is frozen (immutable)
if fr_i.comparison is not None and fr_i.comparison.player_a is not None:
    try:
        fr_i.comparison.player_a.web_name = "Mutated"  # type: ignore[misc]
        ok("I9  ComparisonPlayerContext is frozen (immutable)", False,
           "mutation succeeded unexpectedly")
    except (AttributeError, TypeError):
        ok("I9  ComparisonPlayerContext is frozen (immutable)", True)


# ===========================================================================
# Section J -- Prior phase regression suites inline
# ===========================================================================
print("\n--- J: Prior phase regression (quick smoke) ---")

# J1: Phase 5h _set_piece_advantage_phrase still works
try:
    from fpl_grounded_assistant import _set_piece_advantage_phrase
    r_j1 = _set_piece_advantage_phrase(
        {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]},
        {"role_bonus": 0.5, "set_piece_notes": ["freekick_taker_2"]},
    )
    ok("J1  Phase 5h _set_piece_advantage_phrase still works",
       r_j1 == "set-piece advantage (pen vs fk2)", repr(r_j1))
except Exception as exc:
    ok("J1  Phase 5h _set_piece_advantage_phrase", False, str(exc))

# J2: Phase 5f COMP_RESOLVER_SYSTEM_PROMPT still present
try:
    from fpl_grounded_assistant import COMP_RESOLVER_SYSTEM_PROMPT
    ok("J2  Phase 5f COMP_RESOLVER_SYSTEM_PROMPT still importable",
       isinstance(COMP_RESOLVER_SYSTEM_PROMPT, str))
except ImportError as exc:
    ok("J2  Phase 5f COMP_RESOLVER_SYSTEM_PROMPT", False, str(exc))

# J3: Phase 5c resolve_comparison_followup still works
try:
    from fpl_grounded_assistant import resolve_comparison_followup, ConversationState
    state_j3 = ConversationState()
    state_j3.last_comparison = ("Haaland", "Saka")
    result_j3 = resolve_comparison_followup("And Salah?", state_j3)
    ok("J3  Phase 5c resolve_comparison_followup still works",
       result_j3 is not None and "Salah" in result_j3,
       repr(result_j3))
except Exception as exc:
    ok("J3  Phase 5c resolve_comparison_followup", False, str(exc))

# J4: Phase 5a compare_players still works
try:
    from fpl_grounded_assistant import compare_players
    r_j4 = compare_players("Haaland", "Saka", STANDARD_BOOTSTRAP)
    ok("J4  Phase 5a compare_players status ok",
       r_j4.get("status") == "ok", repr(r_j4.get("status")))
except Exception as exc:
    ok("J4  Phase 5a compare_players", False, str(exc))


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*50}")
total = _passed + _failed
print(f"Phase 5i: {_passed}/{total} assertions passed", end="")
if _failed:
    print(f"  ({_failed} FAILED)")
    sys.exit(1)
else:
    print()
