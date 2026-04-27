"""
run_phase25c_tests.py
=====================
Phase 2.5c: Provider observability and safe logging validation.

Validates:
1. ProviderResult.latency_ms is populated and >= 0 on every call path.
2. Structured log events emitted via _log_provider_event() contain the
   required fields: event, provider, model, latency_ms, attempts
   (+ error_code on failure).
3. No API key or secret appears in any log message or error message.
4. Latency aggregates ALL retry attempts — latency with 2 attempts >
   latency with 1 attempt when calls take real time.
5. ask_llm() emits a structured log event for both success and failure.
6. 2.5a (17) and 2.5b (34) no-regression.

Sections
--------
A  latency_ms >= 0 for success, auth failure, timeout failure
B  structured log event fields (provider, model, latency_ms, attempts)
C  no secret / API key in any log message or error_msg
D  latency aggregates retry attempts (2 retries costs more than 1)
E  ask_llm() emits structured log on success and on failure
F  no-regression 2.5a / 2.5b call_provider_request scenarios
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

from fpl_grounded_assistant import STANDARD_BOOTSTRAP, ask_llm
from fpl_grounded_assistant.provider_client import (
    PERR_AUTH,
    PERR_TIMEOUT,
    PERR_RATE_LIMIT,
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderNotAvailableError,
    call_provider_request,
)

_passed = 0
_failed = 0


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


class _AntTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text

class _AntResponse:
    def __init__(self, text: str) -> None:
        self.content = [_AntTextBlock(text)]


class _MsgAPI:
    def __init__(self, fn):
        self._fn = fn
    def create(self, **_kwargs):
        return self._fn()

class _Client:
    def __init__(self, fn):
        self.messages = _MsgAPI(fn)


def _make_gemini() -> GeminiProvider | None:
    """Return a GeminiProvider with sentinel key, or None if SDK absent."""
    try:
        return GeminiProvider(api_key="test-sentinel-key-25c")
    except ProviderNotAvailableError as exc:
        if "not installed" in str(exc):
            return None
        raise


# ---------------------------------------------------------------------------
# Log capture context manager
# ---------------------------------------------------------------------------

class _LogCapture(_stdlib_logging.Handler):
    """Collect log records from a named logger for assertion."""

    def __init__(self) -> None:
        super().__init__(_stdlib_logging.DEBUG)
        self.records: list[_stdlib_logging.LogRecord] = []

    def emit(self, record: _stdlib_logging.LogRecord) -> None:
        self.records.append(record)

    def fpl_events(self) -> list[dict]:
        """Return all fpl_event dicts from captured records."""
        return [
            getattr(r, "fpl_event")
            for r in self.records
            if hasattr(r, "fpl_event")
        ]

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


def _with_log_capture(logger_name: str):
    """Return (capture_handler, logger) with capture attached."""
    cap = _LogCapture()
    log = _stdlib_logging.getLogger(logger_name)
    log.addHandler(cap)
    saved_level = log.level
    log.setLevel(_stdlib_logging.DEBUG)
    return cap, log, saved_level


def _detach(cap, log, saved_level) -> None:
    log.removeHandler(cap)
    log.setLevel(saved_level)


# ---------------------------------------------------------------------------
# Section A: latency_ms >= 0 on all call paths
# ---------------------------------------------------------------------------

def _run_section_a(gem: GeminiProvider | None) -> None:
    print("\n=== A: latency_ms >= 0 on all call paths ===")

    # A-ant: AnthropicProvider via mock client (always available)
    ant = AnthropicProvider(client=_Client(lambda: _AntResponse("hi")))

    r_ant_ok = ant.call(
        model="claude-test", system_prompt="s", user_message="u",
    )
    ok("A1 Anthropic success latency_ms >= 0",   r_ant_ok.latency_ms >= 0)
    ok("A2 Anthropic success latency_ms is float", isinstance(r_ant_ok.latency_ms, float))

    r_ant_auth = ant.call(
        model="claude-test", system_prompt="s", user_message="u",
        _request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
        _sleep_fn=_NO_SLEEP,
    )
    ok("A3 Anthropic auth-fail latency_ms >= 0", r_ant_auth.latency_ms >= 0)

    r_ant_timeout = ant.call(
        model="claude-test", system_prompt="s", user_message="u",
        max_retries=1,
        _request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
        _sleep_fn=_NO_SLEEP,
    )
    ok("A4 Anthropic timeout latency_ms >= 0", r_ant_timeout.latency_ms >= 0)

    if gem is not None:
        class _GemResp:
            text = "Haaland looks good."

        r_gem_ok = gem.call(
            model="gemini-test", system_prompt="s", user_message="u",
            _request_fn=lambda: _GemResp(),
        )
        ok("A5 Gemini success latency_ms >= 0", r_gem_ok.latency_ms >= 0)
    else:
        print("  SKIP  A5 Gemini success — SDK not installed")


# ---------------------------------------------------------------------------
# Section B: structured log event fields
# ---------------------------------------------------------------------------

def _run_section_b(gem: GeminiProvider | None) -> None:
    print("\n=== B: structured log event fields ===")

    # Capture from provider_client logger isn't the right target —
    # _log_provider_event lives in llm_layer. We verify it via ask_llm() in
    # Section E. Here we test the event dict shape directly by calling
    # _log_provider_event manually and capturing the llm_layer logger.

    from fpl_grounded_assistant.llm_layer import _log_provider_event
    from fpl_grounded_assistant.provider_client import ProviderResult

    cap, log, saved = _with_log_capture("fpl_grounded_assistant.llm_layer")
    try:
        # Success result
        success_result = ProviderResult(
            text="hello", model="test-model", error_code=None,
            error_msg=None, attempts=1, latency_ms=12.5,
        )
        _log_provider_event("anthropic", success_result)

        # Failure result
        failure_result = ProviderResult(
            text=None, model="test-model", error_code=PERR_TIMEOUT,
            error_msg="TimeoutError: timed out", attempts=2, latency_ms=220.3,
        )
        _log_provider_event("gemini", failure_result)
    finally:
        _detach(cap, log, saved)

    events = cap.fpl_events()
    ok("B1 two events emitted", len(events) == 2)

    if len(events) >= 2:
        ev_ok, ev_fail = events[0], events[1]

        # Success event fields
        ok("B2 success event='provider_call_success'", ev_ok.get("event") == "provider_call_success")
        ok("B3 success has provider",    "provider"   in ev_ok)
        ok("B4 success has model",       "model"      in ev_ok)
        ok("B5 success has latency_ms",  "latency_ms" in ev_ok)
        ok("B6 success has attempts",    "attempts"   in ev_ok)
        ok("B7 success no error_code",   "error_code" not in ev_ok)
        ok("B8 success latency_ms=12.5", ev_ok.get("latency_ms") == 12.5)

        # Failure event fields
        ok("B9 failure event='provider_call_failure'",  ev_fail.get("event") == "provider_call_failure")
        ok("B10 failure has error_code",                 "error_code" in ev_fail)
        ok("B11 failure error_code=PERR_TIMEOUT",        ev_fail.get("error_code") == PERR_TIMEOUT)
        ok("B12 failure has latency_ms",                 "latency_ms" in ev_fail)
        ok("B13 failure no error_msg (secret guard)",    "error_msg"  not in ev_fail)
        ok("B14 failure latency_ms=220.3",               ev_fail.get("latency_ms") == 220.3)

        # Verify message is JSON-parseable from the log message string
        msgs = cap.messages()
        ok("B15 messages are JSON-parseable", all(
            _try_parse_event_msg(m) is not None
            for m in msgs if m.startswith("fpl_provider_event ")
        ))


def _try_parse_event_msg(msg: str) -> dict | None:
    """Parse the JSON payload from a 'fpl_provider_event {...}' log message."""
    try:
        payload = msg[len("fpl_provider_event "):]
        return json.loads(payload)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Section C: no secret / API key in any log or error_msg
# ---------------------------------------------------------------------------

def _run_section_c() -> None:
    print("\n=== C: no secret in any log message or error_msg ===")

    # Set a sentinel 'secret' key in env so _sanitize_error has something to redact
    _sentinel_key = "sk-test-SENTINEL-SECRET-KEY-PHASE25C-DO-NOT-LOG"
    old_ant = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = _sentinel_key

    cap, log, saved = _with_log_capture("fpl_grounded_assistant.llm_layer")
    collected_error_msgs: list[str] = []

    try:
        ant = AnthropicProvider(client=_Client(
            lambda: (_ for _ in ()).throw(
                Exception(f"Auth failed with key {_sentinel_key}")
            )
        ))
        result = ant.call(
            model="m", system_prompt="s", user_message="u",
            _sleep_fn=_NO_SLEEP,
        )
        collected_error_msgs.append(result.error_msg or "")

        from fpl_grounded_assistant.llm_layer import _log_provider_event
        _log_provider_event("anthropic", result)
    finally:
        _detach(cap, log, saved)
        if old_ant is not None:
            os.environ["ANTHROPIC_API_KEY"] = old_ant
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    all_log_msgs = " ".join(cap.messages())
    all_error_msgs = " ".join(collected_error_msgs)
    all_event_json = " ".join(
        json.dumps(e) for e in cap.fpl_events()
    )

    ok("C1 secret not in log messages",    _sentinel_key not in all_log_msgs)
    ok("C2 secret not in fpl_event JSON",  _sentinel_key not in all_event_json)
    ok("C3 error_msg has [redacted]",       "[redacted]" in all_error_msgs)
    ok("C4 error_msg secret replaced",      _sentinel_key not in all_error_msgs)

    # Verify no well-known env var names leak real values
    for env_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        real_val = os.environ.get(env_name)
        if real_val:
            ok(
                f"C5 {env_name} not in log messages",
                real_val not in all_log_msgs,
            )


# ---------------------------------------------------------------------------
# Section D: latency aggregates retry attempts
# ---------------------------------------------------------------------------

def _run_section_d() -> None:
    print("\n=== D: latency aggregates retry attempts ===")

    _DELAY = 0.015  # 15 ms per attempt — detectable on any system

    def _slow_timeout():
        time.sleep(_DELAY)
        raise TimeoutError("timed out")

    ant = AnthropicProvider(client=_Client(lambda: _AntResponse("x")))

    r_no_retry = ant.call(
        model="m", system_prompt="s", user_message="u",
        max_retries=0,
        _request_fn=_slow_timeout,
        _sleep_fn=_NO_SLEEP,
    )

    r_with_retry = ant.call(
        model="m", system_prompt="s", user_message="u",
        max_retries=1,
        _request_fn=_slow_timeout,
        _sleep_fn=_NO_SLEEP,
    )

    ok("D1 no-retry: attempts=1",             r_no_retry.attempts == 1)
    ok("D2 with-retry: attempts=2",           r_with_retry.attempts == 2)
    ok("D3 retry latency > no-retry latency", r_with_retry.latency_ms > r_no_retry.latency_ms)
    ok("D4 no-retry latency >= 0",            r_no_retry.latency_ms >= 0)
    ok("D5 with-retry latency >= 0",          r_with_retry.latency_ms >= 0)


# ---------------------------------------------------------------------------
# Section E: ask_llm() emits structured log on success and failure
# ---------------------------------------------------------------------------

def _run_section_e() -> None:
    print("\n=== E: ask_llm() emits structured log on success and failure ===")

    cap, log, saved = _with_log_capture("fpl_grounded_assistant.llm_layer")
    try:
        # Success path
        ask_llm(
            "should I captain Haaland",
            STANDARD_BOOTSTRAP,
            client=_Client(lambda: _AntResponse("Yes, Haaland is a great captain.")),
        )
        # Failure path
        ask_llm(
            "who is the best captain",
            STANDARD_BOOTSTRAP,
            client=_Client(lambda: (_ for _ in ()).throw(_StatusError("unauth", 401))),
        )
    finally:
        _detach(cap, log, saved)

    events = cap.fpl_events()
    ok("E1 at least 2 events captured (one per ask_llm call)", len(events) >= 2)

    success_events = [e for e in events if e.get("event") == "provider_call_success"]
    failure_events = [e for e in events if e.get("event") == "provider_call_failure"]

    ok("E2 success event emitted",              len(success_events) >= 1)
    ok("E3 failure event emitted",              len(failure_events) >= 1)

    if success_events:
        ev = success_events[0]
        ok("E4 success event has provider",    "provider"   in ev)
        ok("E5 success event has model",       "model"      in ev)
        ok("E6 success event has latency_ms",  "latency_ms" in ev)
        ok("E7 success event has attempts",    "attempts"   in ev)

    if failure_events:
        ev = failure_events[0]
        ok("E8 failure event has error_code",  "error_code" in ev)
        ok("E9 failure event has latency_ms",  "latency_ms" in ev)
        ok("E10 failure no error_msg field",   "error_msg"  not in ev)

    # Verify no API key in any of the log messages
    all_msgs = " ".join(cap.messages())
    for env_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_name, "")
        if val:
            ok(f"E11 {env_name} not in ask_llm log", val not in all_msgs)


# ---------------------------------------------------------------------------
# Section F: no-regression (2.5a call_provider_request + 2.5b ProviderResult)
# ---------------------------------------------------------------------------

def _run_section_f(gem: GeminiProvider | None) -> None:
    print("\n=== F: no-regression (2.5a + 2.5b) ===")

    # 2.5a: call_provider_request still works
    r = call_provider_request(lambda: {"ok": True}, max_retries=1)
    ok("F1 2.5a raw success",          r.success)
    ok("F2 2.5a raw attempts=1",       r.attempts == 1)
    ok("F3 2.5a raw error_code None",  r.error_code is None)

    r_auth = call_provider_request(
        lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
        max_retries=2, _sleep_fn=_NO_SLEEP,
    )
    ok("F4 2.5a auth code=PERR_AUTH",    r_auth.error_code == PERR_AUTH)
    ok("F5 2.5a auth attempts=1",        r_auth.attempts == 1)

    r_timeout = call_provider_request(
        lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
        max_retries=1, _sleep_fn=_NO_SLEEP,
    )
    ok("F6 2.5a timeout code=PERR_TIMEOUT", r_timeout.error_code == PERR_TIMEOUT)
    ok("F7 2.5a timeout attempts=2",        r_timeout.attempts == 2)

    # 2.5b: ProviderResult now has latency_ms (no default — must be supplied)
    ant = AnthropicProvider(client=_Client(lambda: _AntResponse("hi")))
    pr = ant.call(model="m", system_prompt="s", user_message="u")
    ok("F8 2.5b ProviderResult has latency_ms attr", hasattr(pr, "latency_ms"))
    ok("F9 2.5b latency_ms is float",                isinstance(pr.latency_ms, float))

    if gem is not None:
        class _GR:
            text = "ok"
        pr_gem = gem.call(model="m", system_prompt="s", user_message="u", _request_fn=lambda: _GR())
        ok("F10 2.5b Gemini result has latency_ms", hasattr(pr_gem, "latency_ms"))


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _run() -> int:
    gem = _make_gemini()

    _run_section_a(gem)
    _run_section_b(gem)
    _run_section_c()
    _run_section_d()
    _run_section_e()
    _run_section_f(gem)

    total = _passed + _failed
    print("\n" + "=" * 60)
    print(f"Phase 2.5c: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"            {_failed} FAILED.")
        return 1
    print("            All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
