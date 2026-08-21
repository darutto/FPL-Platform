"""compare_players must hand the tied players up to its caller.

`/comparar bruno vs João Pedro` used to answer with a dead-end message: the
resolver knew exactly which Brunos matched, but `_score_one`'s failure branch
dropped that list, so nothing downstream could offer a disambiguation wizard.
These pins keep the list attached to both slots.
"""
from __future__ import annotations

import copy

import pytest

from fpl_grounded_assistant.comparison import compare_players
from fpl_grounded_assistant.suggestions import player_disambiguation_suggestions


_ELEMENTS = [
    {"id": 1, "first_name": "Erling", "second_name": "Haaland", "web_name": "Haaland",
     "team": 1, "element_type": 4, "status": "a", "now_cost": 145, "minutes": 900,
     "selected_by_percent": "52.3", "form": "8.0", "total_points": 120,
     "expected_goals": "1.5", "expected_assists": "0.2",
     "expected_goal_involvements": "1.7"},
    {"id": 6, "first_name": "Adam", "second_name": "Johnson", "web_name": "Johnson",
     "team": 1, "element_type": 3, "status": "a", "now_cost": 50, "minutes": 900,
     "selected_by_percent": "0.5", "form": "2.0", "total_points": 30,
     "expected_goals": "0.1", "expected_assists": "0.05",
     "expected_goal_involvements": "0.15"},
    {"id": 7, "first_name": "Glen", "second_name": "Johnson", "web_name": "Johnson",
     "team": 2, "element_type": 2, "status": "a", "now_cost": 45, "minutes": 900,
     "selected_by_percent": "0.3", "form": "1.5", "total_points": 20,
     "expected_goals": "0.05", "expected_assists": "0.02",
     "expected_goal_involvements": "0.07"},
]

_BOOTSTRAP = {
    "elements": _ELEMENTS,
    "teams": [
        {"id": 1, "name": "Alpha", "short_name": "ALP"},
        {"id": 2, "name": "Beta", "short_name": "BET"},
    ],
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
    "events": [{"id": 1, "is_current": True, "is_next": False}],
}


@pytest.fixture
def bootstrap():
    return copy.deepcopy(_BOOTSTRAP)


@pytest.mark.parametrize(
    "query_a, query_b, expected_slot",
    [
        ("Johnson", "Haaland", "Johnson"),   # ambiguity in slot A
        ("Haaland", "Johnson", "Johnson"),   # ambiguity in slot B
    ],
)
def test_candidates_survive_from_either_slot(bootstrap, query_a, query_b, expected_slot):
    result = compare_players(query_a, query_b, bootstrap)
    assert result["status"] == "ambiguous"
    assert result["error_player"] == expected_slot
    assert [c["id"] for c in result["candidates"]] == [6, 7]


def test_both_queries_are_kept_so_the_comparison_can_be_resumed(bootstrap):
    """Resolving the ambiguity means re-running the SAME comparison, so the
    untouched side has to survive alongside the candidate list."""
    result = compare_players("Johnson", "Haaland", bootstrap)
    assert result["query_a"] == "Johnson"
    assert result["query_b"] == "Haaland"


def test_candidates_feed_the_shared_chip_builder(bootstrap):
    """Same candidate shape as get_player_snapshot, so one chip builder serves
    both ambiguity sources."""
    result = compare_players("Johnson", "Haaland", bootstrap)
    chips = player_disambiguation_suggestions(result["candidates"])
    assert chips is not None
    assert [chip.player_id for chip in chips] == [6, 7]
    assert all(chip.label for chip in chips)


def test_successful_comparison_is_unaffected(bootstrap):
    result = compare_players("Haaland", "Adam Johnson", bootstrap)
    assert result["status"] == "ok"
    assert "candidates" not in result
