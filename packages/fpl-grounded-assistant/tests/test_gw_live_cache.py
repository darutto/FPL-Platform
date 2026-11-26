"""gw_live_cache on synthetic gameweeks: single flight, revisions, per-gameweek checks, the sum invariant."""
from __future__ import annotations

import threading
import time
from collections import Counter

import pytest
import requests

from fpl_grounded_assistant import gw_live_cache as glc

METRICS = list(glc.ADDITIVE_FIELDS)
DECIMAL = {"influence", "creativity", "threat", "ict_index", "expected_goals", "expected_assists",
           "expected_goal_involvements", "expected_goals_conceded"}


def _num(metric, value):
    return f"{value:.2f}" if metric in DECIMAL else int(value)


class World:
    """A made-up season: two clubs per fixture, four players, whatever gameweeks a test asks for."""

    def __init__(self, fixtures_per_gw=(1, 1, 1), finished=None):
        self.fixtures, self.events, next_id = [], [], 1
        finished = len(fixtures_per_gw) if finished is None else finished
        for index, count in enumerate(fixtures_per_gw):
            gw, done = index + 1, index < finished
            self.events.append({"id": gw, "finished": done, "data_checked": done,
                                "deadline_time": f"2026-0{8 + index // 4}-{1 + 7 * (index % 4):02d}T17:30:00Z"})
            for _ in range(count):
                self.fixtures.append({"id": next_id, "event": gw, "started": done, "finished": done,
                                      "finished_provisional": done,
                                      "kickoff_time": f"2026-0{8 + index // 4}-{2 + 7 * (index % 4):02d}T14:00:00Z"})
                next_id += 1
        self.calls = Counter()
        self.delay = 0.0
        self.lock = threading.Lock()
        self.payloads = {gw["id"]: self.payload(gw["id"]) if gw["id"] <= finished else {"elements": []}
                         for gw in self.events}

    def payload(self, gw, players=(1, 2, 3)):
        ids = [f["id"] for f in self.fixtures if f["event"] == gw]
        return {"elements": [] if not ids else [
            {"id": p,
             "stats": {glc.ADDITIVE_FIELDS[m]: _num(m, p + gw + i % 3) for i, m in enumerate(METRICS)},
             "explain": [{"fixture": f, "stats": [{"identifier": "minutes", "value": 45 + p, "points": 1}]}
                         for f in ids]}
            for p in players]}

    def bootstrap(self):
        totals = {p: dict.fromkeys(METRICS, 0.0) for p in (1, 2, 3, 4)}  # player 4 never appears
        for payload in self.payloads.values():
            for element in payload["elements"]:
                for m in METRICS:
                    totals[element["id"]][m] += float(element["stats"][glc.ADDITIVE_FIELDS[m]])
        return {"events": [dict(e) for e in self.events],
                "elements": [{"id": p, **{glc.ADDITIVE_FIELDS[m]: _num(m, v) for m, v in t.items()}}
                             for p, t in totals.items()]}

    def fetch_live(self, gw, *, session, deadline):
        with self.lock:
            self.calls[gw] += 1
        if self.delay:
            time.sleep(self.delay)
        return self.payloads[gw]

    def fetch_fixtures(self, *, session, deadline):
        with self.lock:
            self.calls["fixtures"] += 1
        return self.fixtures

    def cache(self, **kwargs):
        kwargs.setdefault("fetch_live", self.fetch_live)
        return glc.GwLiveCache(fetch_fixtures=self.fetch_fixtures, **kwargs)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_the_catalogue_gives_the_27_additive_metrics():
    assert len(METRICS) == 27


def test_a_served_season_passes_the_invariant():
    world = World()
    batch = world.cache().load([1, 2, 3], world.bootstrap())
    assert (sorted(batch.gameweeks), dict(batch.unavailable), batch.invariant) == ([1, 2, 3], {}, "passed")
    assert batch.bad_metrics == frozenset()
    assert {d.status for d in batch.gameweeks.values()} == {"final"}


def test_twenty_concurrent_cold_requests_fetch_each_gameweek_once():
    world = World()
    world.delay = 0.2
    cache, bootstrap = world.cache(), world.bootstrap()
    gate, batches = threading.Barrier(20), []

    def ask():
        gate.wait()
        batches.append(cache.load([1, 2, 3], bootstrap))

    threads = [threading.Thread(target=ask) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(batches) == 20 and all(sorted(b.gameweeks) == [1, 2, 3] for b in batches)
    assert world.calls == {1: 1, 2: 1, 3: 1, "fixtures": 1}


def test_a_data_checked_flip_refetches_only_that_gameweek():
    world = World()
    world.events[2]["data_checked"] = False
    cache = world.cache()
    before = cache.load([1, 2, 3], world.bootstrap())
    assert before.gameweeks[3].status == "provisional" and before.invariant == "not_checked"
    world.events[2]["data_checked"] = True
    after = cache.load([1, 2, 3], world.bootstrap())
    assert (world.calls[1], world.calls[2], world.calls[3]) == (1, 1, 2)
    assert after.gameweeks[3].revision != before.gameweeks[3].revision
    assert after.gameweeks[3].status == "final" and after.invariant == "passed"


def test_a_provisional_gameweek_expires_and_a_final_one_does_not():
    world, clock = World(), Clock()
    world.events[2]["data_checked"] = False
    cache = world.cache(clock=clock)
    cache.load([1], world.bootstrap())
    cache.load([1], world.bootstrap())
    assert world.calls[3] == 1
    clock.now += glc.PROVISIONAL_TTL_S + 1
    cache.load([1], world.bootstrap())
    assert (world.calls[1], world.calls[3]) == (1, 2)


def test_a_swapped_gameweek_payload_is_refused_and_not_cached():
    world = World()
    bootstrap = world.bootstrap()
    right = world.payloads[2]
    world.payloads[2] = world.payloads[1]
    cache = world.cache()
    batch = cache.load([1, 2], bootstrap)
    assert dict(batch.unavailable) == {2: glc.FIXTURE_MISMATCH}
    assert sorted(batch.gameweeks) == [1] and batch.invariant == "not_checked"
    world.payloads[2] = right
    assert sorted(cache.load([1, 2], bootstrap).gameweeks) == [1, 2]


def test_a_checked_gameweek_must_cover_every_one_of_its_fixtures():
    world = World((2,))
    for element in world.payloads[1]["elements"]:
        element["explain"] = element["explain"][:1]
    assert dict(world.cache().load([1], world.bootstrap()).unavailable) == {1: glc.FIXTURE_MISMATCH}


def test_another_season_is_refused():
    world = World()
    bootstrap = world.bootstrap()
    for fixture in world.fixtures:
        fixture["kickoff_time"] = fixture["kickoff_time"].replace("2026", "2025")
    batch = world.cache().load([1], bootstrap)
    assert dict(batch.unavailable) == {1: glc.SEASON_MISMATCH}
    assert world.calls[1] == 0


@pytest.mark.parametrize("damage", [
    lambda p: p["elements"][1]["stats"].pop("tackles"),
    lambda p: p["elements"][1]["stats"].__setitem__("expected_goals", None),
    lambda p: p["elements"][1].pop("explain"),
    lambda p: p["elements"].append(dict(p["elements"][0])),
    lambda p: p["elements"].clear(),
])
def test_a_payload_without_full_field_coverage_is_refused(damage):
    world = World()
    bootstrap = world.bootstrap()
    damage(world.payloads[2])
    assert dict(world.cache().load([2], bootstrap).unavailable) == {2: glc.BAD_PAYLOAD}


def test_a_broken_sum_marks_only_that_metric():
    world = World()
    bootstrap = world.bootstrap()
    bootstrap["elements"][0]["saves"] += 1
    batch = world.cache().load([1, 2, 3], bootstrap)
    assert (batch.bad_metrics, batch.invariant) == (frozenset({"saves"}), "failed")
    assert sorted(batch.gameweeks) == [1, 2, 3]


def test_a_failed_sum_refetches_once_per_cooldown_and_picks_up_a_late_correction():
    world, clock = World(), Clock()
    cache = world.cache(clock=clock)
    cache.load([1], world.bootstrap())
    world.payloads[1]["elements"][0]["stats"]["bonus"] += 1       # corrected at the source, data_checked unchanged
    batch = cache.load([1], world.bootstrap())
    assert batch.invariant == "passed" and world.calls[1] == 2
    wrong = world.bootstrap()
    wrong["elements"][0]["bonus"] += 5
    cache.load([1], wrong)
    cache.load([1], wrong)
    assert world.calls[1] == 2                                    # inside the cooldown: no hammering
    clock.now += glc.REVALIDATE_COOLDOWN_S + 1
    assert cache.load([1], wrong).bad_metrics == frozenset({"bonus"})
    assert world.calls[1] == 3


def test_the_sum_is_not_checked_while_a_match_is_live():
    world = World((1, 1), finished=1)
    world.fixtures[1]["started"] = True
    world.payloads[2] = world.payload(2)
    bootstrap = world.bootstrap()
    bootstrap["elements"][0]["saves"] += 9
    batch = world.cache().load([1, 2], bootstrap)
    assert (batch.invariant, batch.bad_metrics) == ("not_checked", frozenset())
    assert batch.gameweeks[2].status == "provisional"


def test_a_gameweek_that_has_not_started_is_unavailable_and_not_fetched():
    world = World((1, 1), finished=1)
    batch = world.cache().load([1, 2, 30], world.bootstrap())
    assert dict(batch.unavailable) == {2: glc.NOT_STARTED, 30: glc.NOT_STARTED}
    assert world.calls[2] == 0 and batch.invariant == "passed"


def test_an_absent_player_gameweek_counts_as_zero():
    world = World()
    data = world.cache().load([1], world.bootstrap()).gameweeks[1]
    assert data.value(4, "total_points") == 0.0 and data.value(999, "minutes") == 0.0
    assert data.value(1, "total_points") > 0
    with pytest.raises(KeyError):
        data.value(999, "not_a_metric")


def test_a_double_gameweek_keeps_minutes_per_fixture_and_one_total():
    world = World((2, 1))
    batch = world.cache().load([1, 2], world.bootstrap())
    assert dict(batch.gameweeks[1].fixture_minutes[1]) == {1: 46, 2: 46}
    assert dict(batch.gameweeks[2].fixture_minutes[1]) == {3: 46}
    assert batch.invariant == "passed"


def test_a_blank_gameweek_is_served_empty_without_a_fetch():
    world = World((1, 0, 1))
    batch = world.cache().load([1, 2, 3], world.bootstrap())
    assert batch.gameweeks[2].rows == {} and batch.gameweeks[2].value(1, "saves") == 0.0
    assert world.calls[2] == 0 and batch.invariant == "passed"


def test_a_slow_source_fails_inside_the_budget():
    world = World()
    release = threading.Event()

    def slow(gw, *, session, deadline):
        if gw == 2:
            release.wait(5)
            raise requests.Timeout()
        return world.payloads[gw]

    cache = world.cache(fetch_live=slow, budget_s=0.5)
    started = time.monotonic()
    batch = cache.load([1, 2, 3], world.bootstrap())
    elapsed = time.monotonic() - started
    release.set()
    assert elapsed < 2.0
    assert dict(batch.unavailable) == {2: glc.TIMEOUT} and sorted(batch.gameweeks) == [1, 3]


@pytest.mark.parametrize("error,reason", [
    (requests.HTTPError("500"), glc.FETCH_FAILED),
    (requests.ConnectionError(), glc.FETCH_FAILED),
    (ValueError("not json"), glc.FETCH_FAILED),
    (requests.Timeout(), glc.TIMEOUT),
])
def test_a_failing_source_is_reported_and_retried_on_the_next_request(error, reason):
    world = World()
    failing = [True]

    def flaky(gw, *, session, deadline):
        if gw == 3 and failing[0]:
            raise error
        return world.payloads[gw]

    cache, bootstrap = world.cache(fetch_live=flaky), world.bootstrap()
    assert dict(cache.load([3], bootstrap).unavailable) == {3: reason}
    failing[0] = False
    assert sorted(cache.load([3], bootstrap).gameweeks) == [3]


def test_no_fixture_list_means_nothing_is_served():
    world = World()

    def down(*, session, deadline):
        raise requests.ConnectionError()

    cache = glc.GwLiveCache(fetch_live=world.fetch_live, fetch_fixtures=down)
    batch = cache.load([1, 2], world.bootstrap())
    assert dict(batch.unavailable) == {1: glc.FETCH_FAILED, 2: glc.FETCH_FAILED}
    assert not batch.gameweeks and batch.invariant == "not_checked"


def test_the_default_cache_is_one_per_process():
    assert glc.default_cache() is glc.default_cache()
