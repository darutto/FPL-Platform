"""near_rank_eo: pure compute + job service with a fake FPL API (synthetic data, no network)."""
from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path

import pytest

from fpl_grounded_assistant import near_rank_eo as ne

USER = 7_000_001
USER_RANK = 1_234_567          # synthetic
USER_PAGE = ne.rank_page(USER_RANK)


def picks_for(entry: int) -> dict:
    ids = list(range(1, 16))
    if entry % 2:
        ids[1] = 99
    return {"active_chip": None, "picks": [
        {"element": e, "position": i + 1, "multiplier": 0 if i >= 11 else (2 if i == 0 else 1), "is_captain": i == 0}
        for i, e in enumerate(ids)]}


class FakeApi:
    """History, standings and picks. Rows come in tied pairs (shared `rank`), as near the top."""

    def __init__(self, *, rank=USER_RANK, empty_pages=(), fail_picks=(), status=200, history_rank="ok"):
        self.urls: list[str] = []
        self.rank, self.empty_pages, self.fail_picks, self.status = rank, set(empty_pages), set(fail_picks), status
        self.history_rank = history_rank
        self.lock = threading.Lock()

    def __call__(self, url):
        with self.lock:
            self.urls.append(url)
        if self.status != 200:
            return self.status, None, {"Retry-After": "0"}
        if "/history/" in url:
            current = [{"event": 11, "overall_rank": self.rank}] if self.history_rank == "ok" else []
            return 200, {"current": current}, {}
        if "standings" in url:
            page = int(url.rsplit("=", 1)[1])
            if page in self.empty_pages:
                return 200, {"standings": {"results": []}}, {}
            rows = [{"rank": (page - 1) * 50 + (i // 2) * 2 + 1, "entry": 1_000_000 + (page - 1) * 50 + i + 1,
                     "player_name": "Hidden Name"} for i in range(50)]
            if page == USER_PAGE:
                rows[10]["entry"] = USER  # the user sits on their own page
            return 200, {"standings": {"results": rows}}, {}
        entry = int(url.split("/entry/")[1].split("/")[0])
        if entry in self.fail_picks:
            return 404, None, {}  # a missing picks page: skipped, not a failure of the API
        return 200, picks_for(entry), {}


def make_api(fake, budget=250, breaker=None):
    return ne._Api(fake, ne.RateLimiter(0.0, sleep=lambda s: None), breaker or ne.CircuitBreaker(),
                   budget, lambda s: None)


class Inline:
    """An executor that runs the job at once, on the calling thread."""

    def submit(self, fn, *a):
        fn(*a)


def service(fake, **kw):
    return ne.NearRankEOService(
        fake, limiter=ne.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None,
        executor=kw.pop("executor", Inline()), workers=kw.pop("workers", 1), **kw)


# -- window and sample ---------------------------------------------------------------------

def test_window_is_five_pages_around_the_user_and_clips_at_page_one():
    assert ne.window_pages(USER_RANK) == list(range(USER_PAGE - 2, USER_PAGE + 3))
    assert ne.window_pages(1) == [1, 2, 3]
    assert ne.window_pages(120) == [1, 2, 3, 4, 5]  # page 3


def test_user_rank_for_the_gw_or_none():
    assert ne.user_rank_for_gw({"current": [{"event": 11, "overall_rank": 5}]}, 11) == 5
    assert ne.user_rank_for_gw({"current": [{"event": 10, "overall_rank": 5}]}, 11) is None
    assert ne.user_rank_for_gw({"current": [{"event": 11, "overall_rank": None}]}, 11) is None
    assert ne.user_rank_for_gw({}, 11) is None


def test_compute_samples_every_second_manager_excluding_the_user():
    fake = FakeApi()
    out = ne.compute_near_rank_eo(USER, "s", 11, make_api(fake), workers=1)
    assert out["tier"] == "near" and out["approx"] is True and out["user_rank"] == USER_RANK
    assert out["n_sampled"] == out["n_target"] == 125  # 250 managers, every 2nd; the user is odd-positioned
    assert out["window"] == {"pages": [USER_PAGE - 2, USER_PAGE + 2], "every": 2}
    picked = [int(u.split("/entry/")[1].split("/")[0]) for u in fake.urls if "/picks/" in u]
    assert USER not in picked and len(picked) == len(set(picked)) == 125
    assert all((e - 1_000_000) % 2 == 0 for e in picked)  # even positions only
    assert len(fake.urls) == 1 + 1 + 5 + 125  # history, the user's entry (league names), standings, picks


def test_user_on_an_even_position_is_excluded_from_the_sample():
    class EvenUser(FakeApi):
        def __call__(self, url):
            status, body, h = super().__call__(url)
            if "standings" in url and int(url.rsplit("=", 1)[1]) == USER_PAGE:
                body["standings"]["results"][11]["entry"] = USER  # index 11 -> even position
                body["standings"]["results"][10]["entry"] = 1_000_000 + (USER_PAGE - 1) * 50 + 11
            return status, body, h
    fake = EvenUser()
    out = ne.compute_near_rank_eo(USER, "s", 11, make_api(fake), workers=1)
    assert out["n_sampled"] == 124
    assert all(f"/entry/{USER}/event" not in u for u in fake.urls)


def test_output_holds_aggregates_only():
    out = ne.compute_near_rank_eo(USER, "s", 11, make_api(FakeApi()), workers=1)
    text = json.dumps(out)
    assert "Hidden Name" not in text and "1000" not in text.replace("1000.0", "")  # no neighbour ids
    assert set(out["players"]["1"]) == {"owned_pct", "captain_pct", "bench_pct", "eo"}


def test_parallel_workers_give_the_same_answer():
    a = ne.compute_near_rank_eo(USER, "s", 11, make_api(FakeApi()), workers=1)
    b = ne.compute_near_rank_eo(USER, "s", 11, make_api(FakeApi()), workers=4)
    assert a["players"] == b["players"] and a["n_sampled"] == b["n_sampled"]


def test_maths_equal_the_published_sampler():
    spec = importlib.util.spec_from_file_location(
        "tier_eo_top10k", Path(__file__).resolve().parents[3] / "scripts" / "tier_eo_top10k.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    samples = [ne.compact_picks(picks_for(i)) for i in range(40)]
    samples[0]["chip"] = "bboost"
    assert ne.compute_eo(samples) == script.compute_eo(samples)


# -- unavailable, never a crash ------------------------------------------------------------------

@pytest.mark.parametrize("fake,reason", [
    (FakeApi(history_rank="none"), "no_rank"),
    (FakeApi(empty_pages=range(1, 10**6)), "standings_unavailable"),
    (FakeApi(fail_picks={1_000_000 + (USER_PAGE - 3) * 50 + i for i in range(1, 400)}), "too_few_samples"),
])
def test_compute_raises_unavailable_with_a_reason(fake, reason):
    with pytest.raises(ne.Unavailable) as exc:
        ne.compute_near_rank_eo(USER, "s", 11, make_api(fake), workers=1)
    assert exc.value.reason == reason


def test_one_empty_page_is_tolerated():
    out = ne.compute_near_rank_eo(USER, "s", 11, make_api(FakeApi(empty_pages={USER_PAGE + 2})), workers=1)
    assert out["window"]["pages"] == [USER_PAGE - 2, USER_PAGE + 1] and out["n_sampled"] == 100


def test_the_request_budget_stops_a_job():
    with pytest.raises(ne.Unavailable) as exc:
        ne.compute_near_rank_eo(USER, "s", 11, make_api(FakeApi(), budget=40), workers=1)
    assert exc.value.reason == "request_budget"


def test_retry_honours_retry_after_and_failure_opens_the_breaker():
    sleeps: list[float] = []
    breaker = ne.CircuitBreaker(threshold=3, cooldown=60, clock=lambda: 0.0)
    api = ne._Api(FakeApi(status=429), ne.RateLimiter(0.0, sleep=lambda s: None), breaker, 100, sleeps.append)
    assert api.get("u") is None  # 3 attempts, all 429
    assert 1.0 in sleeps and api.requests == 3
    with pytest.raises(ne.Unavailable) as exc:
        api.get("u")
    assert exc.value.reason == "fpl_api_unavailable" and api.requests == 3  # no further calls


def test_breaker_closes_after_the_cooldown():
    t = {"now": 0.0}
    b = ne.CircuitBreaker(threshold=2, cooldown=60, clock=lambda: t["now"])
    b.failure(); b.failure()
    assert b.allow() is False
    t["now"] = 61.0
    assert b.allow() is True


def test_rate_limiter_spaces_requests():
    t = {"now": 0.0}
    waits: list[float] = []
    lim = ne.RateLimiter(0.25, clock=lambda: t["now"], sleep=waits.append)
    for _ in range(3):
        lim.acquire()
    assert waits == [0.25, 0.5]


# -- the service ---------------------------------------------------------------------------------

def test_status_computes_caches_and_does_not_refetch():
    fake = FakeApi()
    svc = service(fake)
    assert svc.status("s", 11, USER, valid_until=10_000_000_000.0)["status"] == "computing"  # the call that starts it
    first = svc.status("s", 11, USER, valid_until=10_000_000_000.0)  # the inline executor has finished by now
    assert first["status"] == "ready" and first["data"]["n_sampled"] == 125  # inline executor: done at once
    calls = len(fake.urls)
    assert svc.status("s", 11, USER, valid_until=10_000_000_000.0) == first
    assert len(fake.urls) == calls


def test_status_is_computing_then_ready_with_a_real_thread_pool():
    gate = threading.Event()
    fake = FakeApi()
    inner = fake.__call__

    def slow(url):
        gate.wait(5)
        return inner(url)

    svc = ne.NearRankEOService(slow, limiter=ne.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None, workers=1)
    assert svc.status("s", 11, USER) == {"status": "computing", "eta_s": ne.ETA_S}
    assert svc.status("s", 11, USER) == {"status": "computing", "eta_s": ne.ETA_S}  # single-flight
    gate.set()
    for _ in range(100):
        out = svc.status("s", 11, USER)
        if out["status"] != "computing":
            break
        threading.Event().wait(0.05)
    assert out["status"] == "ready"
    assert sum("/history/" in u for u in fake.urls) == 1  # one job only


def test_failures_are_cached_negatively_and_expire():
    t = {"now": 1000.0}
    fake = FakeApi(history_rank="none")
    svc = service(fake, **{})
    svc._clock = lambda: t["now"]
    assert svc.status("s", 11, USER)["status"] == "computing"
    assert svc.status("s", 11, USER) == {"status": "unavailable", "reason": "no_rank"}
    n = len(fake.urls)
    assert svc.status("s", 11, USER)["status"] == "unavailable" and len(fake.urls) == n  # cached
    t["now"] += ne.NEGATIVE_TTL_S + 1
    assert svc.status("s", 11, USER)["status"] == "computing"  # a new job starts
    assert len(fake.urls) > n  # retried after the negative TTL


def test_ready_result_expires_at_valid_until():
    t = {"now": 1000.0}
    fake = FakeApi()
    svc = service(fake)
    svc._clock = lambda: t["now"]
    svc.status("s", 11, USER, valid_until=2000.0)
    assert svc.status("s", 11, USER, valid_until=2000.0)["status"] == "ready"
    n = len(fake.urls)
    t["now"] = 2001.0
    assert svc.status("s", 11, USER, valid_until=3000.0)["status"] == "computing"
    assert len(fake.urls) > n


def test_other_users_and_gameweeks_are_separate_keys():
    fake = FakeApi()
    svc = service(fake)
    svc.status("s", 11, USER, valid_until=10**10)
    n = len(fake.urls)
    svc.status("s", 11, USER + 1, valid_until=10**10)
    assert len(fake.urls) > n and svc.status("s", 11, USER, valid_until=10**10)["status"] == "ready"


def test_a_full_queue_answers_busy_without_starting_a_job():
    class Never:
        def submit(self, fn, *a):
            pass  # accepted but never run: the key stays in flight

    svc = ne.NearRankEOService(FakeApi(), executor=Never(), max_queued=2)
    svc.status("s", 11, 1)
    svc.status("s", 11, 2)
    assert svc.status("s", 11, 3) == {"status": "unavailable", "reason": "busy"}


def test_a_bug_in_a_job_becomes_unavailable_not_a_stuck_key():
    def boom(url):
        raise RuntimeError("synthetic bug")

    svc = service(boom)
    assert svc.status("s", 11, USER)["status"] == "computing"
    assert svc.status("s", 11, USER) == {"status": "unavailable", "reason": "error"}
    assert svc._inflight == set()


def test_compute_keeps_the_names_of_the_users_private_leagues_for_the_switch_chip():
    class WithLeagues(FakeApi):
        def __call__(self, url):
            if url.endswith(f"/entry/{USER}/"):
                self.urls.append(url)
                return 200, {"leagues": {"classic": [
                    {"id": 9, "name": "Friends", "league_type": "x", "scoring": "c", "rank_count": 12},
                    {"id": 314, "name": "Overall", "league_type": "s", "scoring": "c"}]}}, {}
            return super().__call__(url)

    out = ne.compute_near_rank_eo(USER, "s", 11, make_api(WithLeagues()), workers=1)
    assert out["leagues"] == [{"id": 9, "name": "Friends"}]
