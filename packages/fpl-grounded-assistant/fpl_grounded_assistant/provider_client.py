"""
fpl_grounded_assistant.provider_client
=========================================
Phase 2.5b: Unified ProviderInterface — single async-compatible call contract
for all LLM backends (Anthropic, OpenAI, Gemini).

Every provider exposes one method::

    provider.call(
        model, system_prompt, user_message,
        max_tokens, timeout_s, max_retries, _sleep_fn, _request_fn
    ) -> ProviderResult

``_request_fn`` is a zero-argument callable override used exclusively in
tests — when supplied it replaces the real HTTP call so provider logic can be
exercised without real credentials.

``get_provider(provider_name, *, client, api_key)`` is the public factory.
It validates credentials at construction time and raises
``ProviderNotAvailableError`` when the SDK is absent or the API key is missing.
Passing an explicit ``client`` always returns an ``AnthropicProvider`` backed by
that client — this preserves the backwards-compat path used by test mocks and
``orchestrator.py``.

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
* ``call_provider_request`` accepts ``_sleep_fn`` for test injection.
* Error messages are truncated to 200 chars and never contain the API key.
* Every public function always returns — it never raises.
* Backwards-compat surface (``call_provider``, ``call_provider_request``,
  ``ProviderCallResult``) is fully preserved.
"""
from __future__ import annotations

import os
import time
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Provider name constants
# ---------------------------------------------------------------------------

PROVIDER_ANTHROPIC: str = "anthropic"
PROVIDER_OPENAI: str    = "openai"
PROVIDER_GEMINI: str    = "gemini"

_ALL_PROVIDERS: frozenset[str] = frozenset({
    PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GEMINI,
})


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
# Optional SDK imports — each provider handles its own import guard
# ---------------------------------------------------------------------------

try:
    import anthropic as _anthropic_sdk  # type: ignore[import]
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_sdk = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False

try:
    import openai as _openai_sdk  # type: ignore[import]
    _OPENAI_AVAILABLE = True
except ImportError:
    _openai_sdk = None  # type: ignore[assignment]
    _OPENAI_AVAILABLE = False

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as _genai_sdk  # type: ignore[import]
    _GEMINI_AVAILABLE = True
except ImportError:
    _genai_sdk = None  # type: ignore[assignment]
    _GEMINI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderCallResult:
    """Structured result from a single ``call_provider_request()`` invocation.

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


@dataclass(frozen=True)
class ProviderResult:
    """Unified result returned by every ``ProviderInterface.call()`` implementation.

    Contract: (model_name, system_prompt, user_message, max_tokens, timeout_s)
    → (text, model, error_code, error_msg, attempts)

    Attributes
    ----------
    text:
        Extracted LLM response text on success.  ``None`` on failure.
    model:
        The model identifier that was used for the call.
    error_code:
        One of the ``PERR_*`` constants on failure.  ``None`` on success.
    error_msg:
        Sanitised error description for logs (no secrets).  ``None`` on success.
    attempts:
        Total HTTP attempts made across all retries.
    """

    text:       str | None
    model:      str
    error_code: str | None
    error_msg:  str | None
    attempts:   int


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProviderNotAvailableError(Exception):
    """Raised by ``get_provider()`` when the provider cannot be initialised.

    Causes: SDK not installed, API key env var missing, or client construction
    failed.  The message is always safe to log (no secrets).
    """


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
        if isinstance(exc, getattr(_anthropic_sdk, "APITimeoutError", type(None))):
            return PERR_TIMEOUT
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

    Truncates to 200 characters and never includes the API key.
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


# ---------------------------------------------------------------------------
# Core retry/error-normalisation loop (provider-agnostic)
# ---------------------------------------------------------------------------

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
# ProviderInterface ABC
# ---------------------------------------------------------------------------

class ProviderInterface(ABC):
    """Unified call contract for all LLM provider backends.

    Concrete implementations: ``AnthropicProvider``, ``OpenAIProvider``,
    ``GeminiProvider``.

    All providers accept an optional ``_request_fn`` parameter on ``call()``
    for test injection.  When supplied, ``_request_fn`` replaces the real
    HTTP call so error paths and response extraction can be tested without
    live credentials.
    """

    @abstractmethod
    def call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 256,
        timeout_s: float = 20.0,
        max_retries: int = 1,
        _sleep_fn: Any = None,
        _request_fn: Any = None,
    ) -> ProviderResult:
        """Invoke the LLM and return a normalised ``ProviderResult``.

        Parameters
        ----------
        model:          Model identifier string (provider-specific format).
        system_prompt:  System instruction text.
        user_message:   User-turn text to send.
        max_tokens:     Maximum tokens to generate.
        timeout_s:      Per-attempt timeout in seconds.
        max_retries:    Maximum additional attempts for transient errors.
        _sleep_fn:      Injected sleep callable (tests — avoids real waits).
        _request_fn:    Zero-arg callable override that bypasses the real HTTP
                        call.  When supplied, the provider's own client is not
                        used.  The returned object is passed to the provider's
                        text-extraction logic as-is.

        Returns
        -------
        ProviderResult
            Always returns — never raises.  ``error_code`` is ``None`` on
            success; one of the ``PERR_*`` constants on failure.
        """


# ---------------------------------------------------------------------------
# Concrete provider implementations
# ---------------------------------------------------------------------------

class AnthropicProvider(ProviderInterface):
    """Anthropic Messages API provider.

    Validates ``ANTHROPIC_API_KEY`` (or ``api_key``) at construction.
    Passing a pre-built ``client`` skips key validation — this is the
    backwards-compat path for test mocks.

    Text extraction: ``response.content[0].text``
    """

    def __init__(self, client: Any = None, api_key: str | None = None) -> None:
        if client is not None:
            self._client = client
            return
        if not _ANTHROPIC_AVAILABLE:
            raise ProviderNotAvailableError("anthropic SDK not installed")
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderNotAvailableError("ANTHROPIC_API_KEY not set")
        try:
            self._client = _anthropic_sdk.Anthropic(api_key=key)
        except Exception as exc:  # noqa: BLE001
            raise ProviderNotAvailableError(
                f"anthropic client init failed: {type(exc).__name__}"
            ) from None

    def call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 256,
        timeout_s: float = 20.0,
        max_retries: int = 1,
        _sleep_fn: Any = None,
        _request_fn: Any = None,
    ) -> ProviderResult:
        if _request_fn is None:
            _client = self._client

            def _request_fn() -> Any:
                return _client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    timeout=timeout_s,
                )

        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
        if not raw.success:
            return ProviderResult(
                text=None,
                model=model,
                error_code=raw.error_code,
                error_msg=raw.error_msg,
                attempts=raw.attempts,
            )
        try:
            text = raw.response.content[0].text.strip()
        except Exception:  # noqa: BLE001
            return ProviderResult(
                text=None,
                model=model,
                error_code=PERR_PROVIDER,
                error_msg="invalid Anthropic response shape",
                attempts=raw.attempts,
            )
        return ProviderResult(
            text=text,
            model=model,
            error_code=None,
            error_msg=None,
            attempts=raw.attempts,
        )


class OpenAIProvider(ProviderInterface):
    """OpenAI Chat Completions provider.

    Validates ``OPENAI_API_KEY`` (or ``api_key``) at construction.

    Text extraction: ``response.choices[0].message.content``
    """

    def __init__(self, api_key: str | None = None) -> None:
        if not _OPENAI_AVAILABLE:
            raise ProviderNotAvailableError("openai SDK not installed")
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderNotAvailableError("OPENAI_API_KEY not set")
        try:
            self._client = _openai_sdk.OpenAI(api_key=key)
        except Exception as exc:  # noqa: BLE001
            raise ProviderNotAvailableError(
                f"openai client init failed: {type(exc).__name__}"
            ) from None

    def call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 256,
        timeout_s: float = 20.0,
        max_retries: int = 1,
        _sleep_fn: Any = None,
        _request_fn: Any = None,
    ) -> ProviderResult:
        if _request_fn is None:
            _client = self._client

            def _request_fn() -> Any:
                return _client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    timeout=timeout_s,
                )

        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
        if not raw.success:
            return ProviderResult(
                text=None,
                model=model,
                error_code=raw.error_code,
                error_msg=raw.error_msg,
                attempts=raw.attempts,
            )
        try:
            text = raw.response.choices[0].message.content.strip()
        except Exception:  # noqa: BLE001
            return ProviderResult(
                text=None,
                model=model,
                error_code=PERR_PROVIDER,
                error_msg="invalid OpenAI response shape",
                attempts=raw.attempts,
            )
        return ProviderResult(
            text=text,
            model=model,
            error_code=None,
            error_msg=None,
            attempts=raw.attempts,
        )


class GeminiProvider(ProviderInterface):
    """Google GenerativeAI (Gemini) provider.

    Validates ``GOOGLE_API_KEY`` (or ``api_key``) at construction.
    The genai client is configured lazily inside ``call()`` to avoid
    global side-effects on import.

    Text extraction: ``response.text``
    """

    def __init__(self, api_key: str | None = None) -> None:
        if not _GEMINI_AVAILABLE:
            raise ProviderNotAvailableError("google-generativeai SDK not installed")
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderNotAvailableError("GOOGLE_API_KEY not set")
        self._api_key = key

    def call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 256,
        timeout_s: float = 20.0,
        max_retries: int = 1,
        _sleep_fn: Any = None,
        _request_fn: Any = None,
    ) -> ProviderResult:
        if _request_fn is None:
            _genai_sdk.configure(api_key=self._api_key)
            _gemini_model = _genai_sdk.GenerativeModel(
                model_name=model,
                system_instruction=system_prompt,
            )

            def _request_fn() -> Any:
                return _gemini_model.generate_content(
                    user_message,
                    request_options={"timeout": timeout_s},
                )

        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
        if not raw.success:
            return ProviderResult(
                text=None,
                model=model,
                error_code=raw.error_code,
                error_msg=raw.error_msg,
                attempts=raw.attempts,
            )
        try:
            text = raw.response.text.strip()
        except Exception:  # noqa: BLE001
            return ProviderResult(
                text=None,
                model=model,
                error_code=PERR_PROVIDER,
                error_msg="invalid Gemini response shape",
                attempts=raw.attempts,
            )
        return ProviderResult(
            text=text,
            model=model,
            error_code=None,
            error_msg=None,
            attempts=raw.attempts,
        )


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def get_provider(
    provider_name: str,
    *,
    client: Any = None,
    api_key: str | None = None,
) -> ProviderInterface:
    """Return a ``ProviderInterface`` for the given provider.

    Parameters
    ----------
    provider_name:
        One of ``PROVIDER_ANTHROPIC``, ``PROVIDER_OPENAI``, ``PROVIDER_GEMINI``.
        Ignored when ``client`` is supplied.
    client:
        Pre-built provider client (e.g. a mock or real ``anthropic.Anthropic``
        instance).  When supplied, always returns ``AnthropicProvider(client=client)``
        regardless of ``provider_name`` — preserving backwards compat for callers
        that pass an explicit Anthropic client.
    api_key:
        Explicit API key.  When ``None``, each provider reads its own env var.

    Returns
    -------
    ProviderInterface
        Ready-to-call provider instance.

    Raises
    ------
    ProviderNotAvailableError
        When the SDK is not installed, the required API key env var is absent,
        or the provider name is unrecognised.  The message never contains secrets.
    """
    if client is not None:
        return AnthropicProvider(client=client)

    name = provider_name.lower().strip()
    if name == PROVIDER_ANTHROPIC:
        return AnthropicProvider(api_key=api_key)
    if name == PROVIDER_OPENAI:
        return OpenAIProvider(api_key=api_key)
    if name == PROVIDER_GEMINI:
        return GeminiProvider(api_key=api_key)
    raise ProviderNotAvailableError(f"unknown provider: {provider_name!r}")


# ---------------------------------------------------------------------------
# Backwards-compat public call wrapper (Phase 2.5a surface — unchanged)
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

    This is the Phase 2.5a surface — unchanged for backwards compat.
    New code should prefer ``get_provider().call()``.
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
