"""
fpl_grounded_assistant.historical_gameweek_top_scorer
======================================================
Historical "Player of the Gameweek" lookup for PAST / COMPLETED seasons.

Closes the gap where every other grounded tool reads only the live/current
FPL bootstrap and can never answer questions about a finished gameweek or a
past season (e.g. "who was top scorer in GW1 of 2025-26?" or "give me the
Player of the Gameweek table for all 38 gameweeks of last season").

Data source
-----------
Reads ``events.parquet`` from ``packages/fpl-historical``'s per-season owned
store (``fpl_historical.paths.merged_parquet_dir(season)``). Seasons captured
live from the FPL API already have ``top_element`` / ``top_element_info.{id,points}``
precomputed on each event — this is the same "Player of the Gameweek" the FPL
app itself shows, not a re-derived proxy. Older vaastav-imported seasons don't
carry that field (some don't even have populated ``events.parquet`` rows), so
for those the top scorer is derived from ``player_gw_stats.parquet`` (max
``total_points`` per ``event_id``) instead. Player identity (name/team/
position) is resolved from that season's ``players.parquet`` + ``teams.parquet``
— team is a season-snapshot association, not necessarily the team the player
was on at that specific gameweek if they transferred mid-season.

Cross-package import uses the same sys.path shim as ``owned_store_fallback.py``.

Registration
------------
Registers ``get_historical_gameweek_top_scorer`` in ``TOOL_REGISTRY`` as a
side-effect of import. ``__init__.py`` must import this module.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

# ---------------------------------------------------------------------------
# sys.path shim — mirror owned_store_fallback.py's pattern
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

_POSITION_MAP: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

_SEASON_RE = re.compile(r"(\d{4})\D+(\d{2,4})")
_YEAR_ONLY_RE = re.compile(r"^(\d{4})$")


# ---------------------------------------------------------------------------
# Season parsing
# ---------------------------------------------------------------------------

def _normalize_season(raw: str) -> str | None:
    """Parse a loosely-formatted season string into ``YYYY-YYYY``.

    Accepts ``2025-2026``, ``2025-26``, ``2025/26``, ``25/26``, ``2025``
    (interpreted as the season starting that year). Returns ``None`` when
    the input cannot be parsed as a season.
    """
    raw = raw.strip()

    m = _SEASON_RE.search(raw)
    if m:
        start_str, end_str = m.group(1), m.group(2)
        start = int(start_str)
        if len(end_str) == 2:
            end = (start // 100) * 100 + int(end_str)
        else:
            end = int(end_str)
        if end == start + 1:
            return f"{start}-{end}"
        return None

    m2 = _YEAR_ONLY_RE.match(raw)
    if m2:
        start = int(m2.group(1))
        return f"{start}-{start + 1}"

    return None


def _safe_int_stat(row: dict[str, Any], key: str) -> int:
    """Read an integer stat from a player_gw_stats record; 0 for missing/NaN.

    Older seasons don't have every column (e.g. no defensive_contribution
    before 2025-26), so callers probe with .get() and this coerces cleanly.
    """
    import math

    val = row.get(key)
    if val is None:
        return 0
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0
    if math.isnan(f):
        return 0
    return int(f)


def _build_highlight(position: str, points: "int | None", box: dict[str, Any] | None) -> str:
    """Build a short human-readable "why" for a Player-of-the-Gameweek pick.

    Reads whatever box-score columns are available for that season (older
    seasons lack defensive_contribution/cards; all seasons have goals/
    assists/clean_sheets/saves/bonus/minutes). Returns an empty string when
    no box score row is available at all.
    """
    if box is None:
        return ""

    parts: list[str] = []

    goals = _safe_int_stat(box, "goals_scored")
    assists = _safe_int_stat(box, "assists")
    clean_sheet = _safe_int_stat(box, "clean_sheets") > 0
    saves = _safe_int_stat(box, "saves")
    bonus = _safe_int_stat(box, "bonus")
    minutes = _safe_int_stat(box, "minutes")
    pens_saved = _safe_int_stat(box, "penalties_saved")
    def_contribution = _safe_int_stat(box, "defensive_contribution")

    if goals == 1:
        parts.append("1 goal")
    elif goals > 1:
        parts.append(f"{goals} goals")

    if assists == 1:
        parts.append("1 assist")
    elif assists > 1:
        parts.append(f"{assists} assists")

    if pens_saved > 0:
        parts.append(f"{pens_saved} penalty save" + ("s" if pens_saved > 1 else ""))

    if position == "GKP" and saves > 0:
        parts.append(f"{saves} save" + ("s" if saves != 1 else ""))

    if clean_sheet and position in ("GKP", "DEF", "MID"):
        parts.append("clean sheet")

    if def_contribution > 0 and position in ("DEF", "MID"):
        parts.append(f"{def_contribution} defensive contribution" + ("s" if def_contribution != 1 else ""))

    if bonus > 0:
        parts.append(f"{bonus} bonus point" + ("s" if bonus != 1 else ""))

    if not parts and minutes > 0:
        parts.append(f"{minutes} minutes played")

    if not parts:
        return ""

    return ", ".join(parts)


def _list_available_seasons() -> list[str]:
    if not _FPL_HISTORICAL_AVAILABLE:
        return []
    seasons_dir = historical_root() / "seasons"
    if not seasons_dir.exists():
        return []
    return sorted(d.name for d in seasons_dir.iterdir() if d.is_dir())


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_historical_gameweek_top_scorer(
    season: str,
    gw: int | None = None,
) -> dict[str, Any]:
    """Return the FPL "Player of the Gameweek" for one GW, or the full-season table.

    Args:
        season: Season string in any common format (e.g. "2025-2026",
            "2025-26", "25/26").
        gw: Optional gameweek number (1-38). Omit to return every finished
            gameweek's top scorer for the season (the full table).

    Returns:
        # Success:
        {
            "status": "ok",
            "season": "2025-2026",
            "gw": <int | None>,
            "entries": [
                {
                    "event_id": <int>,
                    "player_id": <int>,
                    "web_name": <str>,
                    "team_short": <str>,
                    "position": <str>,
                    "points": <int>,
                },
                ...
            ],
        }
        # Failure:
        {"status": "invalid_argument" | "not_found" | "error", "code": <str>, "message": <str>}
    """
    if not _FPL_HISTORICAL_AVAILABLE:
        return {
            "status": "error",
            "code": "historical_unavailable",
            "message": "fpl-historical package is not available on this deployment.",
        }

    canonical_season = _normalize_season(season) if season else None
    if canonical_season is None:
        return {
            "status": "invalid_argument",
            "code": "unparseable_season",
            "message": (
                f"Could not parse season '{season}'. Use a format like "
                "'2025-2026' or '2025-26'."
            ),
        }

    if gw is not None:
        try:
            gw = int(gw)
        except (ValueError, TypeError):
            return {
                "status": "invalid_argument",
                "code": "invalid_gw",
                "message": "gw must be an integer between 1 and 38.",
            }
        if not (1 <= gw <= 38):
            return {
                "status": "invalid_argument",
                "code": "invalid_gw",
                "message": f"gw must be between 1 and 38 (got {gw}).",
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
        events_df = pd.read_parquet(merged_dir / "events.parquet")
        players_df = pd.read_parquet(merged_dir / "players.parquet")
        teams_df = pd.read_parquet(merged_dir / "teams.parquet")
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "code": "parquet_read_failed",
            "message": f"Failed to read historical parquet data: {exc}",
        }

    team_short_by_id: dict[int, str] = dict(zip(teams_df["team_id"], teams_df["short_name"]))
    players_by_id = players_df.set_index("player_id")

    # FPL's "Assistant Manager" fantasy feature (2025-26+) added element_type=5
    # (a real manager, not a player) to the elements table, and some seasons'
    # owned-store snapshots retroactively carry manager rows in BOTH
    # top_element_info and player_gw_stats. A manager can never be "Player of
    # the Gameweek", so both resolution paths below are restricted to genuine
    # player positions (GKP/DEF/MID/FWD).
    valid_player_ids: set[int] = set(
        players_df.loc[players_df["element_type"].isin(_POSITION_MAP.keys()), "player_id"]
    )

    if gw is not None:
        events_df = events_df[events_df["event_id"] == gw]
    else:
        events_df = events_df.sort_values("event_id")

    # Two further data-quality gaps this block works around:
    # 1. Older (vaastav-imported) seasons don't carry FPL's own
    #    top_element/top_element_info fields on events.parquet — only
    #    seasons captured live from the FPL API do.
    # 2. A couple of the earliest seasons have a completely empty
    #    events.parquet (no rows at all), even though player_gw_stats.parquet
    #    is fully populated.
    # In all cases (including the manager-contamination case above), fall
    # back to deriving the top scorer directly from player_gw_stats.parquet
    # (max total_points per event_id, restricted to real players) so every
    # season in the owned store is covered with a genuine player result.
    has_native_top_element = "top_element_info.id" in events_df.columns and len(events_df) > 0

    wanted_events: set[int] = (
        {gw} if gw is not None else set(events_df["event_id"].tolist())
    )

    try:
        gw_stats_df = pd.read_parquet(merged_dir / "player_gw_stats.parquet")
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "code": "parquet_read_failed",
            "message": f"Failed to read player_gw_stats parquet: {exc}",
        }
    if gw is None and not has_native_top_element:
        wanted_events = set(gw_stats_df["event_id"].unique().tolist())

    fallback_top_by_gw: dict[int, tuple[int, int]] = {}
    gw_stats_df = gw_stats_df[
        gw_stats_df["event_id"].isin(wanted_events) & gw_stats_df["player_id"].isin(valid_player_ids)
    ]
    if len(gw_stats_df) > 0:
        idx = gw_stats_df.groupby("event_id")["total_points"].idxmax()
        for rec in gw_stats_df.loc[idx].to_dict(orient="records"):
            fallback_top_by_gw[int(rec["event_id"])] = (
                int(rec["player_id"]),
                int(rec["total_points"]),
            )

    # Box-score lookup for the "why" narrative — keyed by (event_id, player_id).
    # Reuses the same filtered gw_stats_df (already restricted to the wanted
    # events and real players), so every top scorer we end up reporting has a
    # matching row here.
    box_score_by_event_player: dict[tuple[int, int], dict[str, Any]] = {
        (int(rec["event_id"]), int(rec["player_id"])): rec
        for rec in gw_stats_df.to_dict(orient="records")
    }

    if gw is not None and gw not in wanted_events.union(fallback_top_by_gw.keys()):
        return {
            "status": "not_found",
            "code": "gw_not_found",
            "message": f"Gameweek {gw} not found for season {canonical_season}.",
        }

    finished_by_event: dict[int, bool] = {
        int(rec["event_id"]): bool(rec.get("finished"))
        for rec in events_df.to_dict(orient="records")
    }

    native_by_event: dict[int, tuple[int, "int | None"]] = {}
    if has_native_top_element:
        for rec in events_df.to_dict(orient="records"):
            top_id = rec.get("top_element_info.id")
            if top_id is None or pd.isna(top_id):
                continue
            top_id = int(top_id)
            if top_id not in valid_player_ids:
                continue  # manager, not a player — let the fallback path handle this GW
            top_points = rec.get("top_element_info.points")
            native_by_event[int(rec["event_id"])] = (
                top_id,
                int(top_points) if top_points is not None and not pd.isna(top_points) else None,
            )

    entries: list[dict[str, Any]] = []
    for event_id in sorted(wanted_events | set(native_by_event) | set(fallback_top_by_gw)):
        # A season with NO events.parquet rows at all has no "finished" signal
        # to check — treat every GW present in player_gw_stats as finished,
        # since this tool only ever serves past/completed seasons.
        finished = finished_by_event.get(event_id, True)
        if not finished:
            continue

        if event_id in native_by_event:
            top_id, points = native_by_event[event_id]
        elif event_id in fallback_top_by_gw:
            top_id, points = fallback_top_by_gw[event_id]
        else:
            continue

        if top_id in players_by_id.index:
            prow = players_by_id.loc[top_id]
            web_name = str(prow.get("web_name", "?"))
            team_id = prow.get("team_id")
            position = _POSITION_MAP.get(
                int(prow["element_type"]) if pd.notna(prow.get("element_type")) else None, "?"
            )
        else:
            web_name = "?"
            team_id = None
            position = "?"

        team_short = team_short_by_id.get(int(team_id), "?") if team_id is not None and pd.notna(team_id) else "?"

        box = box_score_by_event_player.get((event_id, top_id))
        highlight = _build_highlight(position, points, box)

        entries.append({
            "event_id": event_id,
            "player_id": top_id,
            "web_name": web_name,
            "team_short": team_short,
            "position": position,
            "points": points,
            "highlight": highlight,
        })

    if not entries:
        return {
            "status": "not_found",
            "code": "no_finished_data",
            "message": (
                f"No finished-gameweek data available for season {canonical_season}"
                + (f", GW{gw}" if gw is not None else "")
                + "."
            ),
        }

    return {
        "status": "ok",
        "season": canonical_season,
        "gw": gw,
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC = ToolSpec(
    name="get_historical_gameweek_top_scorer",
    description=(
        "FPL 'Player of the Gameweek' (highest-scoring player) for a PAST/COMPLETED "
        "season. Pass gw for one gameweek's top scorer; omit gw for the full-season "
        "table (top scorer for every finished gameweek). Use for historical/past-season "
        "point queries (e.g. 'top scorer GW1 2025-26', 'Player of the Gameweek table for "
        "last season'). Covers seasons 2016-2017 through the most recently completed one. "
        "NOT for in-progress/live current-season questions — use get_player_history or "
        "rank_players_by_metric for those."
    ),
    parameters={
        "type": "object",
        "properties": {
            "season": {
                "type": "string",
                "description": (
                    "Season identifier, e.g. '2025-2026', '2025-26', or '25/26'. "
                    f"Always required. The current/most recently completed season "
                    f"is {CURRENT_SEASON} — if the user says 'last season', 'this "
                    f"season', or doesn't name a season, pass '{CURRENT_SEASON}'. "
                    "Do NOT guess an earlier season from training-data recall."
                ),
            },
            "gw": {
                "type": "integer",
                "description": "Gameweek number (1-38). Omit for the full-season table.",
                "minimum": 1,
                "maximum": 38,
            },
        },
        # season is genuinely required — the tool can never guess which
        # season the user means. Making it required also ensures the shared
        # ToolRegistry.run() dispatches handler(args, bootstrap) rather than
        # handler(bootstrap) alone (see fpl_tool_runner.runner.ToolRegistry.run).
        "required": ["season"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "season": {"type": "string"},
            "gw": {"type": ["integer", "null"]},
            "entries": {"type": "array"},
        },
    },
)


def _get_historical_gameweek_top_scorer_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to get_historical_gameweek_top_scorer().

    Ignores *bootstrap*: this tool reads season-scoped historical parquet
    files directly rather than the live/current-season bootstrap dict.
    """
    try:
        return get_historical_gameweek_top_scorer(
            season=args["season"],
            gw=args.get("gw"),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "code": "tool_exception",
            "message": f"get_historical_gameweek_top_scorer raised an unexpected error: {exc}",
        }


TOOL_REGISTRY.register(
    GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC,
    _get_historical_gameweek_top_scorer_handler,
)
