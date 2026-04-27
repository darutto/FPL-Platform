"""
run_phase25d3_tests.py
======================
Phase 2.5d3: Operational hardening of the multi-provider orchestration path.

Validates:
A  Gemini configure() side-effect is bounded (_gemini_configure helper)
B  OpenAI timeout compatibility: modern SDK (float accepted) and legacy fallback
C  _orch_request_fn blocked without FPL_TEST_MODE=1
D  Structured event schema unchanged after hardening
E  Gate + cooldown behaviour unchanged after hardening
"""

from __future__ import annotations

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

# Enable test injection paths for sections that use _orch_request_fn.
# Section C temporarily removes this to test the guard.
os.environ["FPL_ORCH_TEST_INJECTION"] = "1"

from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_COOLDOWN,
    OUTCOME_LLM_ERROR,
    OUTCOME_OK,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    _GATE,
    _FailureGate,
    _ORCH_TEST_INJECTION_ENV,
    _test_mode_active,
    ask_orchestrated,
)
from fpl_grounded_assistant.provider_client import (
    PERR_TIMEOUT,
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
# Mock helpers (same shapes as d2)
# ---------------------------------------------------------------------------

class _AntToolBlock:
    type  = "tool_use"
    name  = "get_captain_score"
    input = {"query": "Haaland"}

class _AntResponse:
    content = [_AntToolBlock()]


class _GemFuncCall:
    name = "get_captain_score"
    args = {"query": "Haaland"}

class _GemPart:
    function_call = _GemFuncCall()

class _GemContent:
    parts = [_GemPart()]

class _GemCandidate:
    content = _GemContent()

class _GemResponse:
    candidates = [_GemCandidate()]


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

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


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
# Section A: Gemini configure() side-effect bounded
# ---------------------------------------------------------------------------

def _run_section_a() -> None:
    print("\n=== A: Gemini _gemini_configure() bounds global side-effect ===")

    saved_key = _LAST_GEMINI_CONFIGURED_KEY[0]

    # First call with a new sentinel key — should update cache
    _gemini_configure("sentinel-key-A1")
    ok("A1 key cached after first call",    _LAST_GEMINI_CONFIGURED_KEY[0] == "sentinel-key-A1")

    # Second call with same key — cache hit, no repeated configure()
    _gemini_configure("sentinel-key-A1")
    ok("A2 key unchanged on repeat call",   _LAST_GEMINI_CONFIGURED_KEY[0] == "sentinel-key-A1")

    # Different key — should update cache
    _gemini_configure("sentinel-key-A2")
    ok("A3 key updated on change",          _LAST_GEMINI_CONFIGURED_KEY[0] == "sentinel-key-A2")

    # Consecutive Gemini call_orch_provider calls (via _request_fn) both succeed
    # _request_fn path skips configure(), so these test call-path robustness
    r1 = call_orch_provider(
        PROVIDER_GEMINI,
        model="gemini-test", system="s", tools=[], messages=[{"role": "user", "content": "q"}],
        _request_fn=lambda: _GemResponse(),
    )
    r2 = call_orch_provider(
        PROVIDER_GEMINI,
        model="gemini-test", system="s", tools=[], messages=[{"role": "user", "content": "q"}],
        _request_fn=lambda: _GemResponse(),
    )
    ok("A4 first consecutive Gemini call succeeds",  r1.error_code is None)
    ok("A5 second consecutive Gemini call succeeds", r2.error_code is None)
    ok("A6 response preserved on both",              r1.response is not None and r2.response is not None)

    # Restore
    _LAST_GEMINI_CONFIGURED_KEY[0] = saved_key


# ---------------------------------------------------------------------------
# Section B: OpenAI timeout compatibility
# ---------------------------------------------------------------------------

def _run_section_b() -> None:
    print("\n=== B: OpenAI timeout compatibility helper ===")

    saved_cache = _OAI_TIMEOUT_SUPPORTED[0]
    try:
        # --- Variant 1: modern SDK — accepts timeout= ---
        _OAI_TIMEOUT_SUPPORTED[0] = None   # fresh probe for this variant
        calls_v1: list[dict] = []

        def _sdk_modern(**kwargs: object) -> str:
            calls_v1.append(dict(kwargs))
            return "response_v1"

        r1 = _call_with_oai_compat_timeout(_sdk_modern, timeout_s=15.0, model="m")
        ok("B1 modern SDK: call succeeds",         r1 == "response_v1")
        ok("B2 modern SDK: timeout kwarg passed",  calls_v1[-1].get("timeout") == 15.0)
        ok("B3 modern SDK: called exactly once",   len(calls_v1) == 1)
        ok("B4 modern SDK: model kwarg preserved", calls_v1[-1].get("model") == "m")

        # --- Variant 2: legacy SDK — explicit params, no timeout, no **kwargs ---
        # (represents a real legacy SDK that has no timeout parameter at all)
        _OAI_TIMEOUT_SUPPORTED[0] = None   # fresh probe for this variant
        calls_v2: list[dict] = []

        def _sdk_legacy(model: str, max_tokens: int = 1024,
                         messages: object = None, tools: object = None) -> str:
            calls_v2.append({"model": model, "max_tokens": max_tokens})
            return "response_v2"

        r2 = _call_with_oai_compat_timeout(_sdk_legacy, timeout_s=15.0, model="m")
        ok("B5 legacy SDK: call succeeds via fallback", r2 == "response_v2")
        ok("B6 legacy SDK: fallback called once",       len(calls_v2) == 1)
        ok("B7 legacy SDK: no timeout in fallback",     "timeout" not in calls_v2[0])
        ok("B8 legacy SDK: model kwarg preserved",      calls_v2[0].get("model") == "m")

        # --- Non-TypeError propagates immediately (not masked) ---
        _OAI_TIMEOUT_SUPPORTED[0] = None   # fresh probe
        def _sdk_non_type_err(**_kw: object) -> None:
            raise ValueError("bad credentials")

        caught = None
        try:
            _call_with_oai_compat_timeout(_sdk_non_type_err, timeout_s=15.0)
        except ValueError as exc:
            caught = exc

        ok("B9 ValueError propagates (not swallowed)", caught is not None)
    finally:
        _OAI_TIMEOUT_SUPPORTED[0] = saved_cache

    # --- call_orch_provider OpenAI path still normalises errors correctly ---
    r_timeout = call_orch_provider(
        PROVIDER_OPENAI,
        model="m", system="s", tools=[], messages=[{"role": "user", "content": "q"}],
        max_retries=0,
        _request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
        _sleep_fn=_NO_SLEEP,
    )
    ok("B10 OpenAI timeout still normalised to PERR_TIMEOUT", r_timeout.error_code == PERR_TIMEOUT)


# ---------------------------------------------------------------------------
# Section C: _orch_request_fn blocked without FPL_TEST_MODE
# ---------------------------------------------------------------------------

def _run_section_c() -> None:
    print("\n=== C: _orch_request_fn blocked when FPL_TEST_MODE not set ===")

    # Temporarily clear FPL_TEST_MODE
    old_mode = os.environ.pop(_ORCH_TEST_INJECTION_ENV, None)
    ok("C-pre guard is now inactive", not _test_mode_active())

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
        # Restore FPL_TEST_MODE regardless of test outcome
        if old_mode is not None:
            os.environ[_ORCH_TEST_INJECTION_ENV] = old_mode
        else:
            os.environ[_ORCH_TEST_INJECTION_ENV] = "1"   # re-enable for subsequent sections

    ok("C1 outcome=OUTCOME_LLM_ERROR when blocked", result.outcome == OUTCOME_LLM_ERROR)
    ok("C2 provider NOT called",                    call_count["n"] == 0)
    ok("C3 llm_used=False",                         not result.llm_used)
    ok("C4 answer_text non-empty",                  len(result.answer_text) > 0)
    ok("C5 error message mentions test mode",       "FPL_ORCH_TEST_INJECTION" in (result.error or ""))
    ok("C-post guard restored (FPL_ORCH_TEST_INJECTION=1)", _test_mode_active())

    # With FPL_TEST_MODE=1 the call proceeds normally
    gate2 = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    result_allowed = ask_orchestrated(
        "should I captain Haaland",
        STANDARD_BOOTSTRAP,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=lambda: _AntResponse(),
        _gate=gate2,
    )
    ok("C6 call proceeds with FPL_TEST_MODE=1", result_allowed.outcome in ("ok", "tool_result_error"))


# ---------------------------------------------------------------------------
# Section D: structured event schema unchanged
# ---------------------------------------------------------------------------

def _run_section_d() -> None:
    print("\n=== D: Structured event schema unchanged after hardening ===")

    gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        # Success event
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: _AntResponse(),
            _gate=gate,
        )
        # Failure event
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    evs = cap.events()
    ok("D1 two events emitted",              len(evs) == 2)

    if len(evs) == 2:
        ev_ok, ev_fail = evs[0], evs[1]

        ok("D2 success event='provider_call_success'", ev_ok.get("event")  == "provider_call_success")
        ok("D3 failure event='provider_call_failure'", ev_fail.get("event") == "provider_call_failure")

        required_ok   = {"event", "provider", "model", "latency_ms", "attempts"}
        required_fail = required_ok | {"error_code"}

        ok("D4 success has required fields",  required_ok   <= set(ev_ok.keys()))
        ok("D5 failure has required fields",  required_fail <= set(ev_fail.keys()))
        ok("D6 no error_msg in events",       "error_msg" not in ev_ok and "error_msg" not in ev_fail)
        ok("D7 no error_code in success",     "error_code" not in ev_ok)

    # Verify messages are JSON-parseable
    msgs = cap.messages()
    ok("D8 all fpl_provider_event messages are JSON-parseable", all(
        _try_json(m[len("fpl_provider_event "):]) is not None
        for m in msgs if m.startswith("fpl_provider_event ")
    ))


def _try_json(s: str) -> dict | None:
    try:
        return json.loads(s)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Section E: gate / cooldown unchanged
# ---------------------------------------------------------------------------

def _run_section_e() -> None:
    print("\n=== E: Gate + cooldown unchanged after hardening ===")

    # Two timeouts open gate
    gate = _FailureGate(threshold=2, window_s=60, cooldown_s=9999)
    for _ in range(2):
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
            _gate=gate,
        )
    ok("E1 gate opens after 2 transient errors", gate.is_open())

    # Cooldown skips provider
    call_count = {"n": 0}

    def _count_and_succeed() -> object:
        call_count["n"] += 1
        return _AntResponse()

    result = ask_orchestrated(
        "q", STANDARD_BOOTSTRAP,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=_count_and_succeed,
        _gate=gate,
    )
    ok("E2 OUTCOME_COOLDOWN during active cooldown", result.outcome == OUTCOME_COOLDOWN)
    ok("E3 provider NOT called during cooldown",     call_count["n"] == 0)

    # Auth errors do NOT open gate
    gate2 = _FailureGate(threshold=2, window_s=60, cooldown_s=30)
    for _ in range(3):
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _gate=gate2,
        )
    ok("E4 auth errors do NOT open gate", not gate2.is_open())

    # reset_all clears everything
    gate.reset_all()
    ok("E5 reset_all closes gate",        not gate.is_open())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _run() -> int:
    _run_section_a()
    _run_section_b()
    _run_section_c()
    _run_section_d()
    _run_section_e()

    total = _passed + _failed
    print("\n" + "=" * 60)
    print(f"Phase 2.5d3: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"             {_failed} FAILED.")
        return 1
    print("             All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
