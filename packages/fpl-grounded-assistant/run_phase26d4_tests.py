"""
run_phase26d4_tests.py
======================
Phase 2.6d.4: Operator-visible guard metrics via GET /metrics.

Exposure choice
---------------
GET /metrics — dedicated read-only ops endpoint, not /ready.

Rationale: /ready is used by Railway / Kubernetes readiness probes and must
stay minimal (just {"status": "ready"}).  Adding guard stats there would
change the contract shape for all infrastructure integrations.  A separate
/metrics endpoint is additive, clearly scoped, and conventional for ops
tooling.

Response shape
--------------
{
    "element_summary_guard": {
        "state":                 "open" | "closed",
        "timeout_open_events":   <int>,
        "fast_fail_events":      <int>,
        "successful_recoveries": <int>
    }
}

Tests
-----
A  Response structure (200 OK, required fields, correct types)
B  State field reflects guard open/closed
C  Counters reflect simulated timeout / fast-fail / recovery transitions
D  Existing /ready and /ask contracts unchanged
E  Regression suites
"""
from __future__ import annotations

import os
import sys
import subprocess
import time

_PGROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)


_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        _pass.append(label)
        print(f"  PASS  {label}")
    else:
        _fail.append(label)
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


import fpl_server                                                    # noqa: E402
from fpl_grounded_assistant.player_form import _element_summary_guard  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from starlette.testclient import TestClient                          # noqa: E402

# Pre-load bootstrap so /ask works without a live fetch
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
client = TestClient(fpl_server.app, raise_server_exceptions=True)

_GUARD_KEY = "element_summary_guard"
_REQUIRED_FIELDS = {"state", "timeout_open_events", "fast_fail_events", "successful_recoveries"}


def _get_metrics() -> dict:
    resp = client.get("/metrics")
    assert resp.status_code == 200, f"/metrics returned {resp.status_code}"
    return resp.json()


# ---------------------------------------------------------------------------
# A — Response structure
# ---------------------------------------------------------------------------

print("\n=== A: Response structure ===")

_element_summary_guard._reset()
body = _get_metrics()

_check("A1 /metrics returns 200", True)  # assertion in _get_metrics
_check("A2 top-level key 'element_summary_guard' present", _GUARD_KEY in body,
       f"keys: {list(body.keys())}")

guard = body.get(_GUARD_KEY, {})
_check("A3 all required fields present",
       _REQUIRED_FIELDS.issubset(guard.keys()),
       f"missing: {_REQUIRED_FIELDS - set(guard.keys())}")
_check("A4 'state' is string",        isinstance(guard.get("state"), str))
_check("A5 'timeout_open_events' int",isinstance(guard.get("timeout_open_events"), int))
_check("A6 'fast_fail_events' int",   isinstance(guard.get("fast_fail_events"), int))
_check("A7 'successful_recoveries' int",isinstance(guard.get("successful_recoveries"), int))
_check("A8 'state' is 'open' or 'closed'",
       guard.get("state") in ("open", "closed"),
       f"got: {guard.get('state')!r}")


# ---------------------------------------------------------------------------
# B — state field reflects guard open/closed
# ---------------------------------------------------------------------------

print("\n=== B: state reflects guard open/closed ===")

_element_summary_guard._reset()
g_closed = _get_metrics()[_GUARD_KEY]
_check("B1 state='closed' when guard is closed", g_closed["state"] == "closed",
       f"got: {g_closed['state']!r}")

_element_summary_guard.record_timeout()
g_open = _get_metrics()[_GUARD_KEY]
_check("B2 state='open' when guard is open", g_open["state"] == "open",
       f"got: {g_open['state']!r}")

_element_summary_guard.record_success()
g_back = _get_metrics()[_GUARD_KEY]
_check("B3 state='closed' after record_success", g_back["state"] == "closed")

_element_summary_guard._reset()


# ---------------------------------------------------------------------------
# C — counters reflect simulated transitions
# ---------------------------------------------------------------------------

print("\n=== C: counters reflect simulated transitions ===")

_element_summary_guard._reset()

# Simulate: 1 timeout open, 3 fast-fails, then close + success
_element_summary_guard.record_timeout()           # timeout_open_events → 1
_element_summary_guard.check_fast_fail()          # fast_fail_events → 1
_element_summary_guard.check_fast_fail()          # fast_fail_events → 2
_element_summary_guard.check_fast_fail()          # fast_fail_events → 3
_element_summary_guard.record_success()           # successful_recoveries → 1

m = _get_metrics()[_GUARD_KEY]
_check("C1 timeout_open_events == 1",   m["timeout_open_events"]   == 1, f"got {m}")
_check("C2 fast_fail_events == 3",      m["fast_fail_events"]      == 3, f"got {m}")
_check("C3 successful_recoveries == 1", m["successful_recoveries"] == 1, f"got {m}")
_check("C4 state == 'closed'",          m["state"]                 == "closed")

# Second degradation episode
_element_summary_guard.record_timeout()           # timeout_open_events → 2
_element_summary_guard.check_fast_fail()          # fast_fail_events → 4

m2 = _get_metrics()[_GUARD_KEY]
_check("C5 timeout_open_events == 2 after second episode", m2["timeout_open_events"] == 2)
_check("C6 fast_fail_events == 4 (cumulative)",            m2["fast_fail_events"]    == 4)
_check("C7 successful_recoveries still 1 (no new success)",m2["successful_recoveries"] == 1)
_check("C8 state == 'open' during second episode",         m2["state"] == "open")

_element_summary_guard._reset()


# ---------------------------------------------------------------------------
# D — /ready and /ask contracts unchanged
# ---------------------------------------------------------------------------

print("\n=== D: Existing contracts unchanged ===")

# /ready must still return {"status": "ready"}
resp_ready = client.get("/ready")
_check("D1 /ready still returns 200", resp_ready.status_code == 200)
ready_body = resp_ready.json()
_check("D2 /ready body unchanged: {status: ready}",
       ready_body == {"status": "ready"},
       f"got: {ready_body!r}")

# /health unchanged
resp_health = client.get("/health")
_check("D3 /health still returns 200", resp_health.status_code == 200)
_check("D4 /health body unchanged: {status: ok}",
       resp_health.json() == {"status": "ok"})

# /ask stable fields present
resp_ask = client.post("/ask", json={"question": "should I captain Salah"})
_check("D5 /ask still returns 200", resp_ask.status_code == 200)
ask_body = resp_ask.json()
for field in ("final_text", "outcome", "supported", "intent", "llm_used"):
    _check(f"D6 /ask.{field} present", field in ask_body, f"missing from {list(ask_body.keys())}")
# Confirm /metrics fields do NOT appear in /ask body
_check("D7 /metrics guard stats not leaked into /ask",
       _GUARD_KEY not in ask_body)

_element_summary_guard._reset()


# ---------------------------------------------------------------------------
# E — Regression suites
# ---------------------------------------------------------------------------

print("\n=== E: Regression ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(f"E1 validation corpus {passed}/{total} PASS", passed == total)

for suite, label, pattern in [
    ("run_phase26d3_tests.py", "E2 phase26d3", "40/40"),
    ("run_phase26d2_tests.py", "E3 phase26d2", "38/38"),
    ("run_phase26d1_tests.py", "E4 phase26d1", "27/27"),
    ("run_phase26d_tests.py",  "E5 phase26d",  "92/92"),
]:
    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, suite)],
        capture_output=True, text=True, cwd=_HERE,
        timeout=120, creationflags=_PGROUP,
    )
    count_line = [l for l in proc.stdout.splitlines() if pattern in l]
    if count_line:
        _check(f"{label}: {count_line[-1].strip()}", pattern in count_line[-1])
    else:
        _check(label, False, f"'{pattern}' not found in output")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6d.4: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"              {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("              All assertions passed.")
