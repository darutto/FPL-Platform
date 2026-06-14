"""
worldcup_api_client.wc2022_data
================================
Read-only loader/aggregator for the cached World Cup 2022 dataset
(fetched via ``scripts/fetch_wc2022_dataset.py`` from api-football.com into
``data/wc2022/``).

Why this exists
----------------
The live FIFA Fantasy feed (``wc_client.py``) carries no per-player match
detail beyond aggregate fantasy points, and no historical (2022) data at
all. This module exposes two things from the cached WC2022 dataset:

* ``get_player_wc2022_summary`` — per-player tournament aggregates
  (appearances, minutes, goals, assists, cards, GK saves, key passes,
  average match rating) for players who also featured in 2022, as
  supplementary historical context for ``/jugador`` and ``/comparar``.
* ``get_wc2022_results`` — the 64 match results themselves, optionally
  filtered by team and/or stage.

Static dataset: 64 matches, ~3200 player-match rows (only rows with
minutes > 0 are aggregated), loaded once and cached in-process.

Name resolution is accent-insensitive + token/substring matching, sibling
of ``player_ids.resolve_player``, since API-Football names ("Lionel Messi")
differ in form from FIFA Fantasy's ``knownName``/``lastName`` fields.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "wc2022"

#: API-Football single-letter position codes -> FIFA-Fantasy-style codes,
#: so locale_es.POSITION_ES (which knows "gk"/"def"/"mid"/"fwd") applies.
_POSITION_MAP: dict[str, str] = {"G": "gk", "D": "def", "M": "mid", "F": "fwd"}

#: API-Football "league.round" strings -> the stage enum used by
#: get_fixtures (so locale_es.STAGE_ES applies the same labels for WC2022
#: results as for live WC2026 fixtures).
_ROUND_STAGE_MAP: dict[str, str] = {
    "group stage - 1": "group_stage",
    "group stage - 2": "group_stage",
    "group stage - 3": "group_stage",
    "round of 16": "round_of_16",
    "quarter-finals": "quarter_final",
    "semi-finals": "semi_final",
    "3rd place final": "third_place",
    "final": "final",
}

_cache: dict[str, dict[str, Any]] | None = None
_fixtures_cache: list[dict[str, Any]] | None = None


class WC2022DataError(Exception):
    """Raised when the cached WC2022 dataset is missing on disk."""


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.strip().lower()


def _load() -> dict[str, dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache

    fixture_players_dir = _DATA_DIR / "fixture_players"
    if not fixture_players_dir.exists():
        raise WC2022DataError(
            f"WC2022 dataset not found at {_DATA_DIR}. "
            "Run scripts/fetch_wc2022_dataset.py first."
        )

    players: dict[str, dict[str, Any]] = {}

    for fp_file in sorted(fixture_players_dir.glob("*.json")):
        for team_block in json.loads(fp_file.read_text(encoding="utf-8")):
            team_name = team_block["team"]["name"]
            for p in team_block["players"]:
                stats = p["statistics"][0]
                games = stats["games"]
                minutes = games.get("minutes") or 0
                if minutes <= 0:
                    continue  # did not play

                name = p["player"]["name"]
                key = _normalize(name)
                agg = players.setdefault(key, {
                    "name": name,
                    "team": team_name,
                    "appearances": 0,
                    "minutes": 0,
                    "goals": 0,
                    "assists": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "saves": 0,
                    "key_passes": 0,
                    "_rating_sum": 0.0,
                    "_rating_count": 0,
                    "_positions": [],
                })
                agg["appearances"] += 1
                agg["minutes"] += minutes
                agg["goals"] += stats["goals"].get("total") or 0
                agg["assists"] += stats["goals"].get("assists") or 0
                agg["yellow_cards"] += stats["cards"].get("yellow") or 0
                agg["red_cards"] += stats["cards"].get("red") or 0
                agg["saves"] += stats["goals"].get("saves") or 0
                agg["key_passes"] += stats["passes"].get("key") or 0

                rating = games.get("rating")
                if rating:
                    agg["_rating_sum"] += float(rating)
                    agg["_rating_count"] += 1

                pos = games.get("position")
                if pos:
                    agg["_positions"].append(pos)

    for agg in players.values():
        if agg["_rating_count"]:
            agg["avg_rating"] = round(agg["_rating_sum"] / agg["_rating_count"], 2)
        else:
            agg["avg_rating"] = None
        if agg["_positions"]:
            most_common = max(set(agg["_positions"]), key=agg["_positions"].count)
            agg["position"] = _POSITION_MAP.get(most_common, most_common)
        else:
            agg["position"] = None
        del agg["_rating_sum"], agg["_rating_count"], agg["_positions"]

    _cache = players
    return players


def get_player_wc2022_summary(name: str) -> dict[str, Any]:
    """Aggregate a player's WC2022 tournament stats by free-text name.

    Returns ``{"status": "ok", "season": 2022, ...}`` on a match, or
    ``{"status": "not_found", "query": name}`` if no WC2022 participant
    matches (most players, since only ~590 of ~1500 2026 squad members
    also played in 2022).
    """
    players = _load()
    key = _normalize(name)
    if not key:
        return {"status": "not_found", "query": name}

    # Pass 1: exact normalized full-name match.
    if key in players:
        return {"status": "ok", "season": 2022, **players[key]}

    # Pass 2: shared whitespace-token of length >= 3 (e.g. "Messi" vs
    # "Lionel Messi").
    key_tokens = {t for t in key.split() if len(t) >= 3}
    if key_tokens:
        for pkey, agg in players.items():
            if key_tokens & set(pkey.split()):
                return {"status": "ok", "season": 2022, **agg}

    # Pass 3: query is a substring of a candidate name, for queries >= 4 chars.
    if len(key) >= 4:
        for pkey, agg in players.items():
            if key in pkey:
                return {"status": "ok", "season": 2022, **agg}

    return {"status": "not_found", "query": name}


def _load_fixtures() -> list[dict[str, Any]]:
    global _fixtures_cache
    if _fixtures_cache is not None:
        return _fixtures_cache

    fixtures_file = _DATA_DIR / "fixtures.json"
    if not fixtures_file.exists():
        raise WC2022DataError(
            f"WC2022 dataset not found at {_DATA_DIR}. "
            "Run scripts/fetch_wc2022_dataset.py first."
        )

    raw = json.loads(fixtures_file.read_text(encoding="utf-8"))
    matches: list[dict[str, Any]] = []
    for f in raw:
        round_name = f["league"]["round"]
        stage = _ROUND_STAGE_MAP.get(_normalize(round_name), "group_stage")
        penalty = (f["score"] or {}).get("penalty") or {}
        matches.append({
            "match_id": f["fixture"]["id"],
            "round": None,
            "date": (f["fixture"].get("date") or "")[:10] or None,
            "venue": (f["fixture"].get("venue") or {}).get("name"),
            "venue_city": (f["fixture"].get("venue") or {}).get("city"),
            "home_team": f["teams"]["home"]["name"],
            "away_team": f["teams"]["away"]["name"],
            "home_score": f["goals"].get("home"),
            "away_score": f["goals"].get("away"),
            "penalty_home": penalty.get("home"),
            "penalty_away": penalty.get("away"),
            "status": "completed",
            "minute": None,
            "stage": stage,
        })

    matches.sort(key=lambda m: m["date"] or "")
    _fixtures_cache = matches
    return _fixtures_cache


def get_wc2022_results(team: str | None = None, stage: str | None = None) -> dict[str, Any]:
    """WC2022 (Qatar) match results, optionally filtered by ``team`` (any
    spelling/accents) and/or ``stage`` (enum: group_stage, round_of_16,
    quarter_final, semi_final, third_place, final).

    Always returns ``{"status": "ok", "season": 2022, "matches": [...],
    "count": n}`` — an empty ``matches`` list (count 0) means the filters
    matched nothing (e.g. a team that did not qualify for WC2022), which is
    expected, not an error.
    """
    matches = _load_fixtures()

    if team:
        key = _normalize(team)
        matches = [
            m for m in matches
            if key in _normalize(m["home_team"]) or key in _normalize(m["away_team"])
            or _normalize(m["home_team"]) in key or _normalize(m["away_team"]) in key
        ]

    if stage:
        stage_key = stage.strip().lower()
        matches = [m for m in matches if m["stage"] == stage_key]

    return {"status": "ok", "season": 2022, "matches": matches, "count": len(matches)}
