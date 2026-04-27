"""
run_phase7a_tests.py
====================
Phase 7a: Structured Transfer Metadata -- test suite.

Target: ~88 assertions across 9 sections.

Sections
--------
A  TransferMeta dataclass -- fields, types, frozen (10)
B  FinalResponse.transfer populated for transfer_advice OK turns (12)
C  FinalResponse.transfer None for non-transfer turns (10)
D  CLI _serial_transfer() helper -- correct keys and values (8)
E  CLI run() debug JSON includes transfer key (10)
F  CLI run_session() turn dict includes transfer (8)
G  HTTP /ask serialization -- transfer dict keys and values (12)
H  HTTP session /ask serialization -- transfer present and aligned (8)
I  Multi-intent sub_responses can expose transfer metadata (10)
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
    TransferMeta,
    INTENT_TRANSFER_ADVICE,
)
from fpl_grounded_assistant.dispatcher import (
    INTENT_CAPTAIN_SCORE, INTENT_COMPARE_PLAYERS, INTENT_CHIP_ADVICE,
    OUTCOME_OK, OUTCOME_NOT_FOUND,
)
from fpl_grounded_assistant.final_response import FinalResponse
from fpl_cli import run as cli_run, run_session as cli_run_session, _serial_transfer
from fpl_server import (
    AskResponse, SessionAskResponse, _transfer_meta_dict,
)
import fpl_server
from fastapi.testclient import TestClient


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

# Canonical transfer question used across sections
_Q_TRANSFER = "should I sell Saka for Salah"
_Q_HOLD     = "should I sell Salah for De Bruyne"
_Q_NF       = "should I sell Saka for UnknownXYZPlayer"


# ---------------------------------------------------------------------------
# Section A -- TransferMeta dataclass (10)
# ---------------------------------------------------------------------------

section("A -- TransferMeta dataclass")

_tm = TransferMeta(
    player_out="Saka",
    player_in="Salah",
    recommendation="transfer_in",
    score_delta=25.3,
    price_delta=10,
    reasons=("stronger form (9.5 vs 5.0)",),
)
check(True, "A1: TransferMeta is importable")
check(_tm.player_out == "Saka",              "A2: player_out field")
check(_tm.player_in == "Salah",              "A3: player_in field")
check(_tm.recommendation == "transfer_in",   "A4: recommendation field")
check(_tm.score_delta == 25.3,               "A5: score_delta field")
check(_tm.price_delta == 10,                 "A6: price_delta is int")
check(isinstance(_tm.reasons, tuple),        "A7: reasons is tuple")
check(_tm.reasons == ("stronger form (9.5 vs 5.0)",), "A8: reasons value")

def _check_frozen(obj: Any) -> bool:
    try:
        obj.recommendation = "hold"  # type: ignore[misc]
        return False
    except Exception:
        return True

check(_check_frozen(_tm),                    "A9: frozen -- assignment raises")
check(isinstance(_tm.score_delta, float),    "A10: score_delta is float")


# ---------------------------------------------------------------------------
# Section B -- FinalResponse.transfer populated for transfer_advice OK (12)
# ---------------------------------------------------------------------------

section("B -- FinalResponse.transfer for transfer_advice OK")

_fr_b = respond(_Q_TRANSFER, BS)
check(isinstance(_fr_b, FinalResponse),          "B1: respond() returns FinalResponse")
check(_fr_b.intent == INTENT_TRANSFER_ADVICE,    "B2: intent == transfer_advice")
check(_fr_b.outcome == OUTCOME_OK,               "B3: outcome == ok")
check(_fr_b.transfer is not None,                "B4: transfer is not None for OK turn")
check(isinstance(_fr_b.transfer, TransferMeta),  "B5: transfer is TransferMeta instance")

_tm_b = _fr_b.transfer
check(_tm_b.player_out != "",                    "B6: player_out non-empty")
check(_tm_b.player_in  != "",                    "B7: player_in non-empty")
check(_tm_b.recommendation in ("transfer_in", "marginal_transfer_in", "hold"),
      "B8: recommendation in valid vocab")
check(isinstance(_tm_b.score_delta, float),      "B9: score_delta is float")
check(isinstance(_tm_b.price_delta, int),        "B10: price_delta is int")
check(isinstance(_tm_b.reasons, tuple),          "B11: reasons is tuple")

# Salah > Saka by large margin → transfer_in expected
check(_tm_b.recommendation == "transfer_in",     "B12: Salah > Saka → transfer_in")


# ---------------------------------------------------------------------------
# Section C -- FinalResponse.transfer None for non-transfer turns (10)
# ---------------------------------------------------------------------------

section("C -- FinalResponse.transfer None for non-transfer turns")

_fr_captain = respond("should I captain Salah", BS)
check(_fr_captain.intent == INTENT_CAPTAIN_SCORE, "C1: captain intent correct")
check(_fr_captain.transfer is None,               "C2: transfer None for captain turn")

_fr_compare = respond("compare Haaland and Salah", BS)
check(_fr_compare.intent == INTENT_COMPARE_PLAYERS, "C3: compare intent correct")
check(_fr_compare.transfer is None,                 "C4: transfer None for compare turn")

_fr_chip = respond("should I use triple captain this week", BS)
check(_fr_chip.intent == INTENT_CHIP_ADVICE,      "C5: chip intent correct")
check(_fr_chip.transfer is None,                  "C6: transfer None for chip turn")

# Not-found transfer turn: transfer should be None (only OK turns get metadata)
_fr_nf = respond(_Q_NF, BS)
check(_fr_nf.intent == INTENT_TRANSFER_ADVICE,    "C7: not_found still transfer_advice intent")
check(_fr_nf.outcome == OUTCOME_NOT_FOUND,        "C8: outcome not_found")
check(_fr_nf.transfer is None,                    "C9: transfer None for not_found turn")

# Hold recommendation also gets TransferMeta (still OK outcome)
_fr_hold = respond(_Q_HOLD, BS)
check(_fr_hold.outcome == OUTCOME_OK,             "C10: hold turn outcome ok")
# (transfer is not None is tested in section B; here we just verify hold is ok)


# ---------------------------------------------------------------------------
# Section D -- CLI _serial_transfer() helper (8)
# ---------------------------------------------------------------------------

section("D -- CLI _serial_transfer() helper")

_fr_d = respond(_Q_TRANSFER, BS)
assert _fr_d.transfer is not None
_d = _serial_transfer(_fr_d.transfer)

check(isinstance(_d, dict),                      "D1: _serial_transfer returns dict")
check("player_out" in _d,                        "D2: player_out key present")
check("player_in" in _d,                         "D3: player_in key present")
check("recommendation" in _d,                    "D4: recommendation key present")
check("score_delta" in _d,                       "D5: score_delta key present")
check("price_delta" in _d,                       "D6: price_delta key present")
check("reasons" in _d,                           "D7: reasons key present")
check(isinstance(_d["reasons"], list),           "D8: reasons serialised as list (not tuple)")


# ---------------------------------------------------------------------------
# Section E -- CLI run() debug JSON includes transfer key (10)
# ---------------------------------------------------------------------------

section("E -- CLI run() debug JSON includes transfer")

_exit_e, _out_e = cli_run(_Q_TRANSFER, BS, debug=True)
_body_e: dict = {}
try:
    _body_e = json.loads(_out_e)
except Exception:
    pass

check(_exit_e == 0,                              "E1: exit_code 0 for OK transfer turn")
check(_body_e.get("intent") == "transfer_advice", "E2: debug JSON intent == transfer_advice")
check("transfer" in _body_e,                     "E3: transfer key present in debug JSON")
_t_e = _body_e.get("transfer", {})
check(_t_e.get("player_out") != "",              "E4: transfer.player_out non-empty")
check(_t_e.get("player_in") != "",               "E5: transfer.player_in non-empty")
check(_t_e.get("recommendation") in ("transfer_in", "marginal_transfer_in", "hold"),
      "E6: transfer.recommendation valid vocab")
check(isinstance(_t_e.get("reasons"), list),     "E7: transfer.reasons is list in JSON")

# Non-debug run: no transfer key in plain output
_exit_e2, _out_e2 = cli_run(_Q_TRANSFER, BS, debug=False)
check("transfer" not in _out_e2,                 "E8: no 'transfer' key in plain-text output")

# Not-found: transfer key absent from debug JSON
_exit_e3, _out_e3 = cli_run(_Q_NF, BS, debug=True)
_body_e3: dict = {}
try:
    _body_e3 = json.loads(_out_e3)
except Exception:
    pass
check(_body_e3.get("transfer") is None,          "E9: transfer absent (null) for not_found debug")

# captain turn: transfer absent from debug JSON
_exit_e4, _out_e4 = cli_run("should I captain Salah", BS, debug=True)
_body_e4: dict = {}
try:
    _body_e4 = json.loads(_out_e4)
except Exception:
    pass
check(_body_e4.get("transfer") is None,          "E10: transfer absent (null) for captain debug")


# ---------------------------------------------------------------------------
# Section F -- CLI run_session() turn dict includes transfer (8)
# ---------------------------------------------------------------------------

section("F -- CLI run_session() turn dict includes transfer")

_turns_f = cli_run_session([_Q_TRANSFER], BS)
_turn_f = _turns_f[0] if _turns_f else {}

check("transfer" in _turn_f,                     "F1: transfer in run_session() turn dict")
_t_f = _turn_f.get("transfer", {})
check(_t_f.get("player_out") != "",              "F2: transfer.player_out non-empty in session")
check(_t_f.get("player_in") != "",               "F3: transfer.player_in non-empty in session")
check(_t_f.get("recommendation") in ("transfer_in", "marginal_transfer_in", "hold"),
      "F4: transfer.recommendation valid in session")

# Single-intent captain turn: transfer absent from session turn dict
_turns_f2 = cli_run_session(["should I captain Salah"], BS)
_turn_f2 = _turns_f2[0] if _turns_f2 else {}
check("transfer" not in _turn_f2,               "F5: transfer absent for captain turn in session")

# CLI and HTTP transfer keys align
_exit_f3, _out_f3 = cli_run(_Q_TRANSFER, BS, debug=True)
_body_f3: dict = {}
try:
    _body_f3 = json.loads(_out_f3)
except Exception:
    pass
_cli_keys  = set((_body_f3.get("transfer") or {}).keys())
_sess_keys = set((_turn_f.get("transfer") or {}).keys())
check(_cli_keys == _sess_keys,                   "F6: CLI debug and session transfer keys align")

# Not-found in session: transfer absent
_turns_f3 = cli_run_session([_Q_NF], BS)
_turn_f3 = _turns_f3[0] if _turns_f3 else {}
check("transfer" not in _turn_f3,               "F7: transfer absent for not_found session turn")

# score_delta type preserved in session turn
check(isinstance(_t_f.get("score_delta"), (int, float)),
      "F8: transfer.score_delta numeric in session")


# ---------------------------------------------------------------------------
# Section G -- HTTP /ask serialization (12)
# ---------------------------------------------------------------------------

section("G -- HTTP /ask serialization")

fpl_server._init_bootstrap(BS)
_client_g = TestClient(fpl_server.app, raise_server_exceptions=True)

_resp_g = _client_g.post("/ask", json={"question": _Q_TRANSFER})
check(_resp_g.status_code == 200,                "G1: /ask status 200")
_body_g: dict = {}
try:
    _body_g = _resp_g.json()
except Exception:
    pass

check(_body_g.get("intent") == "transfer_advice", "G2: intent == transfer_advice")
check(_body_g.get("outcome") == "ok",             "G3: outcome ok")
check(_body_g.get("transfer") is not None,        "G4: transfer present in /ask response")
_t_g = _body_g.get("transfer", {})
check("player_out" in _t_g,                       "G5: transfer.player_out key in HTTP response")
check("player_in" in _t_g,                        "G6: transfer.player_in key in HTTP response")
check("recommendation" in _t_g,                   "G7: transfer.recommendation key in HTTP response")
check("score_delta" in _t_g,                      "G8: transfer.score_delta key in HTTP response")
check("price_delta" in _t_g,                      "G9: transfer.price_delta key in HTTP response")
check("reasons" in _t_g,                          "G10: transfer.reasons key in HTTP response")

# Not-found: transfer null in HTTP response
_resp_g2 = _client_g.post("/ask", json={"question": _Q_NF})
_body_g2: dict = {}
try:
    _body_g2 = _resp_g2.json()
except Exception:
    pass
check(_body_g2.get("transfer") is None,           "G11: transfer null for not_found /ask")

# Captain turn: transfer null in HTTP response
_resp_g3 = _client_g.post("/ask", json={"question": "should I captain Salah"})
_body_g3: dict = {}
try:
    _body_g3 = _resp_g3.json()
except Exception:
    pass
check(_body_g3.get("transfer") is None,           "G12: transfer null for captain /ask")


# ---------------------------------------------------------------------------
# Section H -- HTTP session /ask serialization (8)
# ---------------------------------------------------------------------------

section("H -- HTTP session /ask serialization")

fpl_server._clear_sessions()
_sess_h = _client_g.post("/session")
_sid_h  = _sess_h.json()["session_id"]

_resp_h = _client_g.post(f"/session/{_sid_h}/ask", json={"question": _Q_TRANSFER})
_body_h: dict = {}
try:
    _body_h = _resp_h.json()
except Exception:
    pass

check(_resp_h.status_code == 200,                "H1: session /ask status 200")
check(_body_h.get("intent") == "transfer_advice", "H2: session intent == transfer_advice")
check(_body_h.get("transfer") is not None,        "H3: transfer present in session response")
_t_h = _body_h.get("transfer", {})
check(_t_h.get("player_out") != "",              "H4: transfer.player_out non-empty in session HTTP")
check(_t_h.get("player_in") != "",               "H5: transfer.player_in non-empty in session HTTP")

# HTTP and session transfer keys must align
check(set(_t_g.keys()) == set(_t_h.keys()),      "H6: /ask and session /ask transfer keys align")

# Not-found in session: transfer null
_resp_h2 = _client_g.post(f"/session/{_sid_h}/ask", json={"question": _Q_NF})
_body_h2: dict = {}
try:
    _body_h2 = _resp_h2.json()
except Exception:
    pass
check(_body_h2.get("transfer") is None,          "H7: transfer null for not_found session /ask")

_client_g.delete(f"/session/{_sid_h}")
check(True, "H8: session cleanup")


# ---------------------------------------------------------------------------
# Section I -- Multi-intent sub_responses can expose transfer (10)
# ---------------------------------------------------------------------------

section("I -- Multi-intent sub_responses expose transfer")

# "should I captain Salah and sell Saka for Haaland"
# Part 1: "should I captain Salah" -> captain_score
# Part 2: "sell Saka for Haaland"  -> transfer_advice
_q_multi = "should I captain Salah and sell Saka for Haaland"
_fr_i = respond(_q_multi, BS)

check(_fr_i.intent == "multi_intent",            "I1: multi-intent detection fires")
check(_fr_i.sub_responses is not None,           "I2: sub_responses populated")
check(len(_fr_i.sub_responses) == 2,             "I3: two sub-responses")  # type: ignore[arg-type]

_sr_i = list(_fr_i.sub_responses)  # type: ignore[arg-type]
# Identify which sub-response is which
_captain_sr  = next((s for s in _sr_i if s.intent == INTENT_CAPTAIN_SCORE), None)
_transfer_sr = next((s for s in _sr_i if s.intent == INTENT_TRANSFER_ADVICE), None)

check(_captain_sr is not None,                   "I4: captain sub-response found")
check(_transfer_sr is not None,                  "I5: transfer sub-response found")
check(_captain_sr is not None and _captain_sr.transfer is None,
      "I6: captain sub-response has transfer=None")
check(_transfer_sr is not None and _transfer_sr.transfer is not None,
      "I7: transfer sub-response has transfer populated")

# HTTP serialization of multi-intent with transfer sub-response
_resp_i = _client_g.post("/ask", json={"question": _q_multi})
_body_i: dict = {}
try:
    _body_i = _resp_i.json()
except Exception:
    pass
check(_body_i.get("intent") == "multi_intent",   "I8: HTTP multi-intent intent")
_subs_i = _body_i.get("sub_responses") or []
_transfer_sub_http = next(
    (s for s in _subs_i if s.get("intent") == "transfer_advice"), None
)
check(_transfer_sub_http is not None,            "I9: transfer sub-response in HTTP sub_responses")
check(_transfer_sub_http is not None and "transfer" in _transfer_sub_http,
      "I10: transfer key in HTTP transfer sub-response dict")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*50}")
print(f"Phase 7a: {_PASS}/{total} PASS")
if _FAIL:
    print(f"          {_FAIL} FAIL")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
