"""
run_phase4l_tests.py
====================
Phase 4l: HTTP and Session Classifier Parity -- test suite.

Target: ~115 assertions across 7 sections.

Sections
--------
A  HTTP /ask endpoint -- classifier_client threaded, classification_source in debug (22)
B  Session CLI -- run_session() with classifier_client (18)
C  Session HTTP -- session endpoints with classifier injection (22)
D  Cross-surface parity -- all 4 surfaces produce same intent/outcome/supported (15)
E  Validation corpus surface update -- 3 Phase 4k scenarios now span all 4 surfaces (9)
F  Regression -- deterministic routes unchanged on all 3 new surfaces (18)
G  Fallback safety on new surfaces -- bad stub / None stub behave correctly (11)
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

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.dispatcher import (
    INTENT_CAPTAIN_SCORE, INTENT_COMPARE_PLAYERS, INTENT_RANK_CANDIDATES,
    OUTCOME_OK, OUTCOME_UNSUPPORTED_INTENT,
)
from fpl_cli import run as cli_run, run_session as cli_run_session
import fpl_server
from fastapi.testclient import TestClient
from validation_corpus import VALIDATION_SCENARIOS, SCENARIO_BY_ID


# ---------------------------------------------------------------------------
# Shared stub infrastructure
# ---------------------------------------------------------------------------

class _StubBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubMessage:
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]


class _StubMessages:
    def __init__(self, response_json: str) -> None:
        self._json = response_json

    def create(self, **kwargs: Any) -> _StubMessage:
        return _StubMessage(self._json)


class _StubAnthropicClient:
    """Minimal stub satisfying the classifier_client interface."""
    def __init__(self, response_json: str) -> None:
        self.messages = _StubMessages(response_json)


# Pre-built stubs for each Phase 4k/4l scenario
CAPTAIN_STUB = _StubAnthropicClient(
    '{"intent": "captain_score", '
    '"canonical_question": "should I captain Saka", '
    '"confidence": 0.92, "language": "en"}'
)
COMPARISON_STUB = _StubAnthropicClient(
    '{"intent": "compare_players", '
    '"canonical_question": "compare Salah and Haaland", '
    '"confidence": 0.88, "language": "en"}'
)
RANKING_STUB = _StubAnthropicClient(
    '{"intent": "rank_candidates", '
    '"canonical_question": "top captains this week", '
    '"confidence": 0.90, "language": "en"}'
)
BAD_JSON_STUB = _StubAnthropicClient("not valid json at all")
LOW_CONF_STUB = _StubAnthropicClient(
    '{"intent": "captain_score", '
    '"canonical_question": "should I captain Saka", '
    '"confidence": 0.55, "language": "en"}'
)

CANDIDATES = [{"query": "Salah"}, {"query": "Haaland"}, {"query": "Saka"}]

BS = STANDARD_BOOTSTRAP
PHASE4K_IDS = ["natural_captain_phrasing", "natural_comparison_phrasing", "natural_ranking_phrasing"]


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


def _http_client() -> TestClient:
    fpl_server._init_bootstrap(BS)
    return TestClient(fpl_server.app, raise_server_exceptions=True)


def _reset_classifier() -> None:
    fpl_server._init_classifier_client(None)


# ---------------------------------------------------------------------------
# Section A -- HTTP /ask endpoint classifier threading (22)
# ---------------------------------------------------------------------------

section("A -- HTTP /ask endpoint classifier threading")

# A1: captain natural phrasing via /ask with debug=True + classifier stub
fpl_server._init_bootstrap(BS)
fpl_server._init_classifier_client(CAPTAIN_STUB)
client = _http_client()
resp_a1 = client.post("/ask", json={"question": "is Saka worth captaining?", "debug": True})
_reset_classifier()
body_a1: dict = {}
try:
    body_a1 = resp_a1.json()
except Exception:
    pass
check(resp_a1.status_code == 200, "A1: /ask status 200 with captain stub")
check(body_a1.get("intent") == "captain_score", "A1b: /ask captain intent")
check(body_a1.get("outcome") == "ok", "A1c: /ask captain outcome ok")
check(body_a1.get("supported") is True, "A1d: /ask captain supported")
check(body_a1.get("captain") is not None, "A1e: /ask captain metadata present")
debug_a1 = body_a1.get("debug") or {}
check(debug_a1.get("classification_source") == "llm_classifier", "A1f: /ask debug.classification_source == 'llm_classifier'")

# A2: comparison natural phrasing via /ask with debug=True + classifier stub
fpl_server._init_bootstrap(BS)
fpl_server._init_classifier_client(COMPARISON_STUB)
client = _http_client()
resp_a2 = client.post("/ask", json={
    "question": "what's the score differential between Salah and Haaland?",
    "debug": True,
})
_reset_classifier()
body_a2: dict = {}
try:
    body_a2 = resp_a2.json()
except Exception:
    pass
check(resp_a2.status_code == 200, "A2: /ask status 200 with comparison stub")
check(body_a2.get("intent") == "compare_players", "A2b: /ask comparison intent")
check(body_a2.get("outcome") == "ok", "A2c: /ask comparison outcome ok")
check(body_a2.get("comparison") is not None, "A2d: /ask comparison metadata present")
debug_a2 = body_a2.get("debug") or {}
check(debug_a2.get("classification_source") == "llm_classifier", "A2e: /ask comparison classification_source")

# A3: ranking natural phrasing via /ask + classifier stub + candidates_list
fpl_server._init_bootstrap(BS)
fpl_server._init_classifier_client(RANKING_STUB)
client = _http_client()
resp_a3 = client.post("/ask", json={
    "question": "who looks best for captain this week?",
    "debug": True,
    "candidates_list": CANDIDATES,
})
_reset_classifier()
body_a3: dict = {}
try:
    body_a3 = resp_a3.json()
except Exception:
    pass
check(resp_a3.status_code == 200, "A3: /ask status 200 with ranking stub")
check(body_a3.get("intent") == "rank_candidates", "A3b: /ask ranking intent")
check(body_a3.get("captain_ranking") is not None, "A3c: /ask captain_ranking present")
debug_a3 = body_a3.get("debug") or {}
check(debug_a3.get("classification_source") == "llm_classifier", "A3d: /ask ranking classification_source")

# A4: without classifier, same question returns unsupported (no classification_source)
fpl_server._init_bootstrap(BS)
_reset_classifier()
client = _http_client()
resp_a4 = client.post("/ask", json={"question": "is Saka worth captaining?", "debug": True})
body_a4: dict = {}
try:
    body_a4 = resp_a4.json()
except Exception:
    pass
check(body_a4.get("intent") == "unsupported", "A4: no classifier -> unsupported intent on HTTP")
debug_a4 = body_a4.get("debug") or {}
check(debug_a4.get("classification_source") is None, "A4b: no classifier -> classification_source None on HTTP")

# A5: _init_classifier_client(None) resets properly
fpl_server._init_classifier_client(CAPTAIN_STUB)
_reset_classifier()
check(fpl_server._classifier_client is None, "A5: _init_classifier_client(None) resets to None")

# A6: classification_source absent from non-debug HTTP response
fpl_server._init_bootstrap(BS)
fpl_server._init_classifier_client(CAPTAIN_STUB)
client = _http_client()
resp_a6 = client.post("/ask", json={"question": "is Saka worth captaining?"})
_reset_classifier()
body_a6: dict = {}
try:
    body_a6 = resp_a6.json()
except Exception:
    pass
check("classification_source" not in body_a6, "A6: classification_source absent from non-debug HTTP body")
check(body_a6.get("captain") is not None, "A6b: captain still present in non-debug response")


# ---------------------------------------------------------------------------
# Section B -- Session CLI classifier threading (18)
# ---------------------------------------------------------------------------

section("B -- Session CLI classifier threading")

# B1: captain natural phrasing via run_session() with classifier_client
turns_b1 = cli_run_session(
    ["is Saka worth captaining?"],
    BS,
    debug=True,
    classifier_client=CAPTAIN_STUB,
)
last_b1 = turns_b1[-1] if turns_b1 else {}
check(len(turns_b1) == 1, "B1: run_session returns 1 turn")
check(last_b1.get("intent") == "captain_score", "B1b: session captain intent")
check(last_b1.get("outcome") == "ok", "B1c: session captain outcome ok")
check(last_b1.get("supported") is True, "B1d: session captain supported")
check(last_b1.get("captain") is not None, "B1e: session captain metadata present")
dbg_b1 = last_b1.get("debug") or {}
check(dbg_b1.get("classification_source") == "llm_classifier", "B1f: session captain classification_source")

# B2: comparison natural phrasing via run_session() with classifier_client
turns_b2 = cli_run_session(
    ["what's the score differential between Salah and Haaland?"],
    BS,
    debug=True,
    classifier_client=COMPARISON_STUB,
)
last_b2 = turns_b2[-1] if turns_b2 else {}
check(last_b2.get("intent") == "compare_players", "B2: session comparison intent")
check(last_b2.get("comparison") is not None, "B2b: session comparison metadata present")
dbg_b2 = last_b2.get("debug") or {}
check(dbg_b2.get("classification_source") == "llm_classifier", "B2c: session comparison classification_source")

# B3: ranking natural phrasing via run_session() with classifier_client + candidates_list
turns_b3 = cli_run_session(
    ["who looks best for captain this week?"],
    BS,
    debug=True,
    classifier_client=RANKING_STUB,
    candidates_list=CANDIDATES,
)
last_b3 = turns_b3[-1] if turns_b3 else {}
check(last_b3.get("intent") == "rank_candidates", "B3: session ranking intent")
check(last_b3.get("captain_ranking") is not None, "B3b: session captain_ranking present")
dbg_b3 = last_b3.get("debug") or {}
check(dbg_b3.get("classification_source") == "llm_classifier", "B3c: session ranking classification_source")

# B4: multi-turn session -- classifier fires on natural-phrasing turn
turns_b4 = cli_run_session(
    ["should I captain Salah", "is Saka worth captaining?"],
    BS,
    debug=True,
    classifier_client=CAPTAIN_STUB,
)
check(len(turns_b4) == 2, "B4: 2-turn session returns 2 turns")
last_b4 = turns_b4[-1]
check(last_b4.get("intent") == "captain_score", "B4b: second turn captain intent")
dbg_b4 = last_b4.get("debug") or {}
check(dbg_b4.get("classification_source") == "llm_classifier", "B4c: second turn classification_source")

# B5: without classifier, same natural phrasing is unsupported
turns_b5 = cli_run_session(
    ["is Saka worth captaining?"],
    BS,
    debug=True,
)
last_b5 = turns_b5[-1] if turns_b5 else {}
check(last_b5.get("intent") == "unsupported", "B5: no classifier -> unsupported in session")
dbg_b5 = last_b5.get("debug") or {}
check(dbg_b5.get("classification_source") is None, "B5b: no classifier -> classification_source None in session")


# ---------------------------------------------------------------------------
# Section C -- Session HTTP classifier injection (22)
# ---------------------------------------------------------------------------

section("C -- Session HTTP classifier injection")

def _make_session_http_client() -> tuple[TestClient, str]:
    """Create a TestClient + session_id pair, return both."""
    fpl_server._init_bootstrap(BS)
    fpl_server._clear_sessions()
    c = TestClient(fpl_server.app, raise_server_exceptions=True)
    r = c.post("/session")
    return c, r.json()["session_id"]


# C1: captain natural phrasing via session HTTP with classifier stub
fpl_server._init_classifier_client(CAPTAIN_STUB)
c_c1, sid_c1 = _make_session_http_client()
resp_c1 = c_c1.post(f"/session/{sid_c1}/ask", json={
    "question": "is Saka worth captaining?",
    "debug": True,
})
c_c1.delete(f"/session/{sid_c1}")
_reset_classifier()
body_c1: dict = {}
try:
    body_c1 = resp_c1.json()
except Exception:
    pass
check(resp_c1.status_code == 200, "C1: session_http /ask status 200 with captain stub")
check(body_c1.get("intent") == "captain_score", "C1b: session_http captain intent")
check(body_c1.get("outcome") == "ok", "C1c: session_http captain outcome ok")
check(body_c1.get("captain") is not None, "C1d: session_http captain metadata present")
dbg_c1 = body_c1.get("debug") or {}
check(dbg_c1.get("classification_source") == "llm_classifier", "C1e: session_http captain classification_source")

# C2: comparison natural phrasing via session HTTP with classifier stub
fpl_server._init_classifier_client(COMPARISON_STUB)
c_c2, sid_c2 = _make_session_http_client()
resp_c2 = c_c2.post(f"/session/{sid_c2}/ask", json={
    "question": "what's the score differential between Salah and Haaland?",
    "debug": True,
})
c_c2.delete(f"/session/{sid_c2}")
_reset_classifier()
body_c2: dict = {}
try:
    body_c2 = resp_c2.json()
except Exception:
    pass
check(resp_c2.status_code == 200, "C2: session_http comparison status 200")
check(body_c2.get("intent") == "compare_players", "C2b: session_http comparison intent")
check(body_c2.get("comparison") is not None, "C2c: session_http comparison metadata present")
dbg_c2 = body_c2.get("debug") or {}
check(dbg_c2.get("classification_source") == "llm_classifier", "C2d: session_http comparison classification_source")

# C3: ranking natural phrasing via session HTTP with classifier stub + candidates_list
fpl_server._init_classifier_client(RANKING_STUB)
c_c3, sid_c3 = _make_session_http_client()
resp_c3 = c_c3.post(f"/session/{sid_c3}/ask", json={
    "question": "who looks best for captain this week?",
    "debug": True,
    "candidates_list": CANDIDATES,
})
c_c3.delete(f"/session/{sid_c3}")
_reset_classifier()
body_c3: dict = {}
try:
    body_c3 = resp_c3.json()
except Exception:
    pass
check(resp_c3.status_code == 200, "C3: session_http ranking status 200")
check(body_c3.get("intent") == "rank_candidates", "C3b: session_http ranking intent")
check(body_c3.get("captain_ranking") is not None, "C3c: session_http captain_ranking present")
dbg_c3 = body_c3.get("debug") or {}
check(dbg_c3.get("classification_source") == "llm_classifier", "C3d: session_http ranking classification_source")

# C4: multi-turn session HTTP -- classifier fires on second turn
fpl_server._init_classifier_client(CAPTAIN_STUB)
c_c4, sid_c4 = _make_session_http_client()
c_c4.post(f"/session/{sid_c4}/ask", json={"question": "should I captain Salah"})
resp_c4_2 = c_c4.post(f"/session/{sid_c4}/ask", json={
    "question": "is Saka worth captaining?",
    "debug": True,
})
c_c4.delete(f"/session/{sid_c4}")
_reset_classifier()
body_c4_2: dict = {}
try:
    body_c4_2 = resp_c4_2.json()
except Exception:
    pass
check(resp_c4_2.status_code == 200, "C4: session_http 2nd-turn status 200")
check(body_c4_2.get("intent") == "captain_score", "C4b: session_http 2nd-turn captain intent")
dbg_c4_2 = body_c4_2.get("debug") or {}
check(dbg_c4_2.get("classification_source") == "llm_classifier", "C4c: session_http 2nd-turn classification_source")

# C5: stub is scoped per-request -- after reset, natural phrasing is unsupported
fpl_server._init_classifier_client(CAPTAIN_STUB)
_reset_classifier()
c_c5, sid_c5 = _make_session_http_client()
resp_c5 = c_c5.post(f"/session/{sid_c5}/ask", json={
    "question": "is Saka worth captaining?",
    "debug": True,
})
c_c5.delete(f"/session/{sid_c5}")
body_c5: dict = {}
try:
    body_c5 = resp_c5.json()
except Exception:
    pass
check(body_c5.get("intent") == "unsupported", "C5: after reset, natural phrasing is unsupported on session_http")
dbg_c5 = body_c5.get("debug") or {}
check(dbg_c5.get("classification_source") is None, "C5b: after reset, classification_source None on session_http")


# ---------------------------------------------------------------------------
# Section D -- Cross-surface parity for all 3 classifier scenarios (15)
# ---------------------------------------------------------------------------

section("D -- Cross-surface parity")

# D1: captain scenario -- all 4 surfaces agree on intent/outcome/supported/captain
fpl_server._init_bootstrap(BS)

# CLI
exit_d1, out_d1 = cli_run("is Saka worth captaining?", BS, debug=True, classifier_client=CAPTAIN_STUB)
body_d1_cli: dict = {}
try:
    body_d1_cli = json.loads(out_d1)
except Exception:
    pass

# HTTP
fpl_server._init_classifier_client(CAPTAIN_STUB)
resp_d1_http = _http_client().post("/ask", json={"question": "is Saka worth captaining?"})
_reset_classifier()
body_d1_http: dict = {}
try:
    body_d1_http = resp_d1_http.json()
except Exception:
    pass

# session CLI
turns_d1 = cli_run_session(["is Saka worth captaining?"], BS, debug=True, classifier_client=CAPTAIN_STUB)
last_d1_cli = turns_d1[-1] if turns_d1 else {}

# session HTTP
fpl_server._init_classifier_client(CAPTAIN_STUB)
c_d1, sid_d1 = _make_session_http_client()
resp_d1_sh = c_d1.post(f"/session/{sid_d1}/ask", json={"question": "is Saka worth captaining?"})
c_d1.delete(f"/session/{sid_d1}")
_reset_classifier()
body_d1_sh: dict = {}
try:
    body_d1_sh = resp_d1_sh.json()
except Exception:
    pass

all_d1 = [
    ("cli",          body_d1_cli),
    ("http",         body_d1_http),
    ("session_cli",  last_d1_cli),
    ("session_http", body_d1_sh),
]
for surf, result in all_d1:
    check(result.get("intent") == "captain_score", f"D1: captain parity intent [{surf}]")
    check(result.get("outcome") == "ok", f"D1b: captain parity outcome [{surf}]")
    check(result.get("supported") is True, f"D1c: captain parity supported [{surf}]")
    check(result.get("captain") is not None, f"D1d: captain parity captain metadata [{surf}]")


# ---------------------------------------------------------------------------
# Section E -- Validation corpus surface update (9)
# ---------------------------------------------------------------------------

section("E -- Validation corpus surface update")

# E1: all 3 Phase 4k scenarios now include all 4 surfaces
_ALL_4_SURFACES = {"cli", "http", "session_cli", "session_http"}
for sid in PHASE4K_IDS:
    s = SCENARIO_BY_ID[sid]
    surfaces_set = set(s.surfaces)
    check(
        _ALL_4_SURFACES.issubset(surfaces_set),
        f"E1: '{sid}' includes all 4 surfaces (got {sorted(surfaces_set)})",
    )

# E2: scenarios still have requires_stub='classifier' and non-None classifier_stub_json
for sid in PHASE4K_IDS:
    s = SCENARIO_BY_ID[sid]
    check(s.requires_stub == "classifier", f"E2: '{sid}' requires_stub preserved")
    check(s.classifier_stub_json is not None, f"E2b: '{sid}' classifier_stub_json preserved")


# ---------------------------------------------------------------------------
# Section F -- Regression: deterministic routes unchanged on new surfaces (18)
# ---------------------------------------------------------------------------

section("F -- Regression: deterministic routes unchanged on new surfaces")

DET_QUESTIONS = [
    ("should I captain Salah", "captain_score", "ok"),
    ("compare Haaland and Salah", "compare_players", "ok"),
]

for q_f, exp_intent, exp_outcome in DET_QUESTIONS:
    # HTTP surface without classifier
    fpl_server._init_bootstrap(BS)
    _reset_classifier()
    resp_f_http = _http_client().post("/ask", json={"question": q_f})
    bf_http: dict = {}
    try:
        bf_http = resp_f_http.json()
    except Exception:
        pass
    check(bf_http.get("intent") == exp_intent, f"F: HTTP '{q_f}' -> intent={exp_intent}")
    check(bf_http.get("outcome") == exp_outcome, f"F: HTTP '{q_f}' -> outcome={exp_outcome}")

    # session CLI without classifier
    turns_f = cli_run_session([q_f], BS, debug=True)
    last_f = turns_f[-1] if turns_f else {}
    check(last_f.get("intent") == exp_intent, f"F: session_cli '{q_f}' -> intent={exp_intent}")
    check(last_f.get("outcome") == exp_outcome, f"F: session_cli '{q_f}' -> outcome={exp_outcome}")
    dbg_f = last_f.get("debug") or {}
    check(dbg_f.get("classification_source") is None, f"F: session_cli '{q_f}' -> classification_source None")

    # session HTTP without classifier
    fpl_server._init_bootstrap(BS)
    _reset_classifier()
    c_f, sid_f = _make_session_http_client()
    resp_f_sh = c_f.post(f"/session/{sid_f}/ask", json={"question": q_f})
    c_f.delete(f"/session/{sid_f}")
    bfsh: dict = {}
    try:
        bfsh = resp_f_sh.json()
    except Exception:
        pass
    check(bfsh.get("intent") == exp_intent, f"F: session_http '{q_f}' -> intent={exp_intent}")
    check(bfsh.get("outcome") == exp_outcome, f"F: session_http '{q_f}' -> outcome={exp_outcome}")


# ---------------------------------------------------------------------------
# Section G -- Fallback safety on new surfaces (11)
# ---------------------------------------------------------------------------

section("G -- Fallback safety on new surfaces")

# G1: bad JSON stub on HTTP -> unsupported intent, no exception
fpl_server._init_bootstrap(BS)
fpl_server._init_classifier_client(BAD_JSON_STUB)
resp_g1 = _http_client().post("/ask", json={"question": "is Saka worth captaining?"})
_reset_classifier()
body_g1: dict = {}
try:
    body_g1 = resp_g1.json()
except Exception:
    pass
check(resp_g1.status_code == 200, "G1: bad JSON stub on HTTP -> status 200 (no crash)")
check(body_g1.get("intent") == "unsupported", "G1b: bad JSON stub on HTTP -> unsupported intent")

# G2: low confidence stub on HTTP -> unsupported
fpl_server._init_bootstrap(BS)
fpl_server._init_classifier_client(LOW_CONF_STUB)
resp_g2 = _http_client().post("/ask", json={"question": "is Saka worth captaining?"})
_reset_classifier()
body_g2: dict = {}
try:
    body_g2 = resp_g2.json()
except Exception:
    pass
check(body_g2.get("intent") == "unsupported", "G2: low confidence on HTTP -> unsupported")

# G3: bad JSON stub on session CLI -> unsupported, no exception
try:
    turns_g3 = cli_run_session(
        ["is Saka worth captaining?"], BS, debug=True, classifier_client=BAD_JSON_STUB,
    )
    last_g3 = turns_g3[-1] if turns_g3 else {}
    check(last_g3.get("intent") == "unsupported", "G3: bad JSON stub on session_cli -> unsupported")
    check(True, "G3b: run_session() did not raise with bad JSON stub")
except Exception as exc:
    check(False, f"G3: run_session() raised unexpectedly: {exc}")
    check(False, "G3b: run_session() did not raise with bad JSON stub")

# G4: bad JSON stub on session HTTP -> unsupported, no crash
fpl_server._init_classifier_client(BAD_JSON_STUB)
c_g4, sid_g4 = _make_session_http_client()
resp_g4 = c_g4.post(f"/session/{sid_g4}/ask", json={"question": "is Saka worth captaining?"})
c_g4.delete(f"/session/{sid_g4}")
_reset_classifier()
body_g4: dict = {}
try:
    body_g4 = resp_g4.json()
except Exception:
    pass
check(resp_g4.status_code == 200, "G4: bad JSON stub on session_http -> status 200 (no crash)")
check(body_g4.get("intent") == "unsupported", "G4b: bad JSON stub on session_http -> unsupported intent")

# G5: None classifier on all surfaces -> same result as without classifier
fpl_server._init_bootstrap(BS)
_reset_classifier()
resp_g5_http = _http_client().post("/ask", json={"question": "should I captain Salah"})
body_g5_http: dict = {}
try:
    body_g5_http = resp_g5_http.json()
except Exception:
    pass
check(body_g5_http.get("intent") == "captain_score", "G5: None classifier on HTTP -> deterministic routing still works")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*50}")
print(f"Phase 4l: {_PASS}/{total} PASS")
if _FAIL:
    print(f"          {_FAIL} FAIL")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
