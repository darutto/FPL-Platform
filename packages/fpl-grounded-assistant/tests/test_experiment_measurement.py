"""Adversarial tests for the agentic-loop experiment legality rubric."""
from __future__ import annotations

from collections import Counter

from fpl_grounded_assistant.experiment_measurement import (
    SQUAD_QUOTAS,
    exact_completion,
    grade_structured_output,
    validate_decision_payload,
    validate_selection_payload,
)


def _player(player_id: int, position: int, club: int, cost: int = 50) -> dict:
    return {
        "id": player_id,
        "web_name": f"P{player_id}",
        "element_type": position,
        "team": club,
        "now_cost": cost,
        "status": "a",
        "minutes": 900,
    }


def _legal_bootstrap() -> dict:
    players = [
        _player(1, 1, 1), _player(2, 1, 2),
        _player(3, 2, 3), _player(4, 2, 4), _player(5, 2, 5),
        _player(6, 2, 6), _player(7, 2, 7),
        _player(8, 3, 8), _player(9, 3, 9), _player(10, 3, 10),
        _player(11, 3, 1), _player(12, 3, 2),
        _player(13, 4, 3, 155), _player(14, 4, 4), _player(15, 4, 5),
        _player(16, 4, 6), _player(17, 4, 7),
    ]
    return {"elements": players}


def _selection_payload(bootstrap: dict, scenario: str = "Q7") -> dict:
    players = {player["id"]: player for player in bootstrap["elements"]}
    locked = [13]
    if scenario == "Q7":
        primary, alternative, formation = [8, 9, 10, 11], [8, 9, 10, 12], "5-4-1"
    else:
        primary, alternative, formation = [14, 15], [16, 17], "3-4-3"
    locked_cost = sum(players[player_id]["now_cost"] for player_id in locked)
    selection_cost = sum(players[player_id]["now_cost"] for player_id in primary)
    return {
        "locked_players": locked,
        "locked_cost": locked_cost / 10,
        "primary_selection": primary,
        "alternative_selection": alternative,
        "quoted_prices": {
            str(player_id): players[player_id]["now_cost"] / 10 for player_id in primary
        },
        "formation": formation,
        "selection_cost": selection_cost / 10,
        "total_cost_including_locked": (locked_cost + selection_cost) / 10,
        "remaining_budget": (1000 - locked_cost - selection_cost) / 10,
        "ranking_basis": "prior_season_carryover",
    }


def _decision_payload(bootstrap: dict) -> dict:
    players = {player["id"]: player for player in bootstrap["elements"]}
    squad = list(range(1, 16))
    xi = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    return {
        "verdict": "viable",
        "squad_selection": squad,
        "starting_xi": xi,
        "bench_selection": bench,
        "formation": "3-4-3",
        "total_cost": sum(players[player_id]["now_cost"] for player_id in squad) / 10,
        "ranking_basis": "prior_season_carryover",
        "reasons": ["Every bench player has a playable fixture."],
    }


def test_exact_flow_succeeds_on_greedy_counterexample_and_recovers_legal_witness():
    # Fixed squad leaves one GKP and one DEF. Club A already has two fixed
    # players. Greedy takes A's cheap keeper and blocks A's only affordable DEF;
    # exact flow takes the slightly dearer B keeper plus A defender.
    fixed = [
        _player(1, 1, 3, 40),
        _player(2, 2, 4, 40), _player(3, 2, 5, 40),
        _player(4, 2, 6, 40), _player(5, 2, 7, 40),
        _player(6, 3, 1, 40), _player(7, 3, 1, 40),
        _player(8, 3, 8, 40), _player(9, 3, 9, 40), _player(10, 3, 10, 40),
        _player(11, 4, 11, 40), _player(12, 4, 12, 40), _player(13, 4, 13, 40),
    ]
    candidates = [
        _player(14, 1, 1, 40),  # greedy choice, but consumes Club A's final slot
        _player(15, 1, 2, 45),  # exact choice
        _player(16, 2, 1, 40),  # only affordable defender
        _player(17, 2, 14, 100),
    ]
    bootstrap = {"elements": fixed + candidates}
    result = exact_completion(
        bootstrap,
        locked_ids=[player["id"] for player in fixed],
        selected_ids=[],
        budget_tenths=605,
    )
    assert result["completion_exists"] is True
    assert result["completion_ids"] == [15, 16]

    witness = [next(player for player in bootstrap["elements"] if player["id"] == player_id)
               for player_id in result["witness_squad"]]
    assert Counter(player["element_type"] for player in witness) == Counter(SQUAD_QUOTAS)
    assert max(Counter(player["team"] for player in witness).values()) <= 3
    assert sum(player["now_cost"] for player in witness) <= 605


def test_exact_flow_reports_genuine_budget_infeasibility():
    bootstrap = _legal_bootstrap()
    result = exact_completion(bootstrap, [13], [14, 15], budget_tenths=200)
    assert result["completion_exists"] is False


def test_exact_flow_fails_immediately_for_fixed_club_cap_violation():
    bootstrap = {"elements": [_player(index, 3, 1) for index in range(1, 5)]}
    result = exact_completion(bootstrap, [1, 2, 3, 4], [])
    assert result == {
        "completion_exists": False,
        "witness_squad": [],
        "reason": "fixed_club_cap_exceeded",
    }


def test_valid_selection_and_decision_payloads_pass():
    bootstrap = _legal_bootstrap()
    assert validate_selection_payload("Q7", _selection_payload(bootstrap), bootstrap, [13])["valid"]
    assert validate_selection_payload("Q9", _selection_payload(bootstrap, "Q9"), bootstrap, [13])["valid"]
    assert validate_decision_payload(_decision_payload(bootstrap), bootstrap)["valid"]


def test_fluent_but_wrong_selection_fails_budget_and_club_limits():
    bootstrap = _legal_bootstrap()
    payload = _selection_payload(bootstrap)
    # Put Haaland and three selected midfielders at Club 3, and lie about costs.
    for player_id in (8, 9, 10):
        bootstrap["elements"][player_id - 1]["team"] = 3
    payload["selection_cost"] = 1.0
    result = validate_selection_payload("Q7", payload, bootstrap, [13])
    assert result["valid"] is False
    assert any(error.startswith("club_cap") for error in result["errors"])
    assert "budget_reconciliation:selection_cost" in result["errors"]


def test_duplicate_ids_and_partial_price_map_fail():
    bootstrap = _legal_bootstrap()
    payload = _selection_payload(bootstrap)
    payload["primary_selection"] = [8, 8, 10, 11]
    payload["quoted_prices"].pop("10")
    result = validate_selection_payload("Q7", payload, bootstrap, [13])
    assert "duplicate_primary_ids" in result["errors"]
    assert "quoted_prices_keys" in result["errors"]


def test_q6_xi_bench_must_partition_and_bench_must_have_goalkeeper():
    bootstrap = _legal_bootstrap()
    payload = _decision_payload(bootstrap)
    payload["bench_selection"] = [6, 7, 8, 12]
    result = validate_decision_payload(payload, bootstrap)
    assert "xi_bench_partition" in result["errors"]
    assert "bench_composition" in result["errors"]


def test_structured_output_missing_is_not_scored_invalid():
    result = grade_structured_output("Q6", "A substantive prose answer without JSON.", {}, _legal_bootstrap(), [])
    assert result["status"] == "structured_output_missing"
    assert result["valid"] is None
