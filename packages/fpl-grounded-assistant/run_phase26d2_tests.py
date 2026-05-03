"""
run_phase26d2_tests.py
======================
Phase 2.6d.2: Element-summary circuit guard (backpressure).

Stories covered
---------------
* Guard starts closed after module load
* First timeout opens guard
* Call inside cooldown fast-fails without spawning an upstream thread
* Cooldown expiry re-closes guard (half-open allows retry)
* Successful call during half-open closes guard immediately
* Network/HTTP error does NOT open guard
* Bootstrap injection bypasses guard in all states
* 5 repeated timeout requests only spawn 1 thread (the first)

Guard policy
------------
ELEMENT_SUMMARY_COOLDOWN_S = 20.0 s   (production cooldown)
Threshold                  = 1         (single timeout opens circuit)
Reset on success           = immediate

Regression
----------
run_phase26d1_tests: 27/27
run_phase26d_tests:  92/92
run_validation:      60/60
"""
from __future__ import annotations

import os
import sys
import subprocess
import threading
import time

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


import fpl_grounded_assistant.player_form as _pf_mod       # noqa: E402
from fpl_grounded_assistant.player_form import (            # noqa: E402
    _fetch_element_summary,
    get_player_form,
    ELEMENT_SUMMARY_COOLDOWN_S,
    FORM_API_BUDGET_S,
    _element_summary_guard,
    _ElementSummaryCircuitGuard,
)
from fpl_grounded_assistant.conversation_fixtures import (  # noqa: E402
    STANDARD_BOOTSTRAP, PLAYER_FORM_BOOTSTRAP,
)

# Shared tiny budget used across delay tests — avoids actual sleeping.
_TEST_BUDGET_S   = 0.05
_TEST_COOLDOWN_S = 0.1    # short cooldown for expiry tests


def _slow_fn(element_id: int) -> dict:
    """Upstream mock that always sleeps longer than _TEST_BUDGET_S."""
    time.sleep(0.3)
    return {"history": []}


def _fast_fn(element_id: int) -> dict:
    """Upstream mock that succeeds instantly."""
    return {"history": [{"round": 28, "minutes": 90, "goals_scored": 1,
                         "assists": 0, "bonus": 2, "total_points": 9}]}


def _error_fn(element_id: int) -> dict:
    """Upstream mock that raises a network error immediately."""
    import requests  # noqa: PLC0415
    raise requests.ConnectionError("simulated network error")


# ---------------------------------------------------------------------------
# A — Guard class contract
# ---------------------------------------------------------------------------

print("\n=== A: Guard class contract ===")

_check("A1 ELEMENT_SUMMARY_COOLDOWN_S == 20.0",
       ELEMENT_SUMMARY_COOLDOWN_S == 20.0,
       f"got {ELEMENT_SUMMARY_COOLDOWN_S}")
_check("A2 _element_summary_guard is _ElementSummaryCircuitGuard",
       isinstance(_element_summary_guard, _ElementSummaryCircuitGuard))

# Fresh guard starts closed
g = _ElementSummaryCircuitGuard(cooldown_s=1.0)
_check("A3 fresh guard starts closed", not g.is_open())

# record_timeout opens it
g.record_timeout()
_check("A4 record_timeout opens guard", g.is_open())

# record_success closes it immediately
g.record_success()
_check("A5 record_success closes guard immediately", not g.is_open())

# record_timeout then wait for expiry
g2 = _ElementSummaryCircuitGuard(cooldown_s=0.05)
g2.record_timeout()
_check("A6 guard open right after timeout", g2.is_open())
time.sleep(0.1)
_check("A7 guard closed after cooldown expires", not g2.is_open())


# ---------------------------------------------------------------------------
# B — First timeout opens the module guard
# ---------------------------------------------------------------------------

print("\n=== B: First timeout opens module guard ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = _TEST_COOLDOWN_S
_original = _pf_mod.get_element_summary
_pf_mod.get_element_summary = _slow_fn
try:
    _check("B1 guard closed before first call", not _element_summary_guard.is_open())
    _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    _check("B2 guard open after first timeout", _element_summary_guard.is_open())
finally:
    _pf_mod.get_element_summary = _original
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# C — Calls inside cooldown fast-fail without spawning upstream threads
# ---------------------------------------------------------------------------

print("\n=== C: Fast-fail during cooldown (no upstream thread) ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = _TEST_COOLDOWN_S

_c_calls = [0]


def _counting_slow_fn(element_id: int) -> dict:
    _c_calls[0] += 1
    time.sleep(0.3)
    return {"history": []}


_pf_mod.get_element_summary = _counting_slow_fn
try:
    # Call 1: timeout — opens guard; increments counter
    _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)

    # Calls 2-5: guard open — fast-fail, counter must NOT increment
    for _ in range(4):
        result = _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
        _check(f"C{_ + 2} call-{_ + 2} returns None without hitting upstream",
               result is None)

    _check("C1 only 1 upstream call made across 5 requests",
           _c_calls[0] == 1,
           f"got {_c_calls[0]} calls (expected 1)")
    _check("C6 guard still open during cooldown", _element_summary_guard.is_open())
finally:
    _pf_mod.get_element_summary = _original
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# D — Cooldown expiry allows retry (half-open)
# ---------------------------------------------------------------------------

print("\n=== D: Cooldown expiry re-closes guard ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = _TEST_COOLDOWN_S

# Trigger a timeout to open the guard
_pf_mod.get_element_summary = _slow_fn
try:
    _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    _check("D1 guard open after timeout", _element_summary_guard.is_open())
finally:
    _pf_mod.get_element_summary = _original

# Wait for cooldown to expire
time.sleep(_TEST_COOLDOWN_S + 0.05)
_check("D2 guard closed after cooldown expires", not _element_summary_guard.is_open())

# Next call should hit upstream again (guard closed)
_d_retries = [0]


def _counting_fast_fn(element_id: int) -> dict:
    _d_retries[0] += 1
    return _fast_fn(element_id)


_pf_mod.get_element_summary = _counting_fast_fn
try:
    result_retry = _fetch_element_summary(2, STANDARD_BOOTSTRAP,
                                          _budget_s=FORM_API_BUDGET_S)
    _check("D3 retry after expiry hits upstream", _d_retries[0] == 1,
           f"got {_d_retries[0]} calls")
    _check("D4 retry returns non-None on success", result_retry is not None)
    _check("D5 guard closed after successful retry", not _element_summary_guard.is_open())
finally:
    _pf_mod.get_element_summary = _original
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# E — Success closes guard immediately (half-open → closed)
# ---------------------------------------------------------------------------

print("\n=== E: Success resets guard ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = _TEST_COOLDOWN_S

# Open the guard with a timeout
_pf_mod.get_element_summary = _slow_fn
try:
    _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    _check("E1 guard open after timeout", _element_summary_guard.is_open())
finally:
    _pf_mod.get_element_summary = _original

# Force-expire cooldown via time travel (mutate _open_until directly)
with _element_summary_guard._lock:
    _element_summary_guard._open_until = 0.0   # close as if cooldown expired
_check("E2 guard closed after forced expiry", not _element_summary_guard.is_open())

# Successful call should keep guard closed
_pf_mod.get_element_summary = _fast_fn
try:
    result_ok = _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=FORM_API_BUDGET_S)
    _check("E3 successful call returns non-None", result_ok is not None)
    _check("E4 guard still closed after success", not _element_summary_guard.is_open())
finally:
    _pf_mod.get_element_summary = _original
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# F — Network/HTTP error does NOT open the guard
# ---------------------------------------------------------------------------

print("\n=== F: Network error does not open guard ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = _TEST_COOLDOWN_S

_pf_mod.get_element_summary = _error_fn
try:
    result_err = _fetch_element_summary(2, STANDARD_BOOTSTRAP,
                                        _budget_s=FORM_API_BUDGET_S)
    _check("F1 network error returns None", result_err is None)
    _check("F2 guard NOT opened by network error", not _element_summary_guard.is_open())
finally:
    _pf_mod.get_element_summary = _original
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# G — Bootstrap injection bypasses guard in both states
# ---------------------------------------------------------------------------

print("\n=== G: Injection path bypasses guard ===")

# With guard closed
_element_summary_guard._reset()
result_closed = _fetch_element_summary(2, PLAYER_FORM_BOOTSTRAP, _budget_s=0.001)
_check("G1 injection works when guard closed", result_closed is not None)

# With guard open (manually opened)
_element_summary_guard.record_timeout()
_check("G2 guard is open for G2/G3", _element_summary_guard.is_open())
result_open = _fetch_element_summary(2, PLAYER_FORM_BOOTSTRAP, _budget_s=0.001)
_check("G3 injection works even when guard open", result_open is not None)
_element_summary_guard._reset()


# ---------------------------------------------------------------------------
# H — 5 repeated timeout requests spawn exactly 1 thread
# ---------------------------------------------------------------------------

print("\n=== H: 5 repeated requests spawn only 1 upstream thread ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = 60.0  # long cooldown: stays open for all 5 calls

threads_created: list[threading.Thread] = []

# Patch Thread to count actual daemon thread creations
_original_thread_cls = threading.Thread


class _CountingThread(threading.Thread):
    def __init__(self, *args, daemon=False, **kwargs):
        super().__init__(*args, daemon=daemon, **kwargs)
        if daemon:
            threads_created.append(self)


_pf_mod.get_element_summary = _slow_fn
original_thread = getattr(threading, "Thread")
threading.Thread = _CountingThread

try:
    for i in range(5):
        _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    _check("H1 exactly 1 daemon thread spawned across 5 requests",
           len(threads_created) == 1,
           f"got {len(threads_created)} threads")
    _check("H2 guard open after first timeout",
           _element_summary_guard.is_open())
finally:
    threading.Thread = original_thread
    _pf_mod.get_element_summary = _original
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# I — end-to-end: get_player_form fast-fails during cooldown
# ---------------------------------------------------------------------------

print("\n=== I: get_player_form fast-fail end-to-end ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = _TEST_COOLDOWN_S
_pf_mod.get_element_summary = _slow_fn
_i_calls = [0]


def _slow_counted(element_id: int) -> dict:
    _i_calls[0] += 1
    return _slow_fn(element_id)


_pf_mod.get_element_summary = _slow_counted
try:
    # First call: timeout → opens guard
    r1 = get_player_form("Salah", STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    _check("I1 first call returns missing_context",
           r1.get("status") == "missing_context")

    # Second call: guard open → fast-fail, no upstream call
    t0 = time.monotonic()
    r2 = get_player_form("Salah", STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    elapsed_ff = time.monotonic() - t0
    _check("I2 second call returns missing_context",
           r2.get("status") == "missing_context")
    _check("I3 second call fast-failed (elapsed << budget)",
           elapsed_ff < _TEST_BUDGET_S,
           f"elapsed={elapsed_ff:.4f} s, budget={_TEST_BUDGET_S} s")
    _check("I4 only 1 upstream call made (second was fast-fail)",
           _i_calls[0] == 1,
           f"got {_i_calls[0]}")
finally:
    _pf_mod.get_element_summary = _original
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# J — Regression suites
# ---------------------------------------------------------------------------

print("\n=== J: Regression ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(f"J1 validation corpus {passed}/{total} PASS", passed == total)

result_d1 = subprocess.run(
    [sys.executable, os.path.join(_HERE, "run_phase26d1_tests.py")],
    capture_output=True, text=True, cwd=_HERE,
)
last_d1 = [l for l in result_d1.stdout.splitlines() if "Phase 2.6d.1:" in l]
if last_d1:
    _check(f"J2 phase26d1: {last_d1[-1].strip()}", "27/27" in last_d1[-1])
else:
    _check("J2 phase26d1", False, "could not parse output")

result_d = subprocess.run(
    [sys.executable, os.path.join(_HERE, "run_phase26d_tests.py")],
    capture_output=True, text=True, cwd=_HERE,
)
last_d = [l for l in result_d.stdout.splitlines() if "Phase 2.6d:" in l]
if last_d:
    _check(f"J3 phase26d: {last_d[-1].strip()}", "92/92" in last_d[-1])
else:
    _check("J3 phase26d", False, "could not parse output")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6d.2: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"              {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("              All assertions passed.")
