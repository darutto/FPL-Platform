"""The passes, the gate and the call cap on the synthetic recording. No token, no network."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from football_intelligence.ingestion.licensed.store import validate_build
from licensed_ingestion import fetch, recording
from licensed_ingestion.budget import BudgetExceeded, CountingTransport
from licensed_ingestion.fpl import due
from licensed_ingestion.run import NoBaseline, latest_build, run_pass
from sportmonks_client.client import SportmonksClient
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.transport import TransportResponse

class Spy:
    """The recording, plus the path of every request that reached it. ``lenient``: unrecorded paths answer empty."""

    def __init__(self, lenient: bool = False) -> None:
        self.paths: list[str] = []
        self.lenient = lenient
        self.inner = recording.RecordedTransport()

    def request(self, method, url, *, params, timeout):
        path = url.split("/v3/football/", 1)[-1]
        self.paths.append(path)
        if self.lenient and path not in recording.PROVIDER:
            return TransportResponse(200, {}, {"data": []})
        return self.inner.request(method, url, params=params, timeout=timeout)


def _client(inner=None, cap=1_000):
    transport = CountingTransport(inner or recording.RecordedTransport(), cap)
    return SportmonksClient.offline(transport, config=SportmonksConfig()), transport


def _utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def test_a_daily_pass_makes_exactly_the_planned_calls(tmp_path):
    spy = Spy()
    client, transport = _client(spy)
    build, summary = run_pass("daily", client, recording.FEED, tmp_path, now=recording.NOW, previous=None)
    ars, che = recording.ARS, recording.CHE
    assert spy.paths == [
        "seasons", f"teams/seasons/{recording.SEASON_ID}",
        f"squads/teams/{ars}", f"teams/{ars}", f"fixtures/between/2026-10-24/2027-06-20/{ars}",
        f"squads/teams/{che}", f"teams/{che}", f"fixtures/between/2026-10-24/2027-06-20/{che}",
        "fixtures/between/2026-10-24/2026-11-06", "fixtures/between/2026-10-17/2026-10-23"]
    assert transport.calls == fetch.planned_count("daily", clubs=2) == 10
    assert fetch.planned_count("daily") == 64   # 2 discovery + 20 squads + 20 sidelined + 20 team_fixtures + 2 windows
    assert summary["crosswalk"]["pool_resolved"] == 8 and summary["derive"]["other_competitions_dropped"] == 1
    validate_build(build)


def test_the_daily_plan_names_every_family_it_reads():
    requests = fetch.planned_calls("daily")
    assert {"licensed_squads x20", "current_sidelined x20", "licensed_team_fixtures x20"} <= set(requests)
    assert not any(word in " ".join(requests) for word in ("statistics", "coaches", "referees", "odds", "xg"))


def _daily(tmp_path):
    client, _ = _client()
    return run_pass("daily", client, recording.FEED, tmp_path, now=recording.NOW, previous=None)[0]


def test_a_matchday_pass_keeps_the_crosswalk_and_maps_the_players(tmp_path):
    daily = _daily(tmp_path)
    client, transport = _client()
    now = _utc("2026-10-24T13:00:00Z")
    poll, summary = run_pass("matchday", client, recording.FEED, tmp_path, now=now, previous=daily)
    assert transport.calls == 1 and summary["pass"] == "matchday"
    for name in ("crosswalk", "cup_records", "cup_snapshots"):
        assert pd.read_parquet(poll / f"datasets/{name}.parquet").equals(pd.read_parquet(daily / f"datasets/{name}.parquet"))
    slots = pd.read_parquet(poll / "datasets/lineup_slots.parquet")
    confirmed = slots[slots.observed_at == "2026-10-24T13:00:00Z"]
    assert len(confirmed) == 8 and confirmed.element.notna().all()
    snapshots = pd.read_parquet(poll / "datasets/lineup_snapshots.parquet")
    for team in ("ARS", "CHE"):   # per team: predicted (daily read), then confirmed (matchday read)
        assert list(snapshots[snapshots.team == team].sort_values("observed_at").confirmed) == [False, True]


def test_a_deadline_pass_is_one_call_over_the_next_fourteen_days(tmp_path):
    daily = _daily(tmp_path)
    spy = Spy()
    client, transport = _client(spy)
    run_pass("deadline", client, recording.FEED, tmp_path, now=_utc("2026-10-24T09:20:00Z"), previous=daily)
    assert spy.paths == ["fixtures/between/2026-10-24/2026-11-06"] and transport.calls == 1


@pytest.mark.parametrize("now,window", [
    ("2026-10-24T13:00:00Z", "fixtures/between/2026-10-24/2026-10-24"),
    ("2026-10-24T22:00:00Z", "fixtures/between/2026-10-24/2026-10-25"),   # +3 h crosses midnight UTC
    ("2026-10-25T00:10:00Z", "fixtures/between/2026-10-24/2026-10-25"),   # -30 min: a late kickoff of yesterday
])
def test_the_matchday_window_covers_the_gate_window_across_midnight(now, window):
    spy = Spy(lenient=True)
    client, _ = _client(spy)
    fetch.matchday(client, _utc(now))
    assert spy.paths == [window]


def test_a_matchday_pass_without_a_previous_build_fails_and_writes_nothing(tmp_path):
    client, transport = _client()
    with pytest.raises(NoBaseline):
        run_pass("matchday", client, recording.FEED, tmp_path, now=recording.NOW, previous=None)
    assert transport.calls == 0 and latest_build(tmp_path) is None


@pytest.mark.parametrize("kind,now,expected", [
    ("matchday", "2026-10-24T11:00:00Z", True),    # 3 h before the 14:00 kickoff
    ("matchday", "2026-10-24T10:59:00Z", False),
    ("matchday", "2026-10-24T14:30:00Z", True),    # 30 min after
    ("matchday", "2026-10-24T14:31:00Z", False),
    ("matchday", "2026-10-26T13:00:00Z", False),   # nothing kicks off: zero provider calls
    ("deadline", "2026-10-24T09:30:00Z", True),    # 3 h before the 12:30 deadline
    ("deadline", "2026-10-24T09:51:00Z", False),   # past the 20-minute slack of the 3 h target
    ("deadline", "2026-10-24T09:00:00Z", False),   # earlier than the target
    ("deadline", "2026-10-24T12:00:00Z", True),    # 30 min before
    ("deadline", "2026-10-24T11:00:00Z", False),   # between the two targets
    ("deadline", "2026-10-24T12:31:00Z", False),   # after the deadline
    ("daily", "2026-12-25T05:00:00Z", True),
])
def test_the_gate_reads_only_the_free_fpl_feed(kind, now, expected):
    assert due(kind, recording.FEED, _utc(now)) is expected


def test_every_gate_tick_of_a_deadline_finds_each_target_at_least_once():
    ticks = [_utc("2026-10-24T08:00:00Z").replace(hour=h, minute=m) for h in range(8, 13) for m in (7, 22, 37, 52)]
    hits = [t for t in ticks if due("deadline", recording.FEED, t)]
    assert 2 <= len(hits) <= 4


class Inner:
    def __init__(self) -> None:
        self.calls = 0
        self.recorded = recording.RecordedTransport()

    def request(self, *args, **kwargs):
        self.calls += 1
        return self.recorded.request(*args, **kwargs)


def test_call_n_plus_one_raises_before_reaching_the_transport(tmp_path):
    inner = Inner()
    client, capped = _client(inner, cap=2)
    with pytest.raises(BudgetExceeded):
        run_pass("daily", client, recording.FEED, Path(tmp_path), now=recording.NOW, previous=None)
    assert capped.calls == 2 and inner.calls == 2


def test_a_cap_equal_to_the_calls_needed_passes_and_one_less_raises(tmp_path):
    client, _ = _client(cap=10)
    run_pass("daily", client, recording.FEED, tmp_path / "ok", now=recording.NOW, previous=None)
    inner = Inner()
    client, _ = _client(inner, cap=9)
    with pytest.raises(BudgetExceeded):
        run_pass("daily", client, recording.FEED, tmp_path / "short", now=recording.NOW, previous=None)
    assert inner.calls == 9
