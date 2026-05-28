"""
fpl_grounded_assistant.owned_store_fallback
===========================================
Owned-store fallback reader for bootstrap data.

Implements CONTRACT §11.2: reads the merge output produced by
``packages/fpl-historical/fpl_historical/merge.py`` and reconstructs a
bootstrap dict that matches the shape returned by
``fpl_api_client.get_bootstrap()`` so downstream code keeps working.

Cross-package import is done via sys.path insertion, mirroring the
``_SIB()`` pattern in ``fpl_server.py`` (CONTRACT §11.7).
"""
from __future__ import annotations

import json
import logging
import sys
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path shim — mirror fpl_server.py's _SIB() pattern
# Insert fpl-historical onto sys.path so its modules are importable without
# any pyproject.toml changes (CONTRACT §11.7).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))        # fpl_grounded_assistant/
_PKG  = os.path.dirname(_HERE)                            # fpl-grounded-assistant/
_PKGS = os.path.dirname(_PKG)                             # packages/
_FPL_HISTORICAL = os.path.join(_PKGS, "fpl-historical")

if _FPL_HISTORICAL not in sys.path:
    sys.path.insert(0, _FPL_HISTORICAL)

# Try to import the fpl-historical helpers at module load time.
# If the package is not on disk the module still loads — the error is
# surfaced only when load_bootstrap_from_owned_store() is actually called.
try:
    from fpl_historical.paths import (  # type: ignore[import]
        CURRENT_SEASON,
        merged_parquet_dir,
        owned_latest_pointer_path,
    )
    _FPL_HISTORICAL_AVAILABLE = True
except ImportError:
    _FPL_HISTORICAL_AVAILABLE = False
    CURRENT_SEASON = "2025-2026"  # fallback constant so default arg still resolves


# ---------------------------------------------------------------------------
# Public types (CONTRACT §11.2)
# ---------------------------------------------------------------------------

class OwnedStoreUnavailable(Exception):
    """Raised when the owned store cannot satisfy a bootstrap request."""


@dataclass(frozen=True)
class OwnedStoreProvenance:
    pointer_path: str
    merged_at: str
    baseline_captured_at: str | None
    incremental_count: int
    staleness_hours: float
    row_counts: dict


# ---------------------------------------------------------------------------
# element_types hardcode (CONTRACT §11.2)
# FPL's position taxonomy is static — the owned store does not capture
# element_types per §10.2, so the 4 positions are hardcoded here.
# ---------------------------------------------------------------------------
_ELEMENT_TYPES_HARDCODED = [
    {"id": 1, "singular_name": "Goalkeeper"},
    {"id": 2, "singular_name": "Defender"},
    {"id": 3, "singular_name": "Midfielder"},
    {"id": 4, "singular_name": "Forward"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_merged_at(merged_at: str) -> datetime:
    """Parse the filesystem-safe ISO 8601 timestamp used by §10.6.

    Format: ``%Y-%m-%dT%H-%M-%SZ`` (colons replaced by hyphens for Windows).
    """
    return datetime.strptime(merged_at, "%Y-%m-%dT%H-%M-%SZ").replace(
        tzinfo=timezone.utc
    )


def _nan_to_none(records: list[dict]) -> list[dict]:
    """Convert pandas NaN / float('nan') values to Python None in-place.

    Handles the tolerated-null case from §11.5: incremental rows may carry
    NaN for fields not present in event-live.stats.
    """
    import math

    cleaned = []
    for row in records:
        cleaned.append(
            {
                k: (None if (isinstance(v, float) and math.isnan(v)) else v)
                for k, v in row.items()
            }
        )
    return cleaned


def _coerce_native(v):
    """Coerce numpy / pandas scalars to native Python types.

    - Pandas NA / NaN → None
    - numpy.bool_ → bool
    - numpy.integer → int
    - numpy.floating → float (NaN → None)
    - pandas.Timestamp → ISO 8601 string
    - Everything else passed through unchanged.

    Safe to call on None, str, int, bool, float, etc.
    """
    if v is None:
        return None
    # Fast path: native types
    if isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        # math.isnan only works on floats; treat NaN as None
        import math
        return None if math.isnan(v) else v
    # numpy / pandas types — import lazily to keep module import cheap
    try:
        import numpy as np
        if isinstance(v, np.bool_):
            return bool(v)
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            f = float(v)
            import math
            return None if math.isnan(f) else f
    except ImportError:
        pass
    try:
        import pandas as pd
        if v is pd.NaT or (hasattr(pd, "isna") and not isinstance(v, (list, dict, tuple)) and pd.isna(v)):
            return None
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
    except (ImportError, TypeError, ValueError):
        pass
    return v


def _build_team_fixtures_from_owned_store(
    fixtures_df,            # pandas.DataFrame from fixtures.parquet
    bootstrap_teams: list,  # list of bootstrap team dicts (from teams.parquet projection)
) -> dict:
    """Reconstruct the ``team_fixtures`` map from owned-store fixtures parquet.

    Mirrors the semantics of
    ``fpl_pipeline.context._build_team_fixtures``: each team_id key maps to
    a list of upcoming/past fixture entries with keys
    ``gameweek``, ``opponent_team``, ``is_home``, ``difficulty``.

    Difficulty fallback chain:
        fixture difficulty → opponent team strength → 3

    Rows with null ``event_id`` (unscheduled) are skipped. Empty input → ``{}``.
    Re-implemented locally to keep owned_store_fallback.py free of
    ``fpl_pipeline`` imports (CONTRACT §11.7 isolation pattern).
    """
    strength_by_id: dict = {}
    for team in (bootstrap_teams or []):
        tid_raw = team.get("id")
        if tid_raw is None:
            continue
        tid = int(tid_raw)
        s_raw = team.get("strength")
        s = int(s_raw) if s_raw is not None else 3
        strength_by_id[tid] = s

    team_fixtures: dict = {}

    if fixtures_df is None or len(fixtures_df) == 0:
        return team_fixtures

    for rec in fixtures_df.to_dict(orient="records"):
        event_id = _coerce_native(rec.get("event_id"))
        if event_id is None:
            continue
        team_h = _coerce_native(rec.get("team_h"))
        team_a = _coerce_native(rec.get("team_a"))
        if team_h is None or team_a is None:
            continue

        gameweek = int(event_id)
        home_id = int(team_h)
        away_id = int(team_a)

        h_diff_raw = _coerce_native(rec.get("team_h_difficulty"))
        a_diff_raw = _coerce_native(rec.get("team_a_difficulty"))

        home_diff = int(h_diff_raw) if h_diff_raw is not None else int(strength_by_id.get(away_id, 3))
        away_diff = int(a_diff_raw) if a_diff_raw is not None else int(strength_by_id.get(home_id, 3))

        team_fixtures.setdefault(home_id, []).append({
            "gameweek":      gameweek,
            "opponent_team": away_id,
            "is_home":       True,
            "difficulty":    home_diff,
        })
        team_fixtures.setdefault(away_id, []).append({
            "gameweek":      gameweek,
            "opponent_team": home_id,
            "is_home":       False,
            "difficulty":    away_diff,
        })

    for fixture_list in team_fixtures.values():
        fixture_list.sort(key=lambda fx: (int(fx["gameweek"]), int(fx["opponent_team"])))

    return team_fixtures


# ---------------------------------------------------------------------------
# Shared pre-amble: pointer read + provenance build
# Used by both load_bootstrap_from_owned_store and
# load_element_summary_from_owned_store. Returns (merged_dir, provenance).
# Raises OwnedStoreUnavailable on any failure.
# ---------------------------------------------------------------------------

def _read_pointer_and_build_provenance(
    season: str,
) -> "tuple[Path, OwnedStoreProvenance]":
    if not _FPL_HISTORICAL_AVAILABLE:
        raise OwnedStoreUnavailable("fpl-historical not available")

    pointer_path = owned_latest_pointer_path(season)
    if not pointer_path.exists():
        raise OwnedStoreUnavailable("no pointer")

    pointer: dict = json.loads(pointer_path.read_text("utf-8"))

    if pointer.get("baseline") is None and not pointer.get("incrementals", []):
        raise OwnedStoreUnavailable("empty store")

    merged_dir: Path = merged_parquet_dir(season)

    merged_at_str: str = pointer["merged_at"]
    merged_at_dt = _parse_merged_at(merged_at_str)
    now_utc = datetime.now(tz=timezone.utc)
    staleness_hours = round(
        (now_utc - merged_at_dt).total_seconds() / 3600.0, 2
    )

    provenance = OwnedStoreProvenance(
        pointer_path=str(pointer_path),
        merged_at=merged_at_str,
        baseline_captured_at=(pointer.get("baseline") or {}).get("captured_at_utc"),
        incremental_count=len(pointer.get("incrementals", [])),
        staleness_hours=staleness_hours,
        row_counts=pointer.get("row_counts", {}),
    )

    return merged_dir, provenance


# ---------------------------------------------------------------------------
# Public API (CONTRACT §11.2)
# ---------------------------------------------------------------------------

def load_bootstrap_from_owned_store(
    season: str = CURRENT_SEASON,
) -> tuple[dict, OwnedStoreProvenance]:
    """Return (bootstrap_dict, provenance).

    Raises OwnedStoreUnavailable on any failure.

    bootstrap_dict matches the shape returned by fpl_api_client.get_bootstrap():
    keys 'elements', 'teams', 'events', 'element_types' at minimum.
    """
    merged_dir, provenance = _read_pointer_and_build_provenance(season)

    # ------------------------------------------------------------------
    # Load parquet tables from parquet_merged/
    # ------------------------------------------------------------------
    try:
        import pandas as pd
    except ImportError as exc:
        raise OwnedStoreUnavailable(f"pandas not available: {exc}") from exc

    try:
        players_df = pd.read_parquet(merged_dir / "players.parquet")
        teams_df   = pd.read_parquet(merged_dir / "teams.parquet")
        events_df  = pd.read_parquet(merged_dir / "events.parquet")
    except Exception as exc:
        raise OwnedStoreUnavailable(f"parquet read failed: {exc}") from exc

    # ------------------------------------------------------------------
    # 3. Reconstruct bootstrap dict (reverse-rename to FPL native names)
    # ------------------------------------------------------------------

    # players → elements: player_id → id, team_id → team
    players_df = players_df.rename(columns={"player_id": "id", "team_id": "team"})
    elements = _nan_to_none(players_df.to_dict(orient="records"))

    # teams → teams: team_id → id
    teams_df = teams_df.rename(columns={"team_id": "id"})
    teams = _nan_to_none(teams_df.to_dict(orient="records"))

    # events → events: event_id → id
    events_df = events_df.rename(columns={"event_id": "id"})
    events = _nan_to_none(events_df.to_dict(orient="records"))

    # element_types: hardcoded (CONTRACT §11.2 — FPL taxonomy is static)
    element_types = list(_ELEMENT_TYPES_HARDCODED)

    bootstrap_dict: dict = {
        "elements":      elements,
        "teams":         teams,
        "events":        events,
        "element_types": element_types,
    }

    # ------------------------------------------------------------------
    # H4c: reconstruct team_fixtures from fixtures.parquet (if available)
    # so consumers of bootstrap["team_fixtures"] (player_fixture_run + 13
    # others) gain owned-store transparency. Missing fixtures.parquet is
    # tolerated — bootstrap remains usable for non-fixture queries.
    # ------------------------------------------------------------------
    fixtures_row_count: int = 0
    try:
        fixtures_df = pd.read_parquet(merged_dir / "fixtures.parquet")
        fixtures_row_count = int(len(fixtures_df))
        bootstrap_dict["team_fixtures"] = _build_team_fixtures_from_owned_store(
            fixtures_df, bootstrap_dict["teams"]
        )
    except FileNotFoundError:
        _LOGGER.debug(
            "owned_store_team_fixtures_skipped reason=fixtures_parquet_missing "
            "merged_dir=%s",
            merged_dir,
        )
        bootstrap_dict["team_fixtures"] = {}
    except Exception as exc:
        # Treat any read/parse failure as "no team_fixtures available" rather
        # than aborting the whole bootstrap fallback. Consumers degrade to
        # missing_context exactly as they would today.
        _LOGGER.debug(
            "owned_store_team_fixtures_skipped reason=parquet_error err=%s",
            exc,
        )
        bootstrap_dict["team_fixtures"] = {}

    # Augment provenance with fixtures row count (additive — existing keys
    # untouched). Dataclass is frozen, so rebuild with merged row_counts.
    if fixtures_row_count > 0 or "fixtures" not in provenance.row_counts:
        merged_row_counts = dict(provenance.row_counts)
        merged_row_counts["fixtures"] = fixtures_row_count
        provenance = OwnedStoreProvenance(
            pointer_path=provenance.pointer_path,
            merged_at=provenance.merged_at,
            baseline_captured_at=provenance.baseline_captured_at,
            incremental_count=provenance.incremental_count,
            staleness_hours=provenance.staleness_hours,
            row_counts=merged_row_counts,
        )

    return (bootstrap_dict, provenance)


# ---------------------------------------------------------------------------
# H4b Seam 1: per-tool element-summary fallback
# ---------------------------------------------------------------------------

def load_element_summary_from_owned_store(
    element_id: int,
    season: str = CURRENT_SEASON,
) -> tuple[dict, OwnedStoreProvenance]:
    """Return ({"history": [...], "fixtures": [], "history_past": []}, provenance).

    Reads player_gw_stats.parquet from the merged owned store, filters to
    rows where ``player_id == element_id``, and projects each row into the
    FPL element-summary ``history`` shape. NULL columns (value, was_home,
    opponent_team) on incremental-winning rows are preserved as None — no
    synthesis.

    Raises ``OwnedStoreUnavailable`` if the pointer is missing, the store
    is empty, the parquet read fails, or zero rows match ``element_id``.
    """
    merged_dir, provenance = _read_pointer_and_build_provenance(season)

    try:
        import pandas as pd
    except ImportError as exc:
        raise OwnedStoreUnavailable(f"pandas not available: {exc}") from exc

    try:
        gw_df = pd.read_parquet(merged_dir / "player_gw_stats.parquet")
    except Exception as exc:
        raise OwnedStoreUnavailable(
            f"player_gw_stats parquet read failed: {exc}"
        ) from exc

    rows = gw_df[gw_df["player_id"] == element_id]
    if len(rows) == 0:
        raise OwnedStoreUnavailable(f"no owned rows for element_id={element_id}")

    # Sort by event_id ascending (NULL-safe; event_id should always be present
    # but guard against NaN ordering issues anyway).
    rows = rows.sort_values(by="event_id", ascending=True, na_position="last")

    history: list[dict] = []
    for rec in rows.to_dict(orient="records"):
        history.append({
            "element":                      _coerce_native(rec.get("player_id")),
            "round":                        _coerce_native(rec.get("event_id")),
            "total_points":                 _coerce_native(rec.get("total_points")),
            "minutes":                      _coerce_native(rec.get("minutes")),
            "goals_scored":                 _coerce_native(rec.get("goals_scored")),
            "assists":                      _coerce_native(rec.get("assists")),
            "bonus":                        _coerce_native(rec.get("bonus")),
            "bps":                          _coerce_native(rec.get("bps")),
            "expected_goals":               _coerce_native(rec.get("expected_goals")),
            "expected_assists":             _coerce_native(rec.get("expected_assists")),
            "expected_goal_involvements":   _coerce_native(rec.get("expected_goal_involvements")),
            "value":                        _coerce_native(rec.get("value")),
            "was_home":                     _coerce_native(rec.get("was_home")),
            "opponent_team":                _coerce_native(rec.get("opponent_team")),
        })

    return ({"history": history, "fixtures": [], "history_past": []}, provenance)


# ---------------------------------------------------------------------------
# --- H4b Seam 2: fixtures fallback ---
# Per-gameweek fixtures reader for the owned store.
#
# Reuses Agent A's shared pre-amble (_read_pointer_and_build_provenance) and
# numpy/pandas coercion helper (_coerce_native).
# ---------------------------------------------------------------------------

def load_fixtures_for_gw_from_owned_store(
    gw_number: int,
    season: str = CURRENT_SEASON,
) -> tuple[list[dict], OwnedStoreProvenance]:
    """Return (fixtures_list, provenance) for *gw_number* from the owned store.

    fixtures_list mirrors the shape of the FPL `/fixtures/?event=<gw>` response:
    each dict carries keys
        id, event, team_h, team_a, team_h_score, team_a_score,
        team_h_difficulty, team_a_difficulty, finished, kickoff_time

    Sorted by `id` ascending. Numpy / pandas types are coerced to native
    Python; NULL `team_h_score` / `team_a_score` pass through as None.

    Raises OwnedStoreUnavailable on any failure (no pointer, no parquet,
    zero matching rows, etc).
    """
    merged_dir, provenance = _read_pointer_and_build_provenance(season)

    try:
        import pandas as pd
    except ImportError as exc:
        raise OwnedStoreUnavailable(f"pandas not available: {exc}") from exc

    try:
        fixtures_df = pd.read_parquet(merged_dir / "fixtures.parquet")
    except Exception as exc:
        raise OwnedStoreUnavailable(f"fixtures parquet read failed: {exc}") from exc

    gw_rows = fixtures_df[fixtures_df["event_id"] == gw_number]
    if len(gw_rows) == 0:
        raise OwnedStoreUnavailable(f"no owned fixtures for gw={gw_number}")

    # Project to FPL-shaped dicts (rename + coerce).
    out: list[dict] = []
    for rec in gw_rows.to_dict(orient="records"):
        out.append({
            "id":                 _coerce_native(rec.get("fixture_id")),
            "event":              _coerce_native(rec.get("event_id")),
            "team_h":             _coerce_native(rec.get("team_h")),
            "team_a":             _coerce_native(rec.get("team_a")),
            "team_h_score":       _coerce_native(rec.get("team_h_score")),
            "team_a_score":       _coerce_native(rec.get("team_a_score")),
            "team_h_difficulty":  _coerce_native(rec.get("team_h_difficulty")),
            "team_a_difficulty":  _coerce_native(rec.get("team_a_difficulty")),
            "finished":           _coerce_native(rec.get("finished")),
            "kickoff_time":       _coerce_native(rec.get("kickoff_time")),
        })

    # Sort by id ascending (None-safe).
    out.sort(key=lambda f: (f["id"] if f["id"] is not None else 0))

    return (out, provenance)
