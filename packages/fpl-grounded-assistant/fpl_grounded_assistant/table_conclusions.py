"""A ranking table's verdict: 0-3 one-line conclusions ABOUT the table, never a reprint of its rows.

Approved 2026-11-14 for every table card, mirroring the player card (see player_conclusions). Each conclusion is
shown only when its rule fires; when none fires there is no verdict block at all.

Everything comes from the rows the card paints plus the FPL bootstrap already loaded for the turn, so this adds
no call of any kind. Conclusions are structured (``key`` + ``params`` + ``evidence``), never pre-rendered
strings: the UI owns the wording in each locale. This module imports nothing from the live stack.

Priority (max :data:`MAX_CONCLUSIONS`, first wins):

1. ``gap`` -- the leader, or the top two together, is clearly separated from the next row. Not on metrics where
   leading is not a merit, nor on a lead of a single unit in a list of whole numbers.
2. ``concentration`` -- one team, or one FPL position, holds a large share of the list.
3. ``opportunity`` -- a row in the top half is lightly owned.
4. ``reading`` -- the metric is a season total, so it favours minutes. It only fills a free slot.

Never raises: a malformed row is skipped, a malformed input drops that conclusion only.
"""
from __future__ import annotations

import math
from typing import Any

#: At most this many lines above the card -- more stops being a verdict and becomes a list to read.
MAX_CONCLUSIONS: int = 3

#: ``gap`` and ``concentration`` need at least this many rows: on a top 3 every row is "separated" and any two
#: players of one club are "a large share".
MIN_ROWS: int = 5

#: ``gap`` fires when the leader (or the second of a leading pair) is at least this far above the next row,
#: relative to his own value. 20 % is a lead a reader sees in the table without doing arithmetic; near-ties sit
#: well under 10 %.
GAP_SHARE_FIRES: float = 0.20

#: ...and that gap must also be at least this multiple of the spread among the rows below it (next row to last
#: row). It keeps a steadily falling list -- where every step is as big as the first -- from reading as "one
#: player and then the rest".
GAP_VS_REST_SPREAD: float = 1.0

#: When every value in the list is a whole number (goals, bonus, clean sheets), the lead must also be at least
#: this many units: 2 goals against 1 is a 50 % lead and one goal -- a count that small is not "pulling clear".
GAP_MIN_WHOLE_UNITS: int = 2

#: A leading PAIR is only a pair when the two are close: the leader is within this share of the second. Above
#: it the leader would be his own line (and below :data:`GAP_SHARE_FIRES` he was not).
PAIR_MAX_SPREAD: float = 0.10

#: One team "holds" the list from this many rows AND this share. Three of twenty clubs' worth in one list is
#: about six times what an even spread gives on a top 10; two can be chance.
TEAM_MIN_COUNT: int = 3
TEAM_SHARE_FIRES: float = 0.30

#: One FPL position "holds" the list from this share. Midfielders are roughly four in ten of the game's players,
#: so 6 of 10 is the base rate talking; 7 of 10 is the ranking talking.
POSITION_SHARE_FIRES: float = 0.70

#: "Lightly owned" = selected by less than this percent. Stricter than the differential tool's 15 %: this line
#: sits above a table of the best players at something, where 10-15 % ownership is ordinary.
LOW_OWNERSHIP_PCT: float = 10.0

_POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

#: The ranked metric of each ``@resource`` ranking (canonical bootstrap field). ``injuries`` is not a ranking.
RESOURCE_METRICS: dict[str, str] = {
    "top_form":    "form",
    "top_xg":      "expected_goal_involvements",
    "top_xa":      "expected_assists",
    "top_points":  "total_points",
    "top_minutes": "minutes",
    "popular":     "selected_by_percent",
}

#: Set-piece orders: 1 is the good end, and the values are list positions, not amounts. Kept equal to
#: rank_players_by_metric._LOWER_IS_BETTER by test, not by import.
LOWER_IS_BETTER: frozenset[str] = frozenset({
    "penalties_order", "direct_freekicks_order", "corners_and_indirect_freekicks_order",
})

#: Season totals: they accumulate with every minute played, so a top N of them is partly a list of who plays
#: most. An allowlist -- a metric this module does not know gets no ``reading`` line. Not here on purpose:
#: per-90 and rate metrics (form, points_per_game), price, ownership, the current-gameweek transfer counts,
#: the set-piece orders, and ``minutes`` itself (the line would be a tautology).
SEASON_TOTAL_METRICS: frozenset[str] = frozenset({
    "total_points", "expected_goals", "expected_assists", "expected_goal_involvements", "ict_index",
    "influence", "creativity", "threat", "goals_scored", "assists", "clean_sheets", "bonus", "bps",
    "defensive_contribution", "saves", "yellow_cards", "red_cards", "goals_conceded",
    "expected_goals_conceded",
})

#: Leading these lists is not a merit, so a lightly owned leader is not an ``opportunity`` and a clear leader is
#: not a ``gap`` worth a line (the verdict frames things as opportunities): ownership (``opportunity`` would test
#: the metric against itself), price, sales, cards and goals against.
NOT_A_MERIT_METRICS: frozenset[str] = frozenset({
    "selected_by_percent", "now_cost", "transfers_out_event", "yellow_cards", "red_cards", "goals_conceded",
    "expected_goals_conceded",
})

#: Only goalkeepers have these, so "all goalkeepers" is not a finding.
_SINGLE_POSITION_METRICS: frozenset[str] = frozenset({"saves", "saves_per_90"})


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _json_num(value: float) -> int | float:
    """Whole numbers as int (a points total reads 87, not 87.0); the rest as they are."""
    return int(value) if value == int(value) else value


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() and value.strip() != "?" else None


def _normalise(rows: Any) -> list[dict[str, Any]]:
    """Both row shapes -> ``{id, name, team, position, value}``, in table order. Bad rows are skipped.

    ``rank_players_by_metric`` rows carry ``metric_value`` (+ ``id``); ``@resource`` rows carry ``value``.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("web_name"))
        value = _num(row["metric_value"] if "metric_value" in row else row.get("value"))
        if name is None or value is None:
            continue
        player_id = row.get("id")
        out.append({
            "id": player_id if isinstance(player_id, int) and not isinstance(player_id, bool) and player_id > 0
            else None,
            "name": name,
            "team": _text(row.get("team_short")),
            "position": _text(row.get("position")),
            "value": value,
        })
    return out


def _is_best_first_desc(metric: str, order: Any) -> bool:
    """A plain "top N": highest value first, and highest is what the metric rewards."""
    return metric not in LOWER_IS_BETTER and order in (None, "desc")


def _gap(rows: list[dict[str, Any]], metric: str, order: Any) -> dict[str, Any] | None:
    if len(rows) < MIN_ROWS or not _is_best_first_desc(metric, order) or metric in NOT_A_MERIT_METRICS:
        return None
    values = [r["value"] for r in rows]
    min_lead = GAP_MIN_WHOLE_UNITS if all(v == int(v) for v in values) else 0
    if any(later > earlier for earlier, later in zip(values, values[1:])):
        return None  # not actually sorted best-first: say nothing rather than something wrong

    def separated(lead_idx: int) -> bool:
        lead, nxt = values[lead_idx], values[lead_idx + 1]
        if lead <= 0 or nxt < 0:
            return False
        gap = lead - nxt
        return (gap >= GAP_SHARE_FIRES * lead and gap >= GAP_VS_REST_SPREAD * (nxt - values[-1])
                and gap >= min_lead)

    if separated(0):
        leaders = 1
    elif values[0] - values[1] <= PAIR_MAX_SPREAD * values[0] and separated(1):
        leaders = 2
    else:
        return None
    return {
        "key": "gap",
        "params": {"leaders": [r["name"] for r in rows[:leaders]], "metric": metric},
        "evidence": {
            "next_rank": leaders + 1,
            "next_value": _json_num(values[leaders]),
            "lead_values": [_json_num(v) for v in values[:leaders]],
        },
    }


def _most_common(labels: list[str]) -> tuple[str, int] | None:
    """The label with the most rows; None when the top count is shared (no single holder)."""
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return None
    best = max(counts.values())
    holders = [label for label, n in counts.items() if n == best]
    return (holders[0], best) if len(holders) == 1 else None


def _concentration(rows: list[dict[str, Any]], metric: str, position_filter: Any) -> dict[str, Any] | None:
    total = len(rows)
    if total < MIN_ROWS:
        return None
    team = _most_common([r["team"] for r in rows if r["team"]])
    if team is not None and team[1] >= TEAM_MIN_COUNT and team[1] >= TEAM_SHARE_FIRES * total:
        return {"key": "concentration",
                "params": {"kind": "team", "value": team[0], "count": team[1], "total": total},
                "evidence": None}
    if position_filter or metric in _SINGLE_POSITION_METRICS:
        return None  # the list was asked for one position, or only one position has the metric
    position = _most_common([r["position"] for r in rows if r["position"]])
    if position is not None and position[1] >= POSITION_SHARE_FIRES * total:
        return {"key": "concentration",
                "params": {"kind": "position", "value": position[0], "count": position[1], "total": total},
                "evidence": None}
    return None


def _resolve(row: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any] | None:
    """The row's bootstrap element: by id when the row has one, else by web_name + team. None unless unique."""
    elements = [e for e in bootstrap.get("elements") or [] if isinstance(e, dict)]
    if row["id"] is not None:
        matches = [e for e in elements if e.get("id") == row["id"]]
    else:
        if row["team"] is None:
            return None
        team_ids = {t.get("id") for t in bootstrap.get("teams") or []
                    if isinstance(t, dict) and t.get("short_name") == row["team"]}
        matches = [e for e in elements if e.get("web_name") == row["name"] and e.get("team") in team_ids]
    return matches[0] if len(matches) == 1 else None


def _opportunity(rows: list[dict[str, Any]], metric: str, order: Any, bootstrap: Any) -> dict[str, Any] | None:
    if metric in NOT_A_MERIT_METRICS or not isinstance(bootstrap, dict):
        return None
    natural = "asc" if metric in LOWER_IS_BETTER else "desc"
    if order not in (None, natural):
        return None  # a "lowest N" list: its top is not where the good players are
    for row in rows[: (len(rows) + 1) // 2]:
        try:
            element = _resolve(row, bootstrap)
        except Exception:  # noqa: BLE001 -- a bad datum skips this row only
            element = None
        owned = _num(element.get("selected_by_percent")) if element else None
        if owned is not None and 0 <= owned < LOW_OWNERSHIP_PCT:
            return {"key": "opportunity",
                    "params": {"name": row["name"], "kind": "ownership"},
                    "evidence": {"value": owned}}
    return None


def _reading(rows: list[dict[str, Any]], metric: str, order: Any) -> dict[str, Any] | None:
    if not rows or metric not in SEASON_TOTAL_METRICS or order not in (None, "desc"):
        return None
    return {"key": "reading", "params": {"kind": "total_metric"}, "evidence": None}


def ranking_conclusions(
    rows: Any, metric: Any, bootstrap: Any, *, position_filter: Any = None, order: Any = None,
) -> list[dict[str, Any]]:
    """The conclusions for one metric ranking, in priority order, at most :data:`MAX_CONCLUSIONS`.

    *rows* is ``rank_players_by_metric``'s ``ranked`` list or a ``@resource`` ranking's ``rows``; *metric* is the
    canonical bootstrap field (the tool's ``metric``); *position_filter* and *order* are the tool's own output
    keys (None for a ``@resource`` ranking, which is unfiltered and descending). Empty list when no rule fires.
    """
    if not isinstance(metric, str) or not metric:
        return []
    try:
        table = _normalise(rows)
    except Exception:  # noqa: BLE001
        return []
    rules = (
        lambda: _gap(table, metric, order),
        lambda: _concentration(table, metric, position_filter),
        lambda: _opportunity(table, metric, order, bootstrap),
        lambda: _reading(table, metric, order),
    )
    out: list[dict[str, Any]] = []
    for rule in rules:
        try:
            item = rule()
        except Exception:  # noqa: BLE001 -- a bad datum drops this line only
            item = None
        if item is not None:
            out.append(item)
        if len(out) == MAX_CONCLUSIONS:
            break
    return out


def tool_ranking_conclusions(raw_output: Any, bootstrap: Any) -> list[dict[str, Any]]:
    """Conclusions for a ``rank_players_by_metric`` output; empty unless its status is ok."""
    if not isinstance(raw_output, dict) or raw_output.get("status") != "ok":
        return []
    return ranking_conclusions(
        raw_output.get("ranked"), raw_output.get("metric"), bootstrap,
        position_filter=raw_output.get("position_filter"), order=raw_output.get("order"),
    )


def resource_ranking_conclusions(resource: Any, resource_rows: Any, bootstrap: Any) -> list[dict[str, Any]]:
    """Conclusions for a ``@resource`` ranking (``ResourceResult.to_dict()``); empty for any other resource."""
    metric = RESOURCE_METRICS.get(resource) if isinstance(resource, str) else None
    if metric is None or not isinstance(resource_rows, dict):
        return []
    return ranking_conclusions(resource_rows.get("rows"), metric, bootstrap)
