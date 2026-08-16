"""
Tests for the player_snapshot structured intent — the single-player detail
card wiring (INTENT_PLAYER_SNAPSHOT, PlayerSnapshotMeta, and the real
ask_v2()/to_ask_response() path).

Covers:
  * _extract_player_snapshot_meta: builds correctly on "ok", degrades to
    None on ambiguous/not_found/error status and on malformed payloads
  * _TOOL_TO_INTENT maps get_player_snapshot -> INTENT_PLAYER_SNAPSHOT
  * _extract_structured_meta populates "player_snapshot" for this intent
  * real /ask wiring: ask_v2("...") for a resolved player carries
    player_snapshot; to_ask_response maps it onto AskResponse.player_snapshot
"""
from __future__ import annotations

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401

from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    _TOOL_TO_INTENT,
    INTENT_PLAYER_SNAPSHOT,
    OUTCOME_OK,
)
from fpl_grounded_assistant.final_response import (  # noqa: E402
    _extract_player_snapshot_meta,
    _extract_structured_meta,
    PlayerSnapshotMeta,
)
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot  # noqa: E402


def _ok_raw_output() -> dict:
    return {
        "status": "ok",
        "player": {
            "id": 351,
            "web_name": "Haaland",
            "team_short": "MCI",
            "position": "FWD",
            "minutes_played_season": 2953,
            "status": "Available",
            "news": "",
            "news_added": None,
            "chance_of_playing_this_round": None,
            "form": "6.8",
            "total_points": 239,
            "points_per_game": "6.8",
            "expected_goals": "25.50",
            "expected_assists": "2.67",
            "expected_goal_involvements": "28.17",
            "ict_index": "302.3",
            "expected_goals_per_90": "0.78",
            "expected_assists_per_90": "0.08",
            "expected_goal_involvements_per_90": "0.86",
            "ict_index_per_90": "9.21",
            "defensive_contribution": 116,
            "defensive_contribution_per_90": "3.54",
            "now_cost": 155,
            "selected_by_percent": "74.2",
            "transfers_in_event": 12345,
            "transfers_out_event": 6789,
            "fixtures": [
                {"gameweek": 28, "opponent_short": "ARS", "is_home": True, "difficulty": 3},
                {"gameweek": 29, "opponent_short": "LIV", "is_home": False, "difficulty": 5},
            ],
            "team_fdr_context": {
                "avg_fdr": 4.0, "difficulty_label": "hard", "gw_from": 28, "gw_to": 29,
            },
        },
    }


# ---------------------------------------------------------------------------
# _extract_player_snapshot_meta
# ---------------------------------------------------------------------------

def test_extract_builds_from_ok_payload():
    meta = _extract_player_snapshot_meta(_ok_raw_output())
    assert isinstance(meta, PlayerSnapshotMeta)
    assert meta.web_name == "Haaland"
    assert meta.team_short == "MCI"
    assert meta.position == "FWD"
    assert meta.total_points == 239
    assert meta.now_cost == 155
    assert meta.expected_goals_per_90 == 0.78
    assert meta.expected_assists_per_90 == 0.08
    assert meta.expected_goal_involvements_per_90 == 0.86
    assert meta.ict_index_per_90 == 9.21
    assert meta.defensive_contribution == 116
    assert meta.defensive_contribution_per_90 == 3.54
    assert len(meta.fixtures) == 2
    assert meta.fixtures[0].gameweek == 28
    assert meta.fixtures[0].opponent_short == "ARS"
    assert meta.fixtures[1].difficulty == 5
    assert meta.team_fdr_context is not None
    assert meta.team_fdr_context.difficulty_label == "hard"


def test_extract_degrades_gracefully_when_fixtures_missing():
    """A player whose team isn't covered by team_fixtures (missing_context
    upstream) must still produce a valid PlayerSnapshotMeta -- empty
    fixtures, not a crash."""
    ro = _ok_raw_output()
    del ro["player"]["fixtures"]
    del ro["player"]["team_fdr_context"]
    meta = _extract_player_snapshot_meta(ro)
    assert meta is not None
    assert meta.fixtures == ()
    assert meta.team_fdr_context is None


def test_extract_none_on_ambiguous_status():
    ro = {"status": "ambiguous", "query": "smith", "candidates": [], "message": "..."}
    assert _extract_player_snapshot_meta(ro) is None


def test_extract_none_on_not_found_status():
    ro = {"status": "not_found", "query": "zzz", "message": "..."}
    assert _extract_player_snapshot_meta(ro) is None


def test_extract_none_on_error_status():
    ro = {"status": "error", "code": "tool_exception", "message": "..."}
    assert _extract_player_snapshot_meta(ro) is None


def test_extract_none_on_missing_player_key():
    ro = {"status": "ok"}
    assert _extract_player_snapshot_meta(ro) is None


def test_extract_none_on_malformed_player_payload():
    ro = {"status": "ok", "player": "not a dict"}
    assert _extract_player_snapshot_meta(ro) is None


# ---------------------------------------------------------------------------
# _TOOL_TO_INTENT + _extract_structured_meta wiring
# ---------------------------------------------------------------------------

def test_tool_to_intent_maps_get_player_snapshot():
    assert _TOOL_TO_INTENT["get_player_snapshot"] == INTENT_PLAYER_SNAPSHOT


def test_extract_structured_meta_populates_player_snapshot():
    result = _extract_structured_meta(INTENT_PLAYER_SNAPSHOT, _ok_raw_output(), OUTCOME_OK)
    assert result["player_snapshot"] is not None
    assert result["player_snapshot"].web_name == "Haaland"


def test_extract_structured_meta_none_for_other_intents():
    result = _extract_structured_meta("player_form", _ok_raw_output(), OUTCOME_OK)
    assert result["player_snapshot"] is None


def test_session_http_serializer_includes_per_90_and_dc_fields():
    from fpl_server import _player_snapshot_meta_dict  # noqa: PLC0415

    meta = _extract_player_snapshot_meta(_ok_raw_output())
    assert meta is not None
    payload = _player_snapshot_meta_dict(meta)
    assert payload["expected_goals_per_90"] == 0.78
    assert payload["expected_assists_per_90"] == 0.08
    assert payload["expected_goal_involvements_per_90"] == 0.86
    assert payload["ict_index_per_90"] == 9.21
    assert payload["defensive_contribution"] == 116
    assert payload["defensive_contribution_per_90"] == 3.54


# ---------------------------------------------------------------------------
# Integration: real get_player_snapshot() against the fixture bootstrap
# ---------------------------------------------------------------------------

def test_integration_real_tool_output_extracts_cleanly(bootstrap):
    raw = get_player_snapshot("Haaland", bootstrap=bootstrap)
    assert raw["status"] == "ok"
    meta = _extract_player_snapshot_meta(raw)
    assert meta is not None
    assert meta.web_name == "Haaland"
    assert meta.team_short != ""
    assert meta.position == "FWD"


def test_integration_snapshot_prefers_official_rates_and_includes_dc(bootstrap):
    """Official bootstrap rates win over locally derived values."""
    import copy as _copy

    bs = _copy.deepcopy(bootstrap)
    haaland = next(el for el in bs["elements"] if el["web_name"] == "Haaland")
    haaland.update({
        "minutes": 900,
        "ict_index": "100.0",
        "expected_goals_per_90": "0.91",
        "expected_assists_per_90": "0.22",
        "expected_goal_involvements_per_90": "1.13",
        "defensive_contribution": 72,
        "defensive_contribution_per_90": "7.25",
    })

    player = get_player_snapshot("Haaland", bootstrap=bs)["player"]
    assert player["expected_goals_per_90"] == 0.91
    assert player["expected_assists_per_90"] == 0.22
    assert player["expected_goal_involvements_per_90"] == 1.13
    assert player["ict_index_per_90"] == 10.0
    assert player["defensive_contribution"] == 72
    assert player["defensive_contribution_per_90"] == 7.25


def test_integration_snapshot_derives_rates_and_handles_zero_minutes(bootstrap):
    """Cached bootstraps without official rates still work without division errors."""
    import copy as _copy

    bs = _copy.deepcopy(bootstrap)
    haaland = next(el for el in bs["elements"] if el["web_name"] == "Haaland")
    haaland.update({
        "minutes": 180,
        "ict_index": "20.0",
        "defensive_contribution": 16,
    })
    player = get_player_snapshot("Haaland", bootstrap=bs)["player"]
    assert player["expected_goals_per_90"] == 0.75
    assert player["expected_assists_per_90"] == 0.1
    assert player["expected_goal_involvements_per_90"] == 0.85
    assert player["ict_index_per_90"] == 10.0
    assert player["defensive_contribution_per_90"] == 8.0

    haaland["minutes"] = 0
    player = get_player_snapshot("Haaland", bootstrap=bs)["player"]
    assert player["expected_goals_per_90"] == 0.0
    assert player["ict_index_per_90"] == 0.0
    assert player["defensive_contribution_per_90"] == 0.0


def test_integration_no_team_fixtures_degrades_to_empty(bootstrap):
    """The shared fixture bootstrap has no team_fixtures key -- the
    real get_player_snapshot() call must degrade to empty fixtures
    rather than erroring, and the "ok" player result must be unaffected."""
    raw = get_player_snapshot("Haaland", bootstrap=bootstrap)
    assert raw["player"]["fixtures"] == []
    assert raw["player"]["team_fdr_context"] is None


def test_integration_real_fixtures_attached_when_team_fixtures_present(bootstrap):
    """With team_fixtures present, get_player_snapshot() attaches the same
    fixture data get_player_fixture_run() would return standalone."""
    import copy as _copy

    bs = _copy.deepcopy(bootstrap)
    haaland = next(el for el in bs["elements"] if el["web_name"] == "Haaland")
    bs["team_fixtures"] = {
        haaland["team"]: [
            {"gameweek": 29, "opponent_team": 14, "is_home": True, "difficulty": 2},
            {"gameweek": 30, "opponent_team": 1, "is_home": False, "difficulty": 4},
        ],
    }
    raw = get_player_snapshot("Haaland", bootstrap=bs)
    assert raw["status"] == "ok"
    assert len(raw["player"]["fixtures"]) == 2
    assert raw["player"]["fixtures"][0]["opponent_short"] == "LIV"
    assert raw["player"]["team_fdr_context"]["gw_from"] == 29

    meta = _extract_player_snapshot_meta(raw)
    assert meta is not None
    assert len(meta.fixtures) == 2
    assert meta.fixtures[0].opponent_short == "LIV"
    assert meta.team_fdr_context is not None
    assert meta.team_fdr_context.gw_from == 29


# ---------------------------------------------------------------------------
# Real /ask wiring — ask_v2 + harness_adapter.to_ask_response
# ---------------------------------------------------------------------------

def _ask_request(question: str):
    from fpl_server import AskRequest  # noqa: PLC0415
    return AskRequest(question=question)


def test_to_ask_response_maps_player_snapshot(bootstrap):
    from fpl_grounded_assistant.harness_adapter import to_ask_response  # noqa: PLC0415

    d = {
        "answer_text": "Haaland ...",
        "outcome": "ok",
        "supported": True,
        "intent": INTENT_PLAYER_SNAPSHOT,
        "review_passed": True,
        "llm_used": True,
        "player_snapshot": _extract_player_snapshot_meta(_ok_raw_output()),
    }
    resp = to_ask_response(d, _ask_request("haaland"))
    assert resp.player_snapshot is not None
    assert resp.player_snapshot["web_name"] == "Haaland"
    assert resp.player_snapshot["total_points"] == 239
    assert len(resp.player_snapshot["fixtures"]) == 2
    assert resp.player_snapshot["fixtures"][0]["opponent_short"] == "ARS"
    assert resp.player_snapshot["team_fdr_context"]["difficulty_label"] == "hard"


def test_to_ask_response_player_snapshot_none_for_other_intents():
    from fpl_grounded_assistant.harness_adapter import to_ask_response  # noqa: PLC0415

    d = {
        "answer_text": "...",
        "outcome": "ok",
        "supported": True,
        "intent": "player_form",
        "review_passed": True,
        "llm_used": True,
    }
    resp = to_ask_response(d, _ask_request("forma de Haaland"))
    assert resp.player_snapshot is None
