"""The European calendar job: pages, raw cache names, the shared credit check, keep-previous.

Fake transport and fake R2; synthetic games; no network, no key.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from fpl_tactical import europe_calendar as euro
from fpl_tactical.strikerapi_budget import affordable, within_ceiling
from fpl_tactical.strikerapi_client import StrikerApiClient
from fpl_tactical.strikerapi_raw import RawCache, RawCacheError, raw_name

SEASON = "2026-2027"
NOW = datetime(2026, 11, 26, 8, tzinfo=timezone.utc)


def game(league, i, status="scheduled"):
    return {
        "game_id": f"{league}-{i}", "stage": "League Phase", "starts_at": "2026-12-09T20:00:00.000Z",
        "status": status,
        "home": {"name": "Arsenal" if i == 0 else f"Synthetic {i}", "abbrev": "ARS" if i == 0 else "SYN"},
        "away": {"name": f"Synthetic Away {i}", "abbrev": "SYA"},
    }


class FakeApi:
    """``list_games`` per league: a list of pages. Records every paid request."""

    def __init__(self, pages=None, remaining=400, bad=(), status=200, send_headers=True):
        self.pages = pages or {lg: [[game(lg, 0), game(lg, 1)]] for lg in ("ucl", "uel", "uecl")}
        self.remaining, self.bad, self.status, self.send_headers = remaining, set(bad), status, send_headers
        self.requests: list[dict] = []

    def __call__(self, url, headers, body):
        request = json.loads(body)
        self.requests.append(request)
        league, offset = request["league"], request.get("offset", 0)
        index = offset // 200
        games = [dict(g) for g in self.pages[league][index]]
        if league in self.bad:
            games[0]["status"] = "mystery"
        self.remaining -= 2
        nxt = (index + 1) * 200 if index + 1 < len(self.pages[league]) else None
        head = {"x-credits-used": "2", "x-credits-remaining": str(self.remaining)} if self.send_headers else {}
        return self.status, head, json.dumps({"data": {"games": games, "next_offset": nxt}})


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))


def run(api, now=NOW, previous=None, max_credits=euro.RUN_CEILING, cache=None):
    client = StrikerApiClient(api_key="synthetic", transport=api)
    return euro.build(SEASON, client, cache or RawCache(SEASON), now, previous=previous, max_credits=max_credits)


def test_a_normal_run_buys_three_pages_for_six_credits():
    api = FakeApi()
    payload, report = run(api)
    assert [r["league"] for r in api.requests] == ["ucl", "uel", "uecl"]
    assert all(r["limit"] == 200 and r["season"] == 2026 and "status" not in r for r in api.requests)
    assert report.credits_spent == 6 and report.updated == ["UCL", "UEL", "UECL"] and not report.alerts
    assert payload["provenance"] == "strikerapi_calendar" and set(payload["competitions"]) == {"UCL", "UEL", "UECL"}
    assert payload["competitions"]["UCL"]["complete_as_of"] is None    # two games are not a whole League Phase


def test_pages_are_followed_and_a_paged_list_reaches_its_end():
    second = {**game("ucl", 1), "home": {"name": "Liverpool", "abbrev": "LIV"}}
    api = FakeApi(pages={"ucl": [[game("ucl", 0)], [second]], "uel": [[game("uel", 0)]],
                         "uecl": [[game("uecl", 0)]]})
    payload, report = run(api)
    assert [r.get("offset", 0) for r in api.requests] == [0, 200, 0, 0]
    assert report.credits_spent == 8 and len(payload["competitions"]["UCL"]["records"]) == 2


def test_the_raw_names_carry_league_and_day_and_the_shots_names_are_unchanged():
    run(FakeApi())
    kept = sorted(p.name for p in RawCache(SEASON).dir.glob("*.json") if p.name != "_writable.json")
    assert set(kept) == {"list_games_ucl_20261126_0.json", "list_games_uel_20261126_0.json",
                         "list_games_uecl_20261126_0.json"}
    # the shots job's names, byte for byte
    assert raw_name("list_games", {"season": 2026, "status": "final", "limit": 200}) == "list_games_0"
    assert raw_name("list_games", {"season": 2026, "offset": 200}, "20261126") == "list_games_200"
    assert raw_name("get_shot_map", {"game_id": "77"}) == "77"
    assert raw_name("get_shot_map", {"team": "ARS", "season": 2026}) == "team_ARS"
    with pytest.raises(RawCacheError):
        raw_name("list_games", {"league": "ucl"})


def test_the_same_day_costs_nothing_again_and_the_next_day_buys_again():
    run(FakeApi())
    again = FakeApi()
    payload, report = run(again)
    assert again.requests == [] and report.credits_spent == 0 and payload is not None
    tomorrow = FakeApi()
    run(tomorrow, now=NOW + timedelta(days=1))
    assert len(tomorrow.requests) == 3


def test_a_rejected_competition_keeps_its_previous_snapshot():
    first, _ = run(FakeApi())
    later = NOW + timedelta(days=2)
    payload, report = run(FakeApi(bad={"uel"}), now=later, previous=first)
    assert report.updated == ["UCL", "UECL"] and report.kept == ["UEL"]
    assert payload["competitions"]["UEL"] == first["competitions"]["UEL"]          # old fetched_at: goes stale
    assert payload["competitions"]["UCL"]["fetched_at"] != first["competitions"]["UCL"]["fetched_at"]
    assert any(a.startswith("UEL: rejected") for a in report.alerts)


def test_a_previous_file_of_another_season_or_source_is_not_carried_over():
    previous = {"season": "2025-2026", "provenance": "strikerapi_calendar", "competitions": {"UEL": {"x": 1}}}
    payload, _ = run(FakeApi(bad={"uel"}), previous=previous)
    assert "UEL" not in payload["competitions"]


def test_nothing_updated_writes_nothing():
    payload, report = run(FakeApi(bad={"ucl", "uel", "uecl"}))
    assert payload is None and report.kept == ["UCL", "UEL", "UECL"]


def test_an_http_error_keeps_the_previous_and_alerts():
    payload, report = run(FakeApi(status=500))
    assert payload is None and len(report.alerts) == 3


def test_the_run_ceiling_stops_before_the_next_page():
    api = FakeApi()
    payload, report = run(api, max_credits=4)
    assert len(api.requests) == 2 and report.updated == ["UCL", "UEL"] and report.kept == ["UECL"]
    assert any("ceiling" in a for a in report.alerts)


def test_the_ceiling_holds_even_if_the_source_sends_no_usage_header():
    api = FakeApi(send_headers=False)
    _, report = run(api, max_credits=4)
    assert len(api.requests) == 2 and report.credits_spent == 4


def test_the_sources_remaining_credits_stop_the_run():
    api = FakeApi(remaining=3)                 # after the first page the source reports 1 left
    _, report = run(api)
    assert len(api.requests) == 1 and report.credits_remaining == 1
    assert report.updated == ["UCL"] and any("remaining" in a for a in report.alerts)


def test_nothing_is_bought_when_it_cannot_be_kept(monkeypatch):
    api = FakeApi()
    cache = RawCache(SEASON)

    def refuse():
        raise RawCacheError("raw cache is not writable")

    monkeypatch.setattr(cache, "check_writable", refuse)
    with pytest.raises(RawCacheError):
        run(api, cache=cache)
    assert api.requests == []


def test_the_shared_credit_check():
    assert affordable(10, None) and affordable(10, 10) and not affordable(11, 10)
    assert within_ceiling(18, 2, 20) and not within_ceiling(19, 2, 20)


def test_both_jobs_ask_the_same_helper():
    import inspect

    from fpl_tactical import strikerapi_ingest

    source = inspect.getsource(strikerapi_ingest)
    assert "credits_remaining is not None" not in source and "affordable(" in source
    assert "affordable(" in inspect.getsource(euro)


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def upload_file(self, path, bucket, key):
        self.objects[key] = open(path, "rb").read()

    def download_file(self, bucket, key, dest):
        if key not in self.objects:
            error = Exception("not found")
            error.response = {"Error": {"Code": "404"}}
            raise error
        open(dest, "wb").write(self.objects[key])


def test_write_and_read_back_through_r2():
    bucket = FakeBucket()
    assert euro.read_previous(SEASON, bucket, "b", "p/") is None
    payload, _ = run(FakeApi())
    euro.write(payload, SEASON, bucket, "b", "p/")
    assert list(bucket.objects) == ["p/calendar/2026-2027/europe.json"]
    assert euro.read_previous(SEASON, bucket, "b", "p/") == payload


def test_an_r2_error_is_not_read_as_no_previous_file():
    class Broken(FakeBucket):
        def download_file(self, *a):
            raise PermissionError("denied")

    with pytest.raises(RuntimeError):
        euro.read_previous(SEASON, Broken(), "b", "")
