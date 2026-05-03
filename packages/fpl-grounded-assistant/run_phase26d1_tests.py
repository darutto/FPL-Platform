"""
run_phase26d1_tests.py
======================
Phase 2.6d.1: player-form API timeout / latency-budget hardening.

Stories covered
---------------
* ``ELEMENT_SUMMARY_TIMEOUT_S`` exported from fpl_client — per-request HTTP cap
* ``FORM_API_BUDGET_S`` exported from player_form — total latency budget
* ``_fetch_element_summary`` returns ``None`` within bounded time when
  upstream is delayed (budget gate fires before the full sleep completes)
* ``get_player_form`` returns ``missing_context`` when budget exceeded
* Fast (no-delay) paths unchanged: bootstrap injection and live-API success

Constants
---------
ELEMENT_SUMMARY_TIMEOUT_S = 4   (fpl_client.py, per-request HTTP timeout)
FORM_API_BUDGET_S          = 5.0 (player_form.py, total ThreadPoolExecutor cap)

Regression
----------
run_validation: 60/60 (unchanged from 2.6d)
run_phase26d_tests: 92/92 (unchanged)
"""
from __future__ import annotations

import os
import sys
import time
import subprocess

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


import fpl_grounded_assistant.player_form as _pf_mod  # noqa: E402
from fpl_grounded_assistant.player_form import (       # noqa: E402
    _fetch_element_summary,
    get_player_form,
    FORM_API_BUDGET_S,
    DEFAULT_N_GAMES,
    _element_summary_guard,
)
from fpl_grounded_assistant.conversation_fixtures import (  # noqa: E402
    STANDARD_BOOTSTRAP, PLAYER_FORM_BOOTSTRAP,
)
from fpl_api_client.fpl_client import ELEMENT_SUMMARY_TIMEOUT_S  # noqa: E402


# ---------------------------------------------------------------------------
# A — Constant values
# ---------------------------------------------------------------------------

print("\n=== A: Constant values ===")

_check("A1 ELEMENT_SUMMARY_TIMEOUT_S exported from fpl_client",
       isinstance(ELEMENT_SUMMARY_TIMEOUT_S, int))
_check("A2 ELEMENT_SUMMARY_TIMEOUT_S == 4",
       ELEMENT_SUMMARY_TIMEOUT_S == 4,
       f"got {ELEMENT_SUMMARY_TIMEOUT_S}")
_check("A3 FORM_API_BUDGET_S exported from player_form",
       isinstance(FORM_API_BUDGET_S, float))
_check("A4 FORM_API_BUDGET_S == 5.0",
       FORM_API_BUDGET_S == 5.0,
       f"got {FORM_API_BUDGET_S}")
_check("A5 FORM_API_BUDGET_S > ELEMENT_SUMMARY_TIMEOUT_S",
       FORM_API_BUDGET_S > ELEMENT_SUMMARY_TIMEOUT_S,
       "budget must exceed per-request timeout to allow at least one attempt")


# ---------------------------------------------------------------------------
# B — Bootstrap injection path unaffected by budget gate
# ---------------------------------------------------------------------------

print("\n=== B: Injection path bypasses budget gate ===")

_element_summary_guard._reset()   # ensure closed before test
result_inject = _fetch_element_summary(2, PLAYER_FORM_BOOTSTRAP, _budget_s=0.001)
_check("B1 injection path returns non-None even with tiny budget",
       result_inject is not None,
       "bootstrap injection must not pass through the ThreadPoolExecutor gate")
_check("B2 injection path returns history list",
       isinstance(result_inject.get("history"), list))


# ---------------------------------------------------------------------------
# C — Budget gate: 2 s delayed API returns within bounded time
# ---------------------------------------------------------------------------

print("\n=== C: Budget gate — 2 s delayed API with 0.05 s budget ===")

# Mock sleeps 2 s — much longer than the 0.05 s budget.
# With a daemon Thread + join(timeout), _fetch_element_summary must return
# within budget + small OS overhead (< 0.2 s total) without waiting for
# the thread to finish.
# The ThreadPoolExecutor approach would have blocked for the full 2 s.
_original_fn = _pf_mod.get_element_summary

_MOCK_SLEEP_S = 2.0   # much longer than budget — proves non-blocking timeout
_BUDGET_S     = 0.05  # tight budget
_TOLERANCE_S  = 0.15  # OS overhead tolerance; total budget + tolerance < 0.2 s


def _slow_get_element_summary(element_id: int) -> dict:
    time.sleep(_MOCK_SLEEP_S)
    return {"history": [{"round": 1, "minutes": 90, "goals_scored": 1,
                         "assists": 0, "bonus": 0, "total_points": 5}]}


_pf_mod.get_element_summary = _slow_get_element_summary
try:
    t0 = time.monotonic()
    result_slow = _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=_BUDGET_S)
    elapsed = time.monotonic() - t0

    _check("C1 delayed API returns None when budget exceeded",
           result_slow is None,
           f"got {result_slow!r}")
    _check(f"C2 elapsed < budget + tolerance ({_BUDGET_S + _TOLERANCE_S:.2f} s) "
           f"— proves non-blocking timeout",
           elapsed < _BUDGET_S + _TOLERANCE_S,
           f"elapsed={elapsed:.3f} s  (would be ~{_MOCK_SLEEP_S:.1f} s with blocking shutdown)")
    _check(f"C3 elapsed >= budget ({_BUDGET_S:.2f} s) — join actually waited",
           elapsed >= _BUDGET_S,
           f"elapsed={elapsed:.3f} s")
    _check(f"C4 elapsed < mock sleep ({_MOCK_SLEEP_S:.1f} s) — thread was not awaited",
           elapsed < _MOCK_SLEEP_S,
           f"elapsed={elapsed:.3f} s")
finally:
    _pf_mod.get_element_summary = _original_fn


# ---------------------------------------------------------------------------
# D — get_player_form returns missing_context within bounded time
# ---------------------------------------------------------------------------

print("\n=== D: get_player_form returns missing_context within bounded time ===")

_pf_mod.get_element_summary = _slow_get_element_summary
try:
    t0 = time.monotonic()
    result = get_player_form("Salah", STANDARD_BOOTSTRAP, _budget_s=_BUDGET_S)
    elapsed = time.monotonic() - t0

    _check("D1 status=missing_context", result.get("status") == "missing_context",
           f"got status={result.get('status')!r}")
    _check("D2 message present", bool(result.get("message")))
    _check("D3 query preserved", result.get("query") == "Salah")
    _check(f"D4 completed within budget + tolerance ({_BUDGET_S + _TOLERANCE_S:.2f} s)",
           elapsed < _BUDGET_S + _TOLERANCE_S,
           f"elapsed={elapsed:.3f} s")
    _check(f"D5 elapsed < mock sleep ({_MOCK_SLEEP_S:.1f} s) — thread not awaited end-to-end",
           elapsed < _MOCK_SLEEP_S,
           f"elapsed={elapsed:.3f} s")
finally:
    _pf_mod.get_element_summary = _original_fn


# ---------------------------------------------------------------------------
# E — Fast API (no delay) still succeeds via budget gate
# ---------------------------------------------------------------------------

print("\n=== E: Fast API succeeds via budget gate ===")

_element_summary_guard._reset()   # C/D left guard open; reset before success test
_original_fn2 = _pf_mod.get_element_summary


def _fast_get_element_summary(element_id: int) -> dict:
    return {"history": [
        {"round": 28, "minutes": 90, "goals_scored": 1, "assists": 0,
         "bonus": 3, "total_points": 10},
    ]}


_pf_mod.get_element_summary = _fast_get_element_summary
try:
    result_fast = _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=0.5)
    _check("E1 fast API returns non-None", result_fast is not None)
    _check("E2 fast API history has 1 entry",
           len(result_fast.get("history", [])) == 1)

    result_gf = get_player_form("Salah", STANDARD_BOOTSTRAP, _budget_s=0.5)
    _check("E3 get_player_form status=ok via fast API",
           result_gf.get("status") == "ok",
           f"got status={result_gf.get('status')!r}")
    _check("E4 history returned",
           len(result_gf.get("history", [])) == 1)
finally:
    _pf_mod.get_element_summary = _original_fn2


# ---------------------------------------------------------------------------
# F — Exception path (network error) still returns None
# ---------------------------------------------------------------------------

print("\n=== F: Network exception returns None ===")

_element_summary_guard._reset()   # ensure closed so network-error path is exercised
_original_fn3 = _pf_mod.get_element_summary


def _raising_get_element_summary(element_id: int) -> dict:
    import requests  # noqa: PLC0415
    raise requests.ConnectionError("simulated network failure")


_pf_mod.get_element_summary = _raising_get_element_summary
try:
    result_err = _fetch_element_summary(2, STANDARD_BOOTSTRAP, _budget_s=2.0)
    _check("F1 network error returns None", result_err is None,
           f"got {result_err!r}")

    result_mc = get_player_form("Salah", STANDARD_BOOTSTRAP, _budget_s=2.0)
    _check("F2 get_player_form returns missing_context on network error",
           result_mc.get("status") == "missing_context")
finally:
    _pf_mod.get_element_summary = _original_fn3


# ---------------------------------------------------------------------------
# G — Production bootstrap-injection path still works (no _budget_s override)
# ---------------------------------------------------------------------------

print("\n=== G: Production injection path (default budget) ===")

_element_summary_guard._reset()   # guard irrelevant for injection path, but be explicit
result_prod_inject = get_player_form("Salah", PLAYER_FORM_BOOTSTRAP, n_games=3)
_check("G1 injection path status=ok", result_prod_inject.get("status") == "ok")
_check("G2 injection path n_games=3", result_prod_inject.get("n_games") == 3)
_check("G3 injection path history has 3 entries",
       len(result_prod_inject.get("history", [])) == 3)


# ---------------------------------------------------------------------------
# H — Regression: validation corpus 60/60
# ---------------------------------------------------------------------------

print("\n=== H: Regression — validation corpus ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(f"H1 validation corpus {passed}/{total} PASS",
       passed == total,
       f"{total - passed} scenario(s) failed")


# ---------------------------------------------------------------------------
# I — Regression: run_phase26d_tests still passes
# ---------------------------------------------------------------------------

print("\n=== I: Regression — phase26d ===")

result_d = subprocess.run(
    [sys.executable, os.path.join(_HERE, "run_phase26d_tests.py")],
    capture_output=True, text=True, cwd=_HERE,
)
last_d = [l for l in result_d.stdout.splitlines() if "Phase 2.6d:" in l]
if last_d:
    summary_d = last_d[-1].strip()
    _check(f"I1 phase26d regression: {summary_d}", "92/92" in summary_d,
           result_d.stderr[-300:] if result_d.stderr else "")
else:
    _check("I1 phase26d regression", False, "could not parse output")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6d.1: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"              {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("              All assertions passed.")
