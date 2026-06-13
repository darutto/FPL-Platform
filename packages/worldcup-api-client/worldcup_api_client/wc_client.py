"""
worldcup_api_client.wc_client
==============================
Resilient httpx client for the FIFA Fantasy World Cup 2026 public feed, with
tiered in-process TTL caching and derived (computed) views.

Why this source
----------------
worldcupapi.com requires a paid key and (as of 2026-06-12) has trials
disabled until the tournament ends. ``https://play.fifa.com/json/fantasy/``
is a free, public, unauthenticated, currently-live S3-hosted JSON feed used
by the official FIFA Fantasy game. It serves three files:

    squads.json   48 national teams: id (1-48), name, group (a-l), abbr,
                   isEliminated.
    players.json  ~1500 players: id, firstName/lastName/knownName, squadId,
                   position (GK/DEF/MID/FWD), price, status, stats.
    rounds.json   8 rounds, each with a ``tournaments`` list (= matches):
                   id, status (scheduled/complete/...), date, venue,
                   home/awaySquadId+Name+Score, home/awayGoalScorersAssists.

Unlike worldcupapi.com (which had one endpoint per concept), this feed only
gives raw data — ``live_scores``, ``fixtures``, ``squad`` rosters are light
transformations, while ``standings``, ``top_scorers`` and ``head_to_head``
are *computed* here from ``rounds.json`` + ``squads.json`` + ``players.json``.

Not available from this source
-------------------------------
``get_lineup`` and ``get_match_stats`` have no backing data (no confirmed
lineups, no possession/shots/cards). Both return a graceful
``{"available": False, "message": ...}`` envelope instead of raising, so the
LLM can tell the user the data isn't available rather than erroring out.

Caching policy
---------------
    squads.json / players.json   semi-static (TTL 5 min) — rosters/prices
                                   change only between rounds.
    rounds.json                   volatile (TTL 20 s) — live scores and
                                   scorer lists update during matches.

Cache keys are the file path (no query params on this feed). The cache is
process-local and size-bounded; entries are evicted lazily on read and
opportunistically on write.

Error envelope
--------------
``WorldCupAPIError`` is raised for transport failures and non-2xx statuses
(after retries). Callers in the tools layer catch this and convert to a
structured ``{"status": "error"}`` tool result.

Confirmed live 2026-06-12: round 1 status "playing", 4/72 group-stage matches
complete.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from .team_ids import UnknownTeamError, resolve_squad_id

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BASE_URL = "https://play.fifa.com/json/fantasy"

_FILES: dict[str, str] = {
    "squads": "squads.json",
    "players": "players.json",
    "rounds": "rounds.json",
}

# Default HTTP settings (mirrors fpl_api_client retry posture)
_DEFAULT_TIMEOUT_S: float = 15.0
_RETRY_ATTEMPTS: int = 3
_RETRY_BACKOFF_S: float = 1.5  # multiplied by attempt number

# ---------------------------------------------------------------------------
# TTL tiers (seconds)
# ---------------------------------------------------------------------------

#: Semi-static data: squads (teams/groups), players (rosters/prices).
TTL_SEMI_STATIC_S: float = 5 * 60
#: Volatile / live data: rounds (live scores, scorers).
TTL_LIVE_S: float = 20.0
#: Kept for backward-compat with callers importing the static tier name.
TTL_STATIC_S: float = TTL_SEMI_STATIC_S

_FILE_TTLS: dict[str, float] = {
    "squads": TTL_SEMI_STATIC_S,
    "players": TTL_SEMI_STATIC_S,
    "rounds": TTL_LIVE_S,
}

#: Hard cap on cached entries (oldest-evicted-first on overflow).
_CACHE_MAX_ENTRIES: int = 256


class WorldCupAPIError(Exception):
    """Raised on transport failure or non-2xx status (after retries)."""


# ---------------------------------------------------------------------------
# In-process TTL cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cache_key(path: str, params: dict[str, Any]) -> str:
    visible = {k: v for k, v in params.items() if k != "key"}
    return path + "?" + "&".join(f"{k}={visible[k]}" for k in sorted(visible))


def _cache_get(key: str) -> Any | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del _cache[key]
            return None
        return value


def _cache_put(key: str, value: Any, ttl_s: float) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            for stale_key in sorted(_cache, key=lambda k: _cache[k][0])[: len(_cache) // 4 + 1]:
                del _cache[stale_key]
        _cache[key] = (time.monotonic() + ttl_s, value)


def clear_cache() -> None:
    """Drop all cached entries. Used by tests and manual refresh hooks."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Low-level fetch helper
# ---------------------------------------------------------------------------

def fetch_json(path: str, params: dict[str, Any] | None = None, *, ttl_s: float,
                timeout_s: float = _DEFAULT_TIMEOUT_S) -> Any:
    """GET ``_BASE_URL + path`` and return parsed JSON, with TTL caching and
    retries on transport errors / 5xx / 429. Raises ``WorldCupAPIError`` on
    failure after retries."""
    params = dict(params or {})
    key = _cache_key(path, params)
    if ttl_s > 0:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    url = _BASE_URL + path
    last_err: str | None = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, params=params, timeout=timeout_s)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                if attempt < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                    continue
                break
            if resp.status_code >= 400:
                raise WorldCupAPIError(f"HTTP {resp.status_code} for {path}")
            payload = resp.json()
            if ttl_s > 0:
                _cache_put(key, payload, ttl_s)
            return payload
        except WorldCupAPIError:
            raise
        except httpx.TimeoutException:
            last_err = "timeout"
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        except ValueError as exc:  # JSON decode failure
            raise WorldCupAPIError(f"invalid JSON from {path}: {exc}") from None
        if attempt < _RETRY_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_S * attempt)

    raise WorldCupAPIError(f"request failed for {path} after {_RETRY_ATTEMPTS} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Raw feed accessors (cached)
# ---------------------------------------------------------------------------

def _get_squads() -> list[dict[str, Any]]:
    return fetch_json("/" + _FILES["squads"], ttl_s=_FILE_TTLS["squads"])


def _get_players() -> list[dict[str, Any]]:
    return fetch_json("/" + _FILES["players"], ttl_s=_FILE_TTLS["players"])


def _get_rounds() -> list[dict[str, Any]]:
    return fetch_json("/" + _FILES["rounds"], ttl_s=_FILE_TTLS["rounds"])


def _player_name(player: dict[str, Any]) -> str:
    known = player.get("knownName")
    if known:
        return known
    return f"{player.get('firstName', '')} {player.get('lastName', '')}".strip()


def _format_match(tournament: dict[str, Any], round_id: int | None = None) -> dict[str, Any]:
    return {
        "match_id": tournament.get("id"),
        "round": round_id,
        "date": tournament.get("date"),
        "venue": tournament.get("venueName"),
        "venue_city": tournament.get("venueCity"),
        "home_team": tournament.get("homeSquadName"),
        "away_team": tournament.get("awaySquadName"),
        "home_score": tournament.get("homeScore"),
        "away_score": tournament.get("awayScore"),
        "status": tournament.get("status"),
        "minute": tournament.get("minutes"),
        "stage": "group_stage",
    }


def _iter_tournaments(rounds: list[dict[str, Any]]):
    for rnd in rounds:
        for tournament in rnd.get("tournaments") or []:
            yield rnd.get("id"), tournament


#: Spanish/alternate position names -> FIFA Fantasy position code.
_POSITION_ALIASES: dict[str, str] = {
    "goalkeeper": "GK", "portero": "GK", "arquero": "GK", "guardameta": "GK",
    "defender": "DEF", "defensa": "DEF", "defensor": "DEF",
    "midfielder": "MID", "centrocampista": "MID", "mediocampista": "MID", "volante": "MID",
    "forward": "FWD", "delantero": "FWD", "striker": "FWD", "atacante": "FWD",
}


def _normalize_position(position: str) -> str:
    return _POSITION_ALIASES.get(position.strip().lower(), position.strip().upper())


# ---------------------------------------------------------------------------
# Endpoint functions
# ---------------------------------------------------------------------------

def get_live_scores() -> Any:
    """All matches currently in play, with scores and minute."""
    matches = [
        _format_match(t, round_id)
        for round_id, t in _iter_tournaments(_get_rounds())
        if t.get("status") not in ("scheduled", "complete")
    ]
    return {"matches": matches}


def get_fixtures(team: str | None = None, date: str | None = None, stage: str | None = None) -> Any:
    """Fixture schedule and results, optionally filtered by ``team``
    (English FIFA name, resolved to ``squadId``) and/or ``date``
    (``YYYY-MM-DD`` prefix match). ``stage`` is accepted for tool-schema
    compatibility but this feed only covers the group stage, so it is
    ignored."""
    team_id = resolve_squad_id(team, _get_squads()) if team else None
    matches = []
    for round_id, t in _iter_tournaments(_get_rounds()):
        if team_id is not None and team_id not in (t.get("homeSquadId"), t.get("awaySquadId")):
            continue
        if date and not str(t.get("date", "")).startswith(date):
            continue
        matches.append(_format_match(t, round_id))
    return {"matches": matches}


def get_squad(team: str) -> Any:
    """Full tournament roster for *team* (English FIFA name)."""
    squads = _get_squads()
    squad_id = resolve_squad_id(team, squads)
    squad = next(s for s in squads if s["id"] == squad_id)
    roster = [
        {"name": _player_name(p), "position": p.get("position"), "price": p.get("price")}
        for p in _get_players()
        if p.get("squadId") == squad_id
    ]
    return {"team": squad["name"], "group": squad["group"].upper(), "players": roster}


def get_lineup(match_id: str | int) -> Any:
    """Not available from this data source — see module docstring."""
    return {
        "match_id": match_id,
        "available": False,
        "message": "No tengo alineaciones confirmadas para este partido: la fuente de datos actual no las incluye.",
    }


def get_standings(group: str | None = None) -> Any:
    """Group standings computed from completed group-stage matches.

    Tie-break order: points, then goal difference, then goals scored, then
    team name (alphabetical, as a deterministic final fallback — head-to-head
    tie-breaks are not computed).
    """
    squads = _get_squads()
    table: dict[int, dict[str, Any]] = {
        s["id"]: {
            "team": s["name"], "group": s["group"], "played": 0, "won": 0,
            "drawn": 0, "lost": 0, "goals_for": 0, "goals_against": 0, "points": 0,
        }
        for s in squads
    }
    for _, t in _iter_tournaments(_get_rounds()):
        if t.get("status") != "complete":
            continue
        home_id, away_id = t.get("homeSquadId"), t.get("awaySquadId")
        home_score, away_score = t.get("homeScore") or 0, t.get("awayScore") or 0
        home, away = table[home_id], table[away_id]
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += home_score
        home["goals_against"] += away_score
        away["goals_for"] += away_score
        away["goals_against"] += home_score
        if home_score > away_score:
            home["won"] += 1
            home["points"] += 3
            away["lost"] += 1
        elif home_score < away_score:
            away["won"] += 1
            away["points"] += 3
            home["lost"] += 1
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1

    def _finalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            row["goal_difference"] = row["goals_for"] - row["goals_against"]
        rows.sort(key=lambda r: (-r["points"], -r["goal_difference"], -r["goals_for"], r["team"]))
        return rows

    if group:
        group_key = group.strip().lower()
        rows = [table[s["id"]] for s in squads if s["group"] == group_key]
        if not rows:
            raise WorldCupAPIError(f"unknown group: {group!r}")
        return {"groups": {group_key.upper(): _finalize(rows)}}

    groups: dict[str, list[dict[str, Any]]] = {}
    for s in squads:
        groups.setdefault(s["group"], []).append(table[s["id"]])
    return {"groups": {g.upper(): _finalize(rows) for g, rows in groups.items()}}


def get_top_scorers() -> Any:
    """Tournament top goalscorers, computed from completed matches'
    goal/assist records."""
    players_by_id = {p["id"]: p for p in _get_players()}
    squads_by_id = {s["id"]: s for s in _get_squads()}
    goals: dict[int, int] = {}
    assists: dict[int, int] = {}
    for _, t in _iter_tournaments(_get_rounds()):
        for side in ("home", "away"):
            for entry in (t.get(f"{side}GoalScorersAssists") or []):
                pid, aid = entry.get("playerId"), entry.get("assistId")
                if pid:
                    goals[pid] = goals.get(pid, 0) + 1
                if aid:
                    assists[aid] = assists.get(aid, 0) + 1

    scorers = []
    for pid, g in goals.items():
        player = players_by_id.get(pid)
        if not player:
            continue
        squad = squads_by_id.get(player.get("squadId"))
        scorers.append({
            "player": _player_name(player),
            "team": squad["name"] if squad else None,
            "goals": g,
            "assists": assists.get(pid, 0),
        })
    scorers.sort(key=lambda r: (-r["goals"], -r["assists"], r["player"]))
    return {"scorers": scorers}


def get_fantasy_top_players(position: str | None = None, team: str | None = None,
                              limit: int = 10) -> Any:
    """FIFA Fantasy points leaderboard: players ranked by ``stats.totalPoints``
    this tournament, optionally filtered by ``position`` (GK/DEF/MID/FWD,
    Spanish names also accepted) and/or ``team`` (English FIFA name)."""
    squads = _get_squads()
    squads_by_id = {s["id"]: s for s in squads}
    pos = _normalize_position(position) if position else None
    team_id = resolve_squad_id(team, squads) if team else None

    rows = []
    for p in _get_players():
        if pos and p.get("position") != pos:
            continue
        if team_id is not None and p.get("squadId") != team_id:
            continue
        squad = squads_by_id.get(p.get("squadId"))
        stats = p.get("stats") or {}
        rows.append({
            "player": _player_name(p),
            "team": squad["name"] if squad else None,
            "position": p.get("position"),
            "total_points": stats.get("totalPoints", 0),
            "avg_points": stats.get("avgPoints", 0),
            "form": stats.get("form", 0),
            "price": p.get("price"),
        })
    rows.sort(key=lambda r: (-r["total_points"], r["player"]))
    limit = max(1, min(int(limit) if limit else 10, 50))
    return {"players": rows[:limit]}


def get_head_to_head(team_a: str, team_b: str) -> Any:
    """Matches between two national teams within this World Cup (this feed
    has no data from prior tournaments)."""
    squads = _get_squads()
    id_a = resolve_squad_id(team_a, squads)
    id_b = resolve_squad_id(team_b, squads)
    matches = [
        _format_match(t, round_id)
        for round_id, t in _iter_tournaments(_get_rounds())
        if {t.get("homeSquadId"), t.get("awaySquadId")} == {id_a, id_b}
    ]
    return {
        "matches": matches,
        "note": "Solo se incluyen partidos de esta Copa del Mundo; no hay datos de enfrentamientos anteriores.",
    }


def get_match_stats(match_id: str | int) -> Any:
    """Not available from this data source — see module docstring."""
    return {
        "match_id": match_id,
        "available": False,
        "message": "No tengo estadísticas de partido (posesión, tiros, tarjetas): la fuente de datos actual no las incluye.",
    }


__all__ = [
    "WorldCupAPIError",
    "UnknownTeamError",
    "TTL_STATIC_S",
    "TTL_SEMI_STATIC_S",
    "TTL_LIVE_S",
    "clear_cache",
    "fetch_json",
    "get_live_scores",
    "get_fixtures",
    "get_squad",
    "get_lineup",
    "get_standings",
    "get_top_scorers",
    "get_fantasy_top_players",
    "get_head_to_head",
    "get_match_stats",
]
