"""
fpl-player-registry · packages/fpl-player-registry/python/player_registry.py
==============================================================================
Unified player and team identity service.

Merges three independent identity systems:
  1. Cross-season player ID mapping
  2. Spanish community nickname resolution
  3. Live FPL bootstrap player database

SOURCE:  Merges and unifies:
  - captaincy-ml/ml/data/season_id_mapper.py
    • SeasonIdMapper class (full file — re-exported unchanged)
  - fpl-video-repurposer/build_fpl_kb.py
    • KNOWN_NICKNAMES    (lines 73-100)
    • SPANISH_PORTUGUESE_PATTERNS (lines 62-70)
    • build_master_squad() (lines 38-58)
  - captaincy-ml/check_players.py
    • validation_players dict (manual spot-check — absorbed into tests)

REPLACES (do NOT delete originals until migration is approved):
  - captaincy-ml/ml/data/season_id_mapper.py
  - fpl-video-repurposer/build_fpl_kb.py (name sections)
  - captaincy-ml/check_players.py

CONSUMERS AFTER MIGRATION:
  - fpl-video-repurposer/build_fpl_kb.py   → from fpl_player_registry import ...
  - fpl-video-repurposer/correct_transcript.py
  - captaincy-ml/phase4_tiered_recommendations.py
  - fpl-platform/apps/fpl-chat (LLM tool: resolve_player_name)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from fpl_data_core.season_registry import get_season_layout

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-export SeasonIdMapper unchanged from captaincy-ml
# ---------------------------------------------------------------------------

# NOTE: After migration, captaincy-ml/ml/data/season_id_mapper.py is deleted
# and SeasonIdMapper lives here. The class below is a direct copy with updated
# import paths.

class SeasonIdMapper:
    """Cross-season player ID harmonisation.

    Uses players.csv.player_id as canonical identity.
    Maps to/from per-season playerstats.id values.

    SOURCE: captaincy-ml/ml/data/season_id_mapper.py (full file — lines 17-248)
            Only import paths changed:
              from .season_layouts import get_season_layout
              → from fpl_data_core.season_registry import get_season_layout
    """

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path.cwd()
        self.id_maps_dir = self.workspace_root / "data" / "id_maps"
        self.id_maps_dir.mkdir(parents=True, exist_ok=True)
        self._season_to_canonical: Dict[str, Dict[int, int]] = {}
        self._canonical_to_season: Dict[str, Dict[int, int]] = {}

    def _load_players_canonical(self, season: str) -> Dict[str, int]:
        layout = get_season_layout(season)
        players_path = self.workspace_root / layout.get_file_path("players")
        if not players_path.exists():
            raise FileNotFoundError(f"Players file not found: {players_path}")
        players_df = pd.read_csv(players_path)
        return {row["web_name"]: row["player_id"] for _, row in players_df.iterrows()}

    def _load_season_playerstats(self, season: str) -> pd.DataFrame:
        layout = get_season_layout(season)
        if not layout.has_consolidated_files:
            path = self.workspace_root / layout.get_file_path("playerstats_gw", gameweek=1)
        else:
            path = self.workspace_root / layout.get_file_path("playerstats")
        if not path.exists():
            raise FileNotFoundError(f"Playerstats file not found: {path}")
        return pd.read_csv(path)

    def _build_mapping_table(self, season: str) -> Dict[int, int]:
        name_to_canonical = self._load_players_canonical(season)
        playerstats_df = self._load_season_playerstats(season)
        season_to_canonical: Dict[int, int] = {}
        if "web_name" in playerstats_df.columns:
            for _, row in playerstats_df.iterrows():
                sid = row["id"]
                wn = row["web_name"]
                if wn in name_to_canonical:
                    season_to_canonical[sid] = name_to_canonical[wn]
                else:
                    logger.warning(f"Player {wn} (ID {sid}) not in players.csv for {season}")
        return season_to_canonical

    def _save_mapping(self, season: str, mapping: Dict[int, int]) -> None:
        out = self.id_maps_dir / f"{season.replace('-', '_')}_id_to_canonical.json"
        data = {
            "season": season,
            "season_to_canonical": {str(k): int(v) for k, v in mapping.items()},
            "canonical_to_season": {str(v): int(k) for k, v in mapping.items()},
        }
        out.write_text(json.dumps(data, indent=2))

    def _load_mapping(self, season: str) -> None:
        if season in self._season_to_canonical:
            return
        map_file = self.id_maps_dir / f"{season.replace('-', '_')}_id_to_canonical.json"
        if map_file.exists():
            raw = json.loads(map_file.read_text())
            self._season_to_canonical[season] = {int(k): v for k, v in raw["season_to_canonical"].items()}
            self._canonical_to_season[season] = {int(k): v for k, v in raw["canonical_to_season"].items()}
        else:
            s2c = self._build_mapping_table(season)
            c2s = {v: k for k, v in s2c.items()}
            self._season_to_canonical[season] = s2c
            self._canonical_to_season[season] = c2s
            self._save_mapping(season, s2c)

    def to_canonical(self, season: str, ids: List[int]) -> List[Optional[int]]:
        self._load_mapping(season)
        m = self._season_to_canonical[season]
        return [m.get(i) for i in ids]

    def to_season(self, canonical_ids: List[int], target_season: str) -> List[Optional[int]]:
        self._load_mapping(target_season)
        m = self._canonical_to_season[target_season]
        return [m.get(i) for i in canonical_ids]


# ---------------------------------------------------------------------------
# Nickname / alias resolver  (from fpl-video-repurposer/build_fpl_kb.py)
# ---------------------------------------------------------------------------

# SOURCE: fpl-video-repurposer/build_fpl_kb.py::KNOWN_NICKNAMES (lines 73-100)
KNOWN_NICKNAMES: Dict[str, List[str]] = {
    "Salah":       ["Mo", "el Salah", "el Faraón"],
    "Haaland":     ["Erling", "el Vikingo", "el Haaland"],
    "De Bruyne":   ["KDB", "el De Bruyne"],
    "Palmer":      ["el Palmer", "Cole"],
    "Saka":        ["el Saka", "Bukayo"],
    "Son":         ["Sonny", "el Son", "Heung-Min"],
    "Mbappé":      ["Kylian", "el Mbappé"],
    "Foden":       ["Phil", "el Foden"],
    "Trippier":    ["el Trippier", "Kieran"],
    "Alexander-Arnold": ["TAA", "el Alexander-Arnold", "Trent"],
    "Rashford":    ["el Rashford", "Marcus"],
    "Martinelli":  ["el Martinelli", "Gabi"],
    "Watkins":     ["el Watkins", "Ollie"],
    "Gordon":      ["el Gordon", "Anthony"],
    "Isak":        ["el Isak", "Alexander"],
}

# SOURCE: fpl-video-repurposer/build_fpl_kb.py::SPANISH_PORTUGUESE_PATTERNS (lines 62-70)
SPANISH_PORTUGUESE_GIVEN_NAMES: set[str] = {
    "Pedro", "Diogo", "Bruno", "Bernardo", "Matheus", "João", "Joao",
    "Diego", "Luis", "Carlos", "Fernando", "Marco", "Marcos", "Pablo",
    "Raul", "Sergio", "Álvaro", "Alvaro", "Alejandro", "Adrián",
    "Adrian", "Miguel", "Antonio", "Emiliano", "Leandro", "Mateo",
    "Rodrigo", "Thiago", "Lucas", "Gabriel", "Rafael", "Renato",
    "Fabio", "Nuno", "Rúben", "Ruben", "Gonçalo", "Goncalo",
    "Julio", "Eduardo", "Manuel",
}


def resolve_nickname(alias: str, players: List[Dict]) -> Optional[Dict]:
    """Resolve a Spanish community nickname to a canonical player dict.

    SOURCE: fpl-video-repurposer/build_fpl_kb.py + correct_transcript.py logic

    Args:
        alias:   A nickname or partial name (e.g. "el Vikingo", "Mo", "KDB")
        players: List of player dicts (from get_players() or master_squad.json)

    Returns:
        The best-matching player dict, or None if unresolved.
    """
    alias_lower = alias.lower().lstrip("el ").strip()

    # Direct match on known nicknames
    for web_name, aliases in KNOWN_NICKNAMES.items():
        if alias.strip() in aliases or alias_lower in [a.lower() for a in aliases]:
            for p in players:
                if p.get("web_name", "").lower() == web_name.lower():
                    return p

    # Fallback: fuzzy match on web_name
    for p in players:
        if alias_lower in p.get("web_name", "").lower():
            return p

    return None


def build_name_lookup(players: List[Dict]) -> Dict[str, Dict]:
    """Build a mapping of all known names/aliases → player dict.

    Useful for fast transcript correction.

    SOURCE: fpl-video-repurposer/build_fpl_kb.py::build_phonetic_map (inferred)
    """
    lookup: Dict[str, Dict] = {}
    for player in players:
        web_name = player.get("web_name", "")
        first = player.get("first_name", "")
        second = player.get("second_name", "")
        lookup[web_name.lower()] = player
        if first:
            lookup[first.lower()] = player
        if second:
            lookup[second.lower()] = player

    for web_name, aliases in KNOWN_NICKNAMES.items():
        matched = next((p for p in players if p.get("web_name", "").lower() == web_name.lower()), None)
        if matched:
            for alias in aliases:
                lookup[alias.lower()] = matched

    return lookup


