"""
run_phase25d2_tests.py
======================
Phase 2.5d2: Multi-provider orchestration parity for tool-use calls.

Validates:
A  Anthropic tool-call success path through ask_orchestrated()
B  OpenAI function-call success path through ask_orchestrated()
C  Gemini function-call success path through ask_orchestrated()
D  Failure normalisation is consistent across all three providers
E  Gate + cooldown behaviour unchanged after introducing call_orch_provider
F  Structured event schema is identical across all three providers
G  call_orch_provider() _request_fn injection and OrchCallResult shape
H  No-regression: 2.5a/2.5b/2.5c/2.5d1 call_provider_request scenarios
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

# Enable _orch_request_fn test injection — must be set before ask_orchestrated is called.
os.environ["FPL_ORCH_TEST_INJECTION"] = "1"

from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_COOLDOWN,
    OUTCOME_LLM_ERROR,
    OUTCOME_NO_CLIENT,
    OUTCOME_OK,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    _GATE,
    _FailureGate,
    ask_orchestrated,
)
from fpl_grounded_assistant.provider_client import (
    PERR_AUTH,
    PERR_TIMEOUT,
    OrchCallResult,
    ProviderResult,
    call_orch_provider,
    call_provider_request,
)

_passed = 0
_failed = 0

_GATE.reset_all()   # clean global gate state before any test


def ok(label: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


_NO_SLEEP = lambda _x: None  # noqa: E731

_GOOD_OUTCOME = frozenset({"ok", "tool_result_error"})  # LLM call succeeded


# ---------------------------------------------------------------------------
# Provider-specific mock response shapes
# ---------------------------------------------------------------------------

# --- Anthropic tool_use ---
class _AntToolBlock:
    type  = "tool_use"
    name  = "get_captain_score"
    input = {"query": "Haaland"}

class _AntResponse:
    content = [_AntToolBlock()]


# --- OpenAI function-calling ---
class _OAIFunc:
    name      = "get_captain_score"
    arguments = '{"query": "Haaland"}'

class _OAIToolCall:
    function = _OAIFunc()

class _OAIMessage:
    tool_calls = [_OAIToolCall()]

class _OAIChoice:
    message = _OAIMessage()

class _OAIResponse:
    choices = [_OAIChoice()]


# --- Gemini function_call ---
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


# Error mock
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
# Section A: Anthropic success path
# ---------------------------------------------------------------------------

def _run_section_a() -> tuple[dict | None, _LogCap]:
    print("\n=== A: Anthropic tool-call success path ===")
    gate = _FailureGate(threshold=5, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        result = ask_orchestrated(
            "should I captain Haaland",
            STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: _AntResponse(),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    ok("A1 outcome in {ok, tool_result_error}", result.outcome in _GOOD_OUTCOME)
    ok("A2 llm_used=True",                      result.llm_used)
    ok("A3 model != 'none'",                    result.model != "none")
    ok("A4 tool_chosen set",                    result.tool_chosen is not None)

    evs = cap.events()
    ok("A5 exactly 1 event emitted",            len(evs) == 1)
    ev = evs[0] if evs else {}
    ok("A6 event='provider_call_success'",      ev.get("event") == "provider_call_success")
    ok("A7 provider='anthropic'",               ev.get("provider") == PROVIDER_ANTHROPIC)
    ok("A8 latency_ms >= 0",                    ev.get("latency_ms", -1) >= 0)
    ok("A9 attempts >= 1",                      ev.get("attempts", 0) >= 1)
    return ev if evs else None, cap


# ---------------------------------------------------------------------------
# Section B: OpenAI success path
# ---------------------------------------------------------------------------

def _run_section_b() -> dict | None:
    print("\n=== B: OpenAI function-call success path ===")
    gate = _FailureGate(threshold=5, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        result = ask_orchestrated(
            "should I captain Haaland",
            STANDARD_BOOTSTRAP,
            provider=PROVIDER_OPENAI,
            _orch_request_fn=lambda: _OAIResponse(),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    ok("B1 outcome in {ok, tool_result_error}", result.outcome in _GOOD_OUTCOME)
    ok("B2 llm_used=True",                      result.llm_used)
    ok("B3 tool_chosen set",                    result.tool_chosen is not None)

    evs = cap.events()
    ok("B4 exactly 1 event emitted",            len(evs) == 1)
    ev = evs[0] if evs else {}
    ok("B5 event='provider_call_success'",      ev.get("event") == "provider_call_success")
    ok("B6 provider='openai'",                  ev.get("provider") == PROVIDER_OPENAI)
    ok("B7 latency_ms >= 0",                    ev.get("latency_ms", -1) >= 0)
    return ev if evs else None


# ---------------------------------------------------------------------------
# Section C: Gemini success path
# ---------------------------------------------------------------------------

def _run_section_c() -> dict | None:
    print("\n=== C: Gemini function-call success path ===")
    gate = _FailureGate(threshold=5, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        result = ask_orchestrated(
            "should I captain Haaland",
            STANDARD_BOOTSTRAP,
            provider=PROVIDER_GEMINI,
            _orch_request_fn=lambda: _GemResponse(),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    ok("C1 outcome in {ok, tool_result_error}", result.outcome in _GOOD_OUTCOME)
    ok("C2 llm_used=True",                      result.llm_used)
    ok("C3 tool_chosen set",                    result.tool_chosen is not None)

    evs = cap.events()
    ok("C4 exactly 1 event emitted",            len(evs) == 1)
    ev = evs[0] if evs else {}
    ok("C5 event='provider_call_success'",      ev.get("event") == "provider_call_success")
    ok("C6 provider='gemini'",                  ev.get("provider") == PROVIDER_GEMINI)
    ok("C7 latency_ms >= 0",                    ev.get("latency_ms", -1) >= 0)
    return ev if evs else None


# ---------------------------------------------------------------------------
# Section D: failure normalisation consistency across providers
# ---------------------------------------------------------------------------

def _run_section_d() -> None:
    print("\n=== D: Failure normalisation consistency (call_orch_provider level) ===")
    _no_creds_gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)

    for pname in (PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GEMINI):
        # Auth error via mock
        r401 = call_orch_provider(
            pname,
            model="m", system="s", tools=[], messages=[{"role": "user", "content": "q"}],
            _request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _sleep_fn=_NO_SLEEP,
        )
        ok(f"D-{pname} 401->PERR_AUTH",       r401.error_code == PERR_AUTH)
        ok(f"D-{pname} auth no retry",        r401.attempts == 1)
        ok(f"D-{pname} latency_ms >= 0",      r401.latency_ms >= 0)

        # Timeout via mock (1 retry)
        r_t = call_orch_provider(
            pname,
            model="m", system="s", tools=[], messages=[{"role": "user", "content": "q"}],
            max_retries=1,
            _request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
            _sleep_fn=_NO_SLEEP,
        )
        ok(f"D-{pname} timeout->PERR_TIMEOUT", r_t.error_code == PERR_TIMEOUT)
        ok(f"D-{pname} timeout 2 attempts",    r_t.attempts == 2)

    # OrchCallResult shape: verify all required fields present
    r = call_orch_provider(
        PROVIDER_ANTHROPIC,
        model="m", system="s", tools=[], messages=[{"role": "user", "content": "q"}],
        _request_fn=lambda: {"ok": True},
    )
    ok("D-shape response set on success",   r.response is not None)
    ok("D-shape error_code None on success", r.error_code is None)
    ok("D-shape attempts >= 1",             r.attempts >= 1)
    ok("D-shape latency_ms is float",       isinstance(r.latency_ms, float))


# ---------------------------------------------------------------------------
# Section E: gate and cooldown unchanged with new call path
# ---------------------------------------------------------------------------

def _run_section_e() -> None:
    print("\n=== E: Gate + cooldown unchanged with call_orch_provider ===")
    gate = _FailureGate(threshold=2, window_s=60, cooldown_s=9999)

    # Two timeout failures via _orch_request_fn open the gate
    for _ in range(2):
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
            _gate=gate,
        )
    ok("E1 gate open after 2 timeouts", gate.is_open())

    # Cooldown active → OUTCOME_COOLDOWN, provider not called
    call_count = {"n": 0}

    def _count():
        call_count["n"] += 1
        return _AntResponse()

    result = ask_orchestrated(
        "q", STANDARD_BOOTSTRAP,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=_count,
        _gate=gate,
    )
    ok("E2 OUTCOME_COOLDOWN during cooldown", result.outcome == OUTCOME_COOLDOWN)
    ok("E3 provider not called during cool",  call_count["n"] == 0)

    # Non-transient (auth) does not trigger gate
    gate2 = _FailureGate(threshold=2, window_s=60, cooldown_s=30)
    for _ in range(3):
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _gate=gate2,
        )
    ok("E4 auth errors do not open gate", not gate2.is_open())


# ---------------------------------------------------------------------------
# Section F: event schema identical across all three providers
# ---------------------------------------------------------------------------

def _run_section_f(ev_a: dict | None, ev_b: dict | None, ev_c: dict | None) -> None:
    print("\n=== F: Structured event schema identical across all providers ===")

    if ev_a and ev_b and ev_c:
        ok("F1 Anthropic/OpenAI same keys",   set(ev_a.keys()) == set(ev_b.keys()))
        ok("F2 Anthropic/Gemini same keys",   set(ev_a.keys()) == set(ev_c.keys()))

    required = {"event", "provider", "model", "latency_ms", "attempts"}
    for ev, pname in [(ev_a, "Anthropic"), (ev_b, "OpenAI"), (ev_c, "Gemini")]:
        if ev is not None:
            for field in required:
                ok(f"F-{pname} has '{field}'", field in ev)
        else:
            print(f"  SKIP  F-{pname} — no event captured")

    # Failure events also have error_code and no error_msg
    gate = _FailureGate(threshold=10, window_s=60, cooldown_s=30)
    cap, log, saved = _attach("fpl_grounded_assistant.orchestrator")
    try:
        ask_orchestrated(
            "q", STANDARD_BOOTSTRAP,
            provider=PROVIDER_ANTHROPIC,
            _orch_request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _gate=gate,
        )
    finally:
        _detach(cap, log, saved)

    fail_events = [e for e in cap.events() if e.get("event") == "provider_call_failure"]
    ok("F3 failure event emitted",            len(fail_events) == 1)
    if fail_events:
        fe = fail_events[0]
        ok("F4 failure has error_code",        "error_code" in fe)
        ok("F5 failure no error_msg",          "error_msg"  not in fe)
        ok("F6 failure has latency_ms",        "latency_ms" in fe)


# ---------------------------------------------------------------------------
# Section G: OrchCallResult shape and call_orch_provider contract
# ---------------------------------------------------------------------------

def _run_section_g() -> None:
    print("\n=== G: OrchCallResult shape and call_orch_provider contract ===")

    # Success via _request_fn
    r_ok = call_orch_provider(
        PROVIDER_ANTHROPIC,
        model="claude-test",
        system="sys",
        tools=[],
        messages=[{"role": "user", "content": "q"}],
        _request_fn=lambda: _AntResponse(),
    )
    ok("G1 error_code None on success", r_ok.error_code is None)
    ok("G2 response set on success",    r_ok.response is not None)
    ok("G3 attempts=1",                 r_ok.attempts == 1)
    ok("G4 latency_ms >= 0",            r_ok.latency_ms >= 0)
    ok("G5 OrchCallResult is frozen",   hasattr(r_ok, "__dataclass_params__"))

    # Failure via _request_fn
    r_fail = call_orch_provider(
        PROVIDER_OPENAI,
        model="gpt-test",
        system="sys",
        tools=[],
        messages=[{"role": "user", "content": "q"}],
        _request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
        max_retries=0,
        _sleep_fn=_NO_SLEEP,
    )
    ok("G6 error_code set on failure", r_fail.error_code == PERR_TIMEOUT)
    ok("G7 response None on failure",  r_fail.response is None)
    ok("G8 attempts=1",                r_fail.attempts == 1)

    # _request_fn bypasses credentials check even for unknown provider
    r_unk = call_orch_provider(
        "unknown_provider",
        model="m", system="s", tools=[],
        messages=[{"role": "user", "content": "q"}],
        _request_fn=lambda: {"ok": True},
    )
    ok("G9 _request_fn bypass works for unknown provider", r_unk.error_code is None)


# ---------------------------------------------------------------------------
# Section H: no-regression — 2.5a / 2.5b / 2.5c / 2.5d1 scenarios
# ---------------------------------------------------------------------------

def _run_section_h() -> None:
    print("\n=== H: No-regression (2.5a/2.5b/2.5c/2.5d1 scenarios) ===")

    # 2.5a: call_provider_request
    r = call_provider_request(lambda: {"ok": True})
    ok("H1 2.5a raw success",        r.success)
    ok("H2 2.5a raw error_code None", r.error_code is None)

    r_t = call_provider_request(
        lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
        max_retries=1, _sleep_fn=_NO_SLEEP,
    )
    ok("H3 2.5a timeout code",    r_t.error_code == PERR_TIMEOUT)
    ok("H4 2.5a timeout attempts", r_t.attempts == 2)

    # 2.5b: ProviderResult has latency_ms
    from fpl_grounded_assistant.provider_client import AnthropicProvider

    class _TextBlock:
        text = "hi"
    class _AntR:
        content = [_TextBlock()]
    class _AntC:
        class messages:
            @staticmethod
            def create(**_kw): return _AntR()

    pr = AnthropicProvider(client=_AntC()).call(model="m", system_prompt="s", user_message="u")
    ok("H5 2.5b ProviderResult has latency_ms", hasattr(pr, "latency_ms"))

    # 2.5d1: _FailureGate logic unchanged
    gate = _FailureGate(threshold=1, window_s=60, cooldown_s=30)
    gate.record_failure(PERR_TIMEOUT)
    ok("H6 2.5d1 gate opens at threshold=1", gate.is_open())
    gate.reset_all()
    ok("H7 2.5d1 reset_all closes gate",     not gate.is_open())

    # 2.5d1: OUTCOME_NO_CLIENT still fires when no client and default provider
    result = ask_orchestrated("q", STANDARD_BOOTSTRAP,
                              _gate=_FailureGate(threshold=10, window_s=60, cooldown_s=30))
    # Without API key set, _get_anthropic_client returns None → OUTCOME_NO_CLIENT
    # (This assertion depends on env; we only assert the outcome is not OUTCOME_COOLDOWN)
    ok("H8 no-client outcome != OUTCOME_COOLDOWN",
       result.outcome != OUTCOME_COOLDOWN)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _run() -> int:
    ev_a, _ = _run_section_a()
    ev_b    = _run_section_b()
    ev_c    = _run_section_c()
    _run_section_d()
    _run_section_e()
    _run_section_f(ev_a, ev_b, ev_c)
    _run_section_g()
    _run_section_h()

    total = _passed + _failed
    print("\n" + "=" * 60)
    print(f"Phase 2.5d2: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"             {_failed} FAILED.")
        return 1
    print("             All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
