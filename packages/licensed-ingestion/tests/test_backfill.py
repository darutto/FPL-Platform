"""The manual history backfill: finished lineups from the season's start into the store. Synthetic data, no network."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from football_intelligence.ingestion.licensed.store import TABLES, validate_build
from licensed_ingestion import fetch, recording
from licensed_ingestion.__main__ import main
from licensed_ingestion.budget import BudgetExceeded, CountingTransport
from licensed_ingestion.fpl import FplFeed
from licensed_ingestion.run import NoBaseline, run_pass
from sportmonks_client.client import SportmonksClient
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.transport import TransportResponse

NOW = recording.NOW   # 2026-10-24 12:00 UTC


class Provider:
    """The backfill recording, with every request path logged; unrecorded windows answer an empty list."""

    def __init__(self, extra=None):
        self.paths: list[str] = []
        self.recording = {**recording.BACKFILL_PROVIDER, **(extra or {})}

    def request(self, method, url, *, params, timeout):
        path = url.split("/v3/football/", 1)[-1]
        self.paths.append(path)
        if path not in self.recording:
            return TransportResponse(200, {}, {"data": []})
        return TransportResponse(200, {}, self.recording[path])


def _client(provider, cap=1_000):
    transport = CountingTransport(provider, cap)
    return SportmonksClient.offline(transport, config=SportmonksConfig()), transport


def _daily(root):
    client, _ = _client(recording.RecordedTransport())
    return run_pass("daily", client, recording.FEED, root, now=NOW, previous=None)[0]


def _backfill(root, previous, *, now=NOW, provider=None, feed=recording.BACKFILL_FEED, since=None, cap=1_000):
    provider = provider or Provider()
    client, transport = _client(provider, cap)
    build, summary = run_pass("backfill", client, feed, root, now=now, previous=previous, since=since)
    return build, summary, provider, transport


def _table(build, name):
    return pd.read_parquet(build / f"datasets/{name}.parquet")


def _keys(frame, name):
    return list(map(tuple, frame[list(TABLES[name][1])].astype(str).values.tolist()))


def test_a_finished_match_enters_as_confirmed_even_when_the_providers_flag_is_stale(tmp_path):
    daily = _daily(tmp_path)
    build, summary, _p, _t = _backfill(tmp_path, daily)
    validate_build(build)
    snaps = _table(build, "lineup_snapshots")
    backfilled = snaps[snaps.observed_at == "2026-10-11T00:00:00Z"]       # the morning after the 10th
    assert len(backfilled) == 2 and set(backfilled.confirmed) == {True}   # the recording's flag says False
    assert set(backfilled.state) == {"completed"} and set(backfilled.team) == {"ARS", "CHE"}
    assert summary["backfill"] == {"fixtures_read": 1, "fixtures_completed": 1, "fixtures_skipped_not_completed": 0}


def test_the_daily_passes_provisional_and_confirmed_rows_are_not_overwritten(tmp_path):
    daily = _daily(tmp_path)
    before = _table(daily, "lineup_snapshots")
    assert False in set(before.confirmed)                                # the daily read left a provisional XI
    build, *_ = _backfill(tmp_path, daily)
    after = _table(build, "lineup_snapshots")
    # every row the daily build held is still there, byte for byte, with its own state
    kept = after.merge(before, how="inner", on=list(TABLES["lineup_snapshots"][1]), suffixes=("", "_old"))
    assert len(kept) == len(before)
    assert (kept.confirmed == kept.confirmed_old).all() and (kept.state == kept.state_old).all()
    # and no backfilled row shares a key with them
    assert len(after) == len(before) + 2 and not after.duplicated(subset=list(TABLES["lineup_snapshots"][1])).any()


def test_running_it_twice_does_not_duplicate_anything_even_a_week_later(tmp_path):
    daily = _daily(tmp_path)
    first, *_ = _backfill(tmp_path, daily)
    later = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
    # a week later the same first window is read again, plus a newer one the provider has nothing in
    second, *_ = _backfill(tmp_path, first, now=later)
    for name in ("lineup_snapshots", "lineup_slots"):
        a, b = _table(first, name), _table(second, name)
        assert len(a) == len(b), name
        assert not b.duplicated(subset=list(TABLES[name][1])).any(), name
    # the state tables are carried, not rebuilt from the empty reads
    assert _table(second, "crosswalk").equals(_table(daily, "crosswalk"))


def test_only_completed_matches_are_kept(tmp_path):
    daily = _daily(tmp_path)
    unfinished = {**recording._finished_fixture(), "id": 860002, "state": {"developer_name": "NS"}}
    provider = Provider({"fixtures/between/2026-10-10/2026-10-23": {"data": [recording._finished_fixture(), unfinished]}})
    build, summary, *_ = _backfill(tmp_path, daily, provider=provider)
    assert summary["backfill"] == {"fixtures_read": 2, "fixtures_completed": 1, "fixtures_skipped_not_completed": 1}
    assert len(_table(build, "lineup_snapshots")) == len(_table(daily, "lineup_snapshots")) + 2


def test_an_empty_window_does_not_break_the_pass(tmp_path):
    daily = _daily(tmp_path)
    build, summary, *_ = _backfill(tmp_path, daily, provider=Provider({"fixtures/between/2026-10-10/2026-10-23": {"data": []}}))
    validate_build(build)
    assert summary["backfill"]["fixtures_read"] == 0
    assert _table(build, "lineup_slots").equals(_table(daily, "lineup_slots"))


def test_a_season_that_starts_today_has_nothing_to_read(tmp_path):
    daily = _daily(tmp_path)
    feed = FplFeed(recording.FEED.bootstrap, [{"id": 1, "team_h": 1, "team_a": 2, "kickoff_time": "2026-10-24T14:00:00Z", "event": 9}])
    build, summary, provider, transport = _backfill(tmp_path, daily, feed=feed)
    assert summary["windows"] == 0 and transport.calls == 0 and provider.paths == []
    validate_build(build)


def test_the_windows_are_fourteen_days_from_the_season_start_to_yesterday():
    windows = fetch.backfill_windows(date(2026, 8, 22), date(2026, 10, 23))
    assert windows[0] == (date(2026, 8, 22), date(2026, 9, 4)) and windows[-1] == (date(2026, 10, 17), date(2026, 10, 23))
    assert len(windows) == 5 and fetch.planned_count("backfill", windows=len(windows)) == 5
    assert all((b - a).days <= 13 for a, b in windows)
    assert [windows[i][1] + (date(2026, 1, 2) - date(2026, 1, 1)) for i in range(4)] == [w[0] for w in windows[1:]]
    assert fetch.backfill_windows(date(2026, 10, 24), date(2026, 10, 23)) == []


def test_it_reads_one_window_per_call_with_the_same_route_as_the_daily_pass(tmp_path):
    daily = _daily(tmp_path)
    feed = FplFeed(recording.FEED.bootstrap, [{"id": 3000, "team_h": 2, "team_a": 1, "kickoff_time": "2026-08-22T14:00:00Z", "event": 1},
                                              *recording.FEED.fixtures])
    _b, summary, provider, transport = _backfill(tmp_path, daily, feed=feed)
    assert provider.paths == ["fixtures/between/2026-08-22/2026-09-04", "fixtures/between/2026-09-05/2026-09-18",
                              "fixtures/between/2026-09-19/2026-10-02", "fixtures/between/2026-10-03/2026-10-16",
                              "fixtures/between/2026-10-17/2026-10-23"]
    assert transport.calls == summary["windows"] == 5


def test_the_hard_cap_stops_before_the_next_window(tmp_path):
    daily = _daily(tmp_path)
    feed = FplFeed(recording.FEED.bootstrap, [{"id": 3000, "team_h": 2, "team_a": 1, "kickoff_time": "2026-08-22T14:00:00Z", "event": 1}])
    with pytest.raises(BudgetExceeded):
        _backfill(tmp_path, daily, feed=feed, cap=2)


def test_since_narrows_the_range_but_never_widens_it_past_the_season_start(tmp_path):
    daily = _daily(tmp_path)
    _b, summary, provider, _t = _backfill(tmp_path, daily, since=date(2026, 10, 15))
    assert summary["windows"] == 1 and provider.paths == ["fixtures/between/2026-10-15/2026-10-23"]
    _b2, summary2, provider2, _t2 = _backfill(tmp_path / 'wider', daily, since=date(2020, 1, 1))
    assert provider2.paths == ["fixtures/between/2026-10-10/2026-10-23"]


def test_without_a_previous_build_it_fails_instead_of_guessing_the_crosswalk(tmp_path):
    client, _ = _client(Provider())
    with pytest.raises(NoBaseline):
        run_pass("backfill", client, recording.BACKFILL_FEED, tmp_path, now=NOW, previous=None)


def test_the_stamp_is_the_morning_after_the_kickoff_not_the_time_of_the_read(tmp_path):
    daily = _daily(tmp_path)
    build, *_ = _backfill(tmp_path, daily, now=datetime(2026, 11, 20, 3, 33, tzinfo=timezone.utc))
    snaps = _table(build, "lineup_snapshots")
    assert "2026-10-11T00:00:00Z" in set(snaps.observed_at)
    assert not any(stamp.startswith("2026-11-20") for stamp in snaps.observed_at)


# ---- the CLI ------------------------------------------------------------------------------------------------------

def _cli(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_cli_ceiling_for_a_backfill_is_sixty(capsys):
    code, out, _ = _cli(capsys, "--pass", "backfill", "--max-calls", "61")
    assert code == 2 and json.loads(out) == {"reason": "max_calls_out_of_range", "status": "refused"}
    code, out, err = _cli(capsys, "--pass", "backfill", "--max-calls", "60")
    assert (code, err) == (0, "") and json.loads(out)["cap"] == 60


def test_the_cli_dry_run_prints_counts_only(capsys):
    code, out, err = _cli(capsys, "--pass", "backfill")
    summary = json.loads(out)
    assert (code, err) == (0, "") and summary["pass"] == "backfill" and summary["planned_calls"] == summary["calls"] == 1
    assert summary["published"] is False and sorted(i for i in recording.identifiers() if i in out) == []


def test_since_is_for_a_backfill_only_and_must_be_a_date(capsys):
    assert _cli(capsys, "--pass", "daily", "--since", "2026-09-01")[0] == 2
    code, out, _ = _cli(capsys, "--pass", "backfill", "--since", "not-a-date")
    assert code == 2 and json.loads(out)["reason"] == "since_is_not_a_date"
