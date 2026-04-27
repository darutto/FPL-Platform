"""
run_phase_v2_bootstrap_resilience_tests.py
==========================================
Bootstrap startup resilience tests.

Validates that:
A  Transient FPL API failures recover automatically: retry succeeds.
B  Exhausted retries leave service in explicit 503 state (no infinite hang).
C  /ask returns 503 while bootstrap is None; recovers to 200 after injection.
D  /ready endpoint correctly reflects bootstrap state; /health is unaffected.
E  Structured log events emitted for each retry attempt and final outcome.
F  Test injection path still skips retries when bootstrap is pre-loaded.

No live network calls are made — assemble_captain_context is monkeypatched
in every section that exercises the retry path.
"""

from __future__ import annotations

import json
import logging
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

BS = STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def ok(label: str, cond: bool) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        print(f"  FAIL  {label}")


def _reset() -> None:
    fpl_server._init_bootstrap(BS)
    fpl_server._init_classifier_client(None)
    fpl_server._clear_sessions()


_NO_SLEEP = lambda _: None  # noqa: E731 — injected to skip real delays


def _make_ctx(bootstrap: dict) -> dict:
    """Minimal assemble_captain_context() return shape."""
    return {
        "bootstrap":              bootstrap,
        "gameweek":               34,
        "fixtures":               [],
        "fixture_difficulty_map": {},
        "meta":                   {},
    }


# ---------------------------------------------------------------------------
# Log capture for structured event assertions
# ---------------------------------------------------------------------------

class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def startup_events(self) -> list[dict]:
        """Return all fpl_startup JSON event dicts from captured records."""
        result = []
        for r in self.records:
            msg = r.getMessage()
            prefix = "fpl_startup "
            if msg.startswith(prefix):
                try:
                    result.append(json.loads(msg[len(prefix):]))
                except Exception:  # noqa: BLE001
                    pass
        return result


def _attach_log_capture() -> tuple[_LogCapture, int]:
    cap = _LogCapture()
    log = logging.getLogger("fpl_server")
    log.addHandler(cap)
    saved = log.level
    log.setLevel(logging.DEBUG)
    return cap, saved


def _detach_log_capture(cap: _LogCapture, saved: int) -> None:
    logging.getLogger("fpl_server").removeHandler(cap)
    logging.getLogger("fpl_server").setLevel(saved)


# ---------------------------------------------------------------------------
# Section A: transient failure then success ->bootstrap loaded
# ---------------------------------------------------------------------------

print("\n=== A: Transient failure then success ===")

original_asm = fpl_server.assemble_captain_context
call_count: dict[str, int] = {"n": 0}


def _fail_twice_then_succeed() -> dict:
    call_count["n"] += 1
    if call_count["n"] < 3:
        raise ConnectionError("FPL API temporarily unavailable")
    return _make_ctx(BS)


fpl_server.assemble_captain_context = _fail_twice_then_succeed
try:
    bs = fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_NO_SLEEP)
    ok("A1: bootstrap returned after 2 transient failures", bs is not None)
    ok("A2: assemble_captain_context called 3 times total",   call_count["n"] == 3)
    ok("A3: returned bootstrap matches STANDARD_BOOTSTRAP",
       bs is not None and "elements" in bs)
finally:
    fpl_server.assemble_captain_context = original_asm

_reset()


# ---------------------------------------------------------------------------
# Section B: all retries exhausted ->returns None; /ask serves 503
# ---------------------------------------------------------------------------

print("\n=== B: All retries exhausted ->None; /ask serves 503 ===")

call_count_b: dict[str, int] = {"n": 0}


def _always_fail() -> dict:
    call_count_b["n"] += 1
    raise ConnectionError("FPL API permanently unavailable")


fpl_server.assemble_captain_context = _always_fail
try:
    bs_b = fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_NO_SLEEP)
    ok("B1: returns None when all attempts fail",          bs_b is None)
    ok(f"B2: tried exactly {fpl_server._BOOTSTRAP_MAX_ATTEMPTS} times",
       call_count_b["n"] == fpl_server._BOOTSTRAP_MAX_ATTEMPTS)
finally:
    fpl_server.assemble_captain_context = original_asm

# Verify /ask returns 503 while bootstrap is unloaded
fpl_server._bootstrap = None  # type: ignore[assignment]
fpl_server._init_bootstrap(BS)  # feed lifespan guard — lifespan will NOT re-fetch
with TestClient(fpl_server.app, raise_server_exceptions=False) as client_b:
    # Clear bootstrap inside the live client context to simulate the
    # "exhausted retries, never loaded" state
    fpl_server._bootstrap = None  # type: ignore[assignment]
    resp_503 = client_b.post("/ask", json={"question": "who to captain"})
    ok("B3: /ask returns 503 when bootstrap is None", resp_503.status_code == 503)
    fpl_server._init_bootstrap(BS)  # restore for cleanup

_reset()


# ---------------------------------------------------------------------------
# Section C: /ask transitions 503 ->200 after bootstrap injection
# ---------------------------------------------------------------------------

print("\n=== C: /ask recovers from 503 to 200 without restart ===")

fpl_server._init_bootstrap(BS)   # prevents lifespan live fetch
with TestClient(fpl_server.app, raise_server_exceptions=False) as client_c:
    # Simulate exhausted-retries state by clearing bootstrap inside the context
    fpl_server._bootstrap = None  # type: ignore[assignment]
    resp_before = client_c.post("/ask", json={"question": "who to captain"})
    ok("C1: /ask 503 when bootstrap unloaded",         resp_before.status_code == 503)

    # Simulate bootstrap becoming available (retry succeeded on later attempt)
    fpl_server._init_bootstrap(BS)
    resp_after = client_c.post("/ask", json={"question": "who to captain"})
    ok("C2: /ask 200 after bootstrap injected",         resp_after.status_code == 200)
    ok("C3: recovered response has outcome",
       resp_after.json().get("outcome") in ("ok", "not_found", "unsupported_intent",
                                             "missing_arguments", "error"))

_reset()


# ---------------------------------------------------------------------------
# Section D: /ready reflects bootstrap state; /health is always 200
# ---------------------------------------------------------------------------

print("\n=== D: /ready vs /health semantics ===")

fpl_server._init_bootstrap(BS)
with TestClient(fpl_server.app, raise_server_exceptions=False) as client_d:
    ok("D1: /health returns 200 (liveness, always)",
       client_d.get("/health").status_code == 200)
    ok("D2: /ready returns 200 when bootstrap loaded",
       client_d.get("/ready").status_code == 200)
    ok("D3: /ready body is {status: ready}",
       client_d.get("/ready").json() == {"status": "ready"})

    # Clear bootstrap
    fpl_server._bootstrap = None  # type: ignore[assignment]
    ok("D4: /health still 200 when bootstrap unloaded (liveness unchanged)",
       client_d.get("/health").status_code == 200)
    ok("D5: /ready returns 503 when bootstrap unloaded",
       client_d.get("/ready").status_code == 503)

_reset()


# ---------------------------------------------------------------------------
# Section E: structured log events emitted for retries and success
# ---------------------------------------------------------------------------

print("\n=== E: Structured log events for retry attempts and outcome ===")

call_count_e: dict[str, int] = {"n": 0}


def _fail_once_then_succeed() -> dict:
    call_count_e["n"] += 1
    if call_count_e["n"] == 1:
        raise TimeoutError("FPL API timeout")
    return _make_ctx(BS)


fpl_server.assemble_captain_context = _fail_once_then_succeed
cap, saved_level = _attach_log_capture()
try:
    fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_NO_SLEEP)
finally:
    _detach_log_capture(cap, saved_level)
    fpl_server.assemble_captain_context = original_asm

events = cap.startup_events()
ok("E1: at least two events emitted (1 failure + 1 success)", len(events) >= 2)

failed_events  = [e for e in events if e.get("event") == "bootstrap_attempt_failed"]
success_events = [e for e in events if e.get("event") == "bootstrap_success"]

ok("E2: exactly 1 bootstrap_attempt_failed event", len(failed_events) == 1)
ok("E3: exactly 1 bootstrap_success event",        len(success_events) == 1)

if failed_events:
    fe = failed_events[0]
    ok("E4: failure event has 'attempt' field",       "attempt"      in fe)
    ok("E5: failure event has 'max_attempts' field",  "max_attempts" in fe)
    ok("E6: failure event has 'error' field",         "error"        in fe)
    ok("E7: failure attempt number is 1",             fe.get("attempt") == 1)
    ok("E8: error field is the exception class name", fe.get("error") == "TimeoutError")

if success_events:
    se = success_events[0]
    ok("E9: success event has 'attempt' field",  "attempt" in se)
    ok("E10: success on attempt 2",              se.get("attempt") == 2)

# Verify exhausted path emits bootstrap_exhausted event
call_count_e2: dict[str, int] = {"n": 0}


def _always_fail_e() -> dict:
    call_count_e2["n"] += 1
    raise ConnectionError("FPL API down")


fpl_server.assemble_captain_context = _always_fail_e
cap2, saved2 = _attach_log_capture()
try:
    fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_NO_SLEEP)
finally:
    _detach_log_capture(cap2, saved2)
    fpl_server.assemble_captain_context = original_asm

exhausted_events = [
    e for e in cap2.startup_events() if e.get("event") == "bootstrap_exhausted"
]
ok("E11: bootstrap_exhausted event emitted when all attempts fail",
   len(exhausted_events) == 1)
if exhausted_events:
    ok("E12: exhausted event has 'attempts' field",
       "attempts" in exhausted_events[0])

_reset()


# ---------------------------------------------------------------------------
# Section F: test injection path skips retries (pre-loaded bootstrap)
# ---------------------------------------------------------------------------

print("\n=== F: Test injection path skips retry logic ===")

# When bootstrap is pre-loaded, lifespan guard skips _fetch_bootstrap_with_retry
fpl_server._init_bootstrap(BS)

fetch_called = {"called": False}
original_fetch = fpl_server._fetch_bootstrap_with_retry


def _spy_fetch(**kwargs: Any) -> Any:
    fetch_called["called"] = True
    return original_fetch(**kwargs)


fpl_server._fetch_bootstrap_with_retry = _spy_fetch  # type: ignore[assignment]
try:
    with TestClient(fpl_server.app, raise_server_exceptions=True) as client_f:
        resp_f = client_f.post("/ask", json={"question": "who to captain"})
        ok("F1: pre-loaded bootstrap ->lifespan skips fetch ->/ask returns 200",
           resp_f.status_code == 200)
        ok("F2: _fetch_bootstrap_with_retry was NOT called (guard fired)",
           not fetch_called["called"])
finally:
    fpl_server._fetch_bootstrap_with_retry = original_fetch  # type: ignore[assignment]

_reset()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*60}")
print(f"Bootstrap resilience: {_PASS}/{total} PASS")
if _FAIL:
    print(f"                      {_FAIL} FAIL")
    sys.exit(1)
else:
    print("                      All assertions passed.")
    sys.exit(0)
