"""
run_phase25a_tests.py
=====================
Phase 2.5a runtime integration validation.

Validates real-provider call wrapping and safe fallback behavior without
requiring live API keys by using transport mocks.

Scenarios
---------
A  success path (mock provider response)
B  timeout error (retryable) normalised + bounded retry
C  rate-limit error (retryable) normalised + bounded retry
D  auth error (non-retryable) normalised + no retry loop
E  ask_llm fallback preserves deterministic contract text on provider failure
"""

from __future__ import annotations

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

from fpl_grounded_assistant import STANDARD_BOOTSTRAP, ask_llm
from fpl_grounded_assistant.provider_client import (
    PERR_AUTH,
    PERR_RATE_LIMIT,
    PERR_TIMEOUT,
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


class _StatusError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _MessageObj:
    def __init__(self, text: str) -> None:
        self.content = [_TextBlock(text)]


class _MsgAPI:
    def __init__(self, fn):
        self._fn = fn

    def create(self, **_kwargs):
        return self._fn()


class _Client:
    def __init__(self, fn):
        self.messages = _MsgAPI(fn)


def _run() -> int:
    print("\n--- A: success path (mock provider response) ---")
    _success = call_provider_request(lambda: {"ok": True}, max_retries=1)
    ok("A1 success=True", _success.success)
    ok("A2 attempts=1", _success.attempts == 1)
    ok("A3 error_code is None", _success.error_code is None)

    print("\n--- B: timeout error normalisation + retry ---")
    _b_counter = {"n": 0}

    def _timeout_then_fail():
        _b_counter["n"] += 1
        raise TimeoutError("provider timed out")

    _timeout = call_provider_request(_timeout_then_fail, max_retries=1, _sleep_fn=lambda _x: None)
    ok("B1 success=False", not _timeout.success)
    ok("B2 code=timeout", _timeout.error_code == PERR_TIMEOUT)
    ok("B3 attempts=2 (1 retry)", _timeout.attempts == 2)

    print("\n--- C: rate-limit error normalisation + retry ---")
    _c_counter = {"n": 0}

    def _rate_then_fail():
        _c_counter["n"] += 1
        raise _StatusError("too many requests", 429)

    _rate = call_provider_request(_rate_then_fail, max_retries=1, _sleep_fn=lambda _x: None)
    ok("C1 success=False", not _rate.success)
    ok("C2 code=rate_limit", _rate.error_code == PERR_RATE_LIMIT)
    ok("C3 attempts=2 (1 retry)", _rate.attempts == 2)

    print("\n--- D: auth error normalisation + no retry ---")

    def _auth_fail():
        raise _StatusError("unauthorized", 401)

    _auth = call_provider_request(_auth_fail, max_retries=2, _sleep_fn=lambda _x: None)
    ok("D1 success=False", not _auth.success)
    ok("D2 code=auth_error", _auth.error_code == PERR_AUTH)
    ok("D3 attempts=1 (non-retryable)", _auth.attempts == 1)

    print("\n--- E: ask_llm fallback preserves deterministic contract text ---")

    def _boom_provider():
        raise _StatusError("unauthorized", 401)

    _resp = ask_llm(
        "should I captain Haaland",
        STANDARD_BOOTSTRAP,
        client=_Client(_boom_provider),
    )
    ok("E1 llm_called=False on provider failure", _resp.llm_called is False)
    ok("E2 model='none' on fallback", _resp.model == "none")
    ok("E3 llm_text equals deterministic response_text", _resp.llm_text == _resp.adapter_response.response_text)

    print("\n--- E2: ask_llm success path with mock provider ---")
    _resp_ok = ask_llm(
        "should I captain Haaland",
        STANDARD_BOOTSTRAP,
        client=_Client(lambda: _MessageObj("Mock LLM phrasing.")),
    )
    ok("E4 llm_called=True when provider succeeds", _resp_ok.llm_called is True)
    ok("E5 llm_text comes from provider", _resp_ok.llm_text == "Mock LLM phrasing.")

    total = _passed + _failed
    print("\n" + "=" * 50)
    print(f"Phase 2.5a: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"               {_failed} FAILED.")
        return 1
    print("               All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
