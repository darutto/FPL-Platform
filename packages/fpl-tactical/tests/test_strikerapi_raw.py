"""Never pay twice: paid responses are kept before anything reads them, and read from there ever after.

Synthetic data, a fake transport and a fake R2; no network, no key.
"""

from __future__ import annotations

import json
import shutil
from datetime import timedelta

import pytest

from fpl_tactical import publish, strikerapi_ingest as si
from fpl_tactical.strikerapi_client import StrikerApiClient, StrikerApiError
from fpl_tactical.strikerapi_raw import RawCache, RawCacheError

from .test_strikerapi_ingest import (
    FIXTURES, G1, G2, KICKOFF, NOW, SEASON, FakeApi, client_for, double_meeting, fixture,
    liv_eve_shots, other_source_rows, seed_store,
)

WRONG_SCORE = [fixture("Arsenal", "Manchester City", 1, 0), fixture("Liverpool", "Everton", 5, 0, gw=9)]
BASE = "tactical/2026-2027/strikerapi/raw/"


def api_with_the_new_match(shots=None):
    return FakeApi([G1, G2], {"2": liv_eve_shots() if shots is None else shots})


class FakeBucket:
    def __init__(self, upload_fails=False, download_error=None):
        self.objects, self.upload_fails, self.download_error = {}, upload_fails, download_error

    def upload_file(self, path, bucket, key):
        if self.upload_fails:
            raise PermissionError("denied")
        self.objects[key] = open(path, "rb").read()

    def download_file(self, bucket, key, dest):
        if self.download_error:
            raise self.download_error
        if key not in self.objects:
            error = Exception("not found")
            error.response = {"Error": {"Code": "404"}}  # the shape boto3 raises
            raise error
        open(dest, "wb").write(self.objects[key])


def on_r2(bucket):
    return RawCache(SEASON, bucket, "b", BASE)


def run_sync(api, fixtures=FIXTURES, **kw):
    return si.sync(SEASON, client_for(api), fixtures, **{"now": NOW, **kw})


# ---------------------------------------------------------------- the daily sync


def test_a_failed_validation_followed_by_a_second_sync_makes_no_call(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    first = api_with_the_new_match()
    with pytest.raises(si.ValidationFailed):
        run_sync(first, WRONG_SCORE)
    assert first.spent == 12

    second = api_with_the_new_match()
    with pytest.raises(si.ValidationFailed, match="goals differ"):
        run_sync(second, WRONG_SCORE, now=NOW + timedelta(days=1))
    assert second.calls == []


def test_once_the_data_or_code_is_fixed_the_kept_response_is_stored_for_free(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    with pytest.raises(si.ValidationFailed):
        run_sync(api_with_the_new_match(), WRONG_SCORE)
    api = api_with_the_new_match()
    rep = run_sync(api, max_credits=0)  # nothing to pay, so no ceiling can refuse it
    assert api.calls == [] and rep.action == "synced" and rep.credits_spent == 0 and rep.credits_estimated == 0
    assert si.read_working_store(SEASON)[0]["match_id"].nunique() == 2


def test_a_ci_runner_with_an_empty_disk_reads_the_kept_responses_from_r2(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    bucket = FakeBucket()
    with pytest.raises(si.ValidationFailed):
        run_sync(api_with_the_new_match(), WRONG_SCORE, cache=on_r2(bucket))
    assert {BASE + "2.json", BASE + "list_games_0.json"} <= set(bucket.objects)
    shutil.rmtree(on_r2(bucket).dir)
    api = api_with_the_new_match()
    with pytest.raises(si.ValidationFailed):
        run_sync(api, WRONG_SCORE, cache=on_r2(bucket))
    assert api.calls == []


@pytest.mark.parametrize("shots", [
    [{**liv_eve_shots()[0], "outcome": "a new word"}],  # normalization fails
    [],                                                  # nothing in it: validation fails
])
def test_whatever_is_wrong_with_a_response_it_is_never_bought_again(tmp_tactical_root, shots):
    seed_store(tmp_tactical_root)
    with pytest.raises(si.IngestError):
        run_sync(api_with_the_new_match(shots))
    api = api_with_the_new_match()
    with pytest.raises(si.IngestError, match="outcome|missing match"):
        run_sync(api)
    assert api.calls == []


def test_the_response_is_kept_verbatim_even_when_it_cannot_be_parsed(tmp_tactical_root):
    cache = RawCache(SEASON)
    client = StrikerApiClient(api_key="k-secret", transport=lambda *a: (200, {}, "not json"))
    si._keep_responses(client, cache, NOW)
    with pytest.raises(StrikerApiError):
        client.shot_map_for_game("7")
    kept = cache.get("7")
    assert kept["body"] == "not json" and "k-secret" not in json.dumps(kept)


def test_an_error_status_is_not_kept(tmp_tactical_root):
    cache = RawCache(SEASON)
    client = StrikerApiClient(api_key="k", transport=lambda *a: (503, {}, "down"))
    si._keep_responses(client, cache, NOW)
    with pytest.raises(StrikerApiError):
        client.shot_map_for_game("7")
    assert cache.get("7") is None


def test_only_the_new_match_is_bought_on_a_later_day(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    later = KICKOFF + timedelta(days=7)
    third = {**G2, "game_id": "3", "home": {"abbrev": "CHE"}, "away": {"abbrev": "FUL"}}
    fixtures = FIXTURES + [fixture("Chelsea", "Fulham", 0, 0, kickoff=later, gw=10)]
    run_sync(FakeApi([G1, G2, third], {"2": liv_eve_shots()}), fixtures)
    shots = [{**s, "game_id": "3", "team": {"LIV": "CHE", "EVE": "FUL"}[s["team"]], "outcome": "saved"}
             for s in liv_eve_shots()]
    api = FakeApi([G1, G2, third], {"3": shots})
    run_sync(api, fixtures, now=later + timedelta(days=3))
    assert api.calls == [("get_shot_map", {"game_id": "3"})]  # the kept list already names it


@pytest.mark.parametrize("bucket", [
    FakeBucket(upload_fails=True), FakeBucket(download_error=ConnectionError("r2 down")),
])
def test_when_responses_cannot_be_kept_or_read_nothing_is_bought(tmp_tactical_root, bucket):
    seed_store(tmp_tactical_root)
    api = api_with_the_new_match()
    with pytest.raises(RawCacheError):
        run_sync(api, cache=on_r2(bucket))
    assert api.calls == []


def test_ci_without_r2_refuses_before_any_call(tmp_tactical_root, monkeypatch, capsys):
    from fpl_tactical import cli

    for name in (publish.ENV_R2_ENDPOINT, publish.ENV_R2_BUCKET,
                 publish.ENV_R2_ACCESS_KEY_ID, publish.ENV_R2_SECRET_ACCESS_KEY):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(si, "fetch_fpl_fixtures", lambda: pytest.fail("went on without a cache"))
    assert cli.main(["strikerapi-sync", "--season", SEASON, "--require-r2"]) == 1
    assert "cannot be kept on R2" in capsys.readouterr().err


# ---------------------------------------------------------------- the first load


def test_a_first_load_that_failed_a_check_costs_nothing_to_run_again(tmp_tactical_root, monkeypatch):
    games, shots, fixtures, now = double_meeting()
    backup = other_source_rows(games, shots)
    first = FakeApi(games, shots)
    with pytest.raises(si.ValidationFailed, match="backup canary"):  # two matches: below the minimum sample
        si.load_by_team(SEASON, client_for(first), fixtures, backup, now=now)
    assert first.spent == 22

    monkeypatch.setattr(si, "CANARY_MIN_MATCHES", 2)  # "a human fixes the code"
    monkeypatch.setattr(si, "CANARY_MIN_MATCHED_SHOTS", 1)
    second = FakeApi(games, shots)
    rep = si.load_by_team(SEASON, client_for(second), fixtures, backup, now=now + timedelta(days=1), max_credits=0)
    assert second.calls == [] and rep.credits_spent == 0
    assert len(si.read_working_store(SEASON)[0]) == 20


def test_a_match_that_became_due_after_the_team_files_is_bought_on_its_own(tmp_tactical_root, monkeypatch):
    games, shots, fixtures, both_due = double_meeting()
    only_first_due = KICKOFF + timedelta(days=3)
    backup = other_source_rows(games, shots)
    with pytest.raises(si.ValidationFailed):  # one match: too small a sample
        si.load_by_team(SEASON, client_for(FakeApi(games, shots)), fixtures, backup, now=only_first_due)

    monkeypatch.setattr(si, "CANARY_MIN_MATCHES", 2)
    monkeypatch.setattr(si, "CANARY_MIN_MATCHED_SHOTS", 1)
    api = FakeApi(games, {str(gid): rows for gid, rows in shots.items()})
    rep = si.load_by_team(SEASON, client_for(api), fixtures, backup, now=both_due)
    # the team files held match 2 before it had settled, so its rows there are not used
    assert api.calls == [("get_shot_map", {"game_id": "2"})] and rep.credits_spent == 10
    df = si.read_working_store(SEASON)[0]
    assert len(df) == 20 and df.groupby("match_id").size().tolist() == [10, 10]


def test_publish_never_uploads_the_kept_responses(tmp_tactical_root, monkeypatch):
    seed_store(tmp_tactical_root)
    run_sync(api_with_the_new_match())
    assert list(RawCache(SEASON).dir.glob("*.json"))
    bucket = FakeBucket()
    monkeypatch.setattr(publish, "_make_r2_client", lambda: bucket)
    monkeypatch.delenv("OWNED_STORE_R2_PREFIX", raising=False)
    publish.publish_tactical_store_to_r2(SEASON, "strikerapi")
    assert sorted(bucket.objects) == ["tactical/2026-2027/strikerapi/_tactical_latest.json",
                                      "tactical/2026-2027/strikerapi/shots.parquet"]
    assert publish.strikerapi_raw_location(SEASON)[2] == BASE
