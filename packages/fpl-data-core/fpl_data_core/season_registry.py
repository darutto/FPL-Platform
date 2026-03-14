"""
fpl_data_core.season_registry
==============================
YAML-driven season layout loader. Canonical platform version.

Reference: fpl-data-core/python/season_registry.py (audit copy — do not modify)
Source:    captaincy-ml/ml/data/season_layouts.py (SeasonLayout dataclass + registry)

The _DEFAULT_YAML path resolves to season_registry.yaml two directories up
from this file, which is fpl-data-core/season_registry.yaml regardless of
whether this module is in python/ or fpl_data_core/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# SeasonLayout dataclass  (identical to captaincy-ml/ml/data/season_layouts.py)
# ---------------------------------------------------------------------------

@dataclass
class SeasonLayout:
    """Encapsulates season-specific data structure information.

    Source: captaincy-ml/ml/data/season_layouts.py (lines 12-31) — unchanged.
    """
    season: str
    data_root: Path
    files: Dict[str, str]
    player_id_column: str
    gameweek_column: str
    has_consolidated_files: bool
    gameweek_pattern: str = "GW{gw}"

    def get_file_path(self, file_type: str, gameweek: Optional[int] = None) -> Path:
        """Return the path to a specific file for this season."""
        if file_type not in self.files:
            raise ValueError(
                f"File type '{file_type}' not found in season {self.season}"
            )
        file_pattern = self.files[file_type]
        if gameweek is not None and "{gw}" in file_pattern:
            gw_dir = self.gameweek_pattern.format(gw=gameweek)
            file_path = file_pattern.format(gw=gw_dir)
            return self.data_root / file_path
        return self.data_root / file_pattern

    def list_available_gameweeks(self) -> List[int]:
        """Return sorted list of gameweek numbers that have data on disk."""
        gameweeks = []
        if self.season == "2025-2026":
            by_gw_dir = self.data_root / "By Gameweek"
            if by_gw_dir.exists():
                for gw_dir in by_gw_dir.iterdir():
                    if gw_dir.is_dir() and gw_dir.name.startswith("GW"):
                        try:
                            gw_num = int(gw_dir.name[2:])
                            ps_file = gw_dir / "playerstats.csv"
                            if ps_file.exists() and ps_file.stat().st_size > 0:
                                gameweeks.append(gw_num)
                        except ValueError:
                            continue
        else:
            for subdir in ["matches", "playermatchstats"]:
                matches_dir = self.data_root / subdir
                if matches_dir.exists():
                    for gw_dir in matches_dir.iterdir():
                        if gw_dir.is_dir() and gw_dir.name.startswith("GW"):
                            try:
                                gw_num = int(gw_dir.name[2:])
                                if list(gw_dir.glob("*.csv")):
                                    gameweeks.append(gw_num)
                            except ValueError:
                                continue
        return sorted(set(gameweeks))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SEASON_REGISTRY: Dict[str, SeasonLayout] = {}

# Default YAML: two levels up from this file → fpl-data-core/season_registry.yaml
_DEFAULT_YAML = Path(__file__).parent.parent / "season_registry.yaml"


def load_registry_from_yaml(yaml_path: Path = _DEFAULT_YAML) -> None:
    """Populate SEASON_REGISTRY from a YAML file.

    Replaces captaincy-ml/ml/data/season_layouts.py::_initialize_registry()
    which had the same data hardcoded in Python source.
    """
    global SEASON_REGISTRY
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    for entry in raw.get("seasons", []):
        layout = SeasonLayout(
            season=entry["season"],
            data_root=Path(entry["data_root"]),
            files=entry.get("files", {}),
            player_id_column=entry.get("player_id_column", "id"),
            gameweek_column=entry.get("gameweek_column", "gw"),
            has_consolidated_files=entry.get("has_consolidated_files", False),
            gameweek_pattern=entry.get("gameweek_pattern", "GW{gw}"),
        )
        SEASON_REGISTRY[layout.season] = layout


def register_season(layout: SeasonLayout) -> None:
    """Manually register a season (for testing or one-off overrides)."""
    SEASON_REGISTRY[layout.season] = layout


def get_season_layout(season: str) -> SeasonLayout:
    """Return the SeasonLayout for a season identifier.

    Raises:
        KeyError: If season not registered.
    """
    if season not in SEASON_REGISTRY:
        raise KeyError(
            f"Season '{season}' not in registry. "
            f"Available: {list(SEASON_REGISTRY.keys())}"
        )
    return SEASON_REGISTRY[season]


def list_available_seasons() -> List[str]:
    """Return all registered season identifiers."""
    return list(SEASON_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Auto-initialize on import (mirrors original behaviour)
# ---------------------------------------------------------------------------

load_registry_from_yaml()


