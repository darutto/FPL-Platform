"""
run_phase_orch4c_tests.py
==========================
Phase Orch-4c test runner: orch_outcome field surface + regression.

Validates:
  A  orch_outcome field surface (exists, default, accepts arbitrary strings)
  B  orch OFF -> orch_outcome is None for all intent/outcome classes
  I  sub-call depth > 0 bypasses orch gate -> orch_outcome is None
  K  regression (Orch-4b, 4a, 3b, 3a, 2a, phase-9)

Retired (2026-07-12): sections C, D, E, F, G, H, J — all of Orch-4c's original
"non-OK orchestration outcome policy" and CLI/HTTP/session serialization
coverage, plus the re-exported-constant checks in the old section A. Every
retired assertion patched `final_response.ask_orchestrated` (or asserted the
6 non-OK ORCH_OUTCOME_* constants were re-exported from final_response) to
exercise the orchestration gate inside respond() that called it when
FPL_ORCH_ENABLED was set. Commit 118d43e ("G2.a delete rollout-isolation
surface", 2026-05-18) deleted that gate entirely — respond() is
deterministic-only now, ask_orchestrated() doesn't exist, and
final_response.py only re-exports ORCH_OUTCOME_OK — so the whole "non-OK
outcome policy" this phase was built to validate is no longer a reachable
code path. What remains (A1-A5, B, I, K) tests genuinely live behavior:
the orch_outcome field's shape and its always-None invariant now that no
gate ever sets it to anything else.
"""
from __future__ import annotations

import os
import sys
from dataclasses import fields

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

# Ensure flag is OFF before imports
os.environ.pop("FPL_ORCH_ENABLED", None)
os.environ.pop("FPL_ORCH_PROVIDER", None)

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def ok(cond: bool, label: str, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"  [{detail}]"
        print(msg)


# ---------------------------------------------------------------------------
# Imports from package
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.final_response import (
    FinalResponse,
    respond,
)
from fpl_grounded_assistant.dispatcher import (
    OUTCOME_OK as DISP_OUTCOME_OK,
    INTENT_CAPTAIN_SCORE,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# Helpers — env flag toggle
# ---------------------------------------------------------------------------

def _set_flag(val: str | None) -> None:
    if val is None:
        os.environ.pop("FPL_ORCH_ENABLED", None)
    else:
        os.environ["FPL_ORCH_ENABLED"] = val


_QUESTION = "should I captain Haaland"
_BS = STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# Section A: orch_outcome field surface
# ---------------------------------------------------------------------------

print("\n=== A: orch_outcome field surface ===")

_fr_field_names = {f.name for f in fields(FinalResponse)}
ok("orch_outcome" in _fr_field_names,       "A1: FinalResponse has orch_outcome field")

_fr_default = FinalResponse(
    final_text="x", outcome="ok", supported=True, intent="captain_score",
    review_passed=True, llm_used=False, debug=None,
)
ok(_fr_default.orch_outcome is None,        "A2: orch_outcome defaults to None")
ok(isinstance(_fr_default.orch_outcome, type(None)),
   "A3: orch_outcome type is None by default")

_fr_explicit = FinalResponse(
    final_text="x", outcome="ok", supported=True, intent="captain_score",
    review_passed=True, llm_used=False, debug=None, orch_outcome="ok",
)
ok(_fr_explicit.orch_outcome == "ok",       "A4: orch_outcome accepts 'ok' string")

_fr_nonok = FinalResponse(
    final_text="x", outcome="ok", supported=True, intent="captain_score",
    review_passed=True, llm_used=False, debug=None, orch_outcome="llm_error",
)
ok(_fr_nonok.orch_outcome == "llm_error",   "A5: orch_outcome accepts non-OK string")


# ---------------------------------------------------------------------------
# Section B: orch OFF -> orch_outcome is None
# ---------------------------------------------------------------------------

print("\n=== B: orch OFF -> orch_outcome is None ===")

_set_flag(None)

_r_b1 = respond(_QUESTION, _BS)
ok(_r_b1.orch_outcome is None,              "B1: captain_score, orch OFF -> None")

_r_b2 = respond("Haaland vs Salah", _BS)
ok(_r_b2.orch_outcome is None,              "B2: compare_players, orch OFF -> None")

_r_b3 = respond("who will win the league", _BS)
ok(_r_b3.orch_outcome is None,              "B3: unsupported, orch OFF -> None")

_r_b4 = respond("should I bench boost", _BS)
ok(_r_b4.orch_outcome is None,              "B4: chip_advice, orch OFF -> None")


# ---------------------------------------------------------------------------
# Section I: Sub-call depth > 0 bypasses orch gate — orch_outcome is None
# ---------------------------------------------------------------------------

print("\n=== I: depth-1 (sub-call) bypasses orch gate ===")

# There is no orch gate to bypass anymore (respond() is deterministic-only),
# so orch_outcome is None here unconditionally — this still guards against
# a future re-introduction of gate logic that forgets the depth check.
_set_flag("1")
_r_i1 = respond(_QUESTION, _BS, _multi_intent_depth=1)
_set_flag(None)
ok(_r_i1.orch_outcome is None,             "I1: depth-1 call bypasses orch gate -> None")
ok(_r_i1.intent == INTENT_CAPTAIN_SCORE,   "I2: depth-1 intent from deterministic path")


# ---------------------------------------------------------------------------
# Section K: regression — Orch-4b (run inline for pass count)
# ---------------------------------------------------------------------------

print("\n=== K: regression check (Orch-4b key invariants) ===")

_set_flag(None)
_r_k1 = respond(_QUESTION, _BS)
ok(_r_k1.intent == "captain_score",        "K1: deterministic captain_score intent")
ok(_r_k1.outcome == DISP_OUTCOME_OK,       "K2: deterministic ok outcome")
ok(_r_k1.captain is not None,             "K3: captain metadata populated deterministically")
ok(_r_k1.orch_outcome is None,            "K4: orch_outcome None in deterministic path")

_r_k2 = respond("Haaland vs Salah", _BS)
ok(_r_k2.intent == "compare_players",      "K5: compare_players deterministic")
ok(_r_k2.comparison is not None,          "K6: comparison populated deterministically")
ok(_r_k2.orch_outcome is None,            "K7: orch_outcome None for compare_players")

_r_k3 = respond("should I bench boost", _BS)
ok(_r_k3.intent == "chip_advice",          "K8: chip_advice deterministic")
ok(_r_k3.chip is not None,                "K9: chip populated deterministically")
ok(_r_k3.orch_outcome is None,            "K10: orch_outcome None for chip_advice")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print()
print("=" * 50)
total = _PASS + _FAIL
print(f"Phase Orch-4c: {_PASS}/{total} assertions passed.")
if _FAIL == 0:
    print("               All assertions passed.")
else:
    print(f"               {_FAIL} FAILED.")
