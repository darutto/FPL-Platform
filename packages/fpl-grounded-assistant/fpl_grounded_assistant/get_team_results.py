"""
fpl_grounded_assistant.get_team_results
=======================================
i107: one team's recent RESULTS with a home/away split -- a query-shaped tool.

Two prod questions ("cómo le ha ido de local", "goles en los últimos N
partidos") had no tool: the model fired 2-3 ``web_fetch`` per turn and ended
in "no puedo confirmarlo". The data was already there -- every FPL fixture
carries ``team_h_score`` / ``team_a_score`` / ``finished``
(``get_fixtures_for_gw`` reads them per gameweek) -- but no tool aggregated
them per team, and nothing served a past season.

Sources
-------
* No ``season`` (the prod case): the LIVE season's fixtures, in this order --
  ``bootstrap["_all_fixtures"]`` (injection, tests / captured bootstraps),
  the in-process cache, then ONE ``fpl_api_client.get_all_fixtures()`` call.
* ``season`` given (``"2024-2025"``, ``"24/25"``, ``"previous"`` -- the same
  parser and sentinel as ``get_player_season_points``): the owned store's
  ``fixtures.parquet`` + ``teams.parquet`` for THAT season. Team ids are
  season-local, so the team is resolved against that season's teams, never
  the live bootstrap's.

Provenance
----------
Every ok payload carries ``season`` and ``data_provenance`` (the i74 card
stamp, ``zonal_weakness.build_data_provenance``): the season is read off
the owned pointer file (or, live, derived from the bootstrap) and compared
against ``derive_live_season(bootstrap)`` -- never against the variable that
chose the file, so a past season is labelled as such on the card.

Shapes
------
``matches``: one row per FINISHED match, oldest first::

    {gameweek, kickoff_time, opponent_id, opponent_short, opponent_name,
     is_home, venue: "home"|"away", goals_for, goals_against,
     result: "W"|"D"|"L"}

``summary`` (over ``matches``) and ``venue_split.home`` / ``.away``::

    {played, won, drawn, lost, gf, ga, clean_sheets, avg_gf, avg_ga}

``venue`` filters ``matches``/``summary``; ``last_n`` is applied AFTER the
venue filter (``venue="home", last_n=5`` = the last five HOME games).
``venue_split`` is always present and always the last ``last_n`` home games
and the last ``last_n`` away games respectively, whatever ``venue`` says --
"cómo le ha ido de local" is answerable from any call.

Registers ``get_team_results`` in ``TOOL_REGISTRY`` on import;
``__init__.py`` must import this module.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .get_player_season_points import _resolve_season_arg
from .team_fixture_calendar import _resolve_team_result
from .zonal_weakness import build_data_provenance
from .zonal_weakness_tool import _live_season

_LOG = logging.getLogger(__name__)

# sys.path shim -- mirrors owned_store_fallback.py (no pyproject in this repo).
_FPL_HISTORICAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fpl-historical",
)
if _FPL_HISTORICAL not in sys.path:
    sys.path.append(_FPL_HISTORICAL)

try:
    from fpl_api_client.fpl_client import get_all_fixtures as _get_all_fixtures_live
except ImportError:  # pragma: no cover - api client absent
    _get_all_fixtures_live = None  # type: ignore[assignment]

VENUES: tuple[str, ...] = ("all", "home", "away")
DEFAULT_LAST_N: int = 5
MAX_LAST_N: int = 38

#: Live all-fixtures cache: one API call per process per TTL, shared by every
#: turn. Cleared by ``_clear_results_cache`` (tests).
_LIVE_CACHE_TTL_S: float = 300.0
_live_cache: dict[str, Any] = {}


def _clear_results_cache() -> None:
    _live_cache.clear()


# ---------------------------------------------------------------------------
# Fixture sources
# ---------------------------------------------------------------------------

def _live_fixtures(bootstrap: dict[str, Any]) -> list[dict[str, Any]] | None:
    """All fixtures of the live season: injection, cache, then one API call."""
    injected = bootstrap.get("_all_fixtures")
    if isinstance(injected, list):
        return injected
    now = time.monotonic()
    if _live_cache and now - _live_cache.get("at", 0.0) < _LIVE_CACHE_TTL_S:
        return _live_cache["fixtures"]
    if _get_all_fixtures_live is None:
        return None
    try:
        fixtures = _get_all_fixtures_live()
    except Exception as exc:  # noqa: BLE001 -- network is never a crash
        _LOG.warning("get_team_results: all-fixtures fetch failed: %s", exc)
        return None
    if not isinstance(fixtures, list):
        return None
    _live_cache.update({"at": now, "fixtures": fixtures})
    return fixtures


def _owned_season(season: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """(fixtures, teams, pointer) for *season* from the owned store.

    Mirrors ``get_player_season_points``: the season directory is
    ``merged_parquet_dir(season)`` (imported seasons carry a pointer with no
    baseline/incrementals, so the captured-store preamble would reject them
    as empty). Raises ``OwnedStoreUnavailable`` on any failure; the caller
    turns it into a status payload.
    """
    import json  # noqa: PLC0415
    from .owned_store_fallback import OwnedStoreUnavailable, _coerce_native  # noqa: PLC0415
    try:
        from fpl_historical.paths import merged_parquet_dir, owned_latest_pointer_path  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - fpl-historical absent
        raise OwnedStoreUnavailable("fpl-historical not available") from exc

    merged_dir = merged_parquet_dir(season)
    if not merged_dir.exists():
        raise OwnedStoreUnavailable("no data for that season")
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise OwnedStoreUnavailable(f"pandas not available: {exc}") from exc
    try:
        fixtures_df = pd.read_parquet(merged_dir / "fixtures.parquet")
        teams_df = pd.read_parquet(merged_dir / "teams.parquet")
    except Exception as exc:
        raise OwnedStoreUnavailable(f"parquet read failed: {exc}") from exc
    if len(fixtures_df) == 0 or len(teams_df) == 0:
        raise OwnedStoreUnavailable("no fixtures/teams stored for that season")

    fixtures = []
    for rec in fixtures_df.to_dict(orient="records"):
        fixtures.append({
            "id":           _coerce_native(rec.get("fixture_id")),
            "event":        _coerce_native(rec.get("event_id")),
            "team_h":       _coerce_native(rec.get("team_h")),
            "team_a":       _coerce_native(rec.get("team_a")),
            "team_h_score": _coerce_native(rec.get("team_h_score")),
            "team_a_score": _coerce_native(rec.get("team_a_score")),
            "finished":     _coerce_native(rec.get("finished")),
            "kickoff_time": _coerce_native(rec.get("kickoff_time")),
        })
    teams = []
    for rec in teams_df.to_dict(orient="records"):
        teams.append({
            "id":         _coerce_native(rec.get("team_id")),
            "name":       rec.get("name"),
            "short_name": rec.get("short_name"),
        })
    # The season on the stamp is READ OFF the pointer file, never taken from
    # the argument that chose the directory (the i75/i82 provenance rule). A
    # season with no pointer stamps as "unknown" rather than echoing the arg.
    pointer: dict[str, Any] = {}
    pointer_path = owned_latest_pointer_path(season)
    if pointer_path.exists():
        try:
            pointer = json.loads(pointer_path.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            pointer = {}
    return fixtures, teams, pointer


def _live_provenance(live_season: str | None) -> dict[str, Any]:
    """The season stamp for the live FPL feed.

    Same shape as the owned-store stamp. The season is whatever
    ``derive_live_season(bootstrap)`` says; when it cannot be derived the
    stamp says so ("unverified") instead of borrowing the tactical store's
    "unknown" wording, which would name the wrong data source.
    """
    if live_season is None:
        return {
            "season": None, "season_label": None,
            "live_season": None, "live_season_label": None,
            "ingested_at": None, "n_matches": None, "n_shots": None,
            "status": "unverified", "is_current": False,
            "label": "Datos: temporada en curso (FPL en vivo; temporada no verificable)",
        }
    prov = build_data_provenance({"season": live_season}, live_season)
    prov["label"] = f"{prov['label']} (FPL en vivo)"
    return prov


# ---------------------------------------------------------------------------
# Aggregation -- pure
# ---------------------------------------------------------------------------

def _team_maps(teams: list[dict[str, Any]]) -> tuple[dict[int, str], dict[int, str]]:
    short: dict[int, str] = {}
    name: dict[int, str] = {}
    for t in teams:
        tid = t.get("id")
        if tid is None:
            continue
        short[int(tid)] = str(t.get("short_name") or f"T{tid}")
        name[int(tid)] = str(t.get("name") or f"Team {tid}")
    return short, name


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_matches(
    fixtures: list[dict[str, Any]], team_id: int, teams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Every FINISHED match of *team_id* with both scores, oldest first."""
    short, name = _team_maps(teams)
    rows: list[dict[str, Any]] = []
    for f in fixtures:
        if not f.get("finished"):
            continue
        h = _int_or_none(f.get("team_h"))
        a = _int_or_none(f.get("team_a"))
        if team_id not in (h, a):
            continue
        hs = _int_or_none(f.get("team_h_score"))
        as_ = _int_or_none(f.get("team_a_score"))
        if hs is None or as_ is None:
            continue
        is_home = h == team_id
        opp = a if is_home else h
        gf, ga = (hs, as_) if is_home else (as_, hs)
        rows.append({
            "gameweek":       _int_or_none(f.get("event")),
            "kickoff_time":   f.get("kickoff_time"),
            "opponent_id":    opp,
            "opponent_short": short.get(opp, f"T{opp}"),
            "opponent_name":  name.get(opp, f"Team {opp}"),
            "is_home":        is_home,
            "venue":          "home" if is_home else "away",
            "goals_for":      gf,
            "goals_against":  ga,
            "result":         "W" if gf > ga else ("D" if gf == ga else "L"),
        })
    rows.sort(key=lambda r: (r["gameweek"] if r["gameweek"] is not None else 0, r["kickoff_time"] or ""))
    return rows


def summarize(matches: list[dict[str, Any]]) -> dict[str, Any]:
    played = len(matches)
    won = sum(1 for m in matches if m["result"] == "W")
    drawn = sum(1 for m in matches if m["result"] == "D")
    gf = sum(m["goals_for"] for m in matches)
    ga = sum(m["goals_against"] for m in matches)
    return {
        "played":       played,
        "won":          won,
        "drawn":        drawn,
        "lost":         played - won - drawn,
        "gf":           gf,
        "ga":           ga,
        "clean_sheets": sum(1 for m in matches if m["goals_against"] == 0),
        "avg_gf":       round(gf / played, 2) if played else 0.0,
        "avg_ga":       round(ga / played, 2) if played else 0.0,
    }


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

def get_team_results(
    team: str,
    bootstrap: dict[str, Any],
    *,
    last_n: int = DEFAULT_LAST_N,
    venue: str = "all",
    season: str | None = None,
) -> dict[str, Any]:
    """Recent results of one team, with the home/away split. Never raises."""
    if not isinstance(team, str) or not team.strip():
        return {"status": "error", "code": "missing_team_name",
                "message": "Falta el nombre del equipo."}
    venue = (venue or "all").strip().lower()
    if venue not in VENUES:
        return {"status": "error", "code": "invalid_argument",
                "message": f"venue debe ser uno de {list(VENUES)}, no {venue!r}."}
    try:
        last_n = int(last_n)
    except (TypeError, ValueError):
        return {"status": "error", "code": "invalid_argument",
                "message": f"last_n debe ser un entero, no {last_n!r}."}
    last_n = max(1, min(MAX_LAST_N, last_n))
    live_season = _live_season(bootstrap)

    # --- source --------------------------------------------------------
    if season:
        canonical = _resolve_season_arg(season)
        if canonical is None:
            return {"status": "invalid_argument", "code": "unparseable_season",
                    "message": (f"Could not parse season '{season}'. Use a format like "
                                "'2024-2025', '2024-25', or 'previous' for last season.")}
        from .owned_store_fallback import OwnedStoreUnavailable  # noqa: PLC0415
        try:
            fixtures, teams, pointer = _owned_season(canonical)
        except OwnedStoreUnavailable as exc:
            from .historical_gameweek_top_scorer import _list_available_seasons  # noqa: PLC0415
            available = _list_available_seasons()
            return {"status": "not_found", "code": "season_not_found",
                    "message": (f"No historical results for season '{canonical}' ({exc}). "
                                f"Available seasons: {', '.join(available) if available else 'none'}.")}
        source = "owned_store"
        # n_matches is left out on purpose: the stamp's "thin" rule is about a
        # league-wide read (Understat shots); a results list of the last N
        # games is not thin because the season is young. played_total says
        # how many finished games the source holds.
        provenance = build_data_provenance(
            {"season": pointer.get("season"), "ingested_at": pointer.get("merged_at")},
            live_season,
        )
    else:
        fixtures = _live_fixtures(bootstrap)
        if fixtures is None:
            return {"status": "error", "code": "fetch_failed",
                    "message": "Could not fetch the season's fixtures from the FPL API."}
        teams = list(bootstrap.get("teams") or [])
        source = "live"
        provenance = _live_provenance(live_season)

    # --- team (resolved against THIS source's teams) --------------------
    res = _resolve_team_result(team, {"teams": teams})
    if res["status"] == "ambiguous":
        return {"status": "ambiguous", "code": "ambiguous_team", "query": team,
                "candidates": res["candidates"],
                "message": f"'{team}' matches several teams: "
                           + ", ".join(c["name"] for c in res["candidates"]) + "."}
    if res["status"] != "ok":
        return {"status": "not_found", "code": "team_not_found", "query": team,
                "message": f"No encontré ningún equipo que coincida con '{team}'."}
    team_data = res["team_data"]
    team_id = int(team_data["id"])

    # --- aggregate ------------------------------------------------------
    all_matches = build_matches(fixtures, team_id, teams)
    home = [m for m in all_matches if m["is_home"]]
    away = [m for m in all_matches if not m["is_home"]]
    pool = all_matches if venue == "all" else (home if venue == "home" else away)
    window = pool[-last_n:]

    return {
        "status":          "ok",
        "team":            {"id": team_id, "name": team_data.get("name"),
                            "short_name": team_data.get("short_name")},
        "season":          provenance.get("season"),
        "source":          source,
        "data_provenance": provenance,
        "venue":           venue,
        "last_n":          last_n,
        "played_total":    len(all_matches),
        "matches":         window,
        "summary":         summarize(window),
        "venue_split": {
            "home": summarize(home[-last_n:]),
            "away": summarize(away[-last_n:]),
        },
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

def _get_team_results_handler(tool_args: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    return get_team_results(
        tool_args.get("team", ""),
        bootstrap,
        last_n=tool_args.get("last_n", DEFAULT_LAST_N),
        venue=tool_args.get("venue", "all"),
        season=tool_args.get("season"),
    )


_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["played", "won", "drawn", "lost", "gf", "ga", "clean_sheets", "avg_gf", "avg_ga"],
    "properties": {
        "played": {"type": "integer"}, "won": {"type": "integer"},
        "drawn": {"type": "integer"}, "lost": {"type": "integer"},
        "gf": {"type": "integer"}, "ga": {"type": "integer"},
        "clean_sheets": {"type": "integer"},
        "avg_gf": {"type": "number"}, "avg_ga": {"type": "number"},
    },
}

GET_TEAM_RESULTS_SPEC = ToolSpec(
    name="get_team_results",
    description=(
        "Recent RESULTS of one team, with a home/away split: last N finished "
        "matches (opponent, venue, score, W/D/L), a summary (won/drawn/lost, goals "
        "for/against, clean sheets, averages) and venue_split with the same summary "
        "for the last N home and the last N away games. Live season by default; "
        "season='YYYY-YYYY' or 'previous' reads the owned store."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team": {
                "type": "string",
                "description": "Team name, short code or alias ('Arsenal', 'ARS', 'Spurs').",
            },
            "last_n": {
                "type": "integer", "minimum": 1, "maximum": MAX_LAST_N,
                "description": f"How many recent matches (default {DEFAULT_LAST_N}), applied after the venue filter.",
            },
            "venue": {
                "type": "string", "enum": list(VENUES),
                "description": "Which games to list: all (default), home ('de local'), away ('de visitante').",
            },
            "season": {
                "type": "string",
                "description": "Omit for the current season; 'YYYY-YYYY', 'YY/YY' or 'previous' for a past one.",
            },
        },
        "required": ["team"],
    },
    output_schema={
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"type": "string",
                       "enum": ["ok", "not_found", "ambiguous", "error", "invalid_argument"]},
            "code": {"type": "string"},
            "message": {"type": "string"},
            "query": {"type": "string"},
            "candidates": {"type": "array", "items": {"type": "object"}},
            "team": {"type": "object"},
            "season": {"type": ["string", "null"]},
            "source": {"type": "string", "enum": ["live", "owned_store"]},
            "data_provenance": {"type": "object"},
            "venue": {"type": "string", "enum": list(VENUES)},
            "last_n": {"type": "integer"},
            "played_total": {"type": "integer"},
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["gameweek", "opponent_id", "opponent_short", "opponent_name",
                                 "is_home", "venue", "goals_for", "goals_against", "result"],
                    "properties": {
                        "gameweek": {"type": ["integer", "null"]},
                        "kickoff_time": {"type": ["string", "null"]},
                        "opponent_id": {"type": "integer"},
                        "opponent_short": {"type": "string"},
                        "opponent_name": {"type": "string"},
                        "is_home": {"type": "boolean"},
                        "venue": {"type": "string", "enum": ["home", "away"]},
                        "goals_for": {"type": "integer"},
                        "goals_against": {"type": "integer"},
                        "result": {"type": "string", "enum": ["W", "D", "L"]},
                    },
                },
            },
            "summary": _SUMMARY_SCHEMA,
            "venue_split": {
                "type": "object",
                "required": ["home", "away"],
                "properties": {"home": _SUMMARY_SCHEMA, "away": _SUMMARY_SCHEMA},
            },
        },
    },
)

TOOL_REGISTRY.register(GET_TEAM_RESULTS_SPEC, _get_team_results_handler)
