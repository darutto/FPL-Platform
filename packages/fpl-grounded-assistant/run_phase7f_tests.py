"""
run_phase7f_tests.py
====================
Phase 7f: Transfer Follow-up Resolution -- test suite.

Target: ~105 assertions across 9 sections.

Sections
--------
A  resolve_transfer_followup() -- pure function pattern coverage (14)
B  ConversationState.last_transfer -- field and lifecycle tracking (10)
C  ConversationSession -- end-to-end follow-up rewrite in single session (14)
D  Resolver source -- "transfer_followup" in debug bundle (8)
E  Session HTTP -- transfer follow-up via POST /session/{id}/ask (14)
F  Session HTTP inspect -- last_transfer in GET /session/{id} (10)
G  Absence / safe fallback -- no context; patterns don't bleed (10)
H  Comparison follow-up unchanged by transfer state logic (12)
I  Regression -- Phase 7c scenarios still pass at expected counts (13)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

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
    ConversationState,
    ConversationSession,
    resolve_transfer_followup,
    resolve_comparison_followup,
    _TRANSFER_FOLLOWUP_PREFIXES,
    _TRANSFER_INSTEAD_SUFFIXES,
    INTENT_TRANSFER_ADVICE,
    INTENT_COMPARE_PLAYERS,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
)
from fpl_grounded_assistant.final_response import FinalResponse, respond
from fpl_grounded_assistant.conversation_state import _map_resolver_source
from fpl_grounded_assistant.reference_resolver import ReferenceResolution
import fpl_server
from fastapi.testclient import TestClient
from examples.session_examples import SESSION_FLOWS, run_session_flow, make_session_client
from examples.cli_examples import CLI_SCENARIOS, run_cli_scenario
from examples.http_examples import HTTP_SCENARIOS, run_http_scenario


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def check(cond: bool, label: str) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
        print(f"  FAIL: {label}")


def section(name: str) -> None:
    print(f"\n{name}")


BS = STANDARD_BOOTSTRAP

# Canonical questions
_Q_XFER = "should I sell Saka for Salah"   # strong transfer_in
_Q_COMP = "compare Haaland and Salah"
_Q_CAP  = "should I captain Salah"


# ---------------------------------------------------------------------------
# Section A -- resolve_transfer_followup() pure function (14)
# ---------------------------------------------------------------------------

section("A -- resolve_transfer_followup() pure function")

_state_a = ConversationState()
_state_a.last_transfer = ("Saka", "Salah")

# Returns None when no last_transfer
_state_empty = ConversationState()
check(resolve_transfer_followup("what about Palmer instead?", _state_empty) is None,
      "A1: returns None when last_transfer is None")

# Exports
check(_TRANSFER_FOLLOWUP_PREFIXES == ("what about ", "how about "),
      "A2: _TRANSFER_FOLLOWUP_PREFIXES tuple content")
check(_TRANSFER_INSTEAD_SUFFIXES == (" instead",),
      "A3: _TRANSFER_INSTEAD_SUFFIXES tuple content")

# Pattern: "what about X instead?"
_r_a4 = resolve_transfer_followup("what about Palmer instead?", _state_a)
check(_r_a4 == "sell Saka for Palmer",
      "A4: 'what about X instead?' → canonical transfer form")

# Pattern: "what about X?"
_r_a5 = resolve_transfer_followup("what about Palmer?", _state_a)
check(_r_a5 == "sell Saka for Palmer",
      "A5: 'what about X?' → canonical transfer form")

# Pattern: "how about X instead?"
_r_a6 = resolve_transfer_followup("how about Haaland instead?", _state_a)
check(_r_a6 == "sell Saka for Haaland",
      "A6: 'how about X instead?' → canonical transfer form")

# Pattern: "how about X?"
_r_a7 = resolve_transfer_followup("how about De Bruyne?", _state_a)
check(_r_a7 == "sell Saka for De Bruyne",
      "A7: 'how about X?' with multi-word player → canonical transfer form")

# Pattern: bare "X instead?"
_r_a8 = resolve_transfer_followup("Haaland instead?", _state_a)
check(_r_a8 == "sell Saka for Haaland",
      "A8: bare 'X instead?' → canonical transfer form")

# Pattern: bare "X instead" (no punctuation)
_r_a9 = resolve_transfer_followup("Haaland instead", _state_a)
check(_r_a9 == "sell Saka for Haaland",
      "A9: bare 'X instead' (no ?) → canonical transfer form")

# Case-insensitivity
_r_a10 = resolve_transfer_followup("What About Palmer Instead?", _state_a)
check(_r_a10 == "sell Saka for Palmer",
      "A10: case-insensitive prefix and suffix matching")

# Unknown prefix → None (no false-match on unrelated questions)
check(resolve_transfer_followup("should I captain Salah", _state_a) is None,
      "A11: unrelated captain question → None (no false-match)")
check(resolve_transfer_followup("compare Salah and Haaland", _state_a) is None,
      "A12: comparison question → None (no false-match)")

# Player preserved from last_transfer[0]
_state_a13 = ConversationState()
_state_a13.last_transfer = ("Bruno", "Foden")
_r_a13 = resolve_transfer_followup("what about Palmer?", _state_a13)
check(_r_a13 == "sell Bruno for Palmer",
      "A13: last_out correctly propagated for different pair")

# Multi-word player_out
_state_a14 = ConversationState()
_state_a14.last_transfer = ("De Bruyne", "Salah")
_r_a14 = resolve_transfer_followup("what about Palmer instead?", _state_a14)
check(_r_a14 == "sell De Bruyne for Palmer",
      "A14: multi-word player_out preserved in rewritten form")


# ---------------------------------------------------------------------------
# Section B -- ConversationState.last_transfer lifecycle (10)
# ---------------------------------------------------------------------------

section("B -- ConversationState.last_transfer lifecycle")

_state_b = ConversationState()
check(_state_b.last_transfer is None,
      "B1: last_transfer initialises to None")

# Populated after successful transfer turn
_fr_b = respond(_Q_XFER, BS)
_state_b.update_from_response(
    _fr_b, resolved_query=None,
    transfer_queries=("Saka", "Salah"),
    resolver_source="none",
)
check(_state_b.last_transfer == ("Saka", "Salah"),
      "B2: last_transfer set after successful transfer OK turn")

# Not cleared by subsequent failed/not_found transfer
_fr_b3 = respond("should I sell Saka for NoSuchPlayer9999", BS)
check(_fr_b3.outcome == OUTCOME_NOT_FOUND,                     "B3-pre: not_found transfer outcome")
_state_b.update_from_response(
    _fr_b3, resolved_query=None,
    transfer_queries=None,   # not set for not_found
    resolver_source="none",
)
check(_state_b.last_transfer == ("Saka", "Salah"),
      "B4: last_transfer NOT cleared on not_found transfer (no new transfer_queries)")

# Cleared by successful captain turn
_fr_b5 = respond(_Q_CAP, BS)
check(_fr_b5.outcome == OUTCOME_OK,                            "B5-pre: captain OK")
_state_b.update_from_response(
    _fr_b5, resolved_query="Salah",
    transfer_queries=None,
    resolver_source="none",
)
check(_state_b.last_transfer is None,
      "B6: last_transfer cleared after successful non-transfer turn")

# Cleared by successful comparison turn
_state_b7 = ConversationState()
_state_b7.update_from_response(
    respond(_Q_XFER, BS), resolved_query=None,
    transfer_queries=("Saka", "Salah"), resolver_source="none",
)
check(_state_b7.last_transfer == ("Saka", "Salah"),            "B7-pre: last_transfer set")
_state_b7.update_from_response(
    respond(_Q_COMP, BS), resolved_query=None,
    comparison_queries=("Haaland", "Salah"), resolver_source="none",
)
check(_state_b7.last_transfer is None,
      "B8: last_transfer cleared after successful comparison turn")

# clear() resets last_transfer
_state_b9 = ConversationState()
_state_b9.last_transfer = ("Saka", "Salah")
_state_b9.clear()
check(_state_b9.last_transfer is None,
      "B9: clear() resets last_transfer to None")

# last_comparison independently tracked (not affected by transfer)
_state_b10 = ConversationState()
_state_b10.update_from_response(
    respond(_Q_COMP, BS), resolved_query=None,
    comparison_queries=("Haaland", "Salah"), resolver_source="none",
)
check(_state_b10.last_comparison == ("Haaland", "Salah"),      "B10-pre: last_comparison set")
_state_b10.update_from_response(
    respond(_Q_XFER, BS), resolved_query=None,
    transfer_queries=("Saka", "Salah"), resolver_source="none",
)
check(_state_b10.last_comparison is None and _state_b10.last_transfer == ("Saka", "Salah"),
      "B10: transfer turn clears last_comparison, sets last_transfer")


# ---------------------------------------------------------------------------
# Section C -- ConversationSession end-to-end follow-up rewrite (14)
# ---------------------------------------------------------------------------

section("C -- ConversationSession end-to-end follow-up")

# Turn 1: direct transfer
_sess_c = ConversationSession()
_r_c1 = _sess_c.respond(_Q_XFER, BS)
check(_r_c1.outcome == OUTCOME_OK,                             "C1: turn 1 transfer OK")
check(_r_c1.intent == INTENT_TRANSFER_ADVICE,                  "C2: turn 1 intent == transfer_advice")
check(_sess_c.state.last_transfer == ("Saka", "Salah"),        "C3: last_transfer set after turn 1")
check(_r_c1.transfer is not None,                              "C4: transfer metadata populated on turn 1")
check(_r_c1.transfer.player_out == "Saka",                     "C5: turn 1 player_out == Saka")
check(_r_c1.transfer.player_in  == "Salah",                    "C6: turn 1 player_in == Salah")

# Turn 2: "what about Haaland instead?" → rewritten to "sell Saka for Haaland"
_r_c7 = _sess_c.respond("what about Haaland instead?", BS)
check(_r_c7.outcome == OUTCOME_OK,                             "C7: turn 2 follow-up OK")
check(_r_c7.intent == INTENT_TRANSFER_ADVICE,                  "C8: turn 2 intent == transfer_advice")
check(_r_c7.transfer is not None,                              "C9: turn 2 transfer metadata populated")
check(_r_c7.transfer.player_out == "Saka",                     "C10: turn 2 player_out anchors to Saka")
check(_r_c7.transfer.player_in  == "Haaland",                  "C11: turn 2 player_in rewritten to Haaland")
check(_sess_c.state.last_transfer == ("Saka", "Haaland"),      "C12: last_transfer updated after follow-up")
check(_sess_c.state.last_resolver_source == "transfer_followup",
      "C13: resolver_source == 'transfer_followup' after follow-up turn")

# Turn 3: bare "Salah instead?" pattern (Salah is in STANDARD_BOOTSTRAP)
_r_c14 = _sess_c.respond("Salah instead?", BS)
check(_r_c14.outcome == OUTCOME_OK,                            "C14: bare 'X instead?' follow-up OK")


# ---------------------------------------------------------------------------
# Section D -- Resolver source "transfer_followup" in debug (8)
# ---------------------------------------------------------------------------

section("D -- Resolver source 'transfer_followup'")

# _map_resolver_source() returns "transfer_followup" for reference_source="transfer_followup"
_xfer_resolution = ReferenceResolution(
    resolved_query=None,
    intent_guess=INTENT_TRANSFER_ADVICE,
    reference_source="transfer_followup",
    confidence=1.0,
    language="en",
    rewritten_question="sell Saka for Haaland",
    fallback_reason=None,
)
check(_map_resolver_source(_xfer_resolution) == "transfer_followup",
      "D1: _map_resolver_source maps 'transfer_followup' correctly")

# ResolverDebug.resolver_source in debug bundle
_sess_d = ConversationSession()
_sess_d.respond(_Q_XFER, BS)   # turn 1 — set context
_r_d2 = _sess_d.respond("what about Haaland instead?", BS, include_debug=True)
check(_r_d2.debug is not None,                                  "D2: debug bundle present")
check(_r_d2.debug.resolver is not None,                         "D3: resolver debug present")
check(_r_d2.debug.resolver.resolver_used is True,               "D4: resolver_used == True")
check(_r_d2.debug.resolver.resolver_source == "transfer_followup",
      "D5: resolver_source == 'transfer_followup' in debug bundle")
check(_r_d2.debug.resolver.resolver_confidence is None,
      "D6: resolver_confidence is None for deterministic transfer_followup")
check(_r_d2.debug.resolver.rewritten_question == "sell Saka for Haaland",
      "D7: rewritten_question in debug reflects rewrite")
check(_r_d2.debug.resolver.fallback_reason is None,
      "D8: fallback_reason is None for deterministic transfer_followup")


# ---------------------------------------------------------------------------
# Section E -- Session HTTP: transfer follow-up via POST /session/{id}/ask (14)
# ---------------------------------------------------------------------------

section("E -- Session HTTP transfer follow-up")

fpl_server._init_bootstrap(BS)
_client_e = TestClient(fpl_server.app, raise_server_exceptions=True)

_cr_e = _client_e.post("/session")
check(_cr_e.status_code == 200,                                "E1: create session 200")
_sid_e = _cr_e.json()["session_id"]

# Turn 1: direct transfer
_t1_e = _client_e.post(f"/session/{_sid_e}/ask",
                        json={"question": _Q_XFER})
check(_t1_e.status_code == 200,                                "E2: turn 1 HTTP 200")
_b1_e = _t1_e.json()
check(_b1_e.get("outcome") == "ok",                            "E3: turn 1 outcome ok")
check(_b1_e.get("transfer") is not None,                       "E4: turn 1 transfer not null")
check(_b1_e["transfer"].get("player_out") == "Saka",           "E5: turn 1 player_out == Saka")
check(_b1_e["transfer"].get("player_in")  == "Salah",          "E6: turn 1 player_in == Salah")

# Turn 2: "what about Haaland instead?"
_t2_e = _client_e.post(f"/session/{_sid_e}/ask",
                        json={"question": "what about Haaland instead?"})
check(_t2_e.status_code == 200,                                "E7: turn 2 HTTP 200")
_b2_e = _t2_e.json()
check(_b2_e.get("outcome") == "ok",                            "E8: turn 2 outcome ok")
check(_b2_e.get("intent") == "transfer_advice",                "E9: turn 2 intent == transfer_advice")
check(_b2_e.get("transfer") is not None,                       "E10: turn 2 transfer not null")
check(_b2_e["transfer"].get("player_out") == "Saka",           "E11: turn 2 player_out anchors to Saka")
check(_b2_e["transfer"].get("player_in")  == "Haaland",        "E12: turn 2 player_in == Haaland")

# Turn 3: "how about Salah?" (back to Salah)
_t3_e = _client_e.post(f"/session/{_sid_e}/ask",
                        json={"question": "how about Salah?"})
check(_t3_e.status_code == 200,                                "E13: turn 3 HTTP 200")
_b3_e = _t3_e.json()
check(_b3_e.get("intent") == "transfer_advice",                "E14: turn 3 intent == transfer_advice via follow-up")

_client_e.delete(f"/session/{_sid_e}")


# ---------------------------------------------------------------------------
# Section F -- Session HTTP inspect: last_transfer in GET /session/{id} (10)
# ---------------------------------------------------------------------------

section("F -- Session HTTP inspect last_transfer")

fpl_server._init_bootstrap(BS)
_client_f = TestClient(fpl_server.app, raise_server_exceptions=True)
_sid_f = _client_f.post("/session").json()["session_id"]

# Inspect before any turn — last_transfer should be null
_inspect_f0 = _client_f.get(f"/session/{_sid_f}").json()
check(_inspect_f0.get("last_transfer") is None,
      "F1: last_transfer null before any turn")

# After turn 1 (transfer)
_client_f.post(f"/session/{_sid_f}/ask", json={"question": _Q_XFER})
_inspect_f1 = _client_f.get(f"/session/{_sid_f}").json()
_lt_f1 = _inspect_f1.get("last_transfer")
check(_lt_f1 is not None,                                      "F2: last_transfer not null after transfer turn")
check(_lt_f1.get("player_out") == "Saka",                      "F3: last_transfer.player_out == Saka")
check(_lt_f1.get("player_in")  == "Salah",                     "F4: last_transfer.player_in == Salah")

# After follow-up turn — last_transfer updates to new pair
_client_f.post(f"/session/{_sid_f}/ask", json={"question": "what about Haaland instead?"})
_inspect_f2 = _client_f.get(f"/session/{_sid_f}").json()
_lt_f2 = _inspect_f2.get("last_transfer")
check(_lt_f2 is not None,                                      "F5: last_transfer not null after follow-up turn")
check(_lt_f2.get("player_out") == "Saka",                      "F6: last_transfer.player_out still Saka after follow-up")
check(_lt_f2.get("player_in")  == "Haaland",                   "F7: last_transfer.player_in updated to Haaland")
check(_inspect_f2.get("last_resolver_source") == "transfer_followup",
      "F8: last_resolver_source == 'transfer_followup' in inspect after follow-up")

# After non-transfer turn — last_transfer cleared
_client_f.post(f"/session/{_sid_f}/ask", json={"question": _Q_CAP})
_inspect_f3 = _client_f.get(f"/session/{_sid_f}").json()
check(_inspect_f3.get("last_transfer") is None,
      "F9: last_transfer cleared after non-transfer successful turn")
check("player_out" not in (_inspect_f3.get("last_transfer") or {}),
      "F10: last_transfer has no player_out when cleared")

_client_f.delete(f"/session/{_sid_f}")


# ---------------------------------------------------------------------------
# Section G -- Absence / safe fallback (10)
# ---------------------------------------------------------------------------

section("G -- Absence and safe fallback")

# No context — "what about X instead?" should not match any supported intent
_sess_g = ConversationSession()
_r_g1 = _sess_g.respond("what about Palmer instead?", BS)
# Without transfer context, this falls through to unsupported (no route matches)
check(_r_g1.intent in ("unsupported", "transfer_advice"),
      "G1: no context — 'what about X instead?' doesn't crash (unsupported or routes)")
# More importantly, resolve_transfer_followup returns None without context:
_state_g2 = ConversationState()
check(resolve_transfer_followup("what about Palmer instead?", _state_g2) is None,
      "G2: pure function returns None with no last_transfer context")
check(resolve_transfer_followup("how about Palmer?", _state_g2) is None,
      "G3: 'how about X?' pure function returns None with no last_transfer context")
check(resolve_transfer_followup("Haaland instead?", _state_g2) is None,
      "G4: bare 'X instead?' pure function returns None with no last_transfer context")

# After not_found transfer, last_transfer is NOT set — follow-up stays safe
_sess_g5 = ConversationSession()
_r_nf = _sess_g5.respond("should I sell Saka for NoSuchXYZ999", BS)
check(_r_nf.outcome == OUTCOME_NOT_FOUND,                      "G5-pre: not_found transfer")
check(_sess_g5.state.last_transfer is None,
      "G5: last_transfer not set after not_found transfer turn")
_r_g6 = _sess_g5.respond("what about Haaland instead?", BS)
check(_r_g6.intent != INTENT_TRANSFER_ADVICE or _r_g6.outcome != OUTCOME_OK,
      "G6: follow-up without transfer context doesn't produce spurious OK transfer")

# Successful transfer followed by captain (context cleared) → follow-up not triggered
_sess_g7 = ConversationSession()
_sess_g7.respond(_Q_XFER, BS)
_sess_g7.respond(_Q_CAP, BS)   # clears last_transfer
check(_sess_g7.state.last_transfer is None,                    "G7: last_transfer cleared after captain turn")
_r_g8 = _sess_g7.respond("what about Palmer?", BS)
# With no transfer context, the follow-up should not rewrite to a transfer
check(_sess_g7.state.last_transfer is None or _r_g8.intent != INTENT_TRANSFER_ADVICE,
      "G8: no transfer follow-up after context cleared by captain turn")

# Stateless respond() unaffected
_r_g9 = respond("what about Palmer?", BS)
check(_r_g9 is not None,                                       "G9: stateless respond() unaffected by new state fields")
check(hasattr(_r_g9, "transfer"),                              "G10: stateless respond() still has transfer attribute")


# ---------------------------------------------------------------------------
# Section H -- Comparison follow-up unchanged (12)
# ---------------------------------------------------------------------------

section("H -- Comparison follow-up not broken")

_sess_h = ConversationSession()
_r_h1 = _sess_h.respond(_Q_COMP, BS)
check(_r_h1.outcome == OUTCOME_OK,                             "H1: comparison turn OK")
check(_r_h1.intent == INTENT_COMPARE_PLAYERS,                  "H2: comparison intent")
check(_sess_h.state.last_comparison == ("Haaland", "Salah"),   "H3: last_comparison set")
check(_sess_h.state.last_transfer is None,                     "H4: last_transfer is None after comparison turn")

# Comparison follow-up still works
_r_h5 = _sess_h.respond("what about Saka?", BS)
check(_r_h5.intent == INTENT_COMPARE_PLAYERS,                  "H5: comparison follow-up still fires")
check(_r_h5.outcome == OUTCOME_OK,                             "H6: comparison follow-up OK")
check(_sess_h.state.last_resolver_source == "comparison_followup",
      "H7: resolver_source still 'comparison_followup' (not 'transfer_followup')")

# Transfer then comparison — comparison follow-up fires, not transfer follow-up
_sess_h8 = ConversationSession()
_sess_h8.respond(_Q_XFER, BS)            # sets last_transfer
_sess_h8.respond(_Q_COMP, BS)            # clears last_transfer, sets last_comparison
check(_sess_h8.state.last_transfer is None,                    "H8: last_transfer cleared after comparison turn")
check(_sess_h8.state.last_comparison == ("Haaland", "Salah"),  "H9: last_comparison set after comparison turn")
_r_h10 = _sess_h8.respond("what about Saka?", BS)
check(_r_h10.intent == INTENT_COMPARE_PLAYERS,                 "H10: comparison follow-up fires after transfer→comparison sequence")
check(_sess_h8.state.last_resolver_source == "comparison_followup",
      "H11: resolver_source is 'comparison_followup' (not 'transfer_followup')")

# resolve_comparison_followup still pure and unaffected
_state_h12 = ConversationState()
_state_h12.last_comparison = ("Haaland", "Salah")
_r_h12 = resolve_comparison_followup("what about Saka?", _state_h12)
check(_r_h12 == "compare Haaland and Saka",                    "H12: resolve_comparison_followup pure function unchanged")


# ---------------------------------------------------------------------------
# Section I -- Regression: Phase 7c scenarios pass (13)
# ---------------------------------------------------------------------------

section("I -- Regression Phase 7c")

fpl_server._init_bootstrap(BS)
_client_i = TestClient(fpl_server.app, raise_server_exceptions=True)

# CLI: transfer_debug still works
_c_transfer = next(s for s in CLI_SCENARIOS if s["id"] == "transfer_debug")
_code_i1, _out_i1 = run_cli_scenario(_c_transfer)
check(_code_i1 == 0,                                           "I1: transfer_debug CLI exit 0")
try:
    _j_i1 = json.loads(_out_i1)
    check("transfer" in _j_i1,                                "I2: transfer_debug CLI JSON has transfer key")
    check(_j_i1["transfer"]["player_out"] == "Saka",           "I3: transfer_debug player_out == Saka")
except Exception:
    check(False, "I2: transfer_debug CLI JSON parse failed")
    check(False, "I3: transfer_debug player_out check skipped")

# CLI: chip_debug still works
_c_chip = next(s for s in CLI_SCENARIOS if s["id"] == "chip_debug")
_code_i4, _out_i4 = run_cli_scenario(_c_chip)
check(_code_i4 == 0,                                           "I4: chip_debug CLI exit 0")
try:
    _j_i4 = json.loads(_out_i4)
    check("chip" in _j_i4,                                    "I5: chip_debug CLI JSON has chip key")
except Exception:
    check(False, "I5: chip_debug CLI JSON parse failed")

# HTTP: transfer_structured still works
_h_transfer = next(s for s in HTTP_SCENARIOS if s["id"] == "transfer_structured")
_status_i6, _body_i6 = run_http_scenario(_h_transfer)
check(_status_i6 == 200,                                       "I6: transfer_structured HTTP 200")
check(_body_i6.get("outcome") == "ok",                        "I7: transfer_structured outcome ok")
check(_body_i6.get("transfer") is not None,                    "I8: transfer_structured transfer not null")

# HTTP: chip_structured still works
_h_chip = next(s for s in HTTP_SCENARIOS if s["id"] == "chip_structured")
_status_i9, _body_i9 = run_http_scenario(_h_chip)
check(_status_i9 == 200,                                       "I9: chip_structured HTTP 200")
check(_body_i9.get("chip") is not None,                        "I10: chip_structured chip not null")

# Session: multi_intent_transfer_and_chip flow still passes
_flow_mi = next(f for f in SESSION_FLOWS if f["id"] == "multi_intent_transfer_and_chip")
_result_i = run_session_flow(_flow_mi, _client_i)
check(all(t["status"] == 200 for t in _result_i.get("turns", [])),
      "I11: multi_intent_transfer_and_chip session flow all 200")
_mi_body = _result_i["turns"][0]["body"]
check(_mi_body.get("intent") == "multi_intent",                "I12: multi_intent session turn intent correct")
check(len(_mi_body.get("sub_responses", [])) == 2,             "I13: multi_intent 2 sub_responses")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

_total = _PASS + _FAIL
print(f"\nPhase 7f: {_PASS}/{_total} PASS")
if _FAIL == 0:
    print("          All assertions passed.")
else:
    print(f"          {_FAIL} assertion(s) FAILED.")
    sys.exit(1)
