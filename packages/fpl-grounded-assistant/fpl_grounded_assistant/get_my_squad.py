"""
fpl_grounded_assistant.get_my_squad
=====================================
i39: Atomic get_my_squad tool — the connected user's own 15-man squad
(starting XI + bench, captain/vice, price, status, active chip) for a given
gameweek.

Addresses the failed query class: a user with a team connected asks "evalúa
a mi equipo y qué tan buena idea sería el bench boost en la fecha 2" and is
told to paste their 15 players by hand — the model had no way to see the
squad it was being asked to evaluate.

Design: a tool, not prompt text
--------------------------------
The squad is fetched **on demand**, only when this tool is invoked, and never
injected into every turn's context. Two consequences:

* Questions with no personal reference (price checks, fixture lookups,
  player comparisons) pay zero extra cost — no fetch, no extra tokens.
* The user's team id must reach this handler through the fixed
  ``handler(args, bootstrap)`` signature (``fpl_tool_runner.ToolRegistry.run``
  never grew a third channel). It arrives via ``bootstrap["_my_team_id"]``,
  injected by ``harness.ask_v2()`` for the one call that has it, on a
  **shallow copy** of the bootstrap dict — never a mutation of the shared
  server-level ``_bootstrap`` singleton (that dict is reused across every
  concurrent request; mutating it in place would leak one user's team id into
  another user's turn, the same class of bug the locale track's ban on
  module-global/contextvar state exists to prevent — see catalogue.py). See
  ``harness.ask_v2``'s ``team_id`` parameter for the injection site.

No team connected
------------------
``bootstrap.get("_my_team_id")`` is ``None`` for every anonymous turn and for
every turn that reached ``ask_v2()`` without a ``team_id`` (the overwhelming
majority — this key exists on a fresh shallow copy only when the caller
passed one). This tool degrades to ``status="no_team_connected"`` with a
message that invites connecting a team, rather than raising or fabricating
data. It never appears in ``bootstrap`` unless a real caller opted in, so a
turn with no team connected behaves byte-for-byte like it did before this
tool existed.

Bootstrap source
-----------------
``bootstrap["elements"]``, ``bootstrap["teams"]``, ``bootstrap["element_types"]``
resolve each pick's id to name/team/position/price/status — the picks
endpoint itself returns bare element ids. ``bootstrap["events"]`` resolves
the current gameweek when ``gw`` is omitted.

Live fetch
----------
``fpl_api_client.get_entry_picks(team_id, gw)`` — the same
``entry/{id}/event/{gw}/picks/`` endpoint the U2 pitch view's server-side
proxy (``packages/fpl-ui/app/api/fpl-squad/[teamId]/route.ts``) already
fetches, just from the Python backend instead of the Next.js route. Network
failure and an unknown/bad team id both degrade to a structured
``status="error"`` / ``status="not_found"`` dict — never an unhandled
exception and never a silent empty answer.

Registration
------------
Registers ``get_my_squad`` in ``TOOL_REGISTRY`` as a side-effect of import.
``__init__.py`` imports this module so ``run_tool("get_my_squad", ...)``
works.
"""
from __future__ import annotations

from typing import Any

import requests

from fpl_api_client.fpl_client import get_entry_picks
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .chip_advisor import (
    CHIP_TRIPLE_CAPTAIN,
    CHIP_WILDCARD,
    CHIP_BENCH_BOOST,
    CHIP_FREE_HIT,
)
from .find_players import _map_status, _position_label, _safe_float, _safe_int, _team_short
from .get_team_snapshot import _current_gw_from_events


_GW_MIN: int = 1
_GW_MAX: int = 38

#: FPL's own active_chip codes -> the backend chip-name vocabulary used
#: everywhere else in this product (chip_advisor.py, SquadContext.chips_remaining).
#: Mirrors packages/fpl-ui/lib/squad-context.ts::FPL_TO_BACKEND_CHIP —
#: duplicated rather than shared because one side is Python and the other TS,
#: but the FPL codes and target vocabulary are the same closed 4-value set.
_FPL_TO_BACKEND_CHIP: dict[str, str] = {
    "wildcard": CHIP_WILDCARD,
    "3xc":      CHIP_TRIPLE_CAPTAIN,
    "bboost":   CHIP_BENCH_BOOST,
    "freehit":  CHIP_FREE_HIT,
}


def _resolve_gw(
    gw: "int | None",
    events: list[dict[str, Any]],
) -> "tuple[int, bool] | tuple[None, bool]":
    """Return ``(resolved_gw, was_clamped)``, or ``(None, False)`` if the
    explicit ``gw`` is out of the valid 1-38 range.

    ``None`` falls back to ``_current_gw_from_events`` (current GW, else last
    finished, else first) — not clamped.

    A **future** ``gw`` (beyond the current GW) is clamped down to the
    current GW rather than sent to the FPL API as-is: ``entry/{id}/event/{gw}/picks/``
    only ever has data through the current gameweek — the public API does not
    expose a manager's planned-but-not-yet-locked squad for a future GW at
    all, so a future request 404s every time, indistinguishable from a bad
    team id. That 404 was reachable in practice: "bench boost en la fecha 2"
    asked while GW1 is still current is exactly this case, and a model that
    reads "team_not_found" for a perfectly valid, connected team is worse
    than one told plainly that the most recent confirmed squad is being
    shown instead. A **past** gw that still 404s (e.g. before the manager's
    team existed) is a real, rare edge case and keeps returning
    ``team_not_found`` — clamping only ever moves a request backward in time
    toward data that is known to exist.
    """
    current_gw = _current_gw_from_events(events)
    if gw is not None:
        gw_int = _safe_int(gw, 0)
        if gw_int < _GW_MIN or gw_int > _GW_MAX:
            return None, False
        if current_gw is not None and gw_int > current_gw:
            return current_gw, True
        return gw_int, False
    return current_gw, False


def get_my_squad(
    bootstrap: "dict[str, Any] | None",
    gw: "int | None" = None,
) -> dict[str, Any]:
    """Return the connected user's 15-man squad for *gw* (default: current GW).

    Returns one of::

        # No team connected (the overwhelmingly common case — safe default):
        {"status": "no_team_connected", "code": "no_team_connected", "message": "..."}

        # Bad gw argument:
        {"status": "error", "code": "invalid_gw", "message": "..."}

        # Unknown/bad team id (FPL API 404):
        {"status": "not_found", "code": "team_not_found", "team_id": <int>, "message": "..."}

        # Network failure:
        {"status": "error", "code": "network_error", "message": "..."}

        # Success:
        {
            "status": "ok",
            "team_id": <int>,
            "gw": <int>,
            # present only when the requested gw was in the future and got
            # clamped back to the current gw — see _resolve_gw's docstring:
            "requested_gw": <int>,
            "gw_clamped": True,
            "players": [
                {
                    "id", "web_name", "team_short", "position", "now_cost",
                    "status", "chance_of_playing_this_round", "form",
                    "total_points", "is_captain", "is_vice_captain",
                    "multiplier", "pick_position", "is_starter",
                },
                ...  # 15 entries, ordered by pick_position (1-11 starters, 12-15 bench)
            ],
            "summary": {
                "gw_points", "total_points", "bank", "active_chip",
            },
        }

    ``active_chip`` is ``None`` or one of ``chip_advisor.SUPPORTED_CHIPS``
    (translated from the FPL API's own chip codes).
    """
    team_id = bootstrap.get("_my_team_id") if bootstrap else None
    if not team_id:
        return {
            "status":  "no_team_connected",
            "code":    "no_team_connected",
            "message": (
                "No hay ningún equipo conectado. Conecta tu equipo desde la "
                "pestaña Plantilla para que pueda evaluarlo."
            ),
        }

    events: list[dict[str, Any]] = (bootstrap or {}).get("events", []) or []
    requested_gw = gw
    resolved_gw, gw_clamped = _resolve_gw(gw, events)
    if resolved_gw is None:
        return {
            "status":  "error",
            "code":    "invalid_gw",
            "message": f"gw debe estar entre {_GW_MIN} y {_GW_MAX}.",
        }

    try:
        picks_data = get_entry_picks(int(team_id), resolved_gw)
    except requests.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 404:
            return {
                "status":  "not_found",
                "code":    "team_not_found",
                "team_id": team_id,
                "message": (
                    f"No encontré ningún equipo FPL con el ID {team_id}. "
                    "Revisa que el ID sea correcto."
                ),
            }
        return {
            "status":  "error",
            "code":    "network_error",
            "message": f"No pude obtener tu plantilla (error del servidor de FPL: {exc}).",
        }
    except requests.RequestException as exc:
        return {
            "status":  "error",
            "code":    "network_error",
            "message": f"No pude obtener tu plantilla (fallo de red: {exc}).",
        }

    elements: list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams: list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []
    elements_by_id: dict[int, dict[str, Any]] = {e.get("id"): e for e in elements}

    raw_picks = sorted(
        picks_data.get("picks", []) or [],
        key=lambda p: _safe_int(p.get("position"), 0),
    )

    players: list[dict[str, Any]] = []
    for pick in raw_picks:
        element_id = pick.get("element")
        el = elements_by_id.get(element_id)
        pick_position = _safe_int(pick.get("position"), 0)
        players.append({
            "id":                          element_id,
            "web_name":                    el.get("web_name", "") if el else f"#{element_id}",
            "team_short":                  _team_short(el, teams) if el else "",
            "position":                    _position_label(el, element_types) if el else "",
            "now_cost":                    _safe_int(el.get("now_cost"), 0) if el else 0,
            "status":                      _map_status(el.get("status")) if el else "Unknown",
            "chance_of_playing_this_round": el.get("chance_of_playing_this_round") if el else None,
            "form":                        _safe_float(el.get("form"), 0.0) if el else 0.0,
            "total_points":                _safe_int(el.get("total_points"), 0) if el else 0,
            "is_captain":                  bool(pick.get("is_captain", False)),
            "is_vice_captain":             bool(pick.get("is_vice_captain", False)),
            "multiplier":                  _safe_int(pick.get("multiplier"), 1),
            "pick_position":               pick_position,
            "is_starter":                  pick_position <= 11,
        })

    entry_history: dict[str, Any] = picks_data.get("entry_history", {}) or {}
    active_chip_raw = picks_data.get("active_chip")
    active_chip = _FPL_TO_BACKEND_CHIP.get(active_chip_raw) if active_chip_raw else None

    result: dict[str, Any] = {
        "status":  "ok",
        "team_id": team_id,
        "gw":      resolved_gw,
        "players": players,
        "summary": {
            "gw_points":    entry_history.get("points"),
            "total_points": entry_history.get("total_points"),
            "bank":         entry_history.get("bank"),
            "active_chip":  active_chip,
        },
    }
    if gw_clamped:
        result["requested_gw"] = requested_gw
        result["gw_clamped"] = True
    return result


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_MY_SQUAD_SPEC = ToolSpec(
    name="get_my_squad",
    description=(
        "The connected user's own 15-man FPL squad for a gameweek: starting XI + bench "
        "(pick order), captain/vice-captain, price, injury/availability status, form, "
        "and any active chip. Use for 'mi equipo', 'mi plantilla', 'mis suplentes', "
        "'evalúa mi equipo', or any question about the user's OWN squad composition — "
        "never for a hypothetical or another manager's team. "
        "status='no_team_connected' when no team is linked (ask the user to connect one, "
        "never ask them to paste their 15 players by hand)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "gw": {
                "type":        "integer",
                "description": (
                    "Gameweek to fetch picks for (1-38). Defaults to the current gameweek. "
                    "A future GW has no published picks yet and is clamped down to the "
                    "current GW automatically (response gw_clamped=true, requested_gw echoes "
                    "what was asked for) — the current squad is still the right basis for "
                    "planning a future chip or transfer."
                ),
                "minimum":     1,
                "maximum":     38,
            },
        },
        "required":             [],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":  {"type": "string"},
            "team_id": {"type": "integer"},
            "gw":      {"type": "integer"},
            "players": {"type": "array"},
            "summary": {"type": "object"},
        },
    },
)


def _get_my_squad_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_my_squad()``."""
    try:
        return get_my_squad(bootstrap, gw=args.get("gw"))
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"get_my_squad raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("get_my_squad", ...) works.
TOOL_REGISTRY.register(GET_MY_SQUAD_SPEC, _get_my_squad_handler)
