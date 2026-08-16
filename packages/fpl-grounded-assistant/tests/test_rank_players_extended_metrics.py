"""Coverage for price, momentum, set-piece, and detailed bootstrap rankings."""

from __future__ import annotations

import pytest

from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
from fpl_grounded_assistant.find_players import _build_match_dict
from fpl_grounded_assistant.rank_players_by_metric import rank_players_by_metric


def _element(player_id: int, name: str, **metrics) -> dict:
    element = {
        "id": player_id,
        "first_name": name,
        "second_name": "Test",
        "web_name": name,
        "team": 1,
        "element_type": 3,
        "status": "a",
        "minutes": 900,
        "expected_goal_involvements_per_90": "0.25",
    }
    element.update(metrics)
    return element


@pytest.fixture()
def extended_bootstrap() -> dict:
    return {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "element_types": [{"id": 3, "singular_name_short": "MID"}],
        "elements": [
            _element(
                1, "Alpha", now_cost=80, transfers_in_event=100,
                transfers_out_event=900, penalties_order=2,
                direct_freekicks_order=None,
                corners_and_indirect_freekicks_order=1, yellow_cards=4,
                red_cards=0, expected_goals_conceded="10.5",
                influence="80.0", creativity="10.0", threat="30.0", saves=5,
            ),
            _element(
                2, "Bravo", now_cost=125, transfers_in_event=500,
                transfers_out_event=100, penalties_order=1,
                direct_freekicks_order=2,
                corners_and_indirect_freekicks_order=2, yellow_cards=1,
                red_cards=1, expected_goals_conceded="20.5",
                influence="70.0", creativity="90.0", threat="40.0", saves=20,
            ),
            _element(
                3, "Charlie", now_cost=60, transfers_in_event=200,
                transfers_out_event=600, penalties_order=None,
                direct_freekicks_order=1,
                corners_and_indirect_freekicks_order=None, yellow_cards=2,
                red_cards=2, expected_goals_conceded="5.5",
                influence="100.0", creativity="50.0", threat="120.0", saves=40,
            ),
        ],
    }


@pytest.mark.parametrize(
    ("alias", "canonical", "winner"),
    [
        ("precio", "now_cost", "Bravo"),
        ("transfers_in", "transfers_in_event", "Bravo"),
        ("transfers_out", "transfers_out_event", "Alpha"),
        ("penales", "penalties_order", "Bravo"),
        ("córners", "corners_and_indirect_freekicks_order", "Alpha"),
        ("tiros libres", "direct_freekicks_order", "Charlie"),
        ("tarjetas amarillas", "yellow_cards", "Alpha"),
        ("tarjetas rojas", "red_cards", "Charlie"),
        ("xgc", "expected_goals_conceded", "Bravo"),
        ("influencia", "influence", "Charlie"),
        ("creatividad", "creativity", "Bravo"),
        ("amenaza", "threat", "Charlie"),
        ("paradas", "saves", "Charlie"),
        ("xgi/90", "expected_goal_involvements_per_90", "Alpha"),
    ],
)
def test_extended_aliases_resolve_and_rank(
    extended_bootstrap, alias: str, canonical: str, winner: str
):
    result = rank_players_by_metric(alias, bootstrap=extended_bootstrap)

    assert result["status"] == "ok"
    assert result["metric"] == canonical
    assert result["ranked"][0]["web_name"] == winner


def test_price_metric_value_is_user_facing_millions(extended_bootstrap):
    result = rank_players_by_metric("price", top_n=1, bootstrap=extended_bootstrap)

    assert result["ranked"][0]["now_cost"] == 125
    assert result["ranked"][0]["metric_value"] == pytest.approx(12.5)


@pytest.mark.parametrize("metric", ["penalties", "corners", "free kicks"])
def test_unlisted_set_piece_players_are_excluded(extended_bootstrap, metric: str):
    result = rank_players_by_metric(metric, bootstrap=extended_bootstrap)

    assert result["status"] == "ok"
    assert all(entry["metric_value"] > 0 for entry in result["ranked"])
    assert [entry["metric_value"] for entry in result["ranked"]] == sorted(
        entry["metric_value"] for entry in result["ranked"]
    )


def test_grounding_payload_adds_level_two_fields(extended_bootstrap):
    element = extended_bootstrap["elements"][0]
    payload = _build_match_dict(
        element, extended_bootstrap["teams"], extended_bootstrap["element_types"],
        match_rank=0,
    )

    assert payload["expected_goals_conceded"] == pytest.approx(10.5)
    assert payload["influence"] == pytest.approx(80.0)
    assert payload["creativity"] == pytest.approx(10.0)
    assert payload["threat"] == pytest.approx(30.0)
    assert payload["saves"] == 5
    assert payload["yellow_cards"] == 4
    assert payload["red_cards"] == 0
    assert payload["penalties_order"] == 2
    assert payload["direct_freekicks_order"] is None
    assert payload["corners_and_indirect_freekicks_order"] == 1


def test_snapshot_projection_does_not_drop_new_grounding_fields(extended_bootstrap):
    player = _build_match_dict(
        extended_bootstrap["elements"][1], extended_bootstrap["teams"],
        extended_bootstrap["element_types"], match_rank=0,
    )
    player.update({"fixtures": [], "team_fdr_context": None})

    meta = _extract_player_snapshot_meta({"status": "ok", "player": player})

    assert meta is not None
    assert meta.expected_goals_conceded == pytest.approx(20.5)
    assert meta.creativity == pytest.approx(90.0)
    assert meta.saves == 20
    assert meta.penalties_order == 1
    assert meta.direct_freekicks_order == 2
    assert meta.corners_and_indirect_freekicks_order == 2


def test_shortest_prefix_preserves_base_metric_when_per90_variant_exists(
    extended_bootstrap,
):
    for element in extended_bootstrap["elements"]:
        element["expected_goal_involvements"] = "1.0"

    result = rank_players_by_metric(
        "expected_goal_involvement", bootstrap=extended_bootstrap,
    )

    assert result["status"] == "ok"
    assert result["metric"] == "expected_goal_involvements"


def test_short_prefix_does_not_guess_between_distinct_metric_families(
    extended_bootstrap,
):
    result = rank_players_by_metric("transfer", bootstrap=extended_bootstrap)

    assert result["status"] == "invalid_argument"
    assert result["code"] == "unknown_metric"
