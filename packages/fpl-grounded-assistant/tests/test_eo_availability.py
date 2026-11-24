"""EO rows carry availability (synthetic data; no network, no LLM, no paid call).

An out player must never be offered as cover; a doubtful one stays, flagged; the user's own differential is kept
and flagged; the card marks only out/doubtful players; and the evaluator is shown the rows with those fields.
"""
from __future__ import annotations

import json

import pytest

from fpl_grounded_assistant import league_eo_tool, near_rank_eo_tool as nr, tier_eo_tool
from fpl_grounded_assistant.atomic_tool_cards import compose_league_eo_card, compose_near_rank_eo_card
from fpl_grounded_assistant.evaluator import MODEL_VIEW_KEY, _build_evaluator_user_message
from fpl_grounded_assistant.orchestrator import _truncate_tool_output

TEAMS = [{"id": t, "short_name": f"T{t}"} for t in range(1, 5)]


def el(i, **kw):
    base = {"id": i, "web_name": f"P{i}", "second_name": f"Surname{i}", "team": (i % 4) + 1, "minutes": 900,
            "status": "a", "chance_of_playing_next_round": None}
    base.update(kw)
    return base


def stats(owned, eo, cap=0.0):
    return {"owned_pct": owned, "captain_pct": cap, "bench_pct": 0.0, "eo": eo}


# 1..7 are owned by most of the group (EO descending); 8 is the user's own rare player
PLAYERS = {str(i): stats(90.0 - i, 200.0 - 10 * i) for i in range(1, 8)}
PLAYERS["8"] = stats(5.0, 5.0)
ELEMENTS = [
    el(1, status="i", chance_of_playing_next_round=0),     # out (injured, 0 %)
    el(2, status="d", chance_of_playing_next_round=50),    # doubtful
    el(3, status="s", chance_of_playing_next_round=None),  # out (suspended)
    el(4),
    el(5, status="a", chance_of_playing_next_round=75),    # doubtful by chance alone
    el(6),
    el(7),
    el(8, status="d", chance_of_playing_next_round=25, minutes=450),  # the user's differential, doubtful
]
BOOT = {"teams": TEAMS, "elements": ELEMENTS}
SQUAD = {"status": "ok", "players": [{"id": 8}, {"id": 20}]}


def by_teams():
    return nr._name_index(BOOT)


# -- the fields ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("element, expected", [
    ({"status": "a", "chance_of_playing_next_round": None, "minutes": 1200}, None),
    ({"status": "a", "chance_of_playing_next_round": 100}, None),
    ({"status": "a", "chance_of_playing_next_round": 75}, "doubtful"),
    ({"status": "d", "chance_of_playing_next_round": 50}, "doubtful"),
    ({"status": "d", "chance_of_playing_next_round": None}, "doubtful"),
    ({"status": "d", "chance_of_playing_next_round": 0}, "out"),
    ({"status": "i", "chance_of_playing_next_round": 0}, "out"),
    ({"status": "s"}, "out"), ({"status": "u"}, "out"), ({"status": "n"}, "out"),
    ({"status": "a", "chance_of_playing_next_round": None, "chance_of_playing_this_round": 0}, "out"),  # falls back to this round
    ({}, None),  # an unknown element: nothing known, no flag
])
def test_availability_flag(element, expected):
    f = nr.availability_fields(element)
    assert f.get("availability") == expected
    assert set(f) >= {"minutes_played_season", "status", "chance_of_playing_next_round"}
    assert ("availability" in f) is (expected is not None)  # absent, not null, when fine


def test_the_bootstrap_values_come_through_under_the_shared_names():
    f = nr.availability_fields({"status": "d", "chance_of_playing_next_round": "50", "minutes": 1234})
    assert (f["minutes_played_season"], f["status"], f["chance_of_playing_next_round"]) == (1234, "d", 50)


# -- group_has / differentials ---------------------------------------------------------------------------

def test_an_out_player_is_never_offered_as_cover_and_the_slots_refill():
    by_id, teams = by_teams()
    out = nr.squad_comparison(PLAYERS, SQUAD, by_id, teams)
    ids = [r["player"] for r in out["group_has"]]
    assert "P1" not in ids and "P3" not in ids          # the injured and the suspended one
    assert ids == ["P2", "P4", "P5", "P6", "P7"]        # five slots, refilled from the next candidates
    flagged = {r["player"]: r.get("availability") for r in out["group_has"]}
    assert flagged["P2"] == "doubtful" and flagged["P5"] == "doubtful" and flagged["P4"] is None


def test_the_users_own_differential_is_kept_and_flagged():
    by_id, teams = by_teams()
    out = nr.squad_comparison(PLAYERS, SQUAD, by_id, teams)
    diff = next(r for r in out["differentials"] if r["player"] == "P8")
    assert diff["player"] == "P8" and diff["availability"] == "doubtful" and diff["minutes_played_season"] == 450


def test_every_row_of_the_three_tools_carries_the_fields():
    near = nr.shape_result({"players": PLAYERS, "gw": 11, "user_rank": 5, "n_sampled": 100}, BOOT, ["P2"], SQUAD)
    league = league_eo_tool.shape_result(
        {"gw": 11, "league_id": 42, "league_name": "L", "league_size": 12, "exact": True, "approx": False,
         "n_sampled": 12, "label": "exact, n=12", "players": PLAYERS}, BOOT, ["P2"], SQUAD)
    tier = tier_eo_tool.shape_result({"gw": 11, "n_sampled": 10000, "players": PLAYERS}, BOOT, ["P2"], SQUAD, 11)
    for out in (near, league, tier):
        for key in ("top_players", "named_players", "group_has", "differentials"):
            assert out[key], key
            for row in out[key]:
                assert {"minutes_played_season", "status", "chance_of_playing_next_round"} <= set(row), (key, row)
        assert "P1" not in [r["player"] for r in out["group_has"]]
        assert "availability" in out["note"]  # the wording rule tells the model how to use it


# -- the card ----------------------------------------------------------------------------------------------

def _card(locale):
    raw = {"status": "ok", "tier": "league", "squad_compared": True, "league_name": "L", "exact": True, "n_sampled": 12,
           "league_size": 12, "label": "exact, n=12", **nr.squad_comparison(PLAYERS, SQUAD, *by_teams())}
    return compose_league_eo_card(raw, locale)


def test_card_marks_only_out_or_doubtful_players():
    cells = {r[1]: r for r in _card("en").rows}
    assert cells["P2 (T3) · doubt"]                       # doubtful: short marker
    assert cells["P8 (T1) · doubt"]                       # the differential too
    assert "P4 (T1)" in cells and "P6 (T3)" in cells      # fit players: nothing added
    assert not any("out" in c for c in cells)             # the out ones are not on the card at all
    assert any("· duda" in r[1] for r in _card("es").rows)


# -- what the evaluator sees ------------------------------------------------------------------------------

def test_the_evaluator_input_contains_the_availability_fields():
    """The evaluator is given the model view of each tool call (orchestrator, i124): the same rows the model read."""
    raw = nr.shape_result({"players": PLAYERS, "gw": 11, "user_rank": 5, "n_sampled": 100}, BOOT, [], SQUAD)
    call = {"name": "get_near_rank_eo", "args": {}, "output": raw,
            MODEL_VIEW_KEY: _truncate_tool_output(raw, tool_name="get_near_rank_eo")}
    message = _build_evaluator_user_message("¿EO cerca de mi rango?", "answer", [call])
    assert '"minutes_played_season"' in message and '"status"' in message
    assert '"chance_of_playing_next_round"' in message
    assert '"availability": "doubtful"' in message
    view = json.loads(message.split("get_near_rank_eo DATA: ")[1].split("\n")[0])
    assert all("minutes_played_season" in r for r in view["top_players"] + view["group_has"] + view["differentials"])
