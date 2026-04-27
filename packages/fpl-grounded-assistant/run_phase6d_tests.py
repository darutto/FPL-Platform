"""
run_phase6d_tests.py
====================
Phase 6d: Multi-Intent Structured Sub-Response Metadata — test suite.

Sections
--------
A  respond() structured metadata in sub-responses         (~20 assertions)
B  CLI run() debug serialization alignment                (~18 assertions)
C  CLI run_session() sub_responses alignment              (~12 assertions)
D  HTTP /ask serialization alignment                      (~16 assertions)
E  HTTP session /ask serialization alignment              (~12 assertions)
F  Regression: single-intent unaffected                   (~14 assertions)
G  Corpus                                                 (~10 assertions)
                                                          ─────────────────
                                                          ~102 total

Usage
-----
    cd packages/fpl-grounded-assistant
    python run_phase6d_tests.py
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
    INTENT_COMPARE_PLAYERS,
    INTENT_PLAYER_RESOLVE,
    INTENT_PLAYER_SUMMARY,
    INTENT_CURRENT_GAMEWEEK,
    OUTCOME_OK,
    respond,
)

BS = STANDARD_BOOTSTRAP

# The two canonical multi-intent test questions for Phase 6d
Q_CAPTAIN_COMPARISON = "should I captain Haaland and compare Salah and Haaland"
Q_CAPTAIN_RESOLVE    = "should I captain Haaland and who is Saka"
Q_SUMMARY_GW         = "tell me about Salah and what gameweek is it"


# ---------------------------------------------------------------------------
# SECTION A — respond() structured metadata in sub-responses
# ---------------------------------------------------------------------------

print("\n=== A: respond() structured metadata in sub-responses ===")

# A1: captain + comparison: sub_responses[0] has .captain, sub_responses[1] has .comparison
a1 = respond(Q_CAPTAIN_COMPARISON, BS)
check(a1.intent == INTENT_MULTI_INTENT, "A1: intent == multi_intent")
check(a1.outcome == OUTCOME_OK, "A1: outcome == ok")
check(a1.sub_responses is not None and len(a1.sub_responses) == 2,
      "A1: sub_responses has 2 entries")

check(a1.sub_responses[0].intent == INTENT_CAPTAIN_SCORE,
      "A1: sub_responses[0].intent == captain_score")
check(a1.sub_responses[0].captain is not None,
      "A1: sub_responses[0].captain non-null (captain_score sub-intent)")
check(a1.sub_responses[0].comparison is None,
      "A1: sub_responses[0].comparison is None")

check(a1.sub_responses[1].intent == INTENT_COMPARE_PLAYERS,
      "A1: sub_responses[1].intent == compare_players")
check(a1.sub_responses[1].comparison is not None,
      "A1: sub_responses[1].comparison non-null (compare_players sub-intent)")
check(a1.sub_responses[1].captain is None,
      "A1: sub_responses[1].captain is None")

# A2: captain sub-response captain fields are correct types
cap = a1.sub_responses[0].captain
check(isinstance(cap.web_name, str) and cap.web_name,
      "A2: captain.web_name is non-empty str")
check(isinstance(cap.captain_score, float),
      "A2: captain.captain_score is float")
check(isinstance(cap.tier, str) and cap.tier,
      "A2: captain.tier is non-empty str")

# A3: comparison sub-response comparison fields are correct types
comp = a1.sub_responses[1].comparison
check(isinstance(comp.margin, float),
      "A3: comparison.margin is float")
check(isinstance(comp.label, str) and comp.label in ("narrow", "moderate", "clear"),
      "A3: comparison.label is valid string")
check(isinstance(comp.reasons, tuple),
      "A3: comparison.reasons is tuple")

# A4: captain + resolve: captain in sub_responses[0], no comparison in sub_responses[1]
a4 = respond(Q_CAPTAIN_RESOLVE, BS)
check(a4.intent == INTENT_MULTI_INTENT, "A4: captain+resolve intent == multi_intent")
check(a4.sub_responses[0].captain is not None,
      "A4: sub_responses[0].captain non-null")
check(a4.sub_responses[1].captain is None,
      "A4: sub_responses[1].captain is None (player_resolve)")
check(a4.sub_responses[1].comparison is None,
      "A4: sub_responses[1].comparison is None (player_resolve)")

# A5: summary + gameweek: neither sub has structured metadata
a5 = respond(Q_SUMMARY_GW, BS)
check(a5.intent == INTENT_MULTI_INTENT, "A5: summary+gw intent == multi_intent")
check(a5.sub_responses[0].captain is None and a5.sub_responses[0].comparison is None,
      "A5: sub_responses[0] has no structured metadata (player_summary)")
check(a5.sub_responses[1].captain is None and a5.sub_responses[1].comparison is None,
      "A5: sub_responses[1] has no structured metadata (current_gameweek)")

# A6: top-level captain/comparison on multi-intent response itself are None
check(a1.captain is None,
      "A6: top-level captain is None for multi_intent turn")
check(a1.comparison is None,
      "A6: top-level comparison is None for multi_intent turn")


# ---------------------------------------------------------------------------
# SECTION B — CLI run() debug serialization alignment
# ---------------------------------------------------------------------------

print("\n=== B: CLI run() debug serialization alignment ===")

from fpl_cli import run

# B1: captain+comparison debug JSON: sub_responses[0] has "captain", sub_responses[1] has "comparison"
_, out_b1 = run(Q_CAPTAIN_COMPARISON, BS, debug=True)
payload_b1 = json.loads(out_b1)
check(payload_b1.get("intent") == "multi_intent", "B1: intent == multi_intent")
check("sub_responses" in payload_b1, "B1: sub_responses key present")
check(isinstance(payload_b1["sub_responses"], list) and len(payload_b1["sub_responses"]) == 2,
      "B1: sub_responses is list of 2")

sub0_b1 = payload_b1["sub_responses"][0]
sub1_b1 = payload_b1["sub_responses"][1]

check("captain" in sub0_b1, "B1: sub_responses[0] has 'captain' key")
check("comparison" not in sub0_b1, "B1: sub_responses[0] has no 'comparison' key")
check("comparison" in sub1_b1, "B1: sub_responses[1] has 'comparison' key")
check("captain" not in sub1_b1, "B1: sub_responses[1] has no 'captain' key")

# B2: captain in sub-response has expected keys
captain_b2 = sub0_b1["captain"]
check(all(k in captain_b2 for k in ("web_name", "captain_score", "tier", "role_bonus", "set_piece_notes")),
      "B2: sub captain dict has all expected keys")

# B3: comparison in sub-response has expected keys
comp_b3 = sub1_b1["comparison"]
check(all(k in comp_b3 for k in ("winner", "margin", "label", "reasons", "player_a", "player_b")),
      "B3: sub comparison dict has all expected keys")

# B4: captain+resolve: sub_responses[0] has captain, sub_responses[1] has no structured keys
_, out_b4 = run(Q_CAPTAIN_RESOLVE, BS, debug=True)
payload_b4 = json.loads(out_b4)
sub0_b4 = payload_b4["sub_responses"][0]
sub1_b4 = payload_b4["sub_responses"][1]
check("captain" in sub0_b4, "B4: captain+resolve sub[0] has captain")
check("comparison" not in sub1_b4 and "captain" not in sub1_b4,
      "B4: captain+resolve sub[1] (player_resolve) has no structured metadata")

# B5: summary+gameweek: neither sub has structured metadata keys
_, out_b5 = run(Q_SUMMARY_GW, BS, debug=True)
payload_b5 = json.loads(out_b5)
sub0_b5 = payload_b5["sub_responses"][0]
sub1_b5 = payload_b5["sub_responses"][1]
check("captain" not in sub0_b5 and "comparison" not in sub0_b5,
      "B5: summary+gw sub[0] has no structured metadata")
check("captain" not in sub1_b5 and "comparison" not in sub1_b5,
      "B5: summary+gw sub[1] has no structured metadata")

# B6: non-debug output is still combined final_text (not JSON)
_, out_b6 = run(Q_CAPTAIN_COMPARISON, BS, debug=False)
check(not out_b6.startswith("{"), "B6: non-debug output is not JSON")
check(len(out_b6) > 0, "B6: non-debug output non-empty")


# ---------------------------------------------------------------------------
# SECTION C — CLI run_session() sub_responses alignment
# ---------------------------------------------------------------------------

print("\n=== C: CLI run_session() sub_responses alignment ===")

from fpl_cli import run_session

# C1: run_session multi-intent turn includes sub_responses in result dict
turns_c1 = run_session([Q_CAPTAIN_COMPARISON], BS)
check(len(turns_c1) == 1, "C1: one turn result")
t_c1 = turns_c1[0]
check("sub_responses" in t_c1, "C1: multi-intent turn has sub_responses key")
check(isinstance(t_c1["sub_responses"], list) and len(t_c1["sub_responses"]) == 2,
      "C1: sub_responses is list of 2")

# C2: sub_responses in run_session include structured metadata
sub0_c2 = t_c1["sub_responses"][0]
sub1_c2 = t_c1["sub_responses"][1]
check("captain" in sub0_c2, "C2: run_session sub[0] has captain")
check("comparison" in sub1_c2, "C2: run_session sub[1] has comparison")

# C3: single-intent turn in run_session has no sub_responses key
turns_c3 = run_session(["who is Salah"], BS)
check("sub_responses" not in turns_c3[0], "C3: single-intent turn has no sub_responses key")

# C4: multi-intent turn followed by single-intent — both behave correctly
turns_c4 = run_session([Q_CAPTAIN_COMPARISON, "who is Saka"], BS)
check("sub_responses" in turns_c4[0], "C4: first turn (multi) has sub_responses")
check("sub_responses" not in turns_c4[1], "C4: second turn (single) has no sub_responses")

# C5: always-present base fields in sub-response entries from run_session
sub_c5 = t_c1["sub_responses"][0]
check(all(k in sub_c5 for k in ("final_text", "outcome", "supported", "intent")),
      "C5: sub_response always has base fields")


# ---------------------------------------------------------------------------
# SECTION D — HTTP /ask serialization alignment
# ---------------------------------------------------------------------------

print("\n=== D: HTTP /ask serialization alignment ===")

from fastapi.testclient import TestClient
from fpl_server import app, _init_bootstrap, _clear_sessions, _init_classifier_client

_init_bootstrap(BS)
_init_classifier_client(None)
http = TestClient(app)

# D1: captain+comparison: sub_responses[0] has captain, sub_responses[1] has comparison
r_d1 = http.post("/ask", json={"question": Q_CAPTAIN_COMPARISON})
check(r_d1.status_code == 200, "D1: /ask multi-intent -> 200")
body_d1 = r_d1.json()
check(body_d1.get("intent") == "multi_intent", "D1: intent == multi_intent")
check("sub_responses" in body_d1 and body_d1["sub_responses"] is not None,
      "D1: sub_responses present and non-null")

sub0_d1 = body_d1["sub_responses"][0]
sub1_d1 = body_d1["sub_responses"][1]
check("captain" in sub0_d1, "D1: HTTP sub[0] has captain")
check("comparison" in sub1_d1, "D1: HTTP sub[1] has comparison")
check("comparison" not in sub0_d1, "D1: HTTP sub[0] no comparison")
check("captain" not in sub1_d1, "D1: HTTP sub[1] no captain")

# D2: structured captain shape in HTTP sub-response
captain_d2 = sub0_d1["captain"]
check(all(k in captain_d2 for k in ("web_name", "captain_score", "tier", "role_bonus", "set_piece_notes", "team_short")),
      "D2: HTTP sub captain has all keys")

# D3: structured comparison shape in HTTP sub-response
comp_d3 = sub1_d1["comparison"]
check(all(k in comp_d3 for k in ("winner", "margin", "label", "reasons", "player_a", "player_b")),
      "D3: HTTP sub comparison has all keys")

# D4: captain+resolve sub_responses: structured captain in sub[0], none in sub[1]
r_d4 = http.post("/ask", json={"question": Q_CAPTAIN_RESOLVE})
body_d4 = r_d4.json()
check("captain" in body_d4["sub_responses"][0],
      "D4: captain+resolve HTTP sub[0] has captain")
check("comparison" not in body_d4["sub_responses"][1] and "captain" not in body_d4["sub_responses"][1],
      "D4: captain+resolve HTTP sub[1] (player_resolve) no structured metadata")

# D5: single-intent /ask: sub_responses is null; captain at top level for captain_score
r_d5 = http.post("/ask", json={"question": "should I captain Salah"})
body_d5 = r_d5.json()
check(body_d5.get("sub_responses") is None, "D5: single-intent sub_responses is null")
check(body_d5.get("captain") is not None, "D5: single-intent captain at top level")

# D6: single-intent comparison at top level; sub_responses null
r_d6 = http.post("/ask", json={"question": "compare Salah and Haaland"})
body_d6 = r_d6.json()
check(body_d6.get("intent") == "compare_players", "D6: comparison intent unchanged")
check(body_d6.get("sub_responses") is None, "D6: comparison sub_responses is null")
check(body_d6.get("comparison") is not None, "D6: comparison at top level for single-intent")


# ---------------------------------------------------------------------------
# SECTION E — HTTP session /ask serialization alignment
# ---------------------------------------------------------------------------

print("\n=== E: HTTP session /ask serialization alignment ===")

_clear_sessions()

# E1: session ask captain+comparison: sub_responses with structured metadata
sess_e1 = http.post("/session").json()
sid_e1 = sess_e1["session_id"]
r_e1 = http.post(f"/session/{sid_e1}/ask", json={"question": Q_CAPTAIN_COMPARISON})
check(r_e1.status_code == 200, "E1: session /ask -> 200")
body_e1 = r_e1.json()
check(body_e1.get("intent") == "multi_intent", "E1: session intent == multi_intent")
check(body_e1.get("sub_responses") is not None, "E1: session sub_responses non-null")

sub0_e1 = body_e1["sub_responses"][0]
sub1_e1 = body_e1["sub_responses"][1]
check("captain" in sub0_e1, "E1: session sub[0] has captain")
check("comparison" in sub1_e1, "E1: session sub[1] has comparison")

# E2: session ask captain+resolve: sub_responses alignment
r_e2 = http.post(f"/session/{sid_e1}/ask", json={"question": Q_CAPTAIN_RESOLVE})
body_e2 = r_e2.json()
check(body_e2.get("sub_responses") is not None, "E2: session captain+resolve sub_responses non-null")
check("captain" in body_e2["sub_responses"][0],
      "E2: session captain+resolve sub[0] has captain")

# E3: session single-intent after multi-intent: no sub_responses
r_e3 = http.post(f"/session/{sid_e1}/ask", json={"question": "who is Salah"})
body_e3 = r_e3.json()
check(body_e3.get("sub_responses") is None, "E3: session single-intent sub_responses is null")

# E4: CLI and HTTP sub-responses shapes are aligned (same keys) for captain+comparison
_, out_e4_cli = run(Q_CAPTAIN_COMPARISON, BS, debug=True)
payload_cli = json.loads(out_e4_cli)
r_e4_http = http.post("/ask", json={"question": Q_CAPTAIN_COMPARISON})
payload_http = r_e4_http.json()
cli_keys_0 = set(payload_cli["sub_responses"][0].keys())
http_keys_0 = set(payload_http["sub_responses"][0].keys())
cli_keys_1 = set(payload_cli["sub_responses"][1].keys())
http_keys_1 = set(payload_http["sub_responses"][1].keys())
check(cli_keys_0 == http_keys_0,
      "E4: CLI and HTTP sub[0] have identical keys for captain+comparison")
check(cli_keys_1 == http_keys_1,
      "E4: CLI and HTTP sub[1] have identical keys for captain+comparison")


# ---------------------------------------------------------------------------
# SECTION F — Regression: single-intent unaffected
# ---------------------------------------------------------------------------

print("\n=== F: Regression: single-intent unaffected ===")

# F1: single-intent captain: captain at top level; sub_responses None; unchanged shape
f1 = respond("should I captain Salah", BS)
check(f1.intent == INTENT_CAPTAIN_SCORE, "F1: captain_score intent unchanged")
check(f1.sub_responses is None, "F1: captain_score sub_responses is None")
check(f1.captain is not None, "F1: captain metadata at top level unchanged")

# F2: single-intent comparison: comparison at top level; sub_responses None
f2 = respond("Salah vs Haaland", BS)
check(f2.intent == INTENT_COMPARE_PLAYERS, "F2: compare_players intent unchanged")
check(f2.sub_responses is None, "F2: compare_players sub_responses is None")
check(f2.comparison is not None, "F2: comparison metadata at top level unchanged")

# F3: comparison NOT split as multi-intent (false-split guard preserved)
f3 = respond("compare Salah and Haaland", BS)
check(f3.intent == INTENT_COMPARE_PLAYERS, "F3: 'compare Salah and Haaland' -> compare_players")
check(f3.sub_responses is None, "F3: full comparison not split into multi-intent")

# F4: HTTP single-intent captain shape unchanged (top-level captain non-null, sub_responses null)
r_f4 = http.post("/ask", json={"question": "should I captain Salah"})
body_f4 = r_f4.json()
check(body_f4.get("captain") is not None, "F4: HTTP single captain at top level")
check(body_f4.get("sub_responses") is None, "F4: HTTP single captain sub_responses null")

# F5: HTTP single comparison shape unchanged
r_f5 = http.post("/ask", json={"question": "compare Salah and Haaland"})
body_f5 = r_f5.json()
check(body_f5.get("comparison") is not None, "F5: HTTP single comparison at top level")
check(body_f5.get("sub_responses") is None, "F5: HTTP single comparison sub_responses null")

# F6: CLI run_session single-intent has no sub_responses, captain at top of turn dict
turns_f6 = run_session(["should I captain Salah"], BS)
check("captain" in turns_f6[0], "F6: run_session single captain at top-level turn dict")
check("sub_responses" not in turns_f6[0], "F6: run_session single no sub_responses key")

# F7: debug None on sub-responses unchanged
f7 = respond(Q_CAPTAIN_COMPARISON, BS, include_debug=True)
check(f7.sub_responses[0].debug is None, "F7: sub-response debug always None")
check(f7.sub_responses[1].debug is None, "F7: sub-response debug always None")


# ---------------------------------------------------------------------------
# SECTION G — Corpus
# ---------------------------------------------------------------------------

print("\n=== G: Corpus ===")

from validation_corpus import VALIDATION_SCENARIOS, SCENARIO_BY_ID

# G1: New Phase 6d scenario present in corpus
check("multi_intent_captain_and_comparison" in SCENARIO_BY_ID,
      "G1: multi_intent_captain_and_comparison in corpus")

# G2: Corpus count updated to 24
check(len(VALIDATION_SCENARIOS) == 24, "G2: corpus has 24 scenarios")

# G3: New scenario properties
s_6d = SCENARIO_BY_ID["multi_intent_captain_and_comparison"]
check(s_6d.expected_intent == "multi_intent", "G3: expected_intent == multi_intent")
check(s_6d.expected_outcome == "ok", "G3: expected_outcome == ok")
check(s_6d.expected_supported is True, "G3: expected_supported == True")
check(s_6d.family == "multi_intent", "G3: family == multi_intent")
check("cli" in s_6d.surfaces and "http" in s_6d.surfaces, "G3: surfaces include cli+http")

# G4: Run Phase 6d corpus scenario through respond()
g4 = respond(s_6d.question, BS)
check(g4.intent == s_6d.expected_intent, "G4: corpus scenario intent matches")
check(g4.outcome == s_6d.expected_outcome, "G4: corpus scenario outcome matches")
check(g4.sub_responses is not None, "G4: corpus scenario has sub_responses")
check(g4.sub_responses[0].captain is not None, "G4: sub[0] captain populated")
check(g4.sub_responses[1].comparison is not None, "G4: sub[1] comparison populated")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*40}")
print(f"Phase 6d results: {_PASS}/{total} PASS")
if _FAIL > 0:
    print(f"  {_FAIL} FAILURES")
    sys.exit(1)
else:
    print("  All assertions passed.")
    sys.exit(0)
