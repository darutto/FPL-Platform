"""
fpl_server -- minimal HTTP entrypoint for the FPL grounded assistant.

Phase 4i: session hygiene and lifecycle hardening.

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
    PYTHONPATH=... python -m uvicorn fpl_server:app --reload

or for a quick smoke test::

    PYTHONPATH=... python fpl_server.py   (binds 127.0.0.1:8000)

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

import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fpl_grounded_assistant import respond
from fpl_pipeline import assemble_captain_context


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


class AskResponse(BaseModel):
    """FinalResponse-compatible JSON response.

    Field names and semantics mirror ``FinalResponse`` exactly.
    ``debug`` is only populated when ``AskRequest.debug=True``.
    ``comparison`` is populated for compare_players OK turns (Phase 5g).
    """

    final_text: str
    outcome: str
    supported: bool
    intent: str
    review_passed: bool
    llm_used: bool
    debug: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None  # Phase 5g


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
    comparison: dict[str, Any] | None = None  # Phase 5g


class ClearSessionResponse(BaseModel):
    """Response from DELETE /session/{session_id}."""

    status: str    # always "cleared"
    session_id: str


class SessionInfoResponse(BaseModel):
    """Response from GET /session/{session_id}."""

    session_id: str
    created_at: float
    last_used_at: float
    turn_count: int


# ---------------------------------------------------------------------------
# Application + lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Assemble live bootstrap once at startup.

    Skipped if ``_bootstrap`` is already set (test injection path).
    """
    if _bootstrap is None:
        ctx = assemble_captain_context()
        _init_bootstrap(ctx["bootstrap"])
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
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check.  Returns 200 when the server is running."""
    return {"status": "ok"}


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

    r = respond(req.question, _bootstrap, include_debug=req.debug)

    debug_bundle: dict[str, Any] | None = None
    if req.debug and r.debug is not None:
        debug_bundle = {
            "response_text": r.debug.response_text,
            "llm_text":      r.debug.llm_text,
            "violations":    list(r.debug.violations),
            "prompt_used":   r.debug.prompt_used,
            "model":         r.debug.model,
        }

    comp_bundle: dict[str, Any] | None = None
    if r.comparison is not None:
        def _player_ctx_dict(ctx: Any) -> dict[str, Any] | None:
            if ctx is None:
                return None
            return {
                "web_name":        ctx.web_name,
                "position":        ctx.position,
                "captain_score":   ctx.captain_score,
                "role_bonus":      ctx.role_bonus,
                "set_piece_notes": list(ctx.set_piece_notes),
            }
        comp_bundle = {
            "winner":   r.comparison.winner,
            "margin":   r.comparison.margin,
            "label":    r.comparison.label,
            "reasons":  list(r.comparison.reasons),
            "player_a": _player_ctx_dict(r.comparison.player_a),  # Phase 5i
            "player_b": _player_ctx_dict(r.comparison.player_b),  # Phase 5i
        }

    return AskResponse(
        final_text=r.final_text,
        outcome=r.outcome,
        supported=r.supported,
        intent=r.intent,
        review_passed=r.review_passed,
        llm_used=r.llm_used,
        debug=debug_bundle,
        comparison=comp_bundle,
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

    r = entry.session.respond(req.question, _bootstrap, include_debug=req.debug)
    entry.last_used_at = time.time()

    debug_bundle: dict[str, Any] | None = None
    rewritten_question: str | None = None

    if req.debug and r.debug is not None:
        debug_bundle = {
            "response_text": r.debug.response_text,
            "llm_text":      r.debug.llm_text,
            "violations":    list(r.debug.violations),
            "prompt_used":   r.debug.prompt_used,
            "model":         r.debug.model,
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
        def _sess_player_ctx_dict(ctx: Any) -> dict[str, Any] | None:
            if ctx is None:
                return None
            return {
                "web_name":        ctx.web_name,
                "position":        ctx.position,
                "captain_score":   ctx.captain_score,
                "role_bonus":      ctx.role_bonus,
                "set_piece_notes": list(ctx.set_piece_notes),
            }
        sess_comp_bundle = {
            "winner":   r.comparison.winner,
            "margin":   r.comparison.margin,
            "label":    r.comparison.label,
            "reasons":  list(r.comparison.reasons),
            "player_a": _sess_player_ctx_dict(r.comparison.player_a),  # Phase 5i
            "player_b": _sess_player_ctx_dict(r.comparison.player_b),  # Phase 5i
        }

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

    return SessionInfoResponse(
        session_id=session_id,
        created_at=entry.created_at,
        last_used_at=entry.last_used_at,
        turn_count=entry.session.turn_count,
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("fpl_server:app", host="127.0.0.1", port=8000, reload=False)
