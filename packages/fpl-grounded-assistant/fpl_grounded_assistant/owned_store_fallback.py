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
import sys
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
    if not _FPL_HISTORICAL_AVAILABLE:
        raise OwnedStoreUnavailable("fpl-historical not available")

    # ------------------------------------------------------------------
    # 1. Read the pointer file
    # ------------------------------------------------------------------
    pointer_path = owned_latest_pointer_path(season)
    if not pointer_path.exists():
        raise OwnedStoreUnavailable("no pointer")

    pointer: dict = json.loads(pointer_path.read_text("utf-8"))

    if pointer.get("baseline") is None and not pointer.get("incrementals", []):
        raise OwnedStoreUnavailable("empty store")

    # ------------------------------------------------------------------
    # 2. Load parquet tables from parquet_merged/
    # ------------------------------------------------------------------
    try:
        import pandas as pd
    except ImportError as exc:
        raise OwnedStoreUnavailable(f"pandas not available: {exc}") from exc

    merged_dir: Path = merged_parquet_dir(season)

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
    # 4. Compute staleness
    # ------------------------------------------------------------------
    merged_at_str: str = pointer["merged_at"]
    merged_at_dt = _parse_merged_at(merged_at_str)
    now_utc = datetime.now(tz=timezone.utc)
    staleness_hours = round(
        (now_utc - merged_at_dt).total_seconds() / 3600.0, 2
    )

    # ------------------------------------------------------------------
    # 5. Build provenance
    # ------------------------------------------------------------------
    provenance = OwnedStoreProvenance(
        pointer_path=str(pointer_path),
        merged_at=merged_at_str,
        baseline_captured_at=(pointer.get("baseline") or {}).get("captured_at_utc"),
        incremental_count=len(pointer.get("incrementals", [])),
        staleness_hours=staleness_hours,
        row_counts=pointer.get("row_counts", {}),
    )

    return (bootstrap_dict, provenance)
