"""Per-gameweek player data from ``event/{gw}/live`` for the query layer: fetched once, checked, cached.

``GwLiveCache.load(gameweeks, bootstrap)`` returns a :class:`GwBatch`:

* ``gameweeks`` -- :class:`GwData` per gameweek that passed every check;
* ``unavailable`` -- ``{gw: reason}`` for each requested gameweek that cannot be served;
* ``bad_metrics`` -- additive metrics whose gameweek sums disagree with the season totals;
* ``invariant`` -- ``passed`` | ``failed`` | ``not_checked``.

Rules:

* **Absent means 0.** A player with no row in a served gameweek scored 0 on every metric that week
  (:meth:`GwData.value`). A gameweek that is *unavailable* is never 0: it is missing.
* **Checks per gameweek** (a payload failing one is refused and not cached): the season of the gameweek's
  fixtures is the bootstrap's season; the fixture ids in ``explain`` are that gameweek's fixtures (the
  payload carries no gameweek number, so this is what catches a swapped payload); every row carries every
  additive field as a number.
* **Revision** = ``data_checked`` + payload hash. A gameweek loaded with ``data_checked`` true is kept for
  the life of the process; a ``data_checked`` flip drops that gameweek only. One loaded before the check is
  provisional and refetched after ``PROVISIONAL_TTL_S``.
* **Additivity invariant.** Over all started gameweeks, each metric's sum equals the bootstrap season total
  for every player. It runs only when all of them are loaded and no match is waiting for its final data. A
  metric that fails is listed in ``bad_metrics``; the others stay usable. A failure also refetches the cached
  gameweeks once per ``REVALIDATE_COOLDOWN_S``, because a late correction looks exactly like this.
* **One fetch per gameweek** however many requests wait for it, on this module's own HTTP session, inside
  ``TURN_BUDGET_S``.

Nothing imports this module at runtime yet (query layer, PR 2).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

import requests

from fpl_api_client.fpl_client import get_all_fixtures, get_event_live

from fpl_grounded_assistant.query_catalogue import METRICS, metric_ids

TURN_BUDGET_S: float = 6.0
PROVISIONAL_TTL_S: float = 60.0
FIXTURES_TTL_S: float = 60.0
REVALIDATE_COOLDOWN_S: float = 600.0
SUM_TOLERANCE: float = 0.005  # the source has two decimals
_WORKERS: int = 8
_FIXTURES_KEY = "fixtures"

#: metric id -> the source field, in the live payload and in bootstrap ``elements`` alike.
ADDITIVE_FIELDS: Mapping[str, str] = MappingProxyType({m: METRICS[m].field for m in metric_ids("additive")})

# Reasons a gameweek is unavailable.
NOT_STARTED = "not_started"
FETCH_FAILED = "fetch_failed"
TIMEOUT = "timeout"
SEASON_MISMATCH = "season_mismatch"
FIXTURE_MISMATCH = "fixture_mismatch"
BAD_PAYLOAD = "bad_payload"


@dataclass(frozen=True)
class GwData:
    gameweek: int
    status: str                                               # final | provisional
    revision: str                                             # "<data_checked 0|1>:<payload hash>"
    data_checked: bool
    fixtures: tuple[Mapping[str, Any], ...]                   # this gameweek's rows from /fixtures/
    rows: Mapping[int, Mapping[str, float]]                   # element id -> metric id -> value (GW total)
    fixture_minutes: Mapping[int, Mapping[int, int]]          # element id -> fixture id -> minutes (> 0 only)

    def value(self, element_id: int, metric: str) -> float:
        """The player's value this gameweek; a player with no row has 0."""
        if metric not in ADDITIVE_FIELDS:
            raise KeyError(metric)
        row = self.rows.get(element_id)
        return row[metric] if row is not None else 0.0


@dataclass(frozen=True)
class GwBatch:
    gameweeks: Mapping[int, GwData]
    unavailable: Mapping[int, str]
    bad_metrics: frozenset[str]
    invariant: str                                            # passed | failed | not_checked


@dataclass(frozen=True)
class _Entry:
    data: Any                                                 # GwData, or the fixtures list
    fetched_at: float


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _parse_time(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _started(fixture: Mapping[str, Any]) -> bool:
    return bool(fixture.get("started") or fixture.get("finished") or fixture.get("finished_provisional"))


def _check_season(fixtures: Iterable[Mapping[str, Any]], bootstrap: Mapping[str, Any]) -> None:
    """Every kickoff falls in the year that starts at the bootstrap's GW1 deadline."""
    first = next((e for e in bootstrap.get("events") or [] if e.get("id") == 1), None)
    start = _parse_time((first or {}).get("deadline_time"))
    if start is None:
        raise _Refused(SEASON_MISMATCH)
    for fixture in fixtures:
        kickoff = _parse_time(fixture.get("kickoff_time"))
        if kickoff is None or not start <= kickoff < start + timedelta(days=365):
            raise _Refused(SEASON_MISMATCH)


def _parse_payload(
    gameweek: int, payload: Any, fixtures: tuple[Mapping[str, Any], ...], data_checked: bool,
) -> GwData:
    """Check one live payload against its gameweek's fixtures and turn it into a :class:`GwData`."""
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list) or (fixtures and not elements) or (not fixtures and elements):
        raise _Refused(BAD_PAYLOAD)
    rows: dict[int, Mapping[str, float]] = {}
    fixture_minutes: dict[int, Mapping[int, int]] = {}
    seen: set[int] = set()
    try:
        for element in elements:
            element_id = int(element["id"])
            stats = element["stats"]
            if element_id in rows:
                raise _Refused(BAD_PAYLOAD)
            rows[element_id] = MappingProxyType({m: float(stats[f]) for m, f in ADDITIVE_FIELDS.items()})
            minutes: dict[int, int] = {}
            for part in element["explain"]:
                fixture_id = int(part["fixture"])
                seen.add(fixture_id)
                for stat in part["stats"]:
                    if stat["identifier"] == "minutes" and int(stat["value"]) > 0:
                        minutes[fixture_id] = int(stat["value"])
            if minutes:
                fixture_minutes[element_id] = MappingProxyType(minutes)
    except (KeyError, TypeError, ValueError):
        raise _Refused(BAD_PAYLOAD) from None
    ids = {int(f["id"]) for f in fixtures}
    required = ids if data_checked else {int(f["id"]) for f in fixtures if _started(f)}
    if not required <= seen <= ids:
        raise _Refused(FIXTURE_MISMATCH)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    final = data_checked and all(f.get("finished") or f.get("finished_provisional") for f in fixtures)
    return GwData(
        gameweek=gameweek,
        status="final" if final else "provisional",
        revision=f"{int(data_checked)}:{digest}",
        data_checked=data_checked,
        fixtures=fixtures,
        rows=MappingProxyType(rows),
        fixture_minutes=MappingProxyType(fixture_minutes),
    )


class GwLiveCache:
    """Per-process cache of checked gameweeks. Use :func:`default_cache` outside tests."""

    def __init__(
        self,
        *,
        fetch_live: Callable[..., Any] = get_event_live,
        fetch_fixtures: Callable[..., Any] = get_all_fixtures,
        session: requests.Session | None = None,
        budget_s: float = TURN_BUDGET_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch_live = fetch_live
        self._fetch_fixtures = fetch_fixtures
        self._session = session or requests.Session()
        self._budget_s = budget_s
        self._clock = clock                                   # ages entries; deadlines use time.monotonic
        self._lock = threading.Lock()
        self._entries: dict[Any, _Entry] = {}
        self._inflight: dict[Any, Future] = {}
        self._revalidated_at: float | None = None
        self._pool = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="gw-live")

    # -- single flight ------------------------------------------------------

    def _submit(self, key: Any, work: Callable[[float], Any], fresh: Callable[[_Entry], bool]) -> Future:
        """A future for *key*: the cached value, the fetch already running, or a new one."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and fresh(entry):
                done: Future = Future()
                done.set_result(entry.data)
                return done
            running = self._inflight.get(key)
            if running is not None:
                return running
            self._entries.pop(key, None)
            future: Future = Future()
            self._inflight[key] = future
        self._pool.submit(self._run, key, work, future)
        return future

    def _run(self, key: Any, work: Callable[[float], Any], future: Future) -> None:
        try:
            data = work(time.monotonic() + self._budget_s)
        except BaseException as exc:  # noqa: BLE001 -- handed to every waiter; failures are not cached
            with self._lock:
                self._inflight.pop(key, None)
            future.set_exception(exc)
            return
        with self._lock:
            self._entries[key] = _Entry(data, self._clock())
            self._inflight.pop(key, None)
        future.set_result(data)

    @staticmethod
    def _result(future: Future) -> tuple[Any, str | None]:
        if not future.done():
            return None, TIMEOUT
        exc = future.exception()
        if exc is None:
            return future.result(), None
        if isinstance(exc, _Refused):
            return None, exc.reason
        return None, TIMEOUT if isinstance(exc, requests.Timeout) else FETCH_FAILED

    # -- fetches ------------------------------------------------------------

    def _fixtures(self, deadline: float) -> tuple[Any, str | None]:
        def work(fetch_deadline: float) -> Any:
            payload = self._fetch_fixtures(session=self._session, deadline=fetch_deadline)
            if not isinstance(payload, list) or not payload:
                raise _Refused(BAD_PAYLOAD)
            return payload

        future = self._submit(_FIXTURES_KEY, work, lambda e: self._clock() - e.fetched_at < FIXTURES_TTL_S)
        wait([future], timeout=max(deadline - time.monotonic(), 0))
        return self._result(future)

    def _load_gameweeks(
        self,
        wanted: Mapping[int, tuple[tuple[Mapping[str, Any], ...], bool]],
        bootstrap: Mapping[str, Any],
        deadline: float,
    ) -> tuple[dict[int, GwData], dict[int, str]]:
        futures: dict[int, Future] = {}
        for gameweek, (fixtures, data_checked) in wanted.items():
            def work(fetch_deadline: float, gw=gameweek, fx=fixtures, checked=data_checked) -> GwData:
                _check_season(fx, bootstrap)
                payload = (
                    self._fetch_live(gw, session=self._session, deadline=fetch_deadline) if fx else {"elements": []}
                )
                return _parse_payload(gw, payload, fx, checked)

            def fresh(entry: _Entry, fx=fixtures, checked=data_checked) -> bool:
                cached: GwData = entry.data
                if cached.data_checked != checked:
                    return False
                if {f["id"] for f in cached.fixtures} != {f["id"] for f in fx}:
                    return False
                return cached.status == "final" or self._clock() - entry.fetched_at < PROVISIONAL_TTL_S

            futures[gameweek] = self._submit(gameweek, work, fresh)
        wait(futures.values(), timeout=max(deadline - time.monotonic(), 0))
        loaded: dict[int, GwData] = {}
        failed: dict[int, str] = {}
        for gameweek, future in futures.items():
            data, reason = self._result(future)
            if reason is None:
                loaded[gameweek] = data
            else:
                failed[gameweek] = reason
        return loaded, failed

    # -- public -------------------------------------------------------------

    def load(self, gameweeks: Iterable[int], bootstrap: Mapping[str, Any]) -> GwBatch:
        """Serve *gameweeks* within the turn budget. Never raises for a source failure."""
        requested = sorted(set(gameweeks))
        deadline = time.monotonic() + self._budget_s
        all_fixtures, reason = self._fixtures(deadline)
        if reason is not None:
            return GwBatch(
                MappingProxyType({}), MappingProxyType({gw: reason for gw in requested}), frozenset(), "not_checked",
            )
        by_gw: dict[int, list[Mapping[str, Any]]] = {}
        for fixture in all_fixtures:
            if fixture.get("event") is not None:
                by_gw.setdefault(int(fixture["event"]), []).append(fixture)
        events = {int(e["id"]): e for e in bootstrap.get("events") or []}

        def plan(gameweek: int) -> tuple[tuple[Mapping[str, Any], ...], bool] | None:
            """(fixtures, data_checked) for a started gameweek, else None. A past blank has no fixtures."""
            event = events.get(gameweek)
            if event is None:
                return None
            fixtures = tuple(by_gw.get(gameweek, ()))
            if any(map(_started, fixtures)) or (not fixtures and event.get("finished")):
                return fixtures, bool(event.get("data_checked"))
            return None

        started = {gw: p for gw in events if (p := plan(gw)) is not None}
        # Every started gameweek is loaded, asked for or not: the invariant sums all of them.
        loaded, failed = self._load_gameweeks(started, bootstrap, deadline)
        bad, invariant = self._invariant(started, loaded, bootstrap)
        if bad and self._may_revalidate():
            with self._lock:
                for gameweek in loaded:
                    self._entries.pop(gameweek, None)
            again, again_failed = self._load_gameweeks(started, bootstrap, deadline)
            if not again_failed:
                loaded, failed = again, {}
                bad, invariant = self._invariant(started, loaded, bootstrap)
        unavailable = {gw: failed.get(gw, NOT_STARTED) for gw in requested if gw not in loaded}
        return GwBatch(
            MappingProxyType({gw: loaded[gw] for gw in requested if gw in loaded}),
            MappingProxyType(unavailable),
            bad,
            invariant,
        )

    def _may_revalidate(self) -> bool:
        with self._lock:
            now = self._clock()
            if self._revalidated_at is not None and now - self._revalidated_at < REVALIDATE_COOLDOWN_S:
                return False
            self._revalidated_at = now
            return True

    @staticmethod
    def _invariant(
        started: Mapping[int, Any], loaded: Mapping[int, GwData], bootstrap: Mapping[str, Any],
    ) -> tuple[frozenset[str], str]:
        if not started or len(loaded) != len(started) or any(d.status != "final" for d in loaded.values()):
            return frozenset(), "not_checked"
        bad: set[str] = set()
        elements = bootstrap.get("elements") or []
        if not elements:
            return frozenset(), "not_checked"
        for metric, field in ADDITIVE_FIELDS.items():
            for element in elements:
                try:
                    total = float(element[field])
                except (KeyError, TypeError, ValueError):
                    bad.add(metric)  # no season total to check against
                    break
                summed = sum(data.value(element["id"], metric) for data in loaded.values())
                if abs(summed - total) > SUM_TOLERANCE:
                    bad.add(metric)
                    break
        return frozenset(bad), "failed" if bad else "passed"


_default: GwLiveCache | None = None
_default_lock = threading.Lock()


def default_cache() -> GwLiveCache:
    """The process-wide cache."""
    global _default
    with _default_lock:
        if _default is None:
            _default = GwLiveCache()
        return _default
