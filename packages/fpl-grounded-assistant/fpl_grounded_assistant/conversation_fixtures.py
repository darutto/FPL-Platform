"""
fpl_grounded_assistant.conversation_fixtures
=============================================
Deterministic, executable conversation fixtures covering all outcome types.

Phase 2n: Contract documentation and conversation fixtures.

These fixtures serve three purposes:
1. **Documentation** — each scenario is a concrete, named example of the
   adapter contract described in CONTRACT.md.
2. **Regression guard** — ``run_all()`` executes all fixtures against the
   live system and verifies expected outcomes.
3. **Integration reference** — a future LLM integration layer can use these
   fixtures to verify that the grounded backend is wired correctly before
   any model calls are made.

Usage
-----
::

    from fpl_grounded_assistant.conversation_fixtures import (
        FIXTURE_DEFINITIONS,
        run_all,
        STANDARD_BOOTSTRAP,
        AMBIGUOUS_BOOTSTRAP,
    )

    results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)
    for fixture, response in results:
        print(f"{fixture.scenario_id}: supported={response.supported} "
              f"outcome={response.dispatch_result.outcome}")

Fixture IDs
-----------
ok_captain_score      — supported + ok captain scoring query
ok_rank_candidates    — supported + ok ranking with candidates_list
ok_current_gameweek   — supported + ok gameweek query
ok_player_summary     — supported + ok player summary query
ok_player_resolve     — supported + ok player identity query
not_found_captain     — supported + not_found (unknown player name)
ambiguous_player      — supported + ambiguous (two players share web_name)
missing_candidates    — supported + missing_arguments (no candidates_list)
unsupported_question  — unsupported (outside supported scope)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Fixture schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConversationFixture:
    """A single named conversation scenario with expected outcome values.

    Attributes
    ----------
    scenario_id:
        Unique kebab-case identifier used in test labels.
    description:
        Human-readable explanation of what this scenario tests.
    user_message:
        The raw message passed to ``adapt()``.
    expected_supported:
        Expected value of ``AdapterResponse.supported``.
    expected_outcome:
        Expected value of ``AdapterResponse.dispatch_result.outcome``.
    expected_intent:
        Expected value of ``AdapterResponse.dispatch_result.intent``.
    candidates_list:
        Optional list of candidate dicts; forwarded to ``adapt()`` when set.
    use_ambiguous_bootstrap:
        When ``True``, ``run_all()`` passes ``AMBIGUOUS_BOOTSTRAP`` instead
        of ``STANDARD_BOOTSTRAP``.
    """
    scenario_id:              str
    description:              str
    user_message:             str
    expected_supported:       bool
    expected_outcome:         str
    expected_intent:          str
    candidates_list:          list[dict[str, Any]] | None = None
    use_ambiguous_bootstrap:  bool = False


# ---------------------------------------------------------------------------
# Standard bootstrap (GW28 — same fixture data used throughout test suite)
# ---------------------------------------------------------------------------

STANDARD_BOOTSTRAP: dict[str, Any] = {
    "elements": [
        {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
         "web_name": "Haaland",   "team": 13, "team_code": 43, "element_type": 4,
         "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
         "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
         "expected_goal_involvements": "1.70", "minutes": 1800,
         "penalties_order": 1, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
         "web_name": "Salah",     "team": 14, "team_code": 1,  "element_type": 3,
         "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
         "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
         "expected_goal_involvements": "1.45", "minutes": 2250,
         "penalties_order": 1, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": 1},
        {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
         "web_name": "Saka",      "team": 1,  "team_code": 3,  "element_type": 3,
         "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
         "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
         "expected_goal_involvements": "0.85", "minutes": 900,
         "chance_of_playing_this_round": 75,
         "penalties_order": None, "direct_freekicks_order": 2,
         "corners_and_indirect_freekicks_order": 2},
        {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
         "web_name": "De Bruyne", "team": 13, "team_code": 43, "element_type": 3,
         "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
         "form": "0.0", "expected_goals": "0.20", "expected_assists": "0.40",
         "expected_goal_involvements": "0.60", "minutes": 270,
         "penalties_order": None, "direct_freekicks_order": 1,
         "corners_and_indirect_freekicks_order": None},
        # Phase 8a1: GKP with FPL pre-computed per-90 fields for position score testing
        {"id": 5,  "first_name": "David",   "second_name": "Raya",
         "web_name": "Raya",      "team": 1,  "team_code": 3,  "element_type": 1,
         "status": "a", "now_cost": 55, "selected_by_percent": "22.0",
         "form": "6.0", "expected_goals": "0.00", "expected_assists": "0.00",
         "expected_goal_involvements": "0.00", "minutes": 2250,
         "saves_per_90": 2.8, "clean_sheets_per_90": 0.27,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
    ],
    "teams": [
        {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
        {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
        {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
        {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
        {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
    ],
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "finished": False},
    ],
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
    "fixture_difficulty_map": {1: 5, 13: 4, 14: 4, 8: 5},
    # Phase 7h: per-team fixture schedule for upcoming GWs (GW28–GW32)
    # Each entry: {gameweek, opponent_team (id), is_home, difficulty 1-5}
    # Difficulty is from the playing team's perspective (1=easy, 5=hard).
    "team_fixtures": {
        1: [   # Arsenal
            {"gameweek": 28, "opponent_team": 8,  "is_home": True,  "difficulty": 3},
            {"gameweek": 29, "opponent_team": 11, "is_home": False, "difficulty": 3},
            {"gameweek": 30, "opponent_team": 14, "is_home": True,  "difficulty": 4},
            {"gameweek": 31, "opponent_team": 13, "is_home": False, "difficulty": 5},
            {"gameweek": 32, "opponent_team": 8,  "is_home": False, "difficulty": 3},
        ],
        13: [  # Manchester City
            {"gameweek": 28, "opponent_team": 1,  "is_home": True,  "difficulty": 3},
            {"gameweek": 29, "opponent_team": 14, "is_home": False, "difficulty": 4},
            {"gameweek": 30, "opponent_team": 11, "is_home": True,  "difficulty": 2},
            {"gameweek": 31, "opponent_team": 1,  "is_home": True,  "difficulty": 3},
            {"gameweek": 32, "opponent_team": 8,  "is_home": False, "difficulty": 3},
        ],
        14: [  # Liverpool
            {"gameweek": 28, "opponent_team": 11, "is_home": True,  "difficulty": 2},
            {"gameweek": 29, "opponent_team": 13, "is_home": True,  "difficulty": 3},
            {"gameweek": 30, "opponent_team": 1,  "is_home": False, "difficulty": 4},
            {"gameweek": 31, "opponent_team": 8,  "is_home": False, "difficulty": 3},
            {"gameweek": 32, "opponent_team": 11, "is_home": True,  "difficulty": 2},
        ],
        8: [   # Chelsea
            {"gameweek": 28, "opponent_team": 1,  "is_home": False, "difficulty": 4},
            {"gameweek": 29, "opponent_team": 11, "is_home": True,  "difficulty": 2},
            {"gameweek": 30, "opponent_team": 14, "is_home": True,  "difficulty": 4},
            {"gameweek": 31, "opponent_team": 13, "is_home": True,  "difficulty": 5},
            {"gameweek": 32, "opponent_team": 1,  "is_home": True,  "difficulty": 3},
        ],
        11: [  # Manchester United
            {"gameweek": 28, "opponent_team": 14, "is_home": False, "difficulty": 5},
            {"gameweek": 29, "opponent_team": 1,  "is_home": True,  "difficulty": 4},
            {"gameweek": 30, "opponent_team": 13, "is_home": False, "difficulty": 5},
            {"gameweek": 31, "opponent_team": 8,  "is_home": False, "difficulty": 3},
            {"gameweek": 32, "opponent_team": 14, "is_home": True,  "difficulty": 4},
        ],
    },
}

# Phase 7j: differential bootstrap — STANDARD + two available low-ownership players
# Used by the validation corpus V2 to exercise the differential_picks ok-path.
# Palmer (Chelsea, 3.5% owned) and Mbeumo (Man Utd, 8.2% owned) are both
# available (status='a') and under the 15% ownership threshold.
# Team 11 (Man Utd) is added to fixture_difficulty_map with difficulty=2.
DIFFERENTIAL_BOOTSTRAP: dict[str, Any] = {
    **STANDARD_BOOTSTRAP,
    "elements": STANDARD_BOOTSTRAP["elements"] + [
        {
            "id": 10, "first_name": "Cole", "second_name": "Palmer",
            "web_name": "Palmer", "team": 8, "team_code": 8, "element_type": 3,
            "status": "a", "now_cost": 60, "selected_by_percent": "3.5",
            "form": "7.0", "expected_goals": "0.40", "expected_assists": "0.50",
            "expected_goal_involvements": "0.90", "minutes": 1800,
            "penalties_order": 1, "direct_freekicks_order": None,
            "corners_and_indirect_freekicks_order": None,
        },
        {
            "id": 11, "first_name": "Bryan", "second_name": "Mbeumo",
            "web_name": "Mbeumo", "team": 11, "team_code": 12, "element_type": 4,
            "status": "a", "now_cost": 75, "selected_by_percent": "8.2",
            "form": "5.0", "expected_goals": "0.30", "expected_assists": "0.20",
            "expected_goal_involvements": "0.50", "minutes": 1620,
            "penalties_order": 1, "direct_freekicks_order": None,
            "corners_and_indirect_freekicks_order": None,
        },
    ],
    "fixture_difficulty_map": {
        **STANDARD_BOOTSTRAP["fixture_difficulty_map"],
        11: 2,
    },
}


# Blank-GW differential bootstrap — DIFFERENTIAL_BOOTSTRAP with Chelsea (team 8) having
# no GW28 fixture.  Palmer (CHE, 3.5% owned) is therefore a blank player and must be
# excluded from differential picks.  Mbeumo (MUN, 8.2% owned) still has a GW28 fixture
# and must appear.  Used to test the blank-GW filter in get_differential_picks.
DIFFERENTIAL_BGW_BOOTSTRAP: dict[str, Any] = {
    **DIFFERENTIAL_BOOTSTRAP,
    "team_fixtures": {
        **STANDARD_BOOTSTRAP["team_fixtures"],
        8: [  # Chelsea: no GW28 fixture (blank this GW)
            {"gameweek": 29, "opponent_team": 11, "is_home": True,  "difficulty": 2},
            {"gameweek": 30, "opponent_team": 14, "is_home": True,  "difficulty": 4},
            {"gameweek": 31, "opponent_team": 13, "is_home": True,  "difficulty": 5},
            {"gameweek": 32, "opponent_team": 1,  "is_home": True,  "difficulty": 3},
        ],
    },
}


# GKP overpromotion analysis bootstrap — self-contained fixture with 3 GKPs
# (high saves_per_90), 2 DEFs, 2 MIDs, 1 FWD, all low ownership, all status=a.
# All teams play at home in GW28 (effective_fdr = raw_fdr - 0.5 = 2.5).
# Designed to produce a measurable GKP overpromotion signal: GKPs rank much
# higher by position_score (saves/cs uplift) than by captain_score (no saves).
# Team IDs 20-24 are unique to this fixture and do not conflict with other fixtures.
GKP_OVERPROMOTION_BOOTSTRAP: dict[str, Any] = {
    "elements": [
        # --- GKPs: low ownership, high saves_per_90 ---
        {"id": 30, "first_name": "Bob",  "second_name": "Flekken",
         "web_name": "Flekken",   "team": 22, "team_code": 94, "element_type": 1,
         "status": "a", "now_cost": 46, "selected_by_percent": "4.2",
         "form": "5.0", "expected_goals": "0.00", "expected_assists": "0.00",
         "expected_goal_involvements": "0.00", "minutes": 1800,
         "saves_per_90": 3.5, "clean_sheets_per_90": 0.30,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 31, "first_name": "Lukasz", "second_name": "Fabianski",
         "web_name": "Fabianski", "team": 20, "team_code": 57, "element_type": 1,
         "status": "a", "now_cost": 44, "selected_by_percent": "3.8",
         "form": "4.0", "expected_goals": "0.00", "expected_assists": "0.00",
         "expected_goal_involvements": "0.00", "minutes": 1800,
         "saves_per_90": 3.0, "clean_sheets_per_90": 0.25,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 32, "first_name": "Jordan", "second_name": "Pickford",
         "web_name": "Pickford",  "team": 21, "team_code": 31, "element_type": 1,
         "status": "a", "now_cost": 50, "selected_by_percent": "5.1",
         "form": "3.5", "expected_goals": "0.00", "expected_assists": "0.00",
         "expected_goal_involvements": "0.00", "minutes": 1800,
         "saves_per_90": 2.5, "clean_sheets_per_90": 0.20,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        # --- DEF: moderate saves/cs, low ownership ---
        {"id": 33, "first_name": "Murillo", "second_name": "Murillo",
         "web_name": "Murillo",   "team": 23, "team_code": 17, "element_type": 2,
         "status": "a", "now_cost": 45, "selected_by_percent": "3.5",
         "form": "4.0", "expected_goals": "0.05", "expected_assists": "0.10",
         "expected_goal_involvements": "0.15", "minutes": 1710,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.35,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 34, "first_name": "Igor", "second_name": "Igor",
         "web_name": "Igor",      "team": 24, "team_code": 36, "element_type": 2,
         "status": "a", "now_cost": 47, "selected_by_percent": "6.3",
         "form": "3.5", "expected_goals": "0.05", "expected_assists": "0.15",
         "expected_goal_involvements": "0.20", "minutes": 1530,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.30,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        # --- MID: good form + xgi, low ownership ---
        {"id": 35, "first_name": "Elliot", "second_name": "Anderson",
         "web_name": "E.Anderson", "team": 23, "team_code": 17, "element_type": 3,
         "status": "a", "now_cost": 50, "selected_by_percent": "6.0",
         "form": "5.5", "expected_goals": "0.25", "expected_assists": "0.10",
         "expected_goal_involvements": "0.35", "minutes": 1620,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.0,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 36, "first_name": "Carlos", "second_name": "Baleba",
         "web_name": "Baleba",    "team": 24, "team_code": 36, "element_type": 3,
         "status": "a", "now_cost": 49, "selected_by_percent": "7.5",
         "form": "5.0", "expected_goals": "0.20", "expected_assists": "0.10",
         "expected_goal_involvements": "0.30", "minutes": 1710,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.0,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        # --- FWD: good form + xgi, low ownership ---
        {"id": 37, "first_name": "Chris",  "second_name": "Wood",
         "web_name": "C.Wood",    "team": 23, "team_code": 17, "element_type": 4,
         "status": "a", "now_cost": 60, "selected_by_percent": "4.8",
         "form": "5.0", "expected_goals": "0.25", "expected_assists": "0.05",
         "expected_goal_involvements": "0.30", "minutes": 1530,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.0,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": 1, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
    ],
    "teams": [
        {"id": 20, "name": "West Ham",       "short_name": "WHU", "code": 21,  "strength": 3},
        {"id": 21, "name": "Everton",        "short_name": "EVE", "code": 11,  "strength": 2},
        {"id": 22, "name": "Brentford",      "short_name": "BRE", "code": 94,  "strength": 3},
        {"id": 23, "name": "Nottm Forest",   "short_name": "NFO", "code": 17,  "strength": 3},
        {"id": 24, "name": "Brighton",       "short_name": "BHA", "code": 36,  "strength": 4},
    ],
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "finished": False},
    ],
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
    # All teams have FDR=3 in current GW; all play at home → effective_fdr=2.5
    "fixture_difficulty_map": {20: 3, 21: 3, 22: 3, 23: 3, 24: 3},
    "team_fixtures": {
        20: [  # West Ham — home GW28
            {"gameweek": 28, "opponent_team": 23, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 24, "is_home": False, "difficulty": 4},
        ],
        21: [  # Everton — home GW28
            {"gameweek": 28, "opponent_team": 24, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 22, "is_home": False, "difficulty": 3},
        ],
        22: [  # Brentford — home GW28
            {"gameweek": 28, "opponent_team": 21, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 20, "is_home": True,  "difficulty": 2},
        ],
        23: [  # Nottm Forest — home GW28
            {"gameweek": 28, "opponent_team": 20, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 21, "is_home": True,  "difficulty": 2},
        ],
        24: [  # Brighton — home GW28
            {"gameweek": 28, "opponent_team": 21, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 20, "is_home": True,  "difficulty": 2},
        ],
    },
}


# GKP weight-sensitivity balanced bootstrap — moderate GKPs (saves~3.0) surrounded
# by strong outfield players.  Designed so that:
#   baseline weights  → 1 GKP in position top-5 (promoted, not in captain top-5)
#   lower-saves       → 0 GKPs in position top-5 (GKP drops to rank 6)
#   lower-cs          → 1 GKP in position top-5 (saves still dominant)
#   combined-lower    → 1 GKP in position top-5 (fixture-weight compensation)
# Team IDs 30-34 are unique to this fixture.
GKP_BALANCED_BOOTSTRAP: dict[str, Any] = {
    "elements": [
        # --- GKPs: moderate saves, low ownership ---
        {"id": 40, "first_name": "Thomas",  "second_name": "Kaminski",
         "web_name": "Kaminski",   "team": 30, "team_code": 102, "element_type": 1,
         "status": "a", "now_cost": 44, "selected_by_percent": "5.2",
         "form": "3.5", "expected_goals": "0.00", "expected_assists": "0.00",
         "expected_goal_involvements": "0.00", "minutes": 1620,
         "saves_per_90": 3.0, "clean_sheets_per_90": 0.25,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 41, "first_name": "James",   "second_name": "Trafford",
         "web_name": "Trafford",   "team": 31, "team_code": 90,  "element_type": 1,
         "status": "a", "now_cost": 43, "selected_by_percent": "6.7",
         "form": "3.0", "expected_goals": "0.00", "expected_assists": "0.00",
         "expected_goal_involvements": "0.00", "minutes": 1620,
         "saves_per_90": 2.5, "clean_sheets_per_90": 0.20,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        # --- Strong outfield: high form, low ownership ---
        {"id": 42, "first_name": "Morgan",  "second_name": "Gibbs-White",
         "web_name": "Gibbs-White","team": 32, "team_code": 17,  "element_type": 3,
         "status": "a", "now_cost": 60, "selected_by_percent": "8.0",
         "form": "7.5", "expected_goals": "0.30", "expected_assists": "0.20",
         "expected_goal_involvements": "0.50", "minutes": 1620,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.0,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": 1},
        {"id": 43, "first_name": "Danny",   "second_name": "Welbeck",
         "web_name": "Welbeck",    "team": 33, "team_code": 36,  "element_type": 4,
         "status": "a", "now_cost": 62, "selected_by_percent": "7.0",
         "form": "7.5", "expected_goals": "0.35", "expected_assists": "0.15",
         "expected_goal_involvements": "0.50", "minutes": 1620,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.0,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": 1, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 44, "first_name": "Andreas",  "second_name": "Pereira",
         "web_name": "A.Pereira",  "team": 34, "team_code": 54,  "element_type": 3,
         "status": "a", "now_cost": 55, "selected_by_percent": "9.0",
         "form": "7.0", "expected_goals": "0.20", "expected_assists": "0.20",
         "expected_goal_involvements": "0.40", "minutes": 1620,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.0,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 45, "first_name": "Raul",    "second_name": "Jimenez",
         "web_name": "Jimenez",    "team": 34, "team_code": 54,  "element_type": 4,
         "status": "a", "now_cost": 60, "selected_by_percent": "10.0",
         "form": "6.5", "expected_goals": "0.30", "expected_assists": "0.10",
         "expected_goal_involvements": "0.40", "minutes": 1620,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.0,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": 1, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 46, "first_name": "Pervis",  "second_name": "Estupinan",
         "web_name": "Estupinan",  "team": 33, "team_code": 36,  "element_type": 2,
         "status": "a", "now_cost": 52, "selected_by_percent": "3.5",
         "form": "5.0", "expected_goals": "0.05", "expected_assists": "0.15",
         "expected_goal_involvements": "0.20", "minutes": 1620,
         "saves_per_90": 0.0, "clean_sheets_per_90": 0.40,
         "defensive_contribution_per_90": 0.0,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
    ],
    "teams": [
        {"id": 30, "name": "Luton Town",    "short_name": "LUT", "code": 102, "strength": 1},
        {"id": 31, "name": "Burnley",       "short_name": "BUR", "code": 90,  "strength": 2},
        {"id": 32, "name": "Nottm Forest",  "short_name": "NFO", "code": 17,  "strength": 3},
        {"id": 33, "name": "Brighton",      "short_name": "BHA", "code": 36,  "strength": 4},
        {"id": 34, "name": "Fulham",        "short_name": "FUL", "code": 54,  "strength": 3},
    ],
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "finished": False},
    ],
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
    # All teams play at home in GW28 with raw_fdr=3 -> effective_fdr=2.5
    "fixture_difficulty_map": {30: 3, 31: 3, 32: 3, 33: 3, 34: 3},
    "team_fixtures": {
        30: [  # Luton — home GW28
            {"gameweek": 28, "opponent_team": 32, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 33, "is_home": False, "difficulty": 4},
        ],
        31: [  # Burnley — home GW28
            {"gameweek": 28, "opponent_team": 33, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 34, "is_home": False, "difficulty": 3},
        ],
        32: [  # Nottm Forest — home GW28
            {"gameweek": 28, "opponent_team": 30, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 31, "is_home": True,  "difficulty": 2},
        ],
        33: [  # Brighton — home GW28
            {"gameweek": 28, "opponent_team": 31, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 30, "is_home": True,  "difficulty": 2},
        ],
        34: [  # Fulham — home GW28
            {"gameweek": 28, "opponent_team": 30, "is_home": True, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 31, "is_home": True,  "difficulty": 2},
        ],
    },
}


# Phase 8c: Double-gameweek bootstrap — 6 teams each playing twice in GW28.
# Used to exercise the free_hit DGW favorable path (affected_count >= 6).
# Adds Tottenham (id=17) as a 6th team and assigns every team 2 GW28 fixtures.
# elements and fixture_difficulty_map are unchanged from STANDARD_BOOTSTRAP
# (no TOT players, so scoring is unaffected).
DGW_BOOTSTRAP: dict[str, Any] = {
    **STANDARD_BOOTSTRAP,
    "teams": STANDARD_BOOTSTRAP["teams"] + [
        {"id": 17, "name": "Tottenham Hotspur", "short_name": "TOT",
         "code": 6, "strength": 3},
    ],
    "team_fixtures": {
        1: [   # Arsenal — 2 GW28 fixtures
            {"gameweek": 28, "opponent_team": 8,  "is_home": True,  "difficulty": 3},
            {"gameweek": 28, "opponent_team": 11, "is_home": True,  "difficulty": 2},
            {"gameweek": 29, "opponent_team": 17, "is_home": False, "difficulty": 3},
        ],
        13: [  # Manchester City — 2 GW28 fixtures
            {"gameweek": 28, "opponent_team": 14, "is_home": True,  "difficulty": 3},
            {"gameweek": 28, "opponent_team": 17, "is_home": True,  "difficulty": 2},
            {"gameweek": 29, "opponent_team": 14, "is_home": False, "difficulty": 4},
        ],
        14: [  # Liverpool — 2 GW28 fixtures
            {"gameweek": 28, "opponent_team": 11, "is_home": True,  "difficulty": 2},
            {"gameweek": 28, "opponent_team": 8,  "is_home": False, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 13, "is_home": True,  "difficulty": 3},
        ],
        8: [   # Chelsea — 2 GW28 fixtures
            {"gameweek": 28, "opponent_team": 1,  "is_home": False, "difficulty": 4},
            {"gameweek": 28, "opponent_team": 14, "is_home": True,  "difficulty": 3},
            {"gameweek": 29, "opponent_team": 11, "is_home": True,  "difficulty": 2},
        ],
        11: [  # Manchester United — 2 GW28 fixtures
            {"gameweek": 28, "opponent_team": 14, "is_home": False, "difficulty": 5},
            {"gameweek": 28, "opponent_team": 1,  "is_home": True,  "difficulty": 4},
            {"gameweek": 29, "opponent_team": 1,  "is_home": True,  "difficulty": 4},
        ],
        17: [  # Tottenham — 2 GW28 fixtures
            {"gameweek": 28, "opponent_team": 13, "is_home": False, "difficulty": 4},
            {"gameweek": 28, "opponent_team": 11, "is_home": False, "difficulty": 3},
            {"gameweek": 29, "opponent_team": 8,  "is_home": True,  "difficulty": 3},
        ],
    },
}

# Phase 8c: Blank-gameweek bootstrap — 2 teams (ARS, MCI) have no GW28 fixture.
# The remaining 3 teams (LIV, CHE, MUN) retain their single GW28 fixture.
# Used to exercise the free_hit BGW marginal path.
BGW_BOOTSTRAP: dict[str, Any] = {
    **STANDARD_BOOTSTRAP,
    "team_fixtures": {
        1: [   # Arsenal — no GW28 fixture (blanked)
            {"gameweek": 29, "opponent_team": 11, "is_home": False, "difficulty": 3},
            {"gameweek": 30, "opponent_team": 14, "is_home": True,  "difficulty": 4},
        ],
        13: [  # Manchester City — no GW28 fixture (blanked)
            {"gameweek": 29, "opponent_team": 14, "is_home": False, "difficulty": 4},
            {"gameweek": 30, "opponent_team": 11, "is_home": True,  "difficulty": 2},
        ],
        14: [  # Liverpool — 1 GW28 fixture (normal)
            {"gameweek": 28, "opponent_team": 11, "is_home": True,  "difficulty": 2},
            {"gameweek": 29, "opponent_team": 13, "is_home": True,  "difficulty": 3},
        ],
        8: [   # Chelsea — 1 GW28 fixture (normal)
            {"gameweek": 28, "opponent_team": 14, "is_home": True,  "difficulty": 3},
            {"gameweek": 29, "opponent_team": 11, "is_home": True,  "difficulty": 2},
        ],
        11: [  # Manchester United — 1 GW28 fixture (normal)
            {"gameweek": 28, "opponent_team": 14, "is_home": False, "difficulty": 5},
            {"gameweek": 29, "opponent_team": 1,  "is_home": True,  "difficulty": 4},
        ],
    },
}


# Ambiguous bootstrap: two elements sharing web_name "Doe"
AMBIGUOUS_BOOTSTRAP: dict[str, Any] = {
    **STANDARD_BOOTSTRAP,
    "elements": STANDARD_BOOTSTRAP["elements"] + [
        {"id": 20, "first_name": "John",  "second_name": "Doe",
         "web_name": "Doe",  "team": 1,  "team_code": 3,  "element_type": 3,
         "status": "a", "now_cost": 60, "selected_by_percent": "1.0",
         "form": "3.0", "expected_goals": "0.10", "expected_assists": "0.10",
         "expected_goal_involvements": "0.20", "minutes": 900,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
        {"id": 21, "first_name": "Jane",  "second_name": "Doe",
         "web_name": "Doe",  "team": 8,  "team_code": 8,  "element_type": 2,
         "status": "a", "now_cost": 45, "selected_by_percent": "0.5",
         "form": "2.0", "expected_goals": "0.05", "expected_assists": "0.05",
         "expected_goal_involvements": "0.10", "minutes": 900,
         "penalties_order": None, "direct_freekicks_order": None,
         "corners_and_indirect_freekicks_order": None},
    ],
}


# Phase 8e2: Marginal transfer bootstrap — Haaland form raised from 8.0 to 9.1
# so that "sell Haaland for Salah" produces marginal_transfer_in (delta ~1.3)
# instead of transfer_in (delta ~5.7 in STANDARD_BOOTSTRAP).
# Used to test hit_warning: free_transfers==1 + marginal_transfer_in -> hit_warning=True.
import copy as _copy
MARGINAL_TRANSFER_BOOTSTRAP: dict[str, Any] = _copy.deepcopy(STANDARD_BOOTSTRAP)
for _e in MARGINAL_TRANSFER_BOOTSTRAP["elements"]:
    if _e["web_name"] == "Haaland":
        _e["form"] = "9.1"
        break
del _e  # clean up loop variable

# Phase 2.6d: player_form bootstrap — STANDARD + injected element_summaries
# The handler checks bootstrap["_element_summaries"][str(element_id)] before
# making a live API call.  Salah (id=2) has 3 GW history entries.
PLAYER_FORM_BOOTSTRAP: dict[str, Any] = {
    **STANDARD_BOOTSTRAP,
    "_element_summaries": {
        "2": {   # Salah element_id=2
            "history": [
                {"round": 26, "minutes": 90, "goals_scored": 1, "assists": 0,
                 "bonus": 3, "total_points": 10},
                {"round": 27, "minutes": 79, "goals_scored": 0, "assists": 2,
                 "bonus": 1, "total_points": 8},
                {"round": 28, "minutes": 90, "goals_scored": 2, "assists": 0,
                 "bonus": 3, "total_points": 15},
            ],
        },
    },
}

# Phase 2.6d: price_changes bootstrap — STANDARD with cost_change_event populated
# Salah (+1 = +£0.1m riser), De Bruyne (-1 = -£0.1m faller).
PRICE_CHANGES_BOOTSTRAP: dict[str, Any] = _copy.deepcopy(STANDARD_BOOTSTRAP)
for _e in PRICE_CHANGES_BOOTSTRAP["elements"]:
    if _e["web_name"] == "Salah":
        _e["cost_change_event"] = 1
        _e["cost_change_start"] = 3
    elif _e["web_name"] == "De Bruyne":
        _e["cost_change_event"] = -1
        _e["cost_change_start"] = -2
    else:
        _e["cost_change_event"] = 0
        _e["cost_change_start"] = 0
del _copy, _e  # clean up module namespace


# ---------------------------------------------------------------------------
# Fixture definitions — one per key scenario
# ---------------------------------------------------------------------------

FIXTURE_DEFINITIONS: tuple[ConversationFixture, ...] = (

    ConversationFixture(
        scenario_id="ok_captain_score",
        description=(
            "Supported captain scoring query for a known player. "
            "Expected: supported=True, outcome=ok, intent=captain_score."
        ),
        user_message="should I captain Haaland",
        expected_supported=True,
        expected_outcome="ok",
        expected_intent="captain_score",
    ),

    ConversationFixture(
        scenario_id="ok_rank_candidates",
        description=(
            "Supported ranking query with candidates_list supplied. "
            "Expected: supported=True, outcome=ok, intent=rank_candidates."
        ),
        user_message="top captains this week",
        expected_supported=True,
        expected_outcome="ok",
        expected_intent="rank_candidates",
        candidates_list=[{"query": "Haaland"}, {"query": "Salah"}],
    ),

    ConversationFixture(
        scenario_id="ok_current_gameweek",
        description=(
            "Supported gameweek query. "
            "Expected: supported=True, outcome=ok, intent=current_gameweek."
        ),
        user_message="what gameweek is it",
        expected_supported=True,
        expected_outcome="ok",
        expected_intent="current_gameweek",
    ),

    ConversationFixture(
        scenario_id="ok_player_summary",
        description=(
            "Supported player summary query for a known player. "
            "Expected: supported=True, outcome=ok, intent=player_summary."
        ),
        user_message="summary for Salah",
        expected_supported=True,
        expected_outcome="ok",
        expected_intent="player_summary",
    ),

    ConversationFixture(
        scenario_id="ok_player_resolve",
        description=(
            "Supported player identity query for a known player. "
            "Expected: supported=True, outcome=ok, intent=player_resolve."
        ),
        user_message="who is Haaland",
        expected_supported=True,
        expected_outcome="ok",
        expected_intent="player_resolve",
    ),

    ConversationFixture(
        scenario_id="not_found_captain",
        description=(
            "Supported captain query for an unknown player name. "
            "Intent is recognised but player does not exist in registry. "
            "Expected: supported=True, outcome=not_found, intent=captain_score."
        ),
        user_message="should I captain xyznotaplayer999",
        expected_supported=True,
        expected_outcome="not_found",
        expected_intent="captain_score",
    ),

    ConversationFixture(
        scenario_id="ambiguous_player",
        description=(
            "Supported player resolve query where two players share the same "
            "web_name 'Doe'. Uses ambiguous bootstrap. "
            "Expected: supported=True, outcome=ambiguous, intent=player_resolve."
        ),
        user_message="who is Doe",
        expected_supported=True,
        expected_outcome="ambiguous",
        expected_intent="player_resolve",
        use_ambiguous_bootstrap=True,
    ),

    ConversationFixture(
        scenario_id="missing_candidates",
        description=(
            "Supported ranking query without candidates_list supplied. "
            "Intent is recognised but required input is missing. "
            "Expected: supported=True, outcome=missing_arguments, intent=rank_candidates."
        ),
        user_message="top captains this week",
        expected_supported=True,
        expected_outcome="missing_arguments",
        expected_intent="rank_candidates",
        # candidates_list intentionally omitted
    ),

    ConversationFixture(
        scenario_id="unsupported_question",
        description=(
            "Question outside the supported scope — not routable by the "
            "deterministic keyword router. "
            "Expected: supported=False, outcome=unsupported_intent, intent=unsupported."
        ),
        user_message="Is Haaland fit to play?",
        expected_supported=False,
        expected_outcome="unsupported_intent",
        expected_intent="unsupported",
    ),
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all(
    standard_bootstrap: dict[str, Any],
    ambiguous_bootstrap: dict[str, Any],
) -> list[tuple[ConversationFixture, Any]]:
    """Execute all fixtures and return ``(fixture, AdapterResponse)`` pairs.

    Parameters
    ----------
    standard_bootstrap:
        Bootstrap dict used for non-ambiguous scenarios.
    ambiguous_bootstrap:
        Bootstrap dict used for the ambiguous-player scenario.

    Returns
    -------
    list[tuple[ConversationFixture, AdapterResponse]]
        One pair per fixture, in definition order.
    """
    # Import here to avoid circular imports at module-load time
    from .adapter import adapt

    results: list[tuple[ConversationFixture, Any]] = []
    for fixture in FIXTURE_DEFINITIONS:
        bs = ambiguous_bootstrap if fixture.use_ambiguous_bootstrap else standard_bootstrap
        response = adapt(
            fixture.user_message,
            bs,
            candidates_list=fixture.candidates_list,
        )
        results.append((fixture, response))
    return results