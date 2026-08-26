"""
tests/test_fpl_client.py
=========================
Tests for fpl_api_client.fpl_client — bootstrap-only surface.

All tests use unittest.mock; no live network calls are made.
Mocking target: fpl_api_client.fpl_client.requests.get

Test suites:
    A. Import smoke                      (2 tests)
    B. fetch_json — happy path           (3 tests)
    C. fetch_json — retry / error paths  (4 tests)
    D. get_bootstrap                     (3 tests)
    E. get_players                       (6 tests)
    F. get_teams                         (5 tests)
    G. get_current_gameweek              (6 tests)
    H. Public surface guard              (2 tests)
"""
from __future__ import annotations

import copy
import pytest
import requests
from unittest.mock import MagicMock, patch, call

from tests.conftest import MINIMAL_BOOTSTRAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_TARGET = "fpl_api_client.fpl_client.requests.get"


def _make_mock_response(payload: dict, status_code: int = 200) -> MagicMock:
    """Return a mock that quacks like a requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = copy.deepcopy(payload)
    mock.raise_for_status.return_value = None
    return mock


def _make_error_response(status_code: int = 500) -> MagicMock:
    """Return a mock that raises HTTPError on raise_for_status."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.raise_for_status.side_effect = requests.HTTPError(
        f"Mock HTTP {status_code}", response=mock
    )
    return mock


# ---------------------------------------------------------------------------
# A. Import smoke
# ---------------------------------------------------------------------------

class TestImportSmoke:
    def test_package_imports_cleanly(self):
        """fpl_api_client exposes the 4 bootstrap functions."""
        import fpl_api_client
        assert hasattr(fpl_api_client, "get_bootstrap")
        assert hasattr(fpl_api_client, "get_players")
        assert hasattr(fpl_api_client, "get_teams")
        assert hasattr(fpl_api_client, "get_current_gameweek")

    def test_no_football_data_client_in_surface(self):
        """FootballDataClient is NOT in the Phase 1c public surface."""
        import fpl_api_client
        assert not hasattr(fpl_api_client, "FootballDataClient")


# ---------------------------------------------------------------------------
# B. fetch_json — happy path
# ---------------------------------------------------------------------------

class TestFetchJsonHappyPath:
    def test_returns_parsed_json(self):
        """fetch_json returns the parsed dict from response.json()."""
        from fpl_api_client.fpl_client import fetch_json
        with patch(_PATCH_TARGET, return_value=_make_mock_response({"ok": True})):
            result = fetch_json("https://example.com/api/")
        assert result == {"ok": True}

    def test_calls_get_with_correct_url_and_timeout(self):
        """fetch_json passes url and default timeout to requests.get."""
        from fpl_api_client.fpl_client import fetch_json, _DEFAULT_TIMEOUT
        with patch(_PATCH_TARGET, return_value=_make_mock_response({})) as mock_get:
            fetch_json("https://example.com/api/")
        mock_get.assert_called_once_with("https://example.com/api/", timeout=_DEFAULT_TIMEOUT)

    def test_custom_timeout_is_forwarded(self):
        """fetch_json forwards a custom timeout to requests.get."""
        from fpl_api_client.fpl_client import fetch_json
        with patch(_PATCH_TARGET, return_value=_make_mock_response({})) as mock_get:
            fetch_json("https://example.com/api/", timeout=5)
        mock_get.assert_called_once_with("https://example.com/api/", timeout=5)


# ---------------------------------------------------------------------------
# C. fetch_json — retry / error paths
# ---------------------------------------------------------------------------

class TestFetchJsonRetry:
    def test_succeeds_on_second_attempt(self):
        """fetch_json retries on ConnectionError and succeeds on 2nd attempt."""
        from fpl_api_client.fpl_client import fetch_json
        err_resp = MagicMock()
        err_resp.raise_for_status.side_effect = requests.ConnectionError("timeout")
        ok_resp = _make_mock_response({"data": 42})
        with patch(_PATCH_TARGET, side_effect=[err_resp, ok_resp]):
            with patch("fpl_api_client.fpl_client.time.sleep"):  # suppress backoff
                result = fetch_json("https://example.com/api/")
        assert result == {"data": 42}

    def test_raises_after_all_retries_exhausted(self):
        """fetch_json raises after _RETRY_ATTEMPTS consecutive failures."""
        from fpl_api_client.fpl_client import fetch_json, _RETRY_ATTEMPTS
        side_effects = [
            _make_error_response(503) for _ in range(_RETRY_ATTEMPTS)
        ]
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_api_client.fpl_client.time.sleep"):
                with pytest.raises(requests.HTTPError):
                    fetch_json("https://example.com/api/")

    def test_sleeps_between_retries(self):
        """fetch_json calls time.sleep between failed attempts."""
        from fpl_api_client.fpl_client import fetch_json, _RETRY_BACKOFF
        err = _make_error_response(503)
        ok = _make_mock_response({})
        with patch(_PATCH_TARGET, side_effect=[err, ok]):
            with patch("fpl_api_client.fpl_client.time.sleep") as mock_sleep:
                fetch_json("https://example.com/api/")
        mock_sleep.assert_called_once_with(_RETRY_BACKOFF * 1)

    def test_no_sleep_on_first_success(self):
        """fetch_json does not sleep when the first attempt succeeds."""
        from fpl_api_client.fpl_client import fetch_json
        with patch(_PATCH_TARGET, return_value=_make_mock_response({})):
            with patch("fpl_api_client.fpl_client.time.sleep") as mock_sleep:
                fetch_json("https://example.com/api/")
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# D. get_bootstrap
# ---------------------------------------------------------------------------

class TestGetBootstrap:
    def test_calls_bootstrap_url(self):
        """get_bootstrap fetches BOOTSTRAP_URL."""
        from fpl_api_client.fpl_client import get_bootstrap, BOOTSTRAP_URL
        with patch(_PATCH_TARGET, return_value=_make_mock_response(MINIMAL_BOOTSTRAP)) as mock_get:
            get_bootstrap()
        mock_get.assert_called_once()
        assert mock_get.call_args[0][0] == BOOTSTRAP_URL

    def test_returns_full_payload(self):
        """get_bootstrap returns the complete bootstrap dict."""
        from fpl_api_client.fpl_client import get_bootstrap
        with patch(_PATCH_TARGET, return_value=_make_mock_response(MINIMAL_BOOTSTRAP)):
            result = get_bootstrap()
        assert "elements" in result
        assert "teams" in result
        assert "events" in result
        assert "element_types" in result

    def test_return_value_is_dict(self):
        """get_bootstrap return type is dict."""
        from fpl_api_client.fpl_client import get_bootstrap
        with patch(_PATCH_TARGET, return_value=_make_mock_response(MINIMAL_BOOTSTRAP)):
            result = get_bootstrap()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# E. get_players
# ---------------------------------------------------------------------------

class TestGetPlayers:
    def test_returns_list(self, minimal_bootstrap):
        """get_players returns a list."""
        from fpl_api_client.fpl_client import get_players
        result = get_players(minimal_bootstrap)
        assert isinstance(result, list)

    def test_player_count_matches_elements(self, minimal_bootstrap):
        """get_players returns one entry per element in bootstrap."""
        from fpl_api_client.fpl_client import get_players
        result = get_players(minimal_bootstrap)
        assert len(result) == len(minimal_bootstrap["elements"])

    def test_required_keys_present(self, minimal_bootstrap):
        """Each player dict contains all required keys."""
        from fpl_api_client.fpl_client import get_players
        required = {
            "id", "first_name", "second_name", "web_name",
            "team_id", "team_code", "element_type", "status",
            "now_cost", "selected_by_percent", "form",
            "expected_goals", "expected_assists", "expected_goal_involvements",
        }
        for player in get_players(minimal_bootstrap):
            assert required.issubset(player.keys()), f"Missing keys in {player}"

    def test_team_id_mapped_correctly(self, minimal_bootstrap):
        """get_players maps element['team'] to player['team_id']."""
        from fpl_api_client.fpl_client import get_players
        players = get_players(minimal_bootstrap)
        haaland = next(p for p in players if p["id"] == 1)
        assert haaland["team_id"] == 13

    def test_calls_get_bootstrap_when_none(self):
        """get_players calls get_bootstrap() when bootstrap arg is None."""
        from fpl_api_client.fpl_client import get_players
        with patch(_PATCH_TARGET, return_value=_make_mock_response(MINIMAL_BOOTSTRAP)):
            result = get_players(None)
        assert len(result) == 3

    def test_optional_fields_none_for_missing_keys(self):
        """Optional fields are None when absent from the element dict."""
        from fpl_api_client.fpl_client import get_players
        sparse_bootstrap = {
            "elements": [{
                "id": 99, "first_name": "Test", "second_name": "Player",
                "web_name": "TPlayer", "team": 1, "element_type": 3,
                "status": "a",
                # all .get() fields deliberately omitted
            }],
        }
        players = get_players(sparse_bootstrap)
        p = players[0]
        assert p["team_code"] is None
        assert p["now_cost"] is None
        assert p["selected_by_percent"] is None
        assert p["form"] is None
        assert p["expected_goals"] is None
        assert p["expected_assists"] is None
        assert p["expected_goal_involvements"] is None


# ---------------------------------------------------------------------------
# F. get_teams
# ---------------------------------------------------------------------------

class TestGetTeams:
    def test_returns_list(self, minimal_bootstrap):
        """get_teams returns a list."""
        from fpl_api_client.fpl_client import get_teams
        result = get_teams(minimal_bootstrap)
        assert isinstance(result, list)

    def test_team_count_matches(self, minimal_bootstrap):
        """get_teams returns one entry per team in bootstrap."""
        from fpl_api_client.fpl_client import get_teams
        result = get_teams(minimal_bootstrap)
        assert len(result) == 3

    def test_required_keys_present(self, minimal_bootstrap):
        """Each team dict contains all required keys."""
        from fpl_api_client.fpl_client import get_teams
        required = {"id", "name", "short_name", "code", "strength"}
        for team in get_teams(minimal_bootstrap):
            assert required.issubset(team.keys())

    def test_team_name_value(self, minimal_bootstrap):
        """get_teams preserves team names correctly."""
        from fpl_api_client.fpl_client import get_teams
        teams = get_teams(minimal_bootstrap)
        man_city = next(t for t in teams if t["id"] == 13)
        assert man_city["name"] == "Manchester City"
        assert man_city["short_name"] == "MCI"
        assert man_city["strength"] == 5

    def test_calls_get_bootstrap_when_none(self):
        """get_teams calls get_bootstrap() when bootstrap arg is None."""
        from fpl_api_client.fpl_client import get_teams
        with patch(_PATCH_TARGET, return_value=_make_mock_response(MINIMAL_BOOTSTRAP)):
            result = get_teams(None)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# G. get_current_gameweek
# ---------------------------------------------------------------------------

class TestGetCurrentGameweek:
    def test_returns_is_current_event(self, minimal_bootstrap):
        """Returns the event id where is_current is True (GW 28)."""
        from fpl_api_client.fpl_client import get_current_gameweek
        assert get_current_gameweek(minimal_bootstrap) == 28

    def test_falls_back_to_is_next_when_no_current(self):
        """Falls back to is_next event when no is_current event exists."""
        from fpl_api_client.fpl_client import get_current_gameweek
        bs = copy.deepcopy(MINIMAL_BOOTSTRAP)
        for ev in bs["events"]:
            ev["is_current"] = False
        assert get_current_gameweek(bs) == 29

    def test_returns_none_when_no_current_or_next(self):
        """Returns None when neither is_current nor is_next is set."""
        from fpl_api_client.fpl_client import get_current_gameweek
        bs = copy.deepcopy(MINIMAL_BOOTSTRAP)
        for ev in bs["events"]:
            ev["is_current"] = False
            ev["is_next"] = False
        assert get_current_gameweek(bs) is None

    def test_returns_none_for_empty_events(self):
        """Returns None when events list is empty."""
        from fpl_api_client.fpl_client import get_current_gameweek
        assert get_current_gameweek({"events": []}) is None

    def test_returns_none_for_missing_events_key(self):
        """Returns None when bootstrap has no 'events' key."""
        from fpl_api_client.fpl_client import get_current_gameweek
        assert get_current_gameweek({}) is None

    def test_calls_get_bootstrap_when_none(self):
        """get_current_gameweek calls get_bootstrap() when bootstrap arg is None."""
        from fpl_api_client.fpl_client import get_current_gameweek
        with patch(_PATCH_TARGET, return_value=_make_mock_response(MINIMAL_BOOTSTRAP)):
            result = get_current_gameweek(None)
        assert result == 28


# ---------------------------------------------------------------------------
# I. get_all_fixtures
# ---------------------------------------------------------------------------

class TestGetAllFixtures:
    def test_calls_all_fixtures_url_without_event_param(self):
        """get_all_fixtures fetches ALL_FIXTURES_URL with no ?event= query param."""
        from fpl_api_client.fpl_client import get_all_fixtures, ALL_FIXTURES_URL
        payload = [{"id": 1, "team_h": 13, "team_a": 1, "event": 1}]
        with patch(_PATCH_TARGET, return_value=_make_mock_response(payload)) as mock_get:
            get_all_fixtures()
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert called_url == ALL_FIXTURES_URL
        assert "?event=" not in called_url

    def test_returns_parsed_fixture_list(self):
        """get_all_fixtures returns the parsed JSON list of fixtures."""
        from fpl_api_client.fpl_client import get_all_fixtures
        payload = [
            {"id": 1, "team_h": 13, "team_a": 1, "event": 1},
            {"id": 2, "team_h": 6,  "team_a": 7, "event": 1},
        ]
        with patch(_PATCH_TARGET, return_value=_make_mock_response(payload)):
            result = get_all_fixtures()
        assert result == payload
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# J. get_event_live
# ---------------------------------------------------------------------------

_MINIMAL_EVENT_LIVE = {
    "elements": [
        {
            "id": 1,
            "stats": {
                "minutes": 90,
                "goals_scored": 2,
                "assists": 0,
                "clean_sheets": 0,
                "goals_conceded": 1,
                "bonus": 3,
                "total_points": 15,
            },
            "explain": [
                {
                    "fixture": 301,
                    "stats": [
                        {"identifier": "goals_scored", "points": 12, "value": 2},
                        {"identifier": "bonus",        "points": 3,  "value": 3},
                    ],
                }
            ],
            "modified": False,
        }
    ]
}


class TestGetEventLive:
    def test_url_format(self):
        """EVENT_LIVE_URL.format(gameweek=38) produces the expected URL."""
        from fpl_api_client.fpl_client import EVENT_LIVE_URL
        url = EVENT_LIVE_URL.format(gameweek=38)
        assert url == "https://fantasy.premierleague.com/api/event/38/live/"

    def test_url_format_gw1(self):
        """EVENT_LIVE_URL.format works for gameweek=1."""
        from fpl_api_client.fpl_client import EVENT_LIVE_URL
        assert EVENT_LIVE_URL.format(gameweek=1) == "https://fantasy.premierleague.com/api/event/1/live/"

    def test_round_trips_payload(self):
        """get_event_live returns the parsed dict from fetch_json."""
        from fpl_api_client.fpl_client import get_event_live
        with patch(_PATCH_TARGET, return_value=_make_mock_response(_MINIMAL_EVENT_LIVE)):
            result = get_event_live(38)
        assert result == _MINIMAL_EVENT_LIVE
        assert "elements" in result
        assert isinstance(result["elements"], list)

    def test_calls_event_live_url(self):
        """get_event_live fetches the correct EVENT_LIVE_URL for the given GW."""
        from fpl_api_client.fpl_client import get_event_live, EVENT_LIVE_URL
        with patch(_PATCH_TARGET, return_value=_make_mock_response(_MINIMAL_EVENT_LIVE)) as mock_get:
            get_event_live(38)
        called_url = mock_get.call_args[0][0]
        assert called_url == EVENT_LIVE_URL.format(gameweek=38)

    def test_elements_entry_shape(self):
        """Each elements entry in the response has id, stats, explain, modified."""
        from fpl_api_client.fpl_client import get_event_live
        with patch(_PATCH_TARGET, return_value=_make_mock_response(_MINIMAL_EVENT_LIVE)):
            result = get_event_live(38)
        entry = result["elements"][0]
        assert "id" in entry
        assert "stats" in entry
        assert "explain" in entry
        assert "modified" in entry


# ---------------------------------------------------------------------------
# K. get_entry_picks
# ---------------------------------------------------------------------------

_MINIMAL_ENTRY_PICKS = {
    "active_chip": None,
    "entry_history": {
        "event": 3,
        "points": 58,
        "total_points": 210,
        "bank": 5,
        "event_transfers": 1,
        "event_transfers_cost": 0,
    },
    "picks": [
        {"element": 1, "position": 1, "multiplier": 1, "is_captain": False, "is_vice_captain": False},
        {"element": 2, "position": 2, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
    ],
}


class TestGetEntryPicks:
    def test_url_format(self):
        """ENTRY_PICKS_URL.format(...) produces the expected URL."""
        from fpl_api_client.fpl_client import ENTRY_PICKS_URL
        url = ENTRY_PICKS_URL.format(team_id=12345, gameweek=3)
        assert url == "https://fantasy.premierleague.com/api/entry/12345/event/3/picks/"

    def test_round_trips_payload(self):
        """get_entry_picks returns the parsed dict from fetch_json."""
        from fpl_api_client.fpl_client import get_entry_picks
        with patch(_PATCH_TARGET, return_value=_make_mock_response(_MINIMAL_ENTRY_PICKS)):
            result = get_entry_picks(12345, 3)
        assert result == _MINIMAL_ENTRY_PICKS
        assert "picks" in result
        assert "entry_history" in result

    def test_calls_entry_picks_url(self):
        """get_entry_picks fetches the correct ENTRY_PICKS_URL for the given team/GW."""
        from fpl_api_client.fpl_client import get_entry_picks, ENTRY_PICKS_URL
        with patch(_PATCH_TARGET, return_value=_make_mock_response(_MINIMAL_ENTRY_PICKS)) as mock_get:
            get_entry_picks(12345, 3)
        called_url = mock_get.call_args[0][0]
        assert called_url == ENTRY_PICKS_URL.format(team_id=12345, gameweek=3)

    def test_uses_entry_picks_timeout(self):
        """get_entry_picks passes ENTRY_PICKS_TIMEOUT_S, not the 30s default."""
        from fpl_api_client.fpl_client import get_entry_picks, ENTRY_PICKS_TIMEOUT_S
        with patch(_PATCH_TARGET, return_value=_make_mock_response(_MINIMAL_ENTRY_PICKS)) as mock_get:
            get_entry_picks(12345, 3)
        assert mock_get.call_args[1]["timeout"] == ENTRY_PICKS_TIMEOUT_S

    def test_picks_entry_shape(self):
        """Each picks entry has element, position, multiplier, is_captain, is_vice_captain."""
        from fpl_api_client.fpl_client import get_entry_picks
        with patch(_PATCH_TARGET, return_value=_make_mock_response(_MINIMAL_ENTRY_PICKS)):
            result = get_entry_picks(12345, 3)
        entry = result["picks"][0]
        assert "element" in entry
        assert "position" in entry
        assert "multiplier" in entry
        assert "is_captain" in entry
        assert "is_vice_captain" in entry

    def test_404_raises_http_error(self):
        """An unknown team_id (404) raises requests.HTTPError, same as fetch_json's other callers."""
        from fpl_api_client.fpl_client import get_entry_picks
        with patch(_PATCH_TARGET, return_value=_make_error_response(404)):
            with pytest.raises(requests.HTTPError):
                get_entry_picks(999999999, 3)

    def test_connection_error_propagates_after_retries(self):
        """A network failure raises requests.ConnectionError after retries, same as fetch_json."""
        from fpl_api_client.fpl_client import get_entry_picks
        with patch(_PATCH_TARGET, side_effect=requests.ConnectionError("no route")):
            with patch("time.sleep"):  # skip real backoff delay
                with pytest.raises(requests.ConnectionError):
                    get_entry_picks(12345, 3)


# ---------------------------------------------------------------------------
# H. Public surface guard
# ---------------------------------------------------------------------------

class TestPublicSurface:
    def test_all_exports_are_callable(self):
        """Every name in __all__ is callable."""
        import fpl_api_client
        for name in fpl_api_client.__all__:
            assert callable(getattr(fpl_api_client, name)), f"{name} is not callable"

    def test_only_bootstrap_surface_in_all(self):
        """``__all__`` is exactly the intended public surface.

        Deliberately an exact-set assertion, not a subset: the point is to make
        *adding* to the public surface a conscious act, so an accidental export
        cannot slip in unnoticed. Extending the set below is the correct way to
        pass this test; loosening it to ``>=`` would delete the guarantee.

        The set is grouped by the slice that introduced each name so a future
        reader can tell deliberate growth from drift:

        * Phase 1c — bootstrap slice
        * Phase 4a — fixtures slice
        * Preseason reweight (b3e8842) — ``is_form_informative``, the
          season-launch guard for ``form``-based scoring

        This assertion had been red since b3e8842 (2026-08-09): the package
        carried no CI job, so nothing reported it. Wired into
        ``package-test-suites.yml`` as part of #72 phase 1.
        """
        import fpl_api_client
        assert set(fpl_api_client.__all__) == {
            # Phase 1c — bootstrap slice
            "get_bootstrap",
            "get_players",
            "get_teams",
            "get_current_gameweek",
            # Phase 4a — fixtures slice
            "get_fixtures",
            "get_fixture_difficulty_map",
            # Preseason reweight — season-launch form guard
            "is_form_informative",
        }


