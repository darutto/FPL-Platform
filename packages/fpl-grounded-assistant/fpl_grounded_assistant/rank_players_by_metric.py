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
The public API accepts common aliases (xgi, xg, xa, ict, popularity) in English
and Spanish. All aliases are resolved to the canonical bootstrap field name
before lookup, in three steps: exact match, then a unique-prefix completion,
then token containment for the Spanish noun phrases a model emits verbatim
("tiros libres directos" -> direct_freekicks_order). Containment never guesses:
a tie between two different fields returns ``unknown_metric``, and so does a
meaning-changing modifier the winning alias does not account for -- "contra",
"recibidos", "90". Without that guard "goles en contra" matched the one-token
alias "goles" and answered a goals-CONCEDED question with the top scorers.

Filters
-------
*  ``position``: optional filter (GKP/DEF/MID/FWD, case-insensitive).
*  ``min_minutes``: exclude players with fewer minutes than this threshold.
*  ``min_price`` / ``max_price``: inclusive GBP-million price bounds.

All filters are applied BEFORE sorting.

Direction
---------
``order`` ("desc" default / "asc") controls the sort. Without it a "cheapest
defenders" question received the ten most expensive ones and the model rescored
that set -- a fluent, confidently wrong answer citing real numbers. The applied
direction is echoed back as ``order`` so renderers can title accordingly.

An explicit ``order="asc"`` also raises ``min_minutes`` to a full match (60)
for accumulating metrics, because otherwise a player with no minutes has 0 of
everything and sorts to the top: "which keepers concede the fewest xG" returned
ten keepers tied at 0.0, none of whom had played. Exempt: ``now_cost`` (a 4.0m
player with no minutes is legitimate bench fodder) and the set-piece orders
(they already drop non-takers). The floor never overrides a larger caller
value, never applies under ``desc``, and is reported in ``min_minutes_filter``
rather than applied silently.

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
from fpl_grounded_assistant.ranking_provenance import get_ranking_basis


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
    # Goals CONCEDED — the real bootstrap field, distinct from its expected
    # counterpart. It had no alias in any language, so "goles en contra" fell
    # through to the one-token "goles" and ranked top SCORERS instead.
    "goals_conceded":                     "goals_conceded",
    "goles en contra":                    "goals_conceded",
    "goles recibidos":                    "goals_conceded",
    "goles concedidos":                   "goals_conceded",
    # Spanish phrasings the orchestrator emits verbatim (i18). Keys are stored
    # accent-free because `_normalize_metric` strips accents before lookup.
    "goles":                              "goals_scored",
    "goles esperados en contra":          "expected_goals_conceded",
    "goles esperados concedidos":         "expected_goals_conceded",
    "xg en contra":                       "expected_goals_conceded",
    "transferencias de entrada":          "transfers_in_event",
    "transferencias de salida":           "transfers_out_event",
    "propiedad":                          "selected_by_percent",
    "porcentaje de propiedad":            "selected_by_percent",
    "asistencias":                        "assists",
    "minutos":                            "minutes",
    "puntos":                             "total_points",
    "puntos por partido":                 "points_per_game",
    # The worst case in the residual tail (i43): the correct field already
    # exists, so "media de puntos" was returning a season TOTAL presented as an
    # average. Named aliases close it now; the general question of unmatched
    # tokens stays with the allowlist card.
    "media de puntos":                    "points_per_game",
    "promedio de puntos":                 "points_per_game",
    "porterias a cero":                   "clean_sheets",
    "porteria a cero":                    "clean_sheets",
    "vallas invictas":                    "clean_sheets",
    "valla invicta":                      "clean_sheets",
    "bonificaciones":                     "bonus",
    "goles esperados":                    "expected_goals",
    "asistencias esperadas":              "expected_assists",
    # Disambiguates against "tiros libres" (direct) under token containment:
    # without it, the longer phrase would resolve to the direct-freekick order.
    "tiros libres indirectos":            "corners_and_indirect_freekicks_order",
    # Spanish per-90 phrasings. Required, not optional: "90" is a meaning-
    # changing modifier (see _MEANING_CHANGING_MODIFIERS), so without these
    # keys every Spanish per-90 phrase is refused. With them each resolves to
    # the rate field rather than silently to the season total.
    "goles esperados por 90":             "expected_goals_per_90",
    "xg por 90":                          "expected_goals_per_90",
    "asistencias esperadas por 90":       "expected_assists_per_90",
    "xa por 90":                          "expected_assists_per_90",
    "xgi por 90":                         "expected_goal_involvements_per_90",
    "porterias a cero por 90":            "clean_sheets_per_90",
    "porteria a cero por 90":             "clean_sheets_per_90",
    "paradas por 90":                     "saves_per_90",
    "contribucion defensiva por 90":      "defensive_contribution_per_90",
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

# Sort directions. `order` is caller-supplied; `natural_order` is what applies
# when the caller supplies nothing.
_ORDER_DESC: str = "desc"
_ORDER_ASC:  str = "asc"


# Minutes floor applied under an EXPLICIT order="asc" (i44). Measured, not
# guessed: with the schema description alone the model passed min_minutes >= 60
# in only 2 of 6 live calls, and the value it does reach for unprompted is 1 --
# which filters nothing, because a player with one minute still has ~0 of every
# accumulating metric. Under "asc" that 0 sorts to the very top, so "which
# keepers concede the fewest xG" answered with ten keepers tied at 0.0, none of
# whom had played. Correct, and useless.
#
# A full match's worth of minutes is the smallest floor that actually separates
# "low" from "has not played". It is never silent: it is written into
# min_minutes_filter, which both renderers already surface.
_ASC_MIN_MINUTES_FLOOR: int = 60

# Metrics that must NOT get the floor under "asc":
#   now_cost -- a 4.0m player with no minutes is a legitimate bench-fodder
#     answer, and filtering it breaks a real use case.
#   set-piece orders -- already exclude non-takers by dropping values <= 0.
_NO_ASC_FLOOR: frozenset[str] = frozenset({"now_cost"}) | _LOWER_IS_BETTER


def natural_order(field_name: str) -> str:
    """Direction that ranks ``field_name`` best-first absent an explicit order.

    Descending for every metric except the set-piece orders, where being 1st on
    the list is the good end. Consumers use it to tell a "top N" ranking from
    one the caller deliberately inverted.
    """
    return _ORDER_ASC if field_name in _LOWER_IS_BETTER else _ORDER_DESC


def _normalize_metric(value: str) -> str:
    """Normalize accents/case without rewriting metric punctuation."""
    nfkd = unicodedata.normalize("NFKD", value)
    stripped = "".join(char for char in nfkd if not unicodedata.combining(char))
    return " ".join(stripped.lower().split())


# ---------------------------------------------------------------------------
# Token containment: resolving the Spanish phrase a model actually emits
# ---------------------------------------------------------------------------
# Measured (26 live calls, i18/i19): routing picks this tool 26/26, but 11 of
# those returned unknown_metric because the model emits the user's whole
# Spanish noun phrase -- "tiros libres directos", "amenaza ofensiva",
# "tiradores de penales" -- and the alias map only did exact equality plus a
# prefix relaxation in the useless direction (input a prefix OF a key). Every
# failing phrase CONTAINS its alias rather than prefixing it.
#
# Deliberately NOT fuzzy: an alias resolves only when all of its tokens appear
# in the input, and a tie between aliases of two DIFFERENT fields returns
# unknown_metric rather than guessing. That is what keeps i15 intact --
# invented metrics ("chispa ofensiva", "garra") share no token with any alias,
# so they still relay unknown_metric to the user.

#: Spanish function words and query framing that carry no metric information.
#: Stripped from both sides so "transferencias de entrada esta jornada" and
#: "transferencias de entrada" compare as the same token set.
_METRIC_STOPWORDS: frozenset[str] = frozenset({
    "de", "del", "la", "las", "los", "el", "en", "por", "esta", "este",
    "jornada", "gameweek", "liga", "temporada",
})


def _metric_tokens(value: str) -> frozenset[str]:
    """Content tokens of a metric phrase, accent- and case-insensitive."""
    return frozenset(
        token for token in _normalize_metric(value).split()
        if token not in _METRIC_STOPWORDS
    )


#: Tokens that change what a metric MEANS rather than merely describing it.
#: Containment works by discarding the input tokens no alias matched, which is
#: safe for filler ("de los defensas") and catastrophic for these: "goles en
#: contra" matched the one-token alias "goles", the unmatched "contra" was
#: dropped, and a question about goals CONCEDED was answered with the top
#: SCORERS -- real numbers, status ok, no signal. Before containment existed
#: that phrase returned unknown_metric, so the relaxation had turned a visible
#: failure into a fluent lie.
#:
#: So a modifier present in the input but absent from the winning alias vetoes
#: the match. Aliases that legitimately carry one ("goles en contra",
#: "goles esperados por 90") satisfy the guard by containing it; everything
#: else fails visibly. The veto covers the whole class, not just the phrasings
#: that have been observed.
#: Listed in every gender/number form Spanish agreement produces -- a
#: masculine-only set leaves "asistencias recibidas" unguarded.
_MEANING_CHANGING_MODIFIERS: frozenset[str] = frozenset({
    "contra",
    "recibido", "recibidos", "recibida", "recibidas",
    "concedido", "concedidos", "concedida", "concedidas",
    "anulado", "anulados", "anulada", "anuladas",
    "propia", "propias",
    # "esperado" separates a stat from its expected counterpart. Aliases that
    # mean the expected form carry the word, so they pass; "puntos esperados"
    # and "paradas esperadas" have no field at all and must fail visibly rather
    # than return the season total. "minutos esperados" matters most: it was
    # ranking raw minutes when get_expected_minutes is the tool that answers it.
    "esperado", "esperados", "esperada", "esperadas",
    "90",
})

#: (alias tokens, canonical field) for every alias with at least one content
#: token. Built once at import; the map is static.
_ALIAS_TOKEN_SETS: tuple[tuple[frozenset[str], str], ...] = tuple(
    (tokens, field)
    for tokens, field in (
        (_metric_tokens(alias), field) for alias, field in _METRIC_ALIASES.items()
    )
    if tokens
)


def _resolve_by_token_containment(normalized_metric: str) -> "str | None":
    """Resolve a phrase that contains an alias, or ``None`` if it is unsafe.

    The alias with the most matched tokens wins, so "goles esperados en contra"
    beats both "goles esperados" and "goles". Two ways to get ``None``, both
    deliberate: a tie between aliases of two different fields, and a
    meaning-changing modifier in the input that the winning alias does not
    account for. Neither guesses.
    """
    input_tokens = _metric_tokens(normalized_metric)
    if not input_tokens:
        return None

    best_size = 0
    winning_fields: set[str] = set()
    winning_tokens: set[str] = set()
    for alias_tokens, field in _ALIAS_TOKEN_SETS:
        if not alias_tokens <= input_tokens:
            continue
        size = len(alias_tokens)
        if size > best_size:
            best_size = size
            winning_fields, winning_tokens = {field}, set(alias_tokens)
        elif size == best_size:
            # Aliases of the same field collapse; distinct fields tie.
            winning_fields.add(field)
            winning_tokens |= alias_tokens

    if len(winning_fields) != 1:
        return None

    # A modifier the winning alias never accounted for would be silently
    # discarded, inverting or rescoping the metric the user asked for.
    unaccounted = (input_tokens & _MEANING_CHANGING_MODIFIERS) - winning_tokens
    if unaccounted:
        return None

    return next(iter(winning_fields))


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def rank_players_by_metric(
    metric: str,
    top_n: int = 10,
    position: "str | None" = None,
    min_minutes: int = 0,
    min_price: "float | None" = None,
    max_price: "float | None" = None,
    order: "str | None" = None,
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
        min_minutes: exclude players with fewer minutes (default 0). Raised to
            60 when ``order="asc"`` is explicit and the metric is not exempt;
            the value actually applied is returned in ``min_minutes_filter``.
        min_price: optional inclusive minimum price in GBP millions.
        max_price: optional inclusive maximum price in GBP millions.
        order: "desc" (default, highest first) or "asc" (lowest first, for
            *menos / más barato / menor / diferencial* questions). An explicit
            value overrides the metric's natural direction, so ``asc`` really
            does return the cheapest players rather than the most expensive.
            Unrecognized values fall back to the natural direction, which the
            returned ``order`` field always reports.
        bootstrap: live FPL bootstrap; fetched if None.

    Returns:
        # Success:
        {
            "status": "ok",
            "metric": <canonical field name>,
            "order": "desc" | "asc",   # direction actually applied
            "min_minutes_filter": <int>,  # includes any asc floor applied
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
            # Last resort: the input is a phrase that CONTAINS an alias.
            field_name = _resolve_by_token_containment(normalized_metric)

        if field_name is None:
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

    # Explicit order wins over the metric's natural direction, including for
    # the set-piece orders. Anything unrecognized falls back rather than
    # erroring -- and the applied direction is reported back in the payload.
    requested_order: "str | None" = None
    if isinstance(order, str):
        candidate = _normalize_metric(order)
        if candidate in (_ORDER_ASC, _ORDER_DESC):
            requested_order = candidate
    effective_order = requested_order or natural_order(field_name)

    # Ascending on an accumulating metric ranks "has not played" as best. Raise
    # the floor -- only on an EXPLICIT asc (a metric that merely sorts ascending
    # by nature is unaffected), never above a caller's own larger value, and
    # never for the two exempt families. `desc` is untouched.
    if requested_order == _ORDER_ASC and field_name not in _NO_ASC_FLOOR:
        min_minutes = max(min_minutes, _ASC_MIN_MINUTES_FLOOR)

    def _price_tenths(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return max(0, int(round(float(value) * 10)))
        except (TypeError, ValueError):
            return None

    min_cost = _price_tenths(min_price)
    max_cost = _price_tenths(max_price)
    min_price_filter = round(min_cost / 10, 1) if min_cost is not None else None
    max_price_filter = round(max_cost / 10, 1) if max_cost is not None else None
    ranking_basis = get_ranking_basis(bootstrap)

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
            "order":              effective_order,
            "top_n":              0,
            "position_filter":    canonical_position,
            "min_minutes_filter": min_minutes,
            "min_price_filter":   min_price_filter,
            "max_price_filter":   max_price_filter,
            "ranking_basis":      ranking_basis,
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

        el_cost = _safe_int(el.get("now_cost"), 0)
        if min_cost is not None and el_cost < min_cost:
            continue
        if max_cost is not None and el_cost > max_cost:
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
        reverse=effective_order == _ORDER_DESC,
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
        "order":              effective_order,
        "top_n":              len(ranked),
        "position_filter":    canonical_position,
        "min_minutes_filter": min_minutes,
        "min_price_filter":   min_price_filter,
        "max_price_filter":   max_price_filter,
        "ranking_basis":      ranking_basis,
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
        "and saves. Filter by position, minutes, and price bounds. "
        "Use for ANY top/best/most-by-metric query, and set order='asc' for the "
        "least/cheapest/lowest variants."
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
                "description": (
                    "Exclude players with fewer minutes (default 0). "
                    "SET THIS WHENEVER order='asc' on any accumulating metric -- goals, "
                    "assists, cards, xGC, saves, clean sheets, points, minutes and every "
                    "per-90 rate. A player who has not played has 0 of all of them, and "
                    "0 sorts to the very top of an ascending list, so the answer fills "
                    "with players who never appeared. Use at least a full match's worth "
                    "of minutes: 60-90. min_minutes=1 filters NOTHING -- one minute "
                    "still leaves ~0 in every accumulating metric. The exception is "
                    "price (now_cost), where a 4.0m player with no minutes is a "
                    "legitimate bench-fodder answer and no floor is wanted. If you "
                    "omit it under order='asc' the tool applies a 60-minute floor "
                    "itself and reports it in min_minutes_filter; pass your own value "
                    "when you want a different one."
                ),
                "minimum":     0,
            },
            "min_price": {
                "type":        "number",
                "description": "Inclusive minimum player price in GBP millions.",
                "minimum":     0,
            },
            "max_price": {
                "type":        "number",
                "description": "Inclusive maximum player price in GBP millions.",
                "minimum":     0,
            },
            "order": {
                "type":        "string",
                "enum":        ["desc", "asc"],
                "description": (
                    "Sort direction. Default 'desc' = highest value first. "
                    "Use 'asc' for LOWEST-first questions -- 'menos', 'más barato', "
                    "'más baratos', 'menor', 'peor', 'diferencial', 'cheapest', "
                    "'fewest', 'lowest'. Without it a 'cheapest defenders' question "
                    "gets the MOST expensive ones. With 'asc' on anything except "
                    "price, ALSO set min_minutes to at least 60 (a full match), or "
                    "every value ties at 0 and the list is players who never played."
                ),
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
            "order":              {"type": "string"},
            "top_n":              {"type": "integer"},
            "position_filter":    {"type": ["string", "null"]},
            "min_minutes_filter": {"type": "integer"},
            "min_price_filter":   {"type": ["number", "null"]},
            "max_price_filter":   {"type": ["number", "null"]},
            "ranking_basis":      {"type": "string"},
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
            min_price   = args.get("min_price"),
            max_price   = args.get("max_price"),
            order       = args.get("order"),
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
