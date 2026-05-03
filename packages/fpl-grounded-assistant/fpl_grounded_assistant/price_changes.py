"""
fpl_grounded_assistant.price_changes
======================================
Phase 2.6d Story 2.4: Deterministic price risers and fallers.

Reports players whose price changed in the current gameweek (``cost_change_event``)
or across the season (``cost_change_start``).  Both fields come directly from
the FPL bootstrap — no external API calls.

Design rules
------------
* Strictly deterministic — ``cost_change_event`` is the actual observed change,
  never a forecast.  No predictive wording.
* Returns ``status="ok"`` with empty lists when no price changes occurred.
* Returns ``status="empty"`` when bootstrap has no ``cost_change_event`` data
  at all (e.g., test fixtures that omit the field).
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec


# ---------------------------------------------------------------------------
# Tool spec (self-registers at import)
# ---------------------------------------------------------------------------

PRICE_CHANGES_SPEC = ToolSpec(
    name="get_price_changes",
    description=(
        "Return players whose price changed in the current gameweek, "
        "sorted into risers (positive cost_change_event) and fallers "
        "(negative cost_change_event).  All data is from the bootstrap."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":  {"type": "string"},
            "risers":  {"type": "array"},
            "fallers": {"type": "array"},
        },
    },
)
def _get_price_changes_handler(bootstrap: "dict") -> "dict":
    return get_price_changes(bootstrap)


TOOL_REGISTRY.register(PRICE_CHANGES_SPEC, _get_price_changes_handler)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_POSITION_LABEL: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _team_short(element: dict, teams_map: dict[int, str]) -> str:
    return teams_map.get(element.get("team", -1), "?")


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

def get_price_changes(bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Return this-GW price risers and fallers from the bootstrap.

    Returns — status "ok"
    ----------------------
    ``status``    "ok"
    ``risers``    Players with positive ``cost_change_event``, sorted desc
    ``fallers``   Players with negative ``cost_change_event``, sorted asc
    ``gw_note``   Informational note about the data source

    Each entry contains:
    ``web_name``, ``team_short``, ``position``, ``now_cost`` (tenths of £),
    ``now_cost_m`` (£m float), ``cost_change_event`` (tenths of £),
    ``cost_change_start`` (season change, tenths of £)

    Returns — status "empty"
    -------------------------
    ``status``   "empty"
    ``message``  "No price-change data found in bootstrap."
    When ``cost_change_event`` is absent from all bootstrap elements.
    """
    teams_map: dict[int, str] = {
        t["id"]: t.get("short_name", "?")
        for t in bootstrap.get("teams", [])
        if "id" in t
    }

    risers: list[dict] = []
    fallers: list[dict] = []
    data_found = False

    for el in bootstrap.get("elements", []):
        change_event = el.get("cost_change_event")
        if change_event is None:
            continue

        data_found = True
        change_event = int(change_event)
        if change_event == 0:
            continue

        pos = _POSITION_LABEL.get(el.get("element_type", 0), "?")
        now_cost = int(el.get("now_cost", 0))
        entry: dict[str, Any] = {
            "web_name":          el.get("web_name", "?"),
            "team_short":        _team_short(el, teams_map),
            "position":          pos,
            "now_cost":          now_cost,
            "now_cost_m":        round(now_cost / 10.0, 1),
            "cost_change_event": change_event,
            "cost_change_start": int(el.get("cost_change_start", 0) or 0),
        }

        if change_event > 0:
            risers.append(entry)
        else:
            fallers.append(entry)

    if not data_found:
        return {
            "status":  "empty",
            "message": "No price-change data found in bootstrap.",
        }

    risers.sort(key=lambda x: -x["cost_change_event"])
    fallers.sort(key=lambda x: x["cost_change_event"])

    return {
        "status":   "ok",
        "risers":   risers,
        "fallers":  fallers,
        "gw_note":  "Price changes reflect cost_change_event from the current bootstrap.",
    }
