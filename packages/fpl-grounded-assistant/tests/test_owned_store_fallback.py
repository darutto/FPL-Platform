"""
Tests for fpl_grounded_assistant.owned_store_fallback (CONTRACT §11.2).

Uses tmp_path + monkeypatching of FPL_HISTORICAL_ROOT to stand up an
on-disk owned-store skeleton without touching real data directories.

Import note: we import the module directly via importlib to avoid triggering
fpl_grounded_assistant/__init__.py, which has transitive deps (fpl_captain_engine
etc.) that may not be available in all test environments.  The module under
test is self-contained and does not rely on the package __init__.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Direct module import — avoids triggering fpl_grounded_assistant/__init__.py
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent                   # tests/
_PKG_DIR = _HERE.parent                                   # fpl-grounded-assistant/
_MODULE_PATH = _PKG_DIR / "fpl_grounded_assistant" / "owned_store_fallback.py"

_spec = importlib.util.spec_from_file_location(
    "fpl_grounded_assistant.owned_store_fallback", _MODULE_PATH
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
# Register in sys.modules BEFORE exec so @dataclass can resolve __module__
sys.modules["fpl_grounded_assistant.owned_store_fallback"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

OwnedStoreProvenance = _mod.OwnedStoreProvenance
OwnedStoreUnavailable = _mod.OwnedStoreUnavailable
load_bootstrap_from_owned_store = _mod.load_bootstrap_from_owned_store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEASON = "2025-2026"

# Filesystem-safe ISO 8601 format used by §10.6
_TS_FMT = "%Y-%m-%dT%H-%M-%SZ"


def _utcnow_safe() -> str:
    return datetime.now(tz=timezone.utc).strftime(_TS_FMT)


def _make_pointer(
    tmp_season_dir: Path,
    *,
    merged_at: str | None = None,
    baseline: dict | None = "DEFAULT",
    incrementals: list | None = None,
    row_counts: dict | None = None,
) -> dict:
    """Write _owned_latest.json and return the pointer dict."""
    if merged_at is None:
        merged_at = _utcnow_safe()
    if baseline == "DEFAULT":
        baseline = {
            "raw_dir": "raw/2026-05-25T14-22-03Z",
            "captured_at_utc": "2026-05-25T14-22-03Z",
            "manifest_status": "complete",
        }
    if incrementals is None:
        incrementals = []
    if row_counts is None:
        row_counts = {"players": 2, "teams": 2, "events": 1}

    pointer = {
        "schema_version": 1,
        "season": _SEASON,
        "merged_at": merged_at,
        "baseline": baseline,
        "incrementals": incrementals,
        "row_counts": row_counts,
    }
    pointer_path = tmp_season_dir / "_owned_latest.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    return pointer


def _write_parquet_files(
    merged_dir: Path,
    players_df: pd.DataFrame | None = None,
    teams_df: pd.DataFrame | None = None,
    events_df: pd.DataFrame | None = None,
) -> None:
    """Write parquet files to merged_dir."""
    merged_dir.mkdir(parents=True, exist_ok=True)

    if players_df is None:
        players_df = pd.DataFrame([
            {"player_id": 1, "team_id": 13, "web_name": "Haaland", "now_cost": 145, "captured_at": "2026-05-25T14-22-03Z"},
            {"player_id": 2, "team_id": 14, "web_name": "Salah",   "now_cost": 135, "captured_at": "2026-05-25T14-22-03Z"},
        ])
    if teams_df is None:
        teams_df = pd.DataFrame([
            {"team_id": 13, "name": "Man City",  "short_name": "MCI", "captured_at": "2026-05-25T14-22-03Z"},
            {"team_id": 14, "name": "Liverpool", "short_name": "LIV", "captured_at": "2026-05-25T14-22-03Z"},
        ])
    if events_df is None:
        events_df = pd.DataFrame([
            {"event_id": 38, "is_current": False, "finished": True, "captured_at": "2026-05-25T14-22-03Z"},
        ])

    players_df.to_parquet(merged_dir / "players.parquet", index=False)
    teams_df.to_parquet(merged_dir / "teams.parquet", index=False)
    events_df.to_parquet(merged_dir / "events.parquet", index=False)


@pytest.fixture()
def season_dir(tmp_path, monkeypatch) -> Path:
    """Return a tmp season dir wired up via FPL_HISTORICAL_ROOT."""
    root = tmp_path / "historical"
    s_dir = root / "seasons" / _SEASON
    s_dir.mkdir(parents=True)
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(root))
    return s_dir


# ---------------------------------------------------------------------------
# (i) Happy path
# ---------------------------------------------------------------------------

def test_happy_path(season_dir):
    """Bootstrap is reconstructed with FPL native field names; provenance is correct."""
    merged_at = _utcnow_safe()
    baseline_captured_at = "2026-05-25T14-22-03Z"
    pointer = _make_pointer(
        season_dir,
        merged_at=merged_at,
        baseline={
            "raw_dir": "raw/2026-05-25T14-22-03Z",
            "captured_at_utc": baseline_captured_at,
            "manifest_status": "complete",
        },
        incrementals=[{"gameweek": 1, "raw_dir": "incremental/gw01/...", "captured_at_utc": "2026-05-25T18-22-03Z"}],
        row_counts={"players": 2, "teams": 2, "events": 1},
    )
    _write_parquet_files(season_dir / "parquet_merged")

    bootstrap, prov = load_bootstrap_from_owned_store(_SEASON)

    # Required keys
    assert set(["elements", "teams", "events", "element_types"]).issubset(bootstrap.keys())

    # FPL native field names in elements
    assert all("id" in e for e in bootstrap["elements"])
    assert all("player_id" not in e for e in bootstrap["elements"])
    assert all("team" in e for e in bootstrap["elements"])
    assert all("team_id" not in e for e in bootstrap["elements"])

    # FPL native field names in teams
    assert all("id" in t for t in bootstrap["teams"])
    assert all("team_id" not in t for t in bootstrap["teams"])

    # FPL native field names in events
    assert all("id" in ev for ev in bootstrap["events"])
    assert all("event_id" not in ev for ev in bootstrap["events"])

    # Provenance
    assert prov.merged_at == merged_at
    assert prov.baseline_captured_at == baseline_captured_at
    assert prov.incremental_count == 1
    assert prov.staleness_hours >= 0.0
    assert prov.row_counts == pointer["row_counts"]


# ---------------------------------------------------------------------------
# (ii) Missing pointer
# ---------------------------------------------------------------------------

def test_missing_pointer(season_dir):
    """No _owned_latest.json → OwnedStoreUnavailable('no pointer')."""
    with pytest.raises(OwnedStoreUnavailable, match="no pointer"):
        load_bootstrap_from_owned_store(_SEASON)


# ---------------------------------------------------------------------------
# (iii) Empty store
# ---------------------------------------------------------------------------

def test_empty_store(season_dir):
    """baseline=None and incrementals=[] → OwnedStoreUnavailable('empty store')."""
    _make_pointer(season_dir, baseline=None, incrementals=[])
    with pytest.raises(OwnedStoreUnavailable, match="empty store"):
        load_bootstrap_from_owned_store(_SEASON)


# ---------------------------------------------------------------------------
# (iv) Parquet read failure
# ---------------------------------------------------------------------------

def test_parquet_read_failure(season_dir):
    """Valid pointer but missing/corrupt players.parquet → OwnedStoreUnavailable."""
    _make_pointer(season_dir)
    # Write partial files — omit players.parquet to trigger failure
    merged_dir = season_dir / "parquet_merged"
    merged_dir.mkdir(parents=True)
    # Write teams and events but NOT players (leave players.parquet absent)
    teams_df = pd.DataFrame([{"team_id": 13, "name": "Man City", "short_name": "MCI", "captured_at": "2026-05-25T14-22-03Z"}])
    events_df = pd.DataFrame([{"event_id": 38, "is_current": False, "finished": True, "captured_at": "2026-05-25T14-22-03Z"}])
    teams_df.to_parquet(merged_dir / "teams.parquet", index=False)
    events_df.to_parquet(merged_dir / "events.parquet", index=False)

    with pytest.raises(OwnedStoreUnavailable) as exc_info:
        load_bootstrap_from_owned_store(_SEASON)
    assert "parquet" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# (v) Null tolerance — NaN values become Python None
# ---------------------------------------------------------------------------

def test_null_tolerance(season_dir):
    """Players with NaN fields (§11.5 whole-row-replacement case) return None, not NaN."""
    import numpy as np

    _make_pointer(season_dir)
    players_df = pd.DataFrame([
        {
            "player_id": 1,
            "team_id": 13,
            "web_name": "Haaland",
            "now_cost": 145,
            "value": float("nan"),
            "was_home": float("nan"),
            "opponent_team": float("nan"),
            "captured_at": "2026-05-25T14-22-03Z",
        }
    ])
    _write_parquet_files(season_dir / "parquet_merged", players_df=players_df)

    bootstrap, _ = load_bootstrap_from_owned_store(_SEASON)
    elt = bootstrap["elements"][0]

    assert elt["value"] is None, f"expected None, got {elt['value']!r}"
    assert elt["was_home"] is None, f"expected None, got {elt['was_home']!r}"
    assert elt["opponent_team"] is None, f"expected None, got {elt['opponent_team']!r}"
    # Sanity: id and team are correctly renamed and not None
    assert elt["id"] == 1
    assert elt["team"] == 13


# ---------------------------------------------------------------------------
# (vi) element_types hardcode
# ---------------------------------------------------------------------------

def test_element_types_hardcode(season_dir):
    """element_types is always the 4-element hardcoded list, per CONTRACT §11.2."""
    _make_pointer(season_dir)
    _write_parquet_files(season_dir / "parquet_merged")

    bootstrap, _ = load_bootstrap_from_owned_store(_SEASON)
    et = bootstrap["element_types"]

    assert len(et) == 4
    assert et[0] == {"id": 1, "singular_name": "Goalkeeper"}
    assert et[1] == {"id": 2, "singular_name": "Defender"}
    assert et[2] == {"id": 3, "singular_name": "Midfielder"}
    assert et[3] == {"id": 4, "singular_name": "Forward"}


# ---------------------------------------------------------------------------
# (vii) Staleness math
# ---------------------------------------------------------------------------

def test_staleness_math(season_dir):
    """merged_at 5h ago → staleness_hours is 4.9..5.1."""
    five_hours_ago = datetime.now(tz=timezone.utc) - timedelta(hours=5)
    merged_at = five_hours_ago.strftime("%Y-%m-%dT%H-%M-%SZ")

    _make_pointer(season_dir, merged_at=merged_at)
    _write_parquet_files(season_dir / "parquet_merged")

    _, prov = load_bootstrap_from_owned_store(_SEASON)

    assert 4.9 <= prov.staleness_hours <= 5.1, (
        f"Expected staleness ~5h, got {prov.staleness_hours}"
    )
