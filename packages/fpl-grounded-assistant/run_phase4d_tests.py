"""
run_phase4d_tests.py
====================
Phase 4d: external integration examples and client fixtures.

Validates the example files in ``examples/`` against expected outcomes.
All tests use ``STANDARD_BOOTSTRAP`` or ``AMBIGUOUS_BOOTSTRAP`` — no live
network calls, no LLM calls.

Sections
--------
A  -- examples package imports and structure
B  -- CLI scenario definitions (field contract)
C  -- CLI supported_ok scenario
D  -- CLI supported_ambiguous scenario
E  -- CLI supported_not_found scenario
F  -- CLI supported_missing_arguments scenario
G  -- CLI unsupported_intent scenario
H  -- CLI cross-scenario invariants
I  -- HTTP example imports and structure
J  -- HTTP supported_ok scenario
K  -- HTTP supported_ambiguous scenario
L  -- HTTP supported_not_found scenario
M  -- HTTP supported_missing_arguments scenario
N  -- HTTP unsupported_intent scenario
O  -- HTTP edge cases (422 malformed, 503 service not ready)
P  -- HTTP GET /health
Q  -- Cross-interface contract invariants

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner;../fpl-player-registry;../fpl-captain-engine;\\
    ../fpl-data-core;../fpl-tool-contract;../fpl-query-tools;\\
    ../fpl-api-client;../fpl-pipeline;. python run_phase4d_tests.py
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path setup
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
# Bootstrap injection BEFORE importing fpl_server
# (lifespan's ``if _bootstrap is None`` guard skips the live fetch)
# ---------------------------------------------------------------------------
from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
)

import fpl_server
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)

from fastapi.testclient import TestClient

from examples.cli_examples import (
    CLI_SCENARIOS,
    run_cli_scenario,
)
from examples.http_examples import (
    HTTP_SCENARIOS,
    HTTP_EDGE_CASES,
    run_http_scenario,
    make_client,
)

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
_passed = 0
_failed = 0


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


# ===========================================================================
# Section A -- examples package imports and structure
# ===========================================================================
_section("A -- examples package imports and structure")

ok("A1  examples package imports without error", True)
ok("A2  CLI_SCENARIOS is a list",      isinstance(CLI_SCENARIOS, list))
ok("A3  CLI_SCENARIOS has 5 entries",  len(CLI_SCENARIOS) == 5)
ok("A4  HTTP_SCENARIOS is a list",     isinstance(HTTP_SCENARIOS, list))
ok("A5  HTTP_SCENARIOS has 5 entries", len(HTTP_SCENARIOS) == 5)
ok("A6  HTTP_EDGE_CASES is a list",    isinstance(HTTP_EDGE_CASES, list))
ok("A7  HTTP_EDGE_CASES has 2 entries (malformed + not_ready)",
   len(HTTP_EDGE_CASES) == 2)
ok("A8  run_cli_scenario is callable",  callable(run_cli_scenario))
ok("A9  run_http_scenario is callable", callable(run_http_scenario))


# ===========================================================================
# Section B -- CLI scenario definitions (field contract)
# ===========================================================================
_section("B -- CLI scenario definitions (field contract)")

_REQUIRED_CLI_KEYS = {"id", "question", "bootstrap", "expected_exit", "note"}

for _i, _s in enumerate(CLI_SCENARIOS):
    ok(f"B{_i+1}.fields  scenario[{_i}] has all required keys",
       _REQUIRED_CLI_KEYS.issubset(_s.keys()))

_cli_ids = [s["id"] for s in CLI_SCENARIOS]
for _expected_id in (
    "supported_ok",
    "supported_ambiguous",
    "supported_not_found",
    "supported_missing_arguments",
    "unsupported_intent",
):
    ok(f"B.id  CLI_SCENARIOS contains '{_expected_id}'",
       _expected_id in _cli_ids)

_cli_exits = [s["expected_exit"] for s in CLI_SCENARIOS]
ok("B.exits  four scenarios expect exit=0", _cli_exits.count(0) == 4)
ok("B.exits  one scenario expects exit=1",  _cli_exits.count(1) == 1)


# ===========================================================================
# Section C -- CLI supported_ok
# ===========================================================================
_section("C -- CLI supported_ok")

_s_ok = next(s for s in CLI_SCENARIOS if s["id"] == "supported_ok")
_c_ok_code, _c_ok_out = run_cli_scenario(_s_ok)

eq("C1  exit code",        _c_ok_code, 0)
ok("C2  output is a str",  isinstance(_c_ok_out, str))
ok("C3  output non-empty", len(_c_ok_out) > 0)
ok("C4  output is plain text (not JSON)", not _c_ok_out.strip().startswith("{"))


# ===========================================================================
# Section D -- CLI supported_ambiguous
# ===========================================================================
_section("D -- CLI supported_ambiguous")

_s_amb = next(s for s in CLI_SCENARIOS if s["id"] == "supported_ambiguous")
_c_amb_code, _c_amb_out = run_cli_scenario(_s_amb)

eq("D1  exit code",        _c_amb_code, 0)
ok("D2  output is a str",  isinstance(_c_amb_out, str))
ok("D3  output non-empty", len(_c_amb_out) > 0)
ok("D4  output is plain text", not _c_amb_out.strip().startswith("{"))


# ===========================================================================
# Section E -- CLI supported_not_found
# ===========================================================================
_section("E -- CLI supported_not_found")

_s_nf = next(s for s in CLI_SCENARIOS if s["id"] == "supported_not_found")
_c_nf_code, _c_nf_out = run_cli_scenario(_s_nf)

eq("E1  exit code",        _c_nf_code, 0)
ok("E2  output is a str",  isinstance(_c_nf_out, str))
ok("E3  output non-empty", len(_c_nf_out) > 0)
ok("E4  output is plain text", not _c_nf_out.strip().startswith("{"))


# ===========================================================================
# Section F -- CLI supported_missing_arguments
# ===========================================================================
_section("F -- CLI supported_missing_arguments")

_s_ma = next(s for s in CLI_SCENARIOS if s["id"] == "supported_missing_arguments")
_c_ma_code, _c_ma_out = run_cli_scenario(_s_ma)

eq("F1  exit code",        _c_ma_code, 0)
ok("F2  output is a str",  isinstance(_c_ma_out, str))
ok("F3  output non-empty", len(_c_ma_out) > 0)
ok("F4  output is plain text", not _c_ma_out.strip().startswith("{"))


# ===========================================================================
# Section G -- CLI unsupported_intent
# ===========================================================================
_section("G -- CLI unsupported_intent")

_s_ui = next(s for s in CLI_SCENARIOS if s["id"] == "unsupported_intent")
_c_ui_code, _c_ui_out = run_cli_scenario(_s_ui)

eq("G1  exit code",        _c_ui_code, 1)
ok("G2  output is a str",  isinstance(_c_ui_out, str))
ok("G3  output non-empty", len(_c_ui_out) > 0)
ok("G4  output is plain text", not _c_ui_out.strip().startswith("{"))


# ===========================================================================
# Section H -- CLI cross-scenario invariants
# ===========================================================================
_section("H -- CLI cross-scenario invariants")

_all_cli_results = [(s, run_cli_scenario(s)) for s in CLI_SCENARIOS]

ok("H1  all 5 scenarios produce (int, str) pairs",
   all(isinstance(code, int) and isinstance(out, str)
       for _, (code, out) in _all_cli_results))

ok("H2  all exit codes are 0 or 1",
   all(code in (0, 1) for _, (code, _) in _all_cli_results))

ok("H3  all outputs are non-empty strings",
   all(len(out) > 0 for _, (_, out) in _all_cli_results))

ok("H4  exit code matches expected_exit for all scenarios",
   all(code == s["expected_exit"] for s, (code, _) in _all_cli_results))

ok("H5  supported scenarios (exit=0) are the majority (4 of 5)",
   sum(1 for _, (code, _) in _all_cli_results if code == 0) == 4)

ok("H6  exactly one unsupported scenario (exit=1)",
   sum(1 for _, (code, _) in _all_cli_results if code == 1) == 1)


# ===========================================================================
# Section I -- HTTP example imports and structure
# ===========================================================================
_section("I -- HTTP example imports and structure")

ok("I1  HTTP_SCENARIOS imported successfully",    True)
ok("I2  HTTP_EDGE_CASES imported successfully",   True)
ok("I3  run_http_scenario imported successfully", True)

_REQUIRED_HTTP_KEYS = {"id", "payload", "bootstrap", "expected_status", "note"}
_REQUIRED_HTTP_SCENARIO_KEYS = _REQUIRED_HTTP_KEYS | {"expected_supported", "expected_outcome"}

for _i, _s in enumerate(HTTP_SCENARIOS):
    ok(f"I4.{_i}  HTTP_SCENARIOS[{_i}] has all required keys",
       _REQUIRED_HTTP_SCENARIO_KEYS.issubset(_s.keys()))

for _i, _s in enumerate(HTTP_EDGE_CASES):
    ok(f"I5.{_i}  HTTP_EDGE_CASES[{_i}] has required keys",
       _REQUIRED_HTTP_KEYS.issubset(_s.keys()))

_http_ids = [s["id"] for s in HTTP_SCENARIOS]
for _expected_id in (
    "supported_ok",
    "supported_ambiguous",
    "supported_not_found",
    "supported_missing_arguments",
    "unsupported_intent",
):
    ok(f"I6.id  HTTP_SCENARIOS contains '{_expected_id}'",
       _expected_id in _http_ids)

_edge_ids = [s["id"] for s in HTTP_EDGE_CASES]
ok("I7  HTTP_EDGE_CASES contains 'malformed_request'",   "malformed_request"  in _edge_ids)
ok("I8  HTTP_EDGE_CASES contains 'service_not_ready'",   "service_not_ready"  in _edge_ids)


# ===========================================================================
# Section J -- HTTP supported_ok
# ===========================================================================
_section("J -- HTTP supported_ok")

_hs_ok = next(s for s in HTTP_SCENARIOS if s["id"] == "supported_ok")
_h_ok_status, _h_ok_body = run_http_scenario(_hs_ok)

_FINAL_RESPONSE_KEYS = {"final_text", "outcome", "supported", "intent",
                         "review_passed", "llm_used"}

eq("J1  HTTP status",                _h_ok_status, 200)
ok("J2  body has all FinalResponse keys",
   _FINAL_RESPONSE_KEYS.issubset(_h_ok_body.keys()))
eq("J3  supported",                  _h_ok_body.get("supported"),  True)
eq("J4  outcome",                    _h_ok_body.get("outcome"),    OUTCOME_OK)
eq("J5  intent",                     _h_ok_body.get("intent"),     INTENT_CAPTAIN_SCORE)
ok("J6  final_text non-empty",       len(_h_ok_body.get("final_text", "")) > 0)
ok("J7  debug field absent (default mode)",
   _h_ok_body.get("debug") is None)


# ===========================================================================
# Section K -- HTTP supported_ambiguous
# ===========================================================================
_section("K -- HTTP supported_ambiguous")

_hs_amb = next(s for s in HTTP_SCENARIOS if s["id"] == "supported_ambiguous")
_h_amb_status, _h_amb_body = run_http_scenario(_hs_amb)

# Restore standard bootstrap after ambiguous scenario
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)

eq("K1  HTTP status",                _h_amb_status, 200)
ok("K2  body has all FinalResponse keys",
   _FINAL_RESPONSE_KEYS.issubset(_h_amb_body.keys()))
eq("K3  supported",                  _h_amb_body.get("supported"),  True)
eq("K4  outcome",                    _h_amb_body.get("outcome"),    OUTCOME_AMBIGUOUS)
eq("K5  intent",                     _h_amb_body.get("intent"),     INTENT_PLAYER_RESOLVE)
ok("K6  final_text non-empty",       len(_h_amb_body.get("final_text", "")) > 0)


# ===========================================================================
# Section L -- HTTP supported_not_found
# ===========================================================================
_section("L -- HTTP supported_not_found")

_hs_nf = next(s for s in HTTP_SCENARIOS if s["id"] == "supported_not_found")
_h_nf_status, _h_nf_body = run_http_scenario(_hs_nf)

eq("L1  HTTP status",                _h_nf_status, 200)
ok("L2  body has all FinalResponse keys",
   _FINAL_RESPONSE_KEYS.issubset(_h_nf_body.keys()))
eq("L3  supported",                  _h_nf_body.get("supported"),  True)
eq("L4  outcome",                    _h_nf_body.get("outcome"),    OUTCOME_NOT_FOUND)
eq("L5  intent",                     _h_nf_body.get("intent"),     INTENT_CAPTAIN_SCORE)
ok("L6  final_text non-empty",       len(_h_nf_body.get("final_text", "")) > 0)


# ===========================================================================
# Section M -- HTTP supported_missing_arguments
# ===========================================================================
_section("M -- HTTP supported_missing_arguments")

_hs_ma = next(s for s in HTTP_SCENARIOS if s["id"] == "supported_missing_arguments")
_h_ma_status, _h_ma_body = run_http_scenario(_hs_ma)

eq("M1  HTTP status",                _h_ma_status, 200)
ok("M2  body has all FinalResponse keys",
   _FINAL_RESPONSE_KEYS.issubset(_h_ma_body.keys()))
eq("M3  supported",                  _h_ma_body.get("supported"),  True)
eq("M4  outcome",                    _h_ma_body.get("outcome"),    OUTCOME_MISSING_ARGUMENTS)
eq("M5  intent",                     _h_ma_body.get("intent"),     INTENT_RANK_CANDIDATES)
ok("M6  final_text non-empty",       len(_h_ma_body.get("final_text", "")) > 0)


# ===========================================================================
# Section N -- HTTP unsupported_intent
# ===========================================================================
_section("N -- HTTP unsupported_intent")

_hs_ui = next(s for s in HTTP_SCENARIOS if s["id"] == "unsupported_intent")
_h_ui_status, _h_ui_body = run_http_scenario(_hs_ui)

eq("N1  HTTP status",                _h_ui_status, 200)
ok("N2  body has all FinalResponse keys",
   _FINAL_RESPONSE_KEYS.issubset(_h_ui_body.keys()))
eq("N3  supported",                  _h_ui_body.get("supported"),  False)
eq("N4  outcome",                    _h_ui_body.get("outcome"),    OUTCOME_UNSUPPORTED_INTENT)
eq("N5  intent",                     _h_ui_body.get("intent"),     INTENT_UNSUPPORTED)
ok("N6  final_text non-empty",       len(_h_ui_body.get("final_text", "")) > 0)
ok("N7  HTTP 200 despite unsupported (domain outcome in body, not status)",
   _h_ui_status == 200)


# ===========================================================================
# Section O -- HTTP edge cases (422 malformed, 503 service not ready)
# ===========================================================================
_section("O -- HTTP edge cases")

_hs_mal = next(s for s in HTTP_EDGE_CASES if s["id"] == "malformed_request")
_h_mal_status, _h_mal_body = run_http_scenario(_hs_mal)

eq("O1  malformed_request HTTP status",     _h_mal_status, 422)
ok("O2  malformed_request body is non-empty", bool(_h_mal_body))

_hs_503 = next(s for s in HTTP_EDGE_CASES if s["id"] == "service_not_ready")
_h_503_status, _h_503_body = run_http_scenario(_hs_503)

# Restore standard bootstrap after the uninitialised test
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)

eq("O3  service_not_ready HTTP status",       _h_503_status, 503)
ok("O4  service_not_ready body non-empty",    bool(_h_503_body))
ok("O5  service_not_ready body has 'detail'", "detail" in _h_503_body)


# ===========================================================================
# Section P -- HTTP GET /health
# ===========================================================================
_section("P -- GET /health")

_h_client = make_client(STANDARD_BOOTSTRAP)
_h_health  = _h_client.get("/health")

eq("P1  /health HTTP status",  _h_health.status_code, 200)
ok("P2  /health response JSON", _h_health.headers["content-type"].startswith("application/json"))

_h_hj = _h_health.json()
ok("P3  /health body has 'status'",  "status" in _h_hj)
eq("P4  /health status value",        _h_hj.get("status"), "ok")


# ===========================================================================
# Section Q -- Cross-interface contract invariants
# ===========================================================================
_section("Q -- cross-interface contract invariants")

# Collect HTTP results for all 5 domain scenarios
_all_http = [(s, run_http_scenario(s)) for s in HTTP_SCENARIOS]

ok("Q1  all HTTP scenarios return status 200",
   all(status == 200 for _, (status, _) in _all_http))

ok("Q2  all HTTP responses have FinalResponse shape",
   all(_FINAL_RESPONSE_KEYS.issubset(body.keys())
       for _, (_, body) in _all_http))

ok("Q3  all HTTP final_text fields are non-empty strings",
   all(isinstance(body.get("final_text"), str) and len(body["final_text"]) > 0
       for _, (_, body) in _all_http))

ok("Q4  HTTP supported=True for 4 scenarios, False for 1",
   sum(1 for _, (_, b) in _all_http if b.get("supported") is True) == 4 and
   sum(1 for _, (_, b) in _all_http if b.get("supported") is False) == 1)

ok("Q5  HTTP unsupported_intent is the only scenario with supported=False",
   all((b.get("supported") is False) == (s["id"] == "unsupported_intent")
       for s, (_, b) in _all_http))

ok("Q6  CLI and HTTP scenario lists cover the same 5 scenario IDs",
   {s["id"] for s in CLI_SCENARIOS} == {s["id"] for s in HTTP_SCENARIOS})

# Re-check with explicit per-scenario comparison
_cli_by_id  = {s["id"]: code for s, (code, _) in _all_cli_results}
_http_by_id = {s["id"]: body.get("supported") for s, (_, body) in _all_http}
_agreement = all(
    (_cli_by_id[sid] == 0) == (_http_by_id[sid] is True)
    for sid in _cli_by_id
    if sid in _http_by_id
)
ok("Q7  CLI exit=0 ↔ HTTP supported=True for all 5 shared scenarios", _agreement)

ok("Q8  HTTP debug field is None by default for all domain scenarios",
   all(body.get("debug") is None for _, (_, body) in _all_http))

ok("Q9  example files cover all 5 canonical final_response_fixtures scenarios",
   {s["id"] for s in CLI_SCENARIOS} ==
   {"supported_ok", "supported_ambiguous", "supported_not_found",
    "supported_missing_arguments", "unsupported_intent"})

ok("Q10 HTTP edge cases cover transport errors (422, 503) not domain outcomes",
   set(s["expected_status"] for s in HTTP_EDGE_CASES) == {422, 503})


# ===========================================================================
# Final summary
# ===========================================================================
print(f"\n{'=' * 60}")
total = _passed + _failed
print(f"{'PASS' if _failed == 0 else 'FAIL'}  {_passed}/{total} assertions")
if _failed:
    print(f"  {_failed} assertion(s) failed — see FAIL lines above")
print("=" * 60)

sys.exit(0 if _failed == 0 else 1)
