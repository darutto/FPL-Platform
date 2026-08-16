"""
fpl_grounded_assistant.rank_players_by_metric
=============================================
P2.8 (Gap A fix): Atomic rank_players_by_metric tool — top N players ranked
by any numeric bootstrap metric.

Closes the "dame el top 10 de jugadores por xgi" class of queries that
previously returned branch=unsupported / outcome=no_tool.

Reuse
-----
*  ``_build_match_dict`` from ``find_players`` — single source of truth for
   the grounding payload.
*  ``_safe_float`` from ``find_players`` — numeric coercion with safe default.
*  ``_POSITION_MAP`` / ``_normalize`` from ``find_players`` — position labels
   and accent-strip utility.

Metric aliases
--------------
The public API accepts common aliases (xgi, xg, xa, ict, popularity).
All aliases are resolved to the canonical bootstrap field name before lookup.

Filters
-------
*  ``position``: optional filter (GKP/DEF/MID/FWD, case-insensitive).
*  ``min_minutes``: exclude players with fewer minutes than this threshold.

Both filters are applied BEFORE sorting.

Registration
------------
Registers ``rank_players_by_metric`` in ``TOOL_REGISTRY`` as a side-effect
of import.  ``__init__.py`` must import this module so
``run_tool("rank_players_by_metric", ...)`` works.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from fpl_grounded_assistant.find_players import (
    _build_match_dict,
    _safe_float,
    _safe_int,
    _normalize,
    _position_label,
)


# ---------------------------------------------------------------------------
# Metric alias map: public name (or alias) -> bootstrap element field name
# ---------------------------------------------------------------------------

_METRIC_ALIASES: dict[str, str] = {
    # Form & points
    "form":                           "form",
    "total_points":                   "total_points",
    "points":                         "total_points",
    "points_per_game":                "points_per_game",
    "ppg":                            "points_per_game",
    # xG stats
    "expected_goals":                 "expected_goals",
    "xg":                             "expected_goals",
    "expected_assists":               "expected_assists",
    "xa":                             "expected_assists",
    "expected_goal_involvements":     "expected_goal_involvements",
    "xgi":                            "expected_goal_involvements",
    # Other metrics
    "ict_index":                      "ict_index",
    "ict":                            "ict_index",
    "selected_by_percent":            "selected_by_percent",
    "popularity":                     "selected_by_percent",
    "ownership":                      "selected_by_percent",
    "minutes":                        "minutes",
    "goals_scored":                   "goals_scored",
    "goals":                          "goals_scored",
    "assists":                        "assists",
    "clean_sheets":                   "clean_sheets",
    "bonus":                          "bonus",
    "bps":                            "bps",
    # Per-90 rate stats. FPL supplies these fields directly on each element,
    # so ranking reads them the same generic way as the season totals above.
    # `_normalize` only lowercases + strips accents (keeps "/" and spaces), so
    # the alias keys below must match the raw phrasings users/LLMs emit.
    "expected_goals_per_90":              "expected_goals_per_90",
    "xg/90":                              "expected_goals_per_90",
    "xg_per_90":                          "expected_goals_per_90",
    "xg per 90":                          "expected_goals_per_90",
    "xg90":                               "expected_goals_per_90",
    "expected_assists_per_90":            "expected_assists_per_90",
    "xa/90":                              "expected_assists_per_90",
    "xa_per_90":                          "expected_assists_per_90",
    "xa per 90":                          "expected_assists_per_90",
    "xa90":                               "expected_assists_per_90",
    "expected_goal_involvements_per_90":  "expected_goal_involvements_per_90",
    "xgi/90":                             "expected_goal_involvements_per_90",
    "xgi_per_90":                         "expected_goal_involvements_per_90",
    "xgi per 90":                         "expected_goal_involvements_per_90",
    "xgi90":                              "expected_goal_involvements_per_90",
    "saves_per_90":                       "saves_per_90",
    "saves/90":                           "saves_per_90",
    "saves_per90":                        "saves_per_90",
    "saves per 90":                       "saves_per_90",
    "clean_sheets_per_90":                "clean_sheets_per_90",
    "cs/90":                              "clean_sheets_per_90",
    "cs_per_90":                          "clean_sheets_per_90",
    "clean sheets per 90":                "clean_sheets_per_90",
    "defensive_contribution_per_90":      "defensive_contribution_per_90",
    "dc/90":                              "defensive_contribution_per_90",
    "dc_per_90":                          "defensive_contribution_per_90",
    "defensive contribution per 90":      "defensive_contribution_per_90",
    # Price and current-GW transfer momentum (already in the grounding payload).
    "now_cost":                           "now_cost",
    "price":                              "now_cost",
    "precio":                             "now_cost",
    "cost":                               "now_cost",
    "transfers_in_event":                 "transfers_in_event",
    "transfers_in":                       "transfers_in_event",
    "transferencias entrantes":           "transfers_in_event",
    "momentum_in":                        "transfers_in_event",
    "transfers_out_event":                "transfers_out_event",
    "transfers_out":                      "transfers_out_event",
    "transferencias salientes":           "transfers_out_event",
    "momentum_out":                       "transfers_out_event",
    # Set-piece order (lower positive value is better).
    "penalties_order":                    "penalties_order",
    "penalty_order":                      "penalties_order",
    "penalties":                          "penalties_order",
    "penales":                            "penalties_order",
    "direct_freekicks_order":             "direct_freekicks_order",
    "free_kick_order":                    "direct_freekicks_order",
    "free kicks":                         "direct_freekicks_order",
    "tiros libres":                       "direct_freekicks_order",
    "corners_and_indirect_freekicks_order": "corners_and_indirect_freekicks_order",
    "corners_order":                      "corners_and_indirect_freekicks_order",
    "corner_order":                       "corners_and_indirect_freekicks_order",
    "corners":                            "corners_and_indirect_freekicks_order",
    "corner kicks":                       "corners_and_indirect_freekicks_order",
    "corners y tiros libres indirectos":  "corners_and_indirect_freekicks_order",
    # Additional season totals supplied by the bootstrap.
    "yellow_cards":                       "yellow_cards",
    "yellow cards":                       "yellow_cards",
    "tarjetas amarillas":                 "yellow_cards",
    "red_cards":                          "red_cards",
    "red cards":                          "red_cards",
    "tarjetas rojas":                     "red_cards",
    "expected_goals_conceded":            "expected_goals_conceded",
    "xgc":                                "expected_goals_conceded",
    "influence":                          "influence",
    "influencia":                         "influence",
    "creativity":                         "creativity",
    "creatividad":                        "creativity",
    "threat":                             "threat",
    "amenaza":                            "threat",
    "saves":                              "saves",
    "paradas":                            "saves",
}

#: Sorted list of canonical metric names exposed to users.
_VALID_METRICS: list[str] = sorted(set(_METRIC_ALIASES.keys()))

#: Position filter map: normalized input -> canonical label
_POSITION_FILTER_MAP: dict[str, str] = {
    "gkp": "GKP",
    "goalkeeper": "GKP",
    "portero": "GKP",
    "def": "DEF",
    "defender": "DEF",
    "defensa": "DEF",
    "mid": "MID",
    "midfielder": "MID",
    "centrocampista": "MID",
    "medio": "MID",
    "fwd": "FWD",
    "forward": "FWD",
    "delantero": "FWD",
}

_TOP_N_CAP: int = 50

# Set-piece list positions are the only supported metrics where 1 ranks above
# 2. Missing/zero order means the player is not listed and is excluded.
_LOWER_IS_BETTER: frozenset[str] = frozenset({
    "penalties_order",
    "direct_freekicks_order",
    "corners_and_indirect_freekicks_order",
})

# now_cost is stored by FPL in tenths of a million; expose the user-facing £m
# value while retaining the raw now_cost in each grounding payload.
_METRIC_VALUE_SCALE: dict[str, float] = {"now_cost": 0.1}


def _normalize_metric(value: str) -> str:
    """Normalize accents/case without rewriting metric punctuation."""
    nfkd = unicodedata.normalize("NFKD", value)
    stripped = "".join(char for char in nfkd if not unicodedata.combining(char))
    return " ".join(stripped.lower().split())


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def rank_players_by_metric(
    metric: str,
    top_n: int = 10,
    position: "str | None" = None,
    min_minutes: int = 0,
    bootstrap: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """Rank players by a numeric bootstrap metric.

    Args:
        metric: metric name or alias (case/accent-insensitive). Supports core
            performance totals and per-90 rates, price, current-GW transfers,
            set-piece order, cards, xGC, ICT components, and saves.
        top_n: max results (1-50, default 10). Silently capped at 50.
        position: optional position filter (GKP/DEF/MID/FWD, case-insensitive).
            Also accepts Spanish names (portero/defensa/centrocampista/delantero).
        min_minutes: exclude players with fewer minutes (default 0).
        bootstrap: live FPL bootstrap; fetched if None.

    Returns:
        # Success:
        {
            "status": "ok",
            "metric": <canonical field name>,
            "top_n": <int>,
            "position_filter": <str | None>,
            "min_minutes_filter": <int>,
            "ranked": [
                {
                    # Full grounding payload (including match_rank=0)
                    # PLUS:
                    "metric_value": <float>,
                    "rank": <int>   # 1-based
                },
                ...
            ]
        }
        # Invalid metric:
        {
            "status": "invalid_argument",
            "code": "unknown_metric",
            "message": "Metric '<m>' not recognized. Try: <list>.",
            "valid_metrics": [<str>, ...]
        }
        # No players match filters:
        {
            "status": "ok",
            "metric": <str>,
            "top_n": 0,
            "position_filter": <str | None>,
            "min_minutes_filter": <int>,
            "ranked": []
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate inputs
    # ------------------------------------------------------------------
    if not isinstance(metric, str) or not metric.strip():
        return {
            "status":        "invalid_argument",
            "code":          "unknown_metric",
            "message":       "Metric must be a non-empty string.",
            "valid_metrics": _VALID_METRICS,
        }

    normalized_metric = _normalize_metric(metric.strip())
    field_name = _METRIC_ALIASES.get(normalized_metric)

    if field_name is None:
        # Try partial: if input is a prefix of exactly one metric, resolve.
        partial_matches = [k for k in _METRIC_ALIASES if k.startswith(normalized_metric)]
        # Prefer a uniquely shortest completion when all longer candidates are
        # variants of the same base metric (e.g. base total and its per-90 form).
        shortest_matches: list[str] = []
        if partial_matches:
            shortest_length = min(len(candidate) for candidate in partial_matches)
            shortest_matches = [
                candidate for candidate in partial_matches if len(candidate) == shortest_length
            ]
        shortest_field = (
            _METRIC_ALIASES[shortest_matches[0]] if len(shortest_matches) == 1 else None
        )
        same_metric_family = shortest_field is not None and all(
            _METRIC_ALIASES[candidate] == shortest_field
            or _METRIC_ALIASES[candidate].startswith(f"{shortest_field}_")
            for candidate in partial_matches
        )
        if len(shortest_matches) == 1 and same_metric_family:
            normalized_metric = shortest_matches[0]
            field_name = shortest_field
        else:
            return {
                "status":        "invalid_argument",
                "code":          "unknown_metric",
                "message":       (
                    f"Metric '{metric}' not recognized. "
                    f"Try: {', '.join(_VALID_METRICS[:15])} ..."
                ),
                "valid_metrics": _VALID_METRICS,
            }

    # Silent cap on top_n
    try:
        top_n = max(1, min(int(top_n), _TOP_N_CAP))
    except (ValueError, TypeError):
        top_n = 10

    # Silent floor on min_minutes
    try:
        min_minutes = max(0, int(min_minutes))
    except (ValueError, TypeError):
        min_minutes = 0

    # Resolve position filter
    canonical_position: "str | None" = None
    if position is not None and isinstance(position, str) and position.strip():
        pos_key = _normalize(position.strip())
        canonical_position = _POSITION_FILTER_MAP.get(pos_key)
        if canonical_position is None:
            # Accept direct canonical forms: GKP/DEF/MID/FWD
            pos_upper = position.strip().upper()
            if pos_upper in ("GKP", "DEF", "MID", "FWD"):
                canonical_position = pos_upper

    # ------------------------------------------------------------------
    # 1. Guard: bootstrap required
    # ------------------------------------------------------------------
    if bootstrap is None:
        return {
            "status":             "ok",
            "metric":             field_name,
            "top_n":              0,
            "position_filter":    canonical_position,
            "min_minutes_filter": min_minutes,
            "ranked":             [],
        }

    elements:      list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams:         list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    # ------------------------------------------------------------------
    # 2. Apply filters
    # ------------------------------------------------------------------
    filtered: list[dict[str, Any]] = []

    for el in elements:
        # Minutes filter
        el_minutes = _safe_int(el.get("minutes"), 0)
        if el_minutes < min_minutes:
            continue

        # Position filter
        if canonical_position is not None:
            el_position = _position_label(el, element_types)
            if el_position != canonical_position:
                continue

        # Null/zero set-piece order means the player is not on that list.
        if field_name in _LOWER_IS_BETTER and _safe_int(el.get(field_name), 0) <= 0:
            continue

        filtered.append(el)

    # ------------------------------------------------------------------
    # 3. Sort by metric direction (descending normally; ascending for order)
    # ------------------------------------------------------------------
    def _raw_metric_value(el: dict[str, Any]) -> float:
        return _safe_float(el.get(field_name), 0.0)

    filtered.sort(
        key=_raw_metric_value,
        reverse=field_name not in _LOWER_IS_BETTER,
    )

    def _metric_value(el: dict[str, Any]) -> float:
        scale = _METRIC_VALUE_SCALE.get(field_name, 1.0)
        return _raw_metric_value(el) * scale

    # ------------------------------------------------------------------
    # 4. Build ranked list
    # ------------------------------------------------------------------
    top = filtered[:top_n]

    ranked: list[dict[str, Any]] = []
    for rank_idx, el in enumerate(top, start=1):
        payload = _build_match_dict(el, teams, element_types, match_rank=0)
        payload["metric_value"] = _metric_value(el)
        payload["rank"] = rank_idx
        ranked.append(payload)

    return {
        "status":             "ok",
        "metric":             field_name,
        "top_n":              len(ranked),
        "position_filter":    canonical_position,
        "min_minutes_filter": min_minutes,
        "ranked":             ranked,
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

RANK_PLAYERS_BY_METRIC_SPEC = ToolSpec(
    name="rank_players_by_metric",
    description=(
        "Top N players by a bootstrap metric: performance, per-90 rates, price, "
        "current-GW transfer momentum, set-piece order, cards, xGC, ICT components, "
        "and saves. Filter by position/min_minutes. Use for ANY top/best/most-by-metric query."
    ),
    parameters={
        "type": "object",
        "properties": {
            "metric": {
                "type":        "string",
                "description": (
                    "Metric to rank by. Common aliases include xgi, xg, xa, ict, ppg, "
                    "xgi/90, price/precio, transfers_in/out, penalties/penales, corners, "
                    "free kicks/tiros libres, yellow/red cards, xgc, influence, creativity, "
                    "threat, and saves/paradas. Unknown values must still be passed through "
                    "so the tool can return unknown_metric with valid_metrics."
                ),
            },
            "top_n": {
                "type":        "integer",
                "description": "Max players to return (1-50, default 10)",
                "minimum":     1,
                "maximum":     50,
            },
            "position": {
                "type":        "string",
                "description": (
                    "Optional position filter: GKP/DEF/MID/FWD (case-insensitive). "
                    "Spanish names accepted: portero/defensa/centrocampista/delantero."
                ),
            },
            "min_minutes": {
                "type":        "integer",
                "description": "Exclude players with fewer minutes (default 0)",
                "minimum":     0,
            },
        },
        "required":             ["metric"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":             {"type": "string"},
            "metric":             {"type": "string"},
            "top_n":              {"type": "integer"},
            "position_filter":    {"type": ["string", "null"]},
            "min_minutes_filter": {"type": "integer"},
            "ranked":             {"type": "array"},
        },
    },
)


def _rank_players_by_metric_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``rank_players_by_metric()``."""
    try:
        metric = args.get("metric")
        if not metric:
            return {
                "status":        "invalid_argument",
                "code":          "unknown_metric",
                "message":       "metric is required.",
                "valid_metrics": _VALID_METRICS,
            }
        return rank_players_by_metric(
            metric      = metric,
            top_n       = args.get("top_n", 10),
            position    = args.get("position"),
            min_minutes = args.get("min_minutes", 0),
            bootstrap   = bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"rank_players_by_metric raised an unexpected error: {exc}",
        }


# Register with the shared tool registry.
TOOL_REGISTRY.register(RANK_PLAYERS_BY_METRIC_SPEC, _rank_players_by_metric_handler)
