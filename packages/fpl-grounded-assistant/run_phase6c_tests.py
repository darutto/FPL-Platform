"""
run_phase6c_tests.py
====================
Phase 6c: Multi-Intent Orchestration — test suite.

Sections
--------
A  detect_multi_intent unit tests          (~22 assertions)
B  Split routing validation                (~14 assertions)
C  respond() multi-intent full stack       (~24 assertions)
D  CLI integration                         (~18 assertions)
E  HTTP integration                        (~18 assertions)
F  Session integration                     (~14 assertions)
G  Regression: single-intent unaffected   (~20 assertions)
H  Corpus                                  (~12 assertions)
                                          ─────────────────
                                          ~142 total

Usage
-----
    cd packages/fpl-grounded-assistant
    python run_phase6c_tests.py
"""
from __future__ import annotations

import json
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def check(condition: bool, label: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        print(f"  FAIL: {label}")


# ---------------------------------------------------------------------------
# Bootstrap fixture
# ---------------------------------------------------------------------------

sys.path.insert(0, ".")

from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    INTENT_MULTI_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_PLAYER_RESOLVE,
    INTENT_PLAYER_SUMMARY,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_CHIP_ADVICE,
    INTENT_UNSUPPORTED,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    detect_multi_intent,
    respond,
)
from fpl_grounded_assistant.router import route
from fpl_grounded_assistant.multi_intent import _MULTI_CONJUNCTION


# ---------------------------------------------------------------------------
# SECTION A — detect_multi_intent unit tests
# ---------------------------------------------------------------------------

print("\n=== A: detect_multi_intent unit tests ===")

# A1: Valid split — gameweek + player summary
r_a1 = detect_multi_intent("tell me about Salah and what gameweek is it")
check(r_a1 is not None, "A1: tell me about Salah and what gameweek is it -> not None")
check(isinstance(r_a1, list) and len(r_a1) == 2, "A1: returns list of 2")
if r_a1:
    check("Salah" in r_a1[0], "A1: part_a contains Salah")
    check("gameweek" in r_a1[1].lower(), "A1: part_b contains gameweek")

# A2: Valid split — captain score + player resolve
r_a2 = detect_multi_intent("should I captain Haaland and who is Saka")
check(r_a2 is not None, "A2: captain + resolve -> not None")
check(isinstance(r_a2, list) and len(r_a2) == 2, "A2: returns list of 2")

# A3: Valid split — player summary + player resolve
r_a3 = detect_multi_intent("give me a summary for Salah and who is Haaland")
check(r_a3 is not None, "A3: summary + resolve -> not None")

# A4: Valid split — case-insensitive conjunction
r_a4 = detect_multi_intent("WHO IS SALAH AND WHAT GAMEWEEK IS IT")
check(r_a4 is not None, "A4: uppercase AND -> not None")

# A5: Not a multi-intent — comparison should fall through
r_a5 = detect_multi_intent("compare Salah and Haaland")
check(r_a5 is None, "A5: compare Salah and Haaland -> None (comparison not split)")

# A6: Not a multi-intent — no 'and' at all
r_a6 = detect_multi_intent("who is Salah")
check(r_a6 is None, "A6: single-intent -> None")

# A7: Not a multi-intent — "sell X and bring in Y" (transfer connector)
r_a7 = detect_multi_intent("sell Saka and bring in Salah")
check(r_a7 is None, "A7: sell Saka and bring in Salah -> None (transfer, not multi)")

# A8: Not a multi-intent — "Haaland vs Salah" (no 'and')
r_a8 = detect_multi_intent("Haaland vs Salah")
check(r_a8 is None, "A8: vs-only comparison -> None")

# A9: Not a multi-intent — second part does not route
r_a9 = detect_multi_intent("who is Salah and is he fit?")
check(r_a9 is None, "A9: second part unroutable -> None")

# A10: Not a multi-intent — first part does not route
r_a10 = detect_multi_intent("what does FPL stand for and who is Salah")
check(r_a10 is None, "A10: first part unroutable -> None")

# A11: Trailing punctuation stripped
r_a11 = detect_multi_intent("who is Salah and what gameweek is it?")
check(r_a11 is not None, "A11: trailing ? stripped -> valid split")

# A12: Conjunction constant value
check(_MULTI_CONJUNCTION == " and ", "A12: _MULTI_CONJUNCTION == ' and '")


# ---------------------------------------------------------------------------
# SECTION B — Split routing validation
# ---------------------------------------------------------------------------

print("\n=== B: Split routing validation ===")

# B1: "tell me about Salah" routes as player_summary
b1 = route("tell me about Salah")
check(b1 is not None, "B1: 'tell me about Salah' routes")
check(b1 is not None and b1.tool_name == "get_player_summary", "B1: routes to get_player_summary")

# B2: "what gameweek is it" routes as current_gameweek
b2 = route("what gameweek is it")
check(b2 is not None, "B2: 'what gameweek is it' routes")
check(b2 is not None and b2.tool_name == "get_current_gameweek", "B2: routes to get_current_gameweek")

# B3: "should I captain Haaland" routes as captain_score
b3 = route("should I captain Haaland")
check(b3 is not None and b3.tool_name == "get_captain_score", "B3: captain half routes correctly")

# B4: "who is Saka" routes as player_resolve
b4 = route("who is Saka")
check(b4 is not None and b4.tool_name == "resolve_player", "B4: resolve half routes correctly")

# B5: "compare Salah" alone does NOT route (no two-player connector)
b5 = route("compare Salah")
check(b5 is None, "B5: 'compare Salah' alone -> None (not a full comparison)")

# B6: "Haaland" alone does NOT route
b6 = route("Haaland")
check(b6 is None, "B6: bare player name alone -> None")

# B7: "sell Saka" alone does NOT route as transfer (no connector)
b7 = route("sell Saka")
check(b7 is None, "B7: 'sell Saka' alone -> None (no transfer connector)")

# B8: Verify the full comparison still works after multi-intent is introduced
b8 = route("compare Salah and Haaland")
check(b8 is not None and b8.tool_name == "compare_players", "B8: full comparison still routes correctly")


# ---------------------------------------------------------------------------
# SECTION C — respond() multi-intent full stack
# ---------------------------------------------------------------------------

print("\n=== C: respond() multi-intent full stack ===")

BS = STANDARD_BOOTSTRAP

# C1: Basic multi-intent response shape
c1 = respond("tell me about Salah and what gameweek is it", BS)
check(c1.intent == INTENT_MULTI_INTENT, "C1: intent == multi_intent")
check(c1.outcome == OUTCOME_OK, "C1: outcome == ok")
check(c1.supported is True, "C1: supported == True")
check(c1.sub_responses is not None, "C1: sub_responses is not None")
check(len(c1.sub_responses) == 2, "C1: sub_responses has 2 entries")
check(bool(c1.final_text), "C1: final_text non-empty")

# C2: Sub-response intents correct
check(c1.sub_responses[0].intent == INTENT_PLAYER_SUMMARY,
      "C2: sub_responses[0].intent == player_summary")
check(c1.sub_responses[1].intent == INTENT_CURRENT_GAMEWEEK,
      "C2: sub_responses[1].intent == current_gameweek")

# C3: Sub-response outcomes correct
check(c1.sub_responses[0].outcome == OUTCOME_OK, "C3: sub_responses[0].outcome == ok")
check(c1.sub_responses[1].outcome == OUTCOME_OK, "C3: sub_responses[1].outcome == ok")

# C4: final_text contains both sub-response texts
check(c1.sub_responses[0].final_text in c1.final_text, "C4: part_a text in combined final_text")
check(c1.sub_responses[1].final_text in c1.final_text, "C4: part_b text in combined final_text")

# C5: Captain + resolve multi-intent
c5 = respond("should I captain Haaland and who is Saka", BS)
check(c5.intent == INTENT_MULTI_INTENT, "C5: intent == multi_intent")
check(c5.outcome == OUTCOME_OK, "C5: outcome == ok")
check(c5.sub_responses is not None and len(c5.sub_responses) == 2, "C5: sub_responses has 2 entries")
check(c5.sub_responses[0].intent == INTENT_CAPTAIN_SCORE,
      "C5: sub_responses[0].intent == captain_score")
check(c5.sub_responses[1].intent == INTENT_PLAYER_RESOLVE,
      "C5: sub_responses[1].intent == player_resolve")

# C6: Single-intent still returns sub_responses=None
c6 = respond("who is Salah", BS)
check(c6.sub_responses is None, "C6: single-intent sub_responses == None")
check(c6.intent == INTENT_PLAYER_RESOLVE, "C6: single-intent intent unchanged")

# C7: Comparison NOT split (falls through to single intent)
c7 = respond("compare Salah and Haaland", BS)
check(c7.intent == INTENT_COMPARE_PLAYERS, "C7: comparison not split -> compare_players")
check(c7.sub_responses is None, "C7: comparison sub_responses == None")

# C8: sub_responses debug field is None (not surfaced for sub-turns)
c8 = respond("tell me about Salah and what gameweek is it", BS, include_debug=True)
check(c8.sub_responses[0].debug is None, "C8: sub-response debug is None")
check(c8.sub_responses[1].debug is None, "C8: sub-response debug is None")

# C9: multi-intent review_passed = True when all sub-intents pass
check(c1.review_passed is True, "C9: review_passed True when all sub-intents pass")


# ---------------------------------------------------------------------------
# SECTION D — CLI integration
# ---------------------------------------------------------------------------

print("\n=== D: CLI integration ===")

sys.path.insert(0, ".")
from fpl_cli import run

# D1: run() non-debug multi-intent exits 0 (supported)
exit_d1, out_d1 = run("tell me about Salah and what gameweek is it", BS, debug=False)
check(exit_d1 == 0, "D1: multi-intent non-debug exit_code == 0")
check(isinstance(out_d1, str) and len(out_d1) > 0, "D1: non-debug output non-empty")

# D2: non-debug output is combined final_text (not JSON)
check(not out_d1.startswith("{"), "D2: non-debug output is not JSON")

# D3: run() debug multi-intent includes sub_responses
exit_d3, out_d3 = run("tell me about Salah and what gameweek is it", BS, debug=True)
check(exit_d3 == 0, "D3: multi-intent debug exit_code == 0")
payload_d3 = json.loads(out_d3)
check(payload_d3.get("intent") == "multi_intent", "D3: debug JSON intent == multi_intent")
check("sub_responses" in payload_d3, "D3: debug JSON contains sub_responses key")
check(isinstance(payload_d3["sub_responses"], list), "D3: sub_responses is a list")
check(len(payload_d3["sub_responses"]) == 2, "D3: sub_responses has 2 entries")

# D4: sub_responses entries have correct shape
sub0 = payload_d3["sub_responses"][0]
check("final_text" in sub0, "D4: sub_response[0] has final_text")
check("outcome" in sub0, "D4: sub_response[0] has outcome")
check("supported" in sub0, "D4: sub_response[0] has supported")
check("intent" in sub0, "D4: sub_response[0] has intent")

# D5: single-intent debug output has no sub_responses
exit_d5, out_d5 = run("who is Salah", BS, debug=True)
payload_d5 = json.loads(out_d5)
check("sub_responses" not in payload_d5, "D5: single-intent debug has no sub_responses key")

# D6: captain+resolve multi-intent debug sub_responses intents correct
exit_d6, out_d6 = run("should I captain Haaland and who is Saka", BS, debug=True)
payload_d6 = json.loads(out_d6)
check(payload_d6["sub_responses"][0]["intent"] == "captain_score",
      "D6: sub_responses[0] intent == captain_score")
check(payload_d6["sub_responses"][1]["intent"] == "player_resolve",
      "D6: sub_responses[1] intent == player_resolve")


# ---------------------------------------------------------------------------
# SECTION E — HTTP integration
# ---------------------------------------------------------------------------

print("\n=== E: HTTP integration ===")

from fastapi.testclient import TestClient
from fpl_server import app, _init_bootstrap, _clear_sessions

_init_bootstrap(BS)
client_http = TestClient(app)

# E1: POST /ask multi-intent returns 200 with intent=multi_intent
r_e1 = client_http.post("/ask", json={"question": "tell me about Salah and what gameweek is it"})
check(r_e1.status_code == 200, "E1: /ask multi-intent -> 200")
body_e1 = r_e1.json()
check(body_e1.get("intent") == "multi_intent", "E1: intent == multi_intent")
check(body_e1.get("outcome") == "ok", "E1: outcome == ok")
check(body_e1.get("supported") is True, "E1: supported == True")

# E2: sub_responses present in HTTP response
check("sub_responses" in body_e1, "E2: sub_responses key present in /ask response")
check(isinstance(body_e1["sub_responses"], list), "E2: sub_responses is a list")
check(len(body_e1["sub_responses"]) == 2, "E2: sub_responses has 2 entries")

# E3: sub_responses entries have correct shape
sub_e3_0 = body_e1["sub_responses"][0]
check("final_text" in sub_e3_0 and "outcome" in sub_e3_0
      and "supported" in sub_e3_0 and "intent" in sub_e3_0,
      "E3: sub_response[0] has all required fields")

# E4: single-intent /ask -> sub_responses is None
r_e4 = client_http.post("/ask", json={"question": "who is Salah"})
body_e4 = r_e4.json()
check(body_e4.get("sub_responses") is None, "E4: single-intent sub_responses == None in /ask")

# E5: comparison intent NOT split in HTTP
r_e5 = client_http.post("/ask", json={"question": "compare Salah and Haaland"})
body_e5 = r_e5.json()
check(body_e5.get("intent") == "compare_players", "E5: comparison not split in HTTP")
check(body_e5.get("sub_responses") is None, "E5: comparison sub_responses == None")

# E6: Session /ask multi-intent
_clear_sessions()
sess_e6 = client_http.post("/session").json()
sid_e6 = sess_e6["session_id"]
r_e6 = client_http.post(
    f"/session/{sid_e6}/ask",
    json={"question": "tell me about Salah and what gameweek is it"},
)
check(r_e6.status_code == 200, "E6: session /ask multi-intent -> 200")
body_e6 = r_e6.json()
check(body_e6.get("intent") == "multi_intent", "E6: session intent == multi_intent")
check(body_e6.get("sub_responses") is not None, "E6: session sub_responses not None")
check(len(body_e6["sub_responses"]) == 2, "E6: session sub_responses has 2 entries")


# ---------------------------------------------------------------------------
# SECTION F — Session integration
# ---------------------------------------------------------------------------

print("\n=== F: Session integration ===")

from fpl_grounded_assistant import ConversationSession

# F1: ConversationSession.respond() returns multi-intent response
sess_f1 = ConversationSession()
r_f1 = sess_f1.respond("tell me about Salah and what gameweek is it", BS)
check(r_f1.intent == INTENT_MULTI_INTENT, "F1: ConversationSession multi-intent -> intent == multi_intent")
check(r_f1.outcome == OUTCOME_OK, "F1: outcome == ok")
check(r_f1.sub_responses is not None, "F1: sub_responses not None")

# F2: Turn count increments after multi-intent turn
check(sess_f1.turn_count == 1, "F2: turn_count == 1 after one multi-intent turn")

# F3: Next single-intent turn works normally after multi-intent turn
r_f3 = sess_f1.respond("who is Salah", BS)
check(r_f3.intent == INTENT_PLAYER_RESOLVE, "F3: next turn after multi-intent works normally")
check(r_f3.sub_responses is None, "F3: single-intent after multi has sub_responses=None")

# F4: Multi-intent session turn does not expose debug bundle on sub-responses
sess_f4 = ConversationSession()
r_f4 = sess_f4.respond("should I captain Haaland and who is Saka", BS, include_debug=True)
check(r_f4.sub_responses[0].debug is None, "F4: sub-response debug always None in session")
check(r_f4.intent == INTENT_MULTI_INTENT, "F4: session multi-intent intent correct")


# ---------------------------------------------------------------------------
# SECTION G — Regression: single-intent unaffected
# ---------------------------------------------------------------------------

print("\n=== G: Regression: single-intent unaffected ===")

# G1: captain score still works
g1 = respond("should I captain Salah", BS)
check(g1.intent == INTENT_CAPTAIN_SCORE, "G1: captain_score unaffected")
check(g1.sub_responses is None, "G1: captain_score sub_responses == None")
check(g1.captain is not None, "G1: captain metadata still present")

# G2: comparison still works
g2 = respond("Haaland vs Salah", BS)
check(g2.intent == INTENT_COMPARE_PLAYERS, "G2: compare_players unaffected")
check(g2.sub_responses is None, "G2: compare_players sub_responses == None")
check(g2.comparison is not None, "G2: comparison metadata still present")

# G3: transfer advice still works (sell X for Y — 'for' not 'and')
g3 = respond("should I sell Saka for Salah", BS)
check(g3.intent == INTENT_TRANSFER_ADVICE, "G3: transfer_advice unaffected")
check(g3.sub_responses is None, "G3: transfer_advice sub_responses == None")

# G4: chip advice still works
g4 = respond("should I wildcard this week", BS)
check(g4.intent == INTENT_CHIP_ADVICE, "G4: chip_advice unaffected")
check(g4.sub_responses is None, "G4: chip_advice sub_responses == None")

# G5: unsupported still works
g5 = respond("is Haaland fit to play?", BS)
check(g5.intent == INTENT_UNSUPPORTED, "G5: unsupported_intent unaffected")
check(g5.sub_responses is None, "G5: unsupported sub_responses == None")

# G6: player resolve still works
g6 = respond("who is De Bruyne", BS)
check(g6.intent == INTENT_PLAYER_RESOLVE, "G6: player_resolve unaffected")
check(g6.sub_responses is None, "G6: player_resolve sub_responses == None")


# ---------------------------------------------------------------------------
# SECTION H — Corpus validation
# ---------------------------------------------------------------------------

print("\n=== H: Corpus validation ===")

from validation_corpus import VALIDATION_SCENARIOS, SCENARIO_BY_ID

# H1: New scenarios exist in corpus
check("multi_intent_gw_and_summary" in SCENARIO_BY_ID, "H1: multi_intent_gw_and_summary in corpus")
check("multi_intent_captain_and_resolve" in SCENARIO_BY_ID, "H1: multi_intent_captain_and_resolve in corpus")

# H2: Corpus count updated
check(len(VALIDATION_SCENARIOS) >= 23, "H2: corpus has at least 23 scenarios")

# H3: New scenario properties
s_gw = SCENARIO_BY_ID["multi_intent_gw_and_summary"]
check(s_gw.expected_intent == "multi_intent", "H3: gw_and_summary expected_intent == multi_intent")
check(s_gw.expected_outcome == "ok", "H3: gw_and_summary expected_outcome == ok")
check(s_gw.expected_supported is True, "H3: gw_and_summary expected_supported == True")
check(s_gw.family == "multi_intent", "H3: gw_and_summary family == multi_intent")
check("cli" in s_gw.surfaces and "http" in s_gw.surfaces, "H3: gw_and_summary surfaces include cli+http")

s_cap = SCENARIO_BY_ID["multi_intent_captain_and_resolve"]
check(s_cap.expected_intent == "multi_intent", "H3: captain_and_resolve expected_intent == multi_intent")
check(s_cap.expected_outcome == "ok", "H3: captain_and_resolve expected_outcome == ok")

# H4: Run corpus scenarios through respond() and CLI
for scenario_id in ("multi_intent_gw_and_summary", "multi_intent_captain_and_resolve"):
    sc = SCENARIO_BY_ID[scenario_id]
    result = respond(sc.question, BS)
    check(
        result.intent == sc.expected_intent,
        f"H4: {scenario_id} intent == {sc.expected_intent}",
    )
    check(
        result.outcome == sc.expected_outcome,
        f"H4: {scenario_id} outcome == {sc.expected_outcome}",
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*40}")
print(f"Phase 6c results: {_PASS}/{total} PASS")
if _FAIL > 0:
    print(f"  {_FAIL} FAILURES")
    sys.exit(1)
else:
    print("  All assertions passed.")
    sys.exit(0)
