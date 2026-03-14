"""
Shared fixtures for fpl-tool-contract tests.

Bootstrap uses raw FPL API element shape ("team" not "team_id") so that
fpl_api_client.get_players(bootstrap) normalises the key correctly.
All other data is synthetic — no network, no file I/O.

Deliberate fixture choices
--------------------------
- Haaland (id=1, FWD, £14.5m, Available) — known nickname "el Vikingo"
- Salah   (id=2, MID, £13.5m, Available) — known nickname "Mo"
- Saka    (id=3, MID, £10.0m, Doubtful)
- De Bruyne (id=4, MID, £10.5m, Injured) — known alias "KDB"
- Two raw-element "Johnson" entries sharing web_name → ambiguity test
- Player 99 absent → not_found test
- GW28 is_current=True → gameweek test
- GW29 is_next=True → gameweek fallback test
"""
import copy
import pytest

# Raw elements use FPL API key "team" (not "team_id") —
# fpl_api_client.get_players() maps this to "team_id" in its output.
_RAW_ELEMENTS = [
    {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",   "team": 13, "team_code": 43, "element_type": 4,
     "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
     "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
     "expected_goal_involvements": "1.70"},
    {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",     "team": 14, "team_code": 1,  "element_type": 3,
     "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
     "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
     "expected_goal_involvements": "1.45"},
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",      "team": 1,  "team_code": 3,  "element_type": 3,
     "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
     "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
     "expected_goal_involvements": "0.85"},
    {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne", "team": 13, "team_code": 43, "element_type": 3,
     "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
     "form": "0.0", "expected_goals": "0.20", "expected_assists": "0.40",
     "expected_goal_involvements": "0.60"},
    # Duplicate web_name pair
    {"id": 6,  "first_name": "Adam",    "second_name": "Johnson",
     "web_name": "Johnson",   "team": 8,  "team_code": 8,  "element_type": 3,
     "status": "a", "now_cost": 50,  "selected_by_percent": "0.5",
     "form": "2.0", "expected_goals": "0.10", "expected_assists": "0.05",
     "expected_goal_involvements": "0.15"},
    {"id": 7,  "first_name": "Glen",    "second_name": "Johnson",
     "web_name": "Johnson",   "team": 11, "team_code": 12, "element_type": 2,
     "status": "a", "now_cost": 45,  "selected_by_percent": "0.3",
     "form": "1.5", "expected_goals": "0.05", "expected_assists": "0.02",
     "expected_goal_involvements": "0.07"},
    # Minimal element (optional fields absent)
    {"id": 8,  "first_name": "Test",    "second_name": "Player",
     "web_name": "TPlayer",   "team": 1,  "element_type": 1,
     "status": "u"},
]

_TEAMS = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
]

_EVENTS = [
    {"id": 27, "is_current": False, "is_next": False, "finished": True},
    {"id": 28, "is_current": True,  "is_next": False, "finished": False},
    {"id": 29, "is_current": False, "is_next": True,  "finished": False},
]

BOOTSTRAP = {
    "elements":     _RAW_ELEMENTS,
    "teams":        _TEAMS,
    "events":       _EVENTS,
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
}


@pytest.fixture(scope="session")
def bootstrap():
    return copy.deepcopy(BOOTSTRAP)


