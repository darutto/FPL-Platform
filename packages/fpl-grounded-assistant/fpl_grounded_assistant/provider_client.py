"""
fpl_grounded_assistant.provider_client
=========================================
Phase 2.5a: Real provider client with timeout, bounded retries, and error normalisation.

Wraps raw LLM API calls with:

* Configurable call timeout  (``FPL_ORCH_TIMEOUT_S``, default 20 s).
* Bounded retry policy: at most ``max_retries`` additional attempts for
  *transient* errors (rate-limit, timeout, network).  Auth errors and
  general provider errors are NOT retried — they will not self-heal.
* Error normalisation: every provider exception is mapped to one of five
  ``PERR_*`` codes before being returned to the caller.  The original
  exception message is sanitised to avoid leaking secrets.

The public surface is ``call_provider()``.  Nothing in this module touches
``FinalResponse`` fields, ``OUTCOME_*`` constants, or contract semantics.

Error code mapping
------------------
PERR_RATE_LIMIT  HTTP 429 / provider rate-limit exception.
PERR_AUTH        HTTP 401/403 / authentication exception.
PERR_TIMEOUT     Call exceeded the configured timeout.
PERR_NETWORK     Transport / connection failure.
PERR_PROVIDER    Any other API-level error.

Retry policy
------------
Retried:     PERR_RATE_LIMIT (1.0 s delay), PERR_TIMEOUT (0 s), PERR_NETWORK (0 s).
Not retried: PERR_AUTH, PERR_PROVIDER.

Design notes
------------
* ``call_provider`` accepts ``_sleep_fn`` for test injection (avoids real
  wall-clock delays in the test suite without monkey-patching ``time``).
* Error messages are truncated to 200 chars and never contain the API key.
* The function always returns — it never raises.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Internal error codes  (NOT exposed through FinalResponse / OUTCOME_*)
# ---------------------------------------------------------------------------

#: HTTP 429 or provider rate-limit exception.
PERR_RATE_LIMIT: str = "rate_limit"
#: HTTP 401 / 403 or invalid API key.
PERR_AUTH: str = "auth_error"
#: Call exceeded the configured timeout.
PERR_TIMEOUT: str = "timeout"
#: Transport / connection failure.
PERR_NETWORK: str = "network"
#: Any other API-level error.
PERR_PROVIDER: str = "provider"

_ALL_PERR: frozenset[str] = frozenset({
    PERR_RATE_LIMIT, PERR_AUTH, PERR_TIMEOUT, PERR_NETWORK, PERR_PROVIDER,
})

# Errors worth retrying (transient; a second attempt may succeed).
_RETRYABLE: frozenset[str] = frozenset({PERR_RATE_LIMIT, PERR_TIMEOUT, PERR_NETWORK})

# Fixed delay (seconds) before each retry per error code.
_RETRY_DELAYS: dict[str, float] = {
    PERR_RATE_LIMIT: 1.0,
    PERR_TIMEOUT:    0.0,
    PERR_NETWORK:    0.0,
}

# ---------------------------------------------------------------------------
# Optional SDK imports for accurate isinstance classification
# ---------------------------------------------------------------------------

try:
    import anthropic as _anthropic_sdk  # type: ignore[import]
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_sdk = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderCallResult:
    """Structured result from a single ``call_provider()`` invocation.

    Attributes
    ----------
    response:
        Raw LLM response object on success.  ``None`` on failure.
    success:
        ``True`` when the LLM call completed without error.
    error_code:
        One of the ``PERR_*`` constants on failure.  ``None`` on success.
    error_msg:
        Sanitised, secret-free error description for logs.  ``None`` on success.
    attempts:
        Number of HTTP attempts made (1 = no retry; 2 = one retry).
    """

    response:   Any
    success:    bool
    error_code: str | None
    error_msg:  str | None
    attempts:   int


# ---------------------------------------------------------------------------
# Exception classification
# ---------------------------------------------------------------------------

def _classify_error(exc: Exception) -> str:
    """Map a provider exception to a ``PERR_*`` code.

    Checks against known Anthropic SDK exception types first (accurate).
    Falls back to ``status_code`` attribute and exception class-name
    heuristics so that test mocks and future SDKs are handled correctly
    without requiring hard SDK imports.
    """
    # -- Anthropic SDK isinstance checks (most accurate) -------------------
    if _ANTHROPIC_AVAILABLE and _anthropic_sdk is not None:
        if isinstance(exc, _anthropic_sdk.RateLimitError):
            return PERR_RATE_LIMIT
        if isinstance(exc, _anthropic_sdk.AuthenticationError):
            return PERR_AUTH
        # APITimeoutError is the explicit timeout class in the SDK
        if isinstance(exc, getattr(_anthropic_sdk, "APITimeoutError", type(None))):
            return PERR_TIMEOUT
        # APIConnectionError covers DNS/socket failures
        if isinstance(exc, getattr(_anthropic_sdk, "APIConnectionError", type(None))):
            return PERR_NETWORK
        if isinstance(exc, _anthropic_sdk.APIStatusError):
            status = getattr(exc, "status_code", None)
            if status == 429:
                return PERR_RATE_LIMIT
            if status in (401, 403):
                return PERR_AUTH
            return PERR_PROVIDER

    # -- Attribute-based fallback (test mocks; future SDKs) ----------------
    status = getattr(exc, "status_code", None)
    if status == 429:
        return PERR_RATE_LIMIT
    if status in (401, 403):
        return PERR_AUTH

    exc_name = type(exc).__name__.lower()
    if "timeout" in exc_name or "timed out" in str(exc).lower():
        return PERR_TIMEOUT
    if "connection" in exc_name or "network" in exc_name:
        return PERR_NETWORK
    if "ratelimit" in exc_name or "rate_limit" in exc_name:
        return PERR_RATE_LIMIT
    if "authentication" in exc_name or "auth" in exc_name:
        return PERR_AUTH

    return PERR_PROVIDER


def _sanitize_error(exc: Exception) -> str:
    """Return a log-safe description of *exc*.

    Truncates to 200 characters and never includes the API key (the SDK
    does not include it, but we guard defensively).
    """
    exc_type = type(exc).__name__
    status   = getattr(exc, "status_code", None)
    if status:
        return f"{exc_type} (HTTP {status})"
    msg = str(exc)
    for key_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        raw_key = os.environ.get(key_name)
        if raw_key and raw_key in msg:
            msg = msg.replace(raw_key, "[redacted]")
    if len(msg) > 200:
        msg = msg[:200] + "…"
    return f"{exc_type}: {msg}"


def call_provider_request(
    request_fn: Any,
    *,
    max_retries: int = 1,
    _sleep_fn: Any = None,
) -> ProviderCallResult:
    """Call a provider request function with bounded retries and normalised errors.

    Parameters
    ----------
    request_fn:
        Zero-argument callable that performs exactly one provider request and
        returns a raw provider response object.
    max_retries:
        Maximum number of additional attempts after the first. Capped at 3.
    _sleep_fn:
        Optional sleep function for tests.

    Returns
    -------
    ProviderCallResult
        Normalised success/failure envelope.
    """
    _sleep = _sleep_fn if _sleep_fn is not None else time.sleep
    _max_retries = max(0, min(int(max_retries), 3))

    last_error_code: str | None = None
    last_error_msg: str | None = None

    for attempt in range(1, _max_retries + 2):
        try:
            response = request_fn()
            return ProviderCallResult(
                response=response,
                success=True,
                error_code=None,
                error_msg=None,
                attempts=attempt,
            )
        except Exception as exc:  # noqa: BLE001
            error_code = _classify_error(exc)
            error_msg = _sanitize_error(exc)
            last_error_code = error_code
            last_error_msg = error_msg

            should_retry = (
                attempt <= _max_retries
                and error_code in _RETRYABLE
            )
            if should_retry:
                delay = _RETRY_DELAYS.get(error_code, 0.0)
                if delay > 0:
                    _sleep(delay)
                continue
            break

    return ProviderCallResult(
        response=None,
        success=False,
        error_code=last_error_code,
        error_msg=last_error_msg,
        attempts=attempt,  # type: ignore[possibly-undefined]
    )


# ---------------------------------------------------------------------------
# Public call wrapper
# ---------------------------------------------------------------------------

def call_provider(
    client: Any,
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
    timeout_s: float = 20.0,
    max_retries: int = 1,
    _sleep_fn: Any = None,
) -> ProviderCallResult:
    """Call the LLM provider with timeout, bounded retries, and error normalisation.

    Parameters
    ----------
    client:
        SDK client object whose ``.messages.create(**kwargs)`` method is
        called (currently Anthropic-compatible).
    model:
        Model identifier string.
    system:
        System prompt text.
    tools:
        Tool list in the provider's wire format.
    messages:
        Conversation messages list.
    max_tokens:
        Maximum tokens to generate.
    timeout_s:
        Per-call timeout in seconds.  Passed directly to the SDK's
        ``timeout`` parameter.
    max_retries:
        Maximum number of *additional* attempts after the first.  Capped
        internally at 3 regardless of the argument.
    _sleep_fn:
        Callable used for retry delays.  Defaults to ``time.sleep``.
        Inject a no-op in tests to avoid wall-clock waits.

    Returns
    -------
    ProviderCallResult
        Always returns — never raises.
    """
    return call_provider_request(
        lambda: client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
            timeout=timeout_s,
        ),
        max_retries=max_retries,
        _sleep_fn=_sleep_fn,
    )
