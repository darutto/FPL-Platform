"""The query layer's catalogue: metric rows, vocabulary and declared defaults, all read from one JSON file.

``query_catalogue.json`` is data: a new metric is a new row. The parser (``query_spec``), the engine and the
reading-line renderer read the same rows, so none of them can hold a list of its own that drifts.

Row fields: ``id`` (what a spec names), ``group`` (additive = summed per gameweek; snapshot = today's value,
season only; team = derived per club), ``field`` (the source field), ``unit``, ``default_order``, ``floor``
(minutes floor rule, see :func:`minutes_floor`), ``name`` (ES/EN, mid-sentence form, used in compounds such
as "goles − xG") and ``desc`` / ``asc`` (ES/EN full phrase for a plain ranking in that direction).

Nothing imports this module at runtime yet (query layer, PR 1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

CATALOGUE_PATH = Path(__file__).with_name("query_catalogue.json")


@dataclass(frozen=True)
class MetricRow:
    id: str
    group: str                       # additive | snapshot | team
    field: str
    unit: str
    default_order: str               # asc | desc
    floor: str                       # standard | rate | none
    name: Mapping[str, str]
    desc: Mapping[str, str]
    asc: Mapping[str, str]


def _load() -> dict[str, Any]:
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


_DOC = _load()


def _row(raw: dict[str, Any]) -> MetricRow:
    return MetricRow(**{k: (MappingProxyType(v) if isinstance(v, dict) else v) for k, v in raw.items()})


METRICS: Mapping[str, MetricRow] = MappingProxyType({r["id"]: _row(r) for r in _DOC["metrics"]})

SHAPES: tuple[str, ...] = tuple(_DOC["shapes"])
GRAINS: tuple[str, ...] = tuple(_DOC["grains"])
PREDICATES: tuple[str, ...] = tuple(_DOC["predicates"])
FILTER_FIELDS: tuple[str, ...] = tuple(_DOC["filter_fields"])
OPS: tuple[str, ...] = tuple(_DOC["ops"])
UNSUPPORTED_KINDS: tuple[str, ...] = tuple(_DOC["unsupported_kinds"])
METRIC_PHRASES: Mapping[str, str] = MappingProxyType(_DOC["metric_phrases"])
POSITIONS: tuple[str, ...] = tuple(_DOC["positions"])
SET_PIECES: tuple[str, ...] = tuple(_DOC["set_pieces"])
FILTER_OPS: Mapping[str, tuple[str, ...]] = MappingProxyType({k: tuple(v) for k, v in _DOC["filter_ops"].items()})
FILTER_RANGES: Mapping[str, tuple[float, float]] = MappingProxyType(
    {k: (v[0], v[1]) for k, v in _DOC["filter_ranges"].items()})
TEAM_GRAIN_METRIC_MAP: Mapping[str, str] = MappingProxyType(_DOC["team_grain_metric_map"])
OPERATORS: Mapping[str, Mapping[str, Any]] = MappingProxyType(_DOC["operators"])
DEFAULTS: Mapping[str, Any] = MappingProxyType(_DOC["defaults"])
LIMITS: Mapping[str, int] = MappingProxyType(_DOC["limits"])
FLOORS: Mapping[str, Any] = MappingProxyType(_DOC["floors"])


def metric_ids(group: str | None = None) -> tuple[str, ...]:
    """Metric ids in vocabulary order, optionally of one group."""
    return tuple(m for m, row in METRICS.items() if group is None or row.group == group)


def operators_for(metric: str) -> tuple[str, ...]:
    """The operators that mean something for *metric*."""
    excluded = _DOC["operator_exclusions"].get(metric, ())
    return tuple(o for o in _DOC["group_operators"][METRICS[metric].group] if o not in excluded)


def minutes_floor(metric: str, operator: str, order: str, window_gameweeks: int) -> int:
    """The minutes a player needs to be listed; 0 = no floor. The ranking tool's rules, applied to a window.

    Ascending: one full match's minutes, so players who have not played do not sort first. Descending rates
    (per match, per 90, FPL's points-per-game): 270, capped at half the window's minutes early on, and 30 % of
    the window's minutes once that is larger. *window_gameweeks* is the number of gameweeks in the window
    (for the whole season, the finished ones; 0 = unknown, giving the plain base). Team rows have no floor.
    """
    row = METRICS[metric]
    if row.floor == "none":
        return 0
    if order == "asc":
        return int(FLOORS["asc_minutes"])
    if row.floor != "rate" and operator not in FLOORS["rate_operators"]:
        return 0
    base = int(FLOORS["rate_minutes_base"])
    if window_gameweeks <= 0:
        return base
    available = window_gameweeks * 90
    early = min(base, int(available * FLOORS["rate_early_cap_share"]))
    return max(early, int(available * FLOORS["rate_share_of_available"]))
