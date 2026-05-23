"""
fpl_grounded_assistant.audit
==============================
Phase P3.1: Append-only NDJSON audit log, one file per UTC day.

Public API
----------
write_audit_entry(entry, log_dir=None)  -> None
estimate_usd_cost(tokens, provider)     -> float

Log format
----------
One JSON object per line, no extra whitespace, UTF-8, LF line endings.
File: ``audit_logs/<YYYY-MM-DD>.ndjson`` (UTC date at write time).
Directory is auto-created if absent.

Replay
------
Each line is independently parseable:
    import json
    for line in open("audit_logs/2026-05-23.ndjson"):
        entry = json.loads(line)

USD cost estimation
-------------------
Uses per-1M-token pricing from PROVIDER_PRICING_PER_1M.  Refine after
P5 cost study.  Pricing is intentionally conservative (not aggressive) —
rounding errors should over-estimate, not under-estimate.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Provider pricing
# ---------------------------------------------------------------------------

PROVIDER_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gemini": {
        "input":      0.075,
        "output":     0.30,
        "cache_read": 0.0075,
    },
    "anthropic": {
        "input":      0.80,
        "output":     4.00,
        "cache_read": 0.08,
    },
    "openai": {
        "input":      0.15,
        "output":     0.60,
        "cache_read": 0.075,
    },
    "deepseek": {
        "input":      0.27,
        "output":     1.10,
        "cache_read": 0.027,
    },
}

# Default fallback when provider is unknown.
_DEFAULT_PROVIDER: str = "gemini"

# Default log directory relative to repo root (packages/fpl-grounded-assistant).
_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_HERE)
_DEFAULT_LOG_DIR: str = os.path.join(_PACKAGE_DIR, "audit_logs")

# File-write lock — prevents interleaved writes when multiple coroutines/threads
# write concurrently (shouldn't happen in production but safe-by-default).
_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    """One turn's audit record."""

    timestamp: str                   # ISO 8601 UTC, e.g. "2026-05-23T14:31:00.123456Z"
    user_id: str                     # anonymized; "anonymous" when no header present
    tier: str                        # quota tier at time of turn
    question: str
    branch: str                      # "resource" / "prompt" / "orchestrator" / "unsupported"
    outcome: str                     # final outcome string
    intent: str | None
    tool_calls: list[dict]           # [{"name": str, "args": dict, "output_status": str}, ...]
    evaluator_verdict: dict | None   # {approved, grounded, complete, safe, retry_feedback} | None
    retry_attempted: bool
    final_text_length: int           # full text length (characters)
    final_text_preview: str          # first 200 chars of final_text
    tokens: dict[str, int]           # {primary_input, primary_output, ..., total}
    usd_cost_estimate: float         # provider pricing × token counts
    provider: str                    # "gemini" / "anthropic" / "openai" / "deepseek"
    error_code: str | None           # if anything errored


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_usd_cost(tokens: dict[str, int], provider: str) -> float:
    """Translate token counts to estimated USD cost using provider pricing.

    Parameters
    ----------
    tokens:
        Dict with any subset of:
        ``primary_input``, ``primary_output``, ``primary_cache_read``,
        ``evaluator`` (treated as input), ``retry_input``, ``retry_output``,
        ``total`` (ignored for cost — we sum components directly).
    provider:
        One of the keys in ``PROVIDER_PRICING_PER_1M``.  Unknown providers
        fall back to ``_DEFAULT_PROVIDER`` pricing.

    Returns
    -------
    float
        Estimated USD cost.  Non-negative.  May be 0.0 when all token counts
        are zero.
    """
    pricing = PROVIDER_PRICING_PER_1M.get(provider, PROVIDER_PRICING_PER_1M[_DEFAULT_PROVIDER])

    input_price      = pricing["input"]
    output_price     = pricing["output"]
    cache_read_price = pricing["cache_read"]

    # Component token counts (fall back to 0 when absent).
    primary_input      = max(0, tokens.get("primary_input", 0))
    primary_output     = max(0, tokens.get("primary_output", 0))
    primary_cache_read = max(0, tokens.get("primary_cache_read", 0))
    evaluator_input    = max(0, tokens.get("evaluator", 0))
    retry_input        = max(0, tokens.get("retry_input", 0))
    retry_output       = max(0, tokens.get("retry_output", 0))

    total_input      = primary_input + evaluator_input + retry_input
    total_output     = primary_output + retry_output
    total_cache_read = primary_cache_read

    cost = (
        total_input      * input_price      / 1_000_000
        + total_output   * output_price     / 1_000_000
        + total_cache_read * cache_read_price / 1_000_000
    )
    return round(cost, 8)


def write_audit_entry(entry: AuditEntry, log_dir: str | None = None) -> None:
    """Append a single audit entry to the day's NDJSON file.

    Parameters
    ----------
    entry:
        The ``AuditEntry`` to append.
    log_dir:
        Directory where log files are written.  Defaults to
        ``packages/fpl-grounded-assistant/audit_logs/``.  Relative paths are
        resolved relative to the current working directory.  The directory is
        auto-created if it does not exist.

    File naming
    -----------
    ``<log_dir>/<YYYY-MM-DD>.ndjson`` where the date is the UTC calendar date
    at the time of the call.  A new file is started automatically at UTC
    midnight.
    """
    target_dir = log_dir if log_dir is not None else _DEFAULT_LOG_DIR
    os.makedirs(target_dir, exist_ok=True)

    # UTC date for file rotation.
    utc_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    log_path = os.path.join(target_dir, f"{utc_date}.ndjson")

    # Serialise the frozen dataclass to a plain dict for JSON encoding.
    entry_dict: dict[str, Any] = {
        "timestamp":           entry.timestamp,
        "user_id":             entry.user_id,
        "tier":                entry.tier,
        "question":            entry.question,
        "branch":              entry.branch,
        "outcome":             entry.outcome,
        "intent":              entry.intent,
        "tool_calls":          entry.tool_calls,
        "evaluator_verdict":   entry.evaluator_verdict,
        "retry_attempted":     entry.retry_attempted,
        "final_text_length":   entry.final_text_length,
        "final_text_preview":  entry.final_text_preview,
        "tokens":              entry.tokens,
        "usd_cost_estimate":   entry.usd_cost_estimate,
        "provider":            entry.provider,
        "error_code":          entry.error_code,
    }

    line = json.dumps(entry_dict, ensure_ascii=False, separators=(",", ":"))

    with _write_lock:
        with open(log_path, mode="a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_audit_entry(
    *,
    user_id: str = "anonymous",
    tier: str = "free",
    question: str,
    branch: str,
    outcome: str,
    intent: str | None = None,
    tool_calls: list[dict] | None = None,
    evaluator_verdict: dict | None = None,
    retry_attempted: bool = False,
    final_text: str = "",
    tokens: dict[str, int] | None = None,
    provider: str = "gemini",
    error_code: str | None = None,
    timestamp: str | None = None,
) -> AuditEntry:
    """Convenience factory for building an AuditEntry from ask_v2() output.

    Fills in derived fields (final_text_length, final_text_preview,
    usd_cost_estimate, timestamp) so callers don't have to.
    """
    resolved_tokens = tokens or {}
    resolved_ts     = timestamp or _now_iso()
    preview         = final_text[:200]

    return AuditEntry(
        timestamp=resolved_ts,
        user_id=user_id,
        tier=tier,
        question=question,
        branch=branch,
        outcome=outcome,
        intent=intent,
        tool_calls=tool_calls or [],
        evaluator_verdict=evaluator_verdict,
        retry_attempted=retry_attempted,
        final_text_length=len(final_text),
        final_text_preview=preview,
        tokens=resolved_tokens,
        usd_cost_estimate=estimate_usd_cost(resolved_tokens, provider),
        provider=provider,
        error_code=error_code,
    )
