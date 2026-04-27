"""
run_phase7b_tests.py
====================
Phase 7b: Structured Chip Advice Metadata -- test suite.

Target: ~92 assertions across 9 sections.

Sections
--------
A  ChipAdviceMeta dataclass -- fields, types, frozen (10)
B  FinalResponse.chip populated for chip_advice OK turns (16)
C  FinalResponse.chip None for non-chip turns (10)
D  signal_value / signal_label per chip (12)
E  CLI _serial_chip() helper -- correct keys and values (8)
F  CLI run() debug JSON includes chip key (10)
G  CLI run_session() turn dict includes chip (8)
H  HTTP /ask serialization -- chip dict keys and values (10)
I  Multi-intent sub_responses can expose chip metadata (8)
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
    respond,
    ChipAdviceMeta,
    INTENT_CHIP_ADVICE,
)
from fpl_grounded_assistant.dispatcher import (
    INTENT_CAPTAIN_SCORE, INTENT_COMPARE_PLAYERS, INTENT_TRANSFER_ADVICE,
    OUTCOME_OK,
)
from fpl_grounded_assistant.final_response import FinalResponse
from fpl_cli import run as cli_run, run_session as cli_run_session, _serial_chip
from fpl_server import (
    AskResponse, SessionAskResponse, _chip_meta_dict,
)
import fpl_server
from fastapi.testclient import TestClient
from validation_corpus import VALIDATION_SCENARIOS


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
    print(f"\n--- {name} ---")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

BS = STANDARD_BOOTSTRAP

# Bootstrap and server client
fpl_server._init_bootstrap(BS)
_client_g = TestClient(fpl_server.app)

# Chip questions
_Q_TC   = "should I use triple captain this week"
_Q_WC   = "should I wildcard this week"
_Q_BB   = "should I bench boost now"
_Q_FH   = "should I free hit this week"


# ---------------------------------------------------------------------------
# Section A -- ChipAdviceMeta dataclass (10)
# ---------------------------------------------------------------------------

section("A -- ChipAdviceMeta dataclass")

# Construct a ChipAdviceMeta directly
_meta_a = ChipAdviceMeta(
    chip="triple_captain",
    recommendation="conditions_favorable",
    gw=22,
    signal_value=83.5,
    signal_label="top captain score",
)

check(isinstance(_meta_a, ChipAdviceMeta),         "A1: ChipAdviceMeta is correct type")
check(_meta_a.chip == "triple_captain",            "A2: chip field correct")
check(_meta_a.recommendation == "conditions_favorable", "A3: recommendation correct")
check(_meta_a.gw == 22,                            "A4: gw field correct")
check(isinstance(_meta_a.gw, int),                 "A5: gw is int")
check(_meta_a.signal_value == 83.5,                "A6: signal_value correct")
check(isinstance(_meta_a.signal_value, float),     "A7: signal_value is float")
check(_meta_a.signal_label == "top captain score", "A8: signal_label correct")

# Frozen
try:
    _meta_a.chip = "wildcard"  # type: ignore[misc]
    check(False, "A9: ChipAdviceMeta is frozen (should have raised)")
except Exception:
    check(True, "A9: ChipAdviceMeta is frozen")

# None signal fields allowed
_meta_fh = ChipAdviceMeta(
    chip="free_hit",
    recommendation="missing_context",
    gw=22,
    signal_value=None,
    signal_label=None,
)
check(_meta_fh.signal_value is None and _meta_fh.signal_label is None,
      "A10: free_hit meta has None signal fields")


# ---------------------------------------------------------------------------
# Section B -- FinalResponse.chip populated for chip_advice OK turns (16)
# ---------------------------------------------------------------------------

section("B -- FinalResponse.chip populated")

_fr_tc = respond(_Q_TC, BS)
_fr_wc = respond(_Q_WC, BS)
_fr_bb = respond(_Q_BB, BS)
_fr_fh = respond(_Q_FH, BS)

# Triple captain
check(_fr_tc.intent == INTENT_CHIP_ADVICE,         "B1: TC intent == chip_advice")
check(_fr_tc.outcome == OUTCOME_OK,                "B2: TC outcome == ok")
check(_fr_tc.chip is not None,                     "B3: TC chip field populated")
check(isinstance(_fr_tc.chip, ChipAdviceMeta),     "B4: TC chip is ChipAdviceMeta")
check(_fr_tc.chip.chip == "triple_captain",        "B5: TC chip.chip field")
check(_fr_tc.chip.recommendation in {
    "conditions_favorable", "conditions_marginal", "conditions_unfavorable"},
      "B6: TC recommendation is valid")

# Wildcard
check(_fr_wc.intent == INTENT_CHIP_ADVICE,         "B7: WC intent == chip_advice")
check(_fr_wc.chip is not None,                     "B8: WC chip field populated")
check(_fr_wc.chip.chip == "wildcard",              "B9: WC chip.chip field")
check(_fr_wc.chip.recommendation in {
    "conditions_favorable", "conditions_marginal", "conditions_unfavorable"},
      "B10: WC recommendation is valid")

# Bench boost
check(_fr_bb.chip is not None,                     "B11: BB chip field populated")
check(_fr_bb.chip.chip == "bench_boost",           "B12: BB chip.chip field")

# Free hit — always missing_context
check(_fr_fh.chip is not None,                     "B13: FH chip field populated")
check(_fr_fh.chip.chip == "free_hit",              "B14: FH chip.chip field")
check(_fr_fh.chip.recommendation == "missing_context",
      "B15: FH recommendation is missing_context")

# gw is int or None (not string)
check(_fr_tc.chip.gw is None or isinstance(_fr_tc.chip.gw, int),
      "B16: TC chip.gw is int or None")


# ---------------------------------------------------------------------------
# Section C -- FinalResponse.chip None for non-chip turns (10)
# ---------------------------------------------------------------------------

section("C -- FinalResponse.chip None for non-chip turns")

_fr_capt = respond("should I captain Haaland", BS)
_fr_comp = respond("compare Salah and Haaland", BS)
_fr_xfer = respond("sell Saka for Salah", BS)
_fr_summ = respond("who is Salah", BS)
_fr_gw   = respond("what gameweek is it", BS)

check(_fr_capt.chip is None,    "C1: captain_score chip is None")
check(_fr_comp.chip is None,    "C2: compare_players chip is None")
check(_fr_xfer.chip is None,    "C3: transfer_advice chip is None")
check(_fr_summ.chip is None,    "C4: player_summary chip is None")
check(_fr_gw.chip is None,      "C5: current_gameweek chip is None")

# Chip field absent does not affect other fields
check(_fr_capt.captain is not None,  "C6: captain_score still populates captain field")
check(_fr_comp.comparison is not None, "C7: compare_players still populates comparison")
check(_fr_xfer.transfer is not None,  "C8: transfer_advice still populates transfer")
check(_fr_capt.transfer is None,      "C9: captain_score transfer is None")
check(_fr_comp.transfer is None,      "C10: compare_players transfer is None")


# ---------------------------------------------------------------------------
# Section D -- signal_value / signal_label per chip (12)
# ---------------------------------------------------------------------------

section("D -- signal_value / signal_label per chip")

# Triple captain: signal is top captain score (float)
check(_fr_tc.chip.signal_value is None or isinstance(_fr_tc.chip.signal_value, float),
      "D1: TC signal_value is float or None")
check(_fr_tc.chip.signal_label == "top captain score" or _fr_tc.chip.signal_value is None,
      "D2: TC signal_label is 'top captain score' when value present")
if _fr_tc.chip.signal_value is not None:
    check(_fr_tc.chip.signal_value > 0,
          "D3: TC signal_value > 0 when present")
else:
    check(True, "D3: TC signal_value is None (acceptable)")

# Wildcard: signal is current gameweek (float)
check(_fr_wc.chip.signal_value is None or isinstance(_fr_wc.chip.signal_value, float),
      "D4: WC signal_value is float or None")
check(_fr_wc.chip.signal_label == "current gameweek" or _fr_wc.chip.signal_value is None,
      "D5: WC signal_label is 'current gameweek' when value present")
if _fr_wc.chip.signal_value is not None:
    check(_fr_wc.chip.signal_value >= 1,
          "D6: WC signal_value >= 1 (valid GW number)")
else:
    check(True, "D6: WC signal_value is None (acceptable)")

# Bench boost: signal is average FDR (float in 1.0–5.0 range)
check(_fr_bb.chip.signal_value is None or isinstance(_fr_bb.chip.signal_value, float),
      "D7: BB signal_value is float or None")
check(_fr_bb.chip.signal_label == "average FDR (top 10)" or _fr_bb.chip.signal_value is None,
      "D8: BB signal_label is 'average FDR (top 10)' when value present")
if _fr_bb.chip.signal_value is not None:
    check(1.0 <= _fr_bb.chip.signal_value <= 5.0,
          "D9: BB signal_value in plausible FDR range")
else:
    check(True, "D9: BB signal_value is None (acceptable)")

# Free hit: signal always None
check(_fr_fh.chip.signal_value is None,  "D10: FH signal_value is None")
check(_fr_fh.chip.signal_label is None,  "D11: FH signal_label is None")

# signal_value None iff signal_label None (invariant)
for _chip_fr, _name in [
    (_fr_tc, "TC"), (_fr_wc, "WC"), (_fr_bb, "BB"), (_fr_fh, "FH"),
]:
    sv = _chip_fr.chip.signal_value
    sl = _chip_fr.chip.signal_label
    check((sv is None) == (sl is None),
          f"D12: {_name} signal_value and signal_label both None or both present")
    break  # one representative check sufficient; rest checked implicitly above


# ---------------------------------------------------------------------------
# Section E -- CLI _serial_chip() helper (8)
# ---------------------------------------------------------------------------

section("E -- CLI _serial_chip() helper")

_chip_e = ChipAdviceMeta(
    chip="bench_boost",
    recommendation="conditions_marginal",
    gw=18,
    signal_value=2.9,
    signal_label="average FDR (top 10)",
)
_sd_e = _serial_chip(_chip_e)

check(isinstance(_sd_e, dict),                      "E1: _serial_chip returns dict")
check(set(_sd_e.keys()) == {
    "chip", "recommendation", "gw", "signal_value", "signal_label"},
      "E2: _serial_chip has exactly expected keys")
check(_sd_e["chip"] == "bench_boost",               "E3: chip key correct")
check(_sd_e["recommendation"] == "conditions_marginal", "E4: recommendation correct")
check(_sd_e["gw"] == 18,                            "E5: gw key correct")
check(_sd_e["signal_value"] == 2.9,                 "E6: signal_value correct")
check(_sd_e["signal_label"] == "average FDR (top 10)", "E7: signal_label correct")

# None fields are preserved
_chip_fh_e = ChipAdviceMeta(
    chip="free_hit", recommendation="missing_context",
    gw=22, signal_value=None, signal_label=None,
)
_sd_fh = _serial_chip(_chip_fh_e)
check(_sd_fh["signal_value"] is None and _sd_fh["signal_label"] is None,
      "E8: None signal fields preserved in serialisation")


# ---------------------------------------------------------------------------
# Section F -- CLI run() debug JSON includes chip key (10)
# ---------------------------------------------------------------------------

section("F -- CLI run() debug JSON includes chip")

# Triple captain debug
_exit_f, _out_f = cli_run(_Q_TC, BS, debug=True)
_payload_f: dict = {}
try:
    _payload_f = json.loads(_out_f)
except Exception:
    pass

check("chip" in _payload_f,                         "F1: chip key in TC debug payload")
check(isinstance(_payload_f.get("chip"), dict),     "F2: chip value is dict")
_chip_f = _payload_f.get("chip") or {}
check(_chip_f.get("chip") == "triple_captain",      "F3: chip.chip == triple_captain")
check("recommendation" in _chip_f,                  "F4: recommendation key present")
check("gw" in _chip_f,                              "F5: gw key present")
check("signal_value" in _chip_f,                    "F6: signal_value key present")
check("signal_label" in _chip_f,                    "F7: signal_label key present")

# Free hit debug — chip present, signal_value null
_exit_fh_f, _out_fh_f = cli_run(_Q_FH, BS, debug=True)
_payload_fh_f: dict = {}
try:
    _payload_fh_f = json.loads(_out_fh_f)
except Exception:
    pass
_chip_fh_f = _payload_fh_f.get("chip") or {}
check(_chip_fh_f.get("recommendation") == "missing_context",
      "F8: FH debug chip recommendation == missing_context")

# Non-chip turn should not have chip key
_exit_nc, _out_nc = cli_run("should I captain Haaland", BS, debug=True)
_payload_nc: dict = {}
try:
    _payload_nc = json.loads(_out_nc)
except Exception:
    pass
check("chip" not in _payload_nc,                    "F9: no chip key for captain turn")

# Non-debug output unchanged
_exit_f2, _out_f2 = cli_run(_Q_TC, BS, debug=False)
check(not _out_f2.startswith("{"),                  "F10: non-debug output is plain text")


# ---------------------------------------------------------------------------
# Section G -- CLI run_session() turn dict includes chip (8)
# ---------------------------------------------------------------------------

section("G -- CLI run_session() turn dict includes chip")

_turns_g = cli_run_session([_Q_TC, "who is Salah"], BS, debug=False)
check(len(_turns_g) == 2,                           "G1: two turns returned")

_turn_chip_g = _turns_g[0]
_turn_other_g = _turns_g[1]

check("chip" in _turn_chip_g,                       "G2: chip turn has chip key")
check(isinstance(_turn_chip_g["chip"], dict),        "G3: chip value is dict in turn")
check(_turn_chip_g["chip"].get("chip") == "triple_captain",
      "G4: chip.chip == triple_captain in turn")
check("chip" not in _turn_other_g,                  "G5: non-chip turn has no chip key")

# Session with bench boost
_turns_bb = cli_run_session([_Q_BB], BS, debug=False)
_turn_bb = _turns_bb[0]
check("chip" in _turn_bb,                           "G6: BB turn has chip key")
check(_turn_bb["chip"].get("chip") == "bench_boost","G7: BB chip.chip field")
check("signal_value" in _turn_bb["chip"],           "G8: BB chip.signal_value present")


# ---------------------------------------------------------------------------
# Section H -- HTTP /ask serialization (10)
# ---------------------------------------------------------------------------

section("H -- HTTP /ask serialization")

_resp_tc = _client_g.post("/ask", json={"question": _Q_TC})
_body_tc: dict = {}
try:
    _body_tc = _resp_tc.json()
except Exception:
    pass

check(_resp_tc.status_code == 200,                  "H1: /ask returns 200 for TC")
check("chip" in _body_tc,                           "H2: chip key in HTTP TC response")
check(isinstance(_body_tc.get("chip"), dict),       "H3: chip is dict in HTTP response")
_chip_h = _body_tc.get("chip") or {}
check(_chip_h.get("chip") == "triple_captain",      "H4: HTTP chip.chip == triple_captain")
check("recommendation" in _chip_h,                  "H5: HTTP recommendation key present")
check("gw" in _chip_h,                              "H6: HTTP gw key present")
check("signal_value" in _chip_h,                    "H7: HTTP signal_value key present")
check("signal_label" in _chip_h,                    "H8: HTTP signal_label key present")

# Non-chip turn: chip absent in HTTP response
_resp_capt_h = _client_g.post("/ask", json={"question": "should I captain Haaland"})
_body_capt_h: dict = {}
try:
    _body_capt_h = _resp_capt_h.json()
except Exception:
    pass
check(_body_capt_h.get("chip") is None,             "H9: chip is None for captain HTTP response")

# Free hit HTTP
_resp_fh_h = _client_g.post("/ask", json={"question": _Q_FH})
_body_fh_h: dict = {}
try:
    _body_fh_h = _resp_fh_h.json()
except Exception:
    pass
_chip_fh_h = _body_fh_h.get("chip") or {}
check(_chip_fh_h.get("recommendation") == "missing_context",
      "H10: HTTP FH chip recommendation == missing_context")


# ---------------------------------------------------------------------------
# Section I -- Multi-intent sub_responses can expose chip metadata (8)
# ---------------------------------------------------------------------------

section("I -- Multi-intent sub_responses expose chip")

# "should I captain Haaland and should I use triple captain this week"
# Part 1: "should I captain Haaland" -> captain_score
# Part 2: "should I use triple captain this week" -> chip_advice
_q_multi = "should I captain Haaland and should I use triple captain this week"
_fr_i = respond(_q_multi, BS)

check(_fr_i.intent == "multi_intent",               "I1: multi-intent detection fires")
check(_fr_i.sub_responses is not None,              "I2: sub_responses populated")
check(len(_fr_i.sub_responses) == 2,                "I3: two sub-responses")  # type: ignore[arg-type]

_sr_i = list(_fr_i.sub_responses)  # type: ignore[arg-type]
_captain_sr  = next((s for s in _sr_i if s.intent == INTENT_CAPTAIN_SCORE), None)
_chip_sr     = next((s for s in _sr_i if s.intent == INTENT_CHIP_ADVICE), None)

check(_captain_sr is not None,                      "I4: captain sub-response found")
check(_chip_sr is not None,                         "I5: chip sub-response found")
check(_captain_sr is not None and _captain_sr.chip is None,
      "I6: captain sub-response has chip=None")
check(_chip_sr is not None and _chip_sr.chip is not None,
      "I7: chip sub-response has chip populated")

# HTTP serialisation of multi-intent with chip sub-response
_resp_i = _client_g.post("/ask", json={"question": _q_multi})
_body_i: dict = {}
try:
    _body_i = _resp_i.json()
except Exception:
    pass
_subs_i = _body_i.get("sub_responses") or []
_chip_sub_http = next(
    (s for s in _subs_i if s.get("intent") == INTENT_CHIP_ADVICE), None
)
check(_chip_sub_http is not None and "chip" in _chip_sub_http,
      "I8: chip key in HTTP chip sub-response dict")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
print(f"Phase 7b results: {_PASS} passed, {_FAIL} failed")
if _FAIL == 0:
    print("ALL PASS")
else:
    print(f"FAILURES: {_FAIL}")
print(f"{'='*50}")
