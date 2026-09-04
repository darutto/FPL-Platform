"""
fpl_grounded_assistant.get_player_season_points
=================================================
Total FPL points (and aggregated box-score stats) for one named player across
a full season — past or present.

Closes the gap where a user asks "how many points did Palmer score in season
25-26" (or any other completed season) and the app has no tool that can
answer it. Every other player tool either reads the live/current-season
bootstrap (``get_player_summary``, ``get_player_form``) or answers a
per-gameweek "top scorer" question for a past season
(``get_historical_gameweek_top_scorer``) — none of them sum one named
player's points across a whole season.

Data source
-----------
Reads ``player_gw_stats.parquet`` + ``players.parquet`` + ``teams.parquet``
from ``packages/fpl-historical``'s per-season owned store
(``fpl_historical.paths.merged_parquet_dir(season)``) — the same store
``get_historical_gameweek_top_scorer`` reads. Covers every season captured
live from the FPL API plus every vaastav-imported season (2016-2017 through
the most recently completed one).

Season totals are computed by summing ``player_gw_stats.parquet`` rows for
the resolved player, rather than trusting ``players.parquet``'s own
``total_points`` column — mirroring ``get_historical_gameweek_top_scorer``'s
established fallback pattern, since older vaastav-imported seasons don't
reliably carry a season-end snapshot on ``players.parquet`` but always carry
complete per-GW rows on ``player_gw_stats.parquet``.

Player identity is resolved against *that season's own* ``players.parquet``
snapshot, not the live bootstrap — FPL element ids are not stable across
seasons (a player transferred, renumbered, or retired won't be in the
current bootstrap at all).

Cross-package import uses the same sys.path shim as
``historical_gameweek_top_scorer.py`` / ``owned_store_fallback.py``.

Registration
------------
Registers ``get_player_season_points`` in ``TOOL_REGISTRY`` as a side-effect
of import. ``__init__.py`` must import this module.
"""
from __future__ import annotations

import os
import sys
import unicodedata
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

# ---------------------------------------------------------------------------
# sys.path shim — mirror historical_gameweek_top_scorer.py's pattern
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))        # fpl_grounded_assistant/
_PKG = os.path.dirname(_HERE)                              # fpl-grounded-assistant/
_PKGS = os.path.dirname(_PKG)                               # packages/
_FPL_HISTORICAL = os.path.join(_PKGS, "fpl-historical")

if _FPL_HISTORICAL not in sys.path:
    sys.path.insert(0, _FPL_HISTORICAL)

try:
    from fpl_historical.paths import CURRENT_SEASON, historical_root, merged_parquet_dir
    _FPL_HISTORICAL_AVAILABLE = True
except ImportError:
    _FPL_HISTORICAL_AVAILABLE = False
    CURRENT_SEASON = "2025-2026"

# Re-use the season-string parser — single source of truth (avoids a second,
# possibly-drifting regex for "2025-26" / "25/26" / "2025" style input).
from fpl_grounded_assistant.historical_gameweek_top_scorer import (  # noqa: E402
    _normalize_season,
    _list_available_seasons,
)

_POSITION_MAP: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

#: Sentinel values (case-insensitive, accent-insensitive) accepted for
#: ``season`` meaning "the season before the current/most-recently-completed
#: one" — used by the router for phrasings like "temporada pasada" /
#: "last season" that don't carry an explicit year.
_PREVIOUS_SEASON_SENTINELS: frozenset[str] = frozenset({
    "previous", "last", "pasada", "anterior", "ultima", "última",
})

_MAX_AMBIGUOUS_CANDIDATES: int = 5


# ---------------------------------------------------------------------------
# Season resolution
# ---------------------------------------------------------------------------

def _previous_season(season: str) -> str | None:
    """Return the season immediately before *season* (``YYYY-YYYY`` form).

    ``"2025-2026"`` -> ``"2024-2025"``. Returns ``None`` if *season* is not
    a well-formed ``YYYY-YYYY`` string.
    """
    parts = season.split("-")
    if len(parts) != 2:
        return None
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return f"{start - 1}-{end - 1}"


def _resolve_season_arg(season: str) -> str | None:
    """Resolve a router/caller-supplied ``season`` argument to ``YYYY-YYYY``.

    Accepts an explicit season string in any format ``_normalize_season``
    understands, or one of ``_PREVIOUS_SEASON_SENTINELS`` meaning "the
    season before the current one". Returns ``None`` on failure to parse.
    """
    raw = (season or "").strip()
    normalized_sentinel = "".join(
        c for c in unicodedata.normalize("NFKD", raw.lower())
        if not unicodedata.combining(c)
    )
    if normalized_sentinel in _PREVIOUS_SEASON_SENTINELS:
        return _previous_season(CURRENT_SEASON)
    return _normalize_season(raw)


# ---------------------------------------------------------------------------
# Player name normalisation / matching (same algorithm family as
# find_players._normalize — accent/case-insensitive).
# ---------------------------------------------------------------------------

def _normalize_name(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower().strip()


def _safe_team_id(value: "Any") -> int:
    """Team id as int, or -1 when the parquet cell is missing/NaN."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _resolve_player_in_season(
    player_query: str,
    players_df: "Any",
    team_short_by_id: "dict[int, str] | None" = None,
) -> dict[str, Any]:
    """Resolve *player_query* against a season's own ``players.parquet``.

    Same exact/prefix/substring three-rank algorithm used throughout the
    package (see ``find_players``), restricted to real player positions
    (excludes FPL's element_type=5 "Assistant Manager" rows). Ties within a
    rank are broken by ``total_points`` (that season's own snapshot column)
    descending — good enough for tie-breaking even where that column is
    stale; it never affects a resolution with a single unambiguous match.

    Returns a dict shaped like the rest of the package's resolution helpers:
    ``{"status": "ok", "player_id", "web_name", "team_short", "position"}``
    or ``{"status": "ambiguous"/"not_found", ...}``.
    """
    normalized_query = _normalize_name(player_query.strip())
    team_shorts = team_short_by_id or {}

    real_players = players_df[players_df["element_type"].isin(_POSITION_MAP.keys())]

    rank_bucket: dict[int, int] = {}
    for rec in real_players.to_dict(orient="records"):
        player_id = int(rec["player_id"])
        first = _normalize_name(str(rec.get("first_name") or ""))
        second = _normalize_name(str(rec.get("second_name") or ""))
        web = _normalize_name(str(rec.get("web_name") or ""))
        composite = f"{first} {second} {web}"

        if normalized_query in (first, second, web):
            rank_bucket[player_id] = 0
            continue
        if first.startswith(normalized_query) or second.startswith(normalized_query) or web.startswith(normalized_query):
            rank_bucket[player_id] = 1
            continue
        if normalized_query in composite:
            rank_bucket[player_id] = 2

    by_id = real_players.set_index("player_id")

    def _at_rank(target_rank: int) -> list[int]:
        ids = [pid for pid, r in rank_bucket.items() if r == target_rank]
        ids.sort(key=lambda pid: -int(by_id.loc[pid].get("total_points", 0) or 0))
        return ids

    def _candidate(pid: int) -> dict[str, Any]:
        row = by_id.loc[pid]
        return {
            "id": pid,
            "web_name": str(row.get("web_name", "?")),
            # team_short completes the shared candidate shape — the chip label
            # is "{web_name} ({team_short})", so omitting it renders "Salah ()".
            # The chip label is "{web_name} ({team_short})", so a candidate
            # without it renders as "Salah ()".  players.parquet only carries
            # team_id, hence the caller-supplied mapping.
            "team_short": team_shorts.get(_safe_team_id(row.get("team_id")), ""),
            "position": _POSITION_MAP.get(int(row["element_type"]), "?"),
        }

    def _ok(pid: int) -> dict[str, Any]:
        row = by_id.loc[pid]
        return {
            "status": "ok",
            "player_id": pid,
            "web_name": str(row.get("web_name", "?")),
            "position": _POSITION_MAP.get(int(row["element_type"]), "?"),
            "team_id": row.get("team_id"),
        }

    def _ambiguous(ids: list[int]) -> dict[str, Any]:
        return {
            "status": "ambiguous",
            "query": normalized_query,
            "candidates": [_candidate(pid) for pid in ids[:_MAX_AMBIGUOUS_CANDIDATES]],
            "message": f"Multiple players match '{normalized_query}'. Please specify.",
        }

    exact = _at_rank(0)
    if len(exact) == 1:
        return _ok(exact[0])
    if len(exact) > 1:
        return _ambiguous(exact)

    prefix = _at_rank(1)
    if len(prefix) == 1:
        return _ok(prefix[0])
    if len(prefix) > 1:
        return _ambiguous(prefix)

    substr = _at_rank(2)
    if substr:
        return _ambiguous(substr)

    return {
        "status": "not_found",
        "query": normalized_query,
        "message": f"No player matching '{normalized_query}'.",
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_player_season_points(query: str, season: str) -> dict[str, Any]:
    """Total FPL points for one player across one full season.

    Args:
        query: Player name (case-insensitive, accent-insensitive).
        season: Season identifier — ``"2025-2026"``, ``"2025-26"``,
            ``"25/26"``, or the literal ``"previous"`` for the season
            before the current/most-recently-completed one.

    Returns:
        # Success:
        {
            "status": "ok",
            "season": "2024-2025",
            "player": {"id": <int>, "web_name": <str>, "team_short": <str>, "position": <str>},
            "summary": {
                "total_points": <int>,
                "gws_played": <int>,
                "total_minutes": <int>,
                "total_goals": <int>,
                "total_assists": <int>,
                "total_clean_sheets": <int>,
                "total_bonus": <int>,
                "points_per_game": <float>,
            },
        }
        # Failure:
        {"status": "invalid_argument" | "ambiguous" | "not_found" | "error", "code": <str>, "message": <str>}
    """
    if not isinstance(query, str) or not query.strip():
        return {
            "status": "invalid_argument",
            "code": "invalid_argument",
            "message": "query must be a non-empty player name.",
        }

    if not _FPL_HISTORICAL_AVAILABLE:
        return {
            "status": "error",
            "code": "historical_unavailable",
            "message": "fpl-historical package is not available on this deployment.",
        }

    canonical_season = _resolve_season_arg(season) if season else None
    if canonical_season is None:
        return {
            "status": "invalid_argument",
            "code": "unparseable_season",
            "message": (
                f"Could not parse season '{season}'. Use a format like "
                "'2025-2026', '2025-26', or 'previous' for last season."
            ),
        }

    merged_dir = merged_parquet_dir(canonical_season)
    if not merged_dir.exists():
        available = _list_available_seasons()
        return {
            "status": "not_found",
            "code": "season_not_found",
            "message": (
                f"No historical data for season '{canonical_season}'. "
                f"Available seasons: {', '.join(available) if available else 'none'}."
            ),
        }

    try:
        import pandas as pd
    except ImportError as exc:
        return {
            "status": "error",
            "code": "pandas_unavailable",
            "message": f"pandas not available: {exc}",
        }

    try:
        players_df = pd.read_parquet(merged_dir / "players.parquet")
        teams_df = pd.read_parquet(merged_dir / "teams.parquet")
        gw_stats_df = pd.read_parquet(merged_dir / "player_gw_stats.parquet")
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "code": "parquet_read_failed",
            "message": f"Failed to read historical parquet data: {exc}",
        }

    team_short_by_id: dict[int, str] = dict(zip(teams_df["team_id"], teams_df["short_name"]))
    resolution = _resolve_player_in_season(query, players_df, team_short_by_id)
    if resolution["status"] != "ok":
        return resolution

    player_id = resolution["player_id"]
    team_id = resolution.get("team_id")
    team_short = (
        team_short_by_id.get(int(team_id), "?")
        if team_id is not None and pd.notna(team_id)
        else "?"
    )

    player_rows = gw_stats_df[gw_stats_df["player_id"] == player_id]

    def _col_sum(col: str) -> int:
        if col not in player_rows.columns:
            return 0
        return int(pd.to_numeric(player_rows[col], errors="coerce").fillna(0).sum())

    total_points = _col_sum("total_points")
    total_minutes = _col_sum("minutes")
    total_goals = _col_sum("goals_scored")
    total_assists = _col_sum("assists")
    total_clean_sheets = _col_sum("clean_sheets")
    total_bonus = _col_sum("bonus")
    gws_played = (
        int((pd.to_numeric(player_rows["minutes"], errors="coerce").fillna(0) > 0).sum())
        if "minutes" in player_rows.columns
        else 0
    )
    points_per_game = round(total_points / gws_played, 2) if gws_played > 0 else 0.0

    return {
        "status": "ok",
        "season": canonical_season,
        "player": {
            "id": player_id,
            "web_name": resolution["web_name"],
            "team_short": team_short,
            "position": resolution["position"],
        },
        "summary": {
            "total_points": total_points,
            "gws_played": gws_played,
            "total_minutes": total_minutes,
            "total_goals": total_goals,
            "total_assists": total_assists,
            "total_clean_sheets": total_clean_sheets,
            "total_bonus": total_bonus,
            "points_per_game": points_per_game,
        },
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_PLAYER_SEASON_POINTS_SPEC = ToolSpec(
    name="get_player_season_points",
    description=(
        "Total FPL points (and aggregated box-score stats: minutes, goals, assists, "
        "clean sheets, bonus) for one named player across a FULL season, past or "
        "present. Reads the owned historical parquet store — covers every season "
        "back to 2016-2017. Use for 'how many points did X score in season Y' / "
        "'X total points last season' style questions where a season is named or "
        "implied. NOT for last-N-gameweek recent form (use get_player_form) and NOT "
        "for who-was-the-top-scorer-that-gameweek (use "
        "get_historical_gameweek_top_scorer)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Player name (case-insensitive, accent-insensitive)",
            },
            "season": {
                "type": "string",
                "description": (
                    "Season identifier, e.g. '2025-2026', '2025-26', or '25/26'. "
                    "Pass 'previous' for the season before the current/most recently "
                    f"completed one (current is {CURRENT_SEASON}). Always required — "
                    "do not guess an earlier season from training-data recall."
                ),
            },
        },
        "required": ["query", "season"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "season": {"type": "string"},
            "player": {"type": "object"},
            "summary": {"type": "object"},
        },
    },
)


def _get_player_season_points_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to get_player_season_points().

    Ignores *bootstrap*: this tool reads season-scoped historical parquet
    files directly rather than the live/current-season bootstrap dict.
    """
    try:
        return get_player_season_points(
            query=args["query"],
            season=args["season"],
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "code": "tool_exception",
            "message": f"get_player_season_points raised an unexpected error: {exc}",
        }


TOOL_REGISTRY.register(
    GET_PLAYER_SEASON_POINTS_SPEC,
    _get_player_season_points_handler,
)
