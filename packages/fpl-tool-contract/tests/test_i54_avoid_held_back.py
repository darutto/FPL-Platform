"""i54 — the ranking must not recommend a player it labels "avoid".

The defect: ``ok_results.sort(key=captain_score)`` ignored the tier it had just
computed. A high scorer with rotation risk could land in the top few carrying
the label "avoid", the prose would quietly skip over it, and the card and the
text then said opposite things about the same player. The user reads the card.

The decision (owner's, 2026-09-06): take them out of the top. Not delete them —
held back, with the reason, so the caller can still show them. Measured before
deciding: 1 "avoid" in 48 top-12 slots across four snapshots, so this removes
roughly nothing and cannot empty a list.
"""
from __future__ import annotations

from typing import Any

import pytest

from fpl_tool_contract.tools import tool_rank_captain_candidates


def _element(pid: int, name: str, *, minutes: float, status: str = "a") -> dict[str, Any]:
    return {
        "id": pid,
        "web_name": name,
        "first_name": name,
        "second_name": "Test",
        "element_type": 3,
        "team": 1,
        "status": status,
        "team_join_date": "2026-07-01",
        "form": "8.0",
        "minutes": minutes,
        "expected_goal_involvements_per_90": "0.6",
        "selected_by_percent": "10.0",
        "now_cost": 70,
    }


@pytest.fixture()
def bootstrap() -> dict[str, Any]:
    """Two strong scorers; one of them played exactly half the minutes.

    That is the real shape of the case that opened this card: not a bad player
    sneaking in, but a good one landing on the wrong side of a threshold.
    """
    return {
        "elements": [
            _element(1, "Reliable", minutes=180.0),
            _element(2, "Rotated", minutes=90.0),
        ],
        "teams": [{"id": 1, "name": "Test FC", "short_name": "TST"}],
        "events": [{"id": 3, "is_current": True, "finished": False}],
        "fixture_difficulty_map": {1: 2},
        "team_fixtures": {
            1: [
                {
                    "finished": True,
                    "kickoff_time": "2026-08-15T14:00:00Z",
                    "minutes": 90,
                    "official_fixture_context_complete": True,
                },
                {
                    "finished": True,
                    "kickoff_time": "2026-08-22T14:00:00Z",
                    "minutes": 90,
                    "official_fixture_context_complete": True,
                },
            ]
        },
    }


def _ranked(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in result["ranked_candidates"] if e.get("status") == "ok"]


def _names(entries: list[dict[str, Any]]) -> list[str]:
    return [e["web_name"] for e in entries]


# --- the defect itself ------------------------------------------------------

def test_no_avoid_survives_in_the_ranking(bootstrap):
    """The whole point: nothing labelled avoid is offered as a recommendation."""
    result = tool_rank_captain_candidates(None, bootstrap, gameweek=3)
    assert [e for e in _ranked(result) if e["tier"] == "avoid"] == []


def test_a_high_score_does_not_buy_its_way_past_the_tier(bootstrap):
    """Guards the exact regression: sorting by score alone put this player in.

    "Rotated" outscores nobody by accident — he is here because a player with a
    real score and real rotation risk is precisely what the old sort promoted.
    """
    result = tool_rank_captain_candidates(None, bootstrap, gameweek=3)
    held = {e["web_name"] for e in result["held_back"]}
    assert "Rotated" in held
    assert "Rotated" not in _names(_ranked(result))


def test_held_back_is_not_deleted(bootstrap):
    """Nobody disappears. The caller gets them, with score, tier and reason."""
    result = tool_rank_captain_candidates(None, bootstrap, gameweek=3)
    (held,) = [e for e in result["held_back"] if e["web_name"] == "Rotated"]
    assert held["held_back_reason"] == "avoid"
    assert held["tier"] == "avoid"
    assert held["captain_score"] > 0
    assert held["rank"] is None, "a held-back player has no rank to show"


def test_ranks_stay_contiguous_after_the_removal(bootstrap):
    """No gap where the removed player used to be — rank 2 must not vanish."""
    result = tool_rank_captain_candidates(None, bootstrap, gameweek=3)
    ranks = [e["rank"] for e in _ranked(result)]
    assert ranks == list(range(1, len(ranks) + 1))


# --- who is never held back -------------------------------------------------

def test_a_player_the_caller_named_is_still_answered(bootstrap):
    """"Should I captain X?" — avoid IS the answer, not a reason to say nothing.

    Silently dropping a named player would turn a warning into a blank.

    Both players are named on purpose. Asking about the risky one alone would
    make every candidate "avoid", and the never-empty rule would carry this test
    without the caller rule ever being exercised — it would pass for the wrong
    reason. (It did, until a mutation run showed the rule could be deleted with
    nothing going red.)
    """
    result = tool_rank_captain_candidates(
        [{"query": "Reliable"}, {"query": "Rotated"}], bootstrap, gameweek=3
    )
    assert set(_names(_ranked(result))) == {"Reliable", "Rotated"}
    assert result["held_back"] == []


def test_a_player_the_user_owns_is_still_shown(bootstrap):
    """It is their squad. A warning about their own player is information."""
    result = tool_rank_captain_candidates(
        None, bootstrap, gameweek=3, squad_player_ids=[2]
    )
    assert "Rotated" in _names(_ranked(result))
    assert result["held_back"] == []


def test_an_all_avoid_pool_still_answers(bootstrap):
    """A bad best option beats no option. Emptying the ranking answers nothing.

    The tier travels with the entry, so the caller can still say it is a poor
    week to captain anyone.
    """
    bootstrap["elements"] = [_element(2, "Rotated", minutes=90.0)]
    result = tool_rank_captain_candidates(None, bootstrap, gameweek=3)
    assert _names(_ranked(result)) == ["Rotated"]
    assert result["held_back"] == []
    assert _ranked(result)[0]["tier"] == "avoid"


# --- the presented lists ----------------------------------------------------

def test_the_shown_lists_never_name_a_held_back_player(bootstrap):
    """presentation is a view over the ranking, so it must inherit the rule."""
    result = tool_rank_captain_candidates(None, bootstrap, gameweek=3)
    held_ids = {e["player_id"] for e in result["held_back"]}
    presentation = result["presentation"]
    shown = set(presentation["owned_top"]) | set(presentation["global_top"])
    for hipster in (presentation["owned_hipster"], presentation["global_hipster"]):
        if hipster.get("player_id") is not None:
            shown.add(hipster["player_id"])
    assert shown.isdisjoint(held_ids)
