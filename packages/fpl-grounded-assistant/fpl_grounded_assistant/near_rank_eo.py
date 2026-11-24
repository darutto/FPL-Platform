"""Effective ownership (EO) of the managers around a user's overall rank.

Pure compute plus a small background-job service. No tool wiring and no network
at import: the HTTP fetch is injected (default: stdlib urllib, read-only, free
public FPL API).

How it works
------------
1. ``entry/{id}/history/`` gives the user's overall rank for the gameweek.
2. The standings window is the user's page of ``leagues-classic/314/standings``
   plus 2 pages either side (<= 250 managers). Rows are matched by their POSITION
   in the page, never by ``rank`` (managers on equal points share a rank).
3. Every 2nd manager in the window (the user excluded) has their picks read for the
   gameweek: about 125 managers, about 131 requests, 17-35 s. That is too slow for a
   chat turn, so the work runs as a background job and callers poll ``status``.
4. EO is ``sum(multiplier) / n``, with ownership, captaincy and bench shares, using
   the same maths as ``scripts/tier_eo_top10k.py`` (a test keeps them equal).

Guards: one global rate limiter shared by every job, at most ``max_jobs`` jobs at a
time (the rest queue, up to ``max_queued``), single-flight per ``(season, gw,
entry)``, a request budget per job, retries with backoff that honour Retry-After,
and a circuit breaker that stops all FPL calls for a while after repeated failures.

Privacy: the cache holds aggregates only (never a neighbour's entry id, name or
picks), keyed by the requesting user's own entry id, in process memory, until
``valid_until`` (the next deadline). Nothing is written to R2 or disk.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

BASE = "https://fantasy.premierleague.com/api"
OVERALL_LEAGUE = 314
PAGE_SIZE = 50
WINDOW_PAGES = 2            # pages either side of the user's page
EVERY = 2                   # every 2nd manager in the window
USER_AGENT = "fpl-platform-near-rank-eo/1.0 (read-only, rate limited)"
TIMEOUT_S = 15

MIN_INTERVAL_S = 0.125      # global cap: 8 requests per second across all jobs
WORKERS = 4                 # parallel picks calls inside one job
MAX_ATTEMPTS = 3
JOB_BUDGET = 250            # requests per job (a normal job needs ~131)
MIN_SAMPLES = 60            # fewer than this and the answer is "unavailable"
ETA_S = 30
DEFAULT_TTL_S = 6 * 3600
NEGATIVE_TTL_S = 300        # a failed compute is not retried for 5 minutes
BREAKER_THRESHOLD = 5
BREAKER_COOLDOWN_S = 60.0

Fetch = Callable[[str], "tuple[int | None, Any, dict[str, str]]"]


def http_get(url: str) -> tuple[int | None, Any, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, None, dict(exc.headers or {})
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ConnectionError(type(exc).__name__) from None


class Unavailable(Exception):
    """The compute cannot produce an answer; ``reason`` is a short machine word."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RateLimiter:
    """Spaces requests at least ``min_interval`` apart across all threads."""

    def __init__(self, min_interval: float = MIN_INTERVAL_S, *, clock=time.monotonic, sleep=time.sleep):
        self._min, self._clock, self._sleep = min_interval, clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            slot = max(now, self._next)
            self._next = slot + self._min
        if slot > now:
            self._sleep(slot - now)


class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures; closed again after ``cooldown``."""

    def __init__(self, threshold: int = BREAKER_THRESHOLD, cooldown: float = BREAKER_COOLDOWN_S, *,
                 clock=time.monotonic):
        self._threshold, self._cooldown, self._clock = threshold, cooldown, clock
        self._fails = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at >= self._cooldown:
                self._opened_at, self._fails = None, 0
                return True
            return False

    def success(self) -> None:
        with self._lock:
            self._fails = 0

    def failure(self) -> None:
        with self._lock:
            self._fails += 1
            if self._fails >= self._threshold and self._opened_at is None:
                self._opened_at = self._clock()


class _Api:
    """One job's view of the FPL API: global limiter, shared breaker, own budget."""

    def __init__(self, fetch: Fetch, limiter: RateLimiter, breaker: CircuitBreaker, budget: int, sleep):
        self._fetch, self._limiter, self._breaker, self._sleep = fetch, limiter, breaker, sleep
        self._budget, self._lock = budget, threading.Lock()
        self.requests = 0

    def get(self, url: str) -> Any | None:
        """The JSON body, or None (404, or MAX_ATTEMPTS failures). Raises Unavailable on budget/breaker."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if not self._breaker.allow():
                raise Unavailable("fpl_api_unavailable")
            with self._lock:
                if self.requests >= self._budget:
                    raise Unavailable("request_budget")
                self.requests += 1
            self._limiter.acquire()
            try:
                status, body, headers = self._fetch(url)
            except ConnectionError:
                status, body, headers = None, None, {}
            if status == 200 and body is not None:
                self._breaker.success()
                return body
            if status == 404:
                self._breaker.success()
                return None
            self._breaker.failure()
            if attempt < MAX_ATTEMPTS:
                try:
                    retry_after = float(headers.get("Retry-After", 0))
                except (TypeError, ValueError):
                    retry_after = 0.0
                self._sleep(max(retry_after, 1.0 * attempt))
        return None


# -- pure pieces -------------------------------------------------------------------------

def rank_page(rank: int) -> int:
    return (rank - 1) // PAGE_SIZE + 1


def window_pages(rank: int) -> list[int]:
    page = rank_page(rank)
    return list(range(max(1, page - WINDOW_PAGES), page + WINDOW_PAGES + 1))


def user_rank_for_gw(history: dict[str, Any], gw: int) -> int | None:
    for row in history.get("current") or []:
        if row.get("event") == gw:
            rank = row.get("overall_rank")
            return int(rank) if isinstance(rank, int) and rank > 0 else None
    return None


def pick_window_entries(pages: dict[int, list[dict[str, Any]]], own_entry: int) -> list[int]:
    """Every EVERY-th position across the fetched pages, the user excluded; entry ids only."""
    chosen: list[int] = []
    for page in sorted(pages):
        for i, row in enumerate(pages[page]):
            position = (page - 1) * PAGE_SIZE + i + 1
            entry = row.get("entry")
            if position % EVERY == 0 and entry and entry != own_entry:
                chosen.append(int(entry))
    return chosen


def compact_picks(body: dict[str, Any]) -> dict[str, Any] | None:
    picks = body.get("picks")
    if not picks:
        return None
    return {"chip": body.get("active_chip"),
            "p": [[p["element"], p["multiplier"], bool(p.get("is_captain")), p["position"]] for p in picks]}


def compute_eo(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-player owned / captain / bench / EO percentages (identical to scripts/tier_eo_top10k.py)."""
    n = len(samples)
    players: dict[int, dict[str, float]] = {}
    chips: dict[str, int] = {}
    for s in samples:
        if s.get("chip"):
            chips[s["chip"]] = chips.get(s["chip"], 0) + 1
        for element, mult, is_cap, _pos in s["p"]:
            row = players.setdefault(element, {"owned": 0, "captain": 0, "bench": 0, "mult": 0})
            row["owned"] += 1
            row["mult"] += mult
            row["captain"] += 1 if is_cap else 0
            row["bench"] += 1 if mult == 0 else 0

    def pct(x: float) -> float:
        return round(100.0 * x / n, 1) if n else 0.0

    return {
        "players": {
            str(el): {"owned_pct": pct(r["owned"]), "captain_pct": pct(r["captain"]),
                      "bench_pct": pct(r["bench"]), "eo": pct(r["mult"])}
            for el, r in sorted(players.items())
        },
        "chips": {f"{name}_pct": pct(count) for name, count in sorted(chips.items())},
    }


def _private_leagues(entry_body: dict[str, Any]) -> list[dict[str, Any]]:
    from .league_eo import private_leagues  # noqa: PLC0415  (lazy: league_eo imports this module)

    return private_leagues(entry_body)


def compute_near_rank_eo(entry_id: int, season: str, gw: int, api: _Api, *, workers: int = WORKERS,
                         now: datetime | None = None) -> dict[str, Any]:
    """Run one compute. Raises ``Unavailable`` (never anything else for an API problem)."""
    history = api.get(f"{BASE}/entry/{entry_id}/history/")
    rank = user_rank_for_gw(history or {}, gw)
    if rank is None:
        raise Unavailable("no_rank")
    entry_body = api.get(f"{BASE}/entry/{entry_id}/") or {}  # the user's league names (for the "EO in <league>" chip)

    pages: dict[int, list[dict[str, Any]]] = {}
    for page in window_pages(rank):
        body = api.get(f"{BASE}/leagues-classic/{OVERALL_LEAGUE}/standings/?page_standings={page}")
        results = ((body or {}).get("standings") or {}).get("results") or []
        if results:
            pages[page] = results
    if not pages:
        raise Unavailable("standings_unavailable")

    entries = pick_window_entries(pages, entry_id)

    def fetch_picks(entry: int) -> dict[str, Any] | None:
        body = api.get(f"{BASE}/entry/{entry}/event/{gw}/picks/")
        return compact_picks(body) if body else None

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = list(pool.map(fetch_picks, entries))
    else:
        fetched = [fetch_picks(e) for e in entries]
    samples = [s for s in fetched if s]
    if len(samples) < MIN_SAMPLES:
        raise Unavailable("too_few_samples")

    ordered = sorted(pages)
    return {
        "schema_version": 1, "season": season, "gw": gw, "tier": "near", "basis": "locked",
        "approx": True, "user_rank": rank,
        "leagues": [{"id": lg["id"], "name": lg["name"]} for lg in _private_leagues(entry_body)],
        "n_sampled": len(samples), "n_target": len(entries),
        "window": {"pages": [ordered[0], ordered[-1]], "every": EVERY},
        "sampled_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        **compute_eo(samples),
    }


# -- the background-job service --------------------------------------------------------------

_SHARED: dict[str, Any] = {}
_SHARED_LOCK = threading.Lock()


def shared_limiter() -> RateLimiter:
    """The one process-wide limiter: every service shares it, so 8 req/s holds for ALL jobs."""
    with _SHARED_LOCK:
        return _SHARED.setdefault("limiter", RateLimiter())


def shared_breaker() -> CircuitBreaker:
    with _SHARED_LOCK:
        return _SHARED.setdefault("breaker", CircuitBreaker())


class JobService:
    """Background-job plumbing shared by the EO services: a result cache, single-flight,
    a bounded queue, negative caching, and the limiter / breaker / budget guards.

    A subclass decides what a key means and what work a key needs; this class only
    runs ``work(api)`` in the pool and caches ``{"status": "ready", "data": ...}``
    (until ``valid_until``) or ``{"status": "unavailable", "reason": ...}`` (for
    NEGATIVE_TTL_S). Nothing here ever waits for a job.
    """

    thread_prefix = "eo-job"

    def __init__(self, fetch: Fetch = http_get, *, limiter: RateLimiter | None = None,
                 breaker: CircuitBreaker | None = None, max_jobs: int = 2, max_queued: int = 20,
                 workers: int = WORKERS, job_budget: int = JOB_BUDGET, executor=None,
                 clock=time.time, sleep=time.sleep):
        self._fetch = fetch
        self._limiter = limiter or shared_limiter()
        self._breaker = breaker or shared_breaker()
        self._workers, self._job_budget, self._max_queued = workers, job_budget, max_queued
        self._clock, self._sleep = clock, sleep
        self._executor = executor or ThreadPoolExecutor(max_workers=max_jobs, thread_name_prefix=self.thread_prefix)
        self._lock = threading.Lock()
        self._cache: dict[Any, tuple[float, dict[str, Any]]] = {}
        self._inflight: set[Any] = set()
        self.started = 0  # jobs submitted so far (a counter, for the warm-up's load figure)

    def _peek(self, key: Any) -> dict[str, Any] | None:
        """A cached, unexpired result for *key*, or None."""
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > self._clock():
                return hit[1]
            if hit:
                del self._cache[key]
            return None

    def peek_ready(self, key: Any) -> dict[str, Any] | None:
        """The data of a cached, unexpired READY result for *key*, else None. Never starts a job, never waits."""
        hit = self._peek(key)
        return hit["data"] if hit is not None and hit.get("status") == "ready" else None

    def _claim(self, key: Any) -> bool:
        """Mark *key* in flight; False if it already is (single-flight)."""
        with self._lock:
            if key in self._inflight:
                return False
            self._inflight.add(key)
            return True

    def _store(self, key: Any, result: dict[str, Any], expires: float) -> None:
        with self._lock:
            self._cache[key] = (expires, result)

    def _release(self, key: Any) -> None:
        with self._lock:
            self._inflight.discard(key)

    def _outcome(self, work, valid_until: float | None, ttl: float = DEFAULT_TTL_S) -> tuple[dict[str, Any], float]:
        """Run *work(api)*; the cache entry and its expiry. Never raises."""
        api = _Api(self._fetch, self._limiter, self._breaker, self._job_budget, self._sleep)
        try:
            data = work(api)
            return {"status": "ready", "data": data}, (valid_until if valid_until is not None else self._clock() + ttl)
        except Unavailable as exc:
            return {"status": "unavailable", "reason": exc.reason}, self._clock() + NEGATIVE_TTL_S
        except Exception:  # noqa: BLE001  (a bug must not kill the worker or leave the key stuck)
            return {"status": "unavailable", "reason": "error"}, self._clock() + NEGATIVE_TTL_S

    def _lookup_or_start(self, key: Any, work, valid_until: float | None, *, ttl: float = DEFAULT_TTL_S) -> dict[str, Any]:
        """The cached result, ``computing`` (job running or just started), or ``busy``."""
        hit = self._peek(key)
        if hit is not None:
            return hit
        with self._lock:
            if key in self._inflight:
                return {"status": "computing", "eta_s": ETA_S}
            if len(self._inflight) >= self._max_queued:
                return {"status": "unavailable", "reason": "busy"}
            self._inflight.add(key)
            self.started += 1
        self._executor.submit(self._run, key, work, valid_until, ttl)
        return {"status": "computing", "eta_s": ETA_S}

    def _run(self, key: Any, work, valid_until: float | None, ttl: float) -> None:
        result, expires = self._outcome(work, valid_until, ttl)
        with self._lock:
            self._cache[key] = (expires, result)
            self._inflight.discard(key)


class NearRankEOService(JobService):
    """``status(season, gw, entry_id)`` -> ready | computing | unavailable, starting a job when needed."""

    thread_prefix = "near-eo"

    def status(self, season: str, gw: int, entry_id: int, *, valid_until: float | None = None) -> dict[str, Any]:
        def work(api: _Api) -> dict[str, Any]:
            return compute_near_rank_eo(entry_id, season, gw, api, workers=self._workers)

        return self._lookup_or_start((season, gw, entry_id), work, valid_until)

    def peek(self, season: str, gw: int, entry_id: int) -> dict[str, Any] | None:
        """The ready near-rank data for this user and gameweek if it is already cached, else None (no job)."""
        return self.peek_ready((season, gw, entry_id))
