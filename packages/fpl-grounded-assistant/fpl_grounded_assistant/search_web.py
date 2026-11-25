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
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import httpx

from fpl_player_registry import normalize_player_name
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


# ---------------------------------------------------------------------------
# Result hygiene: tracking parameters, official-first ranking, PL-first pass
# ---------------------------------------------------------------------------

#: The Premier League's own site: the primary source for a PL player's injury,
#: availability or news. One extra, domain-restricted Tavily call per such turn.
PL_DOMAIN = "premierleague.com"
_PL_MAX_RESULTS: int = 5
#: At most this many official pages are shown; general results fill the rest.
_PL_KEEP: int = 2

#: Query parameters that only track the visitor; stripped from every shown URL.
_TRACKING_PARAMS = frozenset({
    "_gl", "_ga", "_gac", "gclid", "gbraid", "wbraid", "fbclid", "msclkid", "igshid",
    "mc_cid", "mc_eid", "ref_src", "ref_url", "cmpid", "ocid", "ito",
})

#: Preferred-domain tiers (lower = earlier). Only a REORDER: no domain is ever
#: dropped. Anything unlisted sits between the major outlets and the social /
#: aggregator pages. Subdomains count (news.bbc.co.uk is bbc.co.uk).
_TIER_OFFICIAL = ("premierleague.com",)
_TIER_MAJOR = (
    "bbc.co.uk", "bbc.com", "skysports.com", "theguardian.com", "telegraph.co.uk",
    "theathletic.com", "nytimes.com", "espn.com", "reuters.com", "apnews.com",
    "independent.co.uk", "standard.co.uk", "thetimes.co.uk", "uefa.com",
)
_TIER_SOCIAL_OR_AGGREGATOR = (
    "x.com", "twitter.com", "facebook.com", "instagram.com", "threads.net", "tiktok.com",
    "reddit.com", "youtube.com", "dongqiudi.com", "flipboard.com", "newsbreak.com",
)


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except (ValueError, TypeError):
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _on_domain(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def clean_url(url: str) -> str:
    """The URL without tracking query parameters (``_gl``, ``_ga``, ``utm_*``, ...)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def _dedupe_key(url: str) -> str:
    parts = urlsplit(clean_url(url))
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return f"{_host(url)}{parts.path.rstrip('/')}?{query}"


def domain_tier(url: str) -> int:
    """0 official, 1 major outlet, 2 everything else, 3 social / aggregator."""
    host = _host(url)
    if _on_domain(host, _TIER_OFFICIAL):
        return 0
    if _on_domain(host, _TIER_MAJOR):
        return 1
    if _on_domain(host, _TIER_SOCIAL_OR_AGGREGATOR):
        return 3
    return 2


def rank_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by cleaned URL, clean the shown URL, then order by domain tier.

    The sort is stable: inside a tier the incoming order (the relevance order, and
    the premierleague.com results first among the official ones) is kept.
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in results:
        url = item.get("url") or ""
        key = _dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        unique.append({**item, "url": clean_url(url), "source": _source_from_url(clean_url(url))})
    return sorted(unique, key=lambda it: domain_tier(it["url"]))


def is_player_availability_query(query: str, bootstrap: dict[str, Any] | None) -> bool:
    """True when *query* asks about injury / availability / news of a PL player.

    Both halves must hold: an availability word (the same whole-word list that
    diverts the player lookup) and a surname or web name from the bootstrap as a
    whole word. No bootstrap -> False, so nothing else ever pays for the extra call.
    """
    if not bootstrap or not query:
        return False
    from .player_lookup import has_availability_intent  # noqa: PLC0415  (lazy: avoids a cycle)

    if not has_availability_intent(query):
        return False
    padded = f" {normalize_player_name(query)} "
    for element in bootstrap.get("elements") or []:
        for field in ("web_name", "second_name"):
            name = normalize_player_name(element.get(field))
            if len(name) >= 3 and f" {name} " in padded:
                return True
    return False


def _query_terms(query: str, bootstrap: dict[str, Any] | None) -> set[str]:
    """Normalised names that make a result about the player asked: surname / web
    name plus his club's name and short name (whole-word matches in the query)."""
    padded = f" {normalize_player_name(query)} "
    teams = {t.get("id"): t for t in (bootstrap or {}).get("teams") or []}
    terms: set[str] = set()
    for element in (bootstrap or {}).get("elements") or []:
        hit = False
        for field in ("web_name", "second_name"):
            name = normalize_player_name(element.get(field))
            if len(name) >= 3 and f" {name} " in padded:
                hit = True
                terms.add(name)
        if hit:
            team = teams.get(element.get("team")) or {}
            for field in ("name", "short_name"):
                name = normalize_player_name(team.get(field))
                if len(name) >= 3:
                    terms.add(name)
    return terms


def _mentions(item: dict[str, Any], terms: set[str]) -> bool:
    text = f" {normalize_player_name((item.get('title') or '') + ' ' + (item.get('snippet') or ''))} "
    return any(f" {t} " in text for t in terms)


def _published_ts(item: dict[str, Any]) -> float | None:
    raw = item.get("published")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _freshest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first when a date is given; undated items keep their order, after."""
    dated = [(ts, it) for it in items if (ts := _published_ts(it)) is not None]
    undated = [it for it in items if _published_ts(it) is None]
    return [it for _, it in sorted(dated, key=lambda p: p[0], reverse=True)] + undated


def _tavily(payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """One Tavily call -> the decoded JSON body (``results``, ``answer``)."""
    try:
        resp = httpx.post(_BASE_URL, json=payload, timeout=timeout_s)
    except httpx.TimeoutException as exc:
        raise WebSearchError(f"web search timed out after {timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise WebSearchError(f"{type(exc).__name__}: {exc}") from exc

    if resp.status_code >= 400:
        raise WebSearchError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        return resp.json()
    except ValueError as exc:
        raise WebSearchError("web search returned non-JSON body") from exc


def _shape(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score-filter (when scores exist) and shape raw Tavily items."""
    min_score = _min_score()
    has_scores = any(isinstance(it.get("score"), (int, float)) for it in raw_items)
    if has_scores:
        kept = [it for it in raw_items if (it.get("score") or 0.0) >= min_score]
        kept.sort(key=lambda it: it.get("score") or 0.0, reverse=True)
    else:
        kept = list(raw_items)
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
    return results


def search_web(
    query: str,
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    bootstrap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one focused web search and return a card-ready envelope.

    Returns ``{"results": [{title, snippet, url, source, published}],
    "answer": str | None, "timestamp": iso}``. ``answer`` is model input only.
    Raises ``WebSearchError`` on any failure so the executor can surface it as
    a tool-level error the LLM can react to.

    For a PL player's injury / availability / news query (see
    :func:`is_player_availability_query`) a SECOND call restricted to
    premierleague.com runs and its results come first; if it fails or returns
    nothing the normal results stand. Every result list is deduplicated,
    stripped of tracking parameters and ordered official > major outlet > other
    > social / aggregator (reorder only, nothing is blocked).
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
    body = _tavily(payload, timeout_s)
    results = _shape(body.get("results") or [])

    pl_results: list[dict[str, Any]] = []
    if is_player_availability_query(query, bootstrap):
        pl_payload = {
            **payload,
            "max_results": _PL_MAX_RESULTS,
            "include_domains": [PL_DOMAIN],
            "include_answer": False,
        }
        try:
            pl_results = _shape(_tavily(pl_payload, timeout_s).get("results") or [])
        except WebSearchError:
            pl_results = []  # the official pass is best-effort; normal results stand

    if is_player_availability_query(query, bootstrap):
        terms = _query_terms(query, bootstrap)
        # official pages must be about this player or his club; the rest are dropped
        pl_results = _freshest_first([r for r in pl_results if _mentions(r, terms)])
        results = [r for r in results if domain_tier(r["url"]) != 0 or _mentions(r, terms)]
    ranked = rank_results(pl_results + results)
    if pl_results:
        official = 0
        capped: list[dict[str, Any]] = []
        for r in ranked:
            if domain_tier(r["url"]) == 0:
                official += 1
                if official > _PL_KEEP:
                    continue
            capped.append(r)
        ranked = capped
    ranked = ranked[:_MAX_RESULTS]

    answer = body.get("answer")
    answer_ok = bool(results) and isinstance(answer, str) and answer.strip()
    return {
        "results": ranked,
        "answer": answer if answer_ok else None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((?:https?://)[^)\s]*\)")
_BARE_URL_RE = re.compile(r"https?://[^\s)\]]+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([.,;:])")
_EMPTY_BULLET_RE = re.compile(r"^[\s\-*•>]+$")
_SOURCE_LABEL_ONLY_RE = re.compile(
    r"^[\s\-*•>]*(?:fuentes?(?:\s+web)?|sources?|web\s+sources?)\s*:?[\s\-*•]*$",
    re.IGNORECASE,
)


def web_search_payload(d: dict[str, Any], answer_text: str) -> "dict[str, Any] | None":
    """The ``web_search`` response field of one ask_v2 result dict, or ``None``.

    One projection for ``POST /ask`` (``harness_adapter``) and the session route
    (``final_response``): non-null when ``search_web`` ran end-to-end, alone or
    beside another tool. The raw output's own ``answer`` is model input only and
    is never surfaced; ``answer_text`` (the displayed text) is the summary.
    """
    if d.get("selected_tool") == "search_web" and d.get("outcome") == "ok":
        raw = d.get("raw_output") or {}
        return {
            "topic": (d.get("tool_input") or {}).get("query"),
            "summary": answer_text,
            "results": raw.get("results") or [],
            "timestamp": raw.get("timestamp"),
        }
    src = d.get("web_search_sources")
    if src:
        return {
            "topic": src.get("topic"),
            "summary": answer_text,
            "results": src.get("results") or [],
            "timestamp": src.get("timestamp"),
        }
    return None


def strip_urls_from_prose(text: str) -> str:
    """Remove links from model prose: the sources are shown separately as titled links.

    ``[title](url)`` keeps its title; a bare URL is dropped; a line left holding only
    a "Fuente web:" style label goes with it. Prose without links is returned unchanged.
    """
    if not text or "http" not in text:
        return text
    out = _MD_LINK_RE.sub(lambda m: m.group(1), text)
    out = _BARE_URL_RE.sub("", out)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    lines = [ln.rstrip() for ln in out.split("\n")]
    lines = [
        ln for ln in lines
        if not _SOURCE_LABEL_ONLY_RE.match(ln) and not _EMPTY_BULLET_RE.match(ln)
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def web_search_sources_from_trace(trace: Any) -> dict[str, Any] | None:
    """The last successful ``search_web`` call of a turn as {topic, results, timestamp}.

    Read off the orchestrator's executed-call trace, whatever other tools ran in the
    same turn, so the cited sources can reach the UI next to e.g. a player card.
    None when no search ran or it returned nothing usable.
    """
    found: dict[str, Any] | None = None
    for entry in trace or ():
        if not isinstance(entry, dict) or entry.get("name") != "search_web":
            continue
        output = entry.get("output") or {}
        results = output.get("results") if isinstance(output, dict) else None
        if output.get("status") not in (None, "ok") or not results:
            continue
        found = {
            "topic": (entry.get("args") or {}).get("query"),
            "results": list(results),
            "timestamp": output.get("timestamp"),
        }
    return found


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

SEARCH_WEB_SPEC = ToolSpec(
    name="search_web",
    description=(
        "Live web search for FPL/football information that NO other tool can "
        "provide: breaking news, suspensions, press-conference quotes, "
        "transfer/lineup rumours, or opinion/prediction questions. NEVER use it "
        "for player stats, prices, fixtures, or form — those have dedicated "
        "tools and are always more reliable. "
        "When the user asks about a player's injury, availability, fitness or "
        "latest news, call search_web as well as get_player_snapshot: FPL's own "
        "status/news can lag behind club news, so answer with both and say "
        "which source says what, in words (\"según el club…\" / \"FPL lo marca…\"), "
        "never by writing URLs or links: the sources are shown to the user "
        "separately. If the question states a figure (e.g. a chance of "
        "playing) that the FPL data contradicts, say what the data shows and "
        "note the difference; never repeat the user's figure as FPL's. "
        "QUERY CONSTRUCTION: `query` must be concise, keyword-heavy, and "
        "stripped of conversational filler (e.g. '<player> injury update "
        "<club>', not the user's raw sentence)."
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
        raw = search_web(query=query, bootstrap=bootstrap)
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
