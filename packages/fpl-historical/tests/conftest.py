"""
tests/conftest.py
=================
Shared fixtures for fpl-historical tests.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Inline fixture data
# ---------------------------------------------------------------------------

MINIMAL_BOOTSTRAP: dict = {
    "elements": [
        {
            "id": 1,
            "first_name": "Erling",
            "second_name": "Haaland",
            "web_name": "Haaland",
            "team": 13,
            "element_type": 4,
            "status": "a",
            "now_cost": 145,
            "selected_by_percent": "72.5",
            "form": "9.5",
            "expected_goals": "0.85",
            "expected_assists": "0.10",
            "expected_goal_involvements": "0.95",
        },
        {
            "id": 2,
            "first_name": "Mohamed",
            "second_name": "Salah",
            "web_name": "Salah",
            "team": 11,
            "element_type": 3,
            "status": "a",
            "now_cost": 135,
            "selected_by_percent": "65.0",
            "form": "8.0",
            "expected_goals": "0.60",
            "expected_assists": "0.40",
            "expected_goal_involvements": "1.00",
        },
    ],
    "teams": [
        {
            "id": 13,
            "name": "Manchester City",
            "short_name": "MCI",
            "strength": 5,
            "strength_overall_home": 1340,
            "strength_overall_away": 1310,
        },
        {
            "id": 11,
            "name": "Liverpool",
            "short_name": "LIV",
            "strength": 5,
            "strength_overall_home": 1350,
            "strength_overall_away": 1320,
        },
    ],
    "events": [
        {
            "id": 37,
            "deadline_time": "2026-05-05T17:30:00Z",
            "is_current": False,
            "is_next": False,
            "finished": True,
            "data_checked": True,
            "average_entry_score": 52,
        },
        {
            "id": 38,
            "deadline_time": "2026-05-12T17:30:00Z",
            "is_current": True,
            "is_next": False,
            "finished": False,
            "data_checked": False,
            "average_entry_score": 0,
        },
    ],
    "element_types": [
        {"id": 1, "singular_name": "Goalkeeper"},
        {"id": 2, "singular_name": "Defender"},
        {"id": 3, "singular_name": "Midfielder"},
        {"id": 4, "singular_name": "Forward"},
    ],
}

MINIMAL_FIXTURES: list[dict] = [
    {
        "id": 380,
        "event": 38,
        "team_h": 13,
        "team_a": 11,
        "team_h_score": None,
        "team_a_score": None,
        "team_h_difficulty": 4,
        "team_a_difficulty": 5,
        "finished": False,
        "kickoff_time": "2026-05-17T14:00:00Z",
    },
    {
        "id": 379,
        "event": 38,
        "team_h": 1,
        "team_a": 2,
        "team_h_score": None,
        "team_a_score": None,
        "team_h_difficulty": 3,
        "team_a_difficulty": 2,
        "finished": False,
        "kickoff_time": "2026-05-17T14:00:00Z",
    },
]

MINIMAL_EVENT_LIVE: dict = {
    "elements": [
        {
            "id": 1,
            "stats": {
                "minutes": 90,
                "goals_scored": 1,
                "total_points": 8,
            },
            "explain": [],
            "modified": False,
        }
    ]
}

MINIMAL_ELEMENT_SUMMARY: dict = {
    "history": [
        {
            "element": 1,
            "fixture": 379,
            "opponent_team": 11,
            "total_points": 12,
            "was_home": True,
            "kickoff_time": "2026-05-10T14:00:00Z",
            "team_h_score": 3,
            "team_a_score": 1,
            "round": 37,
            "minutes": 90,
            "goals_scored": 2,
            "assists": 0,
            "clean_sheets": 0,
            "goals_conceded": 1,
            "bonus": 3,
            "bps": 40,
            "expected_goals": "1.85",
            "expected_assists": "0.10",
            "expected_goal_involvements": "1.95",
            "value": 145,
        }
    ],
    "fixtures": [],
}


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_historical_root(tmp_path, monkeypatch):
    """Monkeypatch FPL_HISTORICAL_ROOT to a temp directory.

    Also disables HTTP retry in capture._fetch_raw so existing tests that
    assert exact call counts / failure semantics remain accurate. A
    dedicated retry-behavior test in test_capture.py exercises retries
    explicitly.

    Returns the Path to the temp directory so tests can inspect it.
    """
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path))
    monkeypatch.setattr("fpl_historical._io._RETRY_ATTEMPTS", 1)
    return tmp_path
