"""lineup_watch: each row is stamped when the answer is in hand, never before the request."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import lineup_watch  # noqa: E402


class _Body:
    def __init__(self, body):
        self.body = body


def test_the_row_is_stamped_after_the_request_returns(tmp_path, monkeypatch):
    events: list[str] = []

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            events.append("now")
            return dt.datetime(2026, 10, 12, 22, 47, tzinfo=dt.timezone.utc)   # after the match: the loop ends

    class FakeDt:
        datetime = Clock
        timezone = dt.timezone
        timedelta = dt.timedelta

    fixture = {"id": 1, "name": "A vs B", "starting_at": "2026-10-12 19:00:00", "state": {"developer_name": "FT"},
               "lineups": [], "formations": []}

    class FakeClient:
        def _request(self, path, params):
            events.append("request")
            return _Body({"data": [fixture], "pagination": {"has_more": False}})

    def no_sleep(seconds):
        raise AssertionError("the watcher would have slept: the loop did not end after the match")

    monkeypatch.setattr(lineup_watch.time, "sleep", no_sleep)
    monkeypatch.setattr(lineup_watch, "dt", FakeDt)
    monkeypatch.setattr(lineup_watch, "SportmonksClient", FakeClient)
    out = tmp_path / "w.ndjson"
    assert lineup_watch.main(["2026-10-12T00:00:00Z", "2026-10-12T23:59:59Z", str(out)]) == 0
    assert events[:2] == ["request", "now"], "no clock read may come before the request"
    assert json.loads(out.read_text().splitlines()[0])["at"] == "2026-10-12T22:47:00Z"
    assert Path(str(out) + ".done").exists()


def _utc(day, hh, mm=0):
    return dt.datetime(2026, 10, day, hh, mm, tzinfo=dt.timezone.utc)


GW7 = [_utc(17, 11, 30), _utc(17, 14), _utc(17, 16, 30), _utc(18, 13), _utc(18, 15, 30), _utc(19, 19)]


def test_rests_until_four_hours_before_the_first_kickoff():
    assert lineup_watch.next_wake(_utc(16, 12), GW7) == _utc(17, 7, 30)


def test_reads_every_20_minutes_then_every_5_in_the_last_hour():
    assert lineup_watch.next_wake(_utc(17, 8), GW7) == _utc(17, 8, 20)
    assert lineup_watch.next_wake(_utc(17, 10, 29), GW7) == _utc(17, 10, 49)   # 61 min to kickoff: still 20
    assert lineup_watch.next_wake(_utc(17, 10, 31), GW7) == _utc(17, 10, 36)
    assert lineup_watch.next_wake(_utc(17, 12, 0), GW7) == _utc(17, 12, 20)    # 30 min after kickoff, 2 h to the next


def test_rests_between_match_days():
    assert lineup_watch.next_wake(_utc(17, 20), GW7) == _utc(18, 9)
    assert lineup_watch.next_wake(_utc(18, 16), GW7) == _utc(19, 15)


def test_lineup_confirmed_reads_the_provider_flag_and_never_guesses():
    item = lambda value, type_id=572: {"type_id": type_id, "values": value}
    assert lineup_watch.lineup_confirmed({"metadata": [item({"neutral": False}, 35), item({"confirmed": False})]}) is False
    assert lineup_watch.lineup_confirmed({"metadata": [item({"confirmed": True})]}) is True
    assert lineup_watch.lineup_confirmed({"metadata": [item({"neutral": False}, 35)]}) is None
    assert lineup_watch.lineup_confirmed({"metadata": [item({"confirmed": "yes"})]}) is None
    assert lineup_watch.lineup_confirmed({}) is None


def test_every_row_carries_lineup_confirmed(tmp_path, monkeypatch):
    fixture = {"id": 1, "name": "A vs B", "starting_at": "2026-10-12 19:00:00", "state": {"developer_name": "FT"},
               "lineups": [], "formations": [], "metadata": [{"type_id": 572, "values": {"confirmed": True}}]}

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 12, 22, 47, tzinfo=dt.timezone.utc)

    class FakeDt:
        datetime, timezone, timedelta = Clock, dt.timezone, dt.timedelta

    class FakeClient:
        def _request(self, path, params):
            assert "metadata" in params["include"]
            return _Body({"data": [fixture], "pagination": {"has_more": False}})

    monkeypatch.setattr(lineup_watch, "dt", FakeDt)
    monkeypatch.setattr(lineup_watch, "SportmonksClient", FakeClient)
    out = tmp_path / "w.ndjson"
    lineup_watch.main(["2026-10-12T00:00:00Z", "2026-10-12T23:59:59Z", str(out)])
    assert json.loads(out.read_text().splitlines()[0])["lineup_confirmed"] is True
