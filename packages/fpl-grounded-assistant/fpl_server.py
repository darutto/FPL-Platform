"""
fpl_server -- minimal HTTP entrypoint for the FPL grounded assistant.

Phase 4c: thin HTTP interface.

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

import uuid
from contextlib import asynccontextmanager
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
# In-memory session registry
#
# Maps session_id (UUID4 string) → ConversationSession.
# Session lifetime is bounded to the process; no persistence.
# ---------------------------------------------------------------------------
_sessions: dict[str, Any] = {}


def _clear_sessions() -> None:
    """Clear all sessions.  Used by tests to reset state between suites."""
    _sessions.clear()


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
    """

    final_text: str
    outcome: str
    supported: bool
    intent: str
    review_passed: bool
    llm_used: bool
    debug: dict[str, Any] | None = None


class CreateSessionResponse(BaseModel):
    """Response from POST /session."""

    session_id: str


class SessionAskResponse(BaseModel):
    """Response from POST /session/{session_id}/ask.

    Extends AskResponse shape with session_id and optional rewritten_question.
    rewritten_question is only populated when debug=True and the resolver
    actually rewrote the question.
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


class ClearSessionResponse(BaseModel):
    """Response from DELETE /session/{session_id}."""

    status: str    # always "cleared"
    session_id: str


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
    version="4h",
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

    return AskResponse(
        final_text=r.final_text,
        outcome=r.outcome,
        supported=r.supported,
        intent=r.intent,
        review_passed=r.review_passed,
        llm_used=r.llm_used,
        debug=debug_bundle,
    )


@app.post("/session", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    """Create a new in-memory conversation session.

    Returns a session_id to use in subsequent /session/{session_id}/ask calls.
    Sessions are in-memory only; they are lost on server restart.
    """
    from fpl_grounded_assistant import ConversationSession  # noqa: PLC0415
    session_id = str(uuid.uuid4())
    _sessions[session_id] = ConversationSession()
    return CreateSessionResponse(session_id=session_id)


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
    404   session_id not found — create a session first with POST /session.
    422   Malformed request body.
    503   Bootstrap not initialised.
    """
    if _bootstrap is None:
        raise HTTPException(status_code=503, detail="Bootstrap not initialised")
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _sessions[session_id]
    r = session.respond(req.question, _bootstrap, include_debug=req.debug)

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
    )


@app.delete("/session/{session_id}", response_model=ClearSessionResponse)
def clear_session(session_id: str) -> ClearSessionResponse:
    """Clear and remove a conversation session.

    After this call, the session_id is no longer valid.  Create a new session
    with POST /session to start fresh.

    HTTP status codes
    -----------------
    200   Session cleared successfully.
    404   session_id not found.
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    del _sessions[session_id]
    return ClearSessionResponse(status="cleared", session_id=session_id)


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("fpl_server:app", host="127.0.0.1", port=8000, reload=False)
