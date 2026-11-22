"""league_eo: mini-league EO compute + service on the shared job plumbing (synthetic data, no network)."""
from __future__ import annotations

import json
import threading

import pytest

from fpl_grounded_assistant import league_eo as le
from fpl_grounded_assistant import near_rank_eo as ne

USER, OTHER = 7_000_001, 7_000_002
LEAGUE = 4242


def picks_for(entry: int) -> dict:
    ids = list(range(1, 16))
    if entry % 2:
        ids[1] = 99
    return {"active_chip": None, "picks": [
        {"element": e, "position": i + 1, "multiplier": 0 if i >= 11 else (2 if i == 0 else 1), "is_captain": i == 0}
        for i, e in enumerate(ids)]}


def league_row(lid, size, *, kind="x", scoring="c", name="Friends"):
    return {"id": lid, "name": name, "league_type": kind, "scoring": scoring, "rank_count": size}


class FakeApi:
    def __init__(self, *, size=12, extra_leagues=(), entry_ok=True, no_picks=(), members_of=None):
        self.urls: list[str] = []
        self.size, self.entry_ok, self.no_picks = size, entry_ok, set(no_picks)
        self.leagues = [league_row(LEAGUE, size)] + list(extra_leagues)
        self.members_of = members_of  # None = both users are in the league
        self.lock = threading.Lock()

    def __call__(self, url):
        with self.lock:
            self.urls.append(url)
        if "/standings/" in url:
            page = int(url.rsplit("=", 1)[1])
            first = (page - 1) * 50
            rows = [{"entry": 1_000_000 + first + i + 1, "player_name": "Hidden Name", "rank": first + i + 1}
                    for i in range(min(50, max(0, self.size - first)))]
            return 200, {"standings": {"results": rows, "has_next": False}}, {}
        if "/picks/" in url:
            entry = int(url.split("/entry/")[1].split("/")[0])
            if entry in self.no_picks:
                return 404, None, {}
            return 200, picks_for(entry), {}
        if not self.entry_ok:
            return 404, None, {}
        return 200, {"leagues": {"classic": self.leagues, "h2h": []}}, {}

    def count(self, needle):
        return sum(needle in u for u in self.urls)


def make_api(fake, budget=250):
    return ne._Api(fake, ne.RateLimiter(0.0, sleep=lambda s: None), ne.CircuitBreaker(), budget, lambda s: None)


class Inline:
    def submit(self, fn, *a):
        fn(*a)


def service(fake, **kw):
    return le.LeagueEOService(fake, limiter=ne.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None,
                              executor=kw.pop("executor", Inline()), workers=kw.pop("workers", 1), **kw)


# -- which league -----------------------------------------------------------------------------

def test_only_private_classic_leagues_are_listed_smallest_first():
    body = {"leagues": {"classic": [
        league_row(1, 9_000_000, kind="s", name="Overall"), league_row(2, 50), league_row(3, 12),
        league_row(4, 20, scoring="h"), league_row(5, 8, kind="s")], "h2h": [{"id": 9}]}}
    assert [lg["id"] for lg in le.private_leagues(body)] == [3, 2]
    assert le.private_leagues({}) == []


@pytest.mark.parametrize("size,reason", [(0, "league_too_small"), (2, "league_too_small"), (3, None),
                                         (2000, None), (2001, "league_too_large")])
def test_size_limits(size, reason):
    assert le.check_size(size) == reason


def test_positions_are_everyone_up_to_100_then_100_spread_evenly():
    assert le.league_positions(12) == list(range(1, 13)) and le.league_positions(100) == list(range(1, 101))
    for size in (101, 840, 2000):
        pos = le.league_positions(size)
        assert len(pos) == len(set(pos)) == 100 and 1 <= pos[0] and pos[-1] <= size
        assert pos == sorted(pos) and max(b - a for a, b in zip(pos, pos[1:])) <= size / 100 + 1


# -- compute --------------------------------------------------------------------------------------

def test_small_league_is_read_in_full_and_labelled_exact():
    fake = FakeApi(size=12)
    lg = {"id": LEAGUE, "name": "Friends", "size": 12}
    out = le.compute_league_eo(lg, "s", 11, make_api(fake), workers=1)
    assert out["exact"] is True and out["approx"] is False and out["n_sampled"] == 12
    assert out["label"] == "exact, n=12 of 12" and out["tier"] == "league"
    assert fake.count("/standings/") == 1 and fake.count("/picks/") == 12  # 14 with the league list
    assert out["players"]["1"] == {"owned_pct": 100.0, "captain_pct": 100.0, "bench_pct": 0.0, "eo": 200.0}


def test_large_league_is_sampled_with_only_the_pages_needed():
    fake = FakeApi(size=840)
    out = le.compute_league_eo({"id": LEAGUE, "name": "Big", "size": 840}, "s", 11, make_api(fake), workers=4)
    assert out["exact"] is False and out["n_sampled"] == 100 and out["label"] == "approx., n=100 of 840"
    assert fake.count("/picks/") == 100 and fake.count("/standings/") <= 17  # ceil(840 / 50)


def test_members_without_picks_are_left_out_and_counted():
    fake = FakeApi(size=12, no_picks={1_000_001, 1_000_002})
    out = le.compute_league_eo({"id": LEAGUE, "name": "F", "size": 12}, "s", 11, make_api(fake), workers=1)
    assert out["n_sampled"] == 10 and out["n_target"] == 12 and out["label"] == "exact, n=10 of 12"


def test_output_holds_aggregates_only():
    out = le.compute_league_eo({"id": LEAGUE, "name": "F", "size": 12}, "s", 11, make_api(FakeApi()), workers=1)
    text = json.dumps(out)
    assert "Hidden Name" not in text and "1000" not in text


@pytest.mark.parametrize("fake,league,reason", [
    (FakeApi(size=12), {"id": LEAGUE, "name": "F", "size": 2}, "league_too_small"),
    (FakeApi(size=12), {"id": LEAGUE, "name": "F", "size": 5000}, "league_too_large"),
    (FakeApi(size=12, no_picks=range(1_000_001, 1_000_013)), {"id": LEAGUE, "name": "F", "size": 12}, "too_few_samples"),
])
def test_compute_raises_unavailable_with_a_reason(fake, league, reason):
    with pytest.raises(ne.Unavailable) as exc:
        le.compute_league_eo(league, "s", 11, make_api(fake), workers=1)
    assert exc.value.reason == reason


def test_empty_standings_is_unavailable_and_the_budget_stops_a_job():
    class Empty(FakeApi):
        def __call__(self, url):
            if "/standings/" in url:
                return 200, {"standings": {"results": []}}, {}
            return super().__call__(url)

    with pytest.raises(ne.Unavailable) as exc:
        le.compute_league_eo({"id": LEAGUE, "name": "F", "size": 12}, "s", 11, make_api(Empty()), workers=1)
    assert exc.value.reason == "standings_unavailable"
    with pytest.raises(ne.Unavailable) as exc:
        le.compute_league_eo({"id": LEAGUE, "name": "F", "size": 12}, "s", 11, make_api(FakeApi(), budget=5), workers=1)
    assert exc.value.reason == "request_budget"


# -- the service -----------------------------------------------------------------------------------

def test_first_call_computes_in_one_job_and_the_second_is_ready():
    fake = FakeApi(size=12)
    svc = service(fake)
    assert svc.status("s", 11, USER, LEAGUE, valid_until=10**10)["status"] == "computing"
    out = svc.status("s", 11, USER, LEAGUE, valid_until=10**10)
    assert out["status"] == "ready" and out["data"]["n_sampled"] == 12
    assert fake.count("/entry/" + str(USER)) == 1 and fake.count("/standings/") == 1  # waited once, not twice
    n = len(fake.urls)
    assert svc.status("s", 11, USER, LEAGUE, valid_until=10**10) == out and len(fake.urls) == n


def test_the_picker_lists_the_users_private_leagues_without_a_compute():
    fake = FakeApi(size=12, extra_leagues=[league_row(77, 48, name="Work")])
    svc = service(fake)
    assert svc.status("s", 11, USER)["status"] == "computing"
    out = svc.status("s", 11, USER)
    assert out["status"] == "ready"
    assert [(lg["id"], lg["name"], lg["size"]) for lg in out["data"]["leagues"]] == [(LEAGUE, "Friends", 12), (77, "Work", 48)]
    assert fake.count("/standings/") == 0 and fake.count("/picks/") == 0


def test_membership_is_checked_on_every_call_even_with_a_cached_league_result():
    fake = FakeApi(size=12)
    svc = service(fake)
    svc.status("s", 11, USER, LEAGUE, valid_until=10**10)
    assert svc.status("s", 11, USER, LEAGUE, valid_until=10**10)["status"] == "ready"
    assert svc.status("s", 11, USER, 999, valid_until=10**10) == {"status": "unavailable", "reason": "not_a_member"}
    # another user who is NOT in the league may not read the cached result
    stranger = FakeApi(size=12)
    stranger.leagues = [league_row(5, 30, name="Other")]
    svc._fetch = stranger
    svc.status("s", 11, OTHER, LEAGUE, valid_until=10**10)
    assert svc.status("s", 11, OTHER, LEAGUE, valid_until=10**10) == {"status": "unavailable", "reason": "not_a_member"}


def test_members_of_one_league_share_one_result():
    fake = FakeApi(size=12)
    svc = service(fake)
    svc.status("s", 11, USER, LEAGUE, valid_until=10**10)
    svc.status("s", 11, USER, LEAGUE, valid_until=10**10)
    standings, picks = fake.count("/standings/"), fake.count("/picks/")
    assert svc.status("s", 11, OTHER, LEAGUE, valid_until=10**10)["status"] == "computing"  # one list request
    out = svc.status("s", 11, OTHER, LEAGUE, valid_until=10**10)
    assert out["status"] == "ready" and fake.count("/standings/") == standings and fake.count("/picks/") == picks


@pytest.mark.parametrize("size,reason", [(2, "league_too_small"), (2500, "league_too_large")])
def test_size_limits_answer_without_reading_the_league(size, reason):
    fake = FakeApi(size=size)
    svc = service(fake)
    svc.status("s", 11, USER, LEAGUE)
    assert svc.status("s", 11, USER, LEAGUE) == {"status": "unavailable", "reason": reason}
    assert fake.count("/standings/") == 0


def test_an_unreachable_entry_is_unavailable_and_cached_negatively():
    fake = FakeApi(entry_ok=False)
    svc = service(fake)
    svc.status("s", 11, USER, LEAGUE)
    assert svc.status("s", 11, USER, LEAGUE) == {"status": "unavailable", "reason": "entry_unavailable"}
    n = len(fake.urls)
    svc.status("s", 11, USER, LEAGUE)
    assert len(fake.urls) == n


def test_valid_until_expires_the_league_result():
    t = {"now": 1000.0}
    fake = FakeApi(size=12)
    svc = service(fake)
    svc._clock = lambda: t["now"]
    svc.status("s", 11, USER, LEAGUE, valid_until=2000.0)
    assert svc.status("s", 11, USER, LEAGUE, valid_until=2000.0)["status"] == "ready"
    n = fake.count("/picks/")
    t["now"] = 2001.0
    assert svc.status("s", 11, USER, LEAGUE, valid_until=3000.0)["status"] == "computing"
    assert fake.count("/picks/") > n


def test_real_thread_pool_single_flight_and_non_blocking():
    gate = threading.Event()
    fake = FakeApi(size=12)

    def slow(url):
        gate.wait(5)
        return fake(url)

    svc = le.LeagueEOService(slow, limiter=ne.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None, workers=1)
    assert svc.status("s", 11, USER, LEAGUE) == {"status": "computing", "eta_s": ne.ETA_S}
    assert svc.status("s", 11, USER, LEAGUE) == {"status": "computing", "eta_s": ne.ETA_S}
    gate.set()
    for _ in range(100):
        out = svc.status("s", 11, USER, LEAGUE)
        if out["status"] != "computing":
            break
        threading.Event().wait(0.05)
    assert out["status"] == "ready" and fake.count("/entry/" + str(USER)) == 1


def test_a_bug_in_a_job_is_unavailable_not_a_stuck_key():
    def boom(url):
        raise RuntimeError("synthetic bug")

    svc = service(boom)
    svc.status("s", 11, USER, LEAGUE)
    assert svc.status("s", 11, USER, LEAGUE) == {"status": "unavailable", "reason": "error"}
    assert svc._inflight == set()


# -- the shared plumbing ---------------------------------------------------------------------------------

def test_both_services_share_one_limiter_and_one_breaker_by_default():
    a, b = ne.NearRankEOService(FakeApi(), executor=Inline()), le.LeagueEOService(FakeApi(), executor=Inline())
    assert a._limiter is b._limiter is ne.shared_limiter()
    assert a._breaker is b._breaker is ne.shared_breaker()
    assert isinstance(a, ne.JobService) and isinstance(b, ne.JobService)
