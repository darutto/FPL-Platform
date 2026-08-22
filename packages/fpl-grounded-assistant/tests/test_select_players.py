"""Verification for partial selection under a budget.

Deterministic and offline: every assertion runs against the frozen bootstrap
``field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`` (sha256
4cbb9fa1...) or against small synthetic fixtures. No API calls, no LLM.

Verification points, in the order the task states them:

1. The Q7 case -- Haaland locked at 15.5, four midfielders. Every returned
   selection leaves a legal completable 15-man squad, and the witness is itself
   asserted legal: 15 unique players, <=3 per club, <=100.0 total, 2/5/5/3.
2. The Q9 case -- Haaland locked, two forwards. Same assertions.
3. A STRANDING case: inputs where the highest-scoring affordable selection
   leaves no legal completion, and the tool does not return it. This is the
   test that justifies the slice; without it the tool is a filter with extra
   steps, and it must not be weakened.
4. A club-cap interaction: a locked set already holding players from one club,
   where the naive top-N would add a fourth from that club.
5. An impossible request returns an explicit infeasible answer naming what is
   affordable, never a best-effort illegal selection.
6. ``build_squad``'s behaviour is unchanged, from the shared module.

Money is integer ``now_cost`` tenths throughout; millions are display only.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from fpl_grounded_assistant import renderer, tool_schema_registry
from fpl_grounded_assistant.select_players_tool import (
    select_players_within_budget as select_tool,
)
from fpl_grounded_assistant.squad_solver import (
    CLUB_CAP,
    POSITION_CODES,
    SQUAD_QUOTAS,
    build_squad,
    exact_completion,
    select_players,
    validate_squad,
    _candidate_pool,
    _cost,
    _player_index,
)


BOOTSTRAP_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json"
)
FULL_BUDGET_TENTHS = 1000

#: Haaland in the frozen bootstrap. Pinned rather than looked up by name so a
#: resolver change cannot silently move the case this file is about.
HAALAND_ID = 411
HAALAND_COST_TENTHS = 155
MID = POSITION_CODES["MID"]
FWD = POSITION_CODES["FWD"]
DEF = POSITION_CODES["DEF"]


@pytest.fixture(scope="module")
def bootstrap() -> dict:
    if not BOOTSTRAP_PATH.exists():
        pytest.skip(f"frozen bootstrap not present at {BOOTSTRAP_PATH}")
    return json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def players(bootstrap: dict) -> dict:
    return _player_index(bootstrap)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _synthetic(rows: list[tuple[int, int, int, int]]) -> dict:
    """``[(element_type, team, now_cost_tenths, total_points), ...]`` to a bootstrap.

    Ids are assigned in order, so a test can name the players it built.
    """
    elements = [
        {
            "id": index,
            "web_name": f"P{index}",
            "element_type": position,
            "team": club,
            "now_cost": cost,
            "status": "a",
            "minutes": 900,
            "total_points": score,
            "points_per_game": str(score),
        }
        for index, (position, club, cost, score) in enumerate(rows, start=1)
    ]
    teams = [
        {"id": club, "short_name": f"T{club:02d}", "name": f"Team {club}"}
        for club in range(1, 21)
    ]
    return {"elements": elements, "teams": teams}


def _filler_rows(cost: int = 40, score: int = 5) -> list[tuple[int, int, int, int]]:
    """Cheap, legal filler for every position across ten clubs.

    Enough that a legal completion always exists whichever players are picked,
    so a failure in these tests is about the selection and never about the pool.
    """
    return [
        (position, club, cost, score)
        for position in (1, 2, 3, 4)
        for club in range(11, 21)
    ]


def _ids_at(bootstrap: dict, position: int, cost: int) -> list[int]:
    return [
        int(player["id"])
        for player in bootstrap["elements"]
        if int(player["element_type"]) == position and int(player["now_cost"]) == cost
    ]


def _naive_top(
    players: dict,
    position: int,
    count: int,
    *,
    exclude: set[int] = frozenset(),
) -> list[int]:
    """What a filter -- or an LLM -- would answer: the top N by score, ignoring
    whether the rest of the squad can still be bought."""
    pool = [
        player
        for player in players.values()
        if int(player["element_type"]) == position
        and player.get("status") == "a"
        and int(player.get("minutes") or 0) >= 1
        and int(player["id"]) not in exclude
    ]
    pool.sort(key=lambda player: (-int(player.get("total_points") or 0), int(player["id"])))
    return [int(player["id"]) for player in pool[:count]]


# ---------------------------------------------------------------------------
# The shared assertion: a returned selection is completable, provably
# ---------------------------------------------------------------------------

def _assert_completable(
    result: dict,
    players: dict,
    *,
    position: int,
    count: int,
    budget_tenths: int,
    locked_ids: list[int],
) -> list[int]:
    """Verification points 1, 2 and 4, applied to any ok result.

    Re-derives everything from the bootstrap rather than trusting the payload:
    the whole claim of this tool is that its numbers survive an independent
    recomputation.
    """
    assert result["status"] == "ok", result.get("message")
    assert result["completable"] is True

    selection = [entry["id"] for entry in result["selection"]]
    assert len(selection) == count
    assert len(set(selection)) == count
    assert not set(selection) & set(locked_ids)
    assert all(int(players[pid]["element_type"]) == position for pid in selection)

    # -- the witness is a legal squad, checked here and not merely reported --
    witness = [entry["id"] for entry in result["completion"]["witness_squad"]]
    assert len(witness) == 15
    assert len(set(witness)) == 15
    assert set(locked_ids) <= set(witness)
    assert set(selection) <= set(witness)

    assert Counter(int(players[pid]["element_type"]) for pid in witness) == Counter(SQUAD_QUOTAS)
    clubs = Counter(int(players[pid]["team"]) for pid in witness)
    assert max(clubs.values()) <= CLUB_CAP, f"club cap broken in the witness: {clubs}"

    witness_cost = sum(_cost(players[pid]) for pid in witness)
    assert witness_cost <= budget_tenths
    assert validate_squad(
        witness, players, budget_tenths=budget_tenths, quotas=SQUAD_QUOTAS
    ) == []

    # -- the totals reconcile, in tenths, to the penny -----------------------
    selection_cost = sum(_cost(players[pid]) for pid in selection)
    locked_cost = sum(_cost(players[pid]) for pid in locked_ids)
    assert result["selection_cost_tenths"] == selection_cost
    assert result["locked_cost_tenths"] == locked_cost
    assert result["remaining_tenths"] == budget_tenths - locked_cost - selection_cost
    assert sum(entry["price_tenths"] for entry in result["selection"]) == selection_cost

    completion = result["completion"]
    assert completion["exists"] is True
    assert completion["slots_left"] == 15 - len(locked_ids) - count
    assert completion["witness_total_cost_tenths"] == witness_cost
    assert (
        locked_cost + selection_cost + completion["cheapest_fill_cost_tenths"] == witness_cost
    )
    # The claim in one line: what is left over pays for the rest.
    assert completion["cheapest_fill_cost_tenths"] <= result["remaining_tenths"]

    # -- millions are display-only: exactly tenths/10, never rounded apart ---
    assert result["selection_cost"] == round(selection_cost / 10, 1)
    assert result["remaining"] == round(result["remaining_tenths"] / 10, 1)
    assert result["budget"] == round(budget_tenths / 10, 1)
    assert completion["witness_total_cost"] == round(witness_cost / 10, 1)

    # -- an independent second opinion from the oracle itself ----------------
    proof = exact_completion(
        {"elements": list(players.values()), "teams": []},
        locked_ids=locked_ids,
        selected_ids=selection,
        budget_tenths=budget_tenths,
        quotas=SQUAD_QUOTAS,
    )
    assert proof["completion_exists"] is True
    return selection


# ---------------------------------------------------------------------------
# 1 & 2. The Q7 and Q9 cases
# ---------------------------------------------------------------------------

def test_the_frozen_bootstrap_still_holds_the_q7_premise(players):
    """Q7 is 'four midfielders and a price the budget allows', with Haaland a lock."""
    haaland = players[HAALAND_ID]
    assert haaland["web_name"] == "Haaland"
    assert int(haaland["now_cost"]) == HAALAND_COST_TENTHS
    assert int(haaland["element_type"]) == FWD


@pytest.mark.parametrize(
    "case, position, count",
    [
        ("Q7: cuatro medios", MID, 4),
        ("Q9: dos delanteros", FWD, 2),
    ],
)
def test_haaland_locked_selection_leaves_a_completable_squad(
    bootstrap, players, case, position, count
):
    result = select_players(
        bootstrap,
        position=position,
        count=count,
        locked_ids=[HAALAND_ID],
        budget_tenths=FULL_BUDGET_TENTHS,
    )
    _assert_completable(
        result,
        players,
        position=position,
        count=count,
        budget_tenths=FULL_BUDGET_TENTHS,
        locked_ids=[HAALAND_ID],
    )
    assert result["locked_cost_tenths"] == HAALAND_COST_TENTHS
    assert result["ranking_basis"] == "prior_season_carryover"
    assert result["objective"] == "total_points"
    assert result["warnings"] == []


@pytest.mark.parametrize("position, count", [(MID, 4), (FWD, 2), (DEF, 3), (1, 1)])
@pytest.mark.parametrize("budget_tenths", [1000, 900, 800])
def test_every_ok_selection_across_positions_and_budgets_is_completable(
    bootstrap, players, position, count, budget_tenths
):
    result = select_players(
        bootstrap,
        position=position,
        count=count,
        locked_ids=[HAALAND_ID],
        budget_tenths=budget_tenths,
    )
    if result["status"] == "infeasible":
        # Allowed, but then it must be an explicit no with nothing attached.
        assert result["selection"] == []
        assert result["completable"] is False
        return
    _assert_completable(
        result,
        players,
        position=position,
        count=count,
        budget_tenths=budget_tenths,
        locked_ids=[HAALAND_ID],
    )


@pytest.mark.parametrize("objective", ["total_points", "points_per_game"])
def test_both_offered_objectives_produce_completable_selections(bootstrap, players, objective):
    result = select_players(
        bootstrap, position=MID, count=4, locked_ids=[HAALAND_ID], objective=objective
    )
    _assert_completable(
        result,
        players,
        position=MID,
        count=4,
        budget_tenths=FULL_BUDGET_TENTHS,
        locked_ids=[HAALAND_ID],
    )
    assert result["objective"] == objective


def test_form_is_rejected_as_an_objective(bootstrap):
    """Pre-season form reads 0.0 for all 590 elements, so a form ranking would
    be a tie-break wearing the shape of a computed answer. Same call as
    build_squad makes."""
    result = select_players(bootstrap, position=MID, count=4, objective="form")
    assert result["status"] == "invalid_argument"
    assert result["code"] == "unknown_objective"
    assert "form" not in result["valid_objectives"]


def test_price_bounds_constrain_the_picks_and_not_the_rest_of_the_squad(bootstrap, players):
    result = select_players(
        bootstrap,
        position=MID,
        count=4,
        locked_ids=[HAALAND_ID],
        max_price_tenths=60,
    )
    selection = _assert_completable(
        result,
        players,
        position=MID,
        count=4,
        budget_tenths=FULL_BUDGET_TENTHS,
        locked_ids=[HAALAND_ID],
    )
    assert all(_cost(players[pid]) <= 60 for pid in selection)
    # The band bounds the selection only: the witness is free to use anyone,
    # and here it must, because Haaland is 15.5.
    witness = [entry["id"] for entry in result["completion"]["witness_squad"]]
    assert any(_cost(players[pid]) > 60 for pid in witness)


# ---------------------------------------------------------------------------
# 3. STRANDING -- the test that justifies the whole slice
# ---------------------------------------------------------------------------
#
# Do not weaken this. Picking the highest scorers inside a price band is easy
# and wrong: it can leave the remaining slots with no legal, affordable
# filling. A filter cannot tell the difference; the point of the tool is that
# it can.

def _stranding_bootstrap() -> tuple[dict, list[int], list[int]]:
    """A pool whose naive top-4 midfielders cannot be completed.

    Budget 100.0. The eleven slots outside the selection cost 4.0 each -- 44.0
    -- so the four picks may cost at most 56.0 TOGETHER.

    ``stars``  4 MID at 15.0 scoring 300. Each one is affordable on its own;
               the four together cost 60.0 and strand the budget by 4.0.
    ``goods``  6 MID at 13.0 scoring 290.

    Best completable: 2 stars + 2 goods = 56.0 exactly, scoring 1180. The naive
    answer scores 1200 and is not a squad.
    """
    rows = [(3, club, 150, 300) for club in (1, 2, 3, 4)]
    rows += [(3, club, 130, 290) for club in (5, 6, 7, 8, 9, 10)]
    rows += _filler_rows()
    bootstrap = _synthetic(rows)
    return bootstrap, _ids_at(bootstrap, 3, 150), _ids_at(bootstrap, 3, 130)


def test_the_stranding_premise_holds_the_naive_answer_is_not_a_squad():
    bootstrap, stars, goods = _stranding_bootstrap()
    players = _player_index(bootstrap)

    assert len(stars) == 4 and len(goods) == 6
    # It really is the naive top 4 by score.
    assert _naive_top(players, 3, 4) == sorted(stars)
    # Each star is individually affordable...
    for star in stars:
        assert exact_completion(
            bootstrap, [], [star], budget_tenths=FULL_BUDGET_TENTHS, quotas=SQUAD_QUOTAS
        )["completion_exists"]
    # ...and the four of them together are not a squad.
    naive = exact_completion(
        bootstrap, [], stars, budget_tenths=FULL_BUDGET_TENTHS, quotas=SQUAD_QUOTAS
    )
    assert naive["completion_exists"] is False
    assert naive["reason"] == "budget_exceeded"


def test_a_stranding_selection_is_unreachable():
    """THE test. The tool must not return the naive top-4, and what it does
    return must be a selection a real squad can absorb."""
    bootstrap, stars, goods = _stranding_bootstrap()
    players = _player_index(bootstrap)

    result = select_players(
        bootstrap, position=3, count=4, budget_tenths=FULL_BUDGET_TENTHS
    )
    selection = _assert_completable(
        result,
        players,
        position=3,
        count=4,
        budget_tenths=FULL_BUDGET_TENTHS,
        locked_ids=[],
    )

    assert set(selection) != set(stars), "the stranding selection was returned"
    assert sum(_cost(players[pid]) for pid in selection) <= 560

    # And it is not merely legal but the best legal answer: 2 stars + 2 goods.
    assert sorted(Counter(_cost(players[pid]) for pid in selection).items()) == [(130, 2), (150, 2)]
    assert result["objective_total"] == 1180
    assert result["objective_optimality"] == "lagrangian_plus_selection_swap_fixpoint"


def test_stranding_on_the_frozen_bootstrap_too(bootstrap, players):
    """The same failure, on real data: Haaland locked at 15.5 with 80.0 to
    spend. The four best midfielders cost 36.0 and leave nothing that completes;
    the tool spends 23.0 and returns a squad that exists."""
    budget = 800
    naive = _naive_top(players, MID, 4, exclude={HAALAND_ID})
    assert sum(_cost(players[pid]) for pid in naive) == 360

    stranded = exact_completion(
        bootstrap, [HAALAND_ID], naive, budget_tenths=budget, quotas=SQUAD_QUOTAS
    )
    assert stranded["completion_exists"] is False
    assert stranded["reason"] == "budget_exceeded"

    result = select_players(
        bootstrap, position=MID, count=4, locked_ids=[HAALAND_ID], budget_tenths=budget
    )
    selection = _assert_completable(
        result,
        players,
        position=MID,
        count=4,
        budget_tenths=budget,
        locked_ids=[HAALAND_ID],
    )
    assert set(selection) != set(naive)


def test_the_completability_gated_swap_pass_is_load_bearing(bootstrap, players):
    """The multiplier sweep is exact for each lambda but the constrained maximum
    can sit in a concavity no lambda reaches, so a single-substitution pass
    follows, gated on ``exact_completion``. It is not decoration: disabling it
    (``oracle_budget=0``) costs real points on the frozen bootstrap. If this
    ever stops mattering, measure again before deleting the pass."""
    improved = []
    for position, count in ((DEF, 5), (MID, 5), (MID, 2)):
        with_pass = select_players(
            bootstrap, position=position, count=count, budget_tenths=800, locked_ids=[HAALAND_ID]
        )
        without = select_players(
            bootstrap,
            position=position,
            count=count,
            budget_tenths=800,
            locked_ids=[HAALAND_ID],
            oracle_budget=0,
        )
        _assert_completable(
            with_pass,
            players,
            position=position,
            count=count,
            budget_tenths=800,
            locked_ids=[HAALAND_ID],
        )
        assert with_pass["objective_total"] >= without["objective_total"]
        if with_pass["objective_total"] > without["objective_total"]:
            improved.append((position, count))
    assert improved, "the swap pass changed nothing anywhere -- re-measure before keeping it"


def test_running_out_of_oracle_calls_is_reported_not_hidden(bootstrap, players):
    """A truncated search still returns a completable selection, and says so."""
    result = select_players(
        bootstrap, position=MID, count=5, budget_tenths=800, locked_ids=[HAALAND_ID],
        oracle_budget=1,
    )
    _assert_completable(
        result, players, position=MID, count=5, budget_tenths=800, locked_ids=[HAALAND_ID]
    )
    assert result["objective_optimality"] in {
        "lagrangian_plus_selection_swap_fixpoint",
        "lagrangian_plus_selection_swap_truncated",
    }


# ---------------------------------------------------------------------------
# 4. Club-cap interaction
# ---------------------------------------------------------------------------

def _club_cap_bootstrap() -> tuple[dict, list[int], list[int], list[int]]:
    """Two locked defenders from club 1, and the two best midfielders also from
    club 1. The naive top-4 would put four of club 1 in the squad."""
    rows = [(2, 1, 50, 100), (2, 1, 50, 100)]          # ids 1, 2 -- locked
    rows += [(3, 1, 60, 300), (3, 1, 60, 299)]         # ids 3, 4 -- club-1 mids
    rows += [(3, club, 60, 298 - n) for n, club in enumerate((2, 3, 4, 5, 6))]
    rows += _filler_rows()
    bootstrap = _synthetic(rows)
    return bootstrap, [1, 2], [3, 4], [5, 6, 7, 8, 9]


def test_the_club_cap_premise_holds_the_naive_answer_breaks_the_cap():
    bootstrap, locked, hoggers, others = _club_cap_bootstrap()
    players = _player_index(bootstrap)

    naive = _naive_top(players, 3, 4)
    assert set(hoggers) <= set(naive), "the premise requires both club-1 mids in the top 4"
    # Locked 2 + these 2 is four from club 1, and there is no completion at all.
    broken = exact_completion(
        bootstrap, locked, naive, budget_tenths=FULL_BUDGET_TENTHS, quotas=SQUAD_QUOTAS
    )
    assert broken["completion_exists"] is False
    assert broken["reason"] == "fixed_club_cap_exceeded"


def test_the_fourth_player_from_a_locked_club_is_excluded():
    bootstrap, locked, hoggers, others = _club_cap_bootstrap()
    players = _player_index(bootstrap)

    result = select_players(
        bootstrap, position=3, count=4, locked_ids=locked, budget_tenths=FULL_BUDGET_TENTHS
    )
    selection = _assert_completable(
        result,
        players,
        position=3,
        count=4,
        budget_tenths=FULL_BUDGET_TENTHS,
        locked_ids=locked,
    )

    from_club_one = [pid for pid in selection if int(players[pid]["team"]) == 1]
    assert len(from_club_one) == 1, "two locked plus two picked is four from one club"
    assert not set(hoggers) <= set(selection)
    # It takes the better of the two, and fills the rest from elsewhere.
    assert from_club_one == [3]
    assert result["completion"]["witness_club_counts"]["T01"] == CLUB_CAP


# ---------------------------------------------------------------------------
# 5. Impossible requests are refused explicitly, never approximated
# ---------------------------------------------------------------------------

def test_a_price_floor_nothing_can_satisfy_names_what_is_affordable(bootstrap, players):
    """Four midfielders at 12.0m or more: only one such player exists."""
    result = select_players(
        bootstrap,
        position=MID,
        count=4,
        locked_ids=[HAALAND_ID],
        min_price_tenths=120,
    )
    assert result["status"] == "infeasible"
    assert result["code"] == "no_completable_selection_in_price_band"
    assert result["completable"] is False
    assert result["selection"] == [], "a near-miss must never be returned"
    assert result["candidate_pool"]["within_price_bounds"] < 4

    affordable = result["affordable"]
    best = affordable["best_by_objective"]
    assert len(best["players"]) == 4
    assert f"{best['selection_cost']}m" in result["message"]
    # What it names as affordable is itself completable -- not a guess.
    assert exact_completion(
        bootstrap,
        [HAALAND_ID],
        [entry["id"] for entry in best["players"]],
        budget_tenths=FULL_BUDGET_TENTHS,
        quotas=SQUAD_QUOTAS,
    )["completion_exists"]
    assert exact_completion(
        bootstrap,
        [HAALAND_ID],
        [entry["id"] for entry in affordable["most_expensive_that_fits"]["players"]],
        budget_tenths=FULL_BUDGET_TENTHS,
        quotas=SQUAD_QUOTAS,
    )["completion_exists"]


def test_a_budget_no_squad_can_meet_is_infeasible_before_anything_is_picked(bootstrap):
    result = select_players(bootstrap, position=MID, count=4, budget_tenths=400)
    assert result["status"] == "infeasible"
    assert result["selection"] == []
    assert result["completable"] is False
    assert result["minimum_possible_cost_tenths"] is not None
    assert "cheapest legal squad" in result["message"]


def test_a_locked_set_that_already_breaks_the_cap_is_infeasible(bootstrap, players):
    club = int(players[HAALAND_ID]["team"])
    same_club = [
        int(player["id"])
        for player in players.values()
        if int(player["team"]) == club and player.get("status") == "a"
    ][:4]
    result = select_players(bootstrap, position=MID, count=2, locked_ids=same_club)
    assert result["status"] == "infeasible"
    assert result["code"] == "fixed_club_cap_exceeded"
    assert result["selection"] == []


def test_asking_for_more_than_the_position_quota_is_refused_with_the_number(bootstrap):
    """Haaland already fills one of the three forward slots."""
    result = select_players(bootstrap, position=FWD, count=3, locked_ids=[HAALAND_ID])
    assert result["status"] == "invalid_argument"
    assert result["code"] == "selection_exceeds_position_quota"
    assert "at most 2" in result["message"]
    assert "build_squad" in result["message"]
    assert result["selection"] == []


def test_a_price_band_with_enough_members_none_of_which_combine():
    """The sharper band failure: four eligible players exist, and no four of
    them leave a legal squad. Reuses the stranding pool, where the band
    ``>= 14.0m`` is exactly the four stranding stars."""
    bootstrap, stars, goods = _stranding_bootstrap()

    result = select_players(
        bootstrap,
        position=3,
        count=4,
        budget_tenths=FULL_BUDGET_TENTHS,
        min_price_tenths=140,
    )
    assert result["candidate_pool"]["within_price_bounds"] == 4, "enough exist -- that is the point"
    assert result["status"] == "infeasible"
    assert result["code"] == "no_completable_selection_in_price_band"
    assert result["selection"] == []
    assert result["completable"] is False
    assert "no 4 available MID priced at least 14.0m leave a legal 15-man squad" in result["message"]

    alternative = [
        entry["id"] for entry in result["affordable"]["best_by_objective"]["players"]
    ]
    assert exact_completion(
        bootstrap, [], alternative, budget_tenths=FULL_BUDGET_TENTHS, quotas=SQUAD_QUOTAS
    )["completion_exists"]


def test_dropping_the_price_band_always_leaves_a_selection(bootstrap):
    """The invariant behind the shape of the infeasible path: once a legal squad
    exists, any count inside the remaining quota is selectable, so only a price
    band can refuse a request. If this ever fails, the guard branch in
    ``_selection_infeasible`` has become reachable and needs a real answer."""
    for position, quota in sorted(SQUAD_QUOTAS.items()):
        for count in range(1, quota + 1):
            result = select_players(
                bootstrap, position=position, count=count, budget_tenths=FULL_BUDGET_TENTHS
            )
            assert result["status"] == "ok", (position, count, result.get("message"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"position": MID, "count": 0},
        {"position": MID, "count": -2},
        {"position": 9, "count": 2},
        {"position": MID, "count": 2, "budget_tenths": 0},
        {"position": MID, "count": 2, "min_price_tenths": 90, "max_price_tenths": 50},
        {"position": MID, "count": 2, "locked_ids": [HAALAND_ID, HAALAND_ID]},
        {"position": MID, "count": 2, "locked_ids": [999999]},
    ],
)
def test_bad_arguments_are_refused_without_a_selection(bootstrap, kwargs):
    result = select_players(bootstrap, **kwargs)
    assert result["status"] == "invalid_argument"
    assert result.get("selection", []) == []


# ---------------------------------------------------------------------------
# 6. build_squad is unchanged, from the shared module
# ---------------------------------------------------------------------------

def test_build_squad_still_returns_the_same_squad(bootstrap, players):
    """Pinned against the answer recorded before partial selection existed
    (commit 22b9c6b), so the shared-module refactor cannot drift it."""
    result = build_squad(bootstrap)
    assert result["status"] == "ok"
    assert sorted(entry["id"] for entry in result["squad"]) == [
        1, 4, 13, 61, 82, 106, 112, 165, 260, 346, 388, 397, 480, 481, 498
    ]
    assert result["total_cost_tenths"] == 1000
    assert result["objective_total"] == 2603
    assert result["objective_optimality"] == "lagrangian_plus_single_swap_fixpoint"
    assert validate_squad(
        [entry["id"] for entry in result["squad"]],
        players,
        budget_tenths=FULL_BUDGET_TENTHS,
        quotas=SQUAD_QUOTAS,
    ) == []


def test_the_two_tools_share_one_candidate_pool_and_one_oracle(bootstrap, players):
    """There is no second search. ``select_players`` reaches the same players
    through the same helper, and proves itself with the same oracle -- this
    repo has consolidated duplicate resolvers twice already."""
    import fpl_grounded_assistant.squad_solver as solver

    assert solver.select_players.__module__ == solver.build_squad.__module__
    assert solver.exact_completion is exact_completion
    assert solver._candidate_pool is _candidate_pool

    pool = _candidate_pool(players, set(), dict(SQUAD_QUOTAS), {}, 1)
    assert pool == sorted(pool, key=lambda player: int(player["id"]))
    assert all(player.get("status") == "a" for player in pool)


# ---------------------------------------------------------------------------
# Tool surface: schema, adapter, renderer
# ---------------------------------------------------------------------------

def test_the_tool_is_registered_and_offered(bootstrap):
    from fpl_tool_runner import TOOL_REGISTRY

    assert "select_players_within_budget" in tool_schema_registry.TOOL_NAMES
    assert "select_players_within_budget" in tool_schema_registry.get_offered_tool_names(False)
    assert "select_players_within_budget" in TOOL_REGISTRY.list_tools()
    spec = TOOL_REGISTRY.get_spec("select_players_within_budget")
    # The description lives once, in the registry -- two copies drift, and a
    # drifted tool description is the failure 7a05a96 fixed.
    assert spec.description is tool_schema_registry.SELECT_PLAYERS_SCHEMA.description
    assert spec.parameters is tool_schema_registry.SELECT_PLAYERS_SCHEMA.parameters
    assert tool_schema_registry.validate_tool_schema_shape(
        tool_schema_registry.SELECT_PLAYERS_SCHEMA
    )


def test_the_description_states_the_boundary_and_the_blind_spots():
    """7a05a96: a description that promises coverage the tool lacks sends models
    to the wrong tool. Both halves are pinned -- what it does, what it does not."""
    description = tool_schema_registry.SELECT_PLAYERS_SCHEMA.description
    assert "build_squad" in description
    assert "WHOLE 15" in description and "SLICE" in description
    assert "fixtures" in description
    assert "ONE position per call" in description
    assert "never a near-miss" in description

    # ...and the tools that would otherwise absorb the question point at it.
    for schema in (
        tool_schema_registry.GET_TRANSFER_SUGGESTION_SCHEMA,
        tool_schema_registry.RANK_PLAYERS_BY_METRIC_SCHEMA,
        tool_schema_registry.BUILD_SQUAD_SCHEMA,
    ):
        assert "select_players_within_budget" in schema.description, schema.name


def test_the_renderer_is_registered_and_prints_the_tools_own_totals(bootstrap, players):
    """build_squad shipped without a renderer entry and prod would have shown
    'No renderer for tool' as final_text. The renderer must also never re-add a
    column: given a payload whose total disagrees with its rows, it prints the
    payload's total."""
    assert "select_players_within_budget" in renderer._RENDERERS
    missing = {schema.name for schema in tool_schema_registry._ALL_SCHEMAS} - set(
        renderer._RENDERERS
    )
    assert not missing

    result = select_players(bootstrap, position=MID, count=4, locked_ids=[HAALAND_ID])
    text = renderer.render("select_players_within_budget", result)
    assert f"{result['selection_cost']}m" in text
    assert f"{result['remaining']}m" in text
    assert result["selection"][0]["web_name"] in text

    doctored = {**result, "selection_cost": 1.0, "remaining": 2.0}
    doctored_text = renderer.render("select_players_within_budget", doctored)
    assert "1.0m de" in doctored_text and "queda 2.0m" in doctored_text


def test_the_renderer_surfaces_an_infeasible_answer_as_the_refusal_it_is(bootstrap):
    result = select_players(
        bootstrap, position=MID, count=4, locked_ids=[HAALAND_ID], min_price_tenths=120
    )
    text = renderer.render("select_players_within_budget", result)
    assert text.startswith("No selection returned:")
    assert "Sí cabe" in text


@pytest.mark.parametrize(
    "position_query, expected",
    [
        ("medios", "MID"),
        ("centrocampistas", "MID"),
        ("delanteros", "FWD"),
        ("forward", "FWD"),
        ("MID", "MID"),
        ("porteros", "GKP"),
        ("defensas", "DEF"),
    ],
)
def test_the_tool_resolves_spanish_and_english_positions(bootstrap, position_query, expected):
    result = select_tool(position=position_query, count=1, bootstrap=bootstrap)
    assert result["status"] == "ok", result.get("message")
    assert result["position"] == expected


def test_the_tool_resolves_a_locked_player_by_name(bootstrap):
    by_name = select_tool(
        position="medios", count=4, locked_players=["Haaland"], bootstrap=bootstrap
    )
    by_id = select_players(bootstrap, position=MID, count=4, locked_ids=[HAALAND_ID])
    assert by_name["status"] == "ok"
    assert [entry["id"] for entry in by_name["selection"]] == [
        entry["id"] for entry in by_id["selection"]
    ]
    assert by_name["locked_players"][0]["id"] == HAALAND_ID


def test_the_tool_refuses_to_guess_an_unresolvable_lock(bootstrap):
    result = select_tool(
        position="medios", count=2, locked_players=["Nonexistent Player"], bootstrap=bootstrap
    )
    assert result["status"] in {"not_found", "ambiguous"}
    assert result.get("selection", []) == []
    # The consequence is restated for this tool, not borrowed from build_squad.
    assert "No players were selected" in result["message"]
    assert "No squad was built" not in result["message"]


def test_the_tool_budget_is_the_total_not_the_remainder(bootstrap):
    """'Haaland is a lock so I have 84.5 left' is the mistake the arg
    description warns about; passing the full 100.0 must charge him from it."""
    result = select_tool(
        position="medios", count=4, budget=100.0, locked_players=["Haaland"], bootstrap=bootstrap
    )
    assert result["budget_tenths"] == 1000
    assert result["locked_cost_tenths"] == HAALAND_COST_TENTHS
    assert result["remaining_tenths"] == 1000 - HAALAND_COST_TENTHS - result["selection_cost_tenths"]


def test_the_tool_converts_millions_to_tenths_without_float_drift(bootstrap):
    result = select_tool(
        position="medios", count=4, budget=83.3, max_price=6.7, min_price=4.1, bootstrap=bootstrap
    )
    assert result["budget_tenths"] == 833
    assert result["price_bounds"] == {"min": 4.1, "max": 6.7}


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"count": 2}, "missing_position"),
        ({"position": "libero", "count": 2}, "bad_position"),
        ({"position": "medios"}, "missing_count"),
        ({"position": "medios", "count": "muchos"}, "bad_count"),
        ({"position": "medios", "count": 2, "budget": "cien"}, "bad_budget"),
        ({"position": "medios", "count": 2, "max_price": "barato"}, "bad_max_price"),
    ],
)
def test_the_tool_rejects_bad_arguments(bootstrap, kwargs, code):
    result = select_tool(bootstrap=bootstrap, **kwargs)
    assert result["status"] == "invalid_argument"
    assert result["code"] == code


def test_the_tool_needs_bootstrap_data():
    assert select_tool(position="medios", count=2)["code"] == "no_bootstrap"


def test_the_handler_runs_through_the_shared_tool_runner(bootstrap, players):
    from fpl_tool_runner import run_tool

    result = run_tool(
        "select_players_within_budget",
        {"position": "cuatro medios".split()[-1], "count": 4, "locked_players": ["Haaland"]},
        bootstrap,
    )
    _assert_completable(
        result,
        players,
        position=MID,
        count=4,
        budget_tenths=FULL_BUDGET_TENTHS,
        locked_ids=[HAALAND_ID],
    )
