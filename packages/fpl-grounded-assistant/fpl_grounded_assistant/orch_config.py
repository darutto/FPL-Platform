"""
fpl_grounded_assistant.orch_config
====================================
Phase Orch-4a: Orchestration feature-flag configuration.

Reads environment variables to determine whether the LLM-orchestration path
is enabled and which provider to use.  The flag is **OFF by default**.

When OFF: ``respond()`` behaves identically to the pre-Orch-4a baseline.
When ON:  ``respond()`` delegates to ``ask_orchestrated()`` at the shared
          backend point; successful results are mapped to ``FinalResponse``.
          Any orchestration failure silently falls back to the deterministic
          path, preserving safe grounded behavior.

Environment variables
---------------------
FPL_ORCH_ENABLED
    Set to ``"1"``, ``"true"``, ``"yes"``, or ``"on"`` (case-insensitive) to
    enable orchestration.  Any other value (or absent) means OFF.
    Default: OFF.

FPL_ORCH_PROVIDER
    Optional provider string passed to ``ask_orchestrated(provider=...)``.
    Valid values: ``"anthropic"``, ``"openai"``, ``"gemini"``.
    When absent or empty, defaults to ``None`` (Anthropic-first auto-detect).
    Default: None (auto-detect).

Design notes
------------
* ``is_orch_enabled()`` is called once per ``respond()`` invocation; it reads
  the env var fresh each call so tests can toggle the flag without restarting.
* No global mutable state; side-effect free on import.
* The two public functions are the only coupling point — nothing else in the
  package reads these env vars directly.
"""
from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Public env-var name constants
# ---------------------------------------------------------------------------

#: Environment variable that enables orchestration when set to a truthy value.
ORCH_ENABLED_ENV: str = "FPL_ORCH_ENABLED"

#: Environment variable that selects the LLM provider for orchestration.
ORCH_PROVIDER_ENV: str = "FPL_ORCH_PROVIDER"

#: Environment variable for the per-call LLM timeout in seconds (float).
ORCH_TIMEOUT_ENV: str = "FPL_ORCH_TIMEOUT_S"

#: Environment variable for the maximum number of retry attempts (int, 0–3).
ORCH_MAX_RETRIES_ENV: str = "FPL_ORCH_MAX_RETRIES"


# ---------------------------------------------------------------------------
# Internal defaults
# ---------------------------------------------------------------------------

#: Default call timeout used when ``FPL_ORCH_TIMEOUT_S`` is absent or invalid.
DEFAULT_TIMEOUT_S: float = 20.0

#: Default max retries used when ``FPL_ORCH_MAX_RETRIES`` is absent or invalid.
DEFAULT_MAX_RETRIES: int = 1


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_orch_enabled() -> bool:
    """Return ``True`` when ``FPL_ORCH_ENABLED`` is set to a truthy value.

    Reads the environment variable fresh on each call — tests can toggle the
    flag between calls without restarting the process.

    Returns
    -------
    bool
        ``True`` when orchestration is enabled; ``False`` (default) otherwise.

    Examples
    --------
    >>> import os
    >>> os.environ.pop("FPL_ORCH_ENABLED", None)
    >>> is_orch_enabled()
    False
    >>> os.environ["FPL_ORCH_ENABLED"] = "1"
    >>> is_orch_enabled()
    True
    """
    return os.environ.get(ORCH_ENABLED_ENV, "").strip().lower() in _TRUTHY


def get_orch_provider() -> str | None:
    """Return the value of ``FPL_ORCH_PROVIDER``, or ``None`` when absent/empty.

    The returned string is passed directly to ``ask_orchestrated(provider=...)``.
    ``None`` means Anthropic-first auto-detect (Orch-3b default).

    Returns
    -------
    str | None
        Provider string or ``None``.

    Examples
    --------
    >>> import os
    >>> os.environ.pop("FPL_ORCH_PROVIDER", None)
    >>> get_orch_provider() is None
    True
    >>> os.environ["FPL_ORCH_PROVIDER"] = "openai"
    >>> get_orch_provider()
    'openai'
    """
    val = os.environ.get(ORCH_PROVIDER_ENV, "").strip()
    return val if val else None


def get_orch_timeout() -> float:
    """Return the configured LLM call timeout in seconds.

    Reads ``FPL_ORCH_TIMEOUT_S``.  Falls back to :data:`DEFAULT_TIMEOUT_S`
    when the variable is absent, empty, or not a positive number.

    Returns
    -------
    float
        Timeout in seconds (always > 0).

    Examples
    --------
    >>> import os
    >>> os.environ.pop("FPL_ORCH_TIMEOUT_S", None)
    >>> get_orch_timeout() == DEFAULT_TIMEOUT_S
    True
    >>> os.environ["FPL_ORCH_TIMEOUT_S"] = "30"
    >>> get_orch_timeout()
    30.0
    """
    raw = os.environ.get(ORCH_TIMEOUT_ENV, "").strip()
    try:
        val = float(raw)
        return val if val > 0 else DEFAULT_TIMEOUT_S
    except (ValueError, TypeError):
        return DEFAULT_TIMEOUT_S


def get_orch_max_retries() -> int:
    """Return the configured maximum number of LLM retry attempts.

    Reads ``FPL_ORCH_MAX_RETRIES``.  Falls back to :data:`DEFAULT_MAX_RETRIES`
    when the variable is absent, empty, or not a non-negative integer.
    The value is capped at 3 regardless of what is configured.

    Returns
    -------
    int
        Max retries in range [0, 3].

    Examples
    --------
    >>> import os
    >>> os.environ.pop("FPL_ORCH_MAX_RETRIES", None)
    >>> get_orch_max_retries() == DEFAULT_MAX_RETRIES
    True
    >>> os.environ["FPL_ORCH_MAX_RETRIES"] = "0"
    >>> get_orch_max_retries()
    0
    """
    raw = os.environ.get(ORCH_MAX_RETRIES_ENV, "").strip()
    try:
        val = int(raw)
        return max(0, min(val, 3))
    except (ValueError, TypeError):
        return DEFAULT_MAX_RETRIES
