"""The ``query`` door: the tool the model is offered, and what one call of it does (query layer, PR 6).

The tool's name, description, parameters and the prompt text live in ``query_door_text`` (frozen).

    one call -> unwrap (quotes are evidence) -> parse_spec -> apply_brakes -> load gameweeks -> run_query
             -> the public ``query`` block (``query_contract``)

The model writes nothing the user reads: the turn ends with the block's code-written text.

Offered only when ``FPL_QUERY_LAYER`` is on; then ``rank_players_by_metric`` is withdrawn from the model.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant import query_contract as contract
from fpl_grounded_assistant.gw_live_cache import default_cache
from fpl_grounded_assistant.query_brakes import apply_brakes
from fpl_grounded_assistant.query_door_text import QUERY_DESCRIPTION, QUERY_PARAMETERS, QUERY_TOOL_NAME
from fpl_grounded_assistant.query_engine import needed_gameweeks, run_query
from fpl_grounded_assistant.query_spec import QuerySpecError, parse_spec
from fpl_grounded_assistant.rank_condition_guard import RAW_QUESTION_KEY

_LOG = logging.getLogger(__name__)

#: Per-turn bootstrap keys the orchestrator sets (a shallow, request-local copy).
LOCALE_KEY = "_query_locale"
#: Test seams: the day dates are placed from, and the gameweek source.
TODAY_KEY = "_query_today"
CACHE_KEY = "_query_cache"
_QUESTION_KEY = "_question"

# ----------------------------------------------------------------------------------------------------- one call

_WRAPPED = ("metric", "shape", "grain", "operator", "order", "top_n")
_BARE_WRAPPED = ("metric_minus", "metric_plus")
_LISTS: dict[str, frozenset[str]] = {
    "match_set": frozenset({"pred", "value"}), "compare_to": frozenset({"pred", "value"}),
    "filters": frozenset({"field", "op", "value"}), "not_expressible": frozenset({"kind"}),
    "ambiguous": frozenset(),
}


def unwrap_call(args: Any) -> tuple[dict[str, Any], list[dict], list[dict]]:
    """The model's wire form -> (flat spec, not_expressible, ambiguous). Strict about shape; quotes are dropped
    from the spec and kept on the two reports, whose quotes the brakes read."""
    if not isinstance(args, dict) or set(args) - set(QUERY_PARAMETERS["properties"]):
        raise QuerySpecError("unknown_key", "call")
    spec: dict[str, Any] = {}
    reports: dict[str, list[dict]] = {"not_expressible": [], "ambiguous": []}
    for key, value in args.items():
        if key in _WRAPPED or key in _BARE_WRAPPED:
            allowed = {"value", "quote"} if key in _WRAPPED else {"value"}
            if not isinstance(value, dict) or "value" not in value or set(value) - allowed:
                raise QuerySpecError("bad_type", key)
            spec[key] = value["value"]
            continue
        keys = _LISTS[key]
        if not isinstance(value, list) or not all(
                isinstance(i, dict) and keys <= set(i) <= keys | {"quote"} for i in value):
            raise QuerySpecError("bad_type", key)
        if key in reports:
            reports[key] = [dict(i) for i in value]
        else:
            spec[key] = [{k: v for k, v in i.items() if k != "quote"} for i in value]
    unknown = [i for i in reports["not_expressible"] if i.get("kind") not in cat.UNSUPPORTED_KINDS]
    if unknown:
        raise QuerySpecError("bad_value", "not_expressible")
    return spec, reports["not_expressible"], reports["ambiguous"]


def _today(bootstrap: dict[str, Any]) -> dt.date:
    return bootstrap.get(TODAY_KEY) or dt.datetime.now(tz=dt.timezone.utc).date()


def answer_call(args: Any, bootstrap: dict[str, Any]) -> dict[str, Any]:
    """One ``query`` call -> the tool output ``{status, query, query_audit}``. Never raises."""
    lang = "en" if bootstrap.get(LOCALE_KEY) == "en" else "es"
    try:
        return _answer(args, bootstrap, lang)
    except QuerySpecError as error:
        return contract.refused(lang, contract.NEEDS_CLARIFICATION, "invalid_spec", detail=error.code)
    except Exception:  # noqa: BLE001 -- an honest "no data" beats any other tool answering in its place
        _LOG.exception("query call failed")
        return contract.refused(lang, contract.DATA_UNAVAILABLE, "internal_error")


def _answer(args: Any, bootstrap: dict[str, Any], lang: str) -> dict[str, Any]:
    flat, not_expressible, ambiguous = unwrap_call(args)
    if "metric" not in flat:                          # nothing to compute: say what was reported instead
        if not_expressible:
            kinds = tuple(dict.fromkeys(str(i["kind"]) for i in not_expressible))
            return contract.refused(lang, contract.UNSUPPORTED, kinds[0], kinds=kinds, brake="B3")
        if ambiguous:
            return contract.refused(lang, contract.NEEDS_CLARIFICATION, "ambiguous_phrase", brake="ambiguous")
    spec = parse_spec(flat)
    raw_text = bootstrap.get(RAW_QUESTION_KEY) or bootstrap.get(_QUESTION_KEY) or ""
    braked = apply_brakes(spec, str(raw_text), bootstrap, _today(bootstrap), lang,
                          not_expressible=not_expressible, ambiguous=ambiguous)
    if braked.state is not None:
        return contract.build(braked.spec, braked.as_query_result(), bootstrap, lang,
                              chips=braked.chips, brake=braked.brake)
    return run_spec(braked.spec, bootstrap, lang, unused=braked.unused)


def run_spec(spec: Any, bootstrap: dict[str, Any], lang: str, unused: tuple[str, ...] = ()) -> dict[str, Any]:
    """Execute a braked-and-dated spec: load its gameweeks, run it, build the tool output."""
    wanted = needed_gameweeks(spec, bootstrap)
    cache = bootstrap.get(CACHE_KEY) or (default_cache() if wanted else None)
    batch = cache.load(wanted, bootstrap) if wanted else None
    return contract.build(spec, run_query(spec, bootstrap, batch), bootstrap, lang, unused=unused)


QUERY_SPEC = ToolSpec(name=QUERY_TOOL_NAME, description=QUERY_DESCRIPTION, parameters=QUERY_PARAMETERS,
                      output_schema={"type": "object"})

TOOL_REGISTRY.register(QUERY_SPEC, answer_call)
