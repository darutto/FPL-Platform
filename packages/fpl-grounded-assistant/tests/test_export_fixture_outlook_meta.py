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
import json
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

# ---------------------------------------------------------------------------
# The output-side guard and the argument combinations, added after an
# independent verification pass pointed out that measuring `axes_separated`
# and then shipping the bundle regardless left the loop open.
# ---------------------------------------------------------------------------


def _parse(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["export_real_season_fixture_outlook.py", *argv])
    return exporter.parse_args()


def test_season_start_refuses_a_season_rather_than_ignoring_it(monkeypatch):
    """--season-start reads the live API, which only serves the current season.

    Accepting --season there would stamp one season's name onto another
    season's data. Silently ignoring it is the same bug one step quieter.
    """
    with pytest.raises(SystemExit):
        _parse(["--season", "2025-2026", "--season-start"], monkeypatch)


def test_season_defaults_to_the_pin_without_hardcoding_it_at_parse_time(monkeypatch):
    """--season parses as None so the season-start conflict is detectable.

    main() resolves it to SEASON. If this ever became `default=SEASON` again,
    the conflict check above could not tell "passed explicitly" from
    "defaulted" and would fire on every --season-start run.
    """
    assert _parse([], monkeypatch).season is None
    assert _parse(["--season", "2026-2027"], monkeypatch).season == "2026-2027"


def test_require_separated_axes_is_off_by_default(monkeypatch):
    """A legitimate season-start bundle IS collapsed and must still build."""
    assert _parse([], monkeypatch).require_separated_axes is False
    assert _parse(["--require-separated-axes"], monkeypatch).require_separated_axes is True


def test_the_output_guard_reads_the_same_measurement_the_bundle_carries():
    """The flag the workflow exits on is the one stamped into the file.

    Two separate notions of "separated" -- one for the gate, one for the
    stamp -- is how a bundle ends up passing CI while telling the reader
    something else.
    """
    collapsed = _out({"ARS": 2.5, "MCI": 2.0}, {"ARS": 2.5, "MCI": 2.0})
    meta = exporter.build_generation_meta(
        collapsed, season="2026-2027", source="season_start", played=0
    )
    assert meta["axes_separated"] is False
    assert exporter.axis_separation(collapsed) == meta["axis_separation_by_horizon"]

    separated = _out({"ARS": 2.5, "MCI": 2.0}, {"ARS": 3.5, "MCI": 2.0})
    meta = exporter.build_generation_meta(
        separated, season="2026-2027", source="recipe", played=3
    )
    assert meta["axes_separated"] is True
    assert exporter.axis_separation(separated) == meta["axis_separation_by_horizon"]

def _stub_export(monkeypatch, tmp_path, *, defence_bands, argv):
    """Drive main() with the engine stubbed, so the exit path is the subject.

    Only the two expensive edges are replaced -- the parquet read and the
    outlook engine. Everything between them (metadata assembly, the
    measurement, the exit decision, the file write) is the real code.
    """
    fixtures_df = pd.DataFrame(
        [{"event_id": 1, "team_h": 1, "team_a": 2,
          "team_h_score": 1, "team_a_score": 0, "finished": True}]
    )
    monkeypatch.setattr(
        exporter, "_load_frames", lambda season: (pd.DataFrame(), fixtures_df)
    )
    monkeypatch.setattr(
        exporter, "build_recipe_bootstraps",
        lambda teams_df, fixtures_df, season: ({"axis": "attack"}, {"axis": "defence"}),
    )
    monkeypatch.setattr(
        exporter.fixture_outlook, "get_all_team_outlooks",
        lambda boot, axis, horizon: {
            "teams": [
                {"team_short": "ARS",
                 "avg_band": defence_bands if axis == "defence" else 2.0},
            ]
        },
    )
    out_path = tmp_path / "bundle.json"
    monkeypatch.setattr(
        "sys.argv",
        ["export_real_season_fixture_outlook.py", "--out", str(out_path), *argv],
    )
    return out_path


def test_require_separated_axes_exits_nonzero_on_a_collapsed_bundle(
    monkeypatch, tmp_path
):
    """The output-side gate. Without this the shipped incident repeats exactly:
    every precondition satisfied, a collapsed file written, exit 0, uploaded."""
    out_path = _stub_export(
        monkeypatch, tmp_path, defence_bands=2.0, argv=["--require-separated-axes"]
    )
    with pytest.raises(SystemExit) as excinfo:
        exporter.main()
    assert excinfo.value.code == 1
    # Written anyway, on purpose: you cannot diagnose a bundle you cannot open.
    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8"))["generation"][
        "axes_separated"
    ] is False


def test_require_separated_axes_lets_a_genuinely_separated_bundle_through(
    monkeypatch, tmp_path
):
    out_path = _stub_export(
        monkeypatch, tmp_path, defence_bands=4.0, argv=["--require-separated-axes"]
    )
    exporter.main()  # must not raise
    assert json.loads(out_path.read_text(encoding="utf-8"))["generation"][
        "axes_separated"
    ] is True


def test_without_the_flag_a_collapsed_bundle_still_builds(monkeypatch, tmp_path):
    """Season start is legitimately collapsed. The gate is opt-in for that
    reason, and the bundle still declares the mode either way."""
    out_path = _stub_export(monkeypatch, tmp_path, defence_bands=2.0, argv=[])
    exporter.main()  # must not raise
    assert json.loads(out_path.read_text(encoding="utf-8"))["generation"][
        "axes_separated"
    ] is False
