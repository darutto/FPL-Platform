"""
fpl_server -- minimal HTTP entrypoint for the FPL grounded assistant.

Phase 4i: session hygiene and lifecycle hardening.
Phase 4l: classifier_client threaded through all endpoints.

Exposes one endpoint over HTTP that wraps ``respond()`` and returns a
``FinalResponse``-compatible JSON payload.  Bootstrap is assembled once
at startup via ``assemble_captain_context()``.

Endpoint
--------
POST /ask
    Request:  {"question": "...", "debug": false}
    Response: FinalResponse-compatible JSON (see AskResponse schema)

GET  /health
    Returns:  {"status": "ok"}

Start the server
----------------
    cd packages/fpl-grounded-assistant
    python -m uvicorn fpl_server:app --reload

or for a quick smoke test::

    python fpl_server.py   (binds 127.0.0.1:8000)

HTTP status codes
-----------------
200   Question was processed.  Inspect ``supported`` and ``outcome`` in the
      response body for intent classification -- the HTTP status code does
      NOT vary by intent result.  This means ambiguous / not_found /
      missing_arguments outcomes all return 200 with ``supported=True``,
      and unsupported_intent returns 200 with ``supported=False``.
422   Malformed request (missing / invalid ``question`` field).
503   Bootstrap not yet initialised (should not occur in normal operation).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# sys.path setup  (same pattern as fpl_repl.py / run_validation.py)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
_SIB  = lambda name: os.path.join(_PKGS, name)
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

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from fpl_grounded_assistant import respond
from fpl_grounded_assistant.player_form import _element_summary_guard  # Phase 2.6d.3 — guard stats
from fpl_pipeline import assemble_captain_context

# Phase P3.1: quota meter + audit log
from fpl_grounded_assistant.quota import (  # noqa: E402
    QuotaCheck,
    check_quota,
    record_turn as _record_turn,
    get_quota_status,
    reset_quota,
)
from fpl_grounded_assistant.audit import (  # noqa: E402
    AuditEntry,
    write_audit_entry,
    make_audit_entry,
    estimate_usd_cost,
    hash_user_id,
)
from fpl_grounded_assistant.dispatcher import OUTCOME_QUOTA_EXCEEDED  # noqa: E402
from fpl_grounded_assistant.orch_config import is_orch_enabled  # noqa: E402

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level bootstrap state
#
# The ``if _bootstrap is None`` guard in the lifespan means tests can
# pre-set this via ``_init_bootstrap()`` before creating a TestClient,
# bypassing the live network call entirely.
# ---------------------------------------------------------------------------

_bootstrap: dict[str, Any] | None = None


def _init_bootstrap(bs: dict[str, Any]) -> None:
    """Set the cached bootstrap.  Called by the lifespan at startup.

    Tests call this directly with ``STANDARD_BOOTSTRAP`` to skip the
    live ``assemble_captain_context()`` fetch.
    """
    global _bootstrap
    _bootstrap = bs


# ---------------------------------------------------------------------------
# Module-level classifier client state  (Phase 4l)
#
# Parallel to _bootstrap: tests inject a stub via _init_classifier_client().
# At container startup, _try_init_classifier_from_env() attempts to build
# a real client from ANTHROPIC_API_KEY.  Falls back to None (deterministic
# routing) when the key is absent, the anthropic package is not installed,
# or client construction raises.
# ---------------------------------------------------------------------------

_classifier_client: Any | None = None


def _init_classifier_client(client: Any | None) -> None:
    """Set the classifier client.  Called by the lifespan and by tests.

    Pass ``None`` to reset to deterministic-routing-only mode.
    The lifespan calls ``_try_init_classifier_from_env()`` which calls this
    when ``ANTHROPIC_API_KEY`` is set and the ``anthropic`` package is
    available.  Tests call this directly to inject a stub.
    """
    global _classifier_client
    _classifier_client = client


def _try_init_classifier_from_env() -> None:
    """Attempt to build a classifier client from environment variables.

    Respects ``DEFAULT_PROVIDER`` (default: ``"gemini"``).  Tries the active
    provider first; falls back silently when the key or package is absent.

    Deterministic routing remains the safe default when no client is built.
    """
    from fpl_grounded_assistant.intent_classifier import GeminiClassifierAdapter  # noqa: PLC0415

    provider = os.environ.get("DEFAULT_PROVIDER", "gemini").lower()

    if provider == "gemini":
        try:
            import warnings as _w  # noqa: PLC0415
            with _w.catch_warnings():
                _w.simplefilter("ignore")
                import google.generativeai as _genai  # type: ignore[import-untyped]  # noqa: PLC0415
            key = os.environ.get("GOOGLE_API_KEY")
            if key:
                _init_classifier_client(GeminiClassifierAdapter(_genai, key))
        except Exception:  # noqa: BLE001
            pass

    elif provider == "anthropic":
        try:
            import anthropic as _ant  # type: ignore[import-untyped]  # noqa: PLC0415
            key = os.environ.get("ANTHROPIC_API_KEY")
            if key:
                _init_classifier_client(_ant.Anthropic(api_key=key))
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# _SessionEntry dataclass
# ---------------------------------------------------------------------------

@dataclass
class _SessionEntry:
    """In-memory record for a single conversation session.

    Attributes
    ----------
    session:
        The ``ConversationSession`` instance that holds conversation state.
    created_at:
        ``time.time()`` at the moment this session was created.
    last_used_at:
        ``time.time()`` updated after every successful turn.  Drives TTL eviction.
    """

    session: Any       # ConversationSession — lazy-imported to avoid circular dep
    created_at: float
    last_used_at: float


# ---------------------------------------------------------------------------
# Session configuration
# ---------------------------------------------------------------------------

_SESSION_TTL_SECONDS: int = 1800   # idle timeout; 0 = no expiration
_SESSION_MAX_COUNT:   int = 100    # cap to prevent unbounded growth


# ---------------------------------------------------------------------------
# In-memory session registry
# ---------------------------------------------------------------------------

_sessions: dict[str, _SessionEntry] = {}


def _clear_sessions() -> None:
    """Clear all sessions.  Used by tests to reset state between suites."""
    _sessions.clear()


def _prune_expired_sessions() -> int:
    """Remove sessions idle longer than ``_SESSION_TTL_SECONDS``.

    Called lazily on ``POST /session`` before creating a new entry.
    A TTL of 0 disables expiration entirely.

    Returns
    -------
    int
        Number of sessions removed.
    """
    if _SESSION_TTL_SECONDS <= 0:
        return 0
    now = time.time()
    expired_ids = [
        sid for sid, entry in list(_sessions.items())
        if now - entry.last_used_at > _SESSION_TTL_SECONDS
    ]
    for sid in expired_ids:
        del _sessions[sid]
    return len(expired_ids)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    """Incoming question payload."""

    question: str
    debug: bool = False
    candidates_list: list[dict[str, Any]] | None = None  # Phase 5p
    squad_context: dict[str, Any] | None = None          # Phase 8e1: optional per-turn squad state
    intent_hint: str | None = None                       # V2: optional slash-command routing bias


class AskResponse(BaseModel):
    """FinalResponse-compatible JSON response.

    Field names and semantics mirror ``FinalResponse`` exactly.
    ``debug`` is only populated when ``AskRequest.debug=True``.
    ``comparison`` is populated for compare_players OK turns (Phase 5g).
    ``captain`` is populated for captain_score OK turns (Phase 5n).
    ``sub_responses`` is populated for multi_intent turns (Phase 6c/6d).
    Each sub-response dict includes structured metadata (captain, comparison,
    captain_ranking, transfer) when the sub-intent produces it (Phase 6d/7a).
    ``transfer`` is populated for transfer_advice OK turns (Phase 7a).
    ``chip`` is populated for chip_advice OK turns (Phase 7b).
    ``fixture_run`` is populated for player_fixture_run OK turns (Phase 7h).
    ``differential`` is populated for differential_picks OK turns (Phase 7g).
    """

    final_text: str
    outcome: str
    supported: bool
    intent: str
    review_passed: bool
    llm_used: bool
    debug: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None              # Phase 5g
    captain: dict[str, Any] | None = None                 # Phase 5n
    captain_ranking: list[dict[str, Any]] | None = None   # Phase 5p
    sub_responses: list[dict[str, Any]] | None = None     # Phase 6c
    transfer: dict[str, Any] | None = None                # Phase 7a
    chip: dict[str, Any] | None = None                    # Phase 7b
    fixture_run: dict[str, Any] | None = None             # Phase 7h
    differential: dict[str, Any] | None = None            # Phase 7g
    orch_outcome: str | None = None                        # Orch-4c: audit
    degraded: bool = False                                 # Phase 2.6b: provider failed silently
    player_form: dict[str, Any] | None = None              # Phase 2.6d
    injury_list: dict[str, Any] | None = None              # Phase 2.6d
    price_changes: dict[str, Any] | None = None            # Phase 2.6d
    team_calendar: dict[str, Any] | None = None            # Phase 2.6e
    team_schedule: dict[str, Any] | None = None            # Phase 2.6e.3
    position_fixture_run: dict[str, Any] | None = None    # Phase 2.6e.4
    transfer_suggestion:  dict[str, Any] | None = None    # Phase 2.6h
    # Phase A1 (post-graduation): full ResourceListResult dict for @resource turns; null for all other intents.
    resource_rows:        dict[str, Any] | None = None
    # Phase 2.7d: routing audit fields
    route_source:          str | None   = None             # which routing stage decided
    classifier_confidence: float | None = None             # LLM classifier confidence when attempted
    route_conflict:        bool         = False            # True when deterministic and LLM disagree
    # Phase 2.7f: clarification policy layer
    clarification_asked:   bool         = False            # True when outcome==needs_clarification


class CreateSessionResponse(BaseModel):
    """Response from POST /session."""

    session_id: str
    created_at: float
    expires_after_seconds: int


class SessionAskResponse(BaseModel):
    """Response from POST /session/{session_id}/ask.

    Extends AskResponse shape with session_id and optional rewritten_question.
    rewritten_question is only populated when debug=True and the resolver
    actually rewrote the question.
    comparison is populated for compare_players OK turns (Phase 5g).
    captain is populated for captain_score OK turns (Phase 5n).
    sub_responses is populated for multi_intent turns (Phase 6c).
    transfer is populated for transfer_advice OK turns (Phase 7a).
    chip is populated for chip_advice OK turns (Phase 7b).
    fixture_run is populated for player_fixture_run OK turns (Phase 7h).
    differential is populated for differential_picks OK turns (Phase 7g).
    """

    session_id: str
    final_text: str
    outcome: str
    supported: bool
    intent: str
    review_passed: bool
    llm_used: bool
    rewritten_question: str | None = None
    debug: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None              # Phase 5g
    captain: dict[str, Any] | None = None                 # Phase 5n
    captain_ranking: list[dict[str, Any]] | None = None   # Phase 5p
    sub_responses: list[dict[str, Any]] | None = None     # Phase 6c
    transfer: dict[str, Any] | None = None                # Phase 7a
    chip: dict[str, Any] | None = None                    # Phase 7b
    fixture_run: dict[str, Any] | None = None             # Phase 7h
    differential: dict[str, Any] | None = None            # Phase 7g
    orch_outcome: str | None = None                        # Orch-4c: audit
    degraded: bool = False                                 # Phase 2.6b: provider failed silently
    player_form: dict[str, Any] | None = None              # Phase 2.6d
    injury_list: dict[str, Any] | None = None              # Phase 2.6d
    price_changes: dict[str, Any] | None = None            # Phase 2.6d
    team_calendar: dict[str, Any] | None = None            # Phase 2.6e
    team_schedule: dict[str, Any] | None = None            # Phase 2.6e.3
    position_fixture_run: dict[str, Any] | None = None    # Phase 2.6e.4
    transfer_suggestion:  dict[str, Any] | None = None    # Phase 2.6h
    # Phase A1 (post-graduation): full ResourceListResult dict for @resource turns; null for all other intents.
    resource_rows:        dict[str, Any] | None = None
    # Phase 2.7d: routing audit fields
    route_source:          str | None   = None             # which routing stage decided
    classifier_confidence: float | None = None             # LLM classifier confidence when attempted
    route_conflict:        bool         = False            # True when deterministic and LLM disagree
    # Phase 2.7f: clarification policy layer
    clarification_asked:   bool         = False            # True when outcome==needs_clarification


class ClearSessionResponse(BaseModel):
    """Response from DELETE /session/{session_id}."""

    status: str    # always "cleared"
    session_id: str


class SessionInfoResponse(BaseModel):
    """Response from GET /session/{session_id}.

    Phase 5l additions (all optional; None when no turns completed yet):
    last_intent           -- intent of the most recent turn
    last_player           -- last successfully resolved single-player query
    last_comparison       -- {"player_a": ..., "player_b": ...} from last comparison, or None
    last_resolver_source  -- resolver path from most recent turn (same vocab as ResolverDebug)
    Phase 7f additions:
    last_transfer         -- {"player_out": ..., "player_in": ...} from last transfer, or None
    Phase 8d-i additions:
    last_fixture_run_player -- player query from last fixture run turn, or None
    Phase 8d-ii additions:
    last_differential       -- True when last successful turn was differential picks
    """

    session_id: str
    created_at: float
    last_used_at: float
    turn_count: int
    last_intent: str | None = None                      # Phase 5l
    last_player: str | None = None                      # Phase 5l
    last_comparison: dict[str, Any] | None = None       # Phase 5l
    last_resolver_source: str | None = None             # Phase 5l
    last_transfer: dict[str, Any] | None = None         # Phase 7f
    last_fixture_run_player: str | None = None          # Phase 8d-i
    last_differential: bool = False                     # Phase 8d-ii


# ---------------------------------------------------------------------------
# Owned-store fallback imports (deferred-safe per CONTRACT §11.3)
# If Agent A's module is not yet present, the names resolve to None and the
# fallback is simply disabled — no import-time failure.
# ---------------------------------------------------------------------------
try:
    from fpl_grounded_assistant.owned_store_fallback import (  # noqa: E402
        load_bootstrap_from_owned_store,
        OwnedStoreUnavailable,
        OwnedStoreProvenance,
    )
except ImportError:  # fallback module unavailable — owned-store fallback disabled
    load_bootstrap_from_owned_store = None  # type: ignore[assignment]
    OwnedStoreUnavailable = None            # type: ignore[assignment,misc]
    OwnedStoreProvenance = None             # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Bootstrap retry policy
# ---------------------------------------------------------------------------

#: Total attempts for the FPL bootstrap fetch at startup (1 initial + N retries).
_BOOTSTRAP_MAX_ATTEMPTS: int = 4

#: Seconds to wait between consecutive attempts.
#: Increasing delays give the FPL API time to recover from a transient outage.
_BOOTSTRAP_RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 10.0)

#: Records the OwnedStoreProvenance from the most recent fallback-served bootstrap,
#: or None when the last successful fetch came from the live FPL API.
#: Read by /healthz; mutated only inside _fetch_bootstrap_with_retry().
_LAST_BOOTSTRAP_PROVENANCE: "OwnedStoreProvenance | None" = None


def _fetch_bootstrap_with_retry(
    _sleep_fn: Any = None,
) -> "dict[str, Any] | None":
    """Fetch the FPL bootstrap with bounded retries and structured logging.

    Makes up to ``_BOOTSTRAP_MAX_ATTEMPTS`` calls to
    ``assemble_captain_context()``.  Between attempts it sleeps for the
    corresponding delay in ``_BOOTSTRAP_RETRY_DELAYS``.

    After all live retries exhaust, attempts the owned-store fallback exactly
    once (CONTRACT §11.3).  On fallback success the module-level
    ``_LAST_BOOTSTRAP_PROVENANCE`` is set and a WARNING is emitted.  On
    ``OwnedStoreUnavailable`` the original live-fetch exception is re-raised
    (CONTRACT §11.3 resolution #2).  When a subsequent live fetch succeeds
    ``_LAST_BOOTSTRAP_PROVENANCE`` is cleared to None (CONTRACT §11.3.5).

    Parameters
    ----------
    _sleep_fn:
        Callable used for inter-retry sleep.  Defaults to ``time.sleep``.
        Inject a no-op (``lambda _: None``) in tests to avoid real waits.

    Returns
    -------
    dict[str, Any] | None
        The raw bootstrap dict (value of ``ctx["bootstrap"]``) on success,
        or ``None`` if every attempt raises.  Caller is responsible for
        calling ``_init_bootstrap()`` on a non-None return.
    """
    global _LAST_BOOTSTRAP_PROVENANCE

    sleep = _sleep_fn if _sleep_fn is not None else time.sleep
    last_exc: Exception | None = None

    for attempt in range(1, _BOOTSTRAP_MAX_ATTEMPTS + 1):
        try:
            ctx = assemble_captain_context()
            _LOG.info(
                "fpl_startup %s",
                json.dumps({
                    "event":   "bootstrap_success",
                    "attempt": attempt,
                }),
            )
            # Live fetch succeeded — clear any stale fallback provenance
            # (CONTRACT §11.3.5: slot must not lie about staleness).
            _LAST_BOOTSTRAP_PROVENANCE = None
            return ctx["bootstrap"]
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _LOG.warning(
                "fpl_startup %s",
                json.dumps({
                    "event":        "bootstrap_attempt_failed",
                    "attempt":      attempt,
                    "max_attempts": _BOOTSTRAP_MAX_ATTEMPTS,
                    "error":        type(exc).__name__,
                }),
            )
            if attempt < _BOOTSTRAP_MAX_ATTEMPTS:
                sleep(_BOOTSTRAP_RETRY_DELAYS[attempt - 1])

    _LOG.error(
        "fpl_startup %s",
        json.dumps({
            "event":    "bootstrap_exhausted",
            "attempts": _BOOTSTRAP_MAX_ATTEMPTS,
            "error":    type(last_exc).__name__ if last_exc else "unknown",
        }),
    )

    # ------------------------------------------------------------------
    # Owned-store fallback (CONTRACT §11.3): attempted exactly once after
    # all live retries have exhausted.  Disabled when the module is absent.
    # ------------------------------------------------------------------
    if load_bootstrap_from_owned_store is not None:
        try:
            bs_fallback, provenance = load_bootstrap_from_owned_store()
            _LAST_BOOTSTRAP_PROVENANCE = provenance
            _LOG.warning(
                "fpl_startup %s",
                json.dumps({
                    "event":             "bootstrap_owned_store_fallback",
                    "season":            provenance.merged_at.split("T")[0] if provenance.merged_at else None,
                    "merged_at":         provenance.merged_at,
                    "staleness_hours":   provenance.staleness_hours,
                    "incremental_count": provenance.incremental_count,
                }),
            )
            return bs_fallback
        except Exception as fallback_exc:  # noqa: BLE001
            # Distinguish OwnedStoreUnavailable from unexpected errors;
            # either way we log at ERROR and re-raise the original live exc
            # (CONTRACT §11.3 resolution #2: live failure is the root cause).
            if OwnedStoreUnavailable is not None and isinstance(fallback_exc, OwnedStoreUnavailable):
                _LOG.error(
                    "fpl_startup %s",
                    json.dumps({
                        "event": "bootstrap_owned_store_unavailable",
                        "error": str(fallback_exc),
                    }),
                )
            else:
                _LOG.error(
                    "fpl_startup %s",
                    json.dumps({
                        "event": "bootstrap_owned_store_error",
                        "error": str(fallback_exc),
                    }),
                )
            # Re-raise the LIVE failure, not the fallback exception
            # (CONTRACT §11.3 resolution #2).
            if last_exc is not None:
                raise last_exc  # noqa: TRY301
            return None

    return None


# ---------------------------------------------------------------------------
# Application + lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Assemble live bootstrap and optional classifier client at startup.

    Bootstrap is skipped if already set (test injection path).
    On a live start the bootstrap is fetched with bounded retries; if all
    attempts fail the server starts in a degraded state and /ask returns 503
    until the bootstrap is populated externally (no manual restart required).
    """
    if _bootstrap is None:
        bs = _fetch_bootstrap_with_retry()
        if bs is not None:
            _init_bootstrap(bs)
    if _classifier_client is None:
        _try_init_classifier_from_env()
    if not os.environ.get("FPL_INTERNAL_TOKEN", "").strip():
        _LOG.warning(
            "FPL_INTERNAL_TOKEN not set — GET /quota is open to unauthenticated callers. "
            "Set this in production to restrict quota probing."
        )
    yield


app = FastAPI(
    title="FPL Grounded Assistant",
    description=(
        "Thin HTTP wrapper around respond().  "
        "Routing and scoring are deterministic; LLM presentation is optional."
    ),
    version="4i",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Serialisation helpers  (Phase 5n)
# ---------------------------------------------------------------------------

def _captain_meta_dict(captain: Any) -> dict[str, Any]:
    """Serialise a ``CaptainScoreMeta`` instance to a JSON-safe dict."""
    return {
        "web_name":        captain.web_name,
        "team_short":      captain.team_short,
        "captain_score":   captain.captain_score,
        "tier":            captain.tier,
        "role_bonus":      captain.role_bonus,
        "set_piece_notes": list(captain.set_piece_notes),
    }


def _captain_ranking_list(captain_ranking: Any) -> list[dict[str, Any]]:
    """Serialise a ``tuple[RankedCaptainEntry, ...]`` to a JSON-safe list."""
    return [
        {
            "rank":            entry.rank,
            "web_name":        entry.web_name,
            "team_short":      entry.team_short,
            "captain_score":   entry.captain_score,
            "tier":            entry.tier,
            "role_bonus":      entry.role_bonus,
            "set_piece_notes": list(entry.set_piece_notes),
        }
        for entry in captain_ranking
    ]


def _player_ctx_dict(ctx: Any) -> dict[str, Any] | None:
    """Serialise a ``ComparisonPlayerContext`` to a JSON-safe dict, or None."""
    if ctx is None:
        return None
    return {
        "web_name":        ctx.web_name,
        "position":        ctx.position,
        "captain_score":   ctx.captain_score,
        "position_score":  ctx.position_score,   # Phase 8a1 Layer 2
        "is_home":         ctx.is_home,           # Phase 8b
        "effective_fdr":   ctx.effective_fdr,     # Phase 8b
        "role_bonus":      ctx.role_bonus,
        "set_piece_notes": list(ctx.set_piece_notes),
    }


def _comparison_dict(comparison: Any) -> dict[str, Any]:
    """Serialise a ``ComparisonMeta`` instance to a JSON-safe dict."""
    return {
        "winner":   comparison.winner,
        "margin":   comparison.margin,
        "label":    comparison.label,
        "reasons":  list(comparison.reasons),
        "player_a": _player_ctx_dict(comparison.player_a),
        "player_b": _player_ctx_dict(comparison.player_b),
    }


def _transfer_meta_dict(transfer: Any) -> dict[str, Any]:
    """Serialise a ``TransferMeta`` instance to a JSON-safe dict."""
    return {
        "player_out":        transfer.player_out,
        "player_in":         transfer.player_in,
        "recommendation":    transfer.recommendation,
        "score_delta":       transfer.score_delta,
        "price_delta":       transfer.price_delta,
        "reasons":           list(transfer.reasons),
        "budget_constraint": transfer.budget_constraint,  # Phase 8e1
        "hit_warning":       transfer.hit_warning,        # Phase 8e2
    }


def _chip_meta_dict(chip: Any) -> dict[str, Any]:
    """Serialise a ``ChipAdviceMeta`` instance to a JSON-safe dict."""
    return {
        "chip":             chip.chip,
        "recommendation":   chip.recommendation,
        "gw":               chip.gw,
        "signal_value":     chip.signal_value,
        "signal_label":     chip.signal_label,
        "chip_unavailable": chip.chip_unavailable,  # Phase 8e1
    }


def _differential_meta_dict(differential: Any) -> dict[str, Any]:
    """Serialise a ``DifferentialPicksMeta`` instance to a JSON-safe dict.  Phase 7g."""
    return {
        "ownership_threshold": differential.ownership_threshold,
        "top_n":               differential.top_n,
        "picks": [
            {
                "rank":          p.rank,
                "web_name":      p.web_name,
                "team_short":    p.team_short,
                "position":      p.position,
                "captain_score": p.captain_score,
                "ownership":     p.ownership,
                "now_cost":      p.now_cost,
                "is_home":       p.is_home,
            }
            for p in differential.picks
        ],
    }


def _player_form_meta_dict(pf: Any) -> dict[str, Any]:
    """Serialise a ``PlayerFormMeta`` instance to a JSON-safe dict.  Phase 2.6d."""
    return {
        "web_name":   pf.web_name,
        "team_short": pf.team_short,
        "position":   pf.position,
        "n_games":    pf.n_games,
        "history": [
            {
                "gameweek":     e.gameweek,
                "minutes":      e.minutes,
                "goals_scored": e.goals_scored,
                "assists":      e.assists,
                "bonus":        e.bonus,
                "total_points": e.total_points,
            }
            for e in pf.history
        ],
    }


def _injury_list_meta_dict(il: Any) -> dict[str, Any]:
    """Serialise an ``InjuryListMeta`` instance to a JSON-safe dict.  Phase 2.6d."""
    def _entries(lst: Any) -> list[dict]:
        return [
            {
                "web_name":          e.web_name,
                "team_short":        e.team_short,
                "position":          e.position,
                "status_label":      e.status_label,
                "chance_of_playing": e.chance_of_playing,
            }
            for e in lst
        ]
    return {
        "injured":  _entries(il.injured),
        "doubtful": _entries(il.doubtful),
        "other":    _entries(il.other),
        "total":    il.total,
    }


def _price_changes_meta_dict(pc: Any) -> dict[str, Any]:
    """Serialise a ``PriceChangesMeta`` instance to a JSON-safe dict.  Phase 2.6d."""
    def _entries(lst: Any) -> list[dict]:
        return [
            {
                "web_name":          e.web_name,
                "team_short":        e.team_short,
                "position":          e.position,
                "now_cost":          e.now_cost,
                "now_cost_m":        e.now_cost_m,
                "cost_change_event": e.cost_change_event,
                "cost_change_start": e.cost_change_start,
            }
            for e in lst
        ]
    return {
        "risers":  _entries(pc.risers),
        "fallers": _entries(pc.fallers),
    }


def _team_calendar_meta_dict(tc: Any) -> dict[str, Any]:
    """Serialise a ``TeamFixtureCalendarMeta`` instance.  Phase 2.6e."""
    return {
        "mode":             tc.mode,
        "horizon":          tc.horizon,
        "current_gameweek": tc.current_gameweek,
        "top_n":            tc.top_n,
        "teams": [
            {
                "rank":           t.rank,
                "team_short":     t.team_short,
                "team_name":      t.team_name,
                "fixture_count":  t.fixture_count,
                "avg_fdr":        t.avg_fdr,
                "total_fdr":      t.total_fdr,
                "fixtures": [
                    {
                        "gameweek":       fx.gameweek,
                        "opponent_short": fx.opponent_short,
                        "is_home":        fx.is_home,
                        "difficulty":     fx.difficulty,
                    }
                    for fx in t.fixtures
                ],
                # Phase 2.6e.2: DGW/BGW labels
                "has_dgw":        t.has_dgw,
                "has_bgw":        t.has_bgw,
                "dgw_gameweeks":  list(t.dgw_gameweeks),
                "bgw_gameweeks":  list(t.bgw_gameweeks),
            }
            for t in tc.teams
        ],
    }


def _transfer_suggestion_meta_dict(ts: Any) -> dict[str, Any]:
    """Serialise a TransferSuggestionMeta instance.  Phase 2.6h/2.6i."""
    return {
        "position":         ts.position,
        "position_label":   ts.position_label,
        "team_short":       ts.team_short,    # Phase 2.6i
        "team_name":        ts.team_name,     # Phase 2.6i
        "max_price":        ts.max_price,
        "horizon":          ts.horizon,
        "top_n":            ts.top_n,
        "picks": [
            {
                "rank":             p.rank,
                "web_name":         p.web_name,
                "team_short":       p.team_short,
                "position":         p.position,
                "now_cost":         p.now_cost,
                "now_cost_m":       p.now_cost_m,
                "form":             p.form,
                "avg_fdr":          p.avg_fdr,
                "difficulty_label": p.difficulty_label,
                "composite_score":  p.composite_score,
                "ownership":        p.ownership,
            }
            for p in ts.picks
        ],
    }


def _position_fixture_run_meta_dict(pf: Any) -> dict[str, Any]:
    """Serialise a PositionFixtureRunMeta instance.  Phase 2.6e.4."""
    return {
        "position":         pf.position,
        "position_label":   pf.position_label,
        "mode":             pf.mode,
        "horizon":          pf.horizon,
        "current_gameweek": pf.current_gameweek,
        "top_n":            pf.top_n,
        "teams": [
            {
                "rank":           t.rank,
                "team_short":     t.team_short,
                "team_name":      t.team_name,
                "fixture_count":  t.fixture_count,
                "avg_fdr":        t.avg_fdr,
                "total_fdr":      t.total_fdr,
                "fixtures": [
                    {"gameweek": fx.gameweek, "opponent_short": fx.opponent_short,
                     "is_home": fx.is_home, "difficulty": fx.difficulty}
                    for fx in t.fixtures
                ],
                "has_dgw":       t.has_dgw,
                "has_bgw":       t.has_bgw,
                "dgw_gameweeks": list(t.dgw_gameweeks),
                "bgw_gameweeks": list(t.bgw_gameweeks),
            }
            for t in pf.teams
        ],
    }


def _team_schedule_meta_dict(ts: Any) -> dict[str, Any]:
    """Serialise a ``TeamScheduleMeta`` instance.  Phase 2.6e.3."""
    return {
        "team_short":       ts.team_short,
        "team_name":        ts.team_name,
        "horizon":          ts.horizon,
        "current_gameweek": ts.current_gameweek,
        "fixture_count":    ts.fixture_count,
        "avg_fdr":          ts.avg_fdr,
        "total_fdr":        ts.total_fdr,
        "fixtures": [
            {
                "gameweek":       fx.gameweek,
                "opponent_short": fx.opponent_short,
                "is_home":        fx.is_home,
                "difficulty":     fx.difficulty,
            }
            for fx in ts.fixtures
        ],
        "has_dgw":       ts.has_dgw,
        "has_bgw":       ts.has_bgw,
        "dgw_gameweeks": list(ts.dgw_gameweeks),
        "bgw_gameweeks": list(ts.bgw_gameweeks),
    }


def _fixture_run_meta_dict(fixture_run: Any) -> dict[str, Any]:
    """Serialise a ``FixtureRunMeta`` instance to a JSON-safe dict.  Phase 7h."""
    ctx = fixture_run.team_fdr_context
    return {
        "web_name":         fixture_run.web_name,
        "team_short":       fixture_run.team_short,
        "position":         fixture_run.position,
        "horizon":          fixture_run.horizon,
        "current_gameweek": fixture_run.current_gameweek,
        "fixtures": [
            {
                "gameweek":       fx.gameweek,
                "opponent_short": fx.opponent_short,
                "is_home":        fx.is_home,
                "difficulty":     fx.difficulty,
            }
            for fx in fixture_run.fixtures
        ],
        # Phase 2.6f: team FDR context enrichment
        "team_fdr_context": {
            "avg_fdr":          ctx.avg_fdr,
            "difficulty_label": ctx.difficulty_label,
            "gw_from":          ctx.gw_from,
            "gw_to":            ctx.gw_to,
        } if ctx is not None else None,
    }


def _sub_response_dict(sr: Any) -> dict[str, Any]:
    """Serialise a sub-response ``FinalResponse`` to a bounded JSON-safe dict.

    Includes structured metadata (captain, comparison, captain_ranking,
    transfer) when present on the sub-response, mirroring top-level response
    serialisation.  Debug bundles are always excluded from sub-responses.

    Phase 6d addition.  Phase 7a: transfer metadata added.
    Phase 7b: chip metadata added.
    """
    d: dict[str, Any] = {
        "final_text": sr.final_text,
        "outcome":    sr.outcome,
        "supported":  sr.supported,
        "intent":     sr.intent,
    }
    if sr.comparison is not None:
        d["comparison"] = _comparison_dict(sr.comparison)
    if sr.captain is not None:
        d["captain"] = _captain_meta_dict(sr.captain)
    if sr.captain_ranking is not None:
        d["captain_ranking"] = _captain_ranking_list(sr.captain_ranking)
    if sr.transfer is not None:
        d["transfer"] = _transfer_meta_dict(sr.transfer)
    if sr.chip is not None:
        d["chip"] = _chip_meta_dict(sr.chip)
    if sr.fixture_run is not None:                         # Phase 7h
        d["fixture_run"] = _fixture_run_meta_dict(sr.fixture_run)
    if sr.differential is not None:                        # Phase 7g
        d["differential"] = _differential_meta_dict(sr.differential)
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check.  Always returns 200 while the process is running.
    Does NOT reflect bootstrap readiness — use /ready for that."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    """Readiness check.  Returns 200 only when the bootstrap is loaded.

    Use this endpoint for deployment readiness probes (Kubernetes, Railway,
    Docker HEALTHCHECK) so traffic is not routed until data is available.
    Returns 503 while the bootstrap is still loading or if all startup
    attempts failed.
    """
    if _bootstrap is None:
        raise HTTPException(status_code=503, detail="Bootstrap not ready")
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    """Internal observability endpoint for operator tooling.

    Returns runtime metrics for the element-summary circuit guard and
    Phase 2.7g routing telemetry counters.  All values are read-only and
    thread-safe.

    Response shape — circuit guard
    --------------------------------
    ``element_summary_guard.state``
        ``"open"``   — circuit is open; player-form calls are fast-failing.
        ``"closed"`` — circuit is closed; calls reach the upstream API.
    ``element_summary_guard.timeout_open_events``
        Cumulative count of timeouts that opened the circuit since startup
        (or last ``_reset()``).
    ``element_summary_guard.fast_fail_events``
        Cumulative count of player-form calls that short-circuited without
        hitting the upstream API.
    ``element_summary_guard.successful_recoveries``
        Cumulative count of successful upstream calls that followed a
        guard-open cycle.

    Response shape — routing telemetry  (Phase 2.7g)
    --------------------------------------------------
    ``routing.route_source_counts``
        Counts per routing stage (``"deterministic"``, ``"llm_classifier_high"``,
        ``"llm_classifier_medium"``, ``"none"``, etc.).
    ``routing.outcome_counts``
        Counts per OUTCOME_* constant (``"ok"``, ``"needs_clarification"``,
        ``"unsupported_intent"``, etc.).
    ``routing.classifier_confidence_bucket_counts``
        Counts per confidence bucket (``"high"``, ``"medium"``, ``"low"``,
        ``"none"``).
    ``routing.clarification_asked_total``
        Cumulative count of turns where the medium-confidence gate fired and
        a clarification prompt was returned.
    ``routing.intent_route_counts``
        Counts keyed by ``"intent|route_source"`` composite string.

    This endpoint is NOT a stable contract — field names may change across
    platform versions.  Do not use it for deployment probes; use ``/ready``
    instead.
    """
    from fpl_grounded_assistant.telemetry import get_snapshot as _get_telemetry_snapshot  # noqa: PLC0415
    from fpl_grounded_assistant.provider_client import check_provider_health  # noqa: PLC0415
    stats = _element_summary_guard.get_stats()
    return {
        "element_summary_guard": {
            "state": "open" if _element_summary_guard.is_open() else "closed",
            **stats,
        },
        "routing": _get_telemetry_snapshot(),
        # Phase 2.5-smoke: provider availability (credential+SDK check, no network I/O)
        "provider": check_provider_health(),
    }


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Phase M5 (MCP_architecture): decision-tree telemetry and graduation status.

    Returns per-branch routing counters and the graduation-criteria evaluation
    derived from ask_v2() traffic observed since process startup.  Counters are process-global and cumulative; they reset
    only on process restart (or via telemetry.reset() in tests).

    This endpoint is the primary operational surface for answering the three
    go/no-go questions for graduating the MCP_architecture branch to main:

    1. Which branch fired?  — ``routing_counters`` sub-dict, keyed by branch.
    2. Why?                 — ``graduation.deterministic_share`` vs
                              ``graduation.orchestrator_grounded_share`` and
                              ``graduation.reject_rate`` show the split.
    3. How often?           — ``routing_counters.total_primary`` is the total
                              number of distinct requests observed.

    Response shape
    --------------
    ::

        {
          "routing_counters": {
            "resource":               int,   # @resource branch hits
            "prompt":                 int,   # /prompt branch hits (expansion + dispatch + clarif)
            "route":                  int,   # deterministic route() hits (plain text)
            "classifier_rewrite":     int,   # LLM rewrite -> route() hits
            "orchestrator":           int,   # orchestrator grounded (primary branch)
            "unsupported":            int,   # inputs with no grounded answer
            "orchestrator_attempted": int,   # all orchestrator invocations (R5 split)
            "orchestrator_grounded":  int,   # orch invocations that produced a grounded answer
            "total_primary":          int,   # resource+prompt+route+classifier_rewrite
                                            #   +orchestrator+unsupported
            "reject_rate":            float, # unsupported / total_primary
          },
          "graduation": {
            "deterministic_share":       float,  # (resource+prompt+route+classifier_rewrite)
                                                 #   / total_primary. Target: >= 0.80
            "orchestrator_grounded_share": float, # orchestrator_grounded / total_primary.
                                                  # Informational only — not a gating criterion.
            "reject_rate":               float,  # unsupported / total_primary. Target: < 0.05
            "criteria": {
              "deterministic_share_ge_80": bool,  # deterministic_share >= 0.80
              "reject_rate_lt_5":          bool,  # reject_rate < 0.05
            },
            "ready_to_graduate":         bool,   # all criteria True AND total > 0
            "total_observations":        int,
          }
        }

    Counter semantics
    -----------------
    ``orchestrator_attempted`` counts every call to the orchestrator loop
    regardless of whether it grounded.  ``orchestrator_grounded`` is the
    subset that produced a usable tool-grounded answer.  The difference
    ``orchestrator_attempted - orchestrator_grounded`` is the orchestrator
    fail-to-ground rate (finding R5 from the M3 Adversarial Review).

    ``classifier_rewrite`` counts as deterministic share for graduation
    purposes: the LLM rewrites the question to a canonical form that
    re-enters route().  The downstream tool is still a deterministic function.

    Graduation gate
    ---------------
    ``ready_to_graduate`` is True iff:
    - ``deterministic_share`` >= 0.80  (resource+prompt+route+rewrite dominate)
    - ``reject_rate`` < 0.05           (fewer than 5% of inputs fully unsupported)
    - ``total_observations`` > 0       (the system has actually been exercised)

    This endpoint is NOT a deployment readiness probe; use ``GET /ready``
    for that.  These counters are reset on every process restart.
    """
    from fpl_grounded_assistant.telemetry import snapshot as _snap, graduation_status as _grad  # noqa: PLC0415
    snap = _snap()

    # CONTRACT §11.4: expose owned-store fallback provenance; exclude pointer_path
    # (lead resolution #4 — don't leak filesystem layout to external consumers).
    if _LAST_BOOTSTRAP_PROVENANCE is None:
        owned_store_fallback_info = None
    else:
        _prov = _LAST_BOOTSTRAP_PROVENANCE
        owned_store_fallback_info = {
            "merged_at":             _prov.merged_at,
            "baseline_captured_at":  _prov.baseline_captured_at,
            "incremental_count":     _prov.incremental_count,
            "staleness_hours":       _prov.staleness_hours,
            "row_counts":            _prov.row_counts,
        }

    return {
        "routing_counters":    snap,
        "graduation":          _grad(snap),
        "owned_store_fallback": owned_store_fallback_info,
    }


@app.get("/resources")
def list_resources() -> dict[str, Any]:
    """Phase M1 (MCP_architecture): list registered @resources.

    Returns introspection metadata for the six M1 resources. The endpoint
    is read-only, argument-free, and does not consult the bootstrap —
    it reports the static registry only.
    """
    from fpl_grounded_assistant.resource_registry import list_resource_specs  # noqa: PLC0415
    specs = list_resource_specs()
    return {
        "resources": [
            {
                "name":        s.name,
                "title":       s.title,
                "description": s.description,
                "columns":     list(s.columns),
            }
            for s in specs
        ],
        "count": len(specs),
    }


@app.get("/quota")
def quota_status(
    request: Request,
    user_id: str = "anonymous",
    tier: str = "free",
) -> dict[str, Any]:
    """Phase P3.1: Return current quota status for a user.

    Used by the UI quota indicator (P3.2) and for operator inspection.

    Query parameters
    ----------------
    user_id : str, optional
        Opaque user identifier.  Defaults to ``"anonymous"``.
    tier : str, optional
        Quota tier name (``"free"``, ``"patreon_basic"``, ``"patreon_premium"``).
        Defaults to ``"free"``.

    Response shape
    --------------
    JSON object mirroring the ``QuotaCheck`` dataclass fields.
    """
    _internal_token = os.environ.get("FPL_INTERNAL_TOKEN", "").strip()
    if _internal_token:
        _provided = request.headers.get("X-Internal-Token", "")
        if not hmac.compare_digest(_provided, _internal_token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    # P6.2.f F-B fix: hash the query-param user_id the same way _extract_user_context
    # hashes the X-User-Id header. Without this, the UI quota indicator calls
    # GET /quota with the raw userId and gets a bucket that never matches the
    # hashed key used by record_turn() — indicator shows perpetually empty quota.
    user_id = hash_user_id(user_id)
    qc = get_quota_status(user_id, tier)
    return {
        "allowed":               qc.allowed,
        "tier":                  qc.tier,
        "daily_tokens_used":     qc.daily_tokens_used,
        "daily_message_count":   qc.daily_message_count,
        "monthly_tokens_used":   qc.monthly_tokens_used,
        "monthly_message_count": qc.monthly_message_count,
        "daily_token_cap":       qc.daily_token_cap,
        "monthly_token_cap":     qc.monthly_token_cap,
        "daily_message_cap":     qc.daily_message_cap,
        "monthly_message_cap":   qc.monthly_message_cap,
        "reason":                qc.reason,
        "upgrade_prompt_es":     qc.upgrade_prompt_es,
        "upgrade_prompt_en":     qc.upgrade_prompt_en,
    }


def _extract_user_context(request: Request) -> tuple[str, str]:
    """Extract (user_id, tier) from request headers.

    Phase P3.1 stub: reads ``X-User-Id`` header (default ``"anonymous"``) and
    ``X-User-Tier`` header (default ``"free"``).  Future Patreon integration
    will populate these headers via the auth middleware.

    P3.f (F5 remediation): the raw X-User-Id header value is hashed via
    ``hash_user_id()`` (SHA-256 first 16 hex chars) before being used as the
    quota key and stored in the audit log.  The raw value never leaves this
    function.
    """
    raw_user_id = request.headers.get("X-User-Id", "anonymous") or "anonymous"
    user_id = hash_user_id(raw_user_id)
    tier    = request.headers.get("X-User-Tier", "free") or "free"
    return user_id, tier


def _is_deterministic_branch(ask_v2_dict: dict[str, Any]) -> bool:
    """Return True when the branch is a deterministic (LLM-free) turn.

    @resource and /prompt turns go through ask_v2() but burn zero LLM tokens.
    They are audited but NOT quota-gated (deterministic = free per plan).
    """
    branch = (ask_v2_dict.get("routing_trace") or {}).get("branch", "")
    return branch in ("resource", "prompt")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, request: Request) -> AskResponse:
    """Ask a FPL captaincy or player question.

    Always returns HTTP 200 with a ``FinalResponse``-compatible payload.
    The HTTP status code does not vary by intent outcome -- inspect
    ``supported`` and ``outcome`` in the response body instead.

    Parameters (JSON body)
    ----------------------
    question : str
        Your FPL question (e.g. ``"should I captain Haaland this week?"``).
    debug : bool, optional
        When ``True``, populate the ``debug`` blob with the routing_trace.
        Defaults to ``False``.

    Routing
    -------
    G1 (mcp-graduation): rewired through ``harness.ask_v2()`` and
    ``harness_adapter.to_ask_response()``.  ``AskResponse`` shape unchanged.
    ``POST /session/{id}/ask`` still calls ``respond()`` (sessions out of scope).

    intent_hint (deferred deprecation)
    -----------------------------------
    ``intent_hint`` is NOT accepted by ``ask_v2()``; its deprecation is deferred
    to a follow-on branch.  To preserve backward-compatible routing today we
    pre-apply the hint via ``dispatcher._try_route_with_hint``: if the hint
    produces a canonical question, we pass that rewritten text to ``ask_v2()``
    and inject ``classification_source="intent_hint"`` into the routing_trace so
    the adapter correctly sets ``route_source="intent_hint"``.  When the hint
    does not fire (invalid hint, unknown player), ``ask_v2()`` receives the
    original question unchanged.

    Phase P3.1 additions
    --------------------
    * Reads ``X-User-Id`` and ``X-User-Tier`` headers (defaults: ``"anonymous"``
      / ``"free"``).
    * Calls ``check_quota()`` before the LLM.  Deterministic (@resource, /prompt)
      turns bypass the gate and are never blocked.
    * Returns ``outcome="quota_exceeded"`` with a localized upgrade message when
      the gate fires (HTTP 200 — soft-fail, not a 4xx).
    * Calls ``record_turn()`` and ``write_audit_entry()`` after every turn.
    """
    # Deferred imports — avoid circulars at module load time.
    from fpl_grounded_assistant.harness import ask_v2 as _ask_v2  # noqa: PLC0415
    from fpl_grounded_assistant.harness_adapter import to_ask_response as _to_ask_response  # noqa: PLC0415

    if _bootstrap is None:
        raise HTTPException(status_code=503, detail="Bootstrap not initialised")

    # Phase P3.1: extract user context from headers.
    user_id, tier = _extract_user_context(request)

    # ------------------------------------------------------------------
    # P3.f (F2 remediation): deterministic-prefix early-exit.
    # Questions starting with '@' (resource) or '/' (prompt) are
    # deterministic — they burn zero LLM tokens and are FREE per plan.
    # We detect this at the server boundary BEFORE calling check_quota
    # so quota-exhausted users can still use @resource and /prompt.
    # record_turn (tokens=0) and write_audit_entry still fire so usage
    # is observable, but we never block these turns.
    # ------------------------------------------------------------------
    _question_stripped = req.question.lstrip()
    _is_deterministic_prefix = _question_stripped.startswith("@") or _question_stripped.startswith("/")

    # ------------------------------------------------------------------
    # Phase P3.1: pre-call quota gate.
    # Deterministic (@resource, /prompt) branches are checked AFTER the
    # ask_v2() call (we need the branch label).  For plain-text / unknown
    # routes we call check_quota BEFORE ask_v2 to avoid wasted LLM calls.
    # However, we can't know the branch before routing, so we do a
    # lightweight pre-check here and skip gating if the turn turns out
    # to be deterministic (audited anyway with zero tokens).
    # ------------------------------------------------------------------
    _quota_check = check_quota(user_id, tier) if not _is_deterministic_prefix else None

    # ------------------------------------------------------------------
    # intent_hint pre-processing (deferred deprecation — V2 contract).
    # ask_v2() has no intent_hint parameter; we resolve the canonical
    # question here so the routing ladder sees the right text, then
    # inject classification_source into the routing_trace post-call so
    # the adapter can set route_source correctly.
    # ------------------------------------------------------------------
    effective_question = req.question
    _hint_fired = False
    if req.intent_hint is not None:
        from fpl_grounded_assistant.dispatcher import _try_route_with_hint  # noqa: PLC0415
        _hint_result = _try_route_with_hint(req.question, req.intent_hint)
        if _hint_result is not None:
            _route_result, effective_question = _hint_result
            _hint_fired = True

    # ------------------------------------------------------------------
    # Phase P3.1: quota-exceeded soft-fail for non-deterministic turns.
    # We cannot tell the branch before calling ask_v2, so we apply the
    # quota gate speculatively here.  If the turn IS deterministic (zero
    # LLM tokens), record_turn is still called (with tokens=0) and the
    # audit entry captures the zero-cost turn.
    # ------------------------------------------------------------------
    if _quota_check is not None and not _quota_check.allowed:
        # Soft-fail: return a polite upgrade message.
        _lang = "en"   # TODO: detect from Accept-Language header (P4 scope)
        _upgrade_text = (
            _quota_check.upgrade_prompt_es
            or "Has alcanzado tu límite de uso. Por favor actualiza tu plan."
        )
        # Audit the quota-exceeded turn (no LLM was called).
        _quota_exceeded_entry = make_audit_entry(
            user_id=user_id,
            tier=tier,
            question=req.question,
            branch="quota_exceeded",
            outcome=OUTCOME_QUOTA_EXCEEDED,
            intent=None,
            tokens={},
            provider=os.environ.get("DEFAULT_PROVIDER", "gemini"),
            error_code="quota_exceeded",
            final_text=_upgrade_text,
        )
        try:
            write_audit_entry(_quota_exceeded_entry)
        except Exception as _exc:  # noqa: BLE001
            _LOG.exception("audit write failed: %s", _exc)  # P3.f F8: observable signal
        return AskResponse(
            final_text=_upgrade_text,
            outcome=OUTCOME_QUOTA_EXCEEDED,
            supported=False,
            intent="unsupported",
            review_passed=False,
            llm_used=False,
        )

    # ------------------------------------------------------------------
    # Core routing: ask_v2() → harness_adapter.to_ask_response()
    # squad_context goes to the adapter only (not to ask_v2).
    # ------------------------------------------------------------------
    ask_v2_dict: dict[str, Any] = _ask_v2(
        effective_question,
        _bootstrap,
        candidates_list=req.candidates_list,
        classifier_client=_classifier_client,  # Phase 4l
    )

    # ------------------------------------------------------------------
    # intent_hint post-processing: inject classification_source into the
    # routing_trace so the adapter maps it to route_source="intent_hint".
    # We shallow-copy the dict so we never mutate harness internals.
    # ------------------------------------------------------------------
    if _hint_fired:
        routing_trace: dict[str, Any] = dict(ask_v2_dict.get("routing_trace") or {})
        routing_trace["classification_source"] = "intent_hint"
        ask_v2_dict = dict(ask_v2_dict)
        ask_v2_dict["routing_trace"] = routing_trace

    # ------------------------------------------------------------------
    # Phase P3.1: post-call accounting + audit.
    # record_turn() fires for ALL turns including deterministic ones
    # (tokens=0 for @resource / /prompt — they don't burn LLM quota).
    # ------------------------------------------------------------------
    _tokens: dict[str, int] = ask_v2_dict.get("tokens") or {}  # type: ignore[assignment]
    _total_tokens = _tokens.get("total", 0)
    _branch = (ask_v2_dict.get("routing_trace") or {}).get("branch", "unknown")
    _outcome = ask_v2_dict.get("outcome", "unknown")
    _intent  = ask_v2_dict.get("intent")
    _provider = os.environ.get("DEFAULT_PROVIDER", "gemini")
    _final_text = ask_v2_dict.get("answer_text", "")

    # Quota accounting: deterministic turns count as 1 message but 0 tokens.
    try:
        _record_turn(user_id, _total_tokens, tier)
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("quota record_turn failed for user=%s: %s", user_id, exc)

    # Build audit entry from ask_v2 output.
    _routing_trace = ask_v2_dict.get("routing_trace") or {}
    _tool_calls: list[dict] = []
    if ask_v2_dict.get("selected_tool"):
        _tool_calls = [{
            "name":          ask_v2_dict.get("selected_tool", ""),
            "args":          ask_v2_dict.get("tool_input") or {},
            "output_status": (ask_v2_dict.get("raw_output") or {}).get("status", "unknown"),
        }]

    _audit_entry = make_audit_entry(
        user_id=user_id,
        tier=tier,
        question=req.question,
        branch=_branch,
        outcome=_outcome,
        intent=_intent,
        tool_calls=_tool_calls,
        evaluator_verdict=None,  # evaluator verdict not yet surfaced in ask_v2 dict (P3.2)
        retry_attempted=False,
        final_text=_final_text,
        tokens=_tokens,
        provider=_provider,
        error_code=None,
    )
    try:
        write_audit_entry(_audit_entry)
    except Exception as _exc:  # noqa: BLE001
        _LOG.exception("audit write failed: %s", _exc)  # P3.f F8: observable signal

    return _to_ask_response(ask_v2_dict, req)


@app.post("/session", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    """Create a new in-memory conversation session.

    Prunes expired sessions before creating a new entry.
    Returns HTTP 429 when the session cap (_SESSION_MAX_COUNT) is reached.
    Returns HTTP 503 when ``FPL_SESSION_ENABLED=false`` (operator kill-switch).

    Returns a session_id, creation timestamp, and the configured TTL so
    callers know when the session will expire if idle.

    P3.f (F1 remediation): set ``FPL_SESSION_ENABLED=false`` to disable all
    session endpoints.  Default is ``true`` for backwards compatibility.
    """
    if os.environ.get("FPL_SESSION_ENABLED", "true").lower() in ("false", "0", "no"):
        raise HTTPException(
            status_code=503,
            detail="Session endpoints are disabled (FPL_SESSION_ENABLED=false). Use /ask instead.",
        )
    from fpl_grounded_assistant import ConversationSession  # noqa: PLC0415
    _prune_expired_sessions()
    if len(_sessions) >= _SESSION_MAX_COUNT:
        raise HTTPException(
            status_code=429,
            detail=f"Session cap reached ({_SESSION_MAX_COUNT}). Clear idle sessions and retry.",
        )
    now = time.time()
    session_id = str(uuid.uuid4())
    _sessions[session_id] = _SessionEntry(
        session=ConversationSession(),
        created_at=now,
        last_used_at=now,
    )
    return CreateSessionResponse(
        session_id=session_id,
        created_at=now,
        expires_after_seconds=_SESSION_TTL_SECONDS,
    )


@app.post("/session/{session_id}/ask", response_model=SessionAskResponse)
def session_ask(session_id: str, req: AskRequest, request: Request) -> SessionAskResponse:
    """Ask a question within a conversation session.

    Pronoun and reference follow-ups are resolved against previous turns
    in the same session.  Bootstrap is the same server-level bootstrap used
    by the stateless /ask endpoint.

    Parameters (JSON body)
    ----------------------
    question : str
        Your FPL question.
    debug : bool, optional
        When True, populate the debug bundle (same as /ask) plus resolver
        metadata.  rewritten_question is also populated at the top level
        when the resolver rewrote the question.  Defaults to False.

    HTTP status codes
    -----------------
    200   Turn processed.  Inspect supported/outcome in the response body.
    404   session_id not found or expired.
    422   Malformed request body.
    503   Bootstrap not initialised or sessions disabled (FPL_SESSION_ENABLED=false).

    Phase P3.1 additions
    --------------------
    * Reads ``X-User-Id`` and ``X-User-Tier`` headers (same as /ask).
    * Applies quota gate before session.respond().
    * Token observability is limited for session turns: ConversationSession.respond()
      does not currently surface token counts.  Tokens are recorded as 0 for session
      turns; cost estimate will under-report until session path gains token observability.

    P3.f remediation
    ----------------
    F1: Session turns record tokens=0 (graduation debt — ConversationSession.respond()
        does not surface token counts).  A logger.warning fires per turn so production
        has an observable signal.  Set FPL_SESSION_ENABLED=false to disable sessions
        entirely (operator kill-switch) until tokens are properly surfaced.
    F2: @resource and /prompt prefixes bypass check_quota (deterministic = free).
    F8: Audit write failures are logged via logger.exception instead of silently swallowed.
    """
    if os.environ.get("FPL_SESSION_ENABLED", "true").lower() in ("false", "0", "no"):
        raise HTTPException(
            status_code=503,
            detail="Session endpoints are disabled (FPL_SESSION_ENABLED=false). Use /ask instead.",
        )

    if _bootstrap is None:
        raise HTTPException(status_code=503, detail="Bootstrap not initialised")

    entry = _sessions.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Lazy TTL check — treat expired session the same as not found
    if _SESSION_TTL_SECONDS > 0 and time.time() - entry.last_used_at > _SESSION_TTL_SECONDS:
        del _sessions[session_id]
        raise HTTPException(status_code=404, detail=f"Session expired: {session_id}")

    # Phase P3.1: extract user context + apply quota gate (same enforcement as /ask).
    _sess_user_id, _sess_tier = _extract_user_context(request)

    # P3.f (F2 remediation): deterministic-prefix bypass (same as /ask boundary).
    _sess_question_stripped = req.question.lstrip()
    _sess_is_deterministic = (
        _sess_question_stripped.startswith("@") or _sess_question_stripped.startswith("/")
    )
    _sess_quota = check_quota(_sess_user_id, _sess_tier) if not _sess_is_deterministic else None
    if _sess_quota is not None and not _sess_quota.allowed:
        _sess_upgrade_text = (
            _sess_quota.upgrade_prompt_es
            or "Has alcanzado tu límite de uso. Por favor actualiza tu plan."
        )
        _sess_quota_entry = make_audit_entry(
            user_id=_sess_user_id,
            tier=_sess_tier,
            question=req.question,
            branch="quota_exceeded",
            outcome=OUTCOME_QUOTA_EXCEEDED,
            intent=None,
            tokens={},
            provider=os.environ.get("DEFAULT_PROVIDER", "gemini"),
            error_code="quota_exceeded",
            final_text=_sess_upgrade_text,
        )
        try:
            write_audit_entry(_sess_quota_entry)
        except Exception as _exc:  # noqa: BLE001
            _LOG.exception("audit write failed: %s", _exc)  # P3.f F8: observable signal
        return SessionAskResponse(
            session_id=session_id,
            final_text=_sess_upgrade_text,
            outcome=OUTCOME_QUOTA_EXCEEDED,
            supported=False,
            intent="unsupported",
            review_passed=False,
            llm_used=False,
        )

    r = entry.session.respond(
        req.question, _bootstrap,
        include_debug=req.debug,
        candidates_list=req.candidates_list,
        classifier_client=_classifier_client,  # Phase 4l
        squad_context=req.squad_context,        # Phase 8e1
        intent_hint=req.intent_hint,            # V2
    )
    entry.last_used_at = time.time()

    # Phase P3.1 / P3.f (F1 remediation): post-call quota accounting + audit for session turns.
    # Grad-D D3-B: token count now surfaced via entry.session.last_tokens.
    if entry.session.last_tokens == 0 and is_orch_enabled():
        _LOG.warning(
            "session turn recorded with tokens=0 despite orch enabled — "
            "possible token surfacing failure for user=%s tier=%s",
            _sess_user_id, _sess_tier,
        )
    try:
        _record_turn(_sess_user_id, entry.session.last_tokens, _sess_tier)
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("quota record_turn failed for session user=%s: %s", _sess_user_id, exc)
    _sess_audit_entry = make_audit_entry(
        user_id=_sess_user_id,
        tier=_sess_tier,
        question=req.question,
        branch="session",
        outcome=r.outcome,
        intent=r.intent,
        tokens={},
        provider=os.environ.get("DEFAULT_PROVIDER", "gemini"),
        final_text=r.final_text,
    )
    try:
        write_audit_entry(_sess_audit_entry)
    except Exception as _exc:  # noqa: BLE001
        _LOG.exception("audit write failed: %s", _exc)  # P3.f F8: observable signal

    debug_bundle: dict[str, Any] | None = None
    rewritten_question: str | None = None

    if req.debug and r.debug is not None:
        debug_bundle = {
            "response_text":         r.debug.response_text,
            "llm_text":              r.debug.llm_text,
            "violations":            list(r.debug.violations),
            "prompt_used":           r.debug.prompt_used,
            "model":                 r.debug.model,
            "classification_source": r.debug.classification_source,  # Phase 4l
        }
        if r.debug.resolver is not None:
            rdbg = r.debug.resolver
            debug_bundle["resolver"] = {
                "resolver_used":       rdbg.resolver_used,
                "resolver_source":     rdbg.resolver_source,
                "resolver_confidence": rdbg.resolver_confidence,
                "rewritten_question":  rdbg.rewritten_question,
                "fallback_reason":     rdbg.fallback_reason,
            }
            if rdbg.resolver_used:
                rewritten_question = rdbg.rewritten_question

    sess_comp_bundle: dict[str, Any] | None = None
    if r.comparison is not None:
        sess_comp_bundle = _comparison_dict(r.comparison)

    sess_captain_bundle: dict[str, Any] | None = None
    if r.captain is not None:
        sess_captain_bundle = _captain_meta_dict(r.captain)

    sess_captain_ranking_list: list[dict[str, Any]] | None = None
    if r.captain_ranking is not None:
        sess_captain_ranking_list = _captain_ranking_list(r.captain_ranking)

    sess_sub_responses_list: list[dict[str, Any]] | None = None  # Phase 6c/6d
    if r.sub_responses is not None:
        sess_sub_responses_list = [_sub_response_dict(sr) for sr in r.sub_responses]

    sess_transfer_bundle: dict[str, Any] | None = None           # Phase 7a
    if r.transfer is not None:
        sess_transfer_bundle = _transfer_meta_dict(r.transfer)

    sess_chip_bundle: dict[str, Any] | None = None               # Phase 7b
    if r.chip is not None:
        sess_chip_bundle = _chip_meta_dict(r.chip)

    sess_fixture_run_bundle: dict[str, Any] | None = None        # Phase 7h
    if r.fixture_run is not None:
        sess_fixture_run_bundle = _fixture_run_meta_dict(r.fixture_run)

    sess_differential_bundle: dict[str, Any] | None = None      # Phase 7g
    if r.differential is not None:
        sess_differential_bundle = _differential_meta_dict(r.differential)

    sess_player_form_bundle: dict[str, Any] | None = None
    if r.player_form is not None:
        sess_player_form_bundle = _player_form_meta_dict(r.player_form)

    sess_injury_list_bundle: dict[str, Any] | None = None
    if r.injury_list is not None:
        sess_injury_list_bundle = _injury_list_meta_dict(r.injury_list)

    sess_price_changes_bundle: dict[str, Any] | None = None
    if r.price_changes is not None:
        sess_price_changes_bundle = _price_changes_meta_dict(r.price_changes)

    sess_team_calendar_bundle: dict[str, Any] | None = None
    if r.team_calendar is not None:
        sess_team_calendar_bundle = _team_calendar_meta_dict(r.team_calendar)

    sess_team_schedule_bundle: dict[str, Any] | None = None
    if r.team_schedule is not None:
        sess_team_schedule_bundle = _team_schedule_meta_dict(r.team_schedule)

    sess_pos_fixture_run_bundle: dict[str, Any] | None = None
    if r.position_fixture_run is not None:
        sess_pos_fixture_run_bundle = _position_fixture_run_meta_dict(r.position_fixture_run)

    return SessionAskResponse(
        session_id=session_id,
        final_text=r.final_text,
        outcome=r.outcome,
        supported=r.supported,
        intent=r.intent,
        review_passed=r.review_passed,
        llm_used=r.llm_used,
        rewritten_question=rewritten_question,
        debug=debug_bundle,
        comparison=sess_comp_bundle,
        captain=sess_captain_bundle,
        captain_ranking=sess_captain_ranking_list,
        sub_responses=sess_sub_responses_list,
        transfer=sess_transfer_bundle,
        chip=sess_chip_bundle,
        fixture_run=sess_fixture_run_bundle,
        differential=sess_differential_bundle,
        orch_outcome=r.orch_outcome,   # Orch-4c: audit
        degraded=r.degraded,           # Phase 2.6b: provider failed silently
        player_form=sess_player_form_bundle,
        injury_list=sess_injury_list_bundle,
        price_changes=sess_price_changes_bundle,
        team_calendar=sess_team_calendar_bundle,
        team_schedule=sess_team_schedule_bundle,
        position_fixture_run=sess_pos_fixture_run_bundle,
        transfer_suggestion=_transfer_suggestion_meta_dict(r.transfer_suggestion) if r.transfer_suggestion is not None else None,
        # Phase 2.7d: routing audit fields
        route_source=r.route_source,
        classifier_confidence=r.classifier_confidence,
        route_conflict=r.route_conflict,
        # Phase 2.7f: clarification policy layer
        clarification_asked=r.clarification_asked,
    )


@app.delete("/session/{session_id}", response_model=ClearSessionResponse)
def clear_session(session_id: str) -> ClearSessionResponse:
    """Clear and remove a conversation session.

    After this call, the session_id is no longer valid.  Create a new session
    with POST /session to start fresh.

    HTTP status codes
    -----------------
    200   Session cleared successfully.
    404   session_id not found (or already expired and cleaned up).
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    del _sessions[session_id]
    return ClearSessionResponse(status="cleared", session_id=session_id)


@app.get("/session/{session_id}", response_model=SessionInfoResponse)
def get_session(session_id: str) -> SessionInfoResponse:
    """Inspect metadata for an existing session.

    Returns creation/last-used timestamps and turn count.  Performs a lazy
    TTL check — expired sessions are removed and return 404.

    HTTP status codes
    -----------------
    200   Session found; metadata returned.
    404   session_id not found or expired.
    """
    entry = _sessions.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if _SESSION_TTL_SECONDS > 0 and time.time() - entry.last_used_at > _SESSION_TTL_SECONDS:
        del _sessions[session_id]
        raise HTTPException(status_code=404, detail=f"Session expired: {session_id}")

    state = entry.session.state

    # Phase 5l: bounded audit snapshot from ConversationState
    last_intent: str | None = state.history[-1][1] if state.history else None
    last_comparison_dict: dict[str, Any] | None = None
    if state.last_comparison is not None:
        last_comparison_dict = {
            "player_a": state.last_comparison[0],
            "player_b": state.last_comparison[1],
        }
    # Phase 7f: transfer context snapshot
    last_transfer_dict: dict[str, Any] | None = None
    if state.last_transfer is not None:
        last_transfer_dict = {
            "player_out": state.last_transfer[0],
            "player_in":  state.last_transfer[1],
        }

    return SessionInfoResponse(
        session_id=session_id,
        created_at=entry.created_at,
        last_used_at=entry.last_used_at,
        turn_count=entry.session.turn_count,
        last_intent=last_intent,
        last_player=state.last_player_query,
        last_comparison=last_comparison_dict,
        last_resolver_source=state.last_resolver_source,
        last_transfer=last_transfer_dict,
        last_fixture_run_player=state.last_fixture_run_player,  # Phase 8d-i
        last_differential=state.last_differential,               # Phase 8d-ii
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("fpl_server:app", host="127.0.0.1", port=8000, reload=False)
