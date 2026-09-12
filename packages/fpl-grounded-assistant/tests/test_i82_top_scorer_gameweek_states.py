"""i82 -- get_historical_gameweek_top_scorer across gameweek states.

Decision fixed in the i82 PR: the tool serves any FINISHED gameweek of any
season in the owned store, including already-finished gameweeks of the
season in progress. An OPEN gameweek must come back as its own code
(``gameweek_not_finished``) rather than dying in ``gw_not_found`` -- before
this, an in-progress GW was filtered out by the ``finished`` check and became
indistinguishable from "that gameweek does not exist".

Order asserted: invalid_gw -> gameweek_not_finished -> gw_not_found -> rows.

The store is synthetic (tmp_path + FPL_HISTORICAL_ROOT) so nothing here
depends on what the developer happens to have under packages/fpl-historical.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from fpl_grounded_assistant import historical_gameweek_top_scorer as mod
from fpl_grounded_assistant.renderer import render

SEASON = "2026-2027"


def _write_store(root: Path, *, finished_gws: list[int], open_gws: list[int]) -> None:
    merged = root / "seasons" / SEASON / "parquet_merged"
    merged.mkdir(parents=True)
    events = [
        {"event_id": gw, "finished": gw in finished_gws, "top_element_info.id": 10 + gw,
         "top_element_info.points": 10 + gw}
        for gw in sorted(finished_gws + open_gws)
    ]
    pd.DataFrame(events).to_parquet(merged / "events.parquet")
    pd.DataFrame([
        {"player_id": 11, "web_name": "Salah", "team_id": 1, "element_type": 3},
        {"player_id": 12, "web_name": "Haaland", "team_id": 2, "element_type": 4},
        {"player_id": 13, "web_name": "Palmer", "team_id": 3, "element_type": 3},
        {"player_id": 14, "web_name": "Isak", "team_id": 1, "element_type": 4},
    ]).to_parquet(merged / "players.parquet")
    pd.DataFrame([
        {"team_id": 1, "short_name": "LIV"},
        {"team_id": 2, "short_name": "MCI"},
        {"team_id": 3, "short_name": "CHE"},
    ]).to_parquet(merged / "teams.parquet")
    rows = []
    for gw in finished_gws + open_gws:
        rows.append({"event_id": gw, "player_id": 10 + gw, "total_points": 10 + gw,
                     "minutes": 90, "goals_scored": 1, "assists": 1, "clean_sheets": 0,
                     "bonus": 3, "saves": 0})
    pd.DataFrame(rows).to_parquet(merged / "player_gw_stats.parquet")


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "historical"
    _write_store(root, finished_gws=[1, 2, 3], open_gws=[4])
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(root))
    # paths.historical_root() reads the env var at call time; nothing cached.
    importlib.reload(mod)
    return root


def test_finished_gw_of_the_current_season_returns_rows(store: Path) -> None:
    out = mod.get_historical_gameweek_top_scorer(SEASON, gw=3)
    assert out["status"] == "ok", out
    assert out["season"] == SEASON
    assert [e["event_id"] for e in out["entries"]] == [3]
    assert out["entries"][0]["web_name"] == "Palmer"
    assert out["entries"][0]["points"] == 13


def test_open_gw_returns_gameweek_not_finished_with_the_fixed_text(store: Path) -> None:
    out = mod.get_historical_gameweek_top_scorer(SEASON, gw=4)
    assert out == {
        "status": "not_found",
        "code": "gameweek_not_finished",
        "gw": 4,
        "season": SEASON,
        "message": f"La jornada 4 de {SEASON} aún no ha terminado.",
    }


def test_missing_gw_still_gw_not_found(store: Path) -> None:
    out = mod.get_historical_gameweek_top_scorer(SEASON, gw=9)
    assert out["status"] == "not_found"
    assert out["code"] == "gw_not_found"


def test_out_of_range_gw_is_invalid_before_anything_else(store: Path) -> None:
    out = mod.get_historical_gameweek_top_scorer(SEASON, gw=39)
    assert out["status"] == "invalid_argument"
    assert out["code"] == "invalid_gw"


def test_season_table_skips_the_open_gw(store: Path) -> None:
    out = mod.get_historical_gameweek_top_scorer(SEASON)
    assert out["status"] == "ok"
    assert [e["event_id"] for e in out["entries"]] == [1, 2, 3]


def test_renderer_translates_gameweek_not_finished_specifically(store: Path) -> None:
    out = mod.get_historical_gameweek_top_scorer(SEASON, gw=4)
    text = render("get_historical_gameweek_top_scorer", out)
    assert "aún no ha terminado" in text
    assert "jornada 4" in text.lower()
    # not the generic not_found copy
    assert "no encontr" not in text.lower()


def test_spec_text_matches_the_decision() -> None:
    desc = mod.GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC.description
    assert "POINTS" in desc
    assert "current season" in desc
    assert "gameweek_not_finished" in desc
    assert "rank_players_by_metric" in desc
    # 'PAST/COMPLETED season' was the old, now-false scope claim.
    assert "PAST/COMPLETED" not in desc
