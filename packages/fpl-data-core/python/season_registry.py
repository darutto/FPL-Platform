"""
fpl-data-core · packages/fpl-data-core/python/season_registry.py
=================================================================
YAML-driven season layout loader. Replaces hardcoded Python registry.

SOURCE:  Replaces and extends:
  - captaincy-ml/ml/data/season_layouts.py
    • SeasonLayout dataclass               → preserved as-is
    • SEASON_REGISTRY dict                 → now loaded from season_registry.yaml
    • register_season / get_season_layout  → preserved as-is
    • _initialize_registry()               → REPLACED by load_registry_from_yaml()

REPLACES (do NOT delete originals until migration is approved):
  - captaincy-ml/ml/data/season_layouts.py  → imports should switch to this module

CONSUMERS AFTER MIGRATION:
  - captaincy-ml/ml/data/fpl_data_access.py     → from fpl_data_core.season_registry import ...
  - captaincy-ml/ml/data/season_id_mapper.py    → from fpl_data_core.season_registry import ...
  - fpl-platform/pipelines/sync_from_supabase.py
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

    SOURCE: captaincy-ml/ml/data/season_layouts.py (lines 12-31) — unchanged.
    """
    season: str
    data_root: Path
    files: Dict[str, str]
    player_id_column: str
    gameweek_column: str
    has_consolidated_files: bool
    gameweek_pattern: str = "GW{gw}"

    def get_file_path(self, file_type: str, gameweek: Optional[int] = None) -> Path:
        """Return the path to a specific file for this season.

        SOURCE: captaincy-ml/ml/data/season_layouts.py::get_file_path (lines 33-58) — unchanged.
        """
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
        """Return sorted list of gameweek numbers that have data on disk.

        SOURCE: captaincy-ml/ml/data/season_layouts.py::list_available_gameweeks (lines 60-100) — unchanged.
        """
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

# Default path to the YAML config file (same directory as this module)
_DEFAULT_YAML = Path(__file__).parent.parent / "season_registry.yaml"


def load_registry_from_yaml(yaml_path: Path = _DEFAULT_YAML) -> None:
    """Populate SEASON_REGISTRY from a YAML file.

    This REPLACES captaincy-ml/ml/data/season_layouts.py::_initialize_registry()
    which had the same data hardcoded in Python source.

    The YAML schema mirrors season_registry.yaml in this package.
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
    """Manually register a season (for testing or one-off overrides).

    SOURCE: captaincy-ml/ml/data/season_layouts.py::register_season (lines 107-109) — unchanged.
    """
    SEASON_REGISTRY[layout.season] = layout


def get_season_layout(season: str) -> SeasonLayout:
    """Return the SeasonLayout for a season identifier.

    SOURCE: captaincy-ml/ml/data/season_layouts.py::get_season_layout (lines 112-126) — unchanged.

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
    """Return all registered season identifiers.

    SOURCE: captaincy-ml/ml/data/season_layouts.py::list_available_seasons (lines 129-131) — unchanged.
    """
    return list(SEASON_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Auto-initialize on import (mirrors original behaviour)
# ---------------------------------------------------------------------------

load_registry_from_yaml()


