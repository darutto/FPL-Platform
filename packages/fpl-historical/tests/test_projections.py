"""
tests/test_projections.py
=========================
Tests for fpl_historical.projections.build_parquet_from_raw.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from conftest import (
    MINIMAL_BOOTSTRAP,
    MINIMAL_ELEMENT_SUMMARY,
    MINIMAL_FIXTURES,
)
from fpl_historical.manifest import Manifest, write_manifest
from fpl_historical.paths import latest_pointer_path, parquet_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_raw_dir(tmp_path: Path, status: str = "complete") -> Path:
    """Write a minimal raw capture directory with the given manifest status."""
    raw_dir = tmp_path / "raw" / "2026-05-25T14-22-03Z"
    raw_dir.mkdir(parents=True)
    (raw_dir / "element-summary").mkdir()

    # bootstrap-static.json.gz
    bs_bytes = json.dumps(MINIMAL_BOOTSTRAP).encode("utf-8")
    with gzip.open(raw_dir / "bootstrap-static.json.gz", "wb") as fh:
        fh.write(bs_bytes)

    # fixtures.json.gz
    fx_bytes = json.dumps(MINIMAL_FIXTURES).encode("utf-8")
    with gzip.open(raw_dir / "fixtures.json.gz", "wb") as fh:
        fh.write(fx_bytes)

    # element-summary/{id}.json.gz for each element
    for element in MINIMAL_BOOTSTRAP["elements"]:
        eid = element["id"]
        es_bytes = json.dumps(MINIMAL_ELEMENT_SUMMARY).encode("utf-8")
        with gzip.open(raw_dir / "element-summary" / f"{eid}.json.gz", "wb") as fh:
            fh.write(es_bytes)

    # _manifest.json
    m = Manifest(
        schema_version=1,
        season="2025-2026",
        status=status,  # type: ignore[arg-type]
        captured_at_utc="2026-05-25T14:22:03Z",
        git_sha="abc1234",
        fpl_endpoints={
            "bootstrap-static": {"url": "https://...", "status": 200, "bytes": len(bs_bytes), "sha256": ""},
            "fixtures": {"url": "https://...", "status": 200, "bytes": len(fx_bytes), "sha256": ""},
            "element-summary": {"count": len(MINIMAL_BOOTSTRAP["elements"]), "failures": [], "sha256_aggregate": ""},
        },
        current_event_id=38,
        elapsed_seconds=1.0,
    )
    write_manifest(raw_dir, m)
    return raw_dir


# ---------------------------------------------------------------------------
# Test: complete snapshot → 5 parquet files produced
# ---------------------------------------------------------------------------

class TestCompleteSnapshot:
    def test_five_parquet_files_written(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        for name in ("players", "teams", "events", "fixtures", "player_gw_stats"):
            assert (p_dir / f"{name}.parquet").exists(), f"{name}.parquet not found"

    def test_players_pk_column_exists(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        df = pd.read_parquet(p_dir / "players.parquet")
        assert "player_id" in df.columns
        assert "id" not in df.columns, "'id' should have been renamed to 'player_id'"

    def test_teams_pk_column_exists(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        df = pd.read_parquet(p_dir / "teams.parquet")
        assert "team_id" in df.columns

    def test_events_pk_column_exists(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        df = pd.read_parquet(p_dir / "events.parquet")
        assert "event_id" in df.columns

    def test_fixtures_pk_and_fk_columns_exist(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        df = pd.read_parquet(p_dir / "fixtures.parquet")
        assert "fixture_id" in df.columns
        assert "event_id" in df.columns
        assert "id" not in df.columns

    def test_player_gw_stats_pk_uniqueness(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        df = pd.read_parquet(p_dir / "player_gw_stats.parquet")
        assert "player_id" in df.columns
        assert "event_id" in df.columns
        dupes = df.duplicated(subset=["player_id", "event_id"]).sum()
        assert dupes == 0, f"Found {dupes} duplicate (player_id, event_id) pairs"

    def test_captured_at_column_on_all_tables(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        for name in ("players", "teams", "events", "fixtures", "player_gw_stats"):
            df = pd.read_parquet(p_dir / f"{name}.parquet")
            assert "captured_at" in df.columns, f"captured_at missing from {name}"
            assert (df["captured_at"] == "2026-05-25T14:22:03Z").all()

    def test_latest_json_updated_on_success(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        latest_path = latest_pointer_path("2025-2026")
        assert latest_path.exists()
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        assert data["raw_dir"] == raw_dir.name
        assert "parquet_built_at" in data

    def test_players_team_id_rename(self, tmp_historical_root):
        """players.team must be renamed to team_id (CONTRACT §5)."""
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        df = pd.read_parquet(p_dir / "players.parquet")
        assert "team_id" in df.columns

    def test_passthrough_unknown_columns(self, tmp_historical_root):
        """Extra columns in source data are kept (permissive passthrough)."""
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir)

        # 'expected_goals' is an extra field in MINIMAL_BOOTSTRAP elements
        df = pd.read_parquet(p_dir / "players.parquet")
        assert "expected_goals" in df.columns


# ---------------------------------------------------------------------------
# Test: complete_with_gaps — gate behavior
# ---------------------------------------------------------------------------

class TestCompleteWithGaps:
    def test_raises_without_promote_flag(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete_with_gaps")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        with pytest.raises(ValueError, match="complete_with_gaps"):
            build_parquet_from_raw(raw_dir, p_dir)

    def test_succeeds_with_promote_flag(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete_with_gaps")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir, promote_with_gaps=True)

        for name in ("players", "teams", "events", "fixtures", "player_gw_stats"):
            assert (p_dir / f"{name}.parquet").exists()

    def test_latest_json_updated_with_promote_flag(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="complete_with_gaps")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        build_parquet_from_raw(raw_dir, p_dir, promote_with_gaps=True)

        assert latest_pointer_path("2025-2026").exists()


# ---------------------------------------------------------------------------
# Test: failed — always raises
# ---------------------------------------------------------------------------

class TestFailedSnapshot:
    def test_raises_without_promote_flag(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="failed")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        with pytest.raises(ValueError, match="cannot promote failed capture"):
            build_parquet_from_raw(raw_dir, p_dir)

    def test_raises_with_promote_flag(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="failed")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        with pytest.raises(ValueError, match="cannot promote failed capture"):
            build_parquet_from_raw(raw_dir, p_dir, promote_with_gaps=True)

    def test_latest_json_not_written_on_failure(self, tmp_historical_root):
        raw_dir = _write_raw_dir(tmp_historical_root, status="failed")
        p_dir = parquet_dir("2025-2026")

        from fpl_historical.projections import build_parquet_from_raw
        with pytest.raises(ValueError):
            build_parquet_from_raw(raw_dir, p_dir)

        assert not latest_pointer_path("2025-2026").exists()
