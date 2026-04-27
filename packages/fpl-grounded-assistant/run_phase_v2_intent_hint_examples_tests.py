"""
V2 Phase 1d — intent_hint documentation parity tests.
======================================================
Verifies that the intent_hint examples declared in:
  - examples/http_examples.py  (HTTP_SCENARIOS for V2 Phase 1d entries)
  - examples/session_examples.py  (SESSION_FLOWS for V2 Phase 1d entry)

produce the outcomes their notes claim.

Tests
-----
Section A — HTTP intent_hint scenarios (3 tests)
  A1  intent_hint_valid        bare name + valid hint -> routes via hint (ok, captain_score intent not checked here;
                               we just check HTTP 200, supported, outcome, classification_source)
  A2  intent_hint_no_change    routable question + hint -> deterministic wins; classification_source=None
  A3  intent_hint_invalid_safe bare name + invalid hint -> unsupported_intent, supported=False

Section B — Session intent_hint flow (4 tests)
  B1  intent_hint_session / create         POST /session -> 200
  B2  intent_hint_session / ask            POST /session/{id}/ask with intent_hint -> 200, ok, player_fixture_run
  B3  intent_hint_session / classification_source  classification_source == 'intent_hint'
  B4  intent_hint_session / per-turn isolation     second ask without hint -> does NOT inherit hint

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner;../fpl-player-registry;../fpl-captain-engine;\\
    ../fpl-data-core;../fpl-tool-contract;../fpl-query-tools;\\
    ../fpl-api-client;../fpl-pipeline;. python run_phase_v2_intent_hint_examples_tests.py
"""
from __future__ import annotations

import sys
import os

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


import fpl_server
from fastapi.testclient import TestClient
from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from examples.http_examples import HTTP_SCENARIOS, run_http_scenario
from examples.session_examples import SESSION_FLOWS, run_session_flow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(bootstrap=STANDARD_BOOTSTRAP) -> TestClient:
    fpl_server._init_bootstrap(bootstrap)
    return TestClient(fpl_server.app, raise_server_exceptions=True)


def _find_scenario(scenario_id: str) -> dict:
    for s in HTTP_SCENARIOS:
        if s["id"] == scenario_id:
            return s
    raise KeyError(f"HTTP scenario {scenario_id!r} not found in HTTP_SCENARIOS")


def _find_flow(flow_id: str) -> dict:
    for f in SESSION_FLOWS:
        if f["id"] == flow_id:
            return f
    raise KeyError(f"Session flow {flow_id!r} not found in SESSION_FLOWS")


# ---------------------------------------------------------------------------
# Test state
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def _assert(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        print(f"  [PASS] {label}")
        _passed += 1
    else:
        print(f"  [FAIL] {label}{(' -- ' + detail) if detail else ''}")
        _failed += 1


# ---------------------------------------------------------------------------
# Section A -- HTTP intent_hint scenarios
# ---------------------------------------------------------------------------

print("\n=== Section A: HTTP intent_hint scenarios ===\n")

# A1: intent_hint_valid
print("A1 intent_hint_valid")
s = _find_scenario("intent_hint_valid")
status, body = run_http_scenario(s)
_assert("A1.1 HTTP 200", status == 200, f"got {status}")
_assert("A1.2 supported=True", body.get("supported") is True, str(body.get("supported")))
_assert("A1.3 outcome=ok", body.get("outcome") == "ok", str(body.get("outcome")))
_assert("A1.4 debug.classification_source=intent_hint",
        (body.get("debug") or {}).get("classification_source") == "intent_hint",
        str((body.get("debug") or {}).get("classification_source")))
_assert("A1.5 intent=captain_score",
        body.get("intent") == "captain_score",
        str(body.get("intent")))

# A2: intent_hint_no_change
print("\nA2 intent_hint_no_change")
s = _find_scenario("intent_hint_no_change")
status, body = run_http_scenario(s)
_assert("A2.1 HTTP 200", status == 200, f"got {status}")
_assert("A2.2 supported=True", body.get("supported") is True)
_assert("A2.3 outcome=ok", body.get("outcome") == "ok", str(body.get("outcome")))
_assert("A2.4 intent=captain_score",
        body.get("intent") == "captain_score",
        str(body.get("intent")))
_assert("A2.5 debug.classification_source=None (deterministic wins)",
        (body.get("debug") or {}).get("classification_source") is None,
        str((body.get("debug") or {}).get("classification_source")))

# A3: intent_hint_invalid_safe
print("\nA3 intent_hint_invalid_safe")
s = _find_scenario("intent_hint_invalid_safe")
status, body = run_http_scenario(s)
_assert("A3.1 HTTP 200", status == 200, f"got {status}")
_assert("A3.2 supported=False", body.get("supported") is False, str(body.get("supported")))
_assert("A3.3 outcome=unsupported_intent",
        body.get("outcome") == "unsupported_intent",
        str(body.get("outcome")))


# ---------------------------------------------------------------------------
# Section B -- Session intent_hint flow
# ---------------------------------------------------------------------------

print("\n=== Section B: Session intent_hint flow ===\n")

fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()
client = TestClient(fpl_server.app, raise_server_exceptions=True)

# Run the flow using the helper to confirm it executes cleanly
flow = _find_flow("intent_hint_session")
result = run_session_flow(flow, client)

_assert("B1 create -> 200", result["create_status"] == 200,
        str(result.get("create_status")))

# Verify turn 0
turns = result.get("turns", [])
_assert("B2 turn exists", len(turns) >= 1)
turn0 = turns[0] if turns else {}
_assert("B2.1 turn HTTP 200", turn0.get("status") == 200, str(turn0.get("status")))
body0 = turn0.get("body", {})
_assert("B2.2 outcome=ok", body0.get("outcome") == "ok", str(body0.get("outcome")))
_assert("B2.3 intent=player_fixture_run",
        body0.get("intent") == "player_fixture_run",
        str(body0.get("intent")))
_assert("B3 debug.classification_source=intent_hint",
        (body0.get("debug") or {}).get("classification_source") == "intent_hint",
        str((body0.get("debug") or {}).get("classification_source")))

# B4: per-turn isolation — second ask WITHOUT intent_hint should NOT inherit the hint.
# Create a fresh session (run_session_flow cleared the previous one).
fpl_server._clear_sessions()
r_create = client.post("/session")
_assert("B4.1 fresh session create -> 200", r_create.status_code == 200,
        str(r_create.status_code))
fresh_id = r_create.json().get("session_id", "")
r2 = client.post(f"/session/{fresh_id}/ask", json={"question": "Haaland", "debug": True})
body2 = r2.json() if r2.status_code == 200 else {}
_assert("B4.2 second ask HTTP 200", r2.status_code == 200, str(r2.status_code))
# Without hint, "Haaland" alone doesn't route -> unsupported_intent (no hint inherited)
_assert("B4.3 second ask does NOT inherit intent_hint",
        (body2.get("debug") or {}).get("classification_source") != "intent_hint",
        f"classification_source={(body2.get('debug') or {}).get('classification_source')!r}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
total = _passed + _failed
print(f"V2 Phase 1d examples: {_passed}/{total} passed")
if _failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
