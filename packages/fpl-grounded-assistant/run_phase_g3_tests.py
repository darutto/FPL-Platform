"""
run_phase_g3_tests.py
======================
Phase G3 (mcp-graduation): Cold-restart /healthz smoke tests and static
schema verification.

Design choice — degraded-with-live-extension approach
------------------------------------------------------
Full cold-restart automation on Windows requires spawning a subprocess,
managing port 8000, injecting the bootstrap (which requires network access or
a test fixture), and coordinating env vars — all across the Windows PowerShell
process boundary.  This creates fragility that obscures the actual telemetry
assertion logic.

This runner therefore takes the **degraded-with-live-extension** approach:

  Section A  (5 assertions, always run):
    Static schema verification via FastAPI TestClient — confirms every key in
    ``routing_counters`` and ``graduation`` is present and has the correct type
    on a fresh in-process server.  Also confirms counters start at zero and
    that one ``POST /ask`` increments exactly one branch counter from 0 → 1.

  Section B  (informational, exit 0 even if server unreachable):
    Optional live HTTP smoke against ``http://127.0.0.1:8000`` if the user has
    a server running.  Prints SKIP if the port is not up.

The G3 Independent Verifier owns the cold-restart procedure:
  1. Kill any running fpl_server process (confirm port 8000 is free).
  2. ``FPL_ORCH_ENABLED=1 python fpl_server.py`` in a separate terminal.
  3. Wait for the server to print "Application startup complete."
  4. ``curl http://127.0.0.1:8000/healthz`` — assert all routing_counters == 0.
  5. ``curl -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json"
        -d '{"question":"who should I captain"}'``
  6. ``curl http://127.0.0.1:8000/healthz`` — assert total_primary == 1,
     exactly one branch counter == 1, all others == 0.

This runner returns exit code 0 if Section A passes (>= 5 assertions, 0 FAIL).
If Section B is attempted and fails, it prints the failure but does NOT set the
exit code to 1 — the live smoke is the Independent Verifier's responsibility.

Total mandatory assertions: >= 5.  Exit code 0 on success, 1 on any FAIL.

Run from packages/fpl-grounded-assistant::

    python run_phase_g3_tests.py
"""
from __future__ import annotations

import copy
import os
import sys

# Windows console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

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

# Strip orchestrator env vars so FPL_ORCH_ENABLED is off for in-process tests.
for _k in ("FPL_ORCH_ENABLED", "FPL_ORCH_PROVIDER", "ANTHROPIC_API_KEY",
           "OPENAI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_k, None)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant import telemetry  # noqa: E402

# ---------------------------------------------------------------------------
# Test plumbing (identical style to run_phase_g1_tests.py)
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_failures: list[str] = []


def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        _failures.append(label)
        print(f"  FAIL  {label}")


# ---------------------------------------------------------------------------
# Expected /healthz key sets (sourced from fpl_server.py healthz() docstring
# and telemetry.snapshot() / graduation_status() return shapes)
# ---------------------------------------------------------------------------

_EXPECTED_COUNTER_KEYS: frozenset[str] = frozenset({
    "resource",
    "prompt",
    "route",
    "classifier_rewrite",
    "orchestrator",
    "unsupported",
    "orchestrator_attempted",
    "orchestrator_grounded",
    "total_primary",
    "reject_rate",
})

_EXPECTED_GRAD_KEYS: frozenset[str] = frozenset({
    "deterministic_share",
    "orchestrator_grounded_share",
    "reject_rate",
    "criteria",
    "ready_to_graduate",
    "total_observations",
})

_EXPECTED_CRITERIA_KEYS: frozenset[str] = frozenset({
    "deterministic_share_ge_80",
    "reject_rate_lt_5",
})


# ---------------------------------------------------------------------------
# Section A — Static schema + counter zero-start + single-request increment
# ---------------------------------------------------------------------------

print("\n--- A: /healthz static schema, cold counters, and single-request increment ---")

try:
    from fastapi.testclient import TestClient  # noqa: E402
    import fpl_server  # noqa: E402

    # Prepare a deep-copied bootstrap (same guard pattern as M5 runner)
    _bs = copy.deepcopy(STANDARD_BOOTSTRAP)
    for _el in _bs["elements"]:
        _el.setdefault("total_points", 100)

    # Cold start: init bootstrap and reset counters (simulates process start)
    fpl_server._init_bootstrap(_bs)
    telemetry.reset()

    _client = TestClient(fpl_server.app)

    # -----------------------------------------------------------------------
    # A1: GET /healthz returns HTTP 200
    # -----------------------------------------------------------------------
    _r0 = _client.get("/healthz")
    check(_r0.status_code == 200, "A1: GET /healthz returns HTTP 200")

    _body0 = _r0.json()
    _rc0 = _body0.get("routing_counters", {})
    _grad0 = _body0.get("graduation", {})

    # -----------------------------------------------------------------------
    # A2: All routing_counters keys present and all values == 0 / 0.0
    #     (simulates "immediately after cold start, before any POST /ask")
    # -----------------------------------------------------------------------
    _all_counter_keys_present = _EXPECTED_COUNTER_KEYS <= set(_rc0.keys())
    _int_counters_zero = all(
        _rc0.get(k, -1) == 0
        for k in _EXPECTED_COUNTER_KEYS - {"reject_rate"}
    )
    _reject_rate_zero = _rc0.get("reject_rate", -1.0) == 0.0
    check(
        _all_counter_keys_present and _int_counters_zero and _reject_rate_zero,
        "A2: all routing_counters present and all == 0 / 0.0 on cold start",
    )

    # -----------------------------------------------------------------------
    # A3: graduation.total_observations == 0 and ready_to_graduate == False
    # -----------------------------------------------------------------------
    check(
        _grad0.get("total_observations") == 0
        and _grad0.get("ready_to_graduate") is False,
        "A3: graduation.total_observations == 0 and ready_to_graduate == False on cold start",
    )

    # -----------------------------------------------------------------------
    # A4: Send ONE POST /ask with a deterministically-routable query
    #     and confirm the response is well-formed (supported field present).
    # -----------------------------------------------------------------------
    _ask_r = _client.post("/ask", json={"question": "who should I captain"})
    _ask_body = _ask_r.json() if _ask_r.status_code == 200 else {}
    check(
        _ask_r.status_code == 200 and "supported" in _ask_body,
        "A4: POST /ask with captain query returns HTTP 200 with supported field",
    )

    # -----------------------------------------------------------------------
    # A5: After exactly one POST /ask, exactly one branch counter has gone
    #     from 0 → 1; all other branch counters remain 0; total_primary == 1;
    #     graduation.total_observations == 1.
    # -----------------------------------------------------------------------
    _r1 = _client.get("/healthz")
    _body1 = _r1.json()
    _rc1 = _body1.get("routing_counters", {})
    _grad1 = _body1.get("graduation", {})

    _branch_keys = _EXPECTED_COUNTER_KEYS - {"total_primary", "reject_rate",
                                              "orchestrator_attempted",
                                              "orchestrator_grounded"}
    _branch_counts_after = [_rc1.get(k, 0) for k in sorted(_branch_keys)]
    _exactly_one_branch_incremented = (
        sum(1 for v in _branch_counts_after if v == 1) == 1
        and sum(1 for v in _branch_counts_after if v > 1) == 0
    )
    _total_primary_is_one = _rc1.get("total_primary", 0) == 1
    _total_observations_is_one = _grad1.get("total_observations", 0) == 1

    check(
        _exactly_one_branch_incremented
        and _total_primary_is_one
        and _total_observations_is_one,
        "A5: after 1x POST /ask: exactly one branch counter == 1, "
        "total_primary == 1, total_observations == 1",
    )

    # -----------------------------------------------------------------------
    # A6: graduation schema — all expected grad keys present, criteria keys
    #     present.  (Bonus assertion; counts toward >=5 total.)
    # -----------------------------------------------------------------------
    _grad_keys_ok = _EXPECTED_GRAD_KEYS <= set(_grad1.keys())
    _criteria_keys_ok = _EXPECTED_CRITERIA_KEYS <= set(
        _grad1.get("criteria", {}).keys()
    )
    check(
        _grad_keys_ok and _criteria_keys_ok,
        "A6: graduation sub-dict and criteria sub-dict have all expected keys",
    )

except ImportError as _ie:
    print(f"  SKIP  A-suite: fastapi.testclient not available ({_ie})")
    print("        NOTE: the A-suite is mandatory — install fastapi[testclient] to run.")
    _fail += 1  # count as failure — TestClient is a dev dependency
    _failures.append("A-suite skipped: fastapi.testclient not available")


# ---------------------------------------------------------------------------
# Section B — Optional live HTTP smoke (does not affect exit code)
# ---------------------------------------------------------------------------

print("\n--- B: Live HTTP smoke (optional — does not affect exit code) ---")
print("    NOTE: The G3 Independent Verifier owns the cold-restart procedure.")
print("    This section attempts a live probe against http://127.0.0.1:8000.")
print("    SKIP if the server is not running — that is expected in CI.")

_live_issues: list[str] = []

try:
    import urllib.request
    import json as _json

    _live_url = "http://127.0.0.1:8000"

    # B1: GET /healthz
    try:
        with urllib.request.urlopen(f"{_live_url}/healthz", timeout=3) as _resp:
            _live_body = _json.loads(_resp.read())
        _live_rc = _live_body.get("routing_counters", {})
        _live_grad = _live_body.get("graduation", {})
        _schema_ok = (
            _EXPECTED_COUNTER_KEYS <= set(_live_rc.keys())
            and _EXPECTED_GRAD_KEYS <= set(_live_grad.keys())
        )
        if _schema_ok:
            print("  LIVE  B1: GET /healthz schema valid on running server")
        else:
            _live_issues.append("B1: /healthz schema missing keys on live server")
            print(f"  WARN  B1: /healthz schema issue — {sorted(set(_EXPECTED_COUNTER_KEYS) - set(_live_rc.keys()))}")
    except OSError:
        print("  SKIP  B-suite: server not reachable on 127.0.0.1:8000")

except Exception as _be:
    print(f"  SKIP  B-suite: error during live probe ({_be})")

if _live_issues:
    print(f"\n  B-suite found {len(_live_issues)} live-probe issue(s) (informational):")
    for _issue in _live_issues:
        print(f"    - {_issue}")
    print("  These are NOT counted in the exit code — the Verifier owns cold-restart.")

print("\n--- Cold-restart manual checklist for G3 Independent Verifier ---")
print("  1. Stop any running fpl_server process; verify port 8000 is free.")
print("  2. Set FPL_ORCH_ENABLED=1 and start:  python fpl_server.py")
print("  3. Wait for 'Application startup complete.'")
print("  4. GET /healthz  => assert all routing_counters == 0, total_primary == 0,")
print("                       reject_rate == 0.0, graduation.total_observations == 0,")
print("                       graduation.ready_to_graduate == False")
print('  5. POST /ask  -d \'{"question":"who should I captain"}\'')
print("  6. GET /healthz  => assert total_primary == 1, exactly one branch counter == 1,")
print("                       graduation.total_observations == 1")


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
print(f"  TOTAL: {_pass + _fail} assertions  |  PASS: {_pass}  |  FAIL: {_fail}")
if _failures:
    print("\n  Failed assertions:")
    for _f in _failures:
        print(f"    - {_f}")
print(f"{'='*60}")

sys.exit(0 if _fail == 0 else 1)
