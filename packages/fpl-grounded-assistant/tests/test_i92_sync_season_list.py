"""i92 -- the container syncs a LIST of seasons, and /healthz reports what is
actually on disk.

Before: fpl_server called ``sync_owned_store_from_r2()`` once, so Railway's
ephemeral disk held CURRENT_SEASON only and every "temporada pasada" question
died in ``season_not_found`` while R2 held the season intact.

Pinned here:
  1. ``seasons_to_sync()`` is the single source: current + previous by
     default, ``OWNED_STORE_SYNC_SEASONS`` overrides, dedup, order kept.
  2. ``sync_owned_store_seasons`` is fail-soft PER season and keeps the
     ``/healthz.owned_store_sync`` block pointing at the first season.
  3. ``seasons_on_disk()`` reads the filesystem (pointer + parquet count),
     and /healthz.owned_store_seasons comes from THAT -- not from the list
     that was requested. The test makes the two disagree on purpose.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import owned_store_sync as osync

CURRENT = osync.CURRENT_SEASON
PREVIOUS = osync.previous_season(CURRENT)


# --- 1. the list ------------------------------------------------------------

def test_default_list_is_current_then_previous(monkeypatch):
    monkeypatch.delenv(osync.ENV_SYNC_SEASONS, raising=False)
    assert osync.seasons_to_sync() == [CURRENT, PREVIOUS]


def test_env_override_wins_dedups_and_keeps_order(monkeypatch):
    monkeypatch.setenv(osync.ENV_SYNC_SEASONS, " 2024-2025, 2026-2027 ,2024-2025,, ")
    assert osync.seasons_to_sync() == ["2024-2025", "2026-2027"]


def test_previous_season_arithmetic():
    assert osync.previous_season("2026-2027") == "2025-2026"
    assert osync.previous_season("garbage") is None


# --- 2. per-season fail-soft --------------------------------------------------

def test_multi_season_sync_is_fail_soft_per_season_and_keeps_first_as_primary(monkeypatch):
    calls: list[str] = []

    def fake_sync(season):
        calls.append(season)
        ok = season == CURRENT
        return osync.SyncResult(ok=ok, season=season, files_synced=6 if ok else 0,
                                merged_at="2026-09-11T00-15-09Z" if ok else None,
                                staleness_hours=1.0 if ok else None,
                                error=None if ok else "missing files: pointer")

    monkeypatch.setattr(osync, "sync_owned_store_from_r2", fake_sync)
    monkeypatch.delenv(osync.ENV_SYNC_SEASONS, raising=False)
    results = osync.sync_owned_store_seasons()

    assert calls == [CURRENT, PREVIOUS]          # the missing previous did not stop anything
    assert [r.ok for r in results] == [True, False]
    assert osync.get_last_sync_results() == results
    assert osync.get_last_sync_result() == results[0]   # /healthz block unchanged in meaning


def test_explicit_seasons_argument_is_honoured(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(osync, "sync_owned_store_from_r2",
                        lambda s: (seen.append(s), osync.SyncResult(True, s, 6, None, None, None))[1])
    osync.sync_owned_store_seasons(["2023-2024"])
    assert seen == ["2023-2024"]


# --- 3. disk scan, independent of the request ---------------------------------

def _write_season(root: Path, season: str, *, merged_at: str | None, n_parquet: int) -> None:
    d = root / "seasons" / season
    (d / "parquet_merged").mkdir(parents=True)
    (d / "_owned_latest.json").write_text(json.dumps({"season": season, "merged_at": merged_at}), "utf-8")
    for name in osync._PARQUET_NAMES[:n_parquet]:
        (d / "parquet_merged" / f"{name}.parquet").write_bytes(b"x")


@pytest.fixture
def disk(tmp_path: Path, monkeypatch):
    root = tmp_path / "historical"
    _write_season(root, "2026-2027", merged_at="2026-09-11T00-15-09Z", n_parquet=5)
    _write_season(root, "2025-2026", merged_at="2026-06-01T00-40-44Z", n_parquet=3)   # incomplete
    (root / "seasons" / "2024-2025").mkdir(parents=True)                                # no pointer -> absent
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(root))
    return root


def test_seasons_on_disk_reads_pointers_and_parquet_counts(disk: Path):
    rows = osync.seasons_on_disk()
    assert [r["season"] for r in rows] == ["2025-2026", "2026-2027"]
    by = {r["season"]: r for r in rows}
    assert by["2026-2027"] == {"season": "2026-2027", "merged_at": "2026-09-11T00-15-09Z",
                               "parquet_files": 5, "complete": True}
    assert by["2025-2026"]["complete"] is False and by["2025-2026"]["parquet_files"] == 3


def test_seasons_on_disk_never_raises_without_a_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path / "nowhere"))
    assert osync.seasons_on_disk() == []


def test_healthz_reports_disk_not_the_requested_list(disk: Path, monkeypatch):
    """The request said 'sync 2026-2027 and 2019-2020'; the disk has 2026-2027
    and an incomplete 2025-2026. /healthz must say what the disk says."""
    monkeypatch.setenv(osync.ENV_SYNC_SEASONS, "2026-2027,2019-2020")
    requested = osync.seasons_to_sync()
    assert "2019-2020" in requested

    client = TestClient(fpl_server.app)
    payload = client.get("/healthz").json()
    seasons = payload["owned_store_seasons"]
    assert [r["season"] for r in seasons] == ["2025-2026", "2026-2027"]
    assert "2019-2020" not in {r["season"] for r in seasons}
    # the legacy block is untouched in shape
    if payload["owned_store_sync"] is not None:
        assert set(payload["owned_store_sync"]) == {"ok", "season", "files_synced", "merged_at", "staleness_hours", "error"}


def test_healthz_owned_store_seasons_is_a_list_even_with_no_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path / "empty"))
    payload = TestClient(fpl_server.app).get("/healthz").json()
    assert payload["owned_store_seasons"] == []


# --- startup wiring -------------------------------------------------------------

def test_server_startup_uses_the_multi_season_entry_point():
    src = Path(fpl_server.__file__).read_text(encoding="utf-8")
    assert "sync_owned_store_seasons()" in src
    assert "_sync_res = sync_owned_store_from_r2()" not in src
