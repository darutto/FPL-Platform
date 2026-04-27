"""
run_phase_v2_intent_hint_tests.py
===================================
V2 intent_hint slice: bounded routing bias for slash-command use cases.

Proves that:
- No-hint behavior is completely unchanged (deterministic and classifier paths)
- Valid hints bias routing for all six V2 slash-command target intents
- Invalid / unsupported / empty hints fall back safely
- Stateless /ask and session /session/{id}/ask behave identically
- classification_source == "intent_hint" surfaces in debug when hint fires
- The hint does not override a question the deterministic router already handles

Sections
--------
A  _try_route_with_hint unit tests — allowlist, templates, fallback         (14)
B  dispatch() with intent_hint — all six slash-command intents routed       (12)
C  dispatch() safety — invalid hint, empty question, wrong hint ignored      (8)
D  HTTP /ask with intent_hint — contract, debug field, parity               (12)
E  Session HTTP with intent_hint — parity with stateless /ask               (6)
F  No-hint regression — deterministic routing unchanged                     (6)
G  Hint does not override a question already routed deterministically        (4)
"""
from __future__ import annotations

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

from fastapi.testclient import TestClient
import fpl_server
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.dispatcher import (
    dispatch,
    _try_route_with_hint,
    INTENT_HINT_ALLOWLIST,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_CHIP_ADVICE,
    INTENT_PLAYER_FIXTURE_RUN,
    INTENT_DIFFERENTIAL_PICKS,
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
)

BS = STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Helpers
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


def _reset() -> None:
    fpl_server._init_classifier_client(None)
    fpl_server._init_bootstrap(BS)
    fpl_server._clear_sessions()


def _http() -> TestClient:
    fpl_server._init_bootstrap(BS)
    return TestClient(fpl_server.app, raise_server_exceptions=True)


def _post(client: TestClient, payload: dict) -> dict:
    resp = client.post("/ask", json=payload)
    try:
        return resp.json()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Section A -- _try_route_with_hint unit tests (14)
# ---------------------------------------------------------------------------

section("A -- _try_route_with_hint unit tests")

# A1: allowlist contains the six V2 slash-command intents
for _hint in [
    INTENT_CAPTAIN_SCORE, INTENT_RANK_CANDIDATES, INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE, INTENT_CHIP_ADVICE, INTENT_PLAYER_FIXTURE_RUN,
    INTENT_DIFFERENTIAL_PICKS,
]:
    check(_hint in INTENT_HINT_ALLOWLIST, f"A1: {_hint} in INTENT_HINT_ALLOWLIST")

# A2: invalid hint returns None
check(
    _try_route_with_hint("Haaland", "not_a_real_intent") is None,
    "A2: invalid hint returns None",
)

# A3: empty question for player-requiring hint returns None (no player to extract)
check(
    _try_route_with_hint("", INTENT_CAPTAIN_SCORE) is None,
    "A3: empty question for captain_score hint returns None",
)
check(
    _try_route_with_hint("   ", INTENT_CAPTAIN_SCORE) is None,
    "A4: whitespace-only question for captain_score hint returns None",
)

# A5: self-contained hints succeed with any (even empty) question
result_a5 = _try_route_with_hint("", INTENT_DIFFERENTIAL_PICKS)
check(result_a5 is not None, "A5: differential_picks hint succeeds with empty question")
result_a6 = _try_route_with_hint("", INTENT_RANK_CANDIDATES)
check(result_a6 is not None, "A6: rank_candidates hint succeeds with empty question")

# A7: captain_score hint produces correct route for player name
result_a7 = _try_route_with_hint("Haaland", INTENT_CAPTAIN_SCORE)
check(result_a7 is not None, "A7: captain_score hint routes 'Haaland'")
if result_a7:
    rr_a7, canon_a7 = result_a7
    check(rr_a7.tool_name == "get_captain_score", "A7b: tool_name is get_captain_score")
    check("Haaland" in rr_a7.tool_args.get("query", ""), "A7c: player query contains 'Haaland'")

# A8: fixture_run hint routes player name
result_a8 = _try_route_with_hint("Salah", INTENT_PLAYER_FIXTURE_RUN)
check(result_a8 is not None, "A8: fixture_run hint routes 'Salah'")
if result_a8:
    rr_a8, _ = result_a8
    check(rr_a8.tool_name == "get_player_fixture_run", "A8b: tool_name is get_player_fixture_run")


# ---------------------------------------------------------------------------
# Section B -- dispatch() with intent_hint — all six intents (12)
# ---------------------------------------------------------------------------

section("B -- dispatch() intent_hint routes all six slash-command intents")

# B1: captain_score — bare player name routed via hint
dr_b1 = dispatch("Haaland", BS, intent_hint=INTENT_CAPTAIN_SCORE)
check(dr_b1.intent == INTENT_CAPTAIN_SCORE, "B1: captain_score hint routes 'Haaland'")
check(dr_b1.outcome == OUTCOME_OK, "B1b: captain_score outcome ok")
check(dr_b1.classification_source == "intent_hint", "B1c: classification_source == 'intent_hint'")

# B2: rank_candidates — natural phrasing routed via hint
dr_b2 = dispatch("my best options this week", BS, intent_hint=INTENT_RANK_CANDIDATES)
check(dr_b2.intent == INTENT_RANK_CANDIDATES, "B2: rank_candidates hint routes natural phrasing")
check(dr_b2.classification_source == "intent_hint", "B2b: rank_candidates classification_source")

# B3: compare_players — "X and Y" form routed via hint
dr_b3 = dispatch("Salah and Haaland", BS, intent_hint=INTENT_COMPARE_PLAYERS)
check(dr_b3.intent == INTENT_COMPARE_PLAYERS, "B3: compare_players hint routes 'X and Y'")
check(dr_b3.outcome == OUTCOME_OK, "B3b: compare_players outcome ok")
check(dr_b3.classification_source == "intent_hint", "B3c: compare_players classification_source")

# B4: transfer_advice — "X for Y" form routed via hint
dr_b4 = dispatch("Saka for Palmer", BS, intent_hint=INTENT_TRANSFER_ADVICE)
check(dr_b4.intent == INTENT_TRANSFER_ADVICE, "B4: transfer_advice hint routes 'X for Y'")
check(dr_b4.classification_source == "intent_hint", "B4b: transfer_advice classification_source")

# B5: chip_advice — chip name routed via hint
dr_b5 = dispatch("triple captain", BS, intent_hint=INTENT_CHIP_ADVICE)
check(dr_b5.intent == INTENT_CHIP_ADVICE, "B5: chip_advice hint routes 'triple captain'")
check(dr_b5.classification_source == "intent_hint", "B5b: chip_advice classification_source")

# B6: player_fixture_run — bare player name routed via hint
dr_b6 = dispatch("De Bruyne", BS, intent_hint=INTENT_PLAYER_FIXTURE_RUN)
check(dr_b6.intent == INTENT_PLAYER_FIXTURE_RUN, "B6: fixture_run hint routes 'De Bruyne'")
check(dr_b6.classification_source == "intent_hint", "B6b: fixture_run classification_source")

# B7: differential_picks — question with no det. route routed via hint
# ("hidden gems this week" does not match any keyword/prefix; hint fires)
dr_b7 = dispatch("hidden gems this week", BS, intent_hint=INTENT_DIFFERENTIAL_PICKS)
check(dr_b7.intent == INTENT_DIFFERENTIAL_PICKS, "B7: differential_picks hint routes generic question")
check(dr_b7.classification_source == "intent_hint", "B7b: differential_picks classification_source")


# ---------------------------------------------------------------------------
# Section C -- dispatch() safety: invalid / empty / wrong hints (8)
# ---------------------------------------------------------------------------

section("C -- dispatch() safety: invalid, empty, and incompatible hints")

# C1: invalid hint string -> falls through to unsupported
dr_c1 = dispatch("Haaland", BS, intent_hint="not_valid")
check(dr_c1.intent == INTENT_RANK_CANDIDATES or dr_c1.classification_source != "intent_hint",
      "C1: invalid hint does not set classification_source=intent_hint")
check(dr_c1.classification_source != "intent_hint", "C1b: invalid hint classification_source is not 'intent_hint'")

# C2: None hint -> no hint applied (classification_source stays None for det. route)
dr_c2 = dispatch("should I captain Salah", BS, intent_hint=None)
check(dr_c2.intent == INTENT_CAPTAIN_SCORE, "C2: None hint -> deterministic routing unchanged")
check(dr_c2.classification_source is None, "C2b: None hint -> classification_source is None")

# C3: hint fires but question has no connector for compare -> returns unsupported
#     "compare Haaland" has no second player -> route returns None for compare
dr_c3 = dispatch("Haaland", BS, intent_hint=INTENT_COMPARE_PLAYERS)
# "compare Haaland" -> _try_route_comparison finds no connector -> None
# falls through to unsupported_intent
check(dr_c3.outcome == OUTCOME_UNSUPPORTED_INTENT, "C3: compare hint with single player -> unsupported")
check(dr_c3.classification_source != "intent_hint", "C3b: failed hint does not set intent_hint source")

# C4: transfer hint with no connector -> unsupported
dr_c4 = dispatch("Saka", BS, intent_hint=INTENT_TRANSFER_ADVICE)
# "sell Saka" has no connector -> _try_route_transfer returns None
check(dr_c4.outcome == OUTCOME_UNSUPPORTED_INTENT, "C4: transfer hint with single player -> unsupported")
check(dr_c4.classification_source != "intent_hint", "C4b: failed transfer hint does not set intent_hint source")


# ---------------------------------------------------------------------------
# Section D -- HTTP /ask with intent_hint (12)
# ---------------------------------------------------------------------------

section("D -- HTTP /ask with intent_hint")

_reset()
http = _http()

# D1: captain_score via /ask with intent_hint
body_d1 = _post(http, {
    "question": "Haaland",
    "intent_hint": "captain_score",
    "debug": True,
})
check(body_d1.get("intent") == "captain_score", "D1: /ask captain_score hint -> intent")
check(body_d1.get("outcome") == "ok", "D1b: /ask captain_score hint -> outcome ok")
check(body_d1.get("captain") is not None, "D1c: /ask captain_score hint -> captain metadata present")
dbg_d1 = body_d1.get("debug") or {}
check(dbg_d1.get("classification_source") == "intent_hint", "D1d: /ask debug.classification_source == 'intent_hint'")

# D2: compare_players via /ask with intent_hint
body_d2 = _post(http, {
    "question": "Salah and Haaland",
    "intent_hint": "compare_players",
    "debug": True,
})
check(body_d2.get("intent") == "compare_players", "D2: /ask compare hint -> intent")
check(body_d2.get("comparison") is not None, "D2b: /ask compare hint -> comparison metadata present")
dbg_d2 = body_d2.get("debug") or {}
check(dbg_d2.get("classification_source") == "intent_hint", "D2c: /ask compare debug.classification_source")

# D3: intent_hint absent -> classification_source not in debug for deterministic route
body_d3 = _post(http, {
    "question": "should I captain Salah",
    "debug": True,
})
check(body_d3.get("intent") == "captain_score", "D3: no hint -> deterministic route unchanged")
dbg_d3 = body_d3.get("debug") or {}
check(dbg_d3.get("classification_source") is None, "D3b: no hint -> classification_source None")

# D4: invalid hint does not crash
body_d4 = _post(http, {
    "question": "Haaland",
    "intent_hint": "not_a_real_intent",
})
check(body_d4.get("supported") is not None, "D4: invalid hint does not crash /ask")
check(body_d4.get("intent") != "captain_score" or body_d4.get("classification_source") != "intent_hint",
      "D4b: invalid hint does not produce intent_hint classification_source")

_reset()


# ---------------------------------------------------------------------------
# Section E -- Session HTTP /session/{id}/ask with intent_hint (6)
# ---------------------------------------------------------------------------

section("E -- Session HTTP /session/{id}/ask with intent_hint")

_reset()
fpl_server._init_bootstrap(BS)
fpl_server._clear_sessions()
sc = TestClient(fpl_server.app, raise_server_exceptions=True)
sid = sc.post("/session").json()["session_id"]

# E1: captain_score via session ask with intent_hint
resp_e1 = sc.post(f"/session/{sid}/ask", json={
    "question": "Haaland",
    "intent_hint": "captain_score",
    "debug": True,
})
body_e1 = resp_e1.json()
check(body_e1.get("intent") == "captain_score", "E1: session /ask captain hint -> intent")
check(body_e1.get("outcome") == "ok", "E1b: session /ask captain hint -> outcome ok")
dbg_e1 = body_e1.get("debug") or {}
check(dbg_e1.get("classification_source") == "intent_hint", "E1c: session debug.classification_source == 'intent_hint'")

# E2: differential_picks via session ask with intent_hint
resp_e2 = sc.post(f"/session/{sid}/ask", json={
    "question": "hidden gems this week",
    "intent_hint": "differential_picks",
    "debug": True,
})
body_e2 = resp_e2.json()
check(body_e2.get("intent") == "differential_picks", "E2: session /ask differential hint -> intent")
dbg_e2 = body_e2.get("debug") or {}
check(dbg_e2.get("classification_source") == "intent_hint", "E2b: session differential debug.classification_source")

# E3: no hint in session -> deterministic routing unchanged
resp_e3 = sc.post(f"/session/{sid}/ask", json={
    "question": "should I captain Salah",
    "debug": True,
})
body_e3 = resp_e3.json()
check(body_e3.get("intent") == "captain_score", "E3: session no hint -> deterministic routing")
dbg_e3 = body_e3.get("debug") or {}
check(dbg_e3.get("classification_source") is None, "E3b: session no hint -> classification_source None")

sc.delete(f"/session/{sid}")
_reset()


# ---------------------------------------------------------------------------
# Section F -- No-hint regression (6)
# ---------------------------------------------------------------------------

section("F -- No-hint regression: existing deterministic routes unchanged")

DET_CASES = [
    ("should I captain Salah",    "captain_score",   "ok"),
    ("compare Haaland and Salah", "compare_players", "ok"),
    ("sell Salah for Haaland",    "transfer_advice", "ok"),
]

_reset()
http_f = _http()
for q, exp_intent, exp_outcome in DET_CASES:
    body_f = _post(http_f, {"question": q})
    check(body_f.get("intent") == exp_intent, f"F: no hint '{q}' -> intent={exp_intent}")
    check(body_f.get("outcome") == exp_outcome, f"F: no hint '{q}' -> outcome={exp_outcome}")

_reset()


# ---------------------------------------------------------------------------
# Section G -- Hint does not override a question the router already handles (4)
# ---------------------------------------------------------------------------

section("G -- Hint does not override deterministic route (hint is bias, not authority)")

_reset()

# G1: question already routes as captain_score; even a compare hint should NOT
#     change the route (deterministic fires first, hint is never consulted)
dr_g1 = dispatch("should I captain Haaland", BS, intent_hint=INTENT_COMPARE_PLAYERS)
check(dr_g1.intent == INTENT_CAPTAIN_SCORE, "G1: det. route fires first; compare hint not applied")
check(dr_g1.classification_source is None, "G1b: det. route -> classification_source is None (hint ignored)")

# G2: question already routes as transfer_advice; captain hint should NOT change it
dr_g2 = dispatch("sell Saka for Palmer", BS, intent_hint=INTENT_CAPTAIN_SCORE)
check(dr_g2.intent == INTENT_TRANSFER_ADVICE, "G2: det. route fires first; captain hint not applied")
check(dr_g2.classification_source is None, "G2b: transfer det. route -> classification_source None")

_reset()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*50}")
print(f"V2 intent_hint: {_PASS}/{total} PASS")
if _FAIL:
    print(f"                {_FAIL} FAIL")
    sys.exit(1)
else:
    print("                All assertions passed.")
    sys.exit(0)
