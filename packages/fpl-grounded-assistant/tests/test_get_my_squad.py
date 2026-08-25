"""
tests/test_get_my_squad.py
============================
i39: Tests for get_my_squad — the connected user's own squad tool.

Suites:
    A. Registration — TOOL_REGISTRY + tool_schema_registry wiring
    B. No team connected — the default, overwhelmingly common case
    C. gw resolution — explicit / default / out-of-range
    D. Live-fetch failure modes — 404 (bad team id), network error
    E. Happy path — picks -> resolved player payload + summary
    F. Handler — args/bootstrap dispatch, exception safety
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import requests

import fpl_grounded_assistant  # noqa: F401  (triggers tool self-registration)
from fpl_grounded_assistant.get_my_squad import get_my_squad, _get_my_squad_handler
from fpl_tool_runner import TOOL_REGISTRY, run_tool


# ---------------------------------------------------------------------------
# Bootstrap builder
# ---------------------------------------------------------------------------

def _bootstrap(team_id: "int | None" = 12345) -> dict[str, Any]:
    bs: dict[str, Any] = {
        "events": [
            {"id": 1, "is_current": False, "is_next": False, "finished": True},
            {"id": 2, "is_current": False, "is_next": False, "finished": True},
            {"id": 3, "is_current": True, "is_next": False, "finished": False},
            {"id": 4, "is_current": False, "is_next": True, "finished": False},
        ],
        "teams": [
            {"id": 1, "short_name": "ARS", "name": "Arsenal"},
            {"id": 2, "short_name": "MCI", "name": "Man City"},
        ],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [
            {
                "id": 1, "web_name": "Raya", "team": 1, "element_type": 1,
                "now_cost": 50, "status": "a", "form": "4.0", "total_points": 20,
                "chance_of_playing_this_round": None,
            },
            {
                "id": 2, "web_name": "Haaland", "team": 2, "element_type": 4,
                "now_cost": 145, "status": "a", "form": "8.0", "total_points": 60,
                "chance_of_playing_this_round": None,
            },
        ],
    }
    if team_id is not None:
        bs["_my_team_id"] = team_id
    return bs


_PICKS_OK = {
    "active_chip": "bboost",
    "entry_history": {"points": 58, "total_points": 210, "bank": 5},
    "picks": [
        {"element": 2, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
        {"element": 1, "position": 2, "multiplier": 1, "is_captain": False, "is_vice_captain": True},
    ],
}


def _http_error(status_code: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status_code
    return requests.HTTPError(f"mock {status_code}", response=resp)


# ---------------------------------------------------------------------------
# A. Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_registered_in_tool_registry(self):
        assert "get_my_squad" in TOOL_REGISTRY.list_tools()

    def test_registered_in_schema_registry(self):
        from fpl_grounded_assistant.tool_schema_registry import TOOL_NAMES
        assert "get_my_squad" in TOOL_NAMES

    def test_offered_to_the_llm(self):
        from fpl_grounded_assistant.tool_schema_registry import get_offered_tool_names
        assert "get_my_squad" in get_offered_tool_names(False)
        assert "get_my_squad" in get_offered_tool_names(True)

    def test_schema_has_no_required_arguments(self):
        # The team id is server-injected context, never an LLM-supplied arg —
        # requiring it here would let the model hallucinate someone else's id.
        from fpl_grounded_assistant.tool_schema_registry import get_tool_schema
        schema = get_tool_schema("get_my_squad")
        assert schema is not None
        assert schema.parameters.get("required", []) == []
        assert "team_id" not in schema.parameters.get("properties", {})


# ---------------------------------------------------------------------------
# B. No team connected
# ---------------------------------------------------------------------------

class TestNoTeamConnected:
    def test_missing_key_returns_no_team_connected(self):
        result = get_my_squad(_bootstrap(team_id=None))
        assert result["status"] == "no_team_connected"
        assert result["code"] == "no_team_connected"

    def test_none_bootstrap_returns_no_team_connected(self):
        result = get_my_squad(None)
        assert result["status"] == "no_team_connected"

    def test_zero_team_id_treated_as_absent(self):
        # bootstrap.get() truthiness guard: a team_id of 0 is not a valid FPL id.
        result = get_my_squad(_bootstrap(team_id=0))
        assert result["status"] == "no_team_connected"

    def test_no_network_call_made(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks") as mock_fetch:
            get_my_squad(_bootstrap(team_id=None))
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# C. gw resolution
# ---------------------------------------------------------------------------

class TestGwResolution:
    def test_defaults_to_current_gw(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK) as mock_fetch:
            result = get_my_squad(_bootstrap(), gw=None)
        assert result["status"] == "ok"
        assert result["gw"] == 3  # is_current in the fixture bootstrap
        mock_fetch.assert_called_once_with(12345, 3)

    def test_explicit_gw_used(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK) as mock_fetch:
            result = get_my_squad(_bootstrap(), gw=1)
        assert result["gw"] == 1
        mock_fetch.assert_called_once_with(12345, 1)

    def test_out_of_range_gw_is_rejected(self):
        result = get_my_squad(_bootstrap(), gw=99)
        assert result["status"] == "error"
        assert result["code"] == "invalid_gw"

    def test_zero_gw_is_rejected(self):
        result = get_my_squad(_bootstrap(), gw=0)
        assert result["status"] == "error"
        assert result["code"] == "invalid_gw"

    def test_future_gw_clamped_to_current(self):
        # entry/{id}/event/{gw}/picks/ 404s for any gw beyond the current one
        # (no published picks exist yet) — a future request is clamped to the
        # current gw rather than sent to the FPL API as-is, so "bench boost
        # en la fecha 2" while GW1 is current still gets real squad data
        # instead of a misleading "team not found".
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK) as mock_fetch:
            result = get_my_squad(_bootstrap(), gw=4)  # events fixture: current=3, max id=4
        assert result["status"] == "ok"
        assert result["gw"] == 3
        assert result["requested_gw"] == 4
        assert result["gw_clamped"] is True
        mock_fetch.assert_called_once_with(12345, 3)

    def test_current_gw_not_marked_as_clamped(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK):
            result = get_my_squad(_bootstrap(), gw=3)
        assert "gw_clamped" not in result
        assert "requested_gw" not in result

    def test_past_gw_not_clamped(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK) as mock_fetch:
            result = get_my_squad(_bootstrap(), gw=1)
        assert result["gw"] == 1
        assert "gw_clamped" not in result
        mock_fetch.assert_called_once_with(12345, 1)

    def test_default_gw_not_marked_as_clamped(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK):
            result = get_my_squad(_bootstrap(), gw=None)
        assert "gw_clamped" not in result


# ---------------------------------------------------------------------------
# D. Live-fetch failure modes
# ---------------------------------------------------------------------------

class TestFetchFailures:
    def test_404_maps_to_not_found(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", side_effect=_http_error(404)):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result["status"] == "not_found"
        assert result["code"] == "team_not_found"
        assert result["team_id"] == 12345

    def test_500_maps_to_network_error(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", side_effect=_http_error(500)):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result["status"] == "error"
        assert result["code"] == "network_error"

    def test_connection_error_maps_to_network_error(self):
        with patch(
            "fpl_grounded_assistant.get_my_squad.get_entry_picks",
            side_effect=requests.ConnectionError("no route"),
        ):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result["status"] == "error"
        assert result["code"] == "network_error"

    def test_timeout_maps_to_network_error(self):
        with patch(
            "fpl_grounded_assistant.get_my_squad.get_entry_picks",
            side_effect=requests.Timeout("slow"),
        ):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result["status"] == "error"
        assert result["code"] == "network_error"

    def test_failure_never_raises(self):
        # No pytest.raises anywhere in this class is the actual assertion —
        # this test exists so a future regression that lets an exception
        # escape shows up as a clear failure here, not a silent gap.
        with patch(
            "fpl_grounded_assistant.get_my_squad.get_entry_picks",
            side_effect=requests.ConnectionError("no route"),
        ):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result is not None


# ---------------------------------------------------------------------------
# E. Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_ok_status_and_shape(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result["status"] == "ok"
        assert result["team_id"] == 12345
        assert result["gw"] == 3
        assert len(result["players"]) == 2

    def test_players_resolved_from_bootstrap(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK):
            result = get_my_squad(_bootstrap(), gw=3)
        by_id = {p["id"]: p for p in result["players"]}
        assert by_id[2]["web_name"] == "Haaland"
        assert by_id[2]["team_short"] == "MCI"
        assert by_id[2]["position"] == "FWD"
        assert by_id[2]["now_cost"] == 145
        assert by_id[2]["status"] == "Available"
        assert by_id[2]["is_captain"] is True
        assert by_id[1]["is_vice_captain"] is True

    def test_players_ordered_by_pick_position(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK):
            result = get_my_squad(_bootstrap(), gw=3)
        assert [p["id"] for p in result["players"]] == [2, 1]

    def test_is_starter_derived_from_pick_position(self):
        picks = {
            **_PICKS_OK,
            "picks": [
                {"element": 2, "position": 1, "multiplier": 1, "is_captain": False, "is_vice_captain": False},
                {"element": 1, "position": 12, "multiplier": 1, "is_captain": False, "is_vice_captain": False},
            ],
        }
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=picks):
            result = get_my_squad(_bootstrap(), gw=3)
        by_id = {p["id"]: p for p in result["players"]}
        assert by_id[2]["is_starter"] is True
        assert by_id[1]["is_starter"] is False

    def test_summary_fields_and_active_chip_translated(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK):
            result = get_my_squad(_bootstrap(), gw=3)
        summary = result["summary"]
        assert summary["gw_points"] == 58
        assert summary["total_points"] == 210
        assert summary["bank"] == 5
        assert summary["active_chip"] == "bench_boost"  # FPL "bboost" -> backend vocabulary

    def test_no_active_chip_is_none(self):
        picks = {**_PICKS_OK, "active_chip": None}
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=picks):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result["summary"]["active_chip"] is None

    def test_pick_referencing_unknown_element_degrades_gracefully(self):
        picks = {
            **_PICKS_OK,
            "picks": [
                {"element": 999, "position": 1, "multiplier": 1, "is_captain": False, "is_vice_captain": False},
            ],
        }
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=picks):
            result = get_my_squad(_bootstrap(), gw=3)
        assert result["status"] == "ok"
        assert result["players"][0]["web_name"] == "#999"


# ---------------------------------------------------------------------------
# F. Handler — args/bootstrap dispatch
# ---------------------------------------------------------------------------

class TestHandler:
    def test_handler_passes_gw_through(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK) as mock_fetch:
            result = _get_my_squad_handler({"gw": 1}, _bootstrap())
        assert result["status"] == "ok"
        mock_fetch.assert_called_once_with(12345, 1)

    def test_handler_no_args_defaults_to_current_gw(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK) as mock_fetch:
            result = _get_my_squad_handler({}, _bootstrap())
        assert result["status"] == "ok"
        mock_fetch.assert_called_once_with(12345, 3)

    def test_handler_catches_unexpected_exception(self):
        with patch(
            "fpl_grounded_assistant.get_my_squad.get_entry_picks",
            side_effect=RuntimeError("boom"),
        ):
            result = _get_my_squad_handler({}, _bootstrap())
        assert result["status"] == "error"
        assert result["code"] == "tool_exception"

    def test_run_tool_end_to_end(self):
        with patch("fpl_grounded_assistant.get_my_squad.get_entry_picks", return_value=_PICKS_OK):
            result = run_tool("get_my_squad", {}, _bootstrap())
        assert result["status"] == "ok"

    def test_run_tool_no_team_connected_end_to_end(self):
        result = run_tool("get_my_squad", {}, _bootstrap(team_id=None))
        assert result["status"] == "no_team_connected"
