"""
llm_orchestrator_core.provider_client
======================================
Unified, domain-neutral provider call contract for tool-use orchestration.

Extracted from the generic core of ``fpl_grounded_assistant.provider_client``
(Phase 2.5b/2.5d2 lineage).  Behaviour parity is intentional:

* Error code mapping: PERR_RATE_LIMIT / PERR_AUTH / PERR_TIMEOUT /
  PERR_NETWORK / PERR_PROVIDER.
* Retry policy: rate-limit (1.0 s delay), timeout (0 s), network (0 s)
  are retried; auth and hard provider errors are not.
* Every public function always returns — it never raises.
* Error messages are truncated to 200 chars and never contain API keys.
* Token usage extraction (input / output / cache-read) per provider.

What was deliberately NOT carried over from the FPL module (FPL coupling):
``fpl_provider_event`` logging tags, the text-extraction ``ProviderInterface``
classes (presentation-layer, unused by the tool loop), and the FPL-specific
degradation gate (lives in the FPL orchestrator).
"""
from __future__ import annotations

import inspect
import os
import threading
import time
import warnings
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
# Internal error codes
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

# Module-level cache of the last key passed to _genai_sdk.configure().
_LAST_GEMINI_CONFIGURED_KEY: list[str | None] = [None]
_GEMINI_CONFIGURE_LOCK: threading.Lock = threading.Lock()

# Process-lifetime cache for OpenAI timeout capability.
_OAI_TIMEOUT_SUPPORTED: list[bool | None] = [None]
_OAI_TIMEOUT_CACHE_LOCK: threading.Lock = threading.Lock()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderCallResult:
    """Normalised success/failure envelope from ``call_provider_request()``."""

    response:   Any
    success:    bool
    error_code: str | None
    error_msg:  str | None
    attempts:   int


@dataclass(frozen=True)
class OrchCallResult:
    """Result of a provider tool-use call.

    Preserves the raw API response so the tool loop can parse tool-call
    blocks directly.  ``attempts == 0`` means the call was never attempted
    (credentials missing or SDK absent).
    """

    response:          Any
    error_code:        str | None
    error_msg:         str | None
    attempts:          int
    latency_ms:        float
    input_tokens:      int | None = None
    output_tokens:     int | None = None
    cache_read_tokens: int | None = None


class ProviderNotAvailableError(Exception):
    """SDK not installed, API key missing, or client construction failed."""


# ---------------------------------------------------------------------------
# Exception classification / sanitisation
# ---------------------------------------------------------------------------

def _classify_error(exc: Exception) -> str:
    """Map a provider exception to a ``PERR_*`` code."""
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


#: Env var names whose values must never appear in logged error messages.
_SECRET_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
    "WORLDCUP_API_KEY",
)


def _sanitize_error(exc: Exception) -> str:
    """Return a log-safe description of *exc* (truncated, secret-free)."""
    exc_type = type(exc).__name__
    status   = getattr(exc, "status_code", None)
    if status:
        return f"{exc_type} (HTTP {status})"
    msg = str(exc)
    for key_name in _SECRET_ENV_VARS:
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
    """Configure the genai SDK only when the API key has changed."""
    if not _GEMINI_AVAILABLE or _genai_sdk is None:
        return
    with _GEMINI_CONFIGURE_LOCK:
        if _LAST_GEMINI_CONFIGURED_KEY[0] != api_key:
            _genai_sdk.configure(api_key=api_key)
            _LAST_GEMINI_CONFIGURED_KEY[0] = api_key


def _strip_gemini_unsupported_schema_fields(value: Any) -> Any:
    """Recursively drop/normalize JSON-schema keys unsupported by the Gemini SDK.

    Gemini's schema (a protobuf enum) requires ``"type"`` to be a single
    string, unlike JSON Schema which allows a union list (e.g.
    ``["string", "integer"]`` for a polymorphic id field). Collapse such
    unions to their first non-``"null"`` member.
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            if k == "additionalProperties":
                continue
            if k == "type" and isinstance(v, list):
                _non_null = [t for t in v if t != "null"]
                v = _non_null[0] if _non_null else v[0]
            result[k] = _strip_gemini_unsupported_schema_fields(v)
        return result
    if isinstance(value, list):
        return [_strip_gemini_unsupported_schema_fields(v) for v in value]
    return value


def _probe_oai_timeout_support(create_fn: Any) -> bool:
    """Signature-inspect whether *create_fn* accepts ``timeout=``."""
    try:
        sig = inspect.signature(create_fn)
    except (ValueError, TypeError):
        return True  # conservative: assume supported
    params = sig.parameters
    if "timeout" in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _call_with_oai_compat_timeout(
    create_fn: Any,
    *,
    timeout_s: float,
    **kwargs: Any,
) -> Any:
    """Call an OpenAI-style ``create()`` with SDK-version-compatible timeout."""
    cached = _OAI_TIMEOUT_SUPPORTED[0]
    if cached is True:
        return create_fn(timeout=timeout_s, **kwargs)
    if cached is False:
        return create_fn(**kwargs)

    with _OAI_TIMEOUT_CACHE_LOCK:
        cached = _OAI_TIMEOUT_SUPPORTED[0]
        if cached is None:
            _OAI_TIMEOUT_SUPPORTED[0] = _probe_oai_timeout_support(create_fn)
            if not _OAI_TIMEOUT_SUPPORTED[0]:
                return create_fn(**kwargs)
            try:
                return create_fn(timeout=timeout_s, **kwargs)
            except TypeError:
                _OAI_TIMEOUT_SUPPORTED[0] = False
                return create_fn(**kwargs)
            except Exception:
                # Non-TypeError: the kwarg is fine, the error is API-level.
                raise

    if _OAI_TIMEOUT_SUPPORTED[0]:
        return create_fn(timeout=timeout_s, **kwargs)
    return create_fn(**kwargs)


# ---------------------------------------------------------------------------
# Token usage extraction (best-effort; never raises)
# ---------------------------------------------------------------------------

def _extract_anthropic_usage(response: Any) -> tuple[int | None, int | None, int | None]:
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None, None
        def _as_int(attr: str) -> int | None:
            try:
                v = getattr(usage, attr, None)
                return int(v) if v is not None else None
            except Exception:  # noqa: BLE001
                return None
        return (
            _as_int("input_tokens"),
            _as_int("output_tokens"),
            _as_int("cache_read_input_tokens"),
        )
    except Exception:  # noqa: BLE001
        return None, None, None


def _extract_openai_usage(response: Any) -> tuple[int | None, int | None, int | None]:
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


def _extract_gemini_usage(response: Any) -> tuple[int | None, int | None, int | None]:
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
        return input_tokens, output_tokens, None
    except Exception:  # noqa: BLE001
        return None, None, None


# ---------------------------------------------------------------------------
# Core retry/error-normalisation loop (provider-agnostic)
# ---------------------------------------------------------------------------

def call_provider_request(
    request_fn: Any,
    *,
    max_retries: int = 1,
    _sleep_fn: Any = None,
) -> ProviderCallResult:
    """Call a zero-argument request function with bounded retries.

    ``max_retries`` is capped at 3.  Only transient errors (rate-limit,
    timeout, network) are retried.  Always returns; never raises.
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
# Orchestration tool-call surface
# ---------------------------------------------------------------------------

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
    # Optional pre-built system blocks (list) for Anthropic prompt caching.
    # When supplied for an Anthropic call, used in place of the plain
    # ``system`` string so cache_control markers are preserved.
    _system_blocks: list[dict[str, Any]] | None = None,
) -> OrchCallResult:
    """Unified provider call for tool-use / function-calling.

    ``tools`` must already be in the provider-appropriate wire format
    (see ``tool_schema.build_tools()``).  Returns the raw API response so
    the caller can parse tool-call blocks.  Always returns; never raises.
    """
    _t0 = time.perf_counter()

    # --- Test injection: bypass all provider-specific client construction ---
    if _request_fn is not None:
        raw = call_provider_request(_request_fn, max_retries=max_retries, _sleep_fn=_sleep_fn)
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
        _g_tools = _strip_gemini_unsupported_schema_fields(tools)
        if client is not None:
            _gem_model = client   # pre-built model (test mock)
        else:
            try:
                _gemini_configure(_key)
                _gem_model = _genai_sdk.GenerativeModel(
                    model_name=model,
                    system_instruction=system,
                    tools=_g_tools,
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
    _a_tools = tools
    _system_arg: Any = _system_blocks if _system_blocks is not None else system

    def _ant_request() -> Any:
        return _ac.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_system_arg,
            tools=_a_tools,
            messages=_msgs,
            timeout=timeout_s,
        )

    raw = call_provider_request(_ant_request, max_retries=max_retries, _sleep_fn=_sleep_fn)
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
# Provider health check
# ---------------------------------------------------------------------------

def check_provider_health(
    provider_name: str | None = None,
    *,
    api_key: str | None = None,
) -> dict:
    """Return ``{"available": bool, "error": str | None}`` without raising.

    Lightweight credential-and-SDK check; no network I/O.  Reads the
    ``DEFAULT_PROVIDER`` env var when ``provider_name`` is ``None``
    (falls back to ``"anthropic"``).
    """
    try:
        name = (
            provider_name
            or os.environ.get("DEFAULT_PROVIDER", PROVIDER_ANTHROPIC)
        ).lower().strip()

        if name == PROVIDER_GEMINI:
            if not _GEMINI_AVAILABLE:
                return {"available": False, "error": "google-generativeai SDK not installed"}
            key = api_key or os.environ.get("GOOGLE_API_KEY")
            if not key:
                return {"available": False, "error": "GOOGLE_API_KEY not set"}
            return {"available": True, "error": None}

        if name == PROVIDER_OPENAI:
            if not _OPENAI_AVAILABLE:
                return {"available": False, "error": "openai SDK not installed"}
            key = api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                return {"available": False, "error": "OPENAI_API_KEY not set"}
            return {"available": True, "error": None}

        # Default: PROVIDER_ANTHROPIC
        if not _ANTHROPIC_AVAILABLE:
            return {"available": False, "error": "anthropic SDK not installed"}
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return {"available": False, "error": "ANTHROPIC_API_KEY not set"}
        return {"available": True, "error": None}

    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"health check error: {type(exc).__name__}"}
