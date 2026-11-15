"""R6: the ingestion reads each finished match's player statistics in the SAME windows. Synthetic data, no network."""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd
import pytest

from football_intelligence.ingestion.licensed.player_stats import STAT_COLUMNS
from football_intelligence.ingestion.licensed.store import validate_build
from licensed_ingestion import fetch, recording
from licensed_ingestion.budget import BudgetExceeded, CountingTransport
from licensed_ingestion.run import run_pass
from sportmonks_client.client import SportmonksClient
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.transport import TransportResponse

NOW = recording.NOW
WINDOW = "fixtures/between/2026-10-10/2026-10-23"
LATER = NOW + timedelta(days=7)
TYPES_PATH = "fixtures/860000"
#: Invented type ids on purpose.
TOUCHES, PASSES, BACKWARD, MINUTES, RARE = 7001, 7002, 7003, 7004, 7005
#: The curated names the default four-name types answer leaves unknown (their columns are None, not zero).
UNRESOLVED_WITH_FOUR = sorted(set(STAT_COLUMNS) - {"TOUCHES", "PASSES", "BACKWARD_PASSES", "MINUTES_PLAYED"})


class Provider:
    """The backfill recording with a finished match that carries details; logs path and params of every request."""

    def __init__(self, details_by_player=None, types=None):
        self.calls: list[tuple[str, dict]] = []
        self.recording = {**recording.BACKFILL_PROVIDER, WINDOW: {"data": [self._fixture(details_by_player)]},
                          TYPES_PATH: {"data": {"id": 860000, "lineups": [{"details": [
                              {"id": 500 + i, "type_id": i, "data": {"value": 1}, "type": {"developer_name": n}}
                              for i, n in (types or {TOUCHES: "TOUCHES", PASSES: "PASSES", BACKWARD: "BACKWARD_PASSES",
                                                    MINUTES: "MINUTES_PLAYED"}).items()]}]}}}

    @staticmethod
    def _fixture(details_by_player):
        fixture = recording._finished_fixture()
        details = details_by_player or {780002: [(MINUTES, 90), (TOUCHES, 70), (PASSES, 50), (BACKWARD, 12)],
                                        780012: [(MINUTES, 45), (TOUCHES, 30)], 780003: []}
        lineups = [{**row, "details": [{"type_id": t, "data": {"value": v}} for t, v in details.get(row["player_id"], [])]}
                   for row in fixture["lineups"]]
        return {**fixture, "lineups": lineups}

    def request(self, method, url, *, params, timeout):
        path = url.split("/v3/football/", 1)[-1]
        self.calls.append((path, dict(params)))
        if path not in self.recording:
            return TransportResponse(200, {}, {"data": []})
        return TransportResponse(200, {}, self.recording[path])


def _client(provider, cap=1_000):
    transport = CountingTransport(provider, cap)
    return SportmonksClient.offline(transport, config=SportmonksConfig()), transport


def _daily(root):
    client, _ = _client(recording.RecordedTransport())
    return run_pass("daily", client, recording.FEED, root, now=NOW, previous=None)[0]


def _backfill(root, previous, provider, cap=1_000, now=NOW):
    client, transport = _client(provider, cap)
    build, summary = run_pass("backfill", client, recording.BACKFILL_FEED, root, now=now, previous=previous)
    return build, summary, transport


def _table(build, name):
    return pd.read_parquet(build / f"datasets/{name}.parquet")


def test_a_backfill_stores_the_finished_matchs_statistics_keyed_by_fpl_ids(tmp_path):
    build, summary, _ = _backfill(tmp_path, _daily(tmp_path), Provider())
    validate_build(build)
    stats = _table(build, "player_match_stats").set_index("element")
    assert set(stats.index) == {5002, 5012}                                   # 5003 has no details = no minutes
    row = stats.loc[5002]
    assert (row.fixture_id, row.team, row.touches, row.passes, row.backward_passes, row.minutes) == (3000, "ARS", 70, 50, 12, 90)
    assert row.observed_at == "2026-10-11T00:00:00Z" and pd.isna(row.accurate_passes) and row.starter
    assert stats.loc[5012].backward_passes == 0                               # absent = zero, with minutes
    assert summary["rows"]["player_match_stats"] == 2


def test_the_type_names_are_learned_once_and_then_read_from_the_store(tmp_path):
    first, summary, _ = _backfill(tmp_path, _daily(tmp_path), Provider())
    assert summary["stat_types"] == {"known": 4, "learned": 4, "provider_calls": 1, "unknown_after": 0,
                                     "columns_unresolved": UNRESOLVED_WITH_FOUR}
    assert dict(_table(first, "stat_types").values.tolist()) == {TOUCHES: "TOUCHES", PASSES: "PASSES",
                                                                 BACKWARD: "BACKWARD_PASSES", MINUTES: "MINUTES_PLAYED"}
    provider = Provider()
    second, summary, _ = _backfill(tmp_path, first, provider, now=LATER)
    assert summary["stat_types"] == {"known": 4, "learned": 0, "provider_calls": 0, "unknown_after": 0,
                                     "columns_unresolved": UNRESOLVED_WITH_FOUR}
    assert TYPES_PATH not in [path for path, _p in provider.calls]            # no call: every id is already known
    assert len(_table(second, "player_match_stats")) == 2                     # idempotent: the same keys, nothing doubled


def test_an_unknown_type_triggers_one_refresh_and_a_type_still_unknown_is_skipped_and_counted(tmp_path):
    first, *_ = _backfill(tmp_path, _daily(tmp_path), Provider())
    details = {780002: [(MINUTES, 90), (TOUCHES, 70), (RARE, 4)], 780012: [(MINUTES, 45), (RARE, 1)]}
    provider = Provider(details)                                              # the types answer does not name RARE
    second, summary, _ = _backfill(tmp_path, first, provider, now=LATER)
    assert summary["stat_types"]["provider_calls"] == 1 and summary["stat_types"]["unknown_after"] == 1
    assert [p for p, _q in provider.calls].count(TYPES_PATH) == 1
    assert len(_table(second, "player_match_stats")) == 2                     # the rows stand; only RARE is left out


def test_the_type_call_goes_to_the_finished_match_that_carries_the_most_unknown_ids(tmp_path):
    first, *_ = _backfill(tmp_path, _daily(tmp_path), Provider())
    provider = Provider()                                                     # 860000: only ids already known
    other = {**provider.recording[WINDOW]["data"][0], "id": 860001}
    other["lineups"] = [{**r, "details": [*r["details"], {"type_id": RARE, "data": {"value": 2}}]} if r["details"] else r
                        for r in other["lineups"]]
    provider.recording[WINDOW] = {"data": [provider.recording[WINDOW]["data"][0], other]}
    provider.recording["fixtures/860001"] = {"data": {"id": 860001, "lineups": [{"details": [
        {"id": 600, "type_id": RARE, "data": {"value": 2}, "type": {"developer_name": "THROUGH_BALLS"}}]}]}}
    _, summary, _ = _backfill(tmp_path, first, provider, now=LATER)
    paths = [p for p, _q in provider.calls]
    assert "fixtures/860001" in paths and TYPES_PATH not in paths             # not simply the first finished match
    assert summary["stat_types"]["learned"] == 1 and summary["stat_types"]["unknown_after"] == 0
    assert "THROUGH_BALLS" not in summary["stat_types"]["columns_unresolved"]


def test_a_pass_with_no_finished_details_makes_no_type_call(tmp_path):
    provider = Provider({})
    provider.recording[WINDOW] = {"data": []}
    _, summary, _ = _backfill(tmp_path, _daily(tmp_path), provider)
    assert summary["stat_types"] == {"known": 0, "learned": 0, "provider_calls": 0, "unknown_after": 0,
                                     "columns_unresolved": []}
    assert TYPES_PATH not in [p for p, _q in provider.calls]


def test_details_are_requested_only_where_a_match_has_been_played_and_in_small_pages(tmp_path):
    provider = Provider()
    client, _ = _client(provider)
    fetch.daily(client, NOW.date())
    windows = [(p, q) for p, q in provider.calls if p.startswith("fixtures/between/") and p.count("/") == 3]
    ahead = [q for p, q in windows if p.endswith("2026-11-06") and "2026-10-24/" in p]
    played = [q for p, q in windows if p == "fixtures/between/2026-10-17/2026-10-23"]
    assert ahead and "lineups.details" not in ahead[0]["include"] and ahead[0]["per_page"] == fetch.PER_PAGE
    assert played and "lineups.details" in played[0]["include"] and played[0]["per_page"] == fetch.STATS_PER_PAGE == 10
    # a page of 10 at ~100 KB a fixture stays far under the client's default response bound
    assert fetch.STATS_PER_PAGE * 100 * 1024 < SportmonksConfig().max_response_bytes / 3


def test_the_matchday_and_deadline_windows_do_not_ask_for_details(tmp_path):
    provider = Provider()
    client, _ = _client(provider)
    fetch.matchday(client, NOW)
    fetch.deadline(client, NOW.date())
    assert provider.calls and all("lineups.details" not in q["include"] for _p, q in provider.calls)


def test_the_hard_cap_still_stops_a_backfill_that_reads_too_much(tmp_path):
    daily = _daily(tmp_path)
    with pytest.raises(BudgetExceeded):
        _backfill(tmp_path, daily, Provider(), cap=1)                         # the window read is call 1; the types call is 2


def test_the_summary_holds_counts_only(tmp_path):
    _, summary, _ = _backfill(tmp_path, _daily(tmp_path), Provider())
    text = json.dumps(summary)
    assert [i for i in recording.identifiers() if i in text] == []
    assert not any(str(i) in text for i in (TOUCHES, PASSES, BACKWARD, MINUTES, "TOUCHES", "BACKWARD_PASSES"))
