"""
worldcup_assistant.wc_server — HTTP entrypoint for the World Cup assistant.

Mirrors ``fpl_server.py`` at the edge (same ``AskRequest``/``AskResponse``
shapes so the UI proxy + rendering pipeline are shared) while the inside is
the orchestrator-primary tool loop instead of the FPL deterministic router.

Endpoints
---------
POST /ask        {"question": "...", "debug": false, "session_id": null}
                 → AskResponse-compatible JSON (final_text is primary;
                   structured card fields arrive in Iteration 3)
GET  /health     {"status": "ok"}
GET  /ready      provider + context readiness (fail-soft diagnostics)

Session namespacing (plan, cross-cutting requirement 2)
-------------------------------------------------------
``AskRequest.session_id`` is optional and additive.  When present, the turn
transcript is stored under a ``wc:``-prefixed key; ids arriving without the
prefix are normalised to it.  The WC service only ever loads ``wc:`` keys,
so FPL and WC history can never bleed even if a UI bug sends the wrong id.

Start the server
----------------
    cd packages/worldcup-assistant
    python -m uvicorn worldcup_assistant.wc_server:app --port 8100

or for a quick smoke test::

    python -m worldcup_assistant.wc_server   (binds 127.0.0.1:8100)
"""
from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# sys.path setup (same sibling-package pattern as fpl_server.py)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_HERE)             # packages/worldcup-assistant
_PKGS = os.path.dirname(_PKG_ROOT)             # packages/
for _pkg in [
    _PKG_ROOT,
    os.path.join(_PKGS, "llm-orchestrator-core"),
    os.path.join(_PKGS, "worldcup-api-client"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from llm_orchestrator_core import LOOP_OK, check_provider_health  # noqa: E402
from worldcup_assistant.ask import WCAskResult, ask_wc  # noqa: E402
from worldcup_assistant.context_builder import build_wc_context_dict  # noqa: E402

_LOG = logging.getLogger(__name__)

#: Domain namespace prefix for all session keys (end-to-end isolation rule).
_WC_SESSION_PREFIX: str = "wc:"

_SESSION_TTL_SECONDS: int = 1800   # idle timeout; parity with fpl_server
_SESSION_MAX_COUNT:   int = 100
#: History turns (user+assistant pairs) kept per session for the LLM context.
_SESSION_MAX_TURNS:   int = 6


# ---------------------------------------------------------------------------
# In-memory session registry (wc:-namespaced)
# ---------------------------------------------------------------------------

@dataclass
class _WCSessionEntry:
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)


_sessions: dict[str, _WCSessionEntry] = {}


def _normalize_session_id(session_id: str) -> str:
    """Force the ``wc:`` namespace onto any incoming session id."""
    sid = session_id.strip()
    if not sid.startswith(_WC_SESSION_PREFIX):
        sid = _WC_SESSION_PREFIX + sid
    return sid


def _prune_expired_sessions() -> None:
    if _SESSION_TTL_SECONDS <= 0:
        return
    now = time.time()
    for sid in [
        s for s, e in list(_sessions.items())
        if now - e.last_used_at > _SESSION_TTL_SECONDS
    ]:
        del _sessions[sid]


def _get_or_create_session(session_id: str) -> tuple[str, _WCSessionEntry]:
    _prune_expired_sessions()
    sid = _normalize_session_id(session_id)
    entry = _sessions.get(sid)
    if entry is None:
        if len(_sessions) >= _SESSION_MAX_COUNT:
            oldest = min(_sessions, key=lambda s: _sessions[s].last_used_at)
            del _sessions[oldest]
        entry = _WCSessionEntry()
        _sessions[sid] = entry
    entry.last_used_at = time.time()
    return sid, entry


def _clear_sessions() -> None:
    """Used by tests to reset state between suites."""
    _sessions.clear()


# ---------------------------------------------------------------------------
# Request / response schemas (standard shapes; see fpl_server.py)
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    """Incoming question payload — same shape as the FPL service, plus the
    additive ``session_id`` used for wc:-namespaced history."""

    question: str
    debug: bool = False
    candidates_list: list[dict[str, Any]] | None = None
    squad_context: dict[str, Any] | None = None
    intent_hint: str | None = None
    session_id: str | None = None


class AskResponse(BaseModel):
    """AskResponse-compatible JSON (FPL ``FinalResponse`` field contract).

    ``final_text`` is always the primary field. The structured card fields
    (``standings``, ``top_scorers``, ``fantasy_top_players``, ``fixtures``,
    ``squad``, ``head_to_head``, ``players_info`` — Iteration 3) are
    additive: populated when the matching tool was the most recent of its
    kind in the tool loop on an ``ok`` turn, ``None`` otherwise.
    ``players_info`` is a list (one entry per distinct ``get_player_info``
    call — '/jugador' yields 1, '/comparar' yields up to 2+). ``intent`` is
    ``"wc_info"`` for every grounded turn (the WC domain has no
    deterministic intent router — the orchestrator IS the router).

    ``grounded`` is true iff at least one tool call this turn returned
    ``status: "ok"`` — i.e. the answer is backed by real tournament data,
    not just LLM prose. In this domain ``llm_used`` is true on almost every
    turn (the LLM always phrases ``final_text``), so the UI uses
    ``grounded`` rather than ``llm_used`` for its origin badge.
    """

    final_text: str
    outcome: str
    supported: bool
    intent: str
    review_passed: bool
    llm_used: bool
    debug: dict[str, Any] | None = None
    sub_responses: list[dict[str, Any]] | None = None
    orch_outcome: str | None = None
    degraded: bool = False
    session_id: str | None = None
    standings: dict[str, Any] | None = None
    top_scorers: list[dict[str, Any]] | None = None
    top_assists: list[dict[str, Any]] | None = None
    fantasy_top_players: list[dict[str, Any]] | None = None
    fixtures: list[dict[str, Any]] | None = None
    squad: dict[str, Any] | None = None
    head_to_head: dict[str, Any] | None = None
    players_info: list[dict[str, Any]] | None = None
    wc2022_stats: list[dict[str, Any]] | None = None
    wc2022_results: list[dict[str, Any]] | None = None
    grounded: bool = False


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: float
    expires_after_seconds: int


# ---------------------------------------------------------------------------
# App state + lifespan
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {"context": "", "context_meta": None}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Build the grounding context at startup; fail-soft if the WC API is
    unreachable (degrade to tool-only with an empty/minimal context)."""
    try:
        meta = build_wc_context_dict()
        _state["context"] = meta["context"]
        _state["context_meta"] = meta
        _LOG.info(
            "wc_context built: %d chars (~%d tokens), degraded=%s",
            meta["chars"], meta["approx_tokens"], meta["degraded"],
        )
    except Exception as exc:  # noqa: BLE001 — startup must not crash on data outage
        _LOG.warning("wc_context startup build failed (tool-only mode): %s", exc)
        _state["context"] = ""
        _state["context_meta"] = {"degraded": True, "error": str(exc)}
    yield


app = FastAPI(title="worldcup-assistant", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    provider = check_provider_health(os.environ.get("WC_PROVIDER"))
    meta = _state.get("context_meta") or {}
    return {
        "status": "ok" if provider.get("available") else "degraded",
        "provider": provider,
        "worldcup_api_key_set": bool(os.environ.get("WORLDCUP_API_KEY")),
        "context": {
            "built": bool(_state.get("context")),
            "degraded": bool(meta.get("degraded", True)),
            "approx_tokens": meta.get("approx_tokens"),
        },
        "sessions_active": len(_sessions),
    }


@app.post("/session", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    """Mint a new wc:-namespaced session id."""
    sid, entry = _get_or_create_session(uuid.uuid4().hex)
    return CreateSessionResponse(
        session_id=sid,
        created_at=entry.created_at,
        expires_after_seconds=_SESSION_TTL_SECONDS,
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must be non-empty")

    # --- Session history (wc:-namespaced, optional) -----------------------
    session_id: str | None = None
    history: list[dict[str, Any]] | None = None
    entry: _WCSessionEntry | None = None
    if req.session_id:
        session_id, entry = _get_or_create_session(req.session_id)
        history = list(entry.history)

    result: WCAskResult = ask_wc(
        question,
        dynamic_context=_state.get("context", ""),
        history=history,
    )

    # --- Persist the turn (plain-text turns only: provider-portable and
    # avoids replaying stale tool_use blocks into future calls) ------------
    if entry is not None:
        entry.history.append({"role": "user", "content": question})
        entry.history.append({"role": "assistant", "content": result.final_text})
        max_msgs = _SESSION_MAX_TURNS * 2
        if len(entry.history) > max_msgs:
            entry.history = entry.history[-max_msgs:]

    ok = result.outcome == LOOP_OK
    debug_payload: dict[str, Any] | None = None
    if req.debug:
        debug_payload = {
            "model": result.model,
            "iterations": result.iterations,
            "tool_trace": result.tool_trace,
            "total_tokens": result.total_tokens,
            "error": result.error,
        }

    return AskResponse(
        final_text=result.final_text,
        outcome="ok" if ok else "error",
        supported=True,
        intent="wc_info",
        review_passed=ok,
        llm_used=result.llm_used,
        debug=debug_payload,
        orch_outcome=result.outcome,
        degraded=not ok,
        session_id=session_id,
        standings=result.standings if ok else None,
        top_scorers=result.top_scorers if ok else None,
        top_assists=result.top_assists if ok else None,
        fantasy_top_players=result.fantasy_top_players if ok else None,
        fixtures=result.fixtures if ok else None,
        squad=result.squad if ok else None,
        head_to_head=result.head_to_head if ok else None,
        players_info=result.players_info if ok else None,
        wc2022_stats=result.wc2022_stats if ok else None,
        wc2022_results=result.wc2022_results if ok else None,
        grounded=result.grounded if ok else False,
    )


# ---------------------------------------------------------------------------
# Quick smoke-test entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("WC_PORT", "8100")))
