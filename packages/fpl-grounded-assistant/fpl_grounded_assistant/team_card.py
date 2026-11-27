"""The team card: one club's season, computed by code. No model, no chat session.

    build_team_card(team_id, bootstrap, locale) -> the card, or None for an unknown team

Sections (``table``, ``stats``, ``fixtures``, ``players``) fail on their own: a section that cannot be built is
``None`` (or says why, per metric), never a partial figure passed off as the whole one.

* **Table** -- from the finished fixtures' scores for every club, sorted points, goal difference, goals scored,
  then name. The bootstrap's own team record is not used. Official points deductions and tie-breaks may differ,
  so whatever shows the card must label the table as computed.
* **Stats** -- goals and xG, for and against, over the season and over the last five gameweeks. Both come from
  the query engine over the same checked gameweek data, so a goals row and an xG row cover the same matches.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Mapping

from fpl_player_registry import POSITION_BY_ELEMENT_TYPE

from fpl_grounded_assistant.get_team_results import _live_fixtures, _live_provenance, build_matches, summarize
from fpl_grounded_assistant.gw_live_cache import default_cache
from fpl_grounded_assistant.locale_types import DEFAULT_LOCALE, Locale
from fpl_grounded_assistant.query_engine import COMPLETE, needed_gameweeks, run_query
from fpl_grounded_assistant.query_spec import parse_spec
from fpl_grounded_assistant.team_fixture_calendar import get_team_schedule
from fpl_grounded_assistant.zonal_weakness_tool import _live_season

_LOG = logging.getLogger(__name__)

RECENT_GAMEWEEKS = 5
FORM_MATCHES = 5
NEXT_GAMEWEEKS = 5
TOP_PLAYERS = 5
#: Test seam: the gameweek source (same bootstrap key as the query door's).
CACHE_KEY = "_query_cache"

#: card key -> query catalogue metric.
STAT_METRICS: dict[str, str] = {
    "goals_for": "team_goals",
    "goals_against": "team_goals_conceded",
    "xg_for": "team_expected_goals",
    "xg_against": "team_expected_goals_conceded",
}
_WINDOWS: dict[str, dict[str, Any]] = {
    "season": {"pred": "season", "value": True},
    "recent": {"pred": "last_n", "value": RECENT_GAMEWEEKS},
}


def league_table(fixtures: list[dict[str, Any]], teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every club's record over the finished fixtures, in table order."""
    rows = []
    for team in teams:
        record = summarize(build_matches(fixtures, int(team["id"]), teams))
        rows.append({
            "team_id": int(team["id"]), "name": str(team.get("name") or ""),
            "played": record["played"], "won": record["won"], "drawn": record["drawn"], "lost": record["lost"],
            "gf": record["gf"], "ga": record["ga"], "gd": record["gf"] - record["ga"],
            "points": 3 * record["won"] + record["drawn"],
        })
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"].casefold()))
    for position, row in enumerate(rows, start=1):
        row["position"] = position
    return rows


def _table_section(team_id: int, bootstrap: Mapping[str, Any]) -> dict[str, Any] | None:
    fixtures = _live_fixtures(dict(bootstrap))
    if fixtures is None:
        return None
    teams = list(bootstrap.get("teams") or [])
    rows = league_table(fixtures, teams)
    if not any(r["played"] for r in rows):
        return None
    row = next(r for r in rows if r["team_id"] == team_id)
    matches = build_matches(fixtures, team_id, teams)
    form = [{k: m[k] for k in ("gameweek", "opponent_short", "is_home", "goals_for", "goals_against", "result")}
            for m in matches[-FORM_MATCHES:]]
    out = {k: v for k, v in row.items() if k not in ("team_id", "name")}
    return {**out, "teams": len(rows), "form": form}


def _metric(team_code: str, metric: str, window: Mapping[str, Any], bootstrap: Mapping[str, Any],
            batches: dict[tuple[int, ...], Any]) -> dict[str, Any]:
    spec = parse_spec({"metric": metric, "grain": "team", "match_set": [dict(window)],
                       "filters": [{"field": "club", "op": "eq", "value": team_code}]})
    wanted = tuple(needed_gameweeks(spec, bootstrap))
    if wanted and wanted not in batches:
        cache = bootstrap.get(CACHE_KEY) or default_cache()
        batches[wanted] = cache.load(wanted, bootstrap)
    result = run_query(spec, bootstrap, batches.get(wanted))
    if result.state != COMPLETE or not result.rows:
        return {"total": None, "per_match": None, "range": None, "per_match_range": None, "matches": None,
                "reason": result.reason or "no_matches", "missing_gameweeks": list(result.missing_gameweeks),
                "gameweeks": [], "checked": None}
    row = result.rows[0]
    span = row.value_range
    return {
        "total": row.value, "per_match": round(row.value / row.matches, 2),
        "range": None if span is None else list(span),
        "per_match_range": None if span is None else [round(v / row.matches, 2) for v in span],
        "matches": row.matches, "reason": None, "missing_gameweeks": [], "gameweeks": list(result.gameweeks),
        "checked": result.sum_check != "not_checked",
    }


def _stats_section(team_code: str, bootstrap: Mapping[str, Any]) -> dict[str, Any]:
    batches: dict[tuple[int, ...], Any] = {}
    out: dict[str, Any] = {"recent_gameweeks": RECENT_GAMEWEEKS}
    for key, window in _WINDOWS.items():
        out[key] = {name: _metric(team_code, metric, window, bootstrap, batches)
                    for name, metric in STAT_METRICS.items()}
    return out


def _played(team_id: int, bootstrap: Mapping[str, Any]) -> set[tuple[int | None, str, bool]]:
    """(gameweek, opponent, is_home) of the club's finished matches."""
    fixtures = _live_fixtures(dict(bootstrap)) or []
    return {(m["gameweek"], m["opponent_short"], m["is_home"])
            for m in build_matches(fixtures, team_id, list(bootstrap.get("teams") or []))}


def _fixtures_section(team_id: int, team_code: str, bootstrap: Mapping[str, Any]) -> dict[str, Any] | None:
    # one gameweek more than shown: the schedule starts at the current gameweek, which the club may have played
    schedule = get_team_schedule({"team_query": team_code, "horizon": NEXT_GAMEWEEKS + 1}, dict(bootstrap))
    if schedule.get("status") != "ok":
        return None
    done = _played(team_id, bootstrap)
    left = [f for f in schedule["fixtures"] if (f["gameweek"], f["opponent_short"], f["is_home"]) not in done]
    first = schedule.get("current_gameweek")
    if first is None:
        first = min((f["gameweek"] for f in left), default=0)
    elif any(gw == first for gw, _, _ in done) and not any(f["gameweek"] == first for f in left):
        first += 1
    window = range(first, first + NEXT_GAMEWEEKS)
    return {
        "next": [{k: f[k] for k in ("gameweek", "opponent_short", "is_home", "difficulty")}
                 for f in left if f["gameweek"] in window],
        "blank_gameweeks": [gw for gw in schedule.get("bgw_gameweeks") or [] if gw in window],
        "double_gameweeks": [gw for gw in schedule.get("dgw_gameweeks") or [] if gw in window],
    }


def _players_section(team_id: int, bootstrap: Mapping[str, Any]) -> list[dict[str, Any]]:
    squad = [e for e in bootstrap.get("elements") or [] if e.get("team") == team_id]
    squad.sort(key=lambda e: (-int(e.get("total_points") or 0), str(e.get("web_name") or "")))
    return [{"id": int(e["id"]), "web_name": str(e.get("web_name") or ""),
             "position": POSITION_BY_ELEMENT_TYPE.get(e.get("element_type"), ""),
             "total_points": int(e.get("total_points") or 0),
             "price": None if e.get("now_cost") is None else e["now_cost"] / 10}
            for e in squad[:TOP_PLAYERS]]


def _safe(section: str, build: Any) -> Any:
    try:
        return build()
    except Exception:  # noqa: BLE001 -- one section failing must not lose the card
        _LOG.exception("team card: %s section failed", section)
        return None


def data_stamp(card: Mapping[str, Any]) -> str:
    """A fingerprint of what the card shows: it changes when any figure on it changes."""
    body = json.dumps(card, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def build_team_card(team_id: int, bootstrap: Mapping[str, Any],
                    locale: Locale = DEFAULT_LOCALE) -> dict[str, Any] | None:
    team = next((t for t in bootstrap.get("teams") or [] if t.get("id") == team_id), None)
    if team is None:
        return None
    code = str(team.get("short_name") or "")
    finished = [int(e["id"]) for e in bootstrap.get("events") or [] if e.get("finished")]
    return {
        "team": {"id": team_id, "name": str(team.get("name") or ""), "short_name": code},
        "table": _safe("table", lambda: _table_section(team_id, bootstrap)),
        "stats": _safe("stats", lambda: _stats_section(code, bootstrap)),
        "fixtures": _safe("fixtures", lambda: _fixtures_section(team_id, code, bootstrap)),
        "players": _safe("players", lambda: _players_section(team_id, bootstrap)),
        "last_finished_gameweek": max(finished) if finished else None,
        "data_provenance": _safe("provenance", lambda: _live_provenance(_live_season(dict(bootstrap)), locale)),
    }
