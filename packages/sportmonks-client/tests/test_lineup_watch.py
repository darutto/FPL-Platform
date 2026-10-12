"""lineup_watch: each row is stamped when the answer is in hand, never before the request."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import lineup_watch  # noqa: E402

KICKOFF = "2026-10-12 19:00:00"


class _Body:
    def __init__(self, body):
        self.body = body


def test_the_row_is_stamped_after_the_request_returns(tmp_path, monkeypatch):
    events: list[str] = []
    clock = iter([dt.datetime(2026, 10, 12, 8, 43, tzinfo=dt.timezone.utc),     # a stamp taken BEFORE the request
                  dt.datetime(2026, 10, 12, 22, 47, tzinfo=dt.timezone.utc)])   # one taken AFTER it

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            events.append("now")
            return next(clock)

    class FakeDt:
        datetime = Clock
        timezone = dt.timezone
        timedelta = dt.timedelta

    fixture = {"id": 1, "name": "A vs B", "starting_at": KICKOFF, "state": {"developer_name": "FT"},
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
    assert events[0] == "request", "the request must come before any clock read"
    row = json.loads(out.read_text().splitlines()[0])
    assert row["at"] == "2026-10-12T08:43:00Z" or row["at"] == "2026-10-12T22:47:00Z"
    assert row["at"] == "2026-10-12T08:43:00Z" if events[1] == "now" else True
    assert (tmp_path / "w.ndjson.done").exists()
