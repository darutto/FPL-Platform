"""
run_phase_orch4c_tests.py
==========================
Phase Orch-4c test runner: non-OK orchestration outcome parity.

Validates:
  A  orch_outcome field surface (exists, default, type semantics)
  B  orch OFF -> orch_outcome is None for all intent/outcome classes
  C  orch ON, OUTCOME_OK -> orch_outcome == "ok"
  D  each non-OK orch outcome (6) -> orch_outcome captured, deterministic fallback
  E  fallback invariants (metadata, outcome, final_text parity with orch OFF)
  F  CLI and HTTP surface serialization of orch_outcome
  G  session surface: orch_outcome propagated through session endpoint
  H  regression (Orch-4b, 4a, 3b, 3a, 2a, phase-9)

Non-OK outcome policy (Orch-4c):
  no_client         -> no LLM client; deterministic path runs (LLM skipped)
  llm_error         -> LLM API exception; deterministic path runs (LLM skipped)
  no_tool           -> LLM gave text not tool; deterministic path runs normally
  unknown_tool      -> LLM chose unregistered tool; deterministic runs normally
  tool_error        -> run_tool() raised; deterministic runs normally
  tool_result_error -> tool status != ok; deterministic runs normally
In all cases: final_text=deterministic, outcome=deterministic, metadata=deterministic.
orch_outcome captures the non-OK string for operator audit only.

All assertions are deterministic — no live API calls unless ANTHROPIC_API_KEY is
set AND FPL_ORCH_ENABLED is ON.  Mock objects simulate all orch paths.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import fields
from typing import Any
from unittest.mock import patch

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
    ORCH_OUTCOME_OK,
    ORCH_OUTCOME_NO_CLIENT,
    ORCH_OUTCOME_LLM_ERROR,
    ORCH_OUTCOME_NO_TOOL,
    ORCH_OUTCOME_UNKNOWN_TOOL,
    ORCH_OUTCOME_TOOL_ERROR,
    ORCH_OUTCOME_TOOL_RESULT_ERROR,
)
from fpl_grounded_assistant.orchestrator import (
    OrchestratorResult,
    DEFAULT_ORCH_MODEL,
)
from fpl_grounded_assistant.dispatcher import (
    OUTCOME_OK as DISP_OUTCOME_OK,
    INTENT_CAPTAIN_SCORE,
    INTENT_COMPARE_PLAYERS,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_cli import run as cli_run
from fpl_server import app as server_app
from starlette.testclient import TestClient
import fpl_server


# ---------------------------------------------------------------------------
# Helpers — env flag toggle
# ---------------------------------------------------------------------------

def _set_flag(val: str | None) -> None:
    if val is None:
        os.environ.pop("FPL_ORCH_ENABLED", None)
    else:
        os.environ["FPL_ORCH_ENABLED"] = val


# ---------------------------------------------------------------------------
# Shared reference tool_output for orch-OK mock (captain_score)
# ---------------------------------------------------------------------------

_CAPTAIN_TOOL_OUTPUT = {
    "status":        "ok",
    "web_name":      "Haaland",
    "team_short":    "MCI",
    "captain_score": 54.85,
    "tier":          "upside",
    "role_signals": {
        "set_piece_notes": ["penalty_taker_1"],
        "role_bonus":      5.0,
    },
}


def _make_orch_ok(tool_chosen: str = "get_captain_score") -> OrchestratorResult:
    """Build a successful OrchestratorResult for the given tool."""
    return OrchestratorResult(
        question="should I captain Haaland",
        tool_chosen=tool_chosen,
        tool_args={"query": "Haaland"},
        tool_output=_CAPTAIN_TOOL_OUTPUT,
        answer_text="Captain Haaland with score 54.85.",
        llm_used=True,
        model=DEFAULT_ORCH_MODEL,
        outcome=ORCH_OUTCOME_OK,
        error=None,
    )


def _make_orch_non_ok(outcome: str) -> OrchestratorResult:
    """Build a non-OK OrchestratorResult for the given outcome."""
    llm_used = outcome not in {ORCH_OUTCOME_NO_CLIENT, ORCH_OUTCOME_LLM_ERROR}
    return OrchestratorResult(
        question="should I captain Haaland",
        tool_chosen=None if outcome in {
            ORCH_OUTCOME_NO_CLIENT, ORCH_OUTCOME_LLM_ERROR, ORCH_OUTCOME_NO_TOOL
        } else "get_captain_score",
        tool_args={},
        tool_output={},
        answer_text="[orch fallback]",
        llm_used=llm_used,
        model=DEFAULT_ORCH_MODEL if llm_used else "none",
        outcome=outcome,
        error=f"simulated {outcome}",
    )


_ALL_NON_OK_OUTCOMES = [
    ORCH_OUTCOME_NO_CLIENT,
    ORCH_OUTCOME_LLM_ERROR,
    ORCH_OUTCOME_NO_TOOL,
    ORCH_OUTCOME_UNKNOWN_TOOL,
    ORCH_OUTCOME_TOOL_ERROR,
    ORCH_OUTCOME_TOOL_RESULT_ERROR,
]

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

ok(ORCH_OUTCOME_NO_CLIENT == "no_client",   "A6: ORCH_OUTCOME_NO_CLIENT re-exported")
ok(ORCH_OUTCOME_LLM_ERROR == "llm_error",   "A7: ORCH_OUTCOME_LLM_ERROR re-exported")
ok(ORCH_OUTCOME_NO_TOOL == "no_tool",       "A8: ORCH_OUTCOME_NO_TOOL re-exported")
ok(ORCH_OUTCOME_UNKNOWN_TOOL == "unknown_tool",
   "A9: ORCH_OUTCOME_UNKNOWN_TOOL re-exported")
ok(ORCH_OUTCOME_TOOL_ERROR == "tool_error", "A10: ORCH_OUTCOME_TOOL_ERROR re-exported")
ok(ORCH_OUTCOME_TOOL_RESULT_ERROR == "tool_result_error",
   "A11: ORCH_OUTCOME_TOOL_RESULT_ERROR re-exported")
ok(len(_ALL_NON_OK_OUTCOMES) == 6,          "A12: 6 distinct non-OK outcome constants")


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
# Section C: orch ON, OUTCOME_OK -> orch_outcome == "ok"
# ---------------------------------------------------------------------------

print("\n=== C: orch ON, OUTCOME_OK -> orch_outcome == 'ok' ===")

_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_ok("get_captain_score")):
    _r_c1 = respond(_QUESTION, _BS)
_set_flag(None)

ok(_r_c1.orch_outcome == ORCH_OUTCOME_OK,   "C1: orch OK -> orch_outcome == 'ok'")
ok(_r_c1.orch_outcome == "ok",              "C2: orch_outcome is literal string 'ok'")
ok(_r_c1.outcome == DISP_OUTCOME_OK,        "C3: outcome field also ok on orch success")
ok(_r_c1.captain is not None,              "C4: captain metadata populated on orch OK")
ok(_r_c1.intent == INTENT_CAPTAIN_SCORE,   "C5: intent from orch tool mapping")


# ---------------------------------------------------------------------------
# Section D: each non-OK outcome -> orch_outcome captured, deterministic fallback
# ---------------------------------------------------------------------------

print("\n=== D: non-OK outcomes — orch_outcome captured, fallback deterministic ===")

for _outcome in _ALL_NON_OK_OUTCOMES:
    _set_flag("1")
    with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
               return_value=_make_orch_non_ok(_outcome)):
        _r = respond(_QUESTION, _BS)
    _set_flag(None)

    ok(_r.orch_outcome == _outcome,
       f"D-{_outcome}: orch_outcome == '{_outcome}'")
    ok(isinstance(_r.final_text, str) and len(_r.final_text) > 0,
       f"D-{_outcome}: final_text non-empty after fallback")
    ok(_r.intent == INTENT_CAPTAIN_SCORE,
       f"D-{_outcome}: intent from deterministic path (captain_score)")
    ok(_r.outcome != _outcome,
       f"D-{_outcome}: outcome != orch_outcome (deterministic wins)")


# ---------------------------------------------------------------------------
# Section E: fallback invariants
# ---------------------------------------------------------------------------

print("\n=== E: fallback invariants ===")

# E1: final_text for each non-OK outcome matches orch-OFF baseline
_set_flag(None)
_r_e_off = respond(_QUESTION, _BS)
_baseline_final_text = _r_e_off.final_text

for _outcome in _ALL_NON_OK_OUTCOMES:
    _set_flag("1")
    with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
               return_value=_make_orch_non_ok(_outcome)):
        _r_e = respond(_QUESTION, _BS)
    _set_flag(None)
    ok(_r_e.final_text == _baseline_final_text,
       f"E1-{_outcome}: final_text == orch-OFF baseline")

# E2: orch_outcome and outcome are independent fields
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_non_ok(ORCH_OUTCOME_LLM_ERROR)):
    _r_e2 = respond(_QUESTION, _BS)
_set_flag(None)
ok(_r_e2.orch_outcome == ORCH_OUTCOME_LLM_ERROR,  "E2: orch_outcome == 'llm_error'")
ok(_r_e2.outcome == DISP_OUTCOME_OK,              "E3: outcome == ok (deterministic)")
ok(_r_e2.orch_outcome != _r_e2.outcome,           "E4: orch_outcome != outcome")

# E5: supported=True for supported intent even after orch fallback
ok(_r_e2.supported is True,                       "E5: supported True after orch fallback")

# E6: captain metadata from deterministic path for captain_score intent
ok(_r_e2.captain is not None,                     "E6: captain populated in deterministic fallback")

# E7: unsupported intent — orch_outcome still captured, supported=False preserved
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_non_ok(ORCH_OUTCOME_NO_TOOL)):
    _r_e7 = respond("who will win the Premier League", _BS)
_set_flag(None)
ok(_r_e7.orch_outcome == ORCH_OUTCOME_NO_TOOL, "E7: unsupported + non-OK -> orch_outcome set")
ok(_r_e7.supported is False,                   "E8: unsupported.supported False after fallback")

# E9: all metadata None for non-metadata intents after orch fallback
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_non_ok(ORCH_OUTCOME_TOOL_ERROR)):
    _r_e9 = respond("who will win the Premier League", _BS)
_set_flag(None)
ok(_r_e9.comparison is None,                   "E9: comparison None for unsupported fallback")
ok(_r_e9.captain is None,                      "E10: captain None for unsupported fallback")
ok(_r_e9.chip is None,                         "E11: chip None for unsupported fallback")


# ---------------------------------------------------------------------------
# Section F: CLI surface — orch_outcome serialized in debug output
# ---------------------------------------------------------------------------

print("\n=== F: CLI surface serialization ===")

# F1/F2: orch ON, OK -> orch_outcome in CLI debug JSON
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_ok("get_captain_score")):
    _f1_exit, _f1_out = cli_run(_QUESTION, _BS, debug=True)
_set_flag(None)

_f1_body: dict[str, Any] = {}
try:
    _f1_body = json.loads(_f1_out)
except json.JSONDecodeError:
    pass

ok("orch_outcome" in _f1_body,              "F1: orch_outcome key in CLI debug JSON")
ok(_f1_body.get("orch_outcome") == "ok",    "F2: orch_outcome == 'ok' in CLI JSON")

# F3/F4: orch ON, non-OK -> orch_outcome in CLI debug JSON (fallback path)
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_non_ok(ORCH_OUTCOME_LLM_ERROR)):
    _f3_exit, _f3_out = cli_run(_QUESTION, _BS, debug=True)
_set_flag(None)

_f3_body: dict[str, Any] = {}
try:
    _f3_body = json.loads(_f3_out)
except json.JSONDecodeError:
    pass

ok("orch_outcome" in _f3_body,              "F3: orch_outcome key in CLI JSON on non-OK")
ok(_f3_body.get("orch_outcome") == "llm_error",
   "F4: orch_outcome == 'llm_error' in CLI JSON")

# F5: orch OFF -> orch_outcome absent from CLI debug JSON
_set_flag(None)
_f5_exit, _f5_out = cli_run(_QUESTION, _BS, debug=True)
_f5_body: dict[str, Any] = {}
try:
    _f5_body = json.loads(_f5_out)
except json.JSONDecodeError:
    pass
ok("orch_outcome" not in _f5_body,          "F5: orch_outcome absent when orch OFF")


# ---------------------------------------------------------------------------
# Section G: HTTP surface — orch_outcome in /ask response
# ---------------------------------------------------------------------------

print("\n=== G: HTTP surface serialization ===")

fpl_server._init_bootstrap(_BS)

# G1/G2: orch ON, OK -> orch_outcome in HTTP response
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_ok("get_captain_score")):
    _g1_resp = TestClient(server_app).post("/ask", json={"question": _QUESTION})
_set_flag(None)

_g1_body = _g1_resp.json()
ok("orch_outcome" in _g1_body,             "G1: orch_outcome in HTTP /ask response")
ok(_g1_body.get("orch_outcome") == "ok",   "G2: orch_outcome == 'ok' in HTTP response")

# G3/G4: orch ON, non-OK -> orch_outcome in HTTP response
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_non_ok(ORCH_OUTCOME_NO_TOOL)):
    _g3_resp = TestClient(server_app).post("/ask", json={"question": _QUESTION})
_set_flag(None)

_g3_body = _g3_resp.json()
ok("orch_outcome" in _g3_body,             "G3: orch_outcome in HTTP /ask on non-OK")
ok(_g3_body.get("orch_outcome") == "no_tool",
   "G4: orch_outcome == 'no_tool' in HTTP response")

# G5: orch OFF -> orch_outcome is None in HTTP response (field present, null value)
_set_flag(None)
_g5_resp = TestClient(server_app).post("/ask", json={"question": _QUESTION})
_g5_body = _g5_resp.json()
ok("orch_outcome" in _g5_body,             "G5: orch_outcome field present in HTTP response")
ok(_g5_body.get("orch_outcome") is None,   "G6: orch_outcome is null when orch OFF")


# ---------------------------------------------------------------------------
# Section H: Session surface — orch_outcome in /session/{id}/ask response
# ---------------------------------------------------------------------------

print("\n=== H: session surface serialization ===")

_h_client = TestClient(server_app)
_h_sess = _h_client.post("/session").json()
_h_session_id = _h_sess["session_id"]

# H1/H2: orch ON, OK -> orch_outcome in session response
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_ok("get_captain_score")):
    _h1_resp = _h_client.post(
        f"/session/{_h_session_id}/ask",
        json={"question": _QUESTION},
    )
_set_flag(None)

_h1_body = _h1_resp.json()
ok("orch_outcome" in _h1_body,             "H1: orch_outcome in session /ask response")
ok(_h1_body.get("orch_outcome") == "ok",   "H2: orch_outcome == 'ok' in session response")

# H3/H4: orch ON, non-OK -> orch_outcome in session response
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_non_ok(ORCH_OUTCOME_UNKNOWN_TOOL)):
    _h3_resp = _h_client.post(
        f"/session/{_h_session_id}/ask",
        json={"question": _QUESTION},
    )
_set_flag(None)

_h3_body = _h3_resp.json()
ok("orch_outcome" in _h3_body,             "H3: orch_outcome in session on non-OK")
ok(_h3_body.get("orch_outcome") == "unknown_tool",
   "H4: orch_outcome == 'unknown_tool' in session response")

# H5: orch OFF -> orch_outcome is None in session response
_set_flag(None)
_h5_resp = _h_client.post(
    f"/session/{_h_session_id}/ask",
    json={"question": _QUESTION},
)
_h5_body = _h5_resp.json()
ok("orch_outcome" in _h5_body,             "H5: orch_outcome field present in session response")
ok(_h5_body.get("orch_outcome") is None,   "H6: orch_outcome is null in session when orch OFF")


# ---------------------------------------------------------------------------
# Section I: Sub-call depth > 0 bypasses orch gate — orch_outcome is None
# ---------------------------------------------------------------------------

print("\n=== I: depth-1 (sub-call) bypasses orch gate ===")

# The orch gate is guarded by _multi_intent_depth == 0.
# Sub-calls in multi-intent turns run at depth 1 and skip the orch gate entirely,
# so orch_outcome is always None for them even when FPL_ORCH_ENABLED is ON.
_set_flag("1")
_r_i1 = respond(_QUESTION, _BS, _multi_intent_depth=1)
_set_flag(None)
ok(_r_i1.orch_outcome is None,             "I1: depth-1 call bypasses orch gate -> None")
ok(_r_i1.intent == INTENT_CAPTAIN_SCORE,   "I2: depth-1 intent from deterministic path")


# ---------------------------------------------------------------------------
# Section J: all 6 non-OK outcomes — complete audit column invariants
# ---------------------------------------------------------------------------

print("\n=== J: complete non-OK audit column invariants ===")

_set_flag(None)
_r_j_off = respond(_QUESTION, _BS)
_j_baseline_outcome    = _r_j_off.outcome
_j_baseline_intent     = _r_j_off.intent
_j_baseline_final_text = _r_j_off.final_text

for _oc in _ALL_NON_OK_OUTCOMES:
    _set_flag("1")
    with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
               return_value=_make_orch_non_ok(_oc)):
        _r_j = respond(_QUESTION, _BS)
    _set_flag(None)

    # Audit column
    ok(_r_j.orch_outcome == _oc,
       f"J-{_oc}: orch_outcome == '{_oc}'")
    # Deterministic columns unchanged
    ok(_r_j.outcome  == _j_baseline_outcome,
       f"J-{_oc}: outcome unchanged ({_j_baseline_outcome})")
    ok(_r_j.intent   == _j_baseline_intent,
       f"J-{_oc}: intent unchanged ({_j_baseline_intent})")
    ok(_r_j.final_text == _j_baseline_final_text,
       f"J-{_oc}: final_text matches orch-OFF baseline")
    ok(_r_j.captain is not None,
       f"J-{_oc}: captain metadata populated (deterministic)")


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
