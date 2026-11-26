"""``QuerySpec`` v1: the one typed form of a data question, and its strict server-side parse.

:func:`parse_spec` takes the flat JSON form (no quotes: the tool layer strips those) and either returns a
``QuerySpec`` with every declared default filled in, or raises :class:`QuerySpecError`. It never repairs a
value: ``5.0`` where a whole number is due, ``""``, an unknown key, metric or operator are all refused.
The only rewrites are the declared ones:

* at team grain, ``goals_scored`` and its siblings mean their ``team_*`` id;
* a team metric with no grain means team grain;
* ``owned_now`` ``"low"`` means ``< 10``;
* ``season`` beside another predicate adds nothing and is dropped; exact duplicates are dropped;
* predicates and filters are put in a fixed order.

A spec can be well formed and still not executable in this delivery; :func:`unsupported_reasons` says so.
That is a different answer to the user (``unsupported_constraint``) from an invalid spec (a clarify).

``since_date`` may still lack its year (``MM-DD``): code assigns it before execution.

Nothing imports this module at runtime yet (query layer, PR 1).
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any

from fpl_grounded_assistant import query_catalogue as cat

SPEC_VERSION = 1

WINDOW_PREDICATES = frozenset({"season", "last_n", "gw", "gw_range", "since_date"})
PLAYER_PREDICATES = frozenset({"player_played_60", "player_absent"})

_KEYS = frozenset({"v", "shape", "grain", "metric", "operator", "metric_minus", "metric_plus", "match_set",
                   "compare_to", "filters", "order", "top_n"})
_DATE = re.compile(r"(?:([0-9]{4})-)?([0-9]{2})-([0-9]{2})")


class QuerySpecError(ValueError):
    """An invalid spec. *code* is an enum safe to audit; *path* names the field (never the value)."""

    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"{code}:{path}")
        self.code = code
        self.path = path


@dataclass(frozen=True)
class Predicate:
    pred: str
    value: Any                       # True | int | (int, int) | str

    def to_dict(self) -> dict[str, Any]:
        return {"pred": self.pred, "value": list(self.value) if isinstance(self.value, tuple) else self.value}


@dataclass(frozen=True)
class Filter:
    field: str
    op: str
    value: Any                       # str | int | float | tuple of those

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "op": self.op,
                "value": list(self.value) if isinstance(self.value, tuple) else self.value}


@dataclass(frozen=True)
class QuerySpec:
    metric: str
    shape: str
    grain: str
    operator: str
    metric_minus: str | None
    metric_plus: str | None
    match_set: tuple[Predicate, ...]
    compare_to: tuple[Predicate, ...] | None
    filters: tuple[Filter, ...]
    order: str
    top_n: int

    @property
    def second_metric(self) -> str | None:
        return self.metric_minus or self.metric_plus

    def to_dict(self) -> dict[str, Any]:
        """The full public form, defaults included. ``parse_spec(spec.to_dict()) == spec``."""
        out: dict[str, Any] = {"v": SPEC_VERSION, "shape": self.shape, "grain": self.grain, "metric": self.metric,
                               "operator": self.operator, "match_set": [p.to_dict() for p in self.match_set],
                               "filters": [f.to_dict() for f in self.filters], "order": self.order,
                               "top_n": self.top_n}
        if self.metric_minus is not None:
            out["metric_minus"] = self.metric_minus
        if self.metric_plus is not None:
            out["metric_plus"] = self.metric_plus
        if self.compare_to is not None:
            out["compare_to"] = [p.to_dict() for p in self.compare_to]
        return out


# ------------------------------------------------------------------------------------------------ value readers

def _enum(value: Any, allowed: Any, path: str, code: str = "bad_value") -> str:
    if not isinstance(value, str):
        raise QuerySpecError("bad_type", path)
    if value == "":
        raise QuerySpecError("empty_string", path)
    if value not in allowed:
        raise QuerySpecError(code, path)
    return value


def _int(value: Any, low: int, high: int, path: str) -> int:
    if type(value) is not int:                       # refuses bool, 5.0 and "5"
        raise QuerySpecError("bad_type", path)
    if not low <= value <= high:
        raise QuerySpecError("out_of_range", path)
    return value


def _number(value: Any, low: float, high: float, path: str) -> float:
    if type(value) not in (int, float):
        raise QuerySpecError("bad_type", path)
    if not (math.isfinite(value) and low <= value <= high):
        raise QuerySpecError("out_of_range", path)
    return float(value)


def _name(value: Any, path: str) -> str:
    """A player or club as written."""
    if not isinstance(value, str):
        raise QuerySpecError("bad_type", path)
    name = " ".join(value.split())
    if not name:
        raise QuerySpecError("empty_string", path)
    if len(name) > cat.LIMITS["name_max_chars"]:
        raise QuerySpecError("out_of_range", path)
    return name


def _items(raw: Any, keys: set, path: str) -> list[dict]:
    if not isinstance(raw, list):
        raise QuerySpecError("bad_type", path)
    for item in raw:
        if not isinstance(item, dict):
            raise QuerySpecError("bad_type", path)
        if set(item) - keys:
            raise QuerySpecError("unknown_key", path)
        if keys - set(item):
            raise QuerySpecError("missing", path)
    return raw


def parse_date(value: str) -> tuple[int | None, int, int]:
    """``MM-DD`` or ``YYYY-MM-DD`` -> (year or None, month, day). A real calendar day, else ValueError."""
    match = _DATE.fullmatch(value)
    if not match:
        raise ValueError("not a date")
    year = int(match.group(1)) if match.group(1) else None
    month, day = int(match.group(2)), int(match.group(3))
    dt.date(2024 if year is None else year, month, day)          # 2024: a leap year, so 02-29 passes without one
    return year, month, day


def _predicate(item: dict, path: str) -> Predicate:
    pred = _enum(item["pred"], cat.PREDICATES, f"{path}.pred")
    value = item["value"]
    where = f"{path}.{pred}"
    last_gw = cat.LIMITS["gameweek_max"]
    if pred == "season":
        if value is not True:
            raise QuerySpecError("bad_value", where)
    elif pred in ("last_n", "gw"):
        value = _int(value, 1, last_gw, where)
    elif pred == "gw_range":
        if not isinstance(value, list) or len(value) != 2:
            raise QuerySpecError("bad_type", where)
        value = (_int(value[0], 1, last_gw, where), _int(value[1], 1, last_gw, where))
        if value[0] > value[1]:
            raise QuerySpecError("bad_value", where)
    elif pred == "since_date":
        if not isinstance(value, str):
            raise QuerySpecError("bad_type", where)
        try:
            parse_date(value)
        except ValueError:
            raise QuerySpecError("bad_value", where) from None
    elif pred == "venue":
        value = _enum(value, ("home", "away"), where)
    else:
        value = _name(value, where)
    return Predicate(pred, value)


def _match_set(raw: Any, path: str) -> tuple[Predicate, ...]:
    """AND of predicates. At most one window and one venue, so the reading line can always name them."""
    found = {_predicate(item, path) for item in _items(raw, {"pred", "value"}, path)}
    rest = {p for p in found if p.pred != "season"}
    if len([p for p in rest if p.pred in WINDOW_PREDICATES]) > 1:
        raise QuerySpecError("conflict", f"{path}.window")
    if len([p for p in rest if p.pred == "venue"]) > 1:
        raise QuerySpecError("conflict", f"{path}.venue")
    players = [p for p in rest if p.pred in PLAYER_PREDICATES]
    if len({p.value.casefold() for p in players}) < len(players):     # present and absent at once
        raise QuerySpecError("conflict", f"{path}.player")
    if not rest:
        return (Predicate("season", True),)
    return tuple(sorted(rest, key=lambda p: (cat.PREDICATES.index(p.pred), str(p.value))))


def _filter(item: dict) -> Filter:
    field_ = _enum(item["field"], cat.FILTER_FIELDS, "filters.field")
    where = f"filters.{field_}"
    op = _enum(item["op"], cat.OPS, f"{where}.op", "unknown_operator")
    if op not in cat.FILTER_OPS[field_]:
        raise QuerySpecError("bad_value", f"{where}.op")
    value = item["value"]

    if field_ in ("position", "set_piece", "club"):
        def one(v: Any) -> str:
            if field_ == "club":
                return _name(v, where)
            return _enum(v, cat.POSITIONS if field_ == "position" else cat.SET_PIECES, where)
        if op == "eq" or (op == "not" and not isinstance(value, list)):
            return Filter(field_, op, one(value))
        if not isinstance(value, list) or not value:
            raise QuerySpecError("bad_type", where)
        return Filter(field_, op, tuple(sorted({one(v) for v in value})))

    if field_ == "owned_now" and value == "low":
        if op not in ("eq", "lt", "le"):
            raise QuerySpecError("bad_value", f"{where}.op")
        low = cat.DEFAULTS["owned_now_low"]
        return Filter(field_, low["op"], float(low["value"]))
    lo, hi = cat.FILTER_RANGES[field_]
    if field_ == "minutes_in_window":
        def number(v: Any) -> Any:
            return _int(v, int(lo), int(hi), where)
    else:
        def number(v: Any) -> Any:
            return _number(v, lo, hi, where)
    if op != "between":
        return Filter(field_, op, number(value))
    if not isinstance(value, list) or len(value) != 2:
        raise QuerySpecError("bad_type", where)
    ends = (number(value[0]), number(value[1]))
    if ends[0] > ends[1]:
        raise QuerySpecError("bad_value", where)
    return Filter(field_, op, ends)


# ------------------------------------------------------------------------------------------------------- parse

def parse_spec(raw: Any) -> QuerySpec:
    """The flat JSON form -> a complete ``QuerySpec``, or :class:`QuerySpecError`."""
    if not isinstance(raw, dict):
        raise QuerySpecError("bad_type", "spec")
    if set(raw) - _KEYS:
        raise QuerySpecError("unknown_key", "spec")
    for key, value in raw.items():
        if value is None:                            # leave a key out; null is not a default
            raise QuerySpecError("bad_type", key)
    if "v" in raw:
        _int(raw["v"], SPEC_VERSION, SPEC_VERSION, "v")
    if "metric" not in raw:
        raise QuerySpecError("missing", "metric")

    grain = _enum(raw["grain"], cat.GRAINS, "grain") if "grain" in raw else None

    def metric_id(key: str) -> str:
        value = raw[key]
        if grain == "team" and isinstance(value, str):
            value = cat.TEAM_GRAIN_METRIC_MAP.get(value, value)
        return _enum(value, cat.METRICS, key, "unknown_metric")

    metric = metric_id("metric")
    row = cat.METRICS[metric]
    if grain is None:
        grain = "team" if row.group == "team" else cat.DEFAULTS["grain"]
    if (row.group == "team") != (grain == "team"):
        raise QuerySpecError("conflict", "grain")

    operator = (_enum(raw["operator"], cat.OPERATORS, "operator", "unknown_operator")
                if "operator" in raw else cat.DEFAULTS["operator"])
    if operator not in cat.operators_for(metric):
        raise QuerySpecError("conflict", "operator")
    second: dict[str, str | None] = {"metric_minus": None, "metric_plus": None}
    wanted = cat.OPERATORS[operator]["second_metric"]
    for key in second:
        if (key in raw) != (key == wanted):
            raise QuerySpecError("missing" if key == wanted else "conflict", key)
        if key in raw:
            other = metric_id(key)
            if other == metric or cat.METRICS[other].group != row.group or operator not in cat.operators_for(other):
                raise QuerySpecError("conflict", key)
            second[key] = other

    shape = _enum(raw["shape"], cat.SHAPES, "shape") if "shape" in raw else cat.DEFAULTS["shape"]
    match_set = _match_set(raw.get("match_set", []), "match_set")
    compare_to = None
    if shape == "comparison":
        if not raw.get("compare_to"):
            raise QuerySpecError("missing", "compare_to")
        compare_to = _match_set(raw["compare_to"], "compare_to")
        if compare_to == match_set:
            raise QuerySpecError("conflict", "compare_to")
    elif "compare_to" in raw and raw["compare_to"] != []:
        raise QuerySpecError("conflict", "compare_to")

    filters = {_filter(item) for item in _items(raw.get("filters", []), {"field", "op", "value"}, "filters")}
    if grain == "team" and any(f.field != "club" for f in filters):
        raise QuerySpecError("conflict", "filters")

    order = _enum(raw["order"], ("asc", "desc"), "order") if "order" in raw else row.default_order
    top_n = (_int(raw["top_n"], 1, cat.LIMITS["top_n_max"], "top_n")
             if "top_n" in raw else cat.DEFAULTS["top_n"])

    return QuerySpec(metric=metric, shape=shape, grain=grain, operator=operator,
                     metric_minus=second["metric_minus"], metric_plus=second["metric_plus"],
                     match_set=match_set, compare_to=compare_to,
                     filters=tuple(sorted(filters, key=lambda f: (cat.FILTER_FIELDS.index(f.field), f.op,
                                                                  str(f.value)))),
                     order=order, top_n=top_n)


def unsupported_reasons(spec: QuerySpec) -> tuple[str, ...]:
    """Why a well-formed spec cannot be executed in this delivery; empty when it can.

    Ids from ``cat.UNSUPPORTED_KINDS``, plus ``season_only_metric`` (a today's-value metric asked over matches).
    """
    sets = [spec.match_set] + ([spec.compare_to] if spec.compare_to is not None else [])
    preds = [p for s in sets for p in s]
    out: list[str] = []
    if cat.METRICS[spec.metric].group == "snapshot" and (
            spec.shape != "list" or any(p.pred != "season" for p in preds)):
        out.append("season_only_metric")
    if spec.grain == "player" and any(p.pred == "venue" for p in preds):
        out.append("player_venue")
    if len({p.value.casefold() for p in preds if p.pred in PLAYER_PREDICATES}) > 1:
        out.append("several_players")
    if spec.shape == "comparison":
        # One comparison is one club: named in a filter, or the club of the player the sets are built on.
        one_club = any(f.field == "club" and f.op == "eq" for f in spec.filters)
        if spec.grain != "team" or not (one_club or any(p.pred in PLAYER_PREDICATES for p in preds)):
            out.append("difference_list")
    return tuple(out)
