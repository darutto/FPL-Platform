"""
run_phase26a_tests.py
=====================
Phase 2.6a: Deterministic, cached OpenAI timeout compatibility detection.

Replaces exception-message heuristics with signature-based capability probe
(inspect.signature) cached once per process lifetime.

Sections
--------
A  timeout-supported path: signature probe ->True ->call with timeout=
B  timeout-unsupported path: signature probe ->False ->call without timeout=
C  capability decision cached: probe runs only once, subsequent calls deterministic
D  non-timeout errors are never masked by the helper
E  event schema unchanged after 2.6a
F  gate / cooldown no regression
"""

from __future__ import annotations

import inspect as _inspect
import json
import logging as _stdlib_logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
_SIB = lambda name: os.path.join(_PKGS, name)

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

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"

from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_COOLDOWN,
    OUTCOME_LLM_ERROR,
    PROVIDER_ANTHROPIC,
    _GATE,
    _FailureGate,
    ask_orchestrated,
)
from fpl_grounded_assistant.provider_client import (
    PERR_TIMEOUT,
    _OAI_TIMEOUT_SUPPORTED,
    _OAI_TIMEOUT_CACHE_LOCK,
    _call_with_oai_compat_timeout,
    _get_oai_timeout_support,
    _probe_oai_timeout_support,
)

_passed = 0
_failed = 0
_GATE.reset_all()


def ok(label: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


_NO_SLEEP = lambda _x: None  # noqa: E731


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class _AntToolBlock:
    type  = "tool_use"
    name  = "get_captain_score"
    input = {"query": "Haaland"}

class _AntResponse:
    content = [_AntToolBlock()]


class _StatusError(Exception):
    def __init__(self, msg: str, status_code: int) -> None:
        super().__init__(msg)
        self.status_code = status_code


# Log capture
class _LogCap(_stdlib_logging.Handler):
    def __init__(self) -> None:
        super().__init__(_stdlib_logging.DEBUG)
        self.records: list[_stdlib_logging.LogRecord] = []

    def emit(self, record: _stdlib_logging.LogRecord) -> None:
        self.records.append(record)

    def events(self) -> list[dict]:
        return [getattr(r, "fpl_event") for r in self.records if hasattr(r, "fpl_event")]


def _attach(name: str) -> tuple[_LogCap, _stdlib_logging.Logger, int]:
    cap = _LogCap()
    log = _stdlib_logging.getLogger(name)
    log.addHandler(cap)
    saved = log.level
    log.setLevel(_stdlib_logging.DEBUG)
    return cap, log, saved


def _detach(cap: _LogCap, log: _stdlib_logging.Logger, saved: int) -> None:
    log.removeHandler(cap)
    log.setLevel(saved)


# ---------------------------------------------------------------------------
# Cache management helpers
# ---------------------------------------------------------------------------

def _reset_oai_cache() -> bool | None:
    """Save and reset _OAI_TIMEOUT_SUPPORTED. Returns the saved value."""
    saved = _OAI_TIMEOUT_SUPPORTED[0]
    _OAI_TIMEOUT_SUPPORTED[0] = None
    return saved


def _restore_oai_cache(saved: bool | None) -> None:
    _OAI_TIMEOUT_SUPPORTED[0] = saved


# ---------------------------------------------------------------------------
# Section A: timeout-supported path chosen via signature probe
# ---------------------------------------------------------------------------

def _run_section_a() -> None:
    print("\n=== A: Timeout-supported path via signature probe ===")

    saved = _reset_oai_cache()
    try:
        # Function with explicit 'timeout' parameter
        def _fn_explicit_timeout(model: str, timeout: float = 20.0) -> str:
            return f"ok_with_timeout={timeout}"

        ok("A1 probe: explicit timeout param ->True",
           _probe_oai_timeout_support(_fn_explicit_timeout) is True)

        calls: list[dict] = []

        def _explicit_timeout_create(model: str, timeout: float = 20.0, **kw: object) -> str:
            calls.append({"model": model, "timeout": timeout, **kw})
            return "result"

        r = _call_with_oai_compat_timeout(
            _explicit_timeout_create, timeout_s=15.0, model="gpt-4",
        )
        ok("A2 call with explicit timeout param succeeds",     r == "result")
        ok("A3 timeout kwarg forwarded",                       calls[-1].get("timeout") == 15.0)
        ok("A4 model kwarg forwarded",                         calls[-1].get("model") == "gpt-4")
        ok("A5 called exactly once (no retry)",                len(calls) == 1)
        ok("A6 cache set to True after explicit-param probe",  _OAI_TIMEOUT_SUPPORTED[0] is True)

        # Function with **kwargs (also probe ->True)
        _reset_oai_cache()
        calls2: list[dict] = []

        def _kwargs_accepts_all(**kw: object) -> str:
            calls2.append(kw)
            return "ok"

        ok("A7 probe: **kwargs function ->True",
           _probe_oai_timeout_support(_kwargs_accepts_all) is True)
        r2 = _call_with_oai_compat_timeout(
            _kwargs_accepts_all, timeout_s=10.0, model="m",
        )
        ok("A8 **kwargs function called with timeout",    r2 == "ok")
        ok("A9 timeout in kwargs call",                   calls2[-1].get("timeout") == 10.0)
    finally:
        _restore_oai_cache(saved)


# ---------------------------------------------------------------------------
# Section B: timeout-unsupported path chosen via signature probe
# ---------------------------------------------------------------------------

def _run_section_b() -> None:
    print("\n=== B: Timeout-unsupported path via signature probe ===")

    saved = _reset_oai_cache()
    try:
        # Function with explicit params but NO timeout and NO **kwargs
        def _no_timeout_fn(model: str, max_tokens: int = 1024,
                            messages: object = None, tools: object = None) -> str:
            return "ok_no_timeout"

        ok("B1 probe: no-timeout explicit params ->False",
           _probe_oai_timeout_support(_no_timeout_fn) is False)

        calls: list[dict] = []

        def _explicit_no_timeout(model: str, max_tokens: int = 1024) -> str:
            calls.append({"model": model, "max_tokens": max_tokens})
            return "result_no_timeout"

        r = _call_with_oai_compat_timeout(
            _explicit_no_timeout, timeout_s=15.0, model="legacy",
        )
        ok("B2 no-timeout function called successfully",   r == "result_no_timeout")
        ok("B3 no timeout kwarg passed",                   "timeout" not in calls[-1])
        ok("B4 model kwarg still forwarded",               calls[-1].get("model") == "legacy")
        ok("B5 called exactly once (no retry needed)",     len(calls) == 1)
        ok("B6 cache set to False after no-timeout probe", _OAI_TIMEOUT_SUPPORTED[0] is False)
    finally:
        _restore_oai_cache(saved)


# ---------------------------------------------------------------------------
# Section C: capability is cached; probe does not re-run
# ---------------------------------------------------------------------------

def _run_section_c() -> None:
    print("\n=== C: Capability decision cached after first probe ===")

    saved = _reset_oai_cache()
    try:
        ok("C1 cache starts None (reset)",  _OAI_TIMEOUT_SUPPORTED[0] is None)

        # First call: probe runs, cache populated
        def _no_timeout_fn(model: str) -> str:
            return "ok"

        _get_oai_timeout_support(_no_timeout_fn)   # probe call
        ok("C2 cache populated after first call", _OAI_TIMEOUT_SUPPORTED[0] is not None)
        ok("C3 probe result is False for no-timeout fn", _OAI_TIMEOUT_SUPPORTED[0] is False)

        # Second call with a DIFFERENT function that WOULD probe True
        # Since cache is already False, result must stay False
        def _fn_with_timeout(model: str, timeout: float = 20.0) -> str:
            return "ok2"

        result2 = _get_oai_timeout_support(_fn_with_timeout)
        ok("C4 cache reused (different fn, same result)",  result2 is False)
        ok("C5 cache value unchanged",                      _OAI_TIMEOUT_SUPPORTED[0] is False)

        # Re-probe after reset: new function ->cache updated
        _OAI_TIMEOUT_SUPPORTED[0] = None
        result3 = _get_oai_timeout_support(_fn_with_timeout)
        ok("C6 after reset, new probe runs",  result3 is True)
        ok("C7 cache updated to True",        _OAI_TIMEOUT_SUPPORTED[0] is True)

        # End-to-end: two calls to _call_with_oai_compat_timeout after cache=True
        # ->both use fast path (no probe, no try/except)
        calls: list[dict] = []

        def _fn(**kw: object) -> str:
            calls.append(kw)
            return "ok"

        _call_with_oai_compat_timeout(_fn, timeout_s=5.0, model="m1")
        _call_with_oai_compat_timeout(_fn, timeout_s=5.0, model="m2")
        ok("C8 both calls went through timeout path", all("timeout" in c for c in calls))
        ok("C9 called twice total",                   len(calls) == 2)
    finally:
        _restore_oai_cache(saved)


# ---------------------------------------------------------------------------
# Section D: non-timeout errors are never masked
# ---------------------------------------------------------------------------

def _run_section_d() -> None:
    print("\n=== D: Non-timeout errors never masked ===")

    saved = _reset_oai_cache()
    try:
        # ValueError propagates regardless of cache state
        def _raises_valueerror(**_kw: object) -> None:
            raise ValueError("bad auth response")

        caught_v: ValueError | None = None
        try:
            _call_with_oai_compat_timeout(_raises_valueerror, timeout_s=5.0, model="m")
        except ValueError as exc:
            caught_v = exc
        ok("D1 ValueError propagates",             caught_v is not None)
        ok("D2 ValueError message preserved",       "bad auth" in str(caught_v or ""))

        # RuntimeError propagates
        _OAI_TIMEOUT_SUPPORTED[0] = None
        def _raises_runtimeerror(**_kw: object) -> None:
            raise RuntimeError("connection refused")

        caught_r: RuntimeError | None = None
        try:
            _call_with_oai_compat_timeout(_raises_runtimeerror, timeout_s=5.0, model="m")
        except RuntimeError as exc:
            caught_r = exc
        ok("D3 RuntimeError propagates",            caught_r is not None)

        # TypeError unrelated to timeout propagates (after initial probe may cache False)
        _OAI_TIMEOUT_SUPPORTED[0] = None
        def _raises_unrelated_typeerror(**_kw: object) -> None:
            raise TypeError("argument of type 'int' is not iterable")

        caught_t: TypeError | None = None
        try:
            _call_with_oai_compat_timeout(_raises_unrelated_typeerror, timeout_s=5.0, model="m")
        except TypeError as exc:
            caught_t = exc
        ok("D4 unrelated TypeError propagates",           caught_t is not None)
        ok("D5 original TypeError message preserved",     "iterable" in str(caught_t or ""))
    finally:
        _restore_oai_cache(saved)


# ---------------------------------------------------------------------------
# Section E: structured event schema unchanged
# ---------------------------------------------------------------------------

def _run_section_e() -> None:
    print("\n=== E: Structured event schema unchanged ===")

    gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: _AntResponse(),
            _gate=gate,
        )
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    evs = cap.events()
    ok("E1 two events emitted", len(evs) == 2)
    if len(evs) == 2:
        ev_ok, ev_fail = evs[0], evs[1]
        ok("E2 success event='provider_call_success'",
           ev_ok.get("event") == "provider_call_success")
        ok("E3 failure event='provider_call_failure'",
           ev_fail.get("event") == "provider_call_failure")
        required_ok   = {"event", "provider", "model", "latency_ms", "attempts"}
        required_fail = required_ok | {"error_code"}
        ok("E4 success fields present",  required_ok   <= set(ev_ok.keys()))
        ok("E5 failure fields present",  required_fail <= set(ev_fail.keys()))
        ok("E6 no error_msg in events",  "error_msg" not in ev_ok and "error_msg" not in ev_fail)


# ---------------------------------------------------------------------------
# Section F: gate / cooldown no regression
# ---------------------------------------------------------------------------

def _run_section_f() -> None:
    print("\n=== F: Gate + cooldown no regression ===")

    gate = _FailureGate(threshold=2, window_s=60, cooldown_s=9999)
    for _ in range(2):
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
            _gate=gate,
        )
    ok("F1 gate opens after 2 transient errors", gate.is_open())

    call_count = {"n": 0}

    def _count() -> object:
        call_count["n"] += 1
        return _AntResponse()

    result = ask_orchestrated(
        "q", STANDARD_BOOTSTRAP,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=_count,
        _gate=gate,
    )
    ok("F2 OUTCOME_COOLDOWN during cooldown",  result.outcome == OUTCOME_COOLDOWN)
    ok("F3 provider NOT called during cooldown", call_count["n"] == 0)

    gate.reset_all()
    ok("F4 reset_all clears gate",  not gate.is_open())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _run() -> int:
    _run_section_a()
    _run_section_b()
    _run_section_c()
    _run_section_d()
    _run_section_e()
    _run_section_f()

    total = _passed + _failed
    print("\n" + "=" * 60)
    print(f"Phase 2.6a: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"            {_failed} FAILED.")
        return 1
    print("            All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
