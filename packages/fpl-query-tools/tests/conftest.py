"""
Shared fixtures for fpl-query-tools tests.

All data is in-memory (no network, no file I/O).
Players mirror fpl_api_client.get_players() output shape.
Teams mirror fpl_api_client.get_teams() output shape.
Bootstrap mirrors fpl_api_client.get_bootstrap() output shape.

Deliberate fixture design choices
-----------------------------------
- Haaland (id=1) and Salah (id=2): both in KNOWN_NICKNAMES → alias tests
- De Bruyne (id=4): alias "KDB" → alias resolution test
- Clarke (id=5): no nickname, plain second_name lookup
- Two "Johnson" players (id=6, 7): duplicate web_name → ambiguity tests
- GW28 is_current=True in events → gameweek tests
- Player id=99 absent from list → missing-player tests
"""
import copy
import pytest

TEAMS = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
]

PLAYERS = [
    {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",   "team_id": 13, "element_type": 4,
     "status": "a", "now_cost": 145, "selected_by_percent": "52.3"},
    {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",     "team_id": 14, "element_type": 3,
     "status": "a", "now_cost": 135, "selected_by_percent": "64.1"},
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",      "team_id": 1,  "element_type": 3,
     "status": "d", "now_cost": 100, "selected_by_percent": "35.0"},
    {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne", "team_id": 13, "element_type": 3,
     "status": "i", "now_cost": 105, "selected_by_percent": "14.2"},
    {"id": 5,  "first_name": "Ben",     "second_name": "Clarke",
     "web_name": "Clarke",    "team_id": 1,  "element_type": 2,
     "status": "a", "now_cost": 45,  "selected_by_percent": "1.2"},
    # Duplicate web_name pair
    {"id": 6,  "first_name": "Adam",    "second_name": "Johnson",
     "web_name": "Johnson",   "team_id": 8,  "element_type": 3,
     "status": "a", "now_cost": 50},
    {"id": 7,  "first_name": "Glen",    "second_name": "Johnson",
     "web_name": "Johnson",   "team_id": 11, "element_type": 2,
     "status": "a", "now_cost": 45},
    # Minimal fields (no cost or ownership)
    {"id": 8,  "first_name": "Test",    "second_name": "Player",
     "web_name": "TPlayer",   "team_id": 1,  "element_type": 1,
     "status": "u"},
]

BOOTSTRAP = {
    "elements": PLAYERS,   # not used directly by query-tools (callers pass players/teams)
    "teams":    TEAMS,
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "finished": False},
    ],
}


@pytest.fixture(scope="session")
def players():
    return copy.deepcopy(PLAYERS)


@pytest.fixture(scope="session")
def teams():
    return copy.deepcopy(TEAMS)


@pytest.fixture(scope="session")
def bootstrap():
    return copy.deepcopy(BOOTSTRAP)


