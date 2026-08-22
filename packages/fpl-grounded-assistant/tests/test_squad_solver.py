"""Verification for the promoted squad solver and the build_squad tool.

Deterministic and offline: every assertion runs against the frozen bootstrap
``field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`` (sha256
4cbb9fa1...) or against small synthetic fixtures. No API calls.

Verification points, in the order the task states them:

1. Every generated squad is legal -- 15 unique players, 2/5/5/3, <=3 per club,
   total <= 100.0, all available with minutes played.
2. The exact Q6 failure is now unreachable: the historical arm-B squad is
   pinned here, shown to be illegal, and the solver's answer to the same
   question is legal.
3. Haaland locked at 15.5 (Q7) yields a legal completion whose totals reconcile
   to the penny, computed in integer now_cost tenths.
4. A genuinely infeasible constraint set returns an explicit infeasible answer
   and never a best-effort illegal squad. THIS IS THE ONE THAT MUST NOT
   REGRESS: silently returning an illegal squad is the current failure.
5. The greedy counterexample from the measurement-harness tests still passes
   from the solver's new home.
6. The points_per_game vs total_points objective choice is pinned against known
   players, so a change of basis is visible rather than silent.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from fpl_grounded_assistant.build_squad_tool import build_squad as build_squad_tool
from fpl_grounded_assistant.squad_solver import (
    CLUB_CAP,
    SQUAD_QUOTAS,
    build_squad,
    exact_completion,
    parse_formation,
    validate_squad,
    _player_index,
)


BOOTSTRAP_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json"
)
FULL_BUDGET_TENTHS = 1000


@pytest.fixture(scope="module")
def bootstrap() -> dict:
    if not BOOTSTRAP_PATH.exists():
        pytest.skip(f"frozen bootstrap not present at {BOOTSTRAP_PATH}")
    return json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def players(bootstrap: dict) -> dict:
    return _player_index(bootstrap)


def _player(player_id: int, position: int, club: int, cost: int = 50, score: int = 0) -> dict:
    return {
        "id": player_id,
        "web_name": f"P{player_id}",
        "element_type": position,
        "team": club,
        "now_cost": cost,
        "status": "a",
        "minutes": 900,
        "total_points": score,
        "points_per_game": str(score),
    }


def _assert_legal_squad(result: dict, players: dict, budget_tenths: int) -> None:
    """Verification point 1, applied to any ok result."""
    assert result["status"] == "ok", result.get("message")
    ids = [entry["id"] for entry in result["squad"]]

    assert len(ids) == 15
    assert len(set(ids)) == 15, "squad contains a duplicate player"

    positions = Counter(int(players[pid]["element_type"]) for pid in ids)
    assert positions == Counter(SQUAD_QUOTAS)

    clubs = Counter(int(players[pid]["team"]) for pid in ids)
    assert max(clubs.values()) <= CLUB_CAP, f"club cap broken: {clubs}"

    total = sum(int(players[pid]["now_cost"]) for pid in ids)
    assert total <= budget_tenths, f"{total} tenths over a {budget_tenths} budget"

    for pid in ids:
        assert players[pid]["status"] == "a", f"{pid} is not flagged available"
        assert int(players[pid]["minutes"]) > 0, f"{pid} has no minutes"

    # The solver's own re-check must agree with this independent one.
    assert (
        validate_squad(ids, players, budget_tenths=budget_tenths, quotas=SQUAD_QUOTAS) == []
    )


# ---------------------------------------------------------------------------
# 1. Every generated squad is legal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("objective", ["total_points", "points_per_game"])
def test_generated_squads_are_legal_for_every_objective(bootstrap, players, objective):
    result = build_squad(bootstrap, objective=objective)
    _assert_legal_squad(result, players, FULL_BUDGET_TENTHS)


@pytest.mark.parametrize("budget_tenths", [1000, 950, 900, 850, 830])
def test_generated_squads_are_legal_across_budgets(bootstrap, players, budget_tenths):
    result = build_squad(bootstrap, budget_tenths=budget_tenths)
    _assert_legal_squad(result, players, budget_tenths)


@pytest.mark.parametrize("formation", ["4-5-1", "5-4-1", "3-4-3", "4-4-2", "3-5-2"])
def test_requested_formation_is_honoured_and_the_xi_partitions_the_squad(
    bootstrap, players, formation
):
    result = build_squad(bootstrap, formation=formation)
    _assert_legal_squad(result, players, FULL_BUDGET_TENTHS)

    assert result["formation"] == formation
    xi = [entry["id"] for entry in result["starting_xi"]]
    bench = [entry["id"] for entry in result["bench"]]
    assert len(xi) == 11
    assert len(bench) == 4
    assert set(xi) | set(bench) == {entry["id"] for entry in result["squad"]}
    assert not set(xi) & set(bench)

    shape = parse_formation(formation)
    xi_positions = Counter(int(players[pid]["element_type"]) for pid in xi)
    assert xi_positions[1] == 1
    assert (xi_positions[2], xi_positions[3], xi_positions[4]) == shape
    # FPL requires a keeper on the bench, and it takes the first bench slot.
    assert int(players[bench[0]]["element_type"]) == 1


def test_totals_are_derived_from_the_squad_and_reconcile(bootstrap, players):
    result = build_squad(bootstrap)
    ids = [entry["id"] for entry in result["squad"]]

    recomputed = sum(int(players[pid]["now_cost"]) for pid in ids)
    assert result["total_cost_tenths"] == recomputed
    assert result["remaining_tenths"] == result["budget_tenths"] - recomputed
    # Millions are display-only: they must be exactly tenths/10, never rounded
    # independently, or a stated total can drift from the squad.
    assert result["total_cost"] == round(recomputed / 10, 1)
    assert result["budget"] == round(result["budget_tenths"] / 10, 1)
    assert result["remaining"] == round(result["remaining_tenths"] / 10, 1)
    assert sum(entry["price_tenths"] for entry in result["squad"]) == recomputed


def test_provenance_and_optimality_are_declared(bootstrap):
    result = build_squad(bootstrap)
    # Pre-season: last season's numbers are all there is, and the result says so.
    assert result["ranking_basis"] == "prior_season_carryover"
    assert result["objective"] == "total_points"
    assert result["objective_optimality"] == "lagrangian_plus_single_swap_fixpoint"


# ---------------------------------------------------------------------------
# 2. The Q6 failure is unreachable
# ---------------------------------------------------------------------------

#: The squad from ``anthropic/B/Q6/1``. Every price and club in it was grounded
#: correctly against this same bootstrap, and the answer stated "Coste total:
#: 100.0m". It totals 117.5 and puts four players in each of ARS and MCI.
Q6_ARM_B_SQUAD_IDS = [1, 4, 388, 387, 426, 397, 452, 480, 13, 411, 165, 498, 236, 106, 199]


def test_the_historical_q6_squad_is_illegal_and_the_solver_says_so(players):
    errors = validate_squad(
        Q6_ARM_B_SQUAD_IDS,
        players,
        budget_tenths=FULL_BUDGET_TENTHS,
        quotas=SQUAD_QUOTAS,
    )
    # The failure this whole module exists to make unreachable, pinned.
    assert any(error.startswith("budget:1175>1000") for error in errors), errors
    assert sum(1 for error in errors if error.startswith("club_cap:")) == 2, errors
    assert sum(int(players[pid]["now_cost"]) for pid in Q6_ARM_B_SQUAD_IDS) == 1175


def test_q6_inputs_now_produce_a_legal_squad(bootstrap, players):
    """Same question, same bootstrap, same 100.0m: 117.5 is now impossible."""
    result = build_squad(bootstrap)
    _assert_legal_squad(result, players, FULL_BUDGET_TENTHS)

    assert result["total_cost_tenths"] != 1175
    assert result["total_cost_tenths"] <= FULL_BUDGET_TENTHS
    assert all(count <= CLUB_CAP for count in result["club_counts"].values())
    # The claimed total is the computed total, not a restated one.
    assert result["total_cost"] == round(result["total_cost_tenths"] / 10, 1)


# ---------------------------------------------------------------------------
# 3. Q7 — Haaland locked at 15.5
# ---------------------------------------------------------------------------

HAALAND_ID = 411


@pytest.mark.parametrize("formation", ["4-5-1", "5-4-1"])
def test_haaland_locked_reconciles_to_the_penny(bootstrap, players, formation):
    result = build_squad(bootstrap, locked_ids=[HAALAND_ID], formation=formation)
    _assert_legal_squad(result, players, FULL_BUDGET_TENTHS)

    ids = [entry["id"] for entry in result["squad"]]
    assert HAALAND_ID in ids
    haaland = next(entry for entry in result["squad"] if entry["id"] == HAALAND_ID)
    assert haaland["locked"] is True
    assert haaland["price_tenths"] == 155
    assert haaland["price"] == 15.5

    # The "-15.5 start" arithmetic, in integer tenths throughout.
    assert result["locked_cost_tenths"] == 155
    assert result["budget_tenths"] == 1000
    rest = result["total_cost_tenths"] - result["locked_cost_tenths"]
    assert rest == sum(
        entry["price_tenths"] for entry in result["squad"] if entry["id"] != HAALAND_ID
    )
    assert result["locked_cost_tenths"] + rest + result["remaining_tenths"] == 1000
    assert result["formation"] == formation
    assert any(entry["id"] == HAALAND_ID for entry in result["starting_xi"])


def test_locked_player_is_resolved_by_name_through_the_tool(bootstrap, players):
    result = build_squad_tool(
        budget=100.0, locked_players=["Haaland"], formation="5-4-1", bootstrap=bootstrap
    )
    _assert_legal_squad(result, players, FULL_BUDGET_TENTHS)
    assert HAALAND_ID in [entry["id"] for entry in result["squad"]]
    assert result["locked_cost_tenths"] == 155


def test_tool_refuses_to_guess_an_unresolvable_lock(bootstrap):
    result = build_squad_tool(locked_players=["Nokoloko Notaplayer"], bootstrap=bootstrap)
    assert result["status"] == "not_found"
    assert "squad" not in result or not result.get("squad")


# ---------------------------------------------------------------------------
# 4. Infeasibility is explicit -- the regression that must never come back
# ---------------------------------------------------------------------------

def test_budget_too_small_returns_infeasible_not_a_best_effort_squad(bootstrap):
    # Well below the cheapest legal 15 that can be assembled from this bootstrap.
    result = build_squad(bootstrap, budget_tenths=500)
    assert result["status"] == "infeasible"
    assert result["squad"] == []
    assert result["minimum_possible_cost_tenths"] > 500
    assert result["shortfall_tenths"] == result["minimum_possible_cost_tenths"] - 500
    assert "No legal squad exists" in result["message"]


def test_locked_players_breaking_the_club_cap_return_infeasible(bootstrap, players):
    arsenal = [
        pid
        for pid, player in sorted(players.items())
        if int(player["team"]) == int(players[4]["team"]) and player["status"] == "a"
    ][:4]
    assert len(arsenal) == 4
    result = build_squad(bootstrap, locked_ids=arsenal)
    assert result["status"] == "infeasible"
    assert result["code"] == "fixed_club_cap_exceeded"
    assert result["squad"] == []


def test_locked_players_alone_over_budget_return_infeasible(bootstrap):
    result = build_squad(bootstrap, locked_ids=[HAALAND_ID], budget_tenths=100)
    assert result["status"] == "infeasible"
    assert result["code"] == "fixed_budget_exceeded"
    assert result["squad"] == []


def test_infeasible_synthetic_pool_never_yields_a_partial_squad():
    # Only one goalkeeper exists, so no legal 15 can be built at any budget.
    elements = [_player(1, 1, 1)]
    elements += [_player(100 + i, 2, 1 + (i % 6), 40) for i in range(10)]
    elements += [_player(200 + i, 3, 1 + (i % 6), 40) for i in range(10)]
    elements += [_player(300 + i, 4, 1 + (i % 6), 40) for i in range(10)]
    result = build_squad({"elements": elements, "teams": []}, budget_tenths=10_000)
    assert result["status"] == "infeasible"
    assert result["squad"] == []


def test_a_squad_is_never_returned_alongside_an_infeasible_status(bootstrap):
    for kwargs in (
        {"budget_tenths": 500},
        {"budget_tenths": 100, "locked_ids": [HAALAND_ID]},
    ):
        result = build_squad(bootstrap, **kwargs)
        assert result["status"] == "infeasible"
        assert not result["squad"]
        assert not result.get("starting_xi")


# ---------------------------------------------------------------------------
# 5. The greedy counterexample, from the solver's new home
# ---------------------------------------------------------------------------

def test_exact_flow_succeeds_on_greedy_counterexample_from_the_new_home():
    # Fixed squad leaves one GKP and one DEF. Club A already has two fixed
    # players. Greedy takes A's cheap keeper and blocks A's only affordable DEF;
    # exact flow takes the slightly dearer B keeper plus the A defender.
    fixed = [
        _player(1, 1, 3, 40),
        _player(2, 2, 4, 40), _player(3, 2, 5, 40),
        _player(4, 2, 6, 40), _player(5, 2, 7, 40),
        _player(6, 3, 1, 40), _player(7, 3, 1, 40),
        _player(8, 3, 8, 40), _player(9, 3, 9, 40), _player(10, 3, 10, 40),
        _player(11, 4, 11, 40), _player(12, 4, 12, 40), _player(13, 4, 13, 40),
    ]
    candidates = [
        _player(14, 1, 1, 40),   # greedy choice, but consumes Club A's final slot
        _player(15, 1, 2, 45),   # exact choice
        _player(16, 2, 1, 40),   # only affordable defender
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

    witness = {player["id"]: player for player in bootstrap["elements"]}
    squad = [witness[pid] for pid in result["witness_squad"]]
    assert Counter(player["element_type"] for player in squad) == Counter(SQUAD_QUOTAS)
    assert max(Counter(player["team"] for player in squad).values()) <= CLUB_CAP
    assert sum(player["now_cost"] for player in squad) <= 605


def test_greedy_counterexample_also_defeats_the_generator():
    """The generator must reach the same legal completion, not the greedy trap."""
    fixed = [
        _player(1, 1, 3, 40),
        _player(2, 2, 4, 40), _player(3, 2, 5, 40),
        _player(4, 2, 6, 40), _player(5, 2, 7, 40),
        _player(6, 3, 1, 40), _player(7, 3, 1, 40),
        _player(8, 3, 8, 40), _player(9, 3, 9, 40), _player(10, 3, 10, 40),
        _player(11, 4, 11, 40), _player(12, 4, 12, 40), _player(13, 4, 13, 40),
    ]
    candidates = [
        _player(14, 1, 1, 40),
        _player(15, 1, 2, 45),
        _player(16, 2, 1, 40),
        _player(17, 2, 14, 100),
    ]
    bootstrap = {"elements": fixed + candidates, "teams": []}
    result = build_squad(
        bootstrap,
        budget_tenths=605,
        locked_ids=[player["id"] for player in fixed],
    )
    assert result["status"] == "ok"
    ids = sorted(entry["id"] for entry in result["squad"])
    assert 15 in ids and 16 in ids
    assert result["total_cost_tenths"] <= 605


def test_measurement_harness_shares_the_promoted_implementation():
    from fpl_grounded_assistant import experiment_measurement, squad_solver

    assert experiment_measurement.exact_completion is squad_solver.exact_completion
    assert experiment_measurement.SQUAD_QUOTAS is squad_solver.SQUAD_QUOTAS


# ---------------------------------------------------------------------------
# 6. The objective basis is pinned against known players
# ---------------------------------------------------------------------------

#: Read straight off the frozen bootstrap. Benitez is the reason the default is
#: total_points: one 90-minute appearance and 7 points all season gives him the
#: best points_per_game of any keeper in the game.
KNOWN = {
    "Benitez": {"id": 199, "minutes": 90, "total_points": 7, "points_per_game": "7.0"},
    "Raya": {"id": 1, "minutes": 3330, "total_points": 162, "points_per_game": "4.4"},
}


def test_known_player_stats_still_match_the_frozen_bootstrap(players):
    for name, expected in KNOWN.items():
        player = players[expected["id"]]
        assert player["web_name"] == name
        assert int(player["minutes"]) == expected["minutes"]
        assert int(player["total_points"]) == expected["total_points"]
        assert str(player["points_per_game"]) == expected["points_per_game"]


def test_default_objective_is_total_points_and_prefers_the_durable_keeper(bootstrap):
    result = build_squad(bootstrap)
    assert result["objective"] == "total_points"
    ids = [entry["id"] for entry in result["squad"]]
    assert KNOWN["Raya"]["id"] in ids, "total_points should buy the 3330-minute keeper"
    assert KNOWN["Benitez"]["id"] not in ids, (
        "total_points must not buy the 90-minute keeper"
    )


def test_points_per_game_objective_is_the_one_that_buys_the_small_sample_keeper(bootstrap):
    result = build_squad(bootstrap, objective="points_per_game")
    assert result["objective"] == "points_per_game"
    ids = [entry["id"] for entry in result["squad"]]
    # Documents exactly why points_per_game is offered but not the default.
    assert KNOWN["Benitez"]["id"] in ids


def test_min_minutes_suppresses_the_small_sample_pick(bootstrap, players):
    result = build_squad(bootstrap, objective="points_per_game", min_minutes=1000)
    _assert_legal_squad(result, players, FULL_BUDGET_TENTHS)
    ids = [entry["id"] for entry in result["squad"]]
    assert KNOWN["Benitez"]["id"] not in ids
    assert all(int(players[pid]["minutes"]) >= 1000 for pid in ids)


def test_the_two_objectives_disagree_so_the_choice_is_load_bearing(bootstrap):
    by_points = build_squad(bootstrap, objective="total_points")
    by_ppg = build_squad(bootstrap, objective="points_per_game")
    assert {entry["id"] for entry in by_points["squad"]} != {
        entry["id"] for entry in by_ppg["squad"]
    }


def test_form_is_rejected_as_an_objective(bootstrap):
    """form reads 0.0 for every element pre-season; an all-ties objective would
    return an arbitrary squad wearing the shape of a computed one."""
    assert all(float(player.get("form") or 0) == 0.0 for player in bootstrap["elements"])
    result = build_squad(bootstrap, objective="form")
    assert result["status"] == "invalid_argument"
    assert result["code"] == "unknown_objective"
    assert result["valid_objectives"] == ["points_per_game", "total_points"]


# ---------------------------------------------------------------------------
# Argument handling on the tool surface
# ---------------------------------------------------------------------------

def test_tool_rejects_an_illegal_formation(bootstrap):
    result = build_squad_tool(formation="6-4-1", bootstrap=bootstrap)
    assert result["status"] == "invalid_argument"
    assert result["code"] == "bad_formation"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("4-5-1", (4, 5, 1)),
        ("3-4-3", (3, 4, 3)),
        (" 5 - 4 - 1 ", (5, 4, 1)),
        ("6-3-1", None),   # only 5 defenders may start
        ("4-5-2", None),   # eleven players, not twelve
        ("3-7-0", None),   # no forward
        ("nonsense", None),
    ],
)
def test_formation_parsing(text, expected):
    assert parse_formation(text) == expected


def test_non_standard_position_counts_are_flagged_not_silently_accepted(bootstrap):
    result = build_squad(bootstrap, position_counts={2: 4, 3: 6})
    assert result["status"] == "ok"
    assert any("non_standard_squad_structure" in warning for warning in result["warnings"])
    positions = Counter(entry["position"] for entry in result["squad"])
    assert positions["DEF"] == 4 and positions["MID"] == 6


def test_tool_budget_is_the_total_not_the_remainder(bootstrap):
    """Locked cost comes out of the stated budget, never on top of it."""
    result = build_squad_tool(budget=100.0, locked_players=["Haaland"], bootstrap=bootstrap)
    assert result["status"] == "ok"
    assert result["budget_tenths"] == 1000
    assert result["total_cost_tenths"] <= 1000
    assert result["locked_cost_tenths"] == 155
