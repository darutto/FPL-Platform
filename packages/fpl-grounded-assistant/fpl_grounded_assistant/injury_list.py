"""
fpl_grounded_assistant.injury_list
====================================
Phase 2.6d Story 2.3b: GW-wide injury / availability list.

Returns all players from the bootstrap whose status is not "a" (available),
grouped into injured (status "i"), doubtful (status "d"), and
unavailable/suspended (status "s" / "u").

Named player injury checks ("está lesionado X?") are routed to
``player_summary`` instead, which already surfaces ``status_label``.
This handler covers the list-form query only ("hay dudas para esta jornada?").

Design rules
------------
* Purely bootstrap-driven — no API calls beyond bootstrap.
* Returns ``status="ok"`` always (empty lists are valid, not an error).
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec


# ---------------------------------------------------------------------------
# Tool spec (self-registers at import)
# ---------------------------------------------------------------------------

INJURY_LIST_SPEC = ToolSpec(
    name="get_injury_list",
    description=(
        "Return all players with an injury, doubt, or suspension flag "
        "from the current bootstrap. Groups results as injured, doubtful, "
        "and suspended/unavailable."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":   {"type": "string"},
            "injured":  {"type": "array"},
            "doubtful": {"type": "array"},
            "other":    {"type": "array"},
            "total":    {"type": "integer"},
        },
    },
)
def _get_injury_list_handler(bootstrap: "dict") -> "dict":
    return get_injury_list(bootstrap)


TOOL_REGISTRY.register(INJURY_LIST_SPEC, _get_injury_list_handler)


# ---------------------------------------------------------------------------
# Status display helpers
# ---------------------------------------------------------------------------

_STATUS_LABEL: dict[str, str] = {
    "i": "Injured",
    "d": "Doubtful",
    "s": "Suspended",
    "u": "Unavailable",
}

_POSITION_LABEL: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _team_short(element: dict, teams_map: dict[int, str]) -> str:
    return teams_map.get(element.get("team", -1), "?")


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

def get_injury_list(bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Return players currently unavailable from the FPL bootstrap.

    Returns — status "ok"
    ----------------------
    ``status``      "ok"
    ``injured``     List of injured players (status "i")
    ``doubtful``    List of doubtful players (status "d")
    ``other``       Suspended or otherwise unavailable (status "s" / "u")
    ``total``       Total count across all three lists

    Each entry contains:
    ``web_name``, ``team_short``, ``position``, ``status_label``,
    ``chance_of_playing`` (int or None for doubtful players only)
    """
    teams_map: dict[int, str] = {
        t["id"]: t.get("short_name", "?")
        for t in bootstrap.get("teams", [])
        if "id" in t
    }

    injured: list[dict] = []
    doubtful: list[dict] = []
    other: list[dict] = []

    for el in bootstrap.get("elements", []):
        status = el.get("status", "a")
        if status == "a":
            continue

        pos = _POSITION_LABEL.get(el.get("element_type", 0), "?")
        entry: dict[str, Any] = {
            "web_name":    el.get("web_name", "?"),
            "team_short":  _team_short(el, teams_map),
            "position":    pos,
            "status_label": _STATUS_LABEL.get(status, status.upper()),
        }

        if status == "d":
            chance = el.get("chance_of_playing_this_round")
            entry["chance_of_playing"] = int(chance) if chance is not None else None
            doubtful.append(entry)
        elif status == "i":
            injured.append(entry)
        else:
            other.append(entry)

    return {
        "status":   "ok",
        "injured":  injured,
        "doubtful": doubtful,
        "other":    other,
        "total":    len(injured) + len(doubtful) + len(other),
    }
