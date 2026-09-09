"""The /fixtures bundle must be able to describe its own degraded mode.

Background: the shipped 2026-27 bundle was exported on launch day, when no
results existed, so `_defence_overlay_bands` had no rolling form to refine FDR
with and both axes banded from the same signal. The file that came out was
structurally perfect -- 20 teams, 3 horizons, valid runs and verdicts -- and
said nothing at all about having collapsed the two axes into one. It shipped
that way for six weeks and the Ataque / Porteria a cero switcher did nothing.

These tests pin the two measurements the whole guard chain rests on:
`gameweeks_played` (which distinguishes a legitimate season-start bundle from
a stale one) and `axis_separation` (which must be read off the OUTPUT, never
off the code path that produced it).
"""
from __future__ import annotations

import importlib.util
import os

import pandas as pd
import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "export_real_season_fixture_outlook.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("export_fixture_outlook", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = _load_module()


def _bucket(bands: dict[str, float]) -> dict:
    return {"teams": [{"team_short": s, "avg_band": b} for s, b in bands.items()]}


def _out(attack: dict[str, float], defence: dict[str, float]) -> dict:
    return {
        "attack": {str(h): _bucket(attack) for h in exporter.HORIZONS},
        "defence": {str(h): _bucket(defence) for h in exporter.HORIZONS},
    }


class TestSeasonPaths:
    def test_season_label_shortens_the_key(self):
        assert exporter.season_label("2025-2026") == "2025-26"
        assert exporter.season_label("2026-2027") == "2026-27"

    def test_output_filename_derives_from_the_season(self):
        assert exporter.out_path_for("2026-2027").endswith("fixture-outlook-2026-27.json")
        assert exporter.out_path_for("2025-2026").endswith("fixture-outlook-2025-26.json")

    def test_the_pin_is_only_a_default_and_still_points_where_it_did(self):
        # SEASON is deliberately decoupled from the season registry rollover.
        # --season must be able to target another season WITHOUT moving it.
        assert exporter.SEASON == "2025-2026"
        assert exporter._OUT_PATH == exporter.out_path_for("2025-2026")
        assert exporter._OUT_PATH_NEW == exporter.out_path_for("2026-2027")


class TestGameweeksPlayed:
    def test_counts_only_finished_fully_scored_gameweeks(self):
        fixtures = pd.DataFrame(
            [
                {"event_id": 1, "team_h_score": 2, "team_a_score": 1, "finished": True},
                {"event_id": 2, "team_h_score": 0, "team_a_score": 0, "finished": True},
                # live, half-played: a checkpoint must not depend on when we looked
                {"event_id": 3, "team_h_score": 1, "team_a_score": 0, "finished": False},
                {"event_id": 4, "team_h_score": None, "team_a_score": None, "finished": False},
            ]
        )
        assert exporter.gameweeks_played(fixtures) == 2

    def test_distinct_gameweeks_not_fixtures(self):
        fixtures = pd.DataFrame(
            [{"event_id": 1, "team_h_score": 1, "team_a_score": 0, "finished": True}] * 10
        )
        assert exporter.gameweeks_played(fixtures) == 1

    def test_a_schedule_with_no_results_reports_zero_not_a_crash(self):
        fixtures = pd.DataFrame(
            [
                {"event_id": 1, "team_h_score": None, "team_a_score": None, "finished": False},
                {"event_id": 2, "team_h_score": None, "team_a_score": None, "finished": False},
            ]
        )
        assert exporter.gameweeks_played(fixtures) == 0

    def test_missing_score_columns_report_zero_rather_than_guessing(self):
        assert exporter.gameweeks_played(pd.DataFrame([{"event_id": 1}])) == 0


class TestAxisSeparation:
    def test_identical_axes_measure_zero(self):
        bands = {"ARS": 2.4, "MCI": 2.0, "BUR": 3.8}
        counts = exporter.axis_separation(_out(bands, bands))
        assert counts == {str(h): 0 for h in exporter.HORIZONS}

    def test_counts_teams_not_fixtures_and_matches_by_short_name(self):
        attack = {"ARS": 2.4, "MCI": 2.0, "BUR": 3.8}
        defence = {"BUR": 3.8, "ARS": 2.6, "MCI": 2.0}  # reordered; only ARS moved
        counts = exporter.axis_separation(_out(attack, defence))
        assert counts == {str(h): 1 for h in exporter.HORIZONS}

    def test_the_flag_is_measured_from_the_output_not_from_the_code_path(self):
        # A run that CLAIMS to be the separating recipe but produced identical
        # axes must still report axes_separated=False. Reading the flag off
        # `source` would make it a restatement of the caller's intention.
        bands = {"ARS": 2.4, "MCI": 2.0}
        meta = exporter.build_generation_meta(
            _out(bands, bands), season="2026-2027", source="recipe", played=3
        )
        assert meta["axes_separated"] is False
        assert meta["source"] == "recipe"
        assert meta["gameweeks_played"] == 3
        assert meta["season_label"] == "2026-27"
        assert meta["teams"] == 2

    def test_a_separating_run_reports_the_per_horizon_counts(self):
        attack = {"ARS": 2.4, "MCI": 2.0}
        defence = {"ARS": 3.0, "MCI": 1.5}
        meta = exporter.build_generation_meta(
            _out(attack, defence), season="2026-2027", source="recipe", played=3
        )
        assert meta["axes_separated"] is True
        assert meta["axis_separation_by_horizon"] == {str(h): 2 for h in exporter.HORIZONS}

    def test_generated_at_is_an_instant_not_a_placeholder(self):
        bands = {"ARS": 2.4}
        meta = exporter.build_generation_meta(
            _out(bands, bands), season="2026-2027", source="season_start", played=0
        )
        assert meta["generated_at"].endswith("Z")
        assert len(meta["generated_at"]) == 20


@pytest.mark.parametrize("season", ["2025-2026", "2026-2027"])
def test_data_root_follows_the_historical_root_override(season, monkeypatch, tmp_path):
    """A workflow syncing R2 into a scratch root must feed BOTH this script's
    frames and compute_rolling_strength from that same root."""
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path))
    root = exporter.data_root(season)
    assert root == os.path.join(str(tmp_path), "seasons", season, "parquet_merged")
