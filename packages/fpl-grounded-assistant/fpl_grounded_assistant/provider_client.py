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

import inspect
import os
import threading
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

# Mutable single-element list used as a module-level cache for the last API key
# passed to _genai_sdk.configure().  Bounds the global side-effect to once per
# unique key value.  Protected by _GEMINI_CONFIGURE_LOCK for thread safety.
_LAST_GEMINI_CONFIGURED_KEY: list[str | None] = [None]
_GEMINI_CONFIGURE_LOCK: threading.Lock = threading.Lock()

# Process-lifetime cache for OpenAI timeout capability.
# None = not yet determined; True = create() accepts timeout=; False = does not.
# Protected by _OAI_TIMEOUT_CACHE_LOCK during the one-time probe.
_OAI_TIMEOUT_SUPPORTED: list[bool | None] = [None]
_OAI_TIMEOUT_CACHE_LOCK: threading.Lock = threading.Lock()


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
    → (text, model, error_code, error_msg, attempts, latency_ms)

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
    latency_ms:
        Total wall-clock time for all attempts in milliseconds, measured with
        ``time.perf_counter()``.  Includes retry wait time when retries occur.
        Always >= 0.
    """

    text:       str | None
    model:      str
    error_code: str | None
    error_msg:  str | None
    attempts:   int
    latency_ms: float


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
# Provider-specific helpers
# ---------------------------------------------------------------------------

def _gemini_configure(api_key: str) -> None:
    """Configure the genai SDK only when the API key has changed.

    ``_genai_sdk.configure()`` mutates module-level state in the
    ``google.generativeai`` package.  Calling it on every invocation is
    wasteful and makes side-effects hard to reason about.  This helper
    keeps a module-level cache of the last configured key and skips
    ``configure()`` when the key is unchanged.

    Thread safety: the check-and-set is protected by ``_GEMINI_CONFIGURE_LOCK``
    so concurrent callers with different keys do not race.  The SDK's own
    ``configure()`` is not thread-safe; this lock ensures we call it at most
    once per unique key value.

    Safe defaults:
    * When ``_genai_sdk`` is None (SDK not installed) the call is a no-op.
    """
    if not _GEMINI_AVAILABLE or _genai_sdk is None:
        return
    with _GEMINI_CONFIGURE_LOCK:
        if _LAST_GEMINI_CONFIGURED_KEY[0] != api_key:
            _genai_sdk.configure(api_key=api_key)
            _LAST_GEMINI_CONFIGURED_KEY[0] = api_key


def _strip_gemini_unsupported_schema_fields(value: Any) -> Any:
    """Recursively drop JSON-schema keys unsupported by Gemini SDK.

    ``google-generativeai`` rejects ``additionalProperties`` in function
    declaration schemas and raises ``ValueError`` during model construction.
    Removing this key preserves required/typed fields while preventing a hard
    server error in the orchestration path.
    """
    if isinstance(value, dict):
        return {
            k: _strip_gemini_unsupported_schema_fields(v)
            for k, v in value.items()
            if k != "additionalProperties"
        }
    if isinstance(value, list):
        return [_strip_gemini_unsupported_schema_fields(v) for v in value]
    return value


def _probe_oai_timeout_support(create_fn: Any) -> bool:
    """Determine via signature inspection whether *create_fn* accepts ``timeout=``.

    Uses :func:`inspect.signature` — deterministic, no exception-message
    inspection, no network calls.

    Returns ``True`` when:

    * ``"timeout"`` is an explicit named parameter in the signature, **or**
    * the function declares ``**kwargs`` (conservative: assumes it handles
      any keyword, including ``timeout``).

    Returns ``False`` only when ``"timeout"`` is definitively absent **and**
    no ``**kwargs`` catch-all exists.  For functions with ``**kwargs`` that
    actually reject ``timeout`` at runtime, the runtime branch in
    ``_call_with_oai_compat_timeout`` catches the resulting ``TypeError``
    and updates the cache to ``False``.

    Falls back to ``True`` on any introspection error (conservative).
    """
    try:
        sig = inspect.signature(create_fn)
    except (ValueError, TypeError):
        return True  # conservative: assume supported
    params = sig.parameters
    if "timeout" in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _get_oai_timeout_support(create_fn: Any) -> bool:
    """Return cached OpenAI timeout capability; run probe on first call (thread-safe).

    A single result is cached for the process lifetime.  All OpenAI clients
    within the same process share the same installed SDK version, so probing
    once is sufficient.  The cache is protected by ``_OAI_TIMEOUT_CACHE_LOCK``
    to prevent races on the first call.
    """
    # Lock-free fast path — the common case after the first call.
    if _OAI_TIMEOUT_SUPPORTED[0] is not None:
        return _OAI_TIMEOUT_SUPPORTED[0]  # type: ignore[return-value]
    with _OAI_TIMEOUT_CACHE_LOCK:
        if _OAI_TIMEOUT_SUPPORTED[0] is None:
            _OAI_TIMEOUT_SUPPORTED[0] = _probe_oai_timeout_support(create_fn)
        return _OAI_TIMEOUT_SUPPORTED[0]  # type: ignore[return-value]


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

        _t0 = time.perf_counter()
        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
        _latency_ms = (time.perf_counter() - _t0) * 1000.0

        if not raw.success:
            return ProviderResult(
                text=None,
                model=model,
                error_code=raw.error_code,
                error_msg=raw.error_msg,
                attempts=raw.attempts,
                latency_ms=_latency_ms,
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
                latency_ms=_latency_ms,
            )
        return ProviderResult(
            text=text,
            model=model,
            error_code=None,
            error_msg=None,
            attempts=raw.attempts,
            latency_ms=_latency_ms,
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

        _t0 = time.perf_counter()
        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
        _latency_ms = (time.perf_counter() - _t0) * 1000.0

        if not raw.success:
            return ProviderResult(
                text=None,
                model=model,
                error_code=raw.error_code,
                error_msg=raw.error_msg,
                attempts=raw.attempts,
                latency_ms=_latency_ms,
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
                latency_ms=_latency_ms,
            )
        return ProviderResult(
            text=text,
            model=model,
            error_code=None,
            error_msg=None,
            attempts=raw.attempts,
            latency_ms=_latency_ms,
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

        _t0 = time.perf_counter()
        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
        _latency_ms = (time.perf_counter() - _t0) * 1000.0

        if not raw.success:
            return ProviderResult(
                text=None,
                model=model,
                error_code=raw.error_code,
                error_msg=raw.error_msg,
                attempts=raw.attempts,
                latency_ms=_latency_ms,
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
                latency_ms=_latency_ms,
            )
        return ProviderResult(
            text=text,
            model=model,
            error_code=None,
            error_msg=None,
            attempts=raw.attempts,
            latency_ms=_latency_ms,
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
# Orchestration tool-call surface (Phase 2.5d2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrchCallResult:
    """Result of a provider tool-use call made by the orchestrator.

    Unlike ``ProviderResult`` (which extracts text for the presentation layer),
    ``OrchCallResult`` preserves the raw API response so the orchestrator can
    parse tool-call blocks directly.

    Attributes
    ----------
    response:
        Raw LLM API response on success; ``None`` on failure or when no API
        call was attempted (e.g. missing credentials → ``attempts == 0``).
    error_code:
        One of the ``PERR_*`` constants on failure; ``None`` on success.
    error_msg:
        Sanitised, secret-free error string for logs; ``None`` on success.
    attempts:
        Total HTTP attempts made.  ``0`` means the call was never attempted
        (credentials missing, SDK not installed).
    latency_ms:
        Total wall-clock milliseconds from function entry to return, measured
        via ``time.perf_counter()``.  Includes all retry waits.  Always >= 0.
    input_tokens:
        Input tokens consumed by this call, or ``None`` when not available.
        Extracted from the provider response's usage fields. Wrapped in
        try/except at population time — never crashes the orchestrator.
    output_tokens:
        Output tokens generated by this call, or ``None`` when not available.
    cache_read_tokens:
        Cache-read tokens (Anthropic/DeepSeek: ``cache_read_input_tokens``;
        Gemini/OpenAI: ``None``). Populated only when the provider exposes
        this field. Always ``None`` on failure.
    """

    response:          Any
    error_code:        str | None
    error_msg:         str | None
    attempts:          int
    latency_ms:        float
    # F3: token observability fields (additive, all None-default)
    input_tokens:      int | None = None
    output_tokens:     int | None = None
    cache_read_tokens: int | None = None


def _extract_anthropic_usage(
    response: Any,
) -> tuple[int | None, int | None, int | None]:
    """Extract (input_tokens, output_tokens, cache_read_tokens) from an Anthropic response.

    Wraps every field access in a try/except so that malformed or missing
    usage data never crashes the orchestrator.  Returns ``(None, None, None)``
    when extraction fails entirely.
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None, None
        input_tokens: int | None = None
        output_tokens: int | None = None
        cache_read_tokens: int | None = None
        try:
            v = getattr(usage, "input_tokens", None)
            input_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        try:
            v = getattr(usage, "output_tokens", None)
            output_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        try:
            v = getattr(usage, "cache_read_input_tokens", None)
            cache_read_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        return input_tokens, output_tokens, cache_read_tokens
    except Exception:  # noqa: BLE001
        return None, None, None


def _extract_openai_usage(
    response: Any,
) -> tuple[int | None, int | None, int | None]:
    """Extract (input_tokens, output_tokens, cache_read_tokens) from an OpenAI response.

    OpenAI uses ``prompt_tokens`` / ``completion_tokens``; cache reads come from
    ``usage.prompt_tokens_details.cached_tokens`` (present in newer SDK versions).
    Returns ``(None, None, None)`` when extraction fails.
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None, None
        input_tokens: int | None = None
        output_tokens: int | None = None
        cache_read_tokens: int | None = None
        try:
            v = getattr(usage, "prompt_tokens", None)
            input_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        try:
            v = getattr(usage, "completion_tokens", None)
            output_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        try:
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                v = getattr(details, "cached_tokens", None)
                cache_read_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        return input_tokens, output_tokens, cache_read_tokens
    except Exception:  # noqa: BLE001
        return None, None, None


def _extract_gemini_usage(
    response: Any,
) -> tuple[int | None, int | None, int | None]:
    """Extract (input_tokens, output_tokens, None) from a Gemini response.

    Gemini uses ``usage_metadata.prompt_token_count`` /
    ``usage_metadata.candidates_token_count``.  No cache_read field —
    always returns ``None`` for the third element.
    Returns ``(None, None, None)`` when extraction fails.
    """
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None, None, None
        input_tokens: int | None = None
        output_tokens: int | None = None
        try:
            v = getattr(usage, "prompt_token_count", None)
            input_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        try:
            v = getattr(usage, "candidates_token_count", None)
            output_tokens = int(v) if v is not None else None
        except Exception:  # noqa: BLE001
            pass
        # Gemini does not expose a cache_read field.
        return input_tokens, output_tokens, None
    except Exception:  # noqa: BLE001
        return None, None, None


def _call_with_oai_compat_timeout(
    create_fn: Any,
    *,
    timeout_s: float,
    **kwargs: Any,
) -> Any:
    """Call an OpenAI-style ``create()`` function with SDK-version-compatible timeout.

    The ``timeout`` parameter changed across OpenAI SDK major versions:

    * ``>=1.0`` (current): ``timeout=float`` is accepted natively.
    * ``<1.0`` (legacy) or custom wrappers: ``timeout`` kwarg is not recognised
      and raises ``TypeError``.

    Route the call through a cached capability decision:

    1. **Cached True**  — call with ``timeout=``.  No exception handling.
    2. **Cached False** — call without ``timeout=``.  No exception handling.
    3. **Cache empty**  — one-time probe under ``_OAI_TIMEOUT_CACHE_LOCK``:

       a. :func:`_probe_oai_timeout_support` inspects the function signature
          (no exception messages, deterministic).

       b. If signature says ``False``: cache ``False``, call without timeout.

       c. If signature says ``True`` (explicit ``timeout`` param **or**
          ``**kwargs``): attempt the call with timeout.

          * On success: cache ``True``, return result.
          * On ``TypeError``: the ``**kwargs`` function does not handle
            ``timeout`` at runtime.  Cache ``False``, retry without timeout.
          * On any other exception: cache stays ``True`` (supports timeout —
            the error is from the API, not the kwarg), re-raise for
            ``_classify_error`` to handle.

    After the first call per process **all** subsequent calls use the fast,
    deterministic path — no exception inspection, no message matching.

    Parameters
    ----------
    create_fn:
        Callable accepting keyword arguments; typically
        ``openai_client.chat.completions.create``.
    timeout_s:
        Desired timeout in seconds.
    **kwargs:
        All other keyword arguments forwarded verbatim to ``create_fn``.
    """
    # Lock-free fast path (all calls after the first)
    cached = _OAI_TIMEOUT_SUPPORTED[0]
    if cached is True:
        return create_fn(timeout=timeout_s, **kwargs)
    if cached is False:
        return create_fn(**kwargs)

    # One-time probe under lock
    with _OAI_TIMEOUT_CACHE_LOCK:
        cached = _OAI_TIMEOUT_SUPPORTED[0]
        if cached is None:
            # Run signature probe
            _OAI_TIMEOUT_SUPPORTED[0] = _probe_oai_timeout_support(create_fn)
            if not _OAI_TIMEOUT_SUPPORTED[0]:
                # Definitively no timeout support
                return create_fn(**kwargs)
            # Signature says "may support" — verify with the actual call
            try:
                result = create_fn(timeout=timeout_s, **kwargs)
                # _OAI_TIMEOUT_SUPPORTED[0] already True from probe
                return result
            except TypeError:
                # **kwargs function rejects timeout at runtime — update cache
                _OAI_TIMEOUT_SUPPORTED[0] = False
                return create_fn(**kwargs)
            except Exception:
                # Non-TypeError error (auth, network, …): cache stays True
                # (the function does accept timeout= ; the error is API-level)
                raise
        # Another thread populated the cache while we waited for the lock

    # Use the freshly-populated cache (outside lock)
    if _OAI_TIMEOUT_SUPPORTED[0]:
        return create_fn(timeout=timeout_s, **kwargs)
    return create_fn(**kwargs)


def call_orch_provider(
    provider_name: str,
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
    timeout_s: float = 20.0,
    max_retries: int = 1,
    client: Any = None,
    api_key: str | None = None,
    _sleep_fn: Any = None,
    _request_fn: Any = None,
    # P1.e Lever 2: optional pre-built system blocks (list) for Anthropic prompt caching.
    # When supplied for an Anthropic call, used in place of the plain `system` string so
    # that cache_control markers are preserved.  Ignored for OpenAI / Gemini.
    _system_blocks: list[dict[str, Any]] | None = None,
) -> OrchCallResult:
    """Unified orchestration provider call for tool-use / function-calling.

    Handles provider-specific request construction (Anthropic ``messages.create``
    with tools, OpenAI ``chat.completions.create`` with function-calling,
    Gemini ``generate_content`` with function declarations).  Returns the raw
    API response so the orchestrator can parse tool-call blocks directly.

    Parameters
    ----------
    provider_name:
        One of ``PROVIDER_ANTHROPIC``, ``PROVIDER_OPENAI``, ``PROVIDER_GEMINI``.
        Unknown values fall back to Anthropic.
    model:
        Provider-specific model identifier.
    system:
        System prompt text.
    tools:
        Tool list in the **provider-appropriate wire format** (caller is
        responsible for building the right format via ``_build_tools()``).
    messages:
        Conversation messages.  For Gemini, only the first message's
        ``"content"`` value is used (single-turn tool-use).
    max_tokens:
        Maximum tokens to generate.
    timeout_s:
        Per-attempt timeout in seconds.
    max_retries:
        Maximum additional attempts for transient errors (capped at 3).
    client:
        Pre-built provider client.  For Anthropic: ``anthropic.Anthropic``
        instance.  For OpenAI: ``openai.OpenAI`` instance.  For Gemini: a
        ``GenerativeModel``-compatible object (its ``.generate_content()``
        method is called directly).  When ``None``, credentials are read
        from the appropriate env var.
    api_key:
        Explicit API key (used when ``client is None``).
    _sleep_fn:
        Injected sleep callable for tests (avoids real retry waits).
    _request_fn:
        Zero-argument callable override.  When supplied, bypasses all
        provider-specific client construction and calls this function
        directly as the HTTP request.  The returned object is used as the
        raw response.  Use only in tests.

    Returns
    -------
    OrchCallResult
        Always returns — never raises.  ``error_code is None`` on success.
        ``attempts == 0`` signals the call was never attempted (credentials
        missing or SDK absent) — map to ``OUTCOME_NO_CLIENT`` at the caller.
    """
    _t0 = time.perf_counter()

    # --- Test injection: bypass all provider-specific client construction ---
    if _request_fn is not None:
        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
        # F3: attempt token extraction from mock/real response (best-effort, Anthropic shape first).
        _inj_in, _inj_out, _inj_cache = (None, None, None)
        if raw.success and raw.response is not None:
            _inj_in, _inj_out, _inj_cache = _extract_anthropic_usage(raw.response)
        return OrchCallResult(
            response=raw.response if raw.success else None,
            error_code=raw.error_code,
            error_msg=raw.error_msg,
            attempts=raw.attempts,
            latency_ms=(time.perf_counter() - _t0) * 1000.0,
            input_tokens=_inj_in,
            output_tokens=_inj_out,
            cache_read_tokens=_inj_cache,
        )

    name = provider_name.lower().strip() if provider_name else PROVIDER_ANTHROPIC

    # --- OpenAI: Chat Completions with function-calling ---
    if name == PROVIDER_OPENAI:
        _key = api_key or os.environ.get("OPENAI_API_KEY")
        if not _OPENAI_AVAILABLE or not _key:
            return OrchCallResult(
                response=None,
                error_code=PERR_AUTH,
                error_msg="openai SDK not installed or OPENAI_API_KEY not set",
                attempts=0,
                latency_ms=(time.perf_counter() - _t0) * 1000.0,
            )
        _oai   = client or _openai_sdk.OpenAI(api_key=_key)
        _sys   = system
        _msgs  = messages
        _tools = tools

        def _oai_request() -> Any:
            return _call_with_oai_compat_timeout(
                _oai.chat.completions.create,
                timeout_s=timeout_s,
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": _sys}, *_msgs],
                tools=_tools,
            )

        raw = call_provider_request(_oai_request, max_retries=max_retries, _sleep_fn=_sleep_fn)
        # F3: extract OpenAI (and DeepSeek, same shape) usage tokens.
        _oai_in, _oai_out, _oai_cache = (None, None, None)
        if raw.success and raw.response is not None:
            _oai_in, _oai_out, _oai_cache = _extract_openai_usage(raw.response)
        return OrchCallResult(
            response=raw.response if raw.success else None,
            error_code=raw.error_code,
            error_msg=raw.error_msg,
            attempts=raw.attempts,
            latency_ms=(time.perf_counter() - _t0) * 1000.0,
            input_tokens=_oai_in,
            output_tokens=_oai_out,
            cache_read_tokens=_oai_cache,
        )

    # --- Gemini: GenerativeModel with function declarations ---
    if name == PROVIDER_GEMINI:
        _key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not _GEMINI_AVAILABLE or not _key:
            return OrchCallResult(
                response=None,
                error_code=PERR_AUTH,
                error_msg="google-generativeai not installed or GOOGLE_API_KEY not set",
                attempts=0,
                latency_ms=(time.perf_counter() - _t0) * 1000.0,
            )
        _tools = _strip_gemini_unsupported_schema_fields(tools)
        if client is not None:
            _gem_model = client   # pre-built model (test mock)
        else:
            try:
                _gemini_configure(_key)   # bounded configure: skips if key unchanged
                _gem_model = _genai_sdk.GenerativeModel(
                    model_name=model,
                    system_instruction=system,
                    tools=_tools,
                )
            except Exception as exc:  # noqa: BLE001
                return OrchCallResult(
                    response=None,
                    error_code=PERR_PROVIDER,
                    error_msg=_sanitize_error(exc),
                    attempts=1,
                    latency_ms=(time.perf_counter() - _t0) * 1000.0,
                )
        _user_content = messages[0]["content"] if messages else ""
        _gm = _gem_model

        def _gem_request() -> Any:
            return _gm.generate_content(
                _user_content,
                request_options={"timeout": timeout_s},
            )

        raw = call_provider_request(_gem_request, max_retries=max_retries, _sleep_fn=_sleep_fn)
        # F3: extract Gemini usage tokens.
        _gem_in, _gem_out, _gem_cache = (None, None, None)
        if raw.success and raw.response is not None:
            _gem_in, _gem_out, _gem_cache = _extract_gemini_usage(raw.response)
        return OrchCallResult(
            response=raw.response if raw.success else None,
            error_code=raw.error_code,
            error_msg=raw.error_msg,
            attempts=raw.attempts,
            latency_ms=(time.perf_counter() - _t0) * 1000.0,
            input_tokens=_gem_in,
            output_tokens=_gem_out,
            cache_read_tokens=_gem_cache,
        )

    # --- Anthropic: Messages API with tool schemas (default) ---
    _ant_client = client
    if _ant_client is None:
        _key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not _ANTHROPIC_AVAILABLE or not _key:
            return OrchCallResult(
                response=None,
                error_code=PERR_AUTH,
                error_msg="anthropic SDK not installed or ANTHROPIC_API_KEY not set",
                attempts=0,
                latency_ms=(time.perf_counter() - _t0) * 1000.0,
            )
        try:
            _ant_client = _anthropic_sdk.Anthropic(api_key=_key)
        except Exception:  # noqa: BLE001
            return OrchCallResult(
                response=None,
                error_code=PERR_AUTH,
                error_msg="anthropic client init failed",
                attempts=0,
                latency_ms=(time.perf_counter() - _t0) * 1000.0,
            )

    _ac    = _ant_client
    _msgs  = messages
    _tools = tools
    # P1.e Lever 2: use pre-built system blocks (with cache_control) when available.
    # OpenAI prompt caching is automatic — no opt-in needed (system + tools are
    # first in the request payload, which is already the case here).
    # DeepSeek uses the OpenAI-compatible API; same automatic caching applies.
    # Gemini: TODO — caching via genai.Client.caches.create() with TTL requires
    # the google-genai >=0.8 SDK; not yet integrated. Add when SDK version is locked.
    _system_arg: Any = _system_blocks if _system_blocks is not None else system

    def _ant_request() -> Any:
        return _ac.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_system_arg,
            tools=_tools,
            messages=_msgs,
            timeout=timeout_s,
        )

    raw = call_provider_request(_ant_request, max_retries=max_retries, _sleep_fn=_sleep_fn)
    # F3: extract Anthropic usage tokens (including cache_read_input_tokens).
    _ant_in, _ant_out, _ant_cache = (None, None, None)
    if raw.success and raw.response is not None:
        _ant_in, _ant_out, _ant_cache = _extract_anthropic_usage(raw.response)
    return OrchCallResult(
        response=raw.response if raw.success else None,
        error_code=raw.error_code,
        error_msg=raw.error_msg,
        attempts=raw.attempts,
        latency_ms=(time.perf_counter() - _t0) * 1000.0,
        input_tokens=_ant_in,
        output_tokens=_ant_out,
        cache_read_tokens=_ant_cache,
    )


# ---------------------------------------------------------------------------
# Provider health check  (Phase 2.5-smoke)
# ---------------------------------------------------------------------------

def check_provider_health(
    provider_name: str | None = None,
    *,
    api_key: str | None = None,
) -> dict:
    """Return ``{"available": bool, "error": str | None}`` without raising.

    Performs a lightweight credential-and-SDK check (no live API call).
    Reads ``DEFAULT_PROVIDER`` env var when ``provider_name`` is ``None``;
    falls back to ``"gemini"`` when the env var is also absent.

    This function is safe to call at startup or inside a health endpoint:
    it never raises, performs no network I/O, and completes in microseconds.

    Parameters
    ----------
    provider_name:
        One of ``PROVIDER_ANTHROPIC``, ``PROVIDER_OPENAI``, ``PROVIDER_GEMINI``.
        When ``None``, the active provider is read from ``DEFAULT_PROVIDER``
        env var (default ``"gemini"``).
    api_key:
        Explicit API key to check.  When ``None``, the provider-appropriate
        env var is inspected.

    Returns
    -------
    dict
        ``{"available": True, "error": None}``   — credentials present + SDK installed.
        ``{"available": False, "error": "<msg>"}`` — credentials absent or SDK missing.
    """
    import os as _os  # noqa: PLC0415 — local import avoids shadowing module-level `os`
    try:
        name = (
            provider_name
            or _os.environ.get("DEFAULT_PROVIDER", "gemini")
        ).lower().strip()

        if name == PROVIDER_GEMINI:
            if not _GEMINI_AVAILABLE:
                return {"available": False, "error": "google-generativeai SDK not installed"}
            key = api_key or _os.environ.get("GOOGLE_API_KEY")
            if not key:
                return {"available": False, "error": "GOOGLE_API_KEY not set"}
            return {"available": True, "error": None}

        if name == PROVIDER_OPENAI:
            if not _OPENAI_AVAILABLE:
                return {"available": False, "error": "openai SDK not installed"}
            key = api_key or _os.environ.get("OPENAI_API_KEY")
            if not key:
                return {"available": False, "error": "OPENAI_API_KEY not set"}
            return {"available": True, "error": None}

        # Default: PROVIDER_ANTHROPIC
        if not _ANTHROPIC_AVAILABLE:
            return {"available": False, "error": "anthropic SDK not installed"}
        key = api_key or _os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return {"available": False, "error": "ANTHROPIC_API_KEY not set"}
        return {"available": True, "error": None}

    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"health check error: {type(exc).__name__}"}


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
