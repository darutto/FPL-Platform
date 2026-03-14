"""
Shared fixtures and configuration for fpl-api-client tests.

pytest.ini sets pythonpath=. (the fpl-api-client/ root), so
`fpl_api_client` is importable as a normal Python package.

All fixtures use unittest.mock — no live network calls are made.
"""
import pytest


# ---------------------------------------------------------------------------
# Canonical minimal bootstrap payload (mirrors FPL API response shape)
# ---------------------------------------------------------------------------

MINIMAL_BOOTSTRAP: dict = {
    "elements": [
        {
            "id": 1,
            "first_name": "Erling",
            "second_name": "Haaland",
            "web_name": "Haaland",
            "team": 13,
            "team_code": 43,
            "element_type": 4,
            "status": "a",
            "now_cost": 145,
            "selected_by_percent": "52.3",
            "form": "8.0",
            "expected_goals": "1.50",
            "expected_assists": "0.20",
            "expected_goal_involvements": "1.70",
        },
        {
            "id": 2,
            "first_name": "Mohamed",
            "second_name": "Salah",
            "web_name": "Salah",
            "team": 14,
            "team_code": 1,
            "element_type": 3,
            "status": "a",
            "now_cost": 135,
            "selected_by_percent": "64.1",
            "form": "9.5",
            "expected_goals": "0.90",
            "expected_assists": "0.55",
            "expected_goal_involvements": "1.45",
        },
        {
            "id": 3,
            "first_name": "Bukayo",
            "second_name": "Saka",
            "web_name": "Saka",
            "team": 1,
            "team_code": 3,
            "element_type": 3,
            "status": "d",   # doubt
            "now_cost": 100,
            "selected_by_percent": "35.0",
            "form": "5.5",
            "expected_goals": "0.45",
            "expected_assists": "0.40",
            "expected_goal_involvements": "0.85",
        },
    ],
    "teams": [
        {"id": 1,  "name": "Arsenal",          "short_name": "ARS", "code": 3,  "strength": 4},
        {"id": 13, "name": "Manchester City",   "short_name": "MCI", "code": 43, "strength": 5},
        {"id": 14, "name": "Liverpool",         "short_name": "LIV", "code": 1,  "strength": 5},
    ],
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "is_previous": True,  "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "is_previous": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "is_previous": False, "finished": False},
    ],
    "element_types": [
        {"id": 1, "singular_name": "Goalkeeper", "singular_name_short": "GKP"},
        {"id": 2, "singular_name": "Defender",   "singular_name_short": "DEF"},
        {"id": 3, "singular_name": "Midfielder",  "singular_name_short": "MID"},
        {"id": 4, "singular_name": "Forward",     "singular_name_short": "FWD"},
    ],
}


@pytest.fixture
def minimal_bootstrap() -> dict:
    """Return a copy of the canonical minimal bootstrap payload."""
    import copy
    return copy.deepcopy(MINIMAL_BOOTSTRAP)


