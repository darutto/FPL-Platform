"""
run_phase6b_tests.py
====================
Phase 6b: Deterministic Chip Advice -- test suite.

Target: ~120 assertions across 8 sections.

Sections
--------
A  Routing -- _try_route_chip() and route() dispatch (22)
B  Chip engine unit tests -- get_chip_advice() per chip (28)
C  Dispatcher integration -- dispatch() with chip_advice (14)
D  Full stack -- respond() and final_text (12)
E  CLI integration -- run() and run_session() (14)
F  HTTP integration -- POST /ask (10)
G  Regression -- existing intents unchanged (12)
H  Validation corpus -- 3 Phase 6b scenarios present and well-formed (10)
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
    get_chip_advice,
    INTENT_CHIP_ADVICE,
    STANDARD_BOOTSTRAP,
    dispatch,
    respond,
    CHIP_TRIPLE_CAPTAIN,
    CHIP_WILDCARD,
    CHIP_BENCH_BOOST,
    CHIP_FREE_HIT,
    SUPPORTED_CHIPS,
    _TC_FAVORABLE_THRESHOLD,
    _TC_MARGINAL_THRESHOLD,
    _WC_EARLY_CUTOFF,
    _WC_LATE_CUTOFF,
    _BB_FAVORABLE_FDR,
    _BB_MARGINAL_FDR,
)
from fpl_grounded_assistant.dispatcher import (
    INTENT_CAPTAIN_SCORE, INTENT_COMPARE_PLAYERS, INTENT_TRANSFER_ADVICE,
    INTENT_CURRENT_GAMEWEEK,
    OUTCOME_OK, OUTCOME_UNSUPPORTED_INTENT,
    SUPPORTED_INTENTS, INTENT_MANIFEST,
)
from fpl_grounded_assistant.router import route
from fpl_grounded_assistant.router import _try_route_chip
from fpl_grounded_assistant.chip_advisor import (
    _get_current_gameweek,
    _score_outfield_players,
    _advise_triple_captain,
    _advise_wildcard,
    _advise_bench_boost,
    _advise_free_hit,
    SUPPORTED_CHIPS as _CHIP_SET,
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
PHASE6B_IDS = ["chip_advice_tc", "chip_advice_wc", "chip_advice_fh"]

_VALID_RECOMMENDATIONS = frozenset({
    "conditions_favorable",
    "conditions_marginal",
    "conditions_unfavorable",
    "missing_context",
})


# ---------------------------------------------------------------------------
# Section A -- Routing (22)
# ---------------------------------------------------------------------------

section("A -- Routing")

# A1: chip keywords + advisory phrases route to chip_advice
rr_a1 = _try_route_chip("should i use triple captain this week")
check(rr_a1 is not None, "A1: triple captain routes")
check(rr_a1 is not None and rr_a1.tool_name == "get_chip_advice", "A1b: tool_name correct")
check(rr_a1 is not None and rr_a1.tool_args.get("chip") == "triple_captain", "A1c: chip=triple_captain")

rr_a2 = _try_route_chip("should i wildcard this week")
check(rr_a2 is not None and rr_a2.tool_args.get("chip") == "wildcard", "A2: wildcard routes")

rr_a3 = _try_route_chip("should i bench boost now")
check(rr_a3 is not None and rr_a3.tool_args.get("chip") == "bench_boost", "A3: bench boost routes")

rr_a4 = _try_route_chip("should i free hit this gameweek")
check(rr_a4 is not None and rr_a4.tool_args.get("chip") == "free_hit", "A4: free hit routes")

# A5: advisory phrase variants
for phrase, label in [
    ("is this a good week for bench boost",   "A5a: is this a good week for"),
    ("wildcard this week",                     "A5b: chip this week"),
    ("is now a good time to use triple captain", "A5c: is now a good time"),
    ("bench boost worth using this gameweek",  "A5d: worth using"),
    ("when should i use my wildcard",          "A5e: when should i"),
]:
    rr = _try_route_chip(phrase)
    check(rr is not None, label)

# A6: chip keyword without advisory phrase does NOT route (avoids false matches)
rr_a6 = _try_route_chip("triple captain is a powerful chip")
check(rr_a6 is None, "A6: chip mention without advisory phrase does not route")

rr_a7 = _try_route_chip("wildcard info")
check(rr_a7 is None, "A7: bare chip mention without advisory phrase does not route")

# A8: non-chip questions do not route
check(_try_route_chip("should i captain haaland") is None, "A8: captain question not chip")
check(_try_route_chip("what gameweek is it") is None, "A9: gameweek question not chip")
check(_try_route_chip("compare haaland and salah") is None, "A10: comparison not chip")

# A11: route() level -- chip precedes gameweek
rr_a11 = route("should I free hit this gameweek")
check(rr_a11 is not None, "A11: free hit this gameweek routes")
check(rr_a11 is not None and rr_a11.tool_name == "get_chip_advice", "A11b: routes to chip not gameweek")
check(rr_a11 is not None and rr_a11.tool_args.get("chip") == "free_hit", "A11c: chip=free_hit")

# A12: route() -- gameweek question still routes to gameweek
rr_a12 = route("what gameweek is it")
check(rr_a12 is not None and rr_a12.tool_name == "get_current_gameweek", "A12: gameweek question still works")


# ---------------------------------------------------------------------------
# Section B -- Chip engine unit tests (28)
# ---------------------------------------------------------------------------

section("B -- Chip engine unit tests")

# B1: SUPPORTED_CHIPS constants
check(CHIP_TRIPLE_CAPTAIN in _CHIP_SET, "B1: triple_captain in SUPPORTED_CHIPS")
check(CHIP_WILDCARD in _CHIP_SET, "B1b: wildcard in SUPPORTED_CHIPS")
check(CHIP_BENCH_BOOST in _CHIP_SET, "B1c: bench_boost in SUPPORTED_CHIPS")
check(CHIP_FREE_HIT in _CHIP_SET, "B1d: free_hit in SUPPORTED_CHIPS")
check(len(_CHIP_SET) == 4, "B1e: exactly 4 supported chips")

# B2: _get_current_gameweek
gw = _get_current_gameweek(BS)
check(gw == 28, "B2: current GW is 28 in STANDARD_BOOTSTRAP")
check(_get_current_gameweek({"events": []}) is None, "B2b: no events → None")
check(_get_current_gameweek({}) is None, "B2c: empty bootstrap → None")

# B3: _score_outfield_players
ranked = _score_outfield_players(BS)
check(len(ranked) > 0, "B3: outfield players scored")
check(all("captain_score" in p for p in ranked), "B3b: all entries have captain_score")
check(all("tier" in p for p in ranked), "B3c: all entries have tier")
check(all("fdr" in p for p in ranked), "B3d: all entries have fdr")
check(ranked[0]["captain_score"] >= ranked[-1]["captain_score"], "B3e: sorted descending")

# B4: triple captain advice
tc = get_chip_advice(CHIP_TRIPLE_CAPTAIN, BS)
check(tc["status"] == "ok", "B4: TC status ok")
check(tc["chip"] == "triple_captain", "B4b: chip=triple_captain")
check(tc["current_gameweek"] == 28, "B4c: GW28")
check(tc["recommendation"] in _VALID_RECOMMENDATIONS, "B4d: valid recommendation")
check(len(tc["advice_text"]) > 20, "B4e: advice_text non-empty")
check("Triple captain" in tc["advice_text"], "B4f: advice_text mentions Triple captain")
check("signals" in tc and "top_player" in tc["signals"], "B4g: signals.top_player present")
check("top_captain_score" in tc["signals"], "B4h: signals.top_captain_score present")

# B5: wildcard advice
wc = get_chip_advice(CHIP_WILDCARD, BS)
check(wc["status"] == "ok", "B5: WC status ok")
check(wc["recommendation"] in _VALID_RECOMMENDATIONS, "B5b: valid recommendation")
check(wc["signals"]["current_gameweek"] == 28, "B5c: signals.current_gameweek correct")
check("Wildcard" in wc["advice_text"], "B5d: advice_text mentions Wildcard")
# GW28 is in viable window (7 <= 28 < 29)
check(wc["recommendation"] == "conditions_marginal", "B5e: GW28 -> conditions_marginal")

# B6: bench boost advice
bb = get_chip_advice(CHIP_BENCH_BOOST, BS)
check(bb["status"] == "ok", "B6: BB status ok")
check(bb["recommendation"] in _VALID_RECOMMENDATIONS, "B6b: valid recommendation")
check("Bench boost" in bb["advice_text"], "B6c: advice_text mentions Bench boost")
check("average_fdr_top10" in bb["signals"], "B6d: signals.average_fdr_top10 present")

# B7: free hit -- always missing_context
fh = get_chip_advice(CHIP_FREE_HIT, BS)
check(fh["status"] == "ok", "B7: FH status ok (intent recognised)")
check(fh["recommendation"] == "missing_context", "B7b: FH recommendation is missing_context")
check("Free hit" in fh["advice_text"], "B7c: advice_text mentions Free hit")
check("missing context" in fh["advice_text"], "B7d: advice_text says missing context")

# B8: unknown chip name falls through to not_found
unknown = get_chip_advice("triple_boost", BS)
check(unknown["status"] == "not_found", "B8: unknown chip → not_found")


# ---------------------------------------------------------------------------
# Section C -- Dispatcher integration (14)
# ---------------------------------------------------------------------------

section("C -- Dispatcher integration")

# C1: dispatch routes to chip_advice
dr_c1 = dispatch("should I use triple captain this week", BS)
check(dr_c1.intent == INTENT_CHIP_ADVICE, "C1: dispatch intent == chip_advice")
check(dr_c1.outcome == OUTCOME_OK, "C1b: dispatch outcome ok")
check(dr_c1.selected_tool == "get_chip_advice", "C1c: selected_tool correct")
check(dr_c1.outcome != OUTCOME_UNSUPPORTED_INTENT, "C1d: outcome is not unsupported")

# C2: answer_text populated
check(len(dr_c1.answer_text) > 10, "C2: answer_text non-empty")
check("Triple captain" in dr_c1.answer_text, "C2b: answer_text contains Triple captain")

# C3: raw_output has expected structure
raw = dr_c1.raw_output
check(raw.get("status") == "ok", "C3: raw_output.status == ok")
check("recommendation" in raw, "C3b: raw_output has recommendation")
check("chip" in raw, "C3c: raw_output has chip")
check("advice_text" in raw, "C3d: raw_output has advice_text")

# C4: multiple chip phrasings all resolve to chip_advice
for q_c4 in [
    "should I wildcard this week",
    "should I bench boost now",
    "should I free hit this week",
    "is this a good week for bench boost",
    "wildcard this week",
]:
    dr = dispatch(q_c4, BS)
    check(dr.intent == INTENT_CHIP_ADVICE, f"C4: '{q_c4}' -> chip_advice")

# C5: INTENT_CHIP_ADVICE in SUPPORTED_INTENTS and INTENT_MANIFEST
check(INTENT_CHIP_ADVICE in SUPPORTED_INTENTS, "C5: INTENT_CHIP_ADVICE in SUPPORTED_INTENTS")
check(INTENT_CHIP_ADVICE in INTENT_MANIFEST, "C5b: INTENT_CHIP_ADVICE in INTENT_MANIFEST")


# ---------------------------------------------------------------------------
# Section D -- Full stack via respond() (12)
# ---------------------------------------------------------------------------

section("D -- Full stack via respond()")

# D1: respond() for triple captain
fr_d1 = respond("should I use triple captain this week", BS, include_debug=True)
check(fr_d1.intent == INTENT_CHIP_ADVICE, "D1: respond() intent == chip_advice")
check(fr_d1.outcome == OUTCOME_OK, "D1b: respond() outcome ok")
check(fr_d1.supported is True, "D1c: respond() supported=True")
check(len(fr_d1.final_text) > 20, "D1d: final_text non-empty")
check("Triple captain" in fr_d1.final_text, "D1e: final_text mentions Triple captain")

# D2: respond() for wildcard
fr_d2 = respond("should I wildcard this week", BS)
check(fr_d2.intent == INTENT_CHIP_ADVICE, "D2: wildcard respond() chip_advice")
check(fr_d2.outcome == OUTCOME_OK, "D2b: wildcard outcome ok")
check("Wildcard" in fr_d2.final_text, "D2c: wildcard final_text")

# D3: respond() for free hit -- missing_context but still outcome=ok
fr_d3 = respond("should I free hit this week", BS)
check(fr_d3.intent == INTENT_CHIP_ADVICE, "D3: free hit chip_advice")
check(fr_d3.outcome == OUTCOME_OK, "D3b: free hit outcome ok (intent recognised)")
check("missing context" in fr_d3.final_text.lower(), "D3c: free hit final_text says missing context")

# D4: comparison, captain, captain_ranking are absent on chip turns
check(fr_d1.comparison is None, "D4: comparison absent on chip turn")
check(fr_d1.captain is None, "D4b: captain absent on chip turn")
check(fr_d1.captain_ranking is None, "D4c: captain_ranking absent on chip turn")


# ---------------------------------------------------------------------------
# Section E -- CLI integration (14)
# ---------------------------------------------------------------------------

section("E -- CLI integration")

# E1: cli_run for triple captain
exit_e1, out_e1 = cli_run("should I use triple captain this week", BS)
check(exit_e1 == 0, "E1: triple captain exit_code 0")
check("Triple captain" in out_e1, "E1b: triple captain output present")

# E2: cli_run debug mode for wildcard
exit_e2, out_e2 = cli_run("should I wildcard this week", BS, debug=True)
check(exit_e2 == 0, "E2: wildcard debug exit_code 0")
body_e2 = json.loads(out_e2)
check(body_e2.get("intent") == "chip_advice", "E2b: debug intent == chip_advice")
check(body_e2.get("outcome") == "ok", "E2c: debug outcome ok")
check(body_e2.get("comparison") is None, "E2d: comparison absent")
check(body_e2.get("captain") is None, "E2e: captain absent on chip turn")

# E3: cli_run for free hit -- exit_code 0 (supported=True even with missing_context)
exit_e3, out_e3 = cli_run("should I free hit this week", BS)
check(exit_e3 == 0, "E3: free hit exit_code 0 (supported=True)")
check("missing context" in out_e3.lower(), "E3b: free hit output says missing context")

# E4: cli_run for bench boost
exit_e4, out_e4 = cli_run("should I bench boost now", BS)
check(exit_e4 == 0, "E4: bench boost exit_code 0")
check("Bench boost" in out_e4, "E4b: bench boost output present")

# E5: run_session with chip question
turns_e5 = cli_run_session(
    ["should I wildcard this week", "should I triple captain this week"],
    BS,
    debug=True,
)
check(len(turns_e5) == 2, "E5: 2-turn session returns 2 turns")
check(turns_e5[0].get("intent") == "chip_advice", "E5b: turn 1 chip_advice")
check(turns_e5[1].get("intent") == "chip_advice", "E5c: turn 2 chip_advice")
check(turns_e5[0].get("outcome") == "ok", "E5d: turn 1 outcome ok")


# ---------------------------------------------------------------------------
# Section F -- HTTP integration (10)
# ---------------------------------------------------------------------------

section("F -- HTTP integration")

fpl_server._init_bootstrap(BS)
client_f = TestClient(fpl_server.app, raise_server_exceptions=True)

# F1: POST /ask triple captain
resp_f1 = client_f.post("/ask", json={"question": "should I use triple captain this week"})
check(resp_f1.status_code == 200, "F1: HTTP 200 for triple captain")
body_f1 = resp_f1.json()
check(body_f1.get("intent") == "chip_advice", "F1b: intent == chip_advice")
check(body_f1.get("outcome") == "ok", "F1c: outcome ok")
check(len(body_f1.get("final_text", "")) > 10, "F1d: final_text non-empty")
check("Triple captain" in body_f1.get("final_text", ""), "F1e: final_text contains Triple captain")

# F2: POST /ask wildcard
resp_f2 = client_f.post("/ask", json={"question": "should I wildcard this week"})
check(resp_f2.status_code == 200, "F2: HTTP 200 for wildcard")
body_f2 = resp_f2.json()
check(body_f2.get("intent") == "chip_advice", "F2b: wildcard intent chip_advice")
check(body_f2.get("outcome") == "ok", "F2c: wildcard outcome ok")

# F3: POST /ask free hit
resp_f3 = client_f.post("/ask", json={"question": "should I free hit this week"})
check(resp_f3.status_code == 200, "F3: HTTP 200 for free hit")
body_f3 = resp_f3.json()
check(body_f3.get("intent") == "chip_advice", "F3b: free hit intent chip_advice")
check(body_f3.get("outcome") == "ok", "F3c: free hit outcome ok (missing_context is still ok)")
check("missing context" in body_f3.get("final_text", "").lower(), "F3d: free hit final_text says missing context")

# F4: chip turns have no comparison/captain fields
check(body_f1.get("comparison") is None, "F4: comparison absent on chip turn")
check(body_f1.get("captain") is None, "F4b: captain absent on chip turn")


# ---------------------------------------------------------------------------
# Section G -- Regression: existing intents unchanged (12)
# ---------------------------------------------------------------------------

section("G -- Regression: existing intents unchanged")

for q, expected_intent in [
    ("should I captain Haaland",             INTENT_CAPTAIN_SCORE),
    ("who is Salah",                          "player_resolve"),
    ("tell me about Saka",                    "player_summary"),
    ("what gameweek is it",                   INTENT_CURRENT_GAMEWEEK),
    ("compare Haaland and Salah",             INTENT_COMPARE_PLAYERS),
    ("should I sell Saka for Salah",          INTENT_TRANSFER_ADVICE),
]:
    dr_g = dispatch(q, BS)
    check(dr_g.intent == expected_intent, f"G: '{q}' -> {expected_intent}")

# G7: non-chip questions with partial chip word don't false-positive
for q in [
    "who is the wildcard candidate",    # "wildcard" but no advisory
    "tell me about the free hit option", # "free hit" but no advisory
]:
    dr_g_fp = dispatch(q, BS)
    check(dr_g_fp.intent != INTENT_CHIP_ADVICE, f"G: '{q}' not routed to chip_advice")


# ---------------------------------------------------------------------------
# Section H -- Validation corpus (10)
# ---------------------------------------------------------------------------

section("H -- Validation corpus")

# H1: Phase 6b scenarios exist
for sid in PHASE6B_IDS:
    check(sid in SCENARIO_BY_ID, f"H1: corpus has '{sid}'")

# H2: scenarios are well-formed
for sid in PHASE6B_IDS:
    if sid not in SCENARIO_BY_ID:
        check(False, f"H2: '{sid}' missing -- skipping checks")
        continue
    s = SCENARIO_BY_ID[sid]
    check(s.family == "chip", f"H2: '{sid}' family == chip")
    check(s.expected_intent == "chip_advice", f"H2b: '{sid}' expected_intent == chip_advice")
    check(s.expected_outcome == "ok", f"H2c: '{sid}' expected_outcome == ok")
    check(s.expected_supported is True, f"H2d: '{sid}' expected_supported == True")
    check("cli" in s.surfaces and "http" in s.surfaces, f"H2e: '{sid}' includes cli+http surfaces")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
total = _PASS + _FAIL
if _FAIL == 0:
    print(f"Phase 6b: {_PASS}/{total} PASS")
    print("          All assertions passed.")
else:
    print(f"Phase 6b: {_PASS}/{total} PASS  ({_FAIL} FAILED)")
