"""
fpl_grounded_assistant.search_web
====================================
Last-resort, premium-gated query search tool — ported from
``worldcup_assistant.web_search`` (documented there as self-contained and
domain-agnostic so the FPL package could reuse it unchanged).

The deterministic FPL tools cover players/teams/fixtures/prices/form. Anything
*outside* those feeds — transfer rumours, press-conference quotes, breaking
news, rotation/manager commentary — has no grounded source. ``search_web``
fetches focused results from Tavily (a search API purpose-built for LLM
agents) so the orchestrator can synthesise an answer that is **clearly
labelled as unverified** in the UI.

Design contract
----------------
* **Premium-gated**: only exposed to the LLM when the caller's tier is
  eligible AND the turn explicitly opted in (see ``fpl_server.py``'s
  ``WEB_SEARCH_TIERS`` gate and ``orchestrator.ask_orchestrated(web_search_enabled=...)``).
  This module performs no gating itself — gating is a server/orchestrator
  concern.
* **Synthesis is the model's job**: Tavily's ``answer`` is kept only as model
  input; it is never shown to the user directly. The Spanish prose surfaced to
  the user is the orchestrator's rendered ``answer_text``, built downstream in
  ``harness_adapter.to_ask_response()``.
* **Snippet hygiene**: each result's ``snippet`` is capped to ``_SNIPPET_MAX``
  chars so the tool loop never re-ingests whole article bodies.

Auth
----
Reads ``TAVILY_API_KEY`` from the environment. A missing key raises
``WebSearchError`` so the tool-runner handler reports ``{"status": "error", ...}``
rather than crashing.

Registration
------------
Registers ``search_web`` in ``TOOL_REGISTRY`` as a side-effect of import.
``__init__.py`` imports this module so ``run_tool("search_web", ...)`` works.
Schema for the orchestrator's per-request, opt-in tool list lives separately
in ``tool_schema_registry.SEARCH_WEB_SCHEMA`` (kept OUT of ``_ALL_SCHEMAS``).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

_BASE_URL = "https://api.tavily.com/search"
_DEFAULT_TIMEOUT_S: float = 15.0
#: How many results to ask Tavily for (a wider pool to filter from).
_FETCH_RESULTS: int = 8
#: How many to keep after relevance filtering (what the card/model sees).
_MAX_RESULTS: int = 5
#: Tavily relevance score (0-1) below which a result is dropped as off-topic.
_DEFAULT_MIN_SCORE: float = 0.5
#: Hard cap on each result snippet (chars) before it re-enters the tool loop.
_SNIPPET_MAX: int = 280


def _min_score() -> float:
    try:
        return float(os.environ.get("TAVILY_MIN_SCORE", ""))
    except (ValueError, TypeError):
        return _DEFAULT_MIN_SCORE


class WebSearchError(Exception):
    """Raised on missing key, transport failure, or non-2xx Tavily response."""


def _api_key() -> str:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise WebSearchError("TAVILY_API_KEY is not set.")
    return key


def _source_from_url(url: str) -> str:
    """Human-readable outlet name from a result URL (e.g. www.bbc.com -> bbc.com)."""
    try:
        host = urlparse(url).netloc
    except (ValueError, TypeError):
        return ""
    return host[4:] if host.startswith("www.") else host


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _clean_snippet(text: str) -> str:
    """Flatten markdown/markup so a snippet renders as plain prose."""
    if not text:
        return ""
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links/images -> label text
    t = re.sub(r"[*_`>#]+", " ", t)                       # md emphasis/heading marks
    t = re.sub(r"\s+", " ", t)                             # collapse whitespace/newlines
    return t.strip()


def search_web(query: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Run one focused web search and return a card-ready envelope.

    Returns ``{"results": [{title, snippet, url, source, published}],
    "answer": str | None, "timestamp": iso}``. ``answer`` is model input only.
    Raises ``WebSearchError`` on any failure so the executor can surface it as
    a tool-level error the LLM can react to.
    """
    if not query or not query.strip():
        raise WebSearchError("empty search query")

    payload = {
        "api_key": _api_key(),
        "query": query.strip(),
        "search_depth": "advanced",
        "topic": "general",
        "max_results": _FETCH_RESULTS,
        "include_answer": True,
    }

    try:
        resp = httpx.post(_BASE_URL, json=payload, timeout=timeout_s)
    except httpx.TimeoutException as exc:
        raise WebSearchError(f"web search timed out after {timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise WebSearchError(f"{type(exc).__name__}: {exc}") from exc

    if resp.status_code >= 400:
        raise WebSearchError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise WebSearchError("web search returned non-JSON body") from exc

    raw_items = body.get("results") or []

    min_score = _min_score()
    has_scores = any(isinstance(it.get("score"), (int, float)) for it in raw_items)
    if has_scores:
        kept = [it for it in raw_items if (it.get("score") or 0.0) >= min_score]
        kept.sort(key=lambda it: it.get("score") or 0.0, reverse=True)
    else:
        kept = list(raw_items)
    kept = kept[:_MAX_RESULTS]

    results: list[dict[str, Any]] = []
    for item in kept:
        url = item.get("url") or ""
        results.append({
            "title": _clip(_clean_snippet(item.get("title") or ""), 140),
            "snippet": _clip(_clean_snippet(item.get("content") or ""), _SNIPPET_MAX),
            "url": url,
            "source": _source_from_url(url),
            "published": item.get("published_date"),
        })

    answer = body.get("answer")
    answer_ok = bool(results) and isinstance(answer, str) and answer.strip()
    return {
        "results": results,
        "answer": answer if answer_ok else None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

SEARCH_WEB_SPEC = ToolSpec(
    name="search_web",
    description=(
        "LAST RESORT. Live web search for FPL/football information that NO other "
        "tool can provide: breaking news, injuries/doubts, suspensions, "
        "press-conference quotes, transfer/lineup rumours, or opinion/"
        "prediction questions. NEVER use it for player stats, prices, fixtures, "
        "form, or anything covered by a dedicated tool — those are always more "
        "reliable. "
        "QUERY CONSTRUCTION: the `query` must be concise, keyword-heavy, and "
        "stripped of conversational filler. Never pass the user's raw "
        "conversational sentence directly. Example — user 'oye, ¿sabes si "
        "Salah está lesionado para el partido de mañana?' -> "
        "query: 'Salah lesion estado Liverpool'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Concise, keyword-heavy search query (no conversational "
                    "filler). Player/team/topic keywords only."
                ),
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "results": {"type": "array"},
            "answer": {"type": "string"},
            "timestamp": {"type": "string"},
        },
    },
)


def _search_web_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``search_web()``."""
    try:
        query = args.get("query")
        if not query:
            return {
                "status": "error",
                "code": "missing_argument",
                "message": "'query' argument is missing or empty.",
            }
        raw = search_web(query=query)
        return {"status": "ok", **raw}
    except WebSearchError as exc:
        return {
            "status": "error",
            "code": "search_failed",
            "message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "code": "search_failed",
            "message": f"search_web raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("search_web", ...) works.
TOOL_REGISTRY.register(SEARCH_WEB_SPEC, _search_web_handler)
