"""StrikerAPI ingest: transform, vocabulary, validation, the due check, credits, canaries.

Synthetic data only, in the real response shape: invented scores and shots, no row
from the vendor. No network (a fake transport stands in), no key.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from fpl_tactical import strikerapi_ingest as si
from fpl_tactical.strikerapi_client import StrikerApiClient, StrikerApiError

SEASON = "2026-2027"
KICKOFF = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)
NOW = KICKOFF + timedelta(days=3)  # past full time + 36 h


# ---------------------------------------------------------------- builders


def game(gid, home, away, kickoff=KICKOFF, status="final"):
    return {
        "game_id": str(gid), "status": status, "starts_at": kickoff.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "home": {"abbrev": home, "score": 0}, "away": {"abbrev": away, "score": 0},
    }


def shot(gid, team, player="A Player", minute=10, x=0.14, y=0.9, outcome="saved", body="right_foot",
         penalty=False, xg=0.1, pid="1"):
    return {"game_id": str(gid), "date": "2026-10-03", "minute": minute, "team": team, "player_id": pid,
            "player": player, "outcome": outcome, "body_part": body, "penalty": penalty, "zone": "x",
            "xg": xg, "x": x, "y": y, "end_x": 0, "end_y": 0.5, "distance_m": 10}


def fixture(home, away, hs, as_, kickoff=KICKOFF, finished=True, own_h=0, own_a=0, gw=8):
    return si.FplFixture(fpl_id=1, gameweek=gw, home=home, away=away, kickoff=kickoff, finished=finished,
                         home_score=hs, away_score=as_, own_goals_for_home=own_h, own_goals_for_away=own_a)


def sched_for(*games):
    return si.schedule_from_games(games)


def frame(shots, games, season=SEASON):
    return si.normalize_shots(shots, sched_for(*games), season)


# ---------------------------------------------------------------- the transform


def test_penalty_spot_lands_on_the_store_spot():
    x, y = si.api_to_store_xy(0.23, 0.5)
    assert (round(x, 3), round(y, 3)) == (0.885, 0.5)
    assert si.flank_zone(x, y) == "in-box / central"


def test_one_shot_per_flank_lands_on_the_right_side():
    right = si.api_to_store_xy(0.14, 0.9)  # api y high -> store y low -> the attacker's right
    left = si.api_to_store_xy(0.14, 0.1)
    assert (round(right[0], 3), round(right[1], 3)) == (0.93, 0.1)
    assert si.flank_zone(*right) == "in-box / right"
    assert si.flank_zone(*left) == "in-box / left"


def test_x_is_never_scaled_the_wrong_way():
    assert si.api_to_store_xy(0.14, 0.5)[0] <= 1.0  # 2*(1-x) would give 1.72


# ---------------------------------------------------------------- normalize and vocabulary


G1 = game(1, "ARS", "MNC")


def test_names_flags_dates_and_vocabulary_are_the_stores():
    df = frame([
        shot(1, "ARS", outcome="goal", body="left_foot"),
        shot(1, "MNC", outcome="woodwork", body="header"),
        shot(1, "MNC", outcome="blocked", body=None, minute=20),
        shot(1, "ARS", outcome="goal", penalty=True, minute=30),
    ], [G1])
    assert set(df["shooting_team"]) == {"Arsenal", "Manchester City"}
    assert set(df["conceding_team"]) == {"Arsenal", "Manchester City"}
    assert df["date"].iloc[0] == "2026-10-03T14:00:00"
    assert list(df["result"]) == ["Goal", "Shot On Post", "Blocked Shot", "Goal"]
    # The real store has only the two foot values; every other shot is null.
    assert df["shot_type"].where(df["shot_type"].notna(), None).tolist() == ["Left Foot", None, None, "Right Foot"]
    assert list(df["is_home_shot"]) == [True, False, False, True]
    assert list(df["situation"].isna()) == [True, True, True, False]
    assert df["situation"].iloc[3] == "Penalty"


@pytest.mark.parametrize("bad", [
    {"outcome": "deflected"},
    {"body": "knee"},
    {"team": "XXX"},
])
def test_unknown_values_fail_the_run(bad):
    kw = {"team": "ARS", **{k: v for k, v in bad.items()}}
    with pytest.raises((si.IngestError, KeyError)):
        frame([shot(1, **kw)], [G1])


def test_shot_of_a_third_team_or_unknown_game_fails():
    with pytest.raises(si.IngestError):
        frame([shot(1, "CHE")], [G1])
    with pytest.raises(si.IngestError):
        frame([shot(99, "ARS")], [G1])


def test_penalty_flag_must_be_a_boolean():
    bad = shot(1, "ARS")
    bad["penalty"] = "false"
    with pytest.raises(si.IngestError):
        frame([bad], [G1])


# ---------------------------------------------------------------- validation


def two_sided(goals_h=1, goals_a=0):
    shots = [shot(1, "ARS", outcome="goal", minute=m) for m in range(goals_h)]
    shots += [shot(1, "MNC", outcome="goal", minute=50 + m) for m in range(goals_a)]
    shots += [shot(1, "ARS", minute=70), shot(1, "MNC", minute=71)]
    return frame(shots, [G1])


def test_a_consistent_match_passes():
    assert si.validate_store(two_sided(1, 0), [fixture("Arsenal", "Manchester City", 1, 0)], NOW) == []


def test_goals_must_equal_the_fpl_score():
    problems = si.validate_store(two_sided(1, 0), [fixture("Arsenal", "Manchester City", 2, 0)], NOW)
    assert any("goals differ" in p for p in problems)


def test_an_own_goal_counts_for_the_other_side_from_fpl():
    df = two_sided(1, 0)
    ok = fixture("Arsenal", "Manchester City", 2, 0, own_h=1)  # City player scored it
    assert si.validate_store(df, [ok], NOW) == []
    wrong_side = fixture("Arsenal", "Manchester City", 2, 0, own_a=1)
    assert si.validate_store(df, [wrong_side], NOW)


def test_missing_match_and_a_side_without_shots_fail():
    df = two_sided(1, 0)
    other = fixture("Liverpool", "Everton", 0, 0)
    assert any("missing match" in p for p in si.validate_store(df, [other], NOW))
    one_side = frame([shot(1, "ARS", outcome="goal")], [G1])
    assert any("no shots for one side" in p for p in
               si.validate_store(one_side, [fixture("Arsenal", "Manchester City", 1, 0)], NOW))


def test_duplicates_and_out_of_range_fail():
    df = two_sided(1, 0)
    dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    assert any("duplicate" in p for p in si.validate_store(dup, [], NOW))
    bad = df.copy()
    bad.loc[0, "x"] = 1.4
    assert any("coordinates" in p for p in si.validate_store(bad, [], NOW))


def test_a_fixture_not_yet_due_is_not_required():
    young = fixture("Liverpool", "Everton", 1, 0, kickoff=NOW - timedelta(hours=5))
    assert si.validate_store(two_sided(1, 0), [fixture("Arsenal", "Manchester City", 1, 0), young], NOW) == []


# ---------------------------------------------------------------- the due check


def test_due_only_after_full_time_plus_36_hours_and_never_twice():
    f = fixture("Liverpool", "Everton", 1, 0)
    assert si.due_fixtures([f], None, f.kickoff + timedelta(hours=37)) == []
    assert si.due_fixtures([f], None, f.kickoff + timedelta(hours=38, minutes=1)) == [f]
    stored = frame([shot(2, "LIV", outcome="goal"), shot(2, "EVE")], [game(2, "LIV", "EVE")])
    assert si.due_fixtures([f], stored, NOW) == []
    assert si.due_fixtures([fixture("Liverpool", "Everton", 1, 0, finished=False)], None, NOW) == []


# ---------------------------------------------------------------- the client


class FakeApi:
    """A transport answering list_games / get_shot_map from canned data and counting credits."""

    def __init__(self, games, shots_by_game, credits=500, pages=None):
        self.games, self.shots, self.credits, self.calls, self.pages = games, shots_by_game, credits, [], pages

    def __call__(self, url, headers, body):
        tool = url.rsplit("/", 1)[1]
        req = json.loads(body)
        self.calls.append((tool, req))
        cost = 2 if tool == "list_games" else 10
        self.credits -= cost
        hdr = {"x-credits-used": str(cost), "x-credits-remaining": str(self.credits)}
        if tool == "list_games":
            data = {"games": self.games, "count": len(self.games), "next_offset": None}
        else:
            data = {"shots": self.shots.get(req.get("game_id"), [])}
        return 200, hdr, json.dumps({"data": data})

    @property
    def spent(self):
        return sum(2 if t == "list_games" else 10 for t, _ in self.calls)


def client_for(api):
    return StrikerApiClient(api_key="k-secret", transport=api)


def test_client_reads_credit_headers_and_never_echoes_the_key():
    api = FakeApi([G1], {})
    c = client_for(api)
    c.list_games(2026)
    assert c.credits_remaining == 498 and c.credits_spent == 2
    failing = StrikerApiClient(api_key="k-secret", transport=lambda *a: (500, {}, "boom"))
    with pytest.raises(StrikerApiError) as exc:
        failing.shot_map_for_game("1")
    assert "k-secret" not in str(exc.value)


def test_client_without_a_key_says_so_and_calls_nothing():
    calls = []
    c = StrikerApiClient(api_key="", transport=lambda *a: calls.append(a))
    c.api_key = None
    with pytest.raises(StrikerApiError, match="STRIKERAPI_KEY"):
        c.list_games(2026)
    assert calls == []


def test_list_games_pages_until_next_offset_is_empty():
    pages = [
        {"games": [G1], "next_offset": 200},
        {"games": [game(2, "LIV", "EVE")], "next_offset": None},
    ]
    seen = []

    def transport(url, headers, body):
        seen.append(json.loads(body))
        return 200, {}, json.dumps({"data": pages[len(seen) - 1]})

    games = StrikerApiClient(api_key="k", transport=transport).list_games(2026)
    assert [g["game_id"] for g in games] == ["1", "2"]
    assert seen[0] == {"season": 2026, "status": "final", "limit": 200}
    assert seen[1]["offset"] == 200


# ---------------------------------------------------------------- sync


G2 = game(2, "LIV", "EVE")


def seed_store(tmp_tactical_root):
    first = two_sided(1, 0)
    ptr = si._build_pointer(first, SEASON, {}, [], NOW, None)
    si.write_working_store(first, ptr, SEASON)


def liv_eve_shots():
    return [shot(2, "LIV", outcome="goal"), shot(2, "LIV", minute=40), shot(2, "EVE", minute=41)]


FIXTURES = [fixture("Arsenal", "Manchester City", 1, 0), fixture("Liverpool", "Everton", 1, 0, gw=9)]


def test_nothing_due_makes_no_call_and_spends_nothing(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    api = FakeApi([G1, G2], {})
    rep = si.sync(SEASON, client_for(api), FIXTURES[:1], now=NOW)
    assert rep.action == "nothing_due" and api.calls == []


def test_sync_fetches_only_the_due_match_and_stores_it(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    api = FakeApi([G1, G2], {"2": liv_eve_shots()})
    rep = si.sync(SEASON, client_for(api), FIXTURES, now=NOW)
    assert rep.action == "synced" and rep.fetched == 1
    assert [t for t, _ in api.calls] == ["list_games", "get_shot_map"] and api.spent == 12
    df, ptr = si.read_working_store(SEASON)
    assert df["match_id"].nunique() == 2 and ptr["validation"]["status"] == "ok"
    assert ptr["source"] == "strikerapi" and ptr["situation"] == "unknown" and ptr["data_through_gw"] == 9


def test_a_second_run_does_not_refetch(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    si.sync(SEASON, client_for(FakeApi([G1, G2], {"2": liv_eve_shots()})), FIXTURES, now=NOW)
    api = FakeApi([G1, G2], {"2": liv_eve_shots()})
    assert si.sync(SEASON, client_for(api), FIXTURES, now=NOW).action == "nothing_due"
    assert api.calls == []


def test_over_the_ceiling_refuses_before_any_call(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    due = [fixture("Liverpool", "Everton", 1, 0)] + [
        fixture(h, a, 0, 0) for h, a in [("Chelsea", "Fulham"), ("Brentford", "Leeds")]]
    api = FakeApi([G1, G2], {})
    with pytest.raises(si.SyncRefused, match="ceiling"):
        si.sync(SEASON, client_for(api), [FIXTURES[0]] + due, now=NOW, max_credits=20)
    assert api.calls == []


def test_refuses_when_the_source_reports_too_few_credits(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    api = FakeApi([G1, G2], {"2": liv_eve_shots()}, credits=11)  # list_games leaves 9
    with pytest.raises(si.SyncRefused, match="remaining"):
        si.sync(SEASON, client_for(api), FIXTURES, now=NOW)
    assert [t for t, _ in api.calls] == ["list_games"]


def test_failed_validation_publishes_and_stores_nothing(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    before = si.read_working_store(SEASON)[0].copy()
    wrong = [fixture("Arsenal", "Manchester City", 1, 0), fixture("Liverpool", "Everton", 5, 0, gw=9)]
    with pytest.raises(si.ValidationFailed, match="goals differ"):
        si.sync(SEASON, client_for(FakeApi([G1, G2], {"2": liv_eve_shots()})), wrong, now=NOW)
    pd.testing.assert_frame_equal(si.read_working_store(SEASON)[0], before)


def test_a_due_match_missing_from_the_source_for_three_days_raises_an_alert(tmp_tactical_root):
    seed_store(tmp_tactical_root)
    late = FIXTURES[1]
    soon = si.sync(SEASON, client_for(FakeApi([G1], {})), FIXTURES, now=late.due_at + timedelta(days=1))
    assert soon.missing_alerts == [] and soon.action == "nothing_due"
    later = si.sync(SEASON, client_for(FakeApi([G1], {})), FIXTURES, now=late.due_at + timedelta(days=3))
    assert later.missing_alerts and "Liverpool-Everton" in later.missing_alerts[0]


def test_sync_without_a_first_load_says_so(tmp_tactical_root):
    with pytest.raises(si.SyncRefused, match="strikerapi-load"):
        si.sync(SEASON, client_for(FakeApi([], {})), FIXTURES, now=NOW)


def test_the_working_store_never_touches_the_serving_paths(tmp_tactical_root):
    from fpl_tactical.paths import latest_pointer_path, shots_parquet_path

    seed_store(tmp_tactical_root)
    assert not shots_parquet_path(SEASON).exists() and not latest_pointer_path(SEASON).exists()


# ---------------------------------------------------------------- canaries


def player_rows(name, n, y, team="Arsenal", other="Chelsea"):
    return [{"season": SEASON, "match_id": i, "date": "2026-10-03T14:00:00", "shooting_team": team,
             "conceding_team": other, "player": name, "is_home_shot": True, "minute": 10 + i,
             "x": 0.93, "y": y, "xg": 0.1, "situation": None, "shot_type": "Right Foot",
             "result": "Saved Shot"} for i in range(n)]


def overlap_pair(mirror=False, matches=30, shots_per_match=10):
    """The 'other source' rows and ours for the same matches; ours optionally mirrored."""
    rows_b, rows_n = [], []
    for m in range(matches):
        for k in range(shots_per_match):
            y = 0.1 + 0.8 * ((k % 5) / 4)  # 0.1 .. 0.9
            base = {"season": SEASON, "match_id": m, "date": "2026-10-03T14:00:00",
                    "shooting_team": f"H{m}", "conceding_team": f"A{m}", "player": f"P{k}",
                    "is_home_shot": True, "minute": 5 + 2 * k, "x": 0.93, "xg": 0.1, "situation": None,
                    "shot_type": "Right Foot", "result": "Saved Shot"}
            rows_b.append({**base, "y": y})
            rows_n.append({**base, "y": 1 - y if mirror else y})
    return pd.DataFrame(rows_n), pd.DataFrame(rows_b)


def test_backup_canary_passes_on_agreeing_rows():
    new, backup = overlap_pair()
    res = si.compare_with_backup(new, backup)
    assert res["status"] == "ok" and res["zone_agreement"] >= 0.9 and res["opposite_flank"] == 0


def test_backup_canary_fails_when_the_vendor_flips_an_axis():
    new, backup = overlap_pair(mirror=True)
    res = si.compare_with_backup(new, backup)
    assert res["status"] == "mismatch" and res["opposite_flank"] > 0.02


def test_backup_canary_with_too_little_overlap_says_not_checked_never_ok():
    new, backup = overlap_pair(matches=3)
    assert si.compare_with_backup(new, backup)["status"] == "not_checked"


def test_flank_players_come_from_measured_rows_not_a_list():
    trusted = pd.DataFrame(
        player_rows("Left Winger", 12, 0.9) + player_rows("Right Winger", 12, 0.1)
        + player_rows("Both Sides", 12, 0.9)[:6] + player_rows("Both Sides", 12, 0.1)[:6]
        + player_rows("Few Shots", 3, 0.9))
    picked = si.pick_flank_players(trusted)
    assert picked == {"left": ["left winger"], "right": ["right winger"]}


def test_pooled_flank_canary_passes_fails_on_mirror_and_reports_small_samples():
    players = {"left": ["left winger"], "right": ["right winger"]}
    ours = pd.DataFrame(player_rows("Left Winger", 30, 0.9) + player_rows("Right Winger", 30, 0.1))
    assert si.flank_canary(ours, players)["status"] == "ok"
    mirrored = ours.assign(y=1 - ours["y"])
    assert si.flank_canary(mirrored, players)["status"] == "mismatch"
    small = pd.DataFrame(player_rows("Left Winger", 5, 0.9))
    assert si.flank_canary(small, players)["status"] == "not_checked"
    assert si.flank_canary(ours, {"left": [], "right": []})["status"] == "not_checked"


def test_sync_fails_closed_when_the_flank_canary_sees_a_flip(tmp_tactical_root):
    first = pd.DataFrame(
        player_rows("Left Winger", 30, 0.9) + player_rows("Right Winger", 30, 0.1))
    first["match_id"] = 1
    first["shooting_team"], first["conceding_team"] = "Arsenal", "Manchester City"
    ptr = si._build_pointer(first, SEASON, {}, [], NOW, {"left": ["left winger"], "right": ["right winger"]})
    si.write_working_store(first, ptr, SEASON)
    flipped = [shot(2, "LIV", player="Left Winger", x=0.14, y=0.9, outcome="goal") for _ in range(1)]
    flipped += [shot(2, "LIV", player="Left Winger", x=0.14, y=0.9, minute=20 + i) for i in range(60)]
    flipped += [shot(2, "EVE", minute=99)]
    api = FakeApi([G1, G2], {"2": flipped})
    with pytest.raises(si.ValidationFailed, match="flank canary"):
        si.sync(SEASON, client_for(api), [fixture("Liverpool", "Everton", 1, 0, gw=9)], now=NOW)
