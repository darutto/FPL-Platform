"""
run_phase_2_5a_tests.py
========================
Phase 2.5a validation: Real provider client with timeout, bounded retries, and
error normalisation wired into the orchestration path.

All LLM calls are intercepted by mock clients — no real network calls are made,
no API keys are required.

Five scenarios validated:
  S1  Successful provider call (mock returns valid Anthropic tool-use response)
  S2  Timeout (mock raises a timeout-like exception; retry exhausted)
  S3  Rate-limit (mock raises HTTP-429-like exception; retried once, still fails)
  S4  Auth error (mock raises HTTP-401-like exception; NOT retried)
  S5  Deterministic fallback: respond() with orch enabled but no client available
      preserves FinalResponse contract invariants (all stable fields, valid outcome).
"""
from __future__ import annotations

import os
import sys

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

# ---------------------------------------------------------------------------
# Assertion helpers (same style as gate runners)
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def ok(cond: bool, label: str, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"  [{detail}]"
        print(msg)


# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------

class _MockMessages:
    """Simulates client.messages (the Anthropic SDK sub-resource)."""

    def __init__(
        self,
        raises: Exception | None = None,
        response: object = None,
        fail_count: int = 0,
    ) -> None:
        """
        Parameters
        ----------
        raises:
            Exception to raise on every call (when fail_count == 0).
        response:
            Object to return when the call succeeds.
        fail_count:
            Number of calls that raise before returning ``response``.
            0 means always raise (when raises is set).
        """
        self._raises    = raises
        self._response  = response
        self._fail_count = fail_count
        self.call_count = 0

    def create(self, **kwargs: object) -> object:
        self.call_count += 1
        if self._raises and (self._fail_count == 0 or self.call_count <= self._fail_count):
            raise self._raises
        return self._response


class _MockClient:
    def __init__(
        self,
        raises: Exception | None = None,
        response: object = None,
        fail_count: int = 0,
    ) -> None:
        self.messages = _MockMessages(
            raises=raises,
            response=response,
            fail_count=fail_count,
        )


# ---------------------------------------------------------------------------
# Mock exception classes (mimic provider SDK shapes via status_code attribute)
# ---------------------------------------------------------------------------

class _MockTimeoutError(Exception):
    """Simulates anthropic.APITimeoutError (classified by name heuristic)."""


class _MockRateLimitError(Exception):
    """Simulates anthropic.RateLimitError (classified by status_code)."""
    status_code = 429


class _MockAuthError(Exception):
    """Simulates anthropic.AuthenticationError (classified by status_code)."""
    status_code = 401


class _MockProviderError(Exception):
    """Simulates a generic API-level error."""
    status_code = 500


# ---------------------------------------------------------------------------
# Mock LLM response (Anthropic tool-use shape)
# ---------------------------------------------------------------------------

class _MockToolUseBlock:
    type  = "tool_use"
    name  = "get_captain_score"
    input = {"player_name": "Salah"}


class _MockAnthropicResponse:
    content = [_MockToolUseBlock()]


# ---------------------------------------------------------------------------
# Import modules under test
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.provider_client import (  # noqa: E402
    PERR_AUTH,
    PERR_NETWORK,
    PERR_PROVIDER,
    PERR_RATE_LIMIT,
    PERR_TIMEOUT,
    ProviderCallResult,
    call_provider,
)
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_LLM_ERROR,
    OUTCOME_NO_CLIENT,
    OUTCOME_OK,
    ask_orchestrated,
)
from fpl_grounded_assistant.orch_config import (  # noqa: E402
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_S,
    get_orch_max_retries,
    get_orch_timeout,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.final_response import FinalResponse, respond      # noqa: E402
from fpl_grounded_assistant.orch_config import ORCH_ENABLED_ENV               # noqa: E402

_no_sleep = lambda _: None   # noqa: E731  — zero-delay for retry tests


# ===========================================================================
# S1 — Successful provider call
# ===========================================================================

print("\n--- S1: Successful provider call (mock transport) ---")

_s1_client   = _MockClient(response=_MockAnthropicResponse())
_s1_result   = call_provider(
    _s1_client,
    model="claude-test",
    system="system",
    tools=[],
    messages=[{"role": "user", "content": "test"}],
    timeout_s=5.0,
    max_retries=1,
    _sleep_fn=_no_sleep,
)

ok(_s1_result.success,              "S1 call_provider: success=True on valid mock response")
ok(_s1_result.error_code is None,   "S1 call_provider: error_code is None on success")
ok(_s1_result.response is not None, "S1 call_provider: response object returned")
ok(_s1_result.attempts == 1,        "S1 call_provider: exactly 1 attempt on success",
   detail=f"attempts={_s1_result.attempts}")
ok(_s1_client.messages.call_count == 1,
   "S1 call_provider: messages.create() called exactly once")


# ===========================================================================
# S2 — Timeout
# ===========================================================================

print("\n--- S2: Timeout (mock raises timeout, retry exhausted) ---")

_s2_client = _MockClient(raises=_MockTimeoutError("Request timed out"))
_s2_result = call_provider(
    _s2_client,
    model="claude-test",
    system="system",
    tools=[],
    messages=[{"role": "user", "content": "test"}],
    timeout_s=5.0,
    max_retries=1,
    _sleep_fn=_no_sleep,
)

ok(not _s2_result.success,                "S2 call_provider: success=False on timeout")
ok(_s2_result.error_code == PERR_TIMEOUT,  "S2 call_provider: error_code=timeout",
   detail=f"got {_s2_result.error_code!r}")
ok(_s2_result.error_msg is not None,       "S2 call_provider: error_msg is non-empty")
ok(_s2_result.attempts == 2,               "S2 call_provider: 2 attempts made (1 retry)",
   detail=f"attempts={_s2_result.attempts}")
ok(_s2_client.messages.call_count == 2,
   "S2 call_provider: messages.create() called twice (initial + 1 retry)")

# ask_orchestrated must never raise, must return OUTCOME_LLM_ERROR
_s2_orch_client = _MockClient(raises=_MockTimeoutError("Request timed out"))
try:
    _s2_orch = ask_orchestrated(
        "should I captain Salah",
        STANDARD_BOOTSTRAP,
        client=_s2_orch_client,
        model="claude-test",
    )
    _s2_raised = False
except Exception:
    _s2_raised = True

ok(not _s2_raised,                              "S2 ask_orchestrated: never raises on timeout")
ok(_s2_orch.outcome == OUTCOME_LLM_ERROR,        "S2 ask_orchestrated: outcome=llm_error",
   detail=f"got {_s2_orch.outcome!r}")
ok(_s2_orch.error is not None,                   "S2 ask_orchestrated: error field set")
ok(PERR_TIMEOUT in (_s2_orch.error or ""),        "S2 ask_orchestrated: error contains 'timeout' code")


# ===========================================================================
# S3 — Rate-limit (HTTP 429)
# ===========================================================================

print("\n--- S3: Rate-limit (mock raises HTTP 429, retried once) ---")

_s3_client = _MockClient(raises=_MockRateLimitError("Rate limit exceeded"))
_s3_result = call_provider(
    _s3_client,
    model="claude-test",
    system="system",
    tools=[],
    messages=[{"role": "user", "content": "test"}],
    timeout_s=5.0,
    max_retries=1,
    _sleep_fn=_no_sleep,
)

ok(not _s3_result.success,                    "S3 call_provider: success=False on rate-limit")
ok(_s3_result.error_code == PERR_RATE_LIMIT,   "S3 call_provider: error_code=rate_limit",
   detail=f"got {_s3_result.error_code!r}")
ok(_s3_result.attempts == 2,                   "S3 call_provider: 2 attempts made (1 retry)",
   detail=f"attempts={_s3_result.attempts}")
ok(_s3_client.messages.call_count == 2,
   "S3 call_provider: messages.create() called twice (initial + 1 retry)")

# ask_orchestrated: never raises, outcome=llm_error
_s3_orch_client = _MockClient(raises=_MockRateLimitError("Rate limit exceeded"))
try:
    _s3_orch = ask_orchestrated(
        "should I captain Salah",
        STANDARD_BOOTSTRAP,
        client=_s3_orch_client,
        model="claude-test",
    )
    _s3_raised = False
except Exception:
    _s3_raised = True

ok(not _s3_raised,                               "S3 ask_orchestrated: never raises on rate-limit")
ok(_s3_orch.outcome == OUTCOME_LLM_ERROR,         "S3 ask_orchestrated: outcome=llm_error")
ok(PERR_RATE_LIMIT in (_s3_orch.error or ""),     "S3 ask_orchestrated: error contains 'rate_limit' code")


# ===========================================================================
# S4 — Auth error (HTTP 401) — must NOT retry
# ===========================================================================

print("\n--- S4: Auth error (HTTP 401, no retry) ---")

_s4_client = _MockClient(raises=_MockAuthError("Invalid API key"))
_s4_result = call_provider(
    _s4_client,
    model="claude-test",
    system="system",
    tools=[],
    messages=[{"role": "user", "content": "test"}],
    timeout_s=5.0,
    max_retries=1,             # retry allowed by config but must not fire for auth
    _sleep_fn=_no_sleep,
)

ok(not _s4_result.success,               "S4 call_provider: success=False on auth error")
ok(_s4_result.error_code == PERR_AUTH,    "S4 call_provider: error_code=auth_error",
   detail=f"got {_s4_result.error_code!r}")
ok(_s4_result.attempts == 1,              "S4 call_provider: only 1 attempt (auth NOT retried)",
   detail=f"attempts={_s4_result.attempts}")
ok(_s4_client.messages.call_count == 1,
   "S4 call_provider: messages.create() called exactly once (no retry)")

# ask_orchestrated: never raises, outcome=llm_error
_s4_orch_client = _MockClient(raises=_MockAuthError("Invalid API key"))
try:
    _s4_orch = ask_orchestrated(
        "should I captain Salah",
        STANDARD_BOOTSTRAP,
        client=_s4_orch_client,
        model="claude-test",
    )
    _s4_raised = False
except Exception:
    _s4_raised = True

ok(not _s4_raised,                           "S4 ask_orchestrated: never raises on auth error")
ok(_s4_orch.outcome == OUTCOME_LLM_ERROR,     "S4 ask_orchestrated: outcome=llm_error")
ok(PERR_AUTH in (_s4_orch.error or ""),       "S4 ask_orchestrated: error contains 'auth_error' code")
ok("authentication" in (_s4_orch.answer_text or "").lower(),
   "S4 ask_orchestrated: answer_text mentions authentication failure",
   detail=f"got {_s4_orch.answer_text!r}")


# ===========================================================================
# S5 — Deterministic fallback: FinalResponse contract preserved
# ===========================================================================

print("\n--- S5: Deterministic fallback preserving FinalResponse contract ---")

# S5a: orch disabled ->deterministic path; orch_outcome=None
_env_backup = os.environ.get(ORCH_ENABLED_ENV)
os.environ.pop(ORCH_ENABLED_ENV, None)

try:
    _s5a = respond("¿A quién captaneo esta semana?", STANDARD_BOOTSTRAP)
except Exception as _exc:
    print(f"  FAIL  S5a respond() raised: {_exc}")
    _s5a = None

if _s5a is not None:
    ok(_s5a.orch_outcome is None,
       "S5a (orch OFF): orch_outcome is None (orch not attempted)")
    ok(_s5a.outcome in {"ok", "not_found", "ambiguous", "error", "missing_arguments",
                        "unsupported_intent"},
       "S5a (orch OFF): outcome is a valid vocabulary value",
       detail=f"got {_s5a.outcome!r}")
    ok(isinstance(_s5a.final_text, str) and len(_s5a.final_text) > 0,
       "S5a (orch OFF): final_text is non-empty string")
    ok(isinstance(_s5a.supported, bool),  "S5a (orch OFF): supported is bool")
    ok(isinstance(_s5a.llm_used,  bool),  "S5a (orch OFF): llm_used is bool")
    ok(_s5a.intent != "",                 "S5a (orch OFF): intent is non-empty")
    ok(isinstance(_s5a.review_passed, bool), "S5a (orch OFF): review_passed is bool")

# S5b: orch enabled but no API key in env ->OUTCOME_NO_CLIENT ->deterministic fallback
os.environ["FPL_ORCH_ENABLED"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)    # ensure no key present

try:
    _s5b = respond("should I captain Salah", STANDARD_BOOTSTRAP)
except Exception as _exc:
    print(f"  FAIL  S5b respond() raised: {_exc}")
    _s5b = None

if _s5b is not None:
    ok(
        _s5b.orch_outcome in (None, OUTCOME_NO_CLIENT),
        "S5b (orch ON, no key): orch_outcome is None or no_client (fallback triggered)",
        detail=f"got {_s5b.orch_outcome!r}",
    )
    ok(isinstance(_s5b.final_text, str) and len(_s5b.final_text) > 0,
       "S5b (orch ON, no key): final_text is non-empty (deterministic fallback active)")
    ok(_s5b.outcome in {"ok", "not_found", "ambiguous", "error", "missing_arguments"},
       "S5b (orch ON, no key): outcome is valid vocabulary value",
       detail=f"got {_s5b.outcome!r}")
    ok(isinstance(_s5b.supported, bool),     "S5b (orch ON, no key): supported is bool")
    ok(isinstance(_s5b.llm_used,  bool),     "S5b (orch ON, no key): llm_used is bool")
    ok(isinstance(_s5b.review_passed, bool), "S5b (orch ON, no key): review_passed is bool")
    ok(_s5b.intent != "",                    "S5b (orch ON, no key): intent is non-empty")

# Restore env
if _env_backup is None:
    os.environ.pop(ORCH_ENABLED_ENV, None)
else:
    os.environ[ORCH_ENABLED_ENV] = _env_backup


# ===========================================================================
# S6 — Config: timeout and max-retries read from env
# ===========================================================================

print("\n--- S6: Config env-var reading (get_orch_timeout / get_orch_max_retries) ---")

_backup_to  = os.environ.pop("FPL_ORCH_TIMEOUT_S", None)
_backup_mr  = os.environ.pop("FPL_ORCH_MAX_RETRIES", None)

ok(get_orch_timeout()    == DEFAULT_TIMEOUT_S,   "S6 default timeout correct",
   detail=f"got {get_orch_timeout()}")
ok(get_orch_max_retries() == DEFAULT_MAX_RETRIES, "S6 default max_retries correct",
   detail=f"got {get_orch_max_retries()}")

os.environ["FPL_ORCH_TIMEOUT_S"]   = "30"
os.environ["FPL_ORCH_MAX_RETRIES"] = "2"
ok(get_orch_timeout()    == 30.0, "S6 FPL_ORCH_TIMEOUT_S=30 ->30.0")
ok(get_orch_max_retries() == 2,   "S6 FPL_ORCH_MAX_RETRIES=2 ->2")

os.environ["FPL_ORCH_TIMEOUT_S"]   = "invalid"
os.environ["FPL_ORCH_MAX_RETRIES"] = "bad"
ok(get_orch_timeout()    == DEFAULT_TIMEOUT_S,   "S6 invalid timeout falls back to default")
ok(get_orch_max_retries() == DEFAULT_MAX_RETRIES, "S6 invalid max_retries falls back to default")

os.environ["FPL_ORCH_TIMEOUT_S"]   = "-5"
ok(get_orch_timeout() == DEFAULT_TIMEOUT_S, "S6 negative timeout falls back to default")

os.environ["FPL_ORCH_MAX_RETRIES"] = "99"
ok(get_orch_max_retries() == 3, "S6 max_retries capped at 3 when configured as 99")

if _backup_to  is None: os.environ.pop("FPL_ORCH_TIMEOUT_S",    None)
else:                   os.environ["FPL_ORCH_TIMEOUT_S"]   = _backup_to
if _backup_mr  is None: os.environ.pop("FPL_ORCH_MAX_RETRIES",  None)
else:                   os.environ["FPL_ORCH_MAX_RETRIES"] = _backup_mr


# ===========================================================================
# S7 — max_retries=0 disables all retries
# ===========================================================================

print("\n--- S7: max_retries=0 disables all retries ---")

_s7_client = _MockClient(raises=_MockTimeoutError("timed out"))
_s7_result = call_provider(
    _s7_client,
    model="claude-test",
    system="system",
    tools=[],
    messages=[{"role": "user", "content": "test"}],
    timeout_s=5.0,
    max_retries=0,
    _sleep_fn=_no_sleep,
)

ok(not _s7_result.success,       "S7 no retry: success=False")
ok(_s7_result.attempts == 1,     "S7 no retry: exactly 1 attempt",
   detail=f"attempts={_s7_result.attempts}")
ok(_s7_client.messages.call_count == 1,
   "S7 no retry: messages.create() called exactly once")


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'=' * 60}")
total = _PASS + _FAIL
print(f"Phase 2.5a: {_PASS}/{total} assertions passed.")
if _FAIL:
    print(f"            {_FAIL} FAILED.")
    sys.exit(1)
else:
    print("            All assertions passed.")
    sys.exit(0)
