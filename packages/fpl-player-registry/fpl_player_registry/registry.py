"""
fpl_player_registry.registry
==============================
Bootstrap-based canonical player identity registry.

Input:  player dicts from fpl_api_client.get_players()
        team dicts   from fpl_api_client.get_teams()

Output: PlayerRegistry — an in-memory lookup store with:
    - lookup_by_id(player_id)       → exact FPL element id
    - lookup_by_web_name(web_name)  → exact, case-insensitive; None if ambiguous
    - lookup_by_exact_name(query)   → first_name / second_name / web_name match
    - lookup_by_alias(alias)        → KNOWN_NICKNAMES table + "el X" prefix strip

Phase 1d intentionally excludes:
    - SeasonIdMapper  (needs CSV files — Phase 2)
    - Broad fuzzy matching (Phase 2+)
    - Consumer project integration

Source: fpl-platform/packages/fpl-player-registry/python/player_registry.py
        (reference; do not modify)
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .nicknames import KNOWN_NICKNAMES


# Characters not decomposed by NFKD that still need ASCII equivalents.
# Most accented letters (é, ü, ñ, etc.) are handled by NFKD + strip-combining,
# but these standalone letters require explicit mapping.
_SPECIAL_CHAR_MAP: dict[int, str] = str.maketrans({
    ord("ø"): "o",   # Ødegaard → Odegaard
    ord("Ø"): "o",
    ord("æ"): "ae",  # less common in football; keeps intent clear
    ord("Æ"): "ae",
    ord("ß"): "ss",  # German eszett; rare but safe
})


def _fold(s: str) -> str:
    """Lowercase, map standalone special letters, then strip combining diacritics.

    Two-pass approach handles both types of special characters:
    1. Standalone special letters (ø→o, æ→ae, ñ→n, etc.) via explicit map
    2. Precomposed characters that NFKD decomposes (é→e, ü→u, etc.)

    This allows "Odegaard" to match "Ødegaard", "Mbappe" to match "Mbappé",
    and similar queries from users who can't type special characters.
    """
    lowered = s.lower().translate(_SPECIAL_CHAR_MAP)
    return "".join(
        c for c in unicodedata.normalize("NFKD", lowered)
        if not unicodedata.combining(c)
    )


# ---------------------------------------------------------------------------
# PlayerRecord — canonical identity for one player
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerRecord:
    """Canonical player identity record, enriched with team metadata.

    Constructed by ``build_registry()`` from bootstrap player + team dicts.
    All fields come directly from the bootstrap response; no derived values
    are added except ``team_name`` and ``team_short_name`` (joined from teams).

    Fields
    ------
    id                    FPL element id (stable within a season)
    first_name            First name from bootstrap
    second_name           Surname from bootstrap
    web_name              Display name used on the FPL site
    team_id               Team id (bootstrap elements.team)
    team_name             Full team name (joined from bootstrap teams)
    team_short_name       Three-letter abbreviation (joined from bootstrap teams)
    element_type          Position code: 1=GKP 2=DEF 3=MID 4=FWD
    status                Availability: 'a'=available 'd'=doubt 'i'=injured
                          's'=suspended 'u'=unavailable
    now_cost              Current cost in tenths of £ (e.g. 145 = £14.5m)
    selected_by_percent   Ownership string (e.g. "52.3")
    """

    id: int
    first_name: str
    second_name: str
    web_name: str
    team_id: int
    team_name: str
    team_short_name: str
    element_type: int
    status: str
    now_cost: int | None = None
    selected_by_percent: str | None = None


# ---------------------------------------------------------------------------
# PlayerRegistry
# ---------------------------------------------------------------------------

class PlayerRegistry:
    """In-memory lookup store built from FPL bootstrap data.

    Build with ``build_registry(players, teams)`` — do not instantiate
    directly.

    All lookups are O(1) (dict-backed) and case-insensitive for string keys.

    Duplicate web_name handling
    ---------------------------
    If two players share the same web_name (e.g. two "Johnson" entries),
    ``lookup_by_web_name`` returns ``None`` (ambiguous).  The duplicate pair
    is recorded in ``self.ambiguous_web_names`` for inspection.
    ``lookup_by_id`` and ``lookup_by_exact_name`` are unaffected.
    """

    def __init__(
        self,
        records: list[PlayerRecord],
        teams: list[dict[str, Any]],
    ) -> None:
        self._records: list[PlayerRecord] = records

        # Primary index — always unambiguous
        self._by_id: dict[int, PlayerRecord] = {r.id: r for r in records}

        # Teams index for get_team()
        self._teams_by_id: dict[int, dict[str, Any]] = {
            t["id"]: t for t in teams
        }

        # web_name index — may be ambiguous
        self._by_web_name_raw: dict[str, list[PlayerRecord]] = {}
        for r in records:
            key = r.web_name.lower()
            self._by_web_name_raw.setdefault(key, []).append(r)

        self.ambiguous_web_names: set[str] = {
            key for key, recs in self._by_web_name_raw.items() if len(recs) > 1
        }

        # Folded (diacritic-stripped) web_name index for accent-insensitive
        # lookups — "Odegaard" → "Ødegaard", "Mbappe" → "Mbappé", etc.
        # Highest-ownership player wins when folded forms collide.
        self._by_web_name_folded: dict[str, PlayerRecord] = {}
        for r in records:
            key = _fold(r.web_name)
            existing = self._by_web_name_folded.get(key)
            if existing is None:
                self._by_web_name_folded[key] = r
            else:
                try:
                    if float(r.selected_by_percent or 0) > float(existing.selected_by_percent or 0):
                        self._by_web_name_folded[key] = r
                except (TypeError, ValueError):
                    pass

        # first_name index (last-writer wins for duplicates; helper only)
        self._by_first_name: dict[str, PlayerRecord] = {
            r.first_name.lower(): r for r in records if r.first_name
        }

        # second_name index — when multiple players share a surname, keep the
        # highest-ownership player so ambiguous surnames resolve to the most
        # prominent player.
        # Also index on the *last word* of second_name to handle compound
        # surnames (e.g. "Borges Fernandes" → keyed under both
        # "borges fernandes" AND "fernandes").  This makes "Fernandes" find
        # Bruno Fernandes even though his full second_name is "Borges Fernandes".
        self._by_second_name: dict[str, PlayerRecord] = {}
        self._by_second_name_folded: dict[str, PlayerRecord] = {}
        for r in records:
            if not r.second_name:
                continue
            # Index the full second_name and every individual word.
            # This handles compound surnames from any naming convention:
            # "Borges Fernandes" → "fernandes" (last, Portuguese/Brazilian)
            # "Núñez Ribeiro"    → "nunez" (first, Spanish)
            words = r.second_name.lower().split()
            keys_to_index: set[str] = {r.second_name.lower()} | set(words)
            for key in keys_to_index:
                existing = self._by_second_name.get(key)
                if existing is None:
                    self._by_second_name[key] = r
                else:
                    try:
                        existing_pct = float(existing.selected_by_percent or 0)
                        new_pct = float(r.selected_by_percent or 0)
                    except (TypeError, ValueError):
                        existing_pct, new_pct = 0.0, 0.0
                    if new_pct > existing_pct:
                        self._by_second_name[key] = r
                # Also index folded form for diacritic-insensitive lookup
                folded_key = _fold(key)
                existing_f = self._by_second_name_folded.get(folded_key)
                if existing_f is None:
                    self._by_second_name_folded[folded_key] = r
                else:
                    try:
                        if float(r.selected_by_percent or 0) > float(existing_f.selected_by_percent or 0):
                            self._by_second_name_folded[folded_key] = r
                    except (TypeError, ValueError):
                        pass

        # Alias index from KNOWN_NICKNAMES
        # Falls back to second_name lookup when web_name key doesn't match the
        # live FPL web_name (e.g. KNOWN_NICKNAMES["Salah"] still resolves even
        # after FPL renamed the player to "M.Salah").
        self._by_alias: dict[str, PlayerRecord] = {}
        for web_name, aliases in KNOWN_NICKNAMES.items():
            matched = next(
                (r for r in records if r.web_name.lower() == web_name.lower()),
                None,
            )
            if matched is None:
                # Fallback: look up by second_name or first_name
                matched = (
                    self._by_second_name.get(web_name.lower())
                    or self._by_first_name.get(web_name.lower())
                )
            if matched is None:
                continue
            for alias in aliases:
                self._by_alias[alias.lower()] = matched
                # Also index with "el " prefix stripped
                stripped = alias.lower().lstrip("el ").strip()
                if stripped and stripped != alias.lower():
                    self._by_alias.setdefault(stripped, matched)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def lookup_by_id(self, player_id: int) -> PlayerRecord | None:
        """Return the PlayerRecord for *player_id*, or ``None`` if not found."""
        return self._by_id.get(player_id)

    def lookup_by_web_name(self, web_name: str) -> PlayerRecord | None:
        """Return the PlayerRecord whose web_name matches *web_name* exactly.

        Match is case-insensitive and diacritic-insensitive (e.g. "Odegaard"
        matches "Ødegaard").  Returns ``None`` if:
        - no player has that web_name, or
        - more than one player shares it (ambiguous — see ``ambiguous_web_names``)
        """
        key = web_name.lower()
        candidates = self._by_web_name_raw.get(key, [])
        if len(candidates) == 1:
            return candidates[0]
        # Diacritic-insensitive fallback — always try the folded index when
        # the exact lookup missed (handles "Odegaard" → "Ødegaard").
        return self._by_web_name_folded.get(_fold(web_name))

    def lookup_by_exact_name(self, query: str) -> PlayerRecord | None:
        """Return a PlayerRecord by checking web_name, first_name, second_name.

        Resolution order (first match wins):
        1. web_name (exact, unambiguous only)
        2. second_name (highest-ownership wins on collision)
        3. first_name
        4. compound "First Last" — split on space and match first + last-surname
        5. folded (diacritic-stripped) variants of 1–4

        Returns ``None`` if no unambiguous match is found.
        """
        q = query.lower()
        qf = _fold(query)

        # 1. web_name (exact)
        candidates = self._by_web_name_raw.get(q, [])
        if len(candidates) == 1:
            return candidates[0]
        # 2. second_name
        if q in self._by_second_name:
            return self._by_second_name[q]
        # 3. first_name
        if q in self._by_first_name:
            return self._by_first_name[q]
        # 4. compound "First Last" — handles "Harry Wilson", "Bruno Fernandes",
        #    "Darwin Nunez".  Uses the _by_second_name index (which already
        #    indexes every word in a compound surname) and verifies first_name.
        parts = q.split()
        if len(parts) == 2:
            fn, sn = parts
            candidate = self._by_second_name.get(sn)
            if candidate and candidate.first_name.lower() == fn:
                return candidate
            # Folded compound (handles "Darwin Nunez" → "Núñez Ribeiro")
            candidate_f = self._by_second_name_folded.get(_fold(sn))
            if candidate_f and _fold(candidate_f.first_name) == _fold(fn):
                return candidate_f
        # 5. Diacritic-insensitive fallback — always try folded indexes when
        #    exact lookups missed (handles "Odegaard" → "Ødegaard", etc.)
        r = self._by_web_name_folded.get(qf)
        if r:
            return r
        r = self._by_second_name_folded.get(qf)
        if r:
            return r
        return None

    def lookup_by_alias(self, alias: str) -> PlayerRecord | None:
        """Resolve a nickname or alias using the KNOWN_NICKNAMES table.

        Handles:
        - Exact alias match (e.g. "KDB" → De Bruyne)
        - "el X" prefix stripping (e.g. "el Vikingo" → Haaland)
        - Case-insensitive comparison

        Does NOT perform fuzzy matching — that is Phase 2+.
        Returns ``None`` if the alias is not recognised.
        """
        a = alias.strip().lower()
        if a in self._by_alias:
            return self._by_alias[a]
        # Strip "el " prefix and retry
        stripped = a.lstrip("el ").strip()
        if stripped and stripped != a:
            return self._by_alias.get(stripped)
        return None

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    def all_players(self) -> list[PlayerRecord]:
        """Return all PlayerRecords in insertion order."""
        return list(self._records)

    def get_team(self, team_id: int) -> dict[str, Any] | None:
        """Return the raw bootstrap team dict for *team_id*, or ``None``."""
        return self._teams_by_id.get(team_id)

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return (
            f"PlayerRegistry("
            f"{len(self._records)} players, "
            f"{len(self._teams_by_id)} teams, "
            f"{len(self.ambiguous_web_names)} ambiguous web_names)"
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_registry(
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
) -> PlayerRegistry:
    """Build a :class:`PlayerRegistry` from bootstrap player and team dicts.

    Parameters
    ----------
    players:
        Output of ``fpl_api_client.get_players()`` (or the equivalent
        ``bootstrap["elements"]`` slice already normalised to platform keys).
    teams:
        Output of ``fpl_api_client.get_teams()`` (or ``bootstrap["teams"]``
        slice normalised to platform keys).

    Returns
    -------
    PlayerRegistry
        Ready to use; all indexes pre-built.
    """
    team_index: dict[int, dict[str, Any]] = {t["id"]: t for t in teams}

    records: list[PlayerRecord] = []
    for p in players:
        tid = p.get("team_id") or p.get("team")  # accept both key forms
        team = team_index.get(tid, {})
        records.append(
            PlayerRecord(
                id=int(p["id"]),
                first_name=str(p.get("first_name") or ""),
                second_name=str(p.get("second_name") or ""),
                web_name=str(p.get("web_name") or ""),
                team_id=int(tid) if tid is not None else 0,
                team_name=str(team.get("name") or ""),
                team_short_name=str(team.get("short_name") or ""),
                element_type=int(p.get("element_type") or 0),
                status=str(p.get("status") or ""),
                now_cost=p.get("now_cost"),
                selected_by_percent=p.get("selected_by_percent"),
            )
        )
    return PlayerRegistry(records, teams)