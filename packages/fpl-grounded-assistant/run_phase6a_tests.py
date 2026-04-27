"""
run_phase6a_tests.py
====================
Phase 6a: Deterministic Transfer Advice -- test suite.

Target: ~115 assertions across 8 sections.

Sections
--------
A  Routing -- _try_route_transfer() and route() dispatch (20)
B  Transfer engine unit tests -- get_transfer_advice() (24)
C  Dispatcher integration -- dispatch() with transfer_advice (16)
D  Full stack -- respond() and final_text (12)
E  CLI integration -- run() and run_session() (14)
F  HTTP integration -- POST /ask (10)
G  Regression -- existing intents unchanged (12)
H  Validation corpus -- 2 Phase 6a scenarios present and well-formed (7)
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
    get_transfer_advice,
    INTENT_TRANSFER_ADVICE,
    STANDARD_BOOTSTRAP,
    dispatch,
    respond,
)
from fpl_grounded_assistant.dispatcher import (
    INTENT_CAPTAIN_SCORE, INTENT_COMPARE_PLAYERS,
    OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS, OUTCOME_UNSUPPORTED_INTENT,
    SUPPORTED_INTENTS, INTENT_MANIFEST,
)
from fpl_grounded_assistant.router import route
from fpl_grounded_assistant.transfer_advisor import (
    _derive_scoring_inputs,
    _build_transfer_reasons,
    _TRANSFER_THRESHOLD_STRONG,
)
from fpl_cli import run as cli_run, run_session as cli_run_session
import fpl_server
from fastapi.testclient import TestClient
from validation_corpus import VALIDATION_SCENARIOS, SCENARIO_BY_ID


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
PHASE6A_IDS = ["transfer_advice_direct", "transfer_advice_not_found"]


# ---------------------------------------------------------------------------
# Section A -- Routing (20)
# ---------------------------------------------------------------------------

section("A -- Routing")

# A1: "should I sell X for Y" patterns
r_a1 = route("should I sell Saka for Salah")
check(r_a1 is not None, "A1: 'should I sell Saka for Salah' routes")
check(r_a1 is not None and r_a1.tool_name == "get_transfer_advice",
      "A1b: tool_name == 'get_transfer_advice'")
check(r_a1 is not None and r_a1.tool_args.get("query_out") == "Saka",
      "A1c: query_out == 'Saka'")
check(r_a1 is not None and r_a1.tool_args.get("query_in") == "Salah",
      "A1d: query_in == 'Salah'")

# A2: "should I transfer out X for Y"
r_a2 = route("should I transfer out Bruno for Foden")
check(r_a2 is not None and r_a2.tool_name == "get_transfer_advice",
      "A2: 'should I transfer out Bruno for Foden' routes to transfer_advice")
check(r_a2 is not None and r_a2.tool_args.get("query_out") == "Bruno",
      "A2b: query_out == 'Bruno'")
check(r_a2 is not None and r_a2.tool_args.get("query_in") == "Foden",
      "A2c: query_in == 'Foden'")

# A3: bare "sell X for Y"
r_a3 = route("sell Saka for Haaland")
check(r_a3 is not None and r_a3.tool_name == "get_transfer_advice",
      "A3: 'sell Saka for Haaland' routes")
check(r_a3 is not None and r_a3.tool_args.get("query_out") == "Saka",
      "A3b: query_out == 'Saka'")
check(r_a3 is not None and r_a3.tool_args.get("query_in") == "Haaland",
      "A3c: query_in == 'Haaland'")

# A4: "swap X for Y"
r_a4 = route("swap Saka for Salah")
check(r_a4 is not None and r_a4.tool_name == "get_transfer_advice",
      "A4: 'swap Saka for Salah' routes")

# A5: "replace X with Y"
r_a5 = route("replace Saka with Salah")
check(r_a5 is not None and r_a5.tool_name == "get_transfer_advice",
      "A5: 'replace Saka with Salah' routes")
check(r_a5 is not None and r_a5.tool_args.get("query_out") == "Saka",
      "A5b: query_out 'Saka' from 'replace X with Y'")
check(r_a5 is not None and r_a5.tool_args.get("query_in") == "Salah",
      "A5c: query_in 'Salah' from 'replace X with Y'")

# A6: "transfer out X for Y"
r_a6 = route("transfer out Saka for Haaland")
check(r_a6 is not None and r_a6.tool_name == "get_transfer_advice",
      "A6: 'transfer out Saka for Haaland' routes")

# A7: question-mark stripped from player_in
r_a7 = route("should I sell Saka for Salah?")
check(r_a7 is not None and r_a7.tool_args.get("query_in") in ("Salah", "Salah?"),
      "A7: trailing '?' stripped from query_in")

# A8: no false match on captain score
r_a8 = route("should I captain Salah")
check(r_a8 is not None and r_a8.tool_name == "get_captain_score",
      "A8: 'should I captain' does NOT route to transfer")

# A9: no false match on comparison
r_a9 = route("compare Haaland and Salah")
check(r_a9 is not None and r_a9.tool_name == "compare_players",
      "A9: 'compare X and Y' still routes to compare_players")


# ---------------------------------------------------------------------------
# Section B -- Transfer engine unit tests (24)
# ---------------------------------------------------------------------------

section("B -- Transfer engine unit tests")

# B1: happy path — transfer_in recommendation
result_b1 = get_transfer_advice("Saka", "Salah", BS)
check(result_b1["status"] == "ok", "B1: get_transfer_advice happy path status ok")
check(result_b1["query_out"] == "Saka", "B1b: query_out preserved")
check(result_b1["query_in"] == "Salah", "B1c: query_in preserved")
check("player_out" in result_b1, "B1d: player_out present")
check("player_in" in result_b1, "B1e: player_in present")
check(isinstance(result_b1.get("score_delta"), (int, float)), "B1f: score_delta is numeric")
check(isinstance(result_b1.get("price_delta"), int), "B1g: price_delta is int (tenths of £)")
check(result_b1.get("recommendation") in ("transfer_in", "marginal_transfer_in", "hold"),
      "B1h: recommendation in valid vocab")
check(isinstance(result_b1.get("transfer_reasons"), list), "B1i: transfer_reasons is list")
check(isinstance(result_b1.get("recommendation_text"), str), "B1j: recommendation_text is str")
check(len(result_b1.get("recommendation_text", "")) > 10, "B1k: recommendation_text non-empty")

# B2: player_out dict structure
po = result_b1.get("player_out", {})
check("web_name" in po, "B2: player_out.web_name present")
check("captain_score" in po, "B2b: player_out.captain_score present")
check("tier" in po, "B2c: player_out.tier present")
check("now_cost" in po, "B2d: player_out.now_cost present")
check("cost_m" in po, "B2e: player_out.cost_m present")
check(isinstance(po.get("now_cost"), int), "B2f: now_cost is int")

# B3: transfer_in recommendation when player_in clearly better
# Salah (score ~61) vs Saka (score ~36) — big gap → transfer_in
check(result_b1.get("recommendation") == "transfer_in",
      "B3: Salah > Saka by large margin -> transfer_in")
check(float(result_b1.get("score_delta", 0)) > _TRANSFER_THRESHOLD_STRONG,
      "B3b: score_delta > _TRANSFER_THRESHOLD_STRONG for transfer_in")
check("Transfer in Salah" in result_b1.get("recommendation_text", ""),
      "B3c: recommendation_text mentions 'Transfer in Salah'")

# B4: hold recommendation when player_out better
result_b4 = get_transfer_advice("Salah", "De Bruyne", BS)
check(result_b4["status"] == "ok", "B4: hold path status ok")
check(result_b4.get("recommendation") == "hold",
      "B4b: selling Salah for De Bruyne -> hold")
check(float(result_b4.get("score_delta", 0)) <= 0,
      "B4c: score_delta <= 0 for hold")
check("Hold Salah" in result_b4.get("recommendation_text", ""),
      "B4d: recommendation_text mentions 'Hold Salah'")

# B5: not_found for unknown player
result_b5 = get_transfer_advice("Saka", "UnknownXYZPlayer", BS)
check(result_b5["status"] == "not_found", "B5: not_found when player_in unknown")
check(result_b5.get("error_player") == "UnknownXYZPlayer", "B5b: error_player preserved")
check("query_out" in result_b5, "B5c: query_out in error result")
check("query_in" in result_b5, "B5d: query_in in error result")


# ---------------------------------------------------------------------------
# Section C -- Dispatcher integration (16)
# ---------------------------------------------------------------------------

section("C -- Dispatcher integration")

# C1: dispatch routes to transfer_advice intent
dr_c1 = dispatch("should I sell Saka for Salah", BS)
check(dr_c1.intent == INTENT_TRANSFER_ADVICE, "C1: dispatch intent == transfer_advice")
check(dr_c1.outcome == OUTCOME_OK, "C1b: dispatch outcome ok")
check(dr_c1.selected_tool == "get_transfer_advice", "C1c: selected_tool correct")
check(dr_c1.outcome != OUTCOME_UNSUPPORTED_INTENT, "C1d: outcome is not unsupported for transfer_advice")

# C2: answer_text populated correctly
check(len(dr_c1.answer_text) > 10, "C2: answer_text non-empty")
check("Recommendation" in dr_c1.answer_text or "Marginal" in dr_c1.answer_text,
      "C2b: answer_text contains recommendation word")

# C3: not_found outcome
dr_c3 = dispatch("should I sell Saka for UnknownXYZ", BS)
check(dr_c3.intent == INTENT_TRANSFER_ADVICE, "C3: intent still transfer_advice on not_found")
check(dr_c3.outcome == OUTCOME_NOT_FOUND, "C3b: outcome not_found")
check(dr_c3.outcome != OUTCOME_UNSUPPORTED_INTENT, "C3c: outcome is not unsupported even on not_found")

# C4: multiple routing patterns all resolve to transfer_advice
for q_c4 in ["sell Haaland for Salah", "transfer out Saka for Haaland",
             "swap Saka for Salah", "replace Saka with Salah"]:
    dr = dispatch(q_c4, BS)
    check(dr.intent == INTENT_TRANSFER_ADVICE, f"C4: '{q_c4}' -> transfer_advice")

# C5: INTENT_TRANSFER_ADVICE in SUPPORTED_INTENTS
check(INTENT_TRANSFER_ADVICE in SUPPORTED_INTENTS, "C5: INTENT_TRANSFER_ADVICE in SUPPORTED_INTENTS")
check(INTENT_TRANSFER_ADVICE in INTENT_MANIFEST, "C5b: INTENT_TRANSFER_ADVICE in INTENT_MANIFEST")

# C6: raw_output has expected structure on ok
raw = dr_c1.raw_output
check(raw.get("status") == "ok", "C6: raw_output.status == ok")
check("score_delta" in raw, "C6b: raw_output has score_delta")
check("recommendation" in raw, "C6c: raw_output has recommendation")


# ---------------------------------------------------------------------------
# Section D -- Full stack via respond() (12)
# ---------------------------------------------------------------------------

section("D -- Full stack via respond()")

# D1: respond() returns correct FinalResponse for transfer_advice
fr_d1 = respond("should I sell Saka for Salah", BS, include_debug=True)
check(fr_d1.intent == INTENT_TRANSFER_ADVICE, "D1: respond() intent == transfer_advice")
check(fr_d1.outcome == OUTCOME_OK, "D1b: respond() outcome ok")
check(fr_d1.supported is True, "D1c: respond() supported=True")
check(len(fr_d1.final_text) > 10, "D1d: final_text non-empty")
check("Recommendation" in fr_d1.final_text or "Marginal" in fr_d1.final_text,
      "D1e: final_text contains recommendation")
check(fr_d1.comparison is None, "D1f: comparison is None for transfer_advice turn")
check(fr_d1.captain is None, "D1g: captain is None for transfer_advice turn")
check(fr_d1.captain_ranking is None, "D1h: captain_ranking is None for transfer_advice turn")

# D2: not_found flows through correctly
fr_d2 = respond("should I sell Saka for UnknownXYZ", BS)
check(fr_d2.intent == INTENT_TRANSFER_ADVICE, "D2: not_found intent still transfer_advice")
check(fr_d2.outcome == OUTCOME_NOT_FOUND, "D2b: not_found outcome")
check(fr_d2.supported is True, "D2c: not_found still supported=True")
check(len(fr_d2.final_text) > 0, "D2d: not_found final_text non-empty")

# D3: respond() never raises
try:
    fr_d3 = respond("should I sell Saka for Salah", BS)
    check(True, "D3: respond() does not raise")
except Exception as exc:
    check(False, f"D3: respond() raised: {exc}")
check(isinstance(fr_d3.final_text, str), "D3b: final_text is always str")


# ---------------------------------------------------------------------------
# Section E -- CLI integration (14)
# ---------------------------------------------------------------------------

section("E -- CLI integration")

# E1: cli_run happy path
exit_e1, out_e1 = cli_run("should I sell Saka for Salah", BS)
check(exit_e1 == 0, "E1: cli_run exit_code 0 (supported)")
check("Recommendation" in out_e1 or "Marginal" in out_e1,
      "E1b: cli_run plain-text contains recommendation")

# E2: cli_run debug=True
exit_e2, out_e2 = cli_run("should I sell Saka for Salah", BS, debug=True)
check(exit_e2 == 0, "E2: cli_run debug exit_code 0")
body_e2: dict = {}
try:
    body_e2 = json.loads(out_e2)
except Exception:
    pass
check(body_e2.get("intent") == "transfer_advice", "E2b: cli debug intent == transfer_advice")
check(body_e2.get("outcome") == "ok", "E2c: cli debug outcome ok")
check(body_e2.get("supported") is True, "E2d: cli debug supported=True")
check(body_e2.get("comparison") is None, "E2e: cli debug comparison absent for transfer turn")
check(body_e2.get("captain") is None, "E2f: cli debug captain absent for transfer turn")

# E3: cli_run not_found -- exit_code 0 because not_found is supported=True
exit_e3, out_e3 = cli_run("should I sell Saka for UnknownXYZ", BS)
check(exit_e3 == 0, "E3: not_found is supported=True -> exit_code 0")

# E4: run_session with transfer question
turns_e4 = cli_run_session(["should I sell Saka for Salah"], BS, debug=True)
last_e4 = turns_e4[-1] if turns_e4 else {}
check(last_e4.get("intent") == "transfer_advice", "E4: run_session transfer intent")
check(last_e4.get("outcome") == "ok", "E4b: run_session transfer outcome ok")
check(last_e4.get("supported") is True, "E4c: run_session supported=True")


# ---------------------------------------------------------------------------
# Section F -- HTTP integration (10)
# ---------------------------------------------------------------------------

section("F -- HTTP integration")

fpl_server._init_bootstrap(BS)
client_f = TestClient(fpl_server.app, raise_server_exceptions=True)

# F1: POST /ask happy path
resp_f1 = client_f.post("/ask", json={"question": "should I sell Saka for Salah"})
check(resp_f1.status_code == 200, "F1: /ask status 200")
body_f1: dict = {}
try:
    body_f1 = resp_f1.json()
except Exception:
    pass
check(body_f1.get("intent") == "transfer_advice", "F1b: /ask intent == transfer_advice")
check(body_f1.get("outcome") == "ok", "F1c: /ask outcome ok")
check(body_f1.get("supported") is True, "F1d: /ask supported=True")
check(len(body_f1.get("final_text", "")) > 10, "F1e: /ask final_text non-empty")
check(body_f1.get("comparison") is None, "F1f: comparison absent for transfer turn")
check(body_f1.get("captain") is None, "F1g: captain absent for transfer turn")
check(body_f1.get("captain_ranking") is None, "F1h: captain_ranking absent for transfer turn")

# F2: session endpoint
fpl_server._clear_sessions()
sess_r = client_f.post("/session")
sid = sess_r.json()["session_id"]
resp_f2 = client_f.post(f"/session/{sid}/ask",
                         json={"question": "should I sell Saka for Salah"})
client_f.delete(f"/session/{sid}")
body_f2: dict = {}
try:
    body_f2 = resp_f2.json()
except Exception:
    pass
check(resp_f2.status_code == 200, "F2: session /ask status 200")
check(body_f2.get("intent") == "transfer_advice", "F2b: session intent == transfer_advice")


# ---------------------------------------------------------------------------
# Section G -- Regression: existing intents unchanged (12)
# ---------------------------------------------------------------------------

section("G -- Regression: existing intents unchanged")

REGRESSION_CASES = [
    ("should I captain Salah",        "captain_score",    OUTCOME_OK),
    ("compare Haaland and Salah",     "compare_players",  OUTCOME_OK),
    ("who is Salah",                  "player_resolve",   OUTCOME_OK),
    ("tell me about Saka",            "player_summary",   OUTCOME_OK),
]

for q_g, exp_intent, exp_outcome in REGRESSION_CASES:
    dr_g = dispatch(q_g, BS)
    check(dr_g.intent == exp_intent, f"G: '{q_g}' intent unchanged ({exp_intent})")
    check(dr_g.outcome == exp_outcome, f"G: '{q_g}' outcome unchanged ({exp_outcome})")
    check(dr_g.intent != INTENT_TRANSFER_ADVICE,
          f"G: '{q_g}' NOT routed to transfer_advice")


# ---------------------------------------------------------------------------
# Section H -- Validation corpus (7)
# ---------------------------------------------------------------------------

section("H -- Validation corpus")

# H1: 2 new scenarios present
all_ids = [s.id for s in VALIDATION_SCENARIOS]
for sid in PHASE6A_IDS:
    check(sid in all_ids, f"H1: scenario '{sid}' in corpus")

# H2: families set to "transfer"
for sid in PHASE6A_IDS:
    s = SCENARIO_BY_ID.get(sid)
    if s:
        check(s.family == "transfer", f"H2: '{sid}' family == 'transfer'")

# H3: correct expected_intent and surfaces
s_direct = SCENARIO_BY_ID.get("transfer_advice_direct")
s_nf     = SCENARIO_BY_ID.get("transfer_advice_not_found")
if s_direct:
    check(s_direct.expected_intent == "transfer_advice",
          "H3: transfer_advice_direct expected_intent")
    check(s_direct.expected_outcome == "ok",
          "H3b: transfer_advice_direct expected_outcome ok")
    check("cli" in s_direct.surfaces and "http" in s_direct.surfaces,
          "H3c: transfer_advice_direct surfaces include cli + http")
if s_nf:
    check(s_nf.expected_intent == "transfer_advice",
          "H4: transfer_advice_not_found expected_intent")
    check(s_nf.expected_outcome == "not_found",
          "H4b: transfer_advice_not_found expected_outcome not_found")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*50}")
print(f"Phase 6a: {_PASS}/{total} PASS")
if _FAIL:
    print(f"          {_FAIL} FAIL")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
