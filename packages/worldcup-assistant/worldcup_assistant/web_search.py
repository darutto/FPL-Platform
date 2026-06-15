"""
worldcup_assistant.web_search
==============================
Last-resort web-search backend for the World Cup orchestrator.

The deterministic WC tools cover scores, fixtures, standings, squads and
stats. Anything *outside* those feeds — breaking news, injuries/dudas,
press-conference quotes, transfer/lineup rumours, opinion/prediction — has no
grounded source. ``search_web`` fetches focused results from Tavily (a search
API purpose-built for LLM agents) so the orchestrator can synthesise an
answer that is **clearly labelled as unverified** in the UI.

Design contract
---------------
* **Self-contained**: no ``worldcup_assistant`` imports, so the FPL domain can
  reuse this module unchanged later.
* **Synthesis is the model's job**: Tavily's ``answer`` is kept only as model
  input (often English); it is never shown to the user. The Spanish prose the
  card renders is the orchestrator's ``final_text`` (injected downstream in
  ``ask.py``), not anything this module returns.
* **Snippet hygiene**: each result's ``snippet`` is capped to ``_SNIPPET_MAX``
  chars here so the tool loop never re-ingests whole article bodies. Combined
  with list-item truncation in the loop, this bounds token cost without ever
  character-slicing the JSON or dropping the ``url``/``source`` metadata the
  frontend source chips need.

Auth
----
Reads ``TAVILY_API_KEY`` from the environment (set in
``packages/worldcup-assistant/.env``). A missing key raises ``WebSearchError``
so ``execute_wc_tool`` reports ``{"status": "error", ...}`` rather than crashing.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

_BASE_URL = "https://api.tavily.com/search"
_DEFAULT_TIMEOUT_S: float = 15.0
#: How many results to ask Tavily for (a wider pool to filter from).
_FETCH_RESULTS: int = 8
#: How many to keep after relevance filtering (what the card/model sees).
_MAX_RESULTS: int = 5
#: Tavily relevance score (0–1) below which a result is dropped as off-topic.
#: Closes the "irrelevant ESPN/MLB result" leak from the news index. Tunable
#: via TAVILY_MIN_SCORE; lower = more permissive, higher = stricter.
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
        raise WebSearchError(
            "TAVILY_API_KEY is not set. Add it to "
            "packages/worldcup-assistant/.env"
        )
    return key


def _source_from_url(url: str) -> str:
    """Human-readable outlet name from a result URL (e.g. www.bbc.com → bbc.com)."""
    try:
        host = urlparse(url).netloc
    except (ValueError, TypeError):
        return ""
    return host[4:] if host.startswith("www.") else host


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _clean_snippet(text: str) -> str:
    """Flatten markdown/markup so a snippet renders as plain prose.

    Tavily's ``content`` field is raw scraped text — it can carry markdown
    headings (``##``), bold (``**``), list bullets and links. The card renders
    snippets as plain text, so we strip the markup symbols (never the words —
    content is preserved) and collapse whitespace. The model's own ``summary``
    keeps its markdown, which the card renders properly.
    """
    if not text:
        return ""
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links/images → label text
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
        # "advanced" ranks/extracts far better than "basic" — worth the small
        # extra cost for a premium, last-resort feature.
        "search_depth": "advanced",
        # "general" (broad web index), NOT "news": the news topic is a curated,
        # recency-biased, English-wire-heavy sub-index that misses regional
        # (e.g. Spanish football) sources and pulls in tangential sports noise.
        # Measured A/B: a Mitoma squad question scored 0.37 (wrong person) on
        # news vs 0.90 (correct, hamstring injury) on general. Worth ~6 cents
        # extra per query for answers that actually exist.
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

    # Relevance gate: drop off-topic results (the news index can return
    # tangential sports content — NBA/MLB for a football query). Tavily scores
    # every result 0–1; keep only those at/above the threshold, best first.
    # If the API returns no scores at all, fall back to keeping order as-is.
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

    # Drop Tavily's synthesized answer when nothing passed the relevance gate —
    # it was generated from the off-topic pool, so feeding it to the model would
    # reintroduce the junk we just filtered out.
    answer = body.get("answer")
    answer_ok = bool(results) and isinstance(answer, str) and answer.strip()
    return {
        "results": results,
        "answer": answer if answer_ok else None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
