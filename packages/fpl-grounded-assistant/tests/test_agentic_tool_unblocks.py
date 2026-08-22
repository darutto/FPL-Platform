"""Slice 1 regressions for optional args, price filters, and preseason fallback."""
from __future__ import annotations

from copy import deepcopy

import pytest

from fpl_grounded_assistant.get_gameweek_context import _clear_context_cache
from fpl_grounded_assistant.historical_gameweek_top_scorer import (
    GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC,
)
from fpl_grounded_assistant.rank_players_by_metric import (
    RANK_PLAYERS_BY_METRIC_SPEC,
    rank_players_by_metric,
)
from fpl_grounded_assistant.ranking_provenance import get_ranking_basis
from fpl_grounded_assistant.team_fixture_calendar import TEAM_FIXTURE_CALENDAR_SPEC
from fpl_grounded_assistant.tool_schema_registry import _ALL_SCHEMAS
from fpl_grounded_assistant.transfer_suggestion import (
    TRANSFER_SUGGESTION_SPEC,
    get_transfer_suggestion,
)
from fpl_tool_runner import run_tool


def _event(state: str, deadline: str = "2026-08-14T17:30:00Z") -> dict:
    return {
        "id": 1,
        "deadline_time": deadline,
        "finished": state == "finished",
        "is_current": state in {"in_progress", "finished"},
        "is_next": state == "preseason",
    }


def _player(
    player_id: int,
    name: str,
    *,
    cost: int,
    points: int,
    ppg: float,
    minutes: int = 900,
    form: float = 0.0,
    status: str = "a",
) -> dict:
    return {
        "id": player_id,
        "first_name": name,
        "second_name": "Test",
        "web_name": name,
        "team": 1,
        "element_type": 3,
        "status": status,
        "news": "",
        "minutes": minutes,
        "now_cost": cost,
        "total_points": points,
        "points_per_game": str(ppg),
        "form": str(form),
        "selected_by_percent": "1.0",
    }


def _bootstrap(players: list[dict], state: str = "preseason") -> dict:
    return {
        "events": [_event(state)],
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "element_types": [{"id": 3, "singular_name_short": "MID"}],
        "elements": players,
        "team_fixtures": {},
    }


def test_price_filter_reaches_core_handler_and_both_schema_surfaces():
    bootstrap = _bootstrap([
        _player(1, "Alpha", cost=70, points=100, ppg=5.0),
        _player(2, "Bravo", cost=75, points=90, ppg=4.5),
        _player(3, "Charlie", cost=80, points=110, ppg=5.5),
    ])
    _clear_context_cache()

    result = rank_players_by_metric(
        "total_points",
        position="MID",
        min_price=7.0,
        max_price=7.5,
        bootstrap=bootstrap,
    )
    assert [player["id"] for player in result["ranked"]] == [1, 2]
    assert result["min_price_filter"] == pytest.approx(7.0)
    assert result["max_price_filter"] == pytest.approx(7.5)
    assert result["ranking_basis"] == "prior_season_carryover"
    assert all(
        {"id", "web_name", "team_short", "position", "now_cost",
         "minutes_played_season", "status", "news"} <= player.keys()
        for player in result["ranked"]
    )

    via_runner = run_tool(
        "rank_players_by_metric",
        {"metric": "total_points", "min_price": 7.0, "max_price": 7.5},
        bootstrap,
    )
    assert [player["id"] for player in via_runner["ranked"]] == [1, 2]

    assert {"min_price", "max_price"} <= RANK_PLAYERS_BY_METRIC_SPEC.parameters["properties"].keys()
    llm_schema = next(schema for schema in _ALL_SCHEMAS if schema.name == "rank_players_by_metric")
    assert {"min_price", "max_price"} <= llm_schema.parameters["properties"].keys()


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("preseason", "prior_season_carryover"),
        ("in_progress", "current_season_partial"),
        ("finished", "current_season"),
    ],
)
def test_ranking_basis_uses_all_canonical_gameweek_states(state: str, expected: str):
    _clear_context_cache()
    assert get_ranking_basis(_bootstrap([], state)) == expected


def test_frozen_snapshot_deadline_does_not_change_ranking_basis():
    snapshot = _bootstrap([], "preseason")
    replay = deepcopy(snapshot)
    replay["events"][0]["deadline_time"] = "2001-01-01T00:00:00Z"

    _clear_context_cache()
    first = get_ranking_basis(snapshot)
    _clear_context_cache()
    second = get_ranking_basis(replay)
    assert first == second == "prior_season_carryover"


def test_zero_form_falls_back_to_ppg_and_keeps_eligibility_evidence():
    players = [
        _player(1, "Rice", cost=75, points=184, ppg=5.1, minutes=3093),
        _player(2, "Anderson", cost=65, points=175, ppg=4.9),
        _player(3, "Rogers", cost=70, points=170, ppg=4.8),
        _player(4, "Wilson", cost=65, points=168, ppg=4.7),
        _player(5, "Szoboszlai", cost=70, points=160, ppg=4.4),
        _player(6, "Ghost", cost=45, points=200, ppg=9.0, minutes=0),
        _player(7, "Doubt", cost=45, points=210, ppg=9.5, status="d"),
    ]
    bootstrap = _bootstrap(players)
    _clear_context_cache()

    result = get_transfer_suggestion(
        {"position_query": "MID", "max_price": 7.5, "top_n": 5},
        bootstrap,
    )
    assert result["status"] == "ok"
    assert result["ranking_basis"] == "prior_season_carryover"
    assert result["ranking_metric"] == "points_per_game"
    assert [pick["web_name"] for pick in result["picks"]] == [
        "Rice", "Anderson", "Rogers", "Wilson", "Szoboszlai",
    ]
    assert all(pick["minutes"] > 0 for pick in result["picks"])
    assert all(pick["status"] == "a" for pick in result["picks"])
    assert all({"minutes", "status", "news"} <= pick.keys() for pick in result["picks"])

    via_runner = run_tool(
        "get_transfer_suggestion",
        {"position_query": "MID", "max_price": 7.5},
        bootstrap,
    )
    assert via_runner["ranking_metric"] == "points_per_game"


def test_zero_form_and_ppg_fall_back_to_total_points():
    bootstrap = _bootstrap([
        _player(1, "Low", cost=60, points=80, ppg=0),
        _player(2, "High", cost=60, points=120, ppg=0),
    ])
    _clear_context_cache()
    result = get_transfer_suggestion({"position_query": "MID"}, bootstrap)
    assert result["ranking_metric"] == "total_points"
    assert [pick["web_name"] for pick in result["picks"]] == ["High", "Low"]


def test_optional_tool_specs_no_longer_fake_required_arguments():
    assert TRANSFER_SUGGESTION_SPEC.parameters["required"] == []
    assert TEAM_FIXTURE_CALENDAR_SPEC.parameters["required"] == []
    assert GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC.parameters["required"] == []
