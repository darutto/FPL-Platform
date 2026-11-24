"""Readers of player_gw_stats must cope with one row per FIXTURE (double gameweeks).

A double gameweek is two rows with the same (player_id, event_id) and different
``fixture`` (CONTRACT §5.1). Synthetic store only (tmp_path + FPL_HISTORICAL_ROOT).

Rules pinned here:
  * additive counts are summed per (player_id, event_id) before ranking;
  * ``gws_played`` counts gameweeks, not rows (appearances are never summed);
  * single-row gameweeks (and the vaastav shape, no ``fixture`` column) behave as before.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

_PKG_DIR = Path(__file__).resolve().parent.parent
_CAPTAIN_ENGINE_ROOT = str(_PKG_DIR.parent / "fpl-captain-engine")
if _CAPTAIN_ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _CAPTAIN_ENGINE_ROOT)

from fpl_grounded_assistant import historical_gameweek_top_scorer as top_mod  # noqa: E402
from fpl_grounded_assistant.get_player_season_points import get_player_season_points  # noqa: E402

SEASON = "2024-2025"


def _store(root: Path, rows: list[dict]) -> None:
    merged = root / "seasons" / SEASON / "parquet_merged"
    merged.mkdir(parents=True)
    pd.DataFrame([{"event_id": 5, "finished": True}]).to_parquet(merged / "events.parquet")
    pd.DataFrame([
        {"player_id": 1, "web_name": "Doubler", "first_name": "Dee", "second_name": "Doubler", "team_id": 1, "element_type": 3, "total_points": 0},
        {"player_id": 2, "web_name": "Single", "first_name": "Sam", "second_name": "Single", "team_id": 2, "element_type": 4, "total_points": 0},
    ]).to_parquet(merged / "players.parquet")
    pd.DataFrame([{"team_id": 1, "short_name": "AAA"}, {"team_id": 2, "short_name": "BBB"}]).to_parquet(merged / "teams.parquet")
    pd.DataFrame(rows).to_parquet(merged / "player_gw_stats.parquet")


def _row(pid, ev, pts, mins, fixture=None, goals=0, **kw):
    r = {"player_id": pid, "event_id": ev, "total_points": pts, "minutes": mins, "goals_scored": goals,
         "assists": 0, "clean_sheets": 0, "bonus": 0, "saves": 0}
    if fixture is not None:
        r["fixture"] = fixture
    r.update(kw)
    return r


@pytest.fixture
def double_store(tmp_path, monkeypatch):
    root = tmp_path / "historical"
    _store(root, [
        # GW5: Doubler scores 6 + 6 across two fixtures (12 total); Single scores 10 in one.
        _row(1, 5, 6, 90, fixture=501, goals=1),
        _row(1, 5, 6, 90, fixture=502, goals=1),
        _row(2, 5, 10, 90, fixture=503, goals=1),
        # GW6: Doubler plays 0' in one fixture of a double and 90' in the other.
        _row(1, 6, 0, 0, fixture=601),
        _row(1, 6, 2, 90, fixture=602),
    ])
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(root))
    importlib.reload(top_mod)
    return root


def test_top_scorer_ranks_by_gameweek_total_not_best_single_row(double_store):
    out = top_mod.get_historical_gameweek_top_scorer(SEASON, gw=5)
    assert out["status"] == "ok"
    (entry,) = out["entries"]
    assert entry["web_name"] == "Doubler"   # 6 + 6 = 12 beats Single's 10 (best single row is 10)
    assert entry["points"] == 12
    assert "2 goals" in entry["highlight"]   # goals summed across the two fixtures


def test_top_scorer_single_row_gameweeks_unchanged(tmp_path, monkeypatch):
    root = tmp_path / "historical"
    _store(root, [_row(1, 5, 6, 90, goals=1), _row(2, 5, 10, 90, goals=1)])  # vaastav shape: no fixture column
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(root))
    importlib.reload(top_mod)
    (entry,) = top_mod.get_historical_gameweek_top_scorer(SEASON, gw=5)["entries"]
    assert (entry["web_name"], entry["points"]) == ("Single", 10)


def test_season_points_sums_all_fixture_rows(double_store):
    out = get_player_season_points("Doubler", SEASON)
    assert out["status"] == "ok"
    assert out["summary"]["total_points"] == 6 + 6 + 0 + 2
    assert out["summary"]["total_minutes"] == 90 + 90 + 0 + 90


def test_season_points_gws_played_counts_gameweeks_not_rows(double_store):
    s = get_player_season_points("Doubler", SEASON)["summary"]
    # GW5 (two rows with minutes) counts once; GW6 (0' + 90') counts once.
    assert s["gws_played"] == 2
    assert s["points_per_game"] == round(14 / 2, 2)
