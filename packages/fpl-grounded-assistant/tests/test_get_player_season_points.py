"""
Tests for fpl_grounded_assistant.get_player_season_points.

Uses tmp_path + monkeypatching of FPL_HISTORICAL_ROOT to stand up an
on-disk owned-store skeleton without touching real data directories —
same pattern as test_owned_store_fallback.py.

Unlike test_owned_store_fallback.py, this module is imported normally
(not via importlib standalone loading): get_player_season_points.py
unconditionally imports fpl_tool_runner (to self-register in
TOOL_REGISTRY), so there is no dependency it would let us avoid by
bypassing fpl_grounded_assistant/__init__.py — and bypassing it here
would only reintroduce the partial-circular-import hazard that absolute
`from fpl_grounded_assistant.X import Y` sibling imports (the pattern
this module and several others already use) create when loaded via
importlib.util.spec_from_file_location instead of the normal import
system.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# pytest.ini's `pythonpath` puts `../fpl-captain-engine/python` on sys.path,
# but `fpl_tool_contract.tools` (a transitive dep pulled in via
# fpl_grounded_assistant/__init__.py) does `from fpl_captain_engine import
# ...` — the importable name lives in the sibling
# `fpl-captain-engine/fpl_captain_engine/` shim package, one level up from
# `python/`. Add it explicitly so this test doesn't depend on some other
# test file having already done so first (import order should not matter).
_PKG_DIR = Path(__file__).resolve().parent.parent          # fpl-grounded-assistant/
_CAPTAIN_ENGINE_ROOT = str(_PKG_DIR.parent / "fpl-captain-engine")
if _CAPTAIN_ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _CAPTAIN_ENGINE_ROOT)

from fpl_grounded_assistant.get_player_season_points import (  # noqa: E402
    get_player_season_points,
    _previous_season,
    CURRENT_SEASON,
    merged_parquet_dir,
)

_SEASON = "2024-2025"


@pytest.fixture
def season_store(tmp_path, monkeypatch):
    """Build a minimal owned-store parquet_merged/ tree for one season."""
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path / "historical"))

    merged_dir = merged_parquet_dir(_SEASON)
    merged_dir.mkdir(parents=True, exist_ok=True)

    players = pd.DataFrame([
        {"player_id": 101, "web_name": "Palmer", "first_name": "Cole", "second_name": "Palmer", "team_id": 1, "element_type": 3, "total_points": 244},
        {"player_id": 102, "web_name": "Salah", "first_name": "Mohamed", "second_name": "Salah", "team_id": 2, "element_type": 3, "total_points": 300},
        {"player_id": 103, "web_name": "Palmer2", "first_name": "Ricky", "second_name": "Palmer2", "team_id": 1, "element_type": 4, "total_points": 10},
        {"player_id": 999, "web_name": "Managerish", "first_name": "Some", "second_name": "Manager", "team_id": 1, "element_type": 5, "total_points": 0},
    ])
    teams = pd.DataFrame([
        {"team_id": 1, "short_name": "CHE"},
        {"team_id": 2, "short_name": "LIV"},
    ])
    gw_rows = [
        {"player_id": 101, "event_id": gw, "total_points": 8, "minutes": 90,
         "goals_scored": 1, "assists": 0, "clean_sheets": 0, "bonus": 1}
        for gw in range(1, 6)
    ]
    # One DNP gameweek (0 minutes) — should not count toward gws_played.
    gw_rows.append({"player_id": 101, "event_id": 6, "total_points": 0, "minutes": 0,
                     "goals_scored": 0, "assists": 0, "clean_sheets": 0, "bonus": 0})

    players.to_parquet(merged_dir / "players.parquet")
    teams.to_parquet(merged_dir / "teams.parquet")
    pd.DataFrame(gw_rows).to_parquet(merged_dir / "player_gw_stats.parquet")

    return merged_dir


def test_ok_sums_points_across_season(season_store):
    result = get_player_season_points("Palmer", "2024-25")

    assert result["status"] == "ok"
    assert result["season"] == _SEASON
    assert result["player"] == {"id": 101, "web_name": "Palmer", "team_short": "CHE", "position": "MID"}
    assert result["summary"]["total_points"] == 40
    assert result["summary"]["gws_played"] == 5
    assert result["summary"]["total_minutes"] == 450
    assert result["summary"]["total_goals"] == 5
    assert result["summary"]["total_bonus"] == 5
    assert result["summary"]["points_per_game"] == 8.0


def test_season_format_variants_resolve_to_same_dir(season_store):
    # "24/25" (both halves 2-digit) is intentionally NOT accepted —
    # _normalize_season (reused from historical_gameweek_top_scorer, the
    # single source of truth for season-string parsing) requires a 4-digit
    # first half.
    for season_str in ("2024-2025", "2024-25"):
        r = get_player_season_points("Palmer", season_str)
        assert r["status"] == "ok"
        assert r["season"] == _SEASON


def test_bare_2digit_season_form(season_store):
    # "25-26" (no century, no slash) — this is exactly what the deterministic
    # router extracts from phrasings like "la temporada 25-26". Regression
    # guard for the _normalize_season century-inference fix.
    year_from, year_to = _SEASON.split("-")
    bare = f"{year_from[-2:]}-{year_to[-2:]}"
    r = get_player_season_points("Palmer", bare)
    assert r["status"] == "ok"
    assert r["season"] == _SEASON


def test_previous_season_sentinel(season_store):
    r = get_player_season_points("Palmer", "previous")
    expected_previous = _previous_season(CURRENT_SEASON)
    if expected_previous == _SEASON:
        assert r["status"] == "ok"
    else:
        assert r["status"] == "not_found"


def test_player_with_no_matching_gw_rows_returns_zeroed_summary(season_store):
    r = get_player_season_points("Salah", _SEASON)
    assert r["status"] == "ok"
    assert r["summary"]["total_points"] == 0
    assert r["summary"]["gws_played"] == 0
    assert r["summary"]["points_per_game"] == 0.0


def test_exact_name_unambiguous_despite_similar_names(season_store):
    # "Palmer" is an exact web_name match for player 101 only ("Palmer2" is a
    # different web_name) — unambiguous even though a substring match exists.
    r = get_player_season_points("Palmer", _SEASON)
    assert r["status"] == "ok"
    assert r["player"]["id"] == 101


def test_ambiguous_name_returns_candidates(season_store):
    r = get_player_season_points("Palm", _SEASON)
    assert r["status"] == "ambiguous"
    assert len(r["candidates"]) == 2


def test_not_found(season_store):
    r = get_player_season_points("Nonexistentplayer", _SEASON)
    assert r["status"] == "not_found"


def test_assistant_manager_row_excluded_from_matching(season_store):
    r = get_player_season_points("Managerish", _SEASON)
    assert r["status"] == "not_found"


def test_season_not_found(season_store):
    r = get_player_season_points("Palmer", "2010-2011")
    assert r["status"] == "not_found"
    assert r["code"] == "season_not_found"


def test_unparseable_season(season_store):
    r = get_player_season_points("Palmer", "not-a-season")
    assert r["status"] == "invalid_argument"
    assert r["code"] == "unparseable_season"


def test_empty_query_is_invalid_argument(season_store):
    r = get_player_season_points("", _SEASON)
    assert r["status"] == "invalid_argument"


def test_tool_registered_in_tool_registry(season_store):
    from fpl_tool_runner import TOOL_REGISTRY
    assert "get_player_season_points" in TOOL_REGISTRY._specs


def test_handler_via_run_tool(season_store):
    from fpl_tool_runner import run_tool
    result = run_tool("get_player_season_points", {"query": "Palmer", "season": "2024-25"}, {})
    assert result["status"] == "ok"
    assert result["summary"]["total_points"] == 40


# ---------------------------------------------------------------------------
# Regression: _normalize_season (shared with get_historical_gameweek_top_scorer)
# previously rejected bare 2-digit season forms ("25-26", "25/26") despite its
# own docstring claiming "25/26" was accepted. This is exactly what the
# deterministic router extracts from "la temporada 25-26" style phrasings.
# ---------------------------------------------------------------------------

def test_normalize_season_accepts_bare_2digit_forms():
    from fpl_grounded_assistant.historical_gameweek_top_scorer import _normalize_season

    assert _normalize_season("25-26") == "2025-2026"
    assert _normalize_season("25/26") == "2025-2026"
    assert _normalize_season("2025-26") == "2025-2026"
    assert _normalize_season("2025-2026") == "2025-2026"
    assert _normalize_season("99-00") is None  # non-consecutive years, rejected
    assert _normalize_season("garbage") is None
