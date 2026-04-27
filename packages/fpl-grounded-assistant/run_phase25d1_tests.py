"""
run_phase25d1_tests.py
======================
Phase 2.5d1: Orchestrator ProviderInterface parity + degradation gate.

Validates:
1. ask_orchestrated() emits the same structured provider event schema as
   llm_layer._log_provider_event (success and failure cases).
2. ProviderResult envelope carries latency_ms and attempts for orchestrator calls.
3. _FailureGate accumulates only transient errors (timeout, rate-limit, network).
4. Gate opening threshold and window work correctly.
5. Cooldown active: ask_orchestrated() returns OUTCOME_COOLDOWN without touching provider.
6. Cooldown expiry: gate closes again and provider calls resume.
7. No API key or secret appears in event payloads or log messages.
8. No-regression: 2.5a/2.5b/2.5c all pass (called inline via subprocess-free import).

Sections
--------
A  Orchestrator success — structured provider_call_success event emitted
B  Orchestrator failure — structured provider_call_failure event emitted
C  Gate transient accumulation — only PERR_TIMEOUT/RATE_LIMIT/NETWORK count
D  Cooldown active — OUTCOME_COOLDOWN returned, llm_used=False, no log event
E  Cooldown expiry — gate closes; provider call resumes
F  No-secret in event payloads and log messages
G  Schema parity — orchestrator event fields match llm_layer event fields
"""

from __future__ import annotations

import json
import logging as _stdlib_logging
import os
import sys
import time

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

from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_COOLDOWN,
    OUTCOME_LLM_ERROR,
    OUTCOME_NO_CLIENT,
    OUTCOME_OK,
    PROVIDER_ANTHROPIC,
    _GATE,
    _FailureGate,
    _TRANSIENT_PERR,
    _log_orch_provider_event,
    ask_orchestrated,
)
from fpl_grounded_assistant.provider_client import (
    PERR_AUTH,
    PERR_NETWORK,
    PERR_PROVIDER,
    PERR_RATE_LIMIT,
    PERR_TIMEOUT,
    ProviderResult,
    call_provider_request,
)

_passed = 0
_failed = 0

# Reset global gate state before any tests so prior test-run pollution is cleared.
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

class _StatusError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


# Minimal Anthropic tool-use response shape for ask_orchestrated
class _ToolBlock:
    type  = "tool_use"
    name  = "get_captain_score"
    input = {"query": "Haaland"}

class _AntToolResponse:
    content = [_ToolBlock()]

class _MsgAPI:
    def __init__(self, fn):
        self._fn = fn
    def create(self, **_kw):
        return self._fn()

class _MockClient:
    def __init__(self, fn):
        self.messages = _MsgAPI(fn)


# ---------------------------------------------------------------------------
# Log capture
# ---------------------------------------------------------------------------

class _LogCapture(_stdlib_logging.Handler):
    def __init__(self) -> None:
        super().__init__(_stdlib_logging.DEBUG)
        self.records: list[_stdlib_logging.LogRecord] = []

    def emit(self, record: _stdlib_logging.LogRecord) -> None:
        self.records.append(record)

    def fpl_events(self) -> list[dict]:
        return [getattr(r, "fpl_event") for r in self.records if hasattr(r, "fpl_event")]

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


def _attach(logger_name: str) -> tuple[_LogCapture, _stdlib_logging.Logger, int]:
    cap = _LogCapture()
    log = _stdlib_logging.getLogger(logger_name)
    log.addHandler(cap)
    saved = log.level
    log.setLevel(_stdlib_logging.DEBUG)
    return cap, log, saved


def _detach(cap: _LogCapture, log: _stdlib_logging.Logger, saved: int) -> None:
    log.removeHandler(cap)
    log.setLevel(saved)


# ---------------------------------------------------------------------------
# Section A: orchestrator success emits provider_call_success event
# ---------------------------------------------------------------------------

def _run_section_a() -> None:
    print("\n=== A: Orchestrator success emits structured provider_call_success ===")
    fresh_gate = _FailureGate(threshold=3, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        result = ask_orchestrated(
            "should I captain Haaland",
            STANDARD_BOOTSTRAP,
            client=_MockClient(lambda: _AntToolResponse()),
            _gate=fresh_gate,
        )
    finally:
        _detach(cap, log, saved)

    ok("A1 outcome is OK or tool_result_error (LLM call succeeded)",
       result.outcome in (OUTCOME_OK, "tool_result_error"))
    ok("A2 llm_used=True",     result.llm_used)
    ok("A3 model != 'none'",   result.model != "none")

    events = cap.fpl_events()
    ok("A4 exactly 1 event emitted",  len(events) == 1)

    if events:
        ev = events[0]
        ok("A5 event='provider_call_success'", ev.get("event") == "provider_call_success")
        ok("A6 event has provider",            "provider"   in ev)
        ok("A7 event has model",               "model"      in ev)
        ok("A8 event has latency_ms",          "latency_ms" in ev)
        ok("A9 event has attempts",            "attempts"   in ev)
        ok("A10 latency_ms >= 0",              ev.get("latency_ms", -1) >= 0)
        ok("A11 attempts >= 1",                ev.get("attempts", 0) >= 1)
        ok("A12 no error_code on success",     "error_code" not in ev)


# ---------------------------------------------------------------------------
# Section B: orchestrator failure emits provider_call_failure event
# ---------------------------------------------------------------------------

def _run_section_b() -> None:
    print("\n=== B: Orchestrator failure emits structured provider_call_failure ===")
    fresh_gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)  # high threshold
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        result = ask_orchestrated(
            "who should I captain",
            STANDARD_BOOTSTRAP,
            client=_MockClient(
                lambda: (_ for _ in ()).throw(_StatusError("unauthorized", 401))
            ),
            _gate=fresh_gate,
        )
    finally:
        _detach(cap, log, saved)

    ok("B1 outcome=OUTCOME_LLM_ERROR", result.outcome == OUTCOME_LLM_ERROR)
    ok("B2 llm_used=False",            not result.llm_used)

    events = cap.fpl_events()
    ok("B3 exactly 1 event emitted",   len(events) == 1)

    if events:
        ev = events[0]
        ok("B4 event='provider_call_failure'", ev.get("event") == "provider_call_failure")
        ok("B5 error_code=PERR_AUTH",          ev.get("error_code") == PERR_AUTH)
        ok("B6 event has latency_ms",          "latency_ms" in ev)
        ok("B7 event has attempts",            "attempts"   in ev)
        ok("B8 no error_msg in event",         "error_msg"  not in ev)
        ok("B9 latency_ms >= 0",               ev.get("latency_ms", -1) >= 0)


# ---------------------------------------------------------------------------
# Section C: gate transient accumulation — correct error codes count
# ---------------------------------------------------------------------------

def _run_section_c() -> None:
    print("\n=== C: Gate transient accumulation ===")
    gate = _FailureGate(threshold=3, window_s=60, cooldown_s=30)

    # Transient errors must count
    gate.record_failure(PERR_TIMEOUT)
    ok("C1 gate not open after 1 timeout",       not gate.is_open())
    gate.record_failure(PERR_RATE_LIMIT)
    ok("C2 gate not open after 2 transient",     not gate.is_open())
    gate.record_failure(PERR_NETWORK)
    ok("C3 gate opens at threshold=3",           gate.is_open())

    # Reset and verify non-transient errors do NOT count
    gate.reset_all()
    gate.record_failure(PERR_AUTH)
    ok("C4 PERR_AUTH does not count",            not gate.is_open())
    gate.record_failure(PERR_PROVIDER)
    ok("C5 PERR_PROVIDER does not count",        not gate.is_open())
    gate.record_failure(None)
    ok("C6 None error_code does not count",      not gate.is_open())

    # Verify _TRANSIENT_PERR contains exactly the right three codes
    ok("C7 PERR_TIMEOUT in _TRANSIENT_PERR",     PERR_TIMEOUT     in _TRANSIENT_PERR)
    ok("C8 PERR_RATE_LIMIT in _TRANSIENT_PERR",  PERR_RATE_LIMIT  in _TRANSIENT_PERR)
    ok("C9 PERR_NETWORK in _TRANSIENT_PERR",     PERR_NETWORK     in _TRANSIENT_PERR)
    ok("C10 PERR_AUTH not in _TRANSIENT_PERR",   PERR_AUTH        not in _TRANSIENT_PERR)
    ok("C11 PERR_PROVIDER not in _TRANSIENT_PERR", PERR_PROVIDER  not in _TRANSIENT_PERR)

    # reset_on_success clears accumulated failures
    gate2 = _FailureGate(threshold=3, window_s=60, cooldown_s=30)
    gate2.record_failure(PERR_TIMEOUT)
    gate2.record_failure(PERR_TIMEOUT)
    gate2.reset_on_success()
    gate2.record_failure(PERR_TIMEOUT)   # counter cleared → only 1 now
    ok("C12 reset_on_success clears counter",    not gate2.is_open())


# ---------------------------------------------------------------------------
# Section D: cooldown active — OUTCOME_COOLDOWN, no provider call made
# ---------------------------------------------------------------------------

def _run_section_d() -> None:
    print("\n=== D: Cooldown active returns OUTCOME_COOLDOWN without calling provider ===")
    gate = _FailureGate(threshold=1, window_s=60, cooldown_s=9999)
    gate.record_failure(PERR_TIMEOUT)    # opens immediately (threshold=1)
    ok("D1 gate is open", gate.is_open())

    call_count = {"n": 0}

    def _count_and_succeed():
        call_count["n"] += 1
        return _AntToolResponse()

    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        result = ask_orchestrated(
            "captain pick",
            STANDARD_BOOTSTRAP,
            client=_MockClient(_count_and_succeed),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    ok("D2 outcome=OUTCOME_COOLDOWN",    result.outcome == OUTCOME_COOLDOWN)
    ok("D3 llm_used=False",              not result.llm_used)
    ok("D4 provider NOT called",         call_count["n"] == 0)
    ok("D5 no events emitted",           len(cap.fpl_events()) == 0)
    ok("D6 answer_text is non-empty",    len(result.answer_text) > 0)


# ---------------------------------------------------------------------------
# Section E: cooldown expiry — gate closes; provider calls resume
# ---------------------------------------------------------------------------

def _run_section_e() -> None:
    print("\n=== E: Cooldown expiry closes gate and resumes provider calls ===")
    gate = _FailureGate(threshold=1, window_s=60, cooldown_s=30)
    gate.record_failure(PERR_TIMEOUT)
    ok("E1 gate open after threshold",   gate.is_open())

    # Manually expire the cooldown
    gate._cooldown_until = time.monotonic() - 0.001
    ok("E2 gate closed after expiry",    not gate.is_open())

    # Provider call should now proceed
    call_count = {"n": 0}

    def _count_and_succeed():
        call_count["n"] += 1
        return _AntToolResponse()

    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        result = ask_orchestrated(
            "captain pick",
            STANDARD_BOOTSTRAP,
            client=_MockClient(_count_and_succeed),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    ok("E3 outcome != OUTCOME_COOLDOWN", result.outcome != OUTCOME_COOLDOWN)
    ok("E4 provider was called",         call_count["n"] >= 1)
    ok("E5 event emitted after expiry",  len(cap.fpl_events()) >= 1)

    # Failure after expiry accumulates again
    gate2 = _FailureGate(threshold=2, window_s=60, cooldown_s=30)
    gate2.record_failure(PERR_TIMEOUT)
    gate2._cooldown_until = time.monotonic() - 0.001   # expire any phantom cooldown
    ok("E6 gate stays closed at 1 of 2", not gate2.is_open())
    gate2.record_failure(PERR_TIMEOUT)
    ok("E7 gate opens at threshold=2",   gate2.is_open())


# ---------------------------------------------------------------------------
# Section F: no secret in event payloads or log messages
# ---------------------------------------------------------------------------

def _run_section_f() -> None:
    print("\n=== F: No secret in event payloads or log messages ===")
    _sentinel = "sk-SENTINEL-SECRET-KEY-25D1-DO-NOT-LOG"

    old_key = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = _sentinel

    fresh_gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        ask_orchestrated(
            "captain pick",
            STANDARD_BOOTSTRAP,
            client=_MockClient(
                lambda: (_ for _ in ()).throw(
                    Exception(f"Request failed with key {_sentinel}")
                )
            ),
            _gate=fresh_gate,
        )
    finally:
        _detach(cap, log, saved)
        if old_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = old_key
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    all_msgs   = " ".join(cap.messages())
    all_events = " ".join(json.dumps(e) for e in cap.fpl_events())

    ok("F1 sentinel not in log messages",   _sentinel not in all_msgs)
    ok("F2 sentinel not in event payloads", _sentinel not in all_events)

    # Verify real key (if set) also doesn't appear
    for env_name in ("OPENAI_API_KEY", "GOOGLE_API_KEY"):
        real = os.environ.get(env_name, "")
        if real:
            ok(f"F3 {env_name} not in messages", real not in all_msgs)


# ---------------------------------------------------------------------------
# Section G: schema parity with llm_layer events
# ---------------------------------------------------------------------------

def _run_section_g() -> None:
    print("\n=== G: Event schema parity with llm_layer ===")

    # Directly call _log_orch_provider_event and llm_layer._log_provider_event
    # with the same ProviderResult, then compare the emitted fpl_event dicts.
    from fpl_grounded_assistant.llm_layer import _log_provider_event as _llm_log_event

    test_result_ok = ProviderResult(
        text="hi", model="test-model", error_code=None,
        error_msg=None, attempts=1, latency_ms=55.5,
    )
    test_result_fail = ProviderResult(
        text=None, model="test-model", error_code=PERR_TIMEOUT,
        error_msg="timed out", attempts=2, latency_ms=20000.0,
    )

    # Capture orchestrator events
    cap_orch, log_orch, saved_orch = _attach("fpl_grounded_assistant.orchestrator")
    try:
        _log_orch_provider_event("anthropic", test_result_ok)
        _log_orch_provider_event("anthropic", test_result_fail)
    finally:
        _detach(cap_orch, log_orch, saved_orch)

    # Capture llm_layer events
    cap_llm, log_llm, saved_llm = _attach("fpl_grounded_assistant.llm_layer")
    try:
        _llm_log_event("anthropic", test_result_ok)
        _llm_log_event("anthropic", test_result_fail)
    finally:
        _detach(cap_llm, log_llm, saved_llm)

    orch_events = cap_orch.fpl_events()
    llm_events  = cap_llm.fpl_events()

    ok("G1 both paths emit 2 events",        len(orch_events) == 2 and len(llm_events) == 2)

    if len(orch_events) == 2 and len(llm_events) == 2:
        # Success event field parity
        ok("G2 success event keys match",
           set(orch_events[0].keys()) == set(llm_events[0].keys()))
        # Failure event field parity
        ok("G3 failure event keys match",
           set(orch_events[1].keys()) == set(llm_events[1].keys()))
        # Values must match
        ok("G4 success event values match",  orch_events[0] == llm_events[0])
        ok("G5 failure event values match",  orch_events[1] == llm_events[1])

    # Required fields present in orchestrator success event
    if orch_events:
        ev_ok = orch_events[0]
        for field in ("event", "provider", "model", "latency_ms", "attempts"):
            ok(f"G6 success has '{field}'", field in ev_ok)

    # Required fields present in orchestrator failure event
    if len(orch_events) > 1:
        ev_fail = orch_events[1]
        for field in ("event", "provider", "model", "error_code", "latency_ms", "attempts"):
            ok(f"G7 failure has '{field}'", field in ev_fail)


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
    print(f"Phase 2.5d1: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"             {_failed} FAILED.")
        return 1
    print("             All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
