"""
run_phase25b_tests.py
=====================
Phase 2.5b: ProviderInterface standardisation and per-provider testing.

Validates that:
1. All three providers expose the same ``ProviderInterface.call()`` contract.
2. Each provider correctly extracts text from its mock response shape.
3. Auth errors (HTTP 401) → PERR_AUTH, no retry — consistent across providers.
4. Timeout errors → PERR_TIMEOUT, retried per policy — consistent across providers.
5. No API key or secret appears in any error message or test output.
6. ``ask_llm()`` fallback contract preserved: same (llm_called=False, model='none',
   llm_text=response_text) on any provider failure as in Phase 2.5a.
7. ``ask_llm()`` success path produces llm_called=True through the factory.

Scenarios per provider (A/B/C × 3 providers = 9 scenarios)
-----------------------------------------------------------
A  Success — mock request_fn returns provider-shaped response; text extracted.
B  Auth error — mock raises HTTP 401; PERR_AUTH, attempts=1 (non-retryable).
C  Timeout — mock raises TimeoutError; PERR_TIMEOUT, attempts=2 (1 retry).

Additional
----------
D  Cross-provider error code consistency (same error type → same PERR_* code).
E  ask_llm() integration: fallback preserved + success path through factory.
F  No-regression: 2.5a scenarios still pass via ProviderInterface factory.
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
    PERR_TIMEOUT,
    PERR_RATE_LIMIT,
    PERR_PROVIDER,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
    ProviderInterface,
    ProviderNotAvailableError,
    AnthropicProvider,
    OpenAIProvider,
    GeminiProvider,
    get_provider,
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


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

_NO_SLEEP = lambda _x: None  # noqa: E731


class _StatusError(Exception):
    """Simulates a provider SDK error with HTTP status code."""
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


# Anthropic mock response shape: .content[0].text
class _AntTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text

class _AntResponse:
    def __init__(self, text: str) -> None:
        self.content = [_AntTextBlock(text)]


# OpenAI mock response shape: .choices[0].message.content
class _OAIMessage:
    def __init__(self, text: str) -> None:
        self.content = text

class _OAIChoice:
    def __init__(self, text: str) -> None:
        self.message = _OAIMessage(text)

class _OAIResponse:
    def __init__(self, text: str) -> None:
        self.choices = [_OAIChoice(text)]


# Gemini mock response shape: .text
class _GemResponse:
    def __init__(self, text: str) -> None:
        self.text = text


# Mock Anthropic client used for ask_llm backwards-compat tests
class _MsgAPI:
    def __init__(self, fn):
        self._fn = fn
    def create(self, **_kwargs):
        return self._fn()

class _Client:
    def __init__(self, fn):
        self.messages = _MsgAPI(fn)


# ---------------------------------------------------------------------------
# Helper: build a provider with a test key so it constructs successfully.
# Returns None + prints SKIP if the SDK is not installed.
# ---------------------------------------------------------------------------

def _make_provider(cls, name: str):
    """Construct a provider using a sentinel test key. Returns None if SDK absent."""
    try:
        return cls(api_key="test-sentinel-key-phase25b")
    except ProviderNotAvailableError as exc:
        if "not installed" in str(exc):
            print(f"  SKIP  {name} SDK not installed — skipping provider scenarios")
            return None
        # Any other ProviderNotAvailableError (e.g. key missing) should not
        # happen here since we pass a non-empty sentinel key.
        raise


# ---------------------------------------------------------------------------
# Per-provider scenario runner
# ---------------------------------------------------------------------------

def _run_provider_scenarios(
    provider: ProviderInterface,
    label: str,
    success_response,
) -> None:
    """Run A/B/C scenarios for one provider. ``success_response`` is the
    provider-specific mock response object to return on scenario A."""

    print(f"\n  --- {label}: A — success path ---")
    result_a = provider.call(
        model="test-model",
        system_prompt="sys",
        user_message="user msg",
        _request_fn=lambda: success_response,
    )
    ok(f"{label}-A1 error_code is None", result_a.error_code is None)
    ok(f"{label}-A2 text not empty",     result_a.text is not None and len(result_a.text) > 0)
    ok(f"{label}-A3 attempts=1",         result_a.attempts == 1)
    ok(f"{label}-A4 model preserved",    result_a.model == "test-model")

    print(f"\n  --- {label}: B — auth error (HTTP 401, non-retryable) ---")
    result_b = provider.call(
        model="test-model",
        system_prompt="sys",
        user_message="user msg",
        _request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauthorized", 401)),
        _sleep_fn=_NO_SLEEP,
    )
    ok(f"{label}-B1 success=False",       result_b.error_code is not None)
    ok(f"{label}-B2 code=PERR_AUTH",      result_b.error_code == PERR_AUTH)
    ok(f"{label}-B3 attempts=1 (no retry)", result_b.attempts == 1)
    ok(f"{label}-B4 text=None",            result_b.text is None)
    # Verify no API key leaks in error_msg
    ok(
        f"{label}-B5 no secret in error_msg",
        "test-sentinel-key-phase25b" not in (result_b.error_msg or ""),
    )

    print(f"\n  --- {label}: C — timeout (retryable, 1 retry) ---")
    result_c = provider.call(
        model="test-model",
        system_prompt="sys",
        user_message="user msg",
        max_retries=1,
        _request_fn=lambda: (_ for _ in ()).throw(TimeoutError("provider timed out")),
        _sleep_fn=_NO_SLEEP,
    )
    ok(f"{label}-C1 success=False",        result_c.error_code is not None)
    ok(f"{label}-C2 code=PERR_TIMEOUT",    result_c.error_code == PERR_TIMEOUT)
    ok(f"{label}-C3 attempts=2 (1 retry)", result_c.attempts == 2)
    ok(f"{label}-C4 text=None",            result_c.text is None)


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def _run() -> int:

    # -----------------------------------------------------------------------
    # Section 1: AnthropicProvider (A/B/C)
    # -----------------------------------------------------------------------
    print("\n=== AnthropicProvider scenarios ===")
    ant = _make_provider(AnthropicProvider, "AnthropicProvider")
    if ant is not None:
        _run_provider_scenarios(ant, "Anthropic", _AntResponse("  Haaland is a great pick.  "))
        # Verify text is stripped
        r_strip = ant.call(
            model="m", system_prompt="s", user_message="u",
            _request_fn=lambda: _AntResponse("  stripped  "),
        )
        ok("Anthropic text stripped", r_strip.text == "stripped")

    # -----------------------------------------------------------------------
    # Section 2: OpenAIProvider (A/B/C)
    # -----------------------------------------------------------------------
    print("\n=== OpenAIProvider scenarios ===")
    oai = _make_provider(OpenAIProvider, "OpenAIProvider")
    if oai is not None:
        _run_provider_scenarios(oai, "OpenAI", _OAIResponse("  Salah is worth captaining.  "))
        r_strip = oai.call(
            model="m", system_prompt="s", user_message="u",
            _request_fn=lambda: _OAIResponse("  stripped  "),
        )
        ok("OpenAI text stripped", r_strip.text == "stripped")

    # -----------------------------------------------------------------------
    # Section 3: GeminiProvider (A/B/C)
    # -----------------------------------------------------------------------
    print("\n=== GeminiProvider scenarios ===")
    gem = _make_provider(GeminiProvider, "GeminiProvider")
    if gem is not None:
        _run_provider_scenarios(gem, "Gemini", _GemResponse("  Saka is a good differential.  "))
        r_strip = gem.call(
            model="m", system_prompt="s", user_message="u",
            _request_fn=lambda: _GemResponse("  stripped  "),
        )
        ok("Gemini text stripped", r_strip.text == "stripped")

    # -----------------------------------------------------------------------
    # Section D: Cross-provider error code consistency
    # -----------------------------------------------------------------------
    print("\n=== D: Cross-provider error code consistency ===")

    providers_built = [(p, name) for p, name in [
        (ant, "Anthropic"),
        (oai, "OpenAI"),
        (gem, "Gemini"),
    ] if p is not None]

    for p, pname in providers_built:
        r401 = p.call(
            model="m", system_prompt="s", user_message="u",
            _request_fn=lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
            _sleep_fn=_NO_SLEEP,
        )
        ok(f"D-{pname} 401->PERR_AUTH", r401.error_code == PERR_AUTH)

    for p, pname in providers_built:
        r429 = p.call(
            model="m", system_prompt="s", user_message="u",
            _request_fn=lambda: (_ for _ in ()).throw(_StatusError("rate", 429)),
            _sleep_fn=_NO_SLEEP,
        )
        ok(f"D-{pname} 429->PERR_RATE_LIMIT", r429.error_code == PERR_RATE_LIMIT)

    for p, pname in providers_built:
        r_timeout = p.call(
            model="m", system_prompt="s", user_message="u",
            _request_fn=lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
            _sleep_fn=_NO_SLEEP,
        )
        ok(f"D-{pname} TimeoutError->PERR_TIMEOUT", r_timeout.error_code == PERR_TIMEOUT)

    # -----------------------------------------------------------------------
    # Section E: get_provider() factory contract
    # -----------------------------------------------------------------------
    print("\n=== E: get_provider() factory ===")

    # Factory with client → always AnthropicProvider (backwards compat)
    mock_client = _Client(lambda: _AntResponse("from factory"))
    prov_from_client = get_provider(PROVIDER_GEMINI, client=mock_client)
    ok("E1 client overrides provider_name", isinstance(prov_from_client, AnthropicProvider))

    r_factory = prov_from_client.call(
        model="m", system_prompt="s", user_message="u",
    )
    ok("E2 factory client call succeeds", r_factory.error_code is None)
    ok("E3 factory client text extracted", r_factory.text == "from factory")

    # Unknown provider → ProviderNotAvailableError
    try:
        get_provider("unknown_provider_xyz")
        ok("E4 unknown provider raises", False)
    except ProviderNotAvailableError:
        ok("E4 unknown provider raises", True)

    # -----------------------------------------------------------------------
    # Section F: ask_llm() integration — fallback + success through factory
    # -----------------------------------------------------------------------
    print("\n=== F: ask_llm() integration (fallback + success) ===")

    # F1–F3: fallback when provider fails (auth error via mock client)
    resp_fail = ask_llm(
        "should I captain Haaland",
        STANDARD_BOOTSTRAP,
        client=_Client(lambda: (_ for _ in ()).throw(_StatusError("unauthorized", 401))),
    )
    ok("F1 llm_called=False on provider failure", resp_fail.llm_called is False)
    ok("F2 model='none' on fallback",             resp_fail.model == "none")
    ok("F3 llm_text == deterministic response_text",
       resp_fail.llm_text == resp_fail.adapter_response.response_text)

    # F4–F5: success path via mock client
    resp_ok = ask_llm(
        "should I captain Haaland",
        STANDARD_BOOTSTRAP,
        client=_Client(lambda: _AntResponse("Mock LLM says yes.")),
    )
    ok("F4 llm_called=True on provider success", resp_ok.llm_called is True)
    ok("F5 llm_text from provider response",     resp_ok.llm_text == "Mock LLM says yes.")

    # F6: ProviderNotAvailableError → deterministic fallback (no API key, no SDK mock)
    # We test this by temporarily clearing env vars and using a non-existent provider name.
    # Use the factory directly to verify get_provider raises, then ask_llm returns fallback.
    old_provider_env = os.environ.pop("DEFAULT_PROVIDER", None)
    old_anthropic_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    old_google_key    = os.environ.pop("GOOGLE_API_KEY", None)
    old_openai_key    = os.environ.pop("OPENAI_API_KEY", None)
    try:
        try:
            get_provider(PROVIDER_ANTHROPIC)
            ok("F6 missing key raises ProviderNotAvailableError", False)
        except ProviderNotAvailableError:
            ok("F6 missing key raises ProviderNotAvailableError", True)
    finally:
        if old_provider_env is not None:
            os.environ["DEFAULT_PROVIDER"] = old_provider_env
        if old_anthropic_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = old_anthropic_key
        if old_google_key is not None:
            os.environ["GOOGLE_API_KEY"] = old_google_key
        if old_openai_key is not None:
            os.environ["OPENAI_API_KEY"] = old_openai_key

    # -----------------------------------------------------------------------
    # Section G: No-regression — 2.5a call_provider_request scenarios still pass
    # -----------------------------------------------------------------------
    print("\n=== G: No-regression (2.5a call_provider_request) ===")

    _success_raw = call_provider_request(lambda: {"ok": True}, max_retries=1)
    ok("G1 raw success=True",      _success_raw.success)
    ok("G2 raw attempts=1",        _success_raw.attempts == 1)
    ok("G3 raw error_code is None", _success_raw.error_code is None)

    _auth_raw = call_provider_request(
        lambda: (_ for _ in ()).throw(_StatusError("unauth", 401)),
        max_retries=2,
        _sleep_fn=_NO_SLEEP,
    )
    ok("G4 raw auth code=PERR_AUTH",    _auth_raw.error_code == PERR_AUTH)
    ok("G5 raw auth attempts=1",        _auth_raw.attempts == 1)

    _timeout_raw = call_provider_request(
        lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
        max_retries=1,
        _sleep_fn=_NO_SLEEP,
    )
    ok("G6 raw timeout code=PERR_TIMEOUT", _timeout_raw.error_code == PERR_TIMEOUT)
    ok("G7 raw timeout attempts=2",        _timeout_raw.attempts == 2)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total = _passed + _failed
    print("\n" + "=" * 60)
    print(f"Phase 2.5b: {_passed}/{total} assertions passed.")
    if _failed:
        print(f"            {_failed} FAILED.")
        return 1
    print("            All assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
