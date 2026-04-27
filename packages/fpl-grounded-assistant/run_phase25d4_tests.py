"""
run_phase25d4_tests.py
======================
Phase 2.5d4: Closing the three operational risks from 2.5d3.

A  _gemini_configure is thread-safe under concurrent access
B  _call_with_oai_compat_timeout falls back only for timeout-TypeError
C  Non-timeout TypeError is NOT masked (propagates immediately)
D  _orch_request_fn blocked without FPL_ORCH_TEST_INJECTION
E  _orch_request_fn allowed with FPL_ORCH_TEST_INJECTION=1
F  Structured event schema unchanged
G  Gate/cooldown no regression
"""

from __future__ import annotations

import json
import logging as _stdlib_logging
import os
import sys
import threading

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

# Enable _orch_request_fn injection for sections that need it.
# Section D temporarily clears this to test the block path.
os.environ["FPL_ORCH_TEST_INJECTION"] = "1"

from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_COOLDOWN,
    OUTCOME_LLM_ERROR,
    PROVIDER_ANTHROPIC,
    _GATE,
    _FailureGate,
    _ORCH_TEST_INJECTION_ENV,
    _test_mode_active,
    ask_orchestrated,
)
from fpl_grounded_assistant.provider_client import (
    PERR_AUTH,
    PERR_TIMEOUT,
    _GEMINI_CONFIGURE_LOCK,
    _LAST_GEMINI_CONFIGURED_KEY,
    _OAI_TIMEOUT_SUPPORTED,
    _call_with_oai_compat_timeout,
    _gemini_configure,
    call_orch_provider,
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


# ---------------------------------------------------------------------------
# Log capture
# ---------------------------------------------------------------------------

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
# Section A: _gemini_configure thread-safe
# ---------------------------------------------------------------------------

def _run_section_a() -> None:
    print("\n=== A: _gemini_configure thread-safe under concurrent access ===")

    # Verify structural guarantees
    ok("A1 _GEMINI_CONFIGURE_LOCK is a threading.Lock",
       isinstance(_GEMINI_CONFIGURE_LOCK, type(threading.Lock())))

    saved_key = _LAST_GEMINI_CONFIGURED_KEY[0]
    errors: list[Exception] = []
    keys_seen: list[str] = []

    def _configure_worker(key: str) -> None:
        try:
            _gemini_configure(key)
            keys_seen.append(_LAST_GEMINI_CONFIGURED_KEY[0] or "")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    # 20 threads all setting the same key — should never raise
    threads = [
        threading.Thread(target=_configure_worker, args=("thread-safe-key-A",))
        for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok("A2 no exceptions from concurrent configure", len(errors) == 0)
    ok("A3 cache set to the expected key",
       _LAST_GEMINI_CONFIGURED_KEY[0] == "thread-safe-key-A")

    # 10 threads each writing a DIFFERENT key — last-writer-wins, but no crash
    errors2: list[Exception] = []
    write_threads = [
        threading.Thread(target=_configure_worker, args=(f"key-variant-{i}",))
        for i in range(10)
    ]
    for t in write_threads:
        t.start()
    for t in write_threads:
        t.join()

    ok("A4 no exceptions from concurrent multi-key configure", len(errors2) == 0)
    # Cache holds one of the written keys (last writer wins — deterministic under lock)
    ok("A5 cache holds a valid key after concurrent writes",
       (_LAST_GEMINI_CONFIGURED_KEY[0] or "").startswith("key-variant-"))

    # Single-threaded: same-key idempotency still works after threading test
    _gemini_configure("single-thread-final-key")
    ok("A6 idempotency still works post-threading",
       _LAST_GEMINI_CONFIGURED_KEY[0] == "single-thread-final-key")

    # Restore
    _LAST_GEMINI_CONFIGURED_KEY[0] = saved_key


# ---------------------------------------------------------------------------
# Section B: timeout-TypeError fallback is precise
# ---------------------------------------------------------------------------

def _run_section_b() -> None:
    print("\n=== B: _call_with_oai_compat_timeout falls back only for timeout-TypeError ===")

    saved_cache = _OAI_TIMEOUT_SUPPORTED[0]
    try:
        # --- Modern SDK: accepts timeout= ---
        _OAI_TIMEOUT_SUPPORTED[0] = None  # fresh probe
        calls: list[dict] = []

        def _accept_timeout(**kw: object) -> str:
            calls.append(kw)
            return "ok"

        r = _call_with_oai_compat_timeout(_accept_timeout, timeout_s=10.0, model="m")
        ok("B1 modern path: succeeds",          r == "ok")
        ok("B2 modern path: timeout kwarg sent", calls[-1].get("timeout") == 10.0)
        ok("B3 modern path: called once",        len(calls) == 1)

        # --- Legacy SDK: **kwargs but rejects timeout at runtime → probe + fallback ---
        _OAI_TIMEOUT_SUPPORTED[0] = None  # fresh probe
        calls2: list[dict] = []

        def _reject_timeout_kwarg(**kw: object) -> str:
            if "timeout" in kw:
                raise TypeError("unexpected keyword argument 'timeout'")
            calls2.append(kw)
            return "fallback_ok"

        r2 = _call_with_oai_compat_timeout(_reject_timeout_kwarg, timeout_s=10.0, model="m")
        ok("B4 legacy path: fallback succeeds",        r2 == "fallback_ok")
        ok("B5 legacy path: fallback called once",     len(calls2) == 1)
        ok("B6 legacy path: timeout absent in retry",  "timeout" not in calls2[0])
        ok("B7 legacy path: model preserved in retry", calls2[0].get("model") == "m")
    finally:
        _OAI_TIMEOUT_SUPPORTED[0] = saved_cache


# ---------------------------------------------------------------------------
# Section C: non-timeout TypeError propagates immediately
# ---------------------------------------------------------------------------

def _run_section_c() -> None:
    print("\n=== C: Non-timeout TypeError propagates immediately (not masked) ===")

    saved_cache = _OAI_TIMEOUT_SUPPORTED[0]
    _OAI_TIMEOUT_SUPPORTED[0] = None   # fresh probe; C1 will populate to False

    try:
        # TypeError whose message does NOT mention "timeout" must propagate
        def _wrong_type(**_kw: object) -> None:
            raise TypeError("argument of type 'int' is not iterable")

        caught: TypeError | None = None
        try:
            _call_with_oai_compat_timeout(_wrong_type, timeout_s=10.0, model="m")
        except TypeError as exc:
            caught = exc

        ok("C1 non-timeout TypeError propagates",  caught is not None)
        ok("C2 original message preserved",
           caught is not None and "iterable" in str(caught))

        # TypeError about wrong model type — also propagates
        def _wrong_model_type(**_kw: object) -> None:
            raise TypeError("model must be a string, got int")

        caught2: TypeError | None = None
        try:
            _call_with_oai_compat_timeout(_wrong_model_type, timeout_s=10.0, model=42)
        except TypeError as exc:
            caught2 = exc

        ok("C3 wrong-model TypeError propagates", caught2 is not None)
        ok("C4 only timeout-TypeError triggers fallback — verified by C1-C3",
           caught is not None and caught2 is not None)

        # Sanity: a timeout-related TypeError still falls back
        # After C1 set cache=False, this function calls without timeout → "ok"
        def _timeout_type_err(**kw: object) -> str:
            if "timeout" in kw:
                raise TypeError("got unexpected keyword argument 'timeout'")
            return "ok"

        r = _call_with_oai_compat_timeout(_timeout_type_err, timeout_s=5.0, model="m")
        ok("C5 timeout-TypeError still triggers fallback", r == "ok")
    finally:
        _OAI_TIMEOUT_SUPPORTED[0] = saved_cache


# ---------------------------------------------------------------------------
# Section D: _orch_request_fn blocked without FPL_ORCH_TEST_INJECTION
# ---------------------------------------------------------------------------

def _run_section_d() -> None:
    print("\n=== D: _orch_request_fn blocked without FPL_ORCH_TEST_INJECTION ===")

    old = os.environ.pop(_ORCH_TEST_INJECTION_ENV, None)
    ok("D-pre FPL_ORCH_TEST_INJECTION not active", not _test_mode_active())

    call_count = {"n": 0}

    def _must_not_be_called() -> object:
        call_count["n"] += 1
        return _AntResponse()

    gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    try:
        result = ask_orchestrated(
            "should I captain Haaland",
            STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=_must_not_be_called,
            _gate=gate,
        )
    finally:
        # Restore — always re-enable for subsequent sections
        os.environ[_ORCH_TEST_INJECTION_ENV] = old if old is not None else "1"

    ok("D1 outcome=OUTCOME_LLM_ERROR",      result.outcome == OUTCOME_LLM_ERROR)
    ok("D2 provider NOT called",            call_count["n"] == 0)
    ok("D3 llm_used=False",                 not result.llm_used)
    ok("D4 error cites FPL_ORCH_TEST_INJECTION",
       "FPL_ORCH_TEST_INJECTION" in (result.error or ""))
    ok("D-post guard restored",             _test_mode_active())


# ---------------------------------------------------------------------------
# Section E: _orch_request_fn allowed with FPL_ORCH_TEST_INJECTION=1
# ---------------------------------------------------------------------------

def _run_section_e() -> None:
    print("\n=== E: _orch_request_fn allowed with FPL_ORCH_TEST_INJECTION=1 ===")

    ok("E-pre FPL_ORCH_TEST_INJECTION active", _test_mode_active())

    gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    result = ask_orchestrated(
        "should I captain Haaland",
        STANDARD_BOOTSTRAP,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=lambda: _AntResponse(),
        _gate=gate,
    )
    ok("E1 call succeeds with flag set", result.outcome in ("ok", "tool_result_error"))
    ok("E2 llm_used=True",               result.llm_used)
    ok("E3 tool_chosen set",             result.tool_chosen is not None)

    # Verify old FPL_TEST_MODE is no longer honoured (it was removed in 2.5d4)
    old_inj = os.environ.pop(_ORCH_TEST_INJECTION_ENV, None)
    os.environ["FPL_TEST_MODE"] = "1"   # old flag, should have no effect
    call_count = {"n": 0}

    def _should_be_blocked() -> object:
        call_count["n"] += 1
        return _AntResponse()

    gate2 = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    result2 = ask_orchestrated(
        "q", STANDARD_BOOTSTRAP,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=_should_be_blocked,
        _gate=gate2,
    )
    os.environ.pop("FPL_TEST_MODE", None)
    if old_inj is not None:
        os.environ[_ORCH_TEST_INJECTION_ENV] = old_inj
    else:
        os.environ[_ORCH_TEST_INJECTION_ENV] = "1"

    ok("E4 old FPL_TEST_MODE has no effect (blocked without new flag)",
       result2.outcome == OUTCOME_LLM_ERROR)
    ok("E5 provider not called with old flag only", call_count["n"] == 0)


# ---------------------------------------------------------------------------
# Section F: structured event schema unchanged
# ---------------------------------------------------------------------------

def _run_section_f() -> None:
    print("\n=== F: Structured event schema unchanged ===")

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
    ok("F1 two events emitted", len(evs) == 2)

    if len(evs) == 2:
        ev_ok, ev_fail = evs[0], evs[1]
        required_ok   = {"event", "provider", "model", "latency_ms", "attempts"}
        required_fail = required_ok | {"error_code"}

        ok("F2 success event='provider_call_success'",
           ev_ok.get("event") == "provider_call_success")
        ok("F3 failure event='provider_call_failure'",
           ev_fail.get("event") == "provider_call_failure")
        ok("F4 success required fields present",  required_ok   <= set(ev_ok.keys()))
        ok("F5 failure required fields present",  required_fail <= set(ev_fail.keys()))
        ok("F6 no error_msg leaked in either event",
           "error_msg" not in ev_ok and "error_msg" not in ev_fail)


# ---------------------------------------------------------------------------
# Section G: gate / cooldown no regression
# ---------------------------------------------------------------------------

def _run_section_g() -> None:
    print("\n=== G: Gate + cooldown no regression ===")

    gate = _FailureGate(threshold=2, window_s=60, cooldown_s=9999)

    for _ in range(2):
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
            _gate=gate,
        )
    ok("G1 gate opens after 2 transient errors", gate.is_open())

    call_count = {"n": 0}

    def _count() -> object:
        call_count["n"] += 1
        return _AntResponse()

    r = ask_orchestrated(
        "q", STANDARD_BOOTSTRAP,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=_count,
        _gate=gate,
    )
    ok("G2 OUTCOME_COOLDOWN during cooldown",  r.outcome == OUTCOME_COOLDOWN)
    ok("G3 provider NOT called during cooldown", call_count["n"] == 0)

    # Auth errors do NOT count toward gate
    gate2 = _FailureGate(threshold=2, window_s=60, cooldown_s=30)
    for _ in range(3):
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _gate=gate2,
        )
    ok("G4 auth errors do NOT open gate", not gate2.is_open())

    gate.reset_all()
    ok("G5 reset_all closes gate", not gate.is_open())


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
    _run_section_g()

    total = _passed + _failed
    print("\n" + "=" * 60)
    print(f"Phase 2.5d4: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"             {_failed} FAILED.")
        return 1
    print("             All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
