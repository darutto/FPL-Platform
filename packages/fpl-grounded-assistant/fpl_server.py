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

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fpl_grounded_assistant import respond
from fpl_grounded_assistant.player_form import _element_summary_guard  # Phase 2.6d.3 — guard stats
from fpl_pipeline import assemble_captain_context

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
# ---------------------------------------------------------------------------
# Bootstrap retry policy
# ---------------------------------------------------------------------------

#: Total attempts for the FPL bootstrap fetch at startup (1 initial + N retries).
_BOOTSTRAP_MAX_ATTEMPTS: int = 4

#: Seconds to wait between consecutive attempts.
#: Increasing delays give the FPL API time to recover from a transient outage.
_BOOTSTRAP_RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 10.0)


def _fetch_bootstrap_with_retry(
    _sleep_fn: Any = None,
) -> "dict[str, Any] | None":
    """Fetch the FPL bootstrap with bounded retries and structured logging.

    Makes up to ``_BOOTSTRAP_MAX_ATTEMPTS`` calls to
    ``assemble_captain_context()``.  Between attempts it sleeps for the
    corresponding delay in ``_BOOTSTRAP_RETRY_DELAYS``.

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

    Returns runtime metrics for the element-summary circuit guard.
    All values are read-only and thread-safe.

    Response shape
    --------------
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

    This endpoint is NOT a stable contract — field names may change across
    platform versions.  Do not use it for deployment probes; use ``/ready``
    instead.
    """
    stats = _element_summary_guard.get_stats()
    return {
        "element_summary_guard": {
            "state": "open" if _element_summary_guard.is_open() else "closed",
            **stats,
        },
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """Ask a FPL captaincy or player question.

    Always returns HTTP 200 with a ``FinalResponse``-compatible payload.
    The HTTP status code does not vary by intent outcome -- inspect
    ``supported`` and ``outcome`` in the response body instead.

    Parameters (JSON body)
    ----------------------
    question : str
        Your FPL question (e.g. ``"should I captain Haaland this week?"``).
    debug : bool, optional
        When ``True``, populate the ``debug`` bundle with internal fields
        (``response_text``, ``llm_text``, ``violations``, ``prompt_used``,
        ``model``).  Defaults to ``False``.
    """
    if _bootstrap is None:
        raise HTTPException(status_code=503, detail="Bootstrap not initialised")

    r = respond(
        req.question, _bootstrap,
        include_debug=req.debug,
        candidates_list=req.candidates_list,
        classifier_client=_classifier_client,  # Phase 4l
        squad_context=req.squad_context,        # Phase 8e1
        intent_hint=req.intent_hint,            # V2
    )

    debug_bundle: dict[str, Any] | None = None
    if req.debug and r.debug is not None:
        debug_bundle = {
            "response_text":         r.debug.response_text,
            "llm_text":              r.debug.llm_text,
            "violations":            list(r.debug.violations),
            "prompt_used":           r.debug.prompt_used,
            "model":                 r.debug.model,
            "classification_source": r.debug.classification_source,  # Phase 4l / V2
        }

    comp_bundle: dict[str, Any] | None = None
    if r.comparison is not None:
        comp_bundle = _comparison_dict(r.comparison)

    captain_bundle: dict[str, Any] | None = None
    if r.captain is not None:
        captain_bundle = _captain_meta_dict(r.captain)

    captain_ranking_list: list[dict[str, Any]] | None = None
    if r.captain_ranking is not None:
        captain_ranking_list = _captain_ranking_list(r.captain_ranking)

    sub_responses_list: list[dict[str, Any]] | None = None  # Phase 6c/6d
    if r.sub_responses is not None:
        sub_responses_list = [_sub_response_dict(sr) for sr in r.sub_responses]

    transfer_bundle: dict[str, Any] | None = None          # Phase 7a
    if r.transfer is not None:
        transfer_bundle = _transfer_meta_dict(r.transfer)

    chip_bundle: dict[str, Any] | None = None              # Phase 7b
    if r.chip is not None:
        chip_bundle = _chip_meta_dict(r.chip)

    fixture_run_bundle: dict[str, Any] | None = None       # Phase 7h
    if r.fixture_run is not None:
        fixture_run_bundle = _fixture_run_meta_dict(r.fixture_run)

    differential_bundle: dict[str, Any] | None = None     # Phase 7g
    if r.differential is not None:
        differential_bundle = _differential_meta_dict(r.differential)

    player_form_bundle: dict[str, Any] | None = None
    if r.player_form is not None:
        player_form_bundle = _player_form_meta_dict(r.player_form)

    injury_list_bundle: dict[str, Any] | None = None
    if r.injury_list is not None:
        injury_list_bundle = _injury_list_meta_dict(r.injury_list)

    price_changes_bundle: dict[str, Any] | None = None
    if r.price_changes is not None:
        price_changes_bundle = _price_changes_meta_dict(r.price_changes)

    team_calendar_bundle: dict[str, Any] | None = None
    if r.team_calendar is not None:
        team_calendar_bundle = _team_calendar_meta_dict(r.team_calendar)

    team_schedule_bundle: dict[str, Any] | None = None
    if r.team_schedule is not None:
        team_schedule_bundle = _team_schedule_meta_dict(r.team_schedule)

    pos_fixture_run_bundle: dict[str, Any] | None = None
    if r.position_fixture_run is not None:
        pos_fixture_run_bundle = _position_fixture_run_meta_dict(r.position_fixture_run)

    return AskResponse(
        final_text=r.final_text,
        outcome=r.outcome,
        supported=r.supported,
        intent=r.intent,
        review_passed=r.review_passed,
        llm_used=r.llm_used,
        debug=debug_bundle,
        comparison=comp_bundle,
        captain=captain_bundle,
        captain_ranking=captain_ranking_list,
        sub_responses=sub_responses_list,
        transfer=transfer_bundle,
        chip=chip_bundle,
        fixture_run=fixture_run_bundle,
        differential=differential_bundle,
        orch_outcome=r.orch_outcome,   # Orch-4c: audit
        degraded=r.degraded,           # Phase 2.6b: provider failed silently
        player_form=player_form_bundle,
        injury_list=injury_list_bundle,
        price_changes=price_changes_bundle,
        team_calendar=team_calendar_bundle,
        team_schedule=team_schedule_bundle,
        position_fixture_run=pos_fixture_run_bundle,
    )


@app.post("/session", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    """Create a new in-memory conversation session.

    Prunes expired sessions before creating a new entry.
    Returns HTTP 429 when the session cap (_SESSION_MAX_COUNT) is reached.

    Returns a session_id, creation timestamp, and the configured TTL so
    callers know when the session will expire if idle.
    """
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
def session_ask(session_id: str, req: AskRequest) -> SessionAskResponse:
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
    503   Bootstrap not initialised.
    """
    if _bootstrap is None:
        raise HTTPException(status_code=503, detail="Bootstrap not initialised")

    entry = _sessions.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Lazy TTL check — treat expired session the same as not found
    if _SESSION_TTL_SECONDS > 0 and time.time() - entry.last_used_at > _SESSION_TTL_SECONDS:
        del _sessions[session_id]
        raise HTTPException(status_code=404, detail=f"Session expired: {session_id}")

    r = entry.session.respond(
        req.question, _bootstrap,
        include_debug=req.debug,
        candidates_list=req.candidates_list,
        classifier_client=_classifier_client,  # Phase 4l
        squad_context=req.squad_context,        # Phase 8e1
        intent_hint=req.intent_hint,            # V2
    )
    entry.last_used_at = time.time()

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
