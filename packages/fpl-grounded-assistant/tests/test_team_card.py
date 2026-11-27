"""POST /card kind team: the builder and the route. The made-up league of ``query_golden``; no network, no model."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import card_route, team_card
from test_query_engine import world

CLUB = "Alder Town"


class Source:
    """The gameweek cache's surface over the made-up league."""

    def __init__(self, batch):
        self.batch, self.calls = batch, []

    def load(self, gameweeks, bootstrap):
        self.calls.append(tuple(gameweeks))
        return self.batch


def league():
    bootstrap, batch = world()
    fixtures = [{**f, "event": gw, "finished": True} for gw, data in batch.gameweeks.items() for f in data.fixtures]
    bootstrap["_all_fixtures"] = fixtures
    bootstrap[team_card.CACHE_KEY] = Source(batch)
    return bootstrap, batch


def team_of(bootstrap, name=CLUB):
    return next(t for t in bootstrap["teams"] if t["name"] == name)


def scores(fixtures, team_id):
    """(for, against) of each finished match, counted here rather than by the product."""
    out = []
    for f in fixtures:
        if team_id == f["team_h"]:
            out.append((f["team_h_score"], f["team_a_score"]))
        elif team_id == f["team_a"]:
            out.append((f["team_a_score"], f["team_h_score"]))
    return out


# ------------------------------------------------------------------------------------------------------ builder

def test_table_row_matches_a_count_of_the_scores():
    bootstrap, _ = league()
    team = team_of(bootstrap)
    table = team_card.build_team_card(team["id"], bootstrap)["table"]
    played = scores(bootstrap["_all_fixtures"], team["id"])
    assert table["played"] == len(played)
    assert (table["gf"], table["ga"]) == (sum(a for a, _ in played), sum(b for _, b in played))
    assert table["points"] == sum(3 if a > b else 1 if a == b else 0 for a, b in played)
    assert table["teams"] == len(bootstrap["teams"]) and len(table["form"]) == 5


def test_league_table_order_is_points_then_goal_difference_then_goals():
    teams = [{"id": i, "name": n} for i, n in enumerate(("A", "B", "C", "D", "E", "F"), start=1)]
    fx = [{"event": 1, "finished": True, "team_h": h, "team_a": a, "team_h_score": hs, "team_a_score": as_}
          for h, a, hs, as_ in ((1, 2, 1, 0), (3, 4, 3, 1), (5, 6, 4, 2))]
    assert [r["name"] for r in team_card.league_table(fx, teams)][:3] == ["E", "C", "A"]


def test_stats_goals_equal_the_scores_and_the_recent_window_is_five_gameweeks():
    bootstrap, _ = league()
    team = team_of(bootstrap)
    stats = team_card.build_team_card(team["id"], bootstrap)["stats"]
    played = scores(bootstrap["_all_fixtures"], team["id"])
    assert stats["season"]["goals_for"]["total"] == sum(a for a, _ in played)
    assert stats["season"]["goals_against"]["total"] == sum(b for _, b in played)
    assert stats["recent"]["goals_for"]["gameweeks"] == [4, 5, 6, 7, 8]
    for window in ("season", "recent"):
        row = stats[window]
        assert len({row[k]["matches"] for k in team_card.STAT_METRICS}) == 1
        assert row["xg_for"]["per_match"] == pytest.approx(row["xg_for"]["total"] / row["xg_for"]["matches"], abs=0.01)


def test_each_gameweek_window_is_loaded_once():
    bootstrap, _ = league()
    team_card.build_team_card(team_of(bootstrap)["id"], bootstrap)
    assert len(bootstrap[team_card.CACHE_KEY].calls) == 2


def test_a_missing_gameweek_gives_no_season_figure_and_names_it():
    bootstrap, batch = league()
    del batch.gameweeks[2]
    batch.unavailable[2] = "fetch_failed"
    stats = team_card.build_team_card(team_of(bootstrap)["id"], bootstrap)["stats"]
    season = stats["season"]["xg_for"]
    assert season["total"] is None and season["reason"] == "fetch_failed" and season["missing_gameweeks"] == [2]
    assert stats["recent"]["xg_for"]["total"] is not None


def test_one_section_failing_keeps_the_others(monkeypatch):
    bootstrap, _ = league()
    monkeypatch.setattr(team_card, "_stats_section", lambda *a: 1 / 0)
    card = team_card.build_team_card(team_of(bootstrap)["id"], bootstrap)
    assert card["stats"] is None and card["table"] is not None and card["players"]


def test_next_fixtures_come_from_the_schedule_without_the_matches_already_played():
    bootstrap, _ = league()
    team = team_of(bootstrap)
    other = next(t for t in bootstrap["teams"] if t["id"] != team["id"])
    for event in bootstrap["events"]:
        event.update(is_current=False, is_next=False)
    bootstrap["events"].append({"id": 9, "finished": False, "is_current": True, "is_next": False})
    bootstrap["team_fixtures"] = {team["id"]: [
        {"gameweek": gw, "opponent_team": other["id"], "is_home": True, "difficulty": 2} for gw in (9, 10)]}
    bootstrap["_all_fixtures"].append({"event": 9, "finished": True, "team_h": team["id"], "team_a": other["id"],
                                       "team_h_score": 1, "team_a_score": 0})
    fixtures = team_card.build_team_card(team["id"], bootstrap)["fixtures"]
    assert fixtures["next"] == [
        {"gameweek": 10, "opponent_short": other["short_name"], "is_home": True, "difficulty": 2}]


@pytest.mark.parametrize("current_played, expected", [(True, [10, 11, 12, 13, 14]), (False, [9, 10, 11, 12, 13])])
def test_next_fixtures_cover_five_gameweeks_still_to_play(current_played, expected):
    bootstrap, _ = league()
    team = team_of(bootstrap)
    other = next(t for t in bootstrap["teams"] if t["id"] != team["id"])
    for event in bootstrap["events"]:
        event.update(is_current=False, is_next=False)
    bootstrap["events"] += [{"id": gw, "finished": False, "is_current": gw == 9, "is_next": gw == 10}
                            for gw in range(9, 17)]
    bootstrap["team_fixtures"] = {team["id"]: [
        {"gameweek": gw, "opponent_team": other["id"], "is_home": True, "difficulty": 2} for gw in range(9, 17)]}
    if current_played:
        bootstrap["_all_fixtures"].append({"event": 9, "finished": True, "team_h": team["id"],
                                           "team_a": other["id"], "team_h_score": 1, "team_a_score": 0})
    fixtures = team_card.build_team_card(team["id"], bootstrap)["fixtures"]
    assert [f["gameweek"] for f in fixtures["next"]] == expected


def test_players_are_the_clubs_top_five_by_points():
    bootstrap, _ = league()
    team = team_of(bootstrap)
    players = team_card.build_team_card(team["id"], bootstrap)["players"]
    squad = sorted((e["total_points"] for e in bootstrap["elements"] if e["team"] == team["id"]), reverse=True)
    assert [p["total_points"] for p in players] == squad[:5]


def test_data_stamp_changes_with_a_figure():
    bootstrap, _ = league()
    card = team_card.build_team_card(team_of(bootstrap)["id"], bootstrap)
    first = team_card.data_stamp(card)
    card["table"]["points"] += 1
    assert team_card.data_stamp(card) != first


# -------------------------------------------------------------------------------------------------------- route

@pytest.fixture
def client(monkeypatch, tmp_path):
    bootstrap, _ = league()
    monkeypatch.setattr(fpl_server, "_bootstrap", bootstrap)
    monkeypatch.setattr(fpl_server, "_CARD_LIMIT", card_route.WindowLimit(3, 60.0))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("FPL_INTERNAL_TOKEN", raising=False)

    def boom(*a, **k):
        raise AssertionError("the card path must not reach quota or the model")

    for name in ("check_quota", "_record_turn"):
        monkeypatch.setattr(fpl_server, name, boom)
    import fpl_grounded_assistant.orchestrator as orch
    for name in ("run_orchestrator", "ask_orchestrated"):
        if hasattr(orch, name):
            monkeypatch.setattr(orch, name, boom)

    http = TestClient(fpl_server.app)
    http.team_id = team_of(bootstrap)["id"]
    http.lines = lambda: [json.loads(line) for f in tmp_path.glob("*.ndjson")
                          for line in f.read_text(encoding="utf-8").splitlines()]
    return http


USER = {"X-User-Id": "user_abc"}


def test_route_serves_the_card_and_audits_enums_only(client):
    response = client.post("/card", json={"kind": "team", "team_id": client.team_id, "locale": "en"}, headers=USER)
    body = response.json()
    assert response.status_code == 200 and body["v"] == 1 and body["kind"] == "team"
    assert body["card"]["team"]["name"] == CLUB and body["data_stamp"] == team_card.data_stamp(body["card"])
    (line,) = client.lines()
    assert (line["branch"], line["card_kind"], line["outcome"], line["tokens"]) == ("card", "team", "ok", {})
    assert line["question"] == "" and line["final_text_preview"] == "" and line["usd_cost_estimate"] in (None, 0)
    assert "user_abc" not in json.dumps(line) and CLUB not in json.dumps(line)


def test_route_unknown_team_is_404(client):
    assert client.post("/card", json={"kind": "team", "team_id": 999}, headers=USER).status_code == 404
    assert client.lines()[0]["outcome"] == "not_found"


@pytest.mark.parametrize("body", [{"kind": "player", "team_id": 1}, {"kind": "team", "team_id": "1"},
                                  {"kind": "team"}, {"kind": "team", "team_id": 1, "question": "x"}])
def test_route_refuses_a_bad_body(client, body):
    assert client.post("/card", json=body).status_code == 422


def test_route_rate_limit_is_per_user(client):
    payload = {"kind": "team", "team_id": client.team_id}
    assert [client.post("/card", json=payload, headers=USER).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert client.post("/card", json=payload, headers={"X-User-Id": "user_other"}).status_code == 200
    assert "rate_limited" in [line["outcome"] for line in client.lines()]


def test_a_forged_user_id_does_not_get_its_own_bucket(client, monkeypatch):
    monkeypatch.setenv("FPL_INTERNAL_TOKEN", "secret")
    payload = {"kind": "team", "team_id": client.team_id}
    codes = [client.post("/card", json=payload, headers={"X-User-Id": f"forged_{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]


def test_window_limit_frees_up_after_the_window():
    now = [0.0]
    limit = card_route.WindowLimit(2, 60.0, clock=lambda: now[0])
    assert [limit.allow("a"), limit.allow("a"), limit.allow("a")] == [True, True, False]
    now[0] = 61.0
    assert limit.allow("a")
