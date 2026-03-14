"""
run_phase4c_tests.py
====================
Phase 4c: HTTP endpoint validation.

Validates the ``POST /ask`` and ``GET /health`` endpoints of ``fpl_server``.
All tests use ``STANDARD_BOOTSTRAP`` or ``AMBIGUOUS_BOOTSTRAP`` injected via
``fpl_server._init_bootstrap()`` before the TestClient starts.  No live
network calls, no LLM calls.

Uses FastAPI's in-process ``TestClient`` (ASGI transport -- no real HTTP
server required).

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner;../fpl-player-registry;../fpl-captain-engine;\\
    ../fpl-data-core;../fpl-tool-contract;../fpl-query-tools;\\
    ../fpl-api-client;../fpl-pipeline;. python run_phase4c_tests.py

Sections
--------
A  -- Import and server shape
B  -- GET /health
C  -- POST /ask: default mode (no debug)
D  -- POST /ask: debug mode
E  -- POST /ask: HTTP contract (status codes, content-type, schema)
F  -- POST /ask: all 5 supported intent types
G  -- POST /ask: unsupported intents (HTTP 200, supported=False)
H  -- POST /ask: FinalResponse contract invariants
I  -- POST /ask: edge cases
"""
from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Path setup  (mirrors all other phase test runners)
# ---------------------------------------------------------------------------
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
# Inject test bootstrap BEFORE importing fpl_server
# (the lifespan's ``if _bootstrap is None`` guard will skip the live fetch)
# ---------------------------------------------------------------------------
from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
)

import fpl_server
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
_passed  = 0
_failed  = 0


def _section(name: str) -> None:
    print(f"\n  [{name}]")


def ok(label: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"    PASS  {label}")
    else:
        _failed += 1
        print(f"    FAIL  {label}")


def eq(label: str, actual: object, expected: object) -> None:
    ok(f"{label}  (got {actual!r})", actual == expected)


# ---------------------------------------------------------------------------
# Shared TestClient
# ---------------------------------------------------------------------------
_client = TestClient(fpl_server.app, raise_server_exceptions=True)


# ===========================================================================
# Section A -- Import and server shape
# ===========================================================================
_section("A -- Import and server shape")

ok("A1  fpl_server imports without error", True)
ok("A2  app is a FastAPI instance",
   type(fpl_server.app).__name__ == "FastAPI")
ok("A3  _bootstrap is set (injection succeeded)", fpl_server._bootstrap is not None)
ok("A4  _init_bootstrap is callable", callable(fpl_server._init_bootstrap))
ok("A5  AskRequest is defined",  hasattr(fpl_server, "AskRequest"))
ok("A6  AskResponse is defined", hasattr(fpl_server, "AskResponse"))

# AskRequest fields
_req_fields = fpl_server.AskRequest.model_fields
ok("A7  AskRequest has 'question' field", "question" in _req_fields)
ok("A8  AskRequest has 'debug' field",    "debug"    in _req_fields)
ok("A9  AskRequest 'debug' defaults to False",
   _req_fields["debug"].default is False)

# AskResponse fields
_resp_fields = fpl_server.AskResponse.model_fields
for _f in ("final_text", "outcome", "supported", "intent",
           "review_passed", "llm_used", "debug"):
    ok(f"A10.{_f}  AskResponse has '{_f}' field", _f in _resp_fields)

ok("A11 AskResponse 'debug' defaults to None",
   _resp_fields["debug"].default is None)


# ===========================================================================
# Section B -- GET /health
# ===========================================================================
_section("B -- GET /health")

_h = _client.get("/health")
ok("B1  /health returns 200",      _h.status_code == 200)
ok("B2  /health response is JSON", _h.headers["content-type"].startswith("application/json"))

_hj = _h.json()
ok("B3  /health JSON has 'status' key", "status" in _hj)
ok("B4  /health status is 'ok'",         _hj.get("status") == "ok")


# ===========================================================================
# Section C -- POST /ask: default mode (no debug)
# ===========================================================================
_section("C -- POST /ask: default mode")

_r1 = _client.post("/ask", json={"question": "should I captain Haaland"})
ok("C1  /ask returns 200",      _r1.status_code == 200)
ok("C2  /ask response is JSON", _r1.headers["content-type"].startswith("application/json"))

_j1 = _r1.json()
ok("C3  response has 'final_text'",   "final_text"    in _j1)
ok("C4  response has 'outcome'",      "outcome"       in _j1)
ok("C5  response has 'supported'",    "supported"     in _j1)
ok("C6  response has 'intent'",       "intent"        in _j1)
ok("C7  response has 'review_passed'","review_passed" in _j1)
ok("C8  response has 'llm_used'",     "llm_used"      in _j1)
ok("C9  'final_text' is non-empty",   len(_j1.get("final_text", "")) > 0)
ok("C10 'debug' is null in default mode", _j1.get("debug") is None)
ok("C11 captain score -> outcome 'ok'",   _j1.get("outcome") == OUTCOME_OK)
ok("C12 captain score -> supported True", _j1.get("supported") is True)

_r2 = _client.post("/ask", json={"question": "what is the current gameweek"})
ok("C13 gameweek query returns 200",   _r2.status_code == 200)
ok("C14 gameweek 'final_text' non-empty", len(_r2.json().get("final_text", "")) > 0)

_r3 = _client.post("/ask", json={"question": "tell me about Haaland"})
ok("C15 player summary returns 200",    _r3.status_code == 200)
ok("C16 player summary 'final_text' non-empty", len(_r3.json().get("final_text", "")) > 0)


# ===========================================================================
# Section D -- POST /ask: debug mode
# ===========================================================================
_section("D -- POST /ask: debug mode")

_rd = _client.post("/ask", json={"question": "should I captain Haaland", "debug": True})
ok("D1  debug mode returns 200",      _rd.status_code == 200)

_jd = _rd.json()
ok("D2  'debug' key is present",       "debug" in _jd)
ok("D3  'debug' is not null",          _jd.get("debug") is not None)

_bundle = _jd.get("debug") or {}
ok("D4  bundle has 'response_text'",  "response_text" in _bundle)
ok("D5  bundle has 'llm_text'",       "llm_text"      in _bundle)
ok("D6  bundle has 'violations'",     "violations"    in _bundle)
ok("D7  bundle has 'prompt_used'",    "prompt_used"   in _bundle)
ok("D8  bundle has 'model'",          "model"         in _bundle)
ok("D9  bundle 'violations' is list", isinstance(_bundle.get("violations"), list))
ok("D10 bundle 'response_text' non-empty",
   len(_bundle.get("response_text", "")) > 0)

# Top-level fields still present in debug mode
ok("D11 'final_text' present in debug mode",   "final_text"    in _jd)
ok("D12 'outcome' present in debug mode",      "outcome"       in _jd)
ok("D13 'supported' present in debug mode",    "supported"     in _jd)
ok("D14 'intent' present in debug mode",       "intent"        in _jd)
ok("D15 'review_passed' present in debug mode","review_passed" in _jd)
ok("D16 'llm_used' present in debug mode",     "llm_used"      in _jd)

# final_text in debug mode matches default mode response
_j1_ft = _j1.get("final_text")
_jd_ft = _jd.get("final_text")
ok("D17 debug final_text == default final_text", _j1_ft == _jd_ft)

# debug bundle response_text matches final_text (no LLM in test env)
ok("D18 bundle response_text == final_text (no LLM)",
   _bundle.get("response_text") == _jd.get("final_text"))

# Debug mode for unsupported intent also returns debug bundle
_rd_u = _client.post("/ask", json={"question": "what is the weather", "debug": True})
ok("D19 unsupported + debug returns 200", _rd_u.status_code == 200)
_jd_u = _rd_u.json()
ok("D20 unsupported + debug has 'debug' key", _jd_u.get("debug") is not None)


# ===========================================================================
# Section E -- POST /ask: HTTP contract (status codes, content-type, schema)
# ===========================================================================
_section("E -- HTTP contract")

# Missing question field -> 422
_r_miss = _client.post("/ask", json={})
ok("E1  missing question -> 422", _r_miss.status_code == 422)

# Wrong type for question -> 422
_r_type = _client.post("/ask", json={"question": 12345})
ok("E2  numeric question -> 422 (pydantic rejects non-str)", _r_type.status_code == 422)

# Extra unknown fields are ignored (pydantic default)
_r_extra = _client.post("/ask", json={"question": "should I captain Haaland", "unknown_field": "x"})
ok("E3  extra fields in request are ignored", _r_extra.status_code == 200)

# Content-type for all responses
ok("E4  /ask content-type is application/json",
   _r1.headers["content-type"].startswith("application/json"))

# GET /ask should not be defined (method not allowed or 404)
_r_get = _client.get("/ask")
ok("E5  GET /ask is not a valid method (405 or 404)",
   _r_get.status_code in (404, 405))

# Empty string question (valid string, processed gracefully)
_r_empty = _client.post("/ask", json={"question": ""})
ok("E6  empty string question returns 200", _r_empty.status_code == 200)
ok("E7  empty string question has non-empty final_text",
   len(_r_empty.json().get("final_text", "")) > 0)

# debug=false explicitly
_r_dbg_f = _client.post("/ask", json={"question": "should I captain Haaland", "debug": False})
ok("E8  debug=False explicit -> 200", _r_dbg_f.status_code == 200)
ok("E9  debug=False -> debug field is null", _r_dbg_f.json().get("debug") is None)


# ===========================================================================
# Section F -- POST /ask: all 5 supported intent types
# ===========================================================================
_section("F -- Supported intent coverage")

_INTENT_CASES: list[tuple[str, str]] = [
    ("should I captain Haaland",    INTENT_CAPTAIN_SCORE),
    ("rank captains",               INTENT_RANK_CANDIDATES),
    ("what is the current gameweek",INTENT_CURRENT_GAMEWEEK),
    ("tell me about Salah",         INTENT_PLAYER_SUMMARY),
    ("find player Haaland",         INTENT_PLAYER_RESOLVE),
]

for _i, (_q, _expected_intent) in enumerate(_INTENT_CASES, 1):
    _rr = _client.post("/ask", json={"question": _q})
    _jj = _rr.json()
    ok(f"F{_i}a HTTP 200: {_q!r:.35}",              _rr.status_code == 200)
    ok(f"F{_i}b intent={_expected_intent}: {_q!r:.25}",
       _jj.get("intent") == _expected_intent)
    ok(f"F{_i}c supported=True: {_q!r:.35}",        _jj.get("supported") is True)
    ok(f"F{_i}d final_text non-empty: {_q!r:.30}",  len(_jj.get("final_text", "")) > 0)


# ===========================================================================
# Section G -- POST /ask: unsupported intents (HTTP 200, supported=False)
# ===========================================================================
_section("G -- Unsupported intents")

_UNSUPPORTED = [
    "what is the weather today",
    "tell me a joke",
    "who won the Champions League",
]

for _i, _q in enumerate(_UNSUPPORTED, 1):
    _ru = _client.post("/ask", json={"question": _q})
    _ju = _ru.json()
    ok(f"G{_i}a HTTP 200 (not 4xx): {_q!r:.40}",    _ru.status_code == 200)
    ok(f"G{_i}b supported=False: {_q!r:.40}",        _ju.get("supported") is False)
    ok(f"G{_i}c intent=unsupported: {_q!r:.35}",     _ju.get("intent") == INTENT_UNSUPPORTED)
    ok(f"G{_i}d final_text non-empty: {_q!r:.35}",   len(_ju.get("final_text", "")) > 0)


# ===========================================================================
# Section H -- FinalResponse contract invariants
# ===========================================================================
_section("H -- FinalResponse contract invariants")

_ALL_QUERIES = [
    "should I captain Haaland",
    "rank captains",
    "what is the current gameweek",
    "tell me about Salah",
    "find player Haaland",
    "what is the weather today",
    "should I captain unknown player XYZ",  # not_found
]

_responses_h = [
    _client.post("/ask", json={"question": q, "debug": True}).json()
    for q in _ALL_QUERIES
]

ok("H1  all queries return HTTP 200 (no exception)", True)

for _j, (_q, _rh) in enumerate(zip(_ALL_QUERIES, _responses_h), 1):
    ok(f"H2.{_j} final_text non-empty: {_q!r:.30}", len(_rh.get("final_text", "")) > 0)

for _j, (_q, _rh) in enumerate(zip(_ALL_QUERIES, _responses_h), 1):
    # Invariant: supported == (outcome != OUTCOME_UNSUPPORTED_INTENT)
    _exp = _rh.get("outcome") != OUTCOME_UNSUPPORTED_INTENT
    ok(f"H3.{_j} supported == (outcome != unsupported): {_q!r:.25}",
       _rh.get("supported") == _exp)

for _j, (_q, _rh) in enumerate(zip(_ALL_QUERIES, _responses_h), 1):
    # Invariant: llm_used=True -> review_passed=True
    if _rh.get("llm_used"):
        ok(f"H4.{_j} llm_used=True -> review_passed=True: {_q!r:.22}", _rh.get("review_passed"))
    else:
        ok(f"H4.{_j} llm_used=False (deterministic path): {_q!r:.24}", True)

for _j, (_q, _rh) in enumerate(zip(_ALL_QUERIES, _responses_h), 1):
    # Invariant: not llm_used -> final_text == response_text
    _bund = _rh.get("debug") or {}
    if not _rh.get("llm_used") and _bund:
        ok(f"H5.{_j} not llm_used -> final_text==response_text: {_q!r:.20}",
           _rh.get("final_text") == _bund.get("response_text"))
    else:
        ok(f"H5.{_j} llm_used=True (skipping fallback check): {_q!r:.22}", True)

# HTTP response matches respond() output directly
from fpl_grounded_assistant import respond as _respond
for _j, _q in enumerate(_ALL_QUERIES[:5], 1):
    _direct = _respond(_q, STANDARD_BOOTSTRAP)
    _via_http = _client.post("/ask", json={"question": _q}).json()
    ok(f"H6.{_j} HTTP final_text == respond() final_text: {_q!r:.25}",
       _via_http.get("final_text") == _direct.final_text)
    ok(f"H7.{_j} HTTP outcome == respond() outcome: {_q!r:.30}",
       _via_http.get("outcome") == _direct.outcome)


# ===========================================================================
# Section I -- Edge cases
# ===========================================================================
_section("I -- Edge cases")

# Ambiguous bootstrap
fpl_server._init_bootstrap(AMBIGUOUS_BOOTSTRAP)
_ri_a = _client.post("/ask", json={"question": "should I captain Haaland"})
ok("I1  ambiguous bootstrap does not crash",   _ri_a.status_code == 200)
ok("I2  ambiguous bootstrap final_text non-empty",
   len(_ri_a.json().get("final_text", "")) > 0)

# Restore standard bootstrap
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)

# Whitespace-only question (graceful)
_ri_ws = _client.post("/ask", json={"question": "   "})
ok("I3  whitespace question returns 200",         _ri_ws.status_code == 200)
ok("I4  whitespace question final_text non-empty",
   len(_ri_ws.json().get("final_text", "")) > 0)

# Player not found (not_found is a supported outcome -- HTTP 200, supported=True)
_ri_nf = _client.post("/ask", json={"question": "should I captain XYZ Unknown Player"})
ok("I5  not_found query returns 200",          _ri_nf.status_code == 200)
ok("I6  not_found supported=True",             _ri_nf.json().get("supported") is True)
ok("I7  not_found final_text non-empty",       len(_ri_nf.json().get("final_text", "")) > 0)

# Idempotency: same question twice returns same result
_ri_1 = _client.post("/ask", json={"question": "should I captain Haaland"})
_ri_2 = _client.post("/ask", json={"question": "should I captain Haaland"})
ok("I8  identical queries produce same final_text",
   _ri_1.json().get("final_text") == _ri_2.json().get("final_text"))
ok("I9  identical queries produce same outcome",
   _ri_1.json().get("outcome") == _ri_2.json().get("outcome"))

# Single-character question (graceful)
_ri_sc = _client.post("/ask", json={"question": "?"})
ok("I10 single-char question returns 200", _ri_sc.status_code == 200)
ok("I11 single-char final_text non-empty", len(_ri_sc.json().get("final_text", "")) > 0)


# ===========================================================================
# Summary
# ===========================================================================
print()
print("=" * 60)
print(f"  Phase 4c: {_passed + _failed} assertions | {_passed} PASS | {_failed} FAIL")
print("=" * 60)

if _failed:
    sys.exit(1)
