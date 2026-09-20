"""
fpl_grounded_assistant.audit
==============================
Phase P3.1: Append-only NDJSON audit log, one file per UTC day.

Public API
----------
write_audit_entry(entry, log_dir=None)  -> None
estimate_usd_cost(tokens, model, provider=None) -> float | None
tool_calls_from_ask_v2(result)          -> list[dict]   (i80: shared /ask + session projection)

Log format
----------
One JSON object per line, no extra whitespace, UTF-8, LF line endings.
File: ``<log_dir>/<YYYY-MM-DD>.ndjson`` (UTC date at write time).
``log_dir`` defaults to ``$AUDIT_LOG_DIR`` when that variable is set (i104:
absolute, or relative to ``packages/fpl-grounded-assistant``), else to
``packages/fpl-grounded-assistant/audit_logs``. Directory is auto-created if
absent. On Railway the container filesystem is ephemeral, so without a
volume mounted at ``AUDIT_LOG_DIR`` every deploy discards the log.

Replay
------
Each line is independently parseable:
    import json
    for line in open("audit_logs/2026-05-23.ndjson"):
        entry = json.loads(line)

USD cost estimation
-------------------
i105: priced per MODEL from the one shared table
(``model_pricing.PRICING_PER_1M_BY_MODEL``, the same one the measurement
scripts use). A model the table does not know -- or a turn whose model is
unknown -- gets ``usd_cost_estimate=None`` plus a warning, never a default
tariff: a cost computed from the wrong rate looks true and is wrong.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .model_pricing import PRICING_PER_1M_BY_MODEL, cost_usd

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Log directory
# ---------------------------------------------------------------------------

#: i104: env var naming the audit log directory. Absolute, or relative to the
#: package dir (``packages/fpl-grounded-assistant``). Unset -> ``audit_logs/``
#: under the package dir, exactly as before the variable existed.
AUDIT_LOG_DIR_ENV: str = "AUDIT_LOG_DIR"

_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_HERE)
_DEFAULT_LOG_DIR: str = os.path.join(_PACKAGE_DIR, "audit_logs")


def resolve_log_dir() -> str:
    """The directory ``write_audit_entry`` writes to when given no ``log_dir``.

    Read from the environment at call time (not import time) so a value set
    before the process starts and a value set in a test both take effect.
    """
    configured = os.environ.get(AUDIT_LOG_DIR_ENV, "").strip()
    if not configured:
        return _DEFAULT_LOG_DIR
    if os.path.isabs(configured):
        return configured
    return os.path.join(_PACKAGE_DIR, configured)

# File-write lock — prevents interleaved writes when multiple coroutines/threads
# write concurrently (shouldn't happen in production but safe-by-default).
_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# User-ID hashing (F5 remediation)
# ---------------------------------------------------------------------------

def hash_user_id(raw_id: str) -> str:
    """Hash a raw user_id for storage. Returns 'anonymous' unchanged.

    Uses SHA-256 truncated to 16 hex chars (8 bytes of entropy) — enough
    for uniqueness across plausible user populations, while preventing
    direct PII leakage if logs are exposed.

    Privacy vs anti-abuse tradeoff note: the quota counter also keys by user_id.
    If a user changes their X-User-Id (e.g. logs out), their hashed id changes
    and they get a fresh quota bucket.  This is a known trade-off: privacy
    (raw id never stored) vs perfect anti-abuse (id pinning).  Document if
    this becomes a concern.
    """
    if not raw_id or raw_id == "anonymous":
        return "anonymous"
    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    """One turn's audit record."""

    timestamp: str                   # ISO 8601 UTC, e.g. "2026-05-23T14:31:00.123456Z"
    user_id: str                     # hashed (sha256 first 16 hex chars), or "anonymous"
    tier: str                        # quota tier at time of turn
    question: str
    branch: str                      # "resource" / "prompt" / "orchestrator" / "unsupported"
    outcome: str                     # final outcome string
    intent: str | None
    tool_calls: list[dict]           # [{"name": str, "args": dict, "output_status": str,
                                     #   "round": int|None, "retry": bool (i96; orchestrator turns)}, ...]
    evaluator_verdict: dict | None   # {approved, grounded, complete, safe, retry_feedback} | None
    retry_attempted: bool
    final_text_length: int           # full text length (characters)
    final_text_preview: str          # first 200 chars of final_text
    tokens: dict[str, int]           # {primary_input, primary_output, ..., total}
    usd_cost_estimate: float | None  # model pricing × token counts; None = unpriced
    # i105: the provider and model the orchestrator ACTUALLY called this turn,
    # read off OrchestratorResult (provider label dispatched to
    # call_orch_provider; model the call was made with). None on a turn where
    # no LLM ran (deterministic branches, quota_exceeded, orchestrator
    # unreachable) -- never a presentation default such as DEFAULT_PROVIDER.
    provider: str | None             # "gemini" / "anthropic" / "openai" / None
    error_code: str | None           # if anything errored
    # i80: True only for a session turn that never went through ask_v2()
    # (orchestrator disabled / intent_hint legacy pipeline) -- tokens={} and
    # tool_calls=[] on such a line mean "not measured", not "measured zero".
    # False on every /ask line and on every orchestrated session turn.
    orchestration_absent: bool = False
    model: str | None = None         # e.g. "gpt-5.6-luna"; None when no LLM ran


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _token_components(tokens: dict[str, int]) -> tuple[int, int, int]:
    """(input, output, cache_read) summed across primary / evaluator / retry."""
    primary_input      = max(0, tokens.get("primary_input", 0))
    primary_output     = max(0, tokens.get("primary_output", 0))
    primary_cache_read = max(0, tokens.get("primary_cache_read", 0))
    evaluator_input    = max(0, tokens.get("evaluator", 0))   # treated as input
    retry_input        = max(0, tokens.get("retry_input", 0))
    retry_output       = max(0, tokens.get("retry_output", 0))
    return (
        primary_input + evaluator_input + retry_input,
        primary_output + retry_output,
        primary_cache_read,
    )


def estimate_usd_cost(
    tokens: dict[str, int],
    model: str | None,
    provider: str | None = None,
) -> float | None:
    """Translate token counts to estimated USD cost at *model*'s rate.

    Parameters
    ----------
    tokens:
        Dict with any subset of:
        ``primary_input``, ``primary_output``, ``primary_cache_read``,
        ``evaluator`` (treated as input), ``retry_input``, ``retry_output``,
        ``total`` (ignored for cost — we sum components directly).
    model:
        Model id, a key of ``model_pricing.PRICING_PER_1M_BY_MODEL``. ``None``
        when no LLM ran this turn.
    provider:
        Provider label; decides how the cached share is billed
        (``model_pricing.CACHE_READ_INCLUDED_IN_INPUT``).

    Returns
    -------
    float | None
        ``0.0`` when every token count is zero (nothing was bought, whatever
        the model). Otherwise the cost at *model*'s rate, or ``None`` -- with
        a warning -- when *model* is ``None`` or absent from the table.
        ``None`` means "unknown", not "free": a total that folds it in at 0.0
        or at another model's rate is a number that looks true and is wrong.
    """
    total_input, total_output, total_cache_read = _token_components(tokens)
    if total_input == 0 and total_output == 0 and total_cache_read == 0:
        return 0.0
    cost = cost_usd(
        total_input, total_output, total_cache_read,
        model=model, provider=provider,
    )
    if cost is None:
        _LOG.warning(
            "audit: no price for model=%r (provider=%r); %d tokens left unpriced "
            "(known models: %s)",
            model, provider, total_input + total_output + total_cache_read,
            ", ".join(sorted(PRICING_PER_1M_BY_MODEL)),
        )
        return None
    return round(cost, 8)


def write_audit_entry(entry: AuditEntry, log_dir: str | None = None) -> None:
    """Append a single audit entry to the day's NDJSON file.

    Parameters
    ----------
    entry:
        The ``AuditEntry`` to append.
    log_dir:
        Directory where log files are written.  Defaults to
        ``resolve_log_dir()``: ``$AUDIT_LOG_DIR`` when set (i104), else
        ``packages/fpl-grounded-assistant/audit_logs/``.  A relative
        ``log_dir`` argument is resolved against the current working
        directory.  The directory is auto-created if it does not exist.

    File naming
    -----------
    ``<log_dir>/<YYYY-MM-DD>.ndjson`` where the date is the UTC calendar date
    at the time of the call.  A new file is started automatically at UTC
    midnight.
    """
    target_dir = log_dir if log_dir is not None else resolve_log_dir()
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
        "model":               entry.model,
        "error_code":          entry.error_code,
        "orchestration_absent": entry.orchestration_absent,
    }

    line = json.dumps(entry_dict, ensure_ascii=False, separators=(",", ":"))

    with _write_lock:
        with open(log_path, mode="a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def tool_calls_from_ask_v2(result: dict[str, Any]) -> list[dict]:
    """Project an ``ask_v2()`` result dict to ``AuditEntry.tool_calls``.

    One derivation for both HTTP surfaces: ``POST /ask`` applies it to the
    dict it gets back from ``ask_v2()``, and the session path applies it to
    the SAME dict inside ``final_response._try_session_orchestration_response``
    (the only place that dict exists on a session turn) and carries the
    outcome on ``FinalResponse.orchestration``.

    i96: when the dict carries ``tool_calls_trace`` (both orchestrator
    branches of ``harness.ask_v2`` project it off
    ``OrchestratorResult.tool_calls_trace``: every executed call, primary
    rounds and the evaluator retry's own calls alike), the audit gets one
    entry per executed call with that call's real name / args / status.
    The ``selected_tool`` projection below is the fallback for dicts with no
    trace (the deterministic branches: router, resource, prompt, lookup),
    where the one selected tool IS the one call. Empty only when neither
    says a tool ran. Seen in prod 2026-09-13/17: a turn whose retry re-ran
    ``compare_players`` and got a non-ok status audited as ``tool_calls=[]``
    -- two executed calls reported as zero.
    """
    trace = result.get("tool_calls_trace")
    if trace:
        return [
            {
                "name":          str(_e.get("name") or ""),
                "args":          dict(_e.get("args") or {}),
                "output_status": str(_e.get("output_status") or "unknown"),
                "round":         _e.get("round"),
                "retry":         bool(_e.get("retry", False)),
            }
            for _e in trace
            if isinstance(_e, dict) and _e.get("name")
        ]
    selected_tool = result.get("selected_tool")
    if not selected_tool:
        return []
    return [{
        "name":          selected_tool,
        "args":          result.get("tool_input") or {},
        "output_status": (result.get("raw_output") or {}).get("status", "unknown"),
    }]


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
    provider: str | None = None,
    model: str | None = None,
    error_code: str | None = None,
    timestamp: str | None = None,
    orchestration_absent: bool = False,
) -> AuditEntry:
    """Convenience factory for building an AuditEntry from ask_v2() output.

    Fills in derived fields (final_text_length, final_text_preview,
    usd_cost_estimate, timestamp) so callers don't have to. ``provider`` and
    ``model`` default to ``None`` ("no LLM ran"), never to a provider name:
    a caller that has one passes it, a caller that doesn't must not invent it.
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
        usd_cost_estimate=estimate_usd_cost(resolved_tokens, model, provider),
        provider=provider,
        error_code=error_code,
        orchestration_absent=orchestration_absent,
        model=model,
    )
