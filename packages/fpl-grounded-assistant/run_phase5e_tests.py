"""
run_phase5e_tests.py
====================
Phase 5e: comparison exposure consistency across interfaces.

Validates that player comparison — including explanation-enriched output from
Phase 5d (margin_label, comparison_reasons, Advantages clause) — is consistently
surfaced through the CLI, HTTP, and session interfaces.

No changes were made to fpl_cli.py or fpl_server.py: comparison flows
transparently through respond() and ConversationSession.respond() exactly like
all other intents.  This slice verifies that consistency by exercising the
external surfaces directly.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5e_tests.py

Sections
--------
A  -- CLI comparison scenarios (cli_examples.py additions)
B  -- HTTP comparison scenarios (http_examples.py additions)
C  -- Session comparison flows (session_examples.py additions)
D  -- Additive fields visible in CLI and HTTP output
E  -- Regression: prior interface scenarios unaffected
"""
from __future__ import annotations

import os
import sys

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

_passed = 0
_failed = 0


def ok(label: str, expr: bool) -> None:
    global _passed, _failed
    if expr:
        _passed += 1
    else:
        _failed += 1
        print(f"FAIL  {label}")


def eq(label: str, got: object, want: object) -> None:
    if got != want:
        print(f"FAIL  {label}  got={got!r}  want={want!r}")
    ok(label, got == want)


from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    INTENT_COMPARE_PLAYERS,
)

import fpl_server
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()

from fastapi.testclient import TestClient

from examples.cli_examples  import CLI_SCENARIOS, run_cli_scenario
from examples.http_examples import HTTP_SCENARIOS, run_http_scenario
from examples.session_examples import (
    SESSION_FLOWS,
    run_session_flow,
    make_session_client,
)


# ===========================================================================
# Section A -- CLI comparison scenarios
# ===========================================================================

print("A  CLI comparison scenarios")

_cli_ids = [s["id"] for s in CLI_SCENARIOS]

ok("A1  CLI_SCENARIOS contains 'comparison_direct'",    "comparison_direct" in _cli_ids)
ok("A2  CLI_SCENARIOS contains 'comparison_not_found'", "comparison_not_found" in _cli_ids)

_a_direct = next(s for s in CLI_SCENARIOS if s["id"] == "comparison_direct")
_a_code, _a_out = run_cli_scenario(_a_direct)

eq("A3  comparison_direct exit code",               _a_code, 0)
ok("A4  comparison_direct final_text non-empty",    bool(_a_out))
ok("A5  comparison_direct output contains Haaland", "Haaland" in _a_out)
ok("A6  comparison_direct output contains Salah",   "Salah" in _a_out)
ok("A7  comparison_direct output contains 'Advantages'",
   "Advantages" in _a_out or "advantage" in _a_out.lower())
ok("A8  comparison_direct output contains margin label",
   any(word in _a_out for word in ("narrow", "moderate", "clear")))

_a_nf = next(s for s in CLI_SCENARIOS if s["id"] == "comparison_not_found")
_a_nf_code, _a_nf_out = run_cli_scenario(_a_nf)

eq("A9  comparison_not_found exit code", _a_nf_code, 0)
ok("A10 comparison_not_found output non-empty",     bool(_a_nf_out))


# ===========================================================================
# Section B -- HTTP comparison scenarios
# ===========================================================================

print("B  HTTP comparison scenarios")

_http_ids = [s["id"] for s in HTTP_SCENARIOS]

ok("B1  HTTP_SCENARIOS contains 'comparison_direct'",    "comparison_direct" in _http_ids)
ok("B2  HTTP_SCENARIOS contains 'comparison_not_found'", "comparison_not_found" in _http_ids)

_b_direct = next(s for s in HTTP_SCENARIOS if s["id"] == "comparison_direct")
_b_status, _b_body = run_http_scenario(_b_direct)

eq("B3  comparison_direct HTTP status", _b_status, 200)
ok("B4  comparison_direct supported",   _b_body.get("supported") is True)
eq("B5  comparison_direct outcome",     _b_body.get("outcome"), OUTCOME_OK)
eq("B6  comparison_direct intent",      _b_body.get("intent"), INTENT_COMPARE_PLAYERS)
ok("B7  comparison_direct final_text non-empty", bool(_b_body.get("final_text")))

_b_nf = next(s for s in HTTP_SCENARIOS if s["id"] == "comparison_not_found")
_b_nf_status, _b_nf_body = run_http_scenario(_b_nf)

eq("B8  comparison_not_found HTTP status",  _b_nf_status, 200)
ok("B9  comparison_not_found supported",    _b_nf_body.get("supported") is True)
eq("B10 comparison_not_found outcome",      _b_nf_body.get("outcome"), OUTCOME_NOT_FOUND)
ok("B11 comparison_not_found final_text non-empty", bool(_b_nf_body.get("final_text")))


# ===========================================================================
# Section C -- Session comparison flows
# ===========================================================================

print("C  Session comparison flows")

_flow_ids = [f["id"] for f in SESSION_FLOWS]
ok("C1  SESSION_FLOWS contains 'comparison_direct'",   "comparison_direct" in _flow_ids)
ok("C2  SESSION_FLOWS contains 'comparison_followup'", "comparison_followup" in _flow_ids)

# comparison_direct flow
fpl_server._clear_sessions()
_c_client = make_session_client()

_c_direct_flow = next(f for f in SESSION_FLOWS if f["id"] == "comparison_direct")
_c_direct = run_session_flow(_c_direct_flow, _c_client)

eq("C3  comparison_direct create_status",   _c_direct["create_status"], 200)
ok("C4  comparison_direct session_id",      bool(_c_direct.get("session_id")))
eq("C5  comparison_direct one turn",        len(_c_direct.get("turns", [])), 1)
eq("C6  comparison_direct turn 1 status",   _c_direct["turns"][0]["status"], 200)
eq("C7  comparison_direct turn 1 outcome",  _c_direct["turns"][0]["body"].get("outcome"), OUTCOME_OK)
eq("C8  comparison_direct turn 1 intent",   _c_direct["turns"][0]["body"].get("intent"), INTENT_COMPARE_PLAYERS)
ok("C9  comparison_direct turn 1 final_text non-empty",
   bool(_c_direct["turns"][0]["body"].get("final_text")))
eq("C10 comparison_direct inspect turn_count",  _c_direct["inspect_body"].get("turn_count"), 1)
eq("C11 comparison_direct clear_status",        _c_direct["clear_status"], 200)
eq("C12 comparison_direct after_clear_status",  _c_direct["after_clear_status"], 404)

# comparison_followup flow
fpl_server._clear_sessions()
_cf_client = make_session_client()

_c_fu_flow = next(f for f in SESSION_FLOWS if f["id"] == "comparison_followup")
_c_fu = run_session_flow(_c_fu_flow, _cf_client)

eq("C13 comparison_followup create_status",     _c_fu["create_status"], 200)
eq("C14 comparison_followup two turns",         len(_c_fu.get("turns", [])), 2)
eq("C15 comparison_followup turn 1 status",     _c_fu["turns"][0]["status"], 200)
eq("C16 comparison_followup turn 1 outcome ok", _c_fu["turns"][0]["body"].get("outcome"), OUTCOME_OK)
eq("C17 comparison_followup turn 2 status",     _c_fu["turns"][1]["status"], 200)
eq("C18 comparison_followup turn 2 outcome ok", _c_fu["turns"][1]["body"].get("outcome"), OUTCOME_OK)
ok("C19 turn 2 final_text contains Haaland",
   "Haaland" in (_c_fu["turns"][1]["body"].get("final_text") or ""))
ok("C20 turn 2 final_text contains Saka",
   "Saka" in (_c_fu["turns"][1]["body"].get("final_text") or ""))
eq("C21 comparison_followup inspect turn_count", _c_fu["inspect_body"].get("turn_count"), 2)
eq("C22 comparison_followup clear_status",       _c_fu["clear_status"], 200)
eq("C23 comparison_followup after_clear_status", _c_fu["after_clear_status"], 404)


# ===========================================================================
# Section D -- Additive fields visible in output (Phase 5d enrichment)
# ===========================================================================

print("D  Additive fields visible in output")

# CLI output contains enriched recommendation fields
ok("D1  CLI output contains winner name (Salah)",   "Salah" in _a_out)
ok("D2  CLI output contains loser name (Haaland)",  "Haaland" in _a_out)
ok("D3  CLI output contains 'Advantages'",
   "Advantages" in _a_out or "advantage" in _a_out.lower())
ok("D4  CLI output contains margin label word",
   any(word in _a_out for word in ("narrow", "moderate", "clear")))

# HTTP body final_text contains enriched recommendation fields
_d_ft = _b_body.get("final_text", "")
ok("D5  HTTP final_text contains winner name (Salah)",   "Salah" in _d_ft)
ok("D6  HTTP final_text contains loser name (Haaland)",  "Haaland" in _d_ft)
ok("D7  HTTP final_text contains 'Advantages'",
   "Advantages" in _d_ft or "advantage" in _d_ft.lower())
ok("D8  HTTP final_text contains margin label word",
   any(word in _d_ft for word in ("narrow", "moderate", "clear")))

# Session comparison follow-up also carries enriched recommendation
_d_fu_ft = _c_fu["turns"][0]["body"].get("final_text", "")
ok("D9  session comparison_direct turn final_text has 'Advantages'",
   "Advantages" in _d_fu_ft or "advantage" in _d_fu_ft.lower())
ok("D10 session comparison_followup turn 2 also enriched",
   "Advantages" in (_c_fu["turns"][1]["body"].get("final_text") or "")
   or "advantage" in (_c_fu["turns"][1]["body"].get("final_text") or "").lower())


# ===========================================================================
# Section E -- Regression: prior interface scenarios unaffected
# ===========================================================================

print("E  Regression: prior interface scenarios unaffected")

# CLI: supported_ok still works
_e_cli_ok = next(s for s in CLI_SCENARIOS if s["id"] == "supported_ok")
_e_code, _e_out = run_cli_scenario(_e_cli_ok)
eq("E1  CLI supported_ok exit code",         _e_code, 0)
ok("E2  CLI supported_ok output non-empty",  bool(_e_out))

# CLI: unsupported_intent still exits 1
_e_cli_ui = next(s for s in CLI_SCENARIOS if s["id"] == "unsupported_intent")
_e_ui_code, _ = run_cli_scenario(_e_cli_ui)
eq("E3  CLI unsupported_intent exit code",   _e_ui_code, 1)

# HTTP: supported_ok scenario still HTTP 200 + outcome ok
_e_http_ok = next(s for s in HTTP_SCENARIOS if s["id"] == "supported_ok")
_e_h_status, _e_h_body = run_http_scenario(_e_http_ok)
eq("E4  HTTP supported_ok status",           _e_h_status, 200)
eq("E5  HTTP supported_ok outcome",          _e_h_body.get("outcome"), OUTCOME_OK)

# HTTP: CLI and HTTP share the same scenario IDs (consistency check)
ok("E6  CLI and HTTP scenario IDs match",
   {s["id"] for s in CLI_SCENARIOS} == {s["id"] for s in HTTP_SCENARIOS})

# Session: pronoun_follow_up flow still works
fpl_server._clear_sessions()
_e_sess_client = make_session_client()
_e_pf_flow = next(f for f in SESSION_FLOWS if f["id"] == "pronoun_follow_up")
_e_pf = run_session_flow(_e_pf_flow, _e_sess_client)
eq("E7  pronoun_follow_up create_status",    _e_pf["create_status"], 200)
eq("E8  pronoun_follow_up turn 1 status",    _e_pf["turns"][0]["status"], 200)
eq("E9  pronoun_follow_up turn 2 status",    _e_pf["turns"][1]["status"], 200)
eq("E10 pronoun_follow_up turn 2 outcome ok",
   _e_pf["turns"][1]["body"].get("outcome"), OUTCOME_OK)
eq("E11 pronoun_follow_up inspect turn_count", _e_pf["inspect_body"].get("turn_count"), 2)

# Session: SESSION_FLOWS includes both legacy and new comparison flows
ok("E12 SESSION_FLOWS includes 'create_ask_inspect_clear'",
   "create_ask_inspect_clear" in [f["id"] for f in SESSION_FLOWS])
ok("E13 SESSION_FLOWS includes 'pronoun_follow_up'",
   "pronoun_follow_up" in [f["id"] for f in SESSION_FLOWS])


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5e: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
