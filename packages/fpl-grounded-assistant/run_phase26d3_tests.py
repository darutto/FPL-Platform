"""
run_phase26d3_tests.py
======================
Phase 2.6d.3: Guard observability counters.

Counters added to _ElementSummaryCircuitGuard
---------------------------------------------
timeout_open_events   — increments on each record_timeout() call
fast_fail_events      — increments on each check_fast_fail() that returns True
successful_recoveries — increments on record_success() only when guard was open

Increment rules
---------------
* timeout_open_events  : +1 per timeout (thread still alive after budget)
* fast_fail_events     : +1 per _fetch_element_summary call that short-circuits;
                         bootstrap injection and normal-success paths never touch it
* successful_recoveries: +1 per record_success() that finds guard open;
                         record_success() on a closed guard does NOT count

Reset
-----
All three counters reset to 0 in _reset().

Accessor
--------
get_stats() → {"timeout_open_events": int, "fast_fail_events": int,
                "successful_recoveries": int}
Thread-safe snapshot.

Regression
----------
run_phase26d2_tests: 38/38
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

_TEST_BUDGET_S   = 0.05
_TEST_COOLDOWN_S = 0.1

_original_get = _pf_mod.get_element_summary


def _slow(element_id: int) -> dict:
    time.sleep(0.3)
    return {"history": []}


def _fast(element_id: int) -> dict:
    return {"history": [{"round": 28, "minutes": 90, "goals_scored": 1,
                         "assists": 0, "bonus": 2, "total_points": 9}]}


# ---------------------------------------------------------------------------
# A — get_stats() structure and initial values
# ---------------------------------------------------------------------------

print("\n=== A: get_stats() structure and initial values ===")

g0 = _ElementSummaryCircuitGuard()
stats0 = g0.get_stats()

_check("A1 get_stats returns dict",        isinstance(stats0, dict))
_check("A2 has timeout_open_events key",   "timeout_open_events"   in stats0)
_check("A3 has fast_fail_events key",      "fast_fail_events"      in stats0)
_check("A4 has successful_recoveries key", "successful_recoveries" in stats0)
_check("A5 all initial values are 0",
       stats0["timeout_open_events"] == 0
       and stats0["fast_fail_events"] == 0
       and stats0["successful_recoveries"] == 0,
       f"got {stats0}")


# ---------------------------------------------------------------------------
# B — record_timeout() increments timeout_open_events
# ---------------------------------------------------------------------------

print("\n=== B: record_timeout increments timeout_open_events ===")

g = _ElementSummaryCircuitGuard(cooldown_s=_TEST_COOLDOWN_S)
g.record_timeout()
s = g.get_stats()
_check("B1 timeout_open_events == 1 after first record_timeout",
       s["timeout_open_events"] == 1, f"got {s}")
g.record_timeout()
_check("B2 timeout_open_events == 2 after second record_timeout",
       g.get_stats()["timeout_open_events"] == 2)
_check("B3 fast_fail_events and recoveries unchanged",
       g.get_stats()["fast_fail_events"] == 0
       and g.get_stats()["successful_recoveries"] == 0)


# ---------------------------------------------------------------------------
# C — check_fast_fail() increments fast_fail_events when open
# ---------------------------------------------------------------------------

print("\n=== C: check_fast_fail increments fast_fail_events ===")

g2 = _ElementSummaryCircuitGuard(cooldown_s=_TEST_COOLDOWN_S)
# Closed guard: check_fast_fail returns False, counter unchanged
_check("C1 check_fast_fail returns False when closed", not g2.check_fast_fail())
_check("C2 fast_fail_events still 0 when closed",
       g2.get_stats()["fast_fail_events"] == 0)

# Open guard: check_fast_fail returns True, increments counter
g2.record_timeout()
_check("C3 check_fast_fail returns True when open", g2.check_fast_fail())
_check("C4 fast_fail_events == 1 after first fast-fail",
       g2.get_stats()["fast_fail_events"] == 1)
g2.check_fast_fail()
g2.check_fast_fail()
_check("C5 fast_fail_events == 3 after three fast-fails",
       g2.get_stats()["fast_fail_events"] == 3, f"got {g2.get_stats()}")
_check("C6 is_open() does NOT increment fast_fail_events",
       g2.is_open() and g2.get_stats()["fast_fail_events"] == 3)


# ---------------------------------------------------------------------------
# D — record_success() increments successful_recoveries only when was open
# ---------------------------------------------------------------------------

print("\n=== D: record_success increments recoveries only when open ===")

g3 = _ElementSummaryCircuitGuard(cooldown_s=_TEST_COOLDOWN_S)
# Success when already closed: no recovery counted
g3.record_success()
_check("D1 record_success on closed guard does NOT count recovery",
       g3.get_stats()["successful_recoveries"] == 0)

# Open then succeed: recovery counted
g3.record_timeout()
_check("D2 guard open after timeout", g3.is_open())
g3.record_success()
_check("D3 successful_recoveries == 1 after closing open guard",
       g3.get_stats()["successful_recoveries"] == 1, f"got {g3.get_stats()}")
_check("D4 guard closed after record_success", not g3.is_open())

# Another success on now-closed guard: no additional recovery
g3.record_success()
_check("D5 no second recovery on closed guard",
       g3.get_stats()["successful_recoveries"] == 1)


# ---------------------------------------------------------------------------
# E — _reset() zeroes all counters
# ---------------------------------------------------------------------------

print("\n=== E: _reset zeroes counters ===")

g4 = _ElementSummaryCircuitGuard(cooldown_s=_TEST_COOLDOWN_S)
g4.record_timeout()
g4.check_fast_fail()
g4.check_fast_fail()
# manually close then succeed to get a recovery
with g4._lock:
    g4._open_until = 0.0
g4.record_timeout()
g4.record_success()
stats_before = g4.get_stats()
_check("E1 counters non-zero before reset",
       stats_before["timeout_open_events"] >= 1
       and stats_before["fast_fail_events"] >= 2
       and stats_before["successful_recoveries"] >= 1)

g4._reset()
stats_after = g4.get_stats()
_check("E2 all counters zero after _reset",
       stats_after == {"timeout_open_events": 0, "fast_fail_events": 0,
                       "successful_recoveries": 0},
       f"got {stats_after}")
_check("E3 guard closed after _reset", not g4.is_open())


# ---------------------------------------------------------------------------
# F — End-to-end via _fetch_element_summary: 1 timeout + 3 fast-fails + 1 recovery
# ---------------------------------------------------------------------------

print("\n=== F: End-to-end counter sequence (timeout -> ff x3 -> recovery) ===")

_element_summary_guard._reset()
_element_summary_guard._cooldown_s = _TEST_COOLDOWN_S
_pf_mod.get_element_summary = _slow

try:
    # Step 1: timeout → timeout_open_events = 1
    _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    s1 = _element_summary_guard.get_stats()
    _check("F1 timeout_open_events == 1 after first timeout",
           s1["timeout_open_events"] == 1, f"got {s1}")
    _check("F2 fast_fail_events == 0 right after timeout",
           s1["fast_fail_events"] == 0)

    # Steps 2–4: three fast-fails → fast_fail_events = 3
    for _ in range(3):
        _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_TEST_BUDGET_S)
    s2 = _element_summary_guard.get_stats()
    _check("F3 fast_fail_events == 3 after three in-cooldown calls",
           s2["fast_fail_events"] == 3, f"got {s2}")
    _check("F4 timeout_open_events still 1 (no new timeouts)",
           s2["timeout_open_events"] == 1)

finally:
    _pf_mod.get_element_summary = _original_get

# Step 5: wait for natural cooldown expiry, then succeed → successful_recoveries = 1
time.sleep(_TEST_COOLDOWN_S + 0.05)

_pf_mod.get_element_summary = _fast
try:
    _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=FORM_API_BUDGET_S)
    s3 = _element_summary_guard.get_stats()
    _check("F5 successful_recoveries == 1 after recovery",
           s3["successful_recoveries"] == 1, f"got {s3}")
    _check("F6 guard closed after recovery", not _element_summary_guard.is_open())
    _check("F7 final stats: timeout=1, ff=3, recovery=1",
           s3 == {"timeout_open_events": 1, "fast_fail_events": 3,
                  "successful_recoveries": 1},
           f"got {s3}")
finally:
    _pf_mod.get_element_summary = _original_get
    _element_summary_guard._reset()


# ---------------------------------------------------------------------------
# G — get_stats() snapshot is a copy (mutations don't alias)
# ---------------------------------------------------------------------------

print("\n=== G: get_stats returns independent snapshot ===")

g5 = _ElementSummaryCircuitGuard()
snap = g5.get_stats()
snap["timeout_open_events"] = 999   # mutate the returned dict
_check("G1 mutating snapshot does not affect guard internals",
       g5.get_stats()["timeout_open_events"] == 0)


# ---------------------------------------------------------------------------
# H — Thread-safety: concurrent fast-fails all counted
# ---------------------------------------------------------------------------

print("\n=== H: Thread-safe counter under concurrent access ===")

g6 = _ElementSummaryCircuitGuard(cooldown_s=60.0)
g6.record_timeout()  # open the guard

errors: list[str] = []
barrier = threading.Barrier(10)

def _concurrent_ff():
    barrier.wait()
    if not g6.check_fast_fail():
        errors.append("check_fast_fail returned False when guard was open")

threads = [threading.Thread(target=_concurrent_ff, daemon=True) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=2.0)

_check("H1 no errors from concurrent fast-fail threads", not errors,
       str(errors))
_check("H2 fast_fail_events == 10 after 10 concurrent calls",
       g6.get_stats()["fast_fail_events"] == 10,
       f"got {g6.get_stats()['fast_fail_events']}")


# ---------------------------------------------------------------------------
# I — Bootstrap injection never touches counters
# ---------------------------------------------------------------------------

print("\n=== I: Bootstrap injection bypasses counters ===")

_element_summary_guard._reset()
_element_summary_guard.record_timeout()   # open guard

# Injection path should return data without incrementing fast_fail_events
for _ in range(3):
    result = _fetch_element_summary(2, PLAYER_FORM_BOOTSTRAP,
                                    _budget_s=_TEST_BUDGET_S)
    _check(f"I{_ + 1} injection returns data when guard open", result is not None)

s_inj = _element_summary_guard.get_stats()
_check("I4 fast_fail_events == 0 (injection bypassed counter)",
       s_inj["fast_fail_events"] == 0, f"got {s_inj}")

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

for suite, label, pattern in [
    ("run_phase26d2_tests.py", "J2 phase26d2", "38/38"),
    ("run_phase26d1_tests.py", "J3 phase26d1", "27/27"),
    ("run_phase26d_tests.py",  "J4 phase26d",  "92/92"),
]:
    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, suite)],
        capture_output=True, text=True, cwd=_HERE,
        timeout=120, creationflags=_PGROUP,
    )
    key = suite.replace("run_", "Phase ").replace("_tests.py", ":")
    match = [l for l in proc.stdout.splitlines() if key.split("/")[0].lower() in l.lower() and ":" in l]
    # fallback: look for the pass count pattern directly
    count_match = [l for l in proc.stdout.splitlines() if pattern in l]
    if count_match:
        _check(f"{label}: {count_match[-1].strip()}", pattern in count_match[-1])
    elif match:
        _check(f"{label}: {match[-1].strip()}", pattern in match[-1])
    else:
        _check(label, False, f"could not find '{pattern}' in output")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6d.3: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"              {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("              All assertions passed.")
