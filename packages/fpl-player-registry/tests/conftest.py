"""
Shared fixtures for fpl-player-registry tests.

All data is synthetic (no file I/O, no network).
The player list uses real web_names from KNOWN_NICKNAMES where possible
so that alias resolution tests are meaningful.

Deliberate fixture design choices
----------------------------------
- Two players share web_name "Johnson" → tests duplicate handling
- "Haaland" and "Salah" are present → tests alias table hits
- "Clarke" has no nickname → tests alias miss
- "Diaz" and "Díaz" share a second_name collision → tests second_name index
  (last-writer wins, which is documented behaviour)
- Player id 99 is absent from PLAYERS → tests missing-player returns
"""
import copy
import pytest
from fpl_player_registry import build_registry, PlayerRegistry

# ── Raw team dicts (mirrors fpl_api_client.get_teams() output) ──────────────

TEAMS: list[dict] = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
    {"id": 5,  "name": "Everton",         "short_name": "EVE", "code": 11, "strength": 2},
]

# ── Raw player dicts (mirrors fpl_api_client.get_players() output) ───────────

PLAYERS: list[dict] = [
    # Known-nickname players (must match KNOWN_NICKNAMES keys exactly)
    {
        "id": 1, "first_name": "Erling", "second_name": "Haaland",
        "web_name": "Haaland", "team_id": 13, "element_type": 4,
        "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
    },
    {
        "id": 2, "first_name": "Mohamed", "second_name": "Salah",
        "web_name": "Salah", "team_id": 14, "element_type": 3,
        "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
    },
    {
        "id": 3, "first_name": "Bukayo", "second_name": "Saka",
        "web_name": "Saka", "team_id": 1, "element_type": 3,
        "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
    },
    {
        "id": 4, "first_name": "Kevin", "second_name": "De Bruyne",
        "web_name": "De Bruyne", "team_id": 13, "element_type": 3,
        "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
    },
    # Plain player — no known nickname
    {
        "id": 5, "first_name": "Ben", "second_name": "Clarke",
        "web_name": "Clarke", "team_id": 1, "element_type": 2,
        "status": "a", "now_cost": 45, "selected_by_percent": "1.2",
    },
    # Duplicate web_name pair — both named "Johnson"
    {
        "id": 6, "first_name": "Adam", "second_name": "Johnson",
        "web_name": "Johnson", "team_id": 8, "element_type": 3,
        "status": "a", "now_cost": 50, "selected_by_percent": "0.5",
    },
    {
        "id": 7, "first_name": "Glen", "second_name": "Johnson",
        "web_name": "Johnson", "team_id": 11, "element_type": 2,
        "status": "a", "now_cost": 45, "selected_by_percent": "0.3",
    },
    # Minimal fields only (optional fields absent)
    {
        "id": 8, "first_name": "Test", "second_name": "Player",
        "web_name": "TPlayer", "team_id": 5, "element_type": 1,
        "status": "u",
    },
]


@pytest.fixture(scope="session")
def teams() -> list[dict]:
    return copy.deepcopy(TEAMS)


@pytest.fixture(scope="session")
def players() -> list[dict]:
    return copy.deepcopy(PLAYERS)


@pytest.fixture(scope="session")
def registry(players, teams) -> PlayerRegistry:
    """A fully-built PlayerRegistry shared across the test session."""
    return build_registry(players, teams)


