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