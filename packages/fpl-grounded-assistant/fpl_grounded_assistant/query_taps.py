"""Corrections to the last validated spec: a tapped pill, or the parts a typed follow-up states. No model, no
text, no labels (the reading line renders those).

    alternatives(spec)           -> {part: (Alternative, ...)} for the pills that open
    apply_tap(spec, part, value) -> the spec with that one part changed
    apply_stated(spec, stated)   -> the spec with every stated part changed, the rest inherited
    changed_parts(old, new)      -> which parts differ (the highlight, and the ``corrected_part`` audit enum)

Every new spec goes through ``parse_spec``: a correction can never build what the strict parse would refuse.
A tap value is checked by that parse, not against the offered list, so a pill from an older answer still works
or is refused for a real reason.

Tap values (JSON): ``window`` {"pred", "value"}; ``ownership`` / ``price`` / ``minutes`` {"op", "value"};
``position`` "MID". ``None`` removes the filter (all players, all positions, only the automatic floor).

Nothing imports this module at runtime yet (query layer, PR 8; the wiring follows PR 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_spec import WINDOW_PREDICATES, QuerySpec, QuerySpecError, parse_spec

#: The parts of a spec, in the reading line's order. Also the values of the ``corrected_part`` audit enum.
PARTS: tuple[str, ...] = ("grain", "metric", "window", "match_set", "ownership", "price", "position", "club",
                          "set_piece", "minutes", "top_n")
#: Pills that open. Metric and club are corrected by typing.
EDITABLE: tuple[str, ...] = ("window", "ownership", "price", "position", "minutes")

_FILTER_PART = {"owned_now": "ownership", "price": "price", "position": "position", "club": "club",
                "set_piece": "set_piece", "minutes_in_window": "minutes"}
_PART_FIELD = {part: field for field, part in _FILTER_PART.items()}

_WINDOWS = (("last_n", 3), ("last_n", 5), ("last_n", 10), ("season", True))
_OWNERSHIP = (5, 10, 15)
_PRICES = (5.0, 6.0, 7.0, 8.0)
_MINUTES = (270, 450, 900)


@dataclass(frozen=True)
class Alternative:
    value: Any                       # what a tap sends back; None removes the part
    selected: bool


# ----------------------------------------------------------------------------------------------- which pills

def _window_of(preds: Any) -> dict[str, Any]:
    return next((p for p in preds if p["pred"] in WINDOW_PREDICATES), {"pred": "season", "value": True})


def window_is_editable(spec: QuerySpec) -> bool:
    """One window to change: not for today's-value metrics, nor when a comparison is between two periods."""
    if cat.METRICS[spec.metric].group == "snapshot":
        return False
    if spec.compare_to is None:
        return True
    raw = spec.to_dict()
    return _window_of(raw["match_set"]) == _window_of(raw["compare_to"])


def alternatives(spec: QuerySpec, floor_applied: int = 0) -> dict[str, tuple[Alternative, ...]]:
    """The options of each pill that opens for *spec*. *floor_applied* is the result's ``min_minutes``:
    a minutes option at or under it would change nothing, so it is not offered."""
    raw = spec.to_dict()
    out: dict[str, tuple[Alternative, ...]] = {}
    if window_is_editable(spec):
        current = _window_of(raw["match_set"])
        out["window"] = tuple(Alternative({"pred": p, "value": v}, current == {"pred": p, "value": v})
                              for p, v in _WINDOWS)
    if spec.grain != "player":                    # a team row has no ownership, price, position or minutes
        return out

    def current_filters(part: str) -> list[tuple[str, Any]]:
        return [(f["op"], f["value"]) for f in raw["filters"] if f["field"] == _PART_FIELD[part]]

    def thresholds(part: str, op: str, values: tuple) -> tuple[Alternative, ...]:
        now = current_filters(part)
        listed = [Alternative({"op": op, "value": v}, now == [(op, v)]) for v in values]
        return tuple(listed + [Alternative(None, not now)])

    out["ownership"] = thresholds("ownership", "lt", _OWNERSHIP)
    out["price"] = thresholds("price", "le", _PRICES)
    now = current_filters("position")
    out["position"] = tuple([Alternative(p, now == [("eq", p)]) for p in cat.POSITIONS]
                            + [Alternative(None, not now)])
    minutes = tuple(v for v in _MINUTES if v > floor_applied)
    if floor_applied or current_filters("minutes"):          # shown with a floor or a stated minimum only
        out["minutes"] = thresholds("minutes", "ge", minutes)
    return out


# ------------------------------------------------------------------------------------------------- one change

def _with_window(preds: list[dict], window: Mapping[str, Any]) -> list[dict]:
    return [dict(window)] + [p for p in preds if p["pred"] not in WINDOW_PREDICATES]


def _with_filter(filters: list[dict], field: str, new: list[dict]) -> list[dict]:
    return [f for f in filters if f["field"] != field] + new


def apply_tap(spec: QuerySpec, part: str, value: Any) -> QuerySpec:
    """*spec* with the tapped part set to *value*. :class:`QuerySpecError` when the tap cannot apply."""
    if part not in EDITABLE:
        raise QuerySpecError("bad_value", "tap.part")
    raw = spec.to_dict()
    if part == "window":
        if not window_is_editable(spec) or not isinstance(value, dict) or set(value) != {"pred", "value"} \
                or value["pred"] not in WINDOW_PREDICATES:
            raise QuerySpecError("bad_value", "tap.window")
        raw["match_set"] = _with_window(raw["match_set"], value)
        if "compare_to" in raw:
            raw["compare_to"] = _with_window(raw["compare_to"], value)
        return parse_spec(raw)
    field = _PART_FIELD[part]
    if value is None:
        new = []
    elif part == "position":
        new = [{"field": field, "op": "eq", "value": value}]
    elif isinstance(value, dict) and set(value) == {"op", "value"}:
        new = [{"field": field, "op": value["op"], "value": value["value"]}]
    else:
        raise QuerySpecError("bad_type", f"tap.{part}")
    raw["filters"] = _with_filter(raw["filters"], field, new)
    return parse_spec(raw)


# ----------------------------------------------------------------------------------------- a typed follow-up

_STATED_KEYS = frozenset({"grain", "metric", "operator", "metric_minus", "metric_plus", "match_set", "filters",
                          "order", "top_n"})


def _family(pred: Mapping[str, Any]) -> str:
    if pred["pred"] in WINDOW_PREDICATES:
        return "window"
    return "venue" if pred["pred"] == "venue" else "player"


def apply_stated(spec: QuerySpec,stated: Mapping[str, Any], cleared: tuple[str, ...] = ()) -> QuerySpec:
    """*spec* with only the stated parts changed.

    *stated* is a partial flat spec: what the follow-up says and nothing else. *cleared* names filter parts it
    removes ("any price", "all positions"). Inside a part:

    * a new window replaces the old one; a venue replaces the venue; named players replace the named players;
    * filters replace every earlier filter on the same field;
    * a new metric drops an earlier second metric, and keeps "per match / per 90 / per million" if it applies.
    """
    unknown = set(stated) - _STATED_KEYS
    if unknown or set(cleared) - set(_PART_FIELD):
        raise QuerySpecError("unknown_key", "stated")
    raw = spec.to_dict()

    if "grain" in stated and stated["grain"] != spec.grain:
        raise QuerySpecError("conflict", "stated.grain")          # another grain is a new question
    if "metric" in stated:
        raw.pop("metric_minus", None)
        raw.pop("metric_plus", None)
        metric = stated["metric"]
        if spec.grain == "team" and isinstance(metric, str):
            metric = cat.TEAM_GRAIN_METRIC_MAP.get(metric, metric)
        raw["metric"] = metric
        known = metric in cat.METRICS if isinstance(metric, str) else False
        keep = (known and spec.operator in ("per_match", "per_90", "per_million")
                and spec.operator in cat.operators_for(metric))
        raw["operator"] = spec.operator if keep else "sum"
        old, new = cat.METRICS[spec.metric], cat.METRICS.get(metric) if known else None
        if new is not None and (old.default_order != new.default_order or spec.order == old.default_order):
            raw["order"] = new.default_order
    for key in ("operator", "metric_minus", "metric_plus", "order", "top_n"):
        if key in stated:
            raw[key] = stated[key]
    if "operator" in stated:
        for key in ("metric_minus", "metric_plus"):
            if key not in stated and cat.OPERATORS.get(stated["operator"], {}).get("second_metric") != key:
                raw.pop(key, None)

    new_preds = _stated_items(stated, "match_set", "pred")
    if new_preds:
        replaced = {_family(p) for p in new_preds}
        if "window" in replaced and not window_is_editable(spec):
            raise QuerySpecError("conflict", "stated.window")
        if "player" in replaced and spec.compare_to is not None:
            raise QuerySpecError("conflict", "stated.player")     # another with / without is a new question
        for side in ("match_set", "compare_to"):
            if side in raw:
                raw[side] = [p for p in raw[side] if _family(p) not in replaced] + new_preds

    new_filters = _stated_items(stated, "filters", "field")
    for part in cleared:
        raw["filters"] = _with_filter(raw["filters"], _PART_FIELD[part], [])
    for field in {f["field"] for f in new_filters}:
        raw["filters"] = _with_filter(raw["filters"], field, [f for f in new_filters if f["field"] == field])
    return parse_spec(raw)


def _stated_items(stated: Mapping[str, Any], key: str, name: str) -> list[dict]:
    items = stated.get(key, [])
    if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get(name), str)
                                              for i in items):
        raise QuerySpecError("bad_type", f"stated.{key}")
    return items


# ------------------------------------------------------------------------------------------------ what changed

def _parts_of(spec: QuerySpec) -> dict[str, Any]:
    raw = spec.to_dict()
    sets = [raw["match_set"], raw.get("compare_to") or []]
    out: dict[str, Any] = {
        "grain": spec.grain,
        "metric": (spec.metric, spec.operator, spec.second_metric, spec.order),
        "window": [[p for p in s if p["pred"] in WINDOW_PREDICATES] for s in sets],
        "match_set": (spec.shape, [[p for p in s if p["pred"] not in WINDOW_PREDICATES] for s in sets]),
        "top_n": spec.top_n}
    for field, part in _FILTER_PART.items():
        out[part] = [f for f in raw["filters"] if f["field"] == field]
    return out


def changed_parts(old: QuerySpec, new: QuerySpec) -> tuple[str, ...]:
    """The parts on which two specs differ, in the reading line's order."""
    before, after = _parts_of(old), _parts_of(new)
    return tuple(part for part in PARTS if before[part] != after[part])
