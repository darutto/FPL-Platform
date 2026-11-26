"""The query door's frozen texts: the tool the model is offered and the prompt that points to it.

**Byte-identical to the probe's round-4 freeze** (``tests/fixtures/query_door_freeze.json`` pins them).
Change them only with a new measured freeze. Pure data: this module imports only the catalogue.
"""
from __future__ import annotations

from typing import Any

from fpl_grounded_assistant import query_catalogue as cat

QUERY_TOOL_NAME = "query"

# --------------------------------------------------------------------------------------- the frozen tool schema

_METRICS = list(cat.METRICS)
_OPERATORS = list(cat.OPERATORS)

_Q = {"type": ["string", "array"], "items": {"type": "string"},
      "description": "Words copied from the user's message that state this constraint; several short quotes may be a list."}


def _wrapped(value_schema: dict, desc: str, quote_required: bool) -> dict:
    return {"type": "object", "description": desc,
            "properties": {"value": value_schema, "quote": _Q},
            "required": ["value", "quote"] if quote_required else ["value"]}


def build_query_parameters() -> tuple[str, dict[str, Any]]:
    """(description, parameters) of the ``query`` tool."""
    metric_value = {"type": "string", "enum": _METRICS}
    metric_desc = ("The statistic asked for: an id from the list; at team grain use the team_ ids. If no id means what the user asked for, "
                   "do not pick the nearest one: report it in not_expressible or ambiguous.")
    desc = (
        "The one tool for questions that rank, list, total or compare players or teams on a statistic, over a "
        "window of matches, with filters, or that compare two sets of matches (for example with and without a "
        "player). Fill a field only with what the user stated; every constraint carries a `quote` copied "
        "from the user's message (at most 12 words each; give several short quotes as a list when the words are "
        "apart). Leave out anything the user did not say: unstated "
        "fields take declared defaults (list, player, sum, whole season, desc, top 10). A word of the question "
        "that states a constraint must be inside some quote. If the question asks for something this form cannot "
        "state, put it in not_expressible with its kind (single_value only when the question asks for ONE number, "
        "not a list); if a phrase is vague, put it in ambiguous. "
        "match_set is the FIRST set of matches and compare_to the SECOND (only with shape comparison). "
        "At team grain a named club ALWAYS goes in filters as club eq (grain alone does not select a club). "
        "Ownership as it was AT THAT TIME ('then', 'at the time', 'en ese momento', 'entonces') is not owned_now: "
        "report it in not_expressible with kind ownership_then. "
        "Dates: send the day and month as MM-DD; add the year (YYYY-MM-DD) ONLY when the user wrote a year. "
        "Operator plus adds two statistics: metric plus metric_plus. "
        "Example with/without: 'Team T xG with and without Player A' = shape comparison, grain team, filters "
        "[club eq 'Team T'], match_set [player_played_60 'Player A'], compare_to [player_absent 'Player A']. Example periods: 'goals in GW1-5 "
        "against GW6-10' = shape comparison, match_set [gw_range [1,5]], compare_to [gw_range [6,10]]. For "
        "player_played_60 and player_absent the quote is just the player's name. "
        "Unsupported-kind ids: " + ", ".join(cat.UNSUPPORTED_KINDS) + "."
    )
    preds = {"type": "object", "properties": {
        "pred": {"type": "string", "enum": list(cat.PREDICATES)},
        "value": {"description": "season: true; last_n/gw: integer; gw_range: [from,to]; since_date: MM-DD (YYYY-MM-DD only if the user wrote the year); "
                                 "player_played_60/player_absent: the player as written; venue: home|away (team grain)."},
        "quote": _Q}, "required": ["pred", "value", "quote"]}
    metric_desc += (" Phrases that name one id: " + "; ".join(
        f"'{phrase}' = {target}" if "+" not in target else
        f"'{phrase}' = operator plus, metric {target.split('+')[0]}, metric_plus {target.split('+')[1]}"
        for phrase, target in cat.METRIC_PHRASES.items()) + ".")
    props: dict[str, Any] = {
        "metric": _wrapped(metric_value, metric_desc, True),
        "metric_minus": {"type": "object", "description": "Only with operator minus: the second statistic (metric minus this).",
                         "properties": {"value": {"type": "string", "enum": _METRICS}}, "required": ["value"]},
        "metric_plus": {"type": "object", "description": "Only with operator plus: the second statistic (metric plus this).",
                        "properties": {"value": {"type": "string", "enum": _METRICS}}, "required": ["value"]},
        "shape": _wrapped({"type": "string", "enum": list(cat.SHAPES)}, "list (default) or comparison of two match sets.", False),
        "grain": _wrapped({"type": "string", "enum": list(cat.GRAINS)}, "player (default) or team.", False),
        "operator": _wrapped({"type": "string", "enum": _OPERATORS}, "sum (default), per_match, per_90, per_million, minus, plus.", False),
        "match_set": {"type": "array", "description": "The FIRST set of matches: AND of predicates; absent = whole season.", "items": preds},
        "compare_to": {"type": "array", "description": "The SECOND set of matches, only for shape=comparison.", "items": preds},
        "filters": {"type": "array", "description": "Filters on players or teams.", "items": {"type": "object", "properties": {
            "field": {"type": "string", "enum": list(cat.FILTER_FIELDS)},
            "op": {"type": "string", "enum": list(cat.OPS)},
            "value": {"description": "position GKP|DEF|MID|FWD; price in millions; club as written; owned_now percent "
                                     "or \"low\"; minutes_in_window integer; set_piece penalties|direct_freekicks|corners."},
            "quote": _Q}, "required": ["field", "op", "value", "quote"]}},
        "order": _wrapped({"type": "string", "enum": ["asc", "desc"]}, "Sort direction (default desc; asc for set-piece orders).", False),
        "top_n": _wrapped({"type": "integer"}, "How many rows (default 10).", False),
        "not_expressible": {"type": "array", "description": "Constraints the form cannot state.", "items": {"type": "object",
                            "properties": {"kind": {"type": "string", "enum": list(cat.UNSUPPORTED_KINDS)}, "quote": _Q},
                            "required": ["kind", "quote"]}},
        "ambiguous": {"type": "array", "description": "Vague phrases that need a question to the user.", "items": {"type": "object",
                      "properties": {"quote": _Q}, "required": ["quote"]}},
    }
    return desc, {"type": "object", "properties": props, "additionalProperties": False}


QUERY_DESCRIPTION, QUERY_PARAMETERS = build_query_parameters()

# ------------------------------------------------------------------------------- the frozen prompt and tool texts

_OVERRIDE_START = "RANKING-BY-METRIC OVERRIDE (highest tool-routing priority):\n"
_OVERRIDE_END = "or fail silently.\n"
OVERRIDE_BLOCK = (
    "RANKING-BY-METRIC OVERRIDE (highest tool-routing priority):\n"
    "  - Any request to rank, order, list, total or compare players OR teams BY a named metric/statistic,\n"
    "    over a season, one gameweek, the last N gameweeks, a range, since a date, with filters (position,\n"
    "    price, club, ownership) or WITH vs WITHOUT a player (two sets of matches)\n"
    "    → call query FIRST and as the ONLY tool. Fill only what the user stated, each with its quote.\n"
    "  - Never choose another tool from keyword overlap in the metric (for example, do\n"
    "    not choose a gameweek tool because the requested metric mentions gameweek/jornada).\n"
    "  - If the metric is unfamiliar or no listed id means it, do not pick the nearest id: report it in\n"
    "    not_expressible or ambiguous. Do not synthesize a ranking from other data or fail silently.\n"
)
PROMPT_REPLACEMENTS = (
    ("get_chip_advice, get_transfer_suggestion, rank_players_by_metric)",
     "get_chip_advice, get_transfer_suggestion, query)"),
    ("rank_players_by_metric, get_player_form, get_differential_picks",
     "query, get_player_form, get_differential_picks"),
)
#: Two other tools' descriptions pointed at the ranking; with the door on they point here.
SCHEMA_EDITS: dict[str, tuple[str, str]] = {
    "get_historical_gameweek_top_scorer": (
        "Goals over the WHOLE SEASON are rank_players_by_metric(goals_scored). Goals in ONE gameweek, the last N "
        "or a range have NO tool: say so plainly and never answer with points instead. ",
        "Goals, or any other statistic, over a season, ONE gameweek, the last N gameweeks or a range are the "
        "query tool (metric goals_scored): never answer with points instead. ",
    ),
    "get_team_results": ("not a player ranking (rank_players_by_metric).", "not a player ranking (query)."),
}


def rewrite_prompt(base: str) -> str:
    """The orchestrator prompt with the door on. Raises if an anchor moved: a silent half-rewrite would send
    the model after a withdrawn tool."""
    start = base.index(_OVERRIDE_START)
    end = base.index(_OVERRIDE_END, start) + len(_OVERRIDE_END)
    out = base[:start] + OVERRIDE_BLOCK + base[end:]
    for old, new in PROMPT_REPLACEMENTS:
        if out.count(old) != 1:
            raise RuntimeError(f"query door: prompt anchor not found exactly once: {old[:40]!r}")
        out = out.replace(old, new)
    if "rank_players_by_metric" in out:
        raise RuntimeError("query door: the prompt still names the withdrawn ranking tool")
    return out


def rewrite_description(tool: str, description: str) -> str:
    edit = SCHEMA_EDITS.get(tool)
    if edit is None:
        return description
    if description.count(edit[0]) != 1:
        raise RuntimeError(f"query door: description anchor not found exactly once in {tool}")
    return description.replace(edit[0], edit[1])
