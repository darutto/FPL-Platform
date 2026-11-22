"""Effective ownership (EO) of the user's own mini-league.

Pure compute plus a job service on the shared plumbing in ``near_rank_eo.JobService``
(the same limiter, circuit breaker, queue, single-flight and negative cache as the
near-rank tier). No tool wiring and no network at import: the fetch is injected.

Which league
------------
Only a private classic mini-league the user belongs to: ``leagues.classic[]`` of
``entry/{id}/`` with ``league_type == "x"`` and ``scoring == "c"``. System leagues
(overall, country, club) are out: they are huge and the global tiers cover them.
The membership list is cached per user (1 h) and checked on EVERY call, so nobody
can ask for a league they are not in.

Sample or full
--------------
The size is ``rank_count`` from that league list, known before any standings call.
* 3..100 members: every member's picks are read (``exact``).
* 101..2,000 members: 100 members spread evenly over the table (``approx``).
* fewer than 3 or more than 2,000: ``league_too_small`` / ``league_too_large``.
Members without picks for the gameweek (they joined later) are left out and
``n_sampled`` says how many were read. EVERY member counts, the user included,
so the result is "the league's EO" and one cached result serves all its members.

Cost: 1 league-list request + ceil(N/50) standings pages (only those needed) + one
picks call per member read; a 12-member league is ~14 requests, 100 members ~103.

Privacy: aggregates only; no manager name or id is kept. The league name shown is
the user's own league's.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .near_rank_eo import (
    BASE,
    PAGE_SIZE,
    JobService,
    Unavailable,
    _Api,
    compact_picks,
    compute_eo,
)

MIN_MEMBERS = 3
MAX_EXACT = 100
MAX_MEMBERS = 2_000
SAMPLE_N = 100
LEAGUES_TTL_S = 3600.0
MIN_SAMPLES = 3


def private_leagues(entry_body: dict[str, Any]) -> list[dict[str, Any]]:
    """The user's private classic mini-leagues: ``[{id, name, size}]`` (largest last)."""
    out = []
    for league in ((entry_body.get("leagues") or {}).get("classic")) or []:
        if league.get("league_type") == "x" and league.get("scoring") == "c" and league.get("id"):
            size = league.get("rank_count")
            out.append({"id": int(league["id"]), "name": str(league.get("name") or ""),
                        "size": int(size) if isinstance(size, int) else 0})
    return sorted(out, key=lambda lg: (lg["size"], lg["id"]))


def check_size(size: int) -> str | None:
    """The unavailable reason for a league of *size* members, or None when it can be read."""
    if size < MIN_MEMBERS:
        return "league_too_small"
    if size > MAX_MEMBERS:
        return "league_too_large"
    return None


def league_positions(size: int) -> list[int]:
    """The table positions (1-based) whose picks are read: all of them up to MAX_EXACT,
    else SAMPLE_N spread evenly over the table."""
    if size <= MAX_EXACT:
        return list(range(1, size + 1))
    return [min(size, int((k + 0.5) * size / SAMPLE_N) + 1) for k in range(SAMPLE_N)]


def compute_league_eo(league: dict[str, Any], season: str, gw: int, api: _Api, *, workers: int = 4,
                      now: datetime | None = None) -> dict[str, Any]:
    """Run one league compute. Raises ``Unavailable`` for every API problem."""
    size = league["size"]
    reason = check_size(size)
    if reason:
        raise Unavailable(reason)
    positions = league_positions(size)

    entries: list[int] = []
    for page in sorted({(p - 1) // PAGE_SIZE + 1 for p in positions}):
        body = api.get(f"{BASE}/leagues-classic/{league['id']}/standings/?page_standings={page}")
        rows = ((body or {}).get("standings") or {}).get("results") or []
        for position in positions:
            if (position - 1) // PAGE_SIZE + 1 == page and (position - 1) % PAGE_SIZE < len(rows):
                entry = rows[(position - 1) % PAGE_SIZE].get("entry")
                if entry:
                    entries.append(int(entry))
    if not entries:
        raise Unavailable("standings_unavailable")

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

    exact = size <= MAX_EXACT
    return {
        "schema_version": 1, "season": season, "gw": gw, "tier": "league", "basis": "locked",
        "league_id": league["id"], "league_name": league["name"], "league_size": size,
        "exact": exact, "approx": not exact,
        "n_sampled": len(samples), "n_target": len(entries),
        "label": f"{'exact' if exact else 'approx.'}, n={len(samples)} of {size}",
        "sampled_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        **compute_eo(samples),
    }


class LeagueEOService(JobService):
    """``status(season, gw, entry_id, league_id)`` -> ready | computing | unavailable.

    With ``league_id=None`` it answers the picker: ``ready`` with ``data["leagues"]``
    (the user's private leagues), so the assistant can ask which one.
    """

    thread_prefix = "league-eo"

    def status(self, season: str, gw: int, entry_id: int, league_id: int | None = None, *,
               valid_until: float | None = None) -> dict[str, Any]:
        leagues_key = ("leagues", entry_id)
        listed = self._peek(leagues_key)
        if listed is None:
            return self._lookup_or_start(
                leagues_key, self._leagues_work(season, gw, entry_id, league_id, valid_until),
                None, ttl=LEAGUES_TTL_S)
        if listed["status"] != "ready":
            return listed
        leagues = listed["data"]["leagues"]
        if league_id is None:
            return listed
        league = next((lg for lg in leagues if lg["id"] == league_id), None)
        if league is None:
            return {"status": "unavailable", "reason": "not_a_member"}  # checked on every call
        reason = check_size(league["size"])
        if reason:
            return {"status": "unavailable", "reason": reason}
        return self._lookup_or_start(("league", season, gw, league_id),
                                     self._league_work(league, season, gw), valid_until)

    def _league_work(self, league: dict[str, Any], season: str, gw: int):
        def work(api: _Api) -> dict[str, Any]:
            return compute_league_eo(league, season, gw, api, workers=self._workers)
        return work

    def _leagues_work(self, season: str, gw: int, entry_id: int, league_id: int | None, valid_until: float | None):
        """List the user's leagues (1 request); if a league was asked for, compute it in the same job
        so the user waits once, not twice."""
        def work(api: _Api) -> dict[str, Any]:
            body = api.get(f"{BASE}/entry/{entry_id}/")
            if not body:
                raise Unavailable("entry_unavailable")
            leagues = private_leagues(body)
            league = next((lg for lg in leagues if lg["id"] == league_id), None) if league_id else None
            key = ("league", season, gw, league_id)
            if league and check_size(league["size"]) is None and self._peek(key) is None and self._claim(key):
                try:
                    result, expires = self._outcome(self._league_work(league, season, gw), valid_until)
                    self._store(key, result, expires)
                finally:
                    self._release(key)
            return {"leagues": leagues}
        return work
