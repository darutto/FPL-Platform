"""Tool surface for the exact squad solver.

Thin adapter only. It resolves Spanish/English player names to element ids,
converts the LLM's millions into the solver's integer tenths, and hands over to
``squad_solver.build_squad``. It computes nothing itself: every number in the
result comes from the solver, so the tool output and the squad it describes
cannot disagree.

Name resolution reuses ``get_player_snapshot`` rather than matching names here.
That is deliberate -- this repo has already paid for two rounds of duplicate
resolver consolidation, and a locked player resolved by a second matcher would
be a third.

Registers ``build_squad`` in ``TOOL_REGISTRY`` as a side-effect of import;
``__init__.py`` must import this module for ``run_tool("build_squad", ...)``.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
from fpl_grounded_assistant.squad_solver import (
    DEFAULT_OBJECTIVE,
    POSITION_CODES,
    build_squad as _build_squad,
)
from fpl_grounded_assistant.tool_schema_registry import BUILD_SQUAD_SCHEMA


DEFAULT_BUDGET_TENTHS: int = 1000


def _resolve_locked(
    entries: Any, bootstrap: dict[str, Any]
) -> tuple[list[int], dict[str, Any] | None]:
    """Resolve locked-player entries to element ids.

    Returns ``(ids, early_result)``. ``early_result`` is non-None when a name
    could not be pinned to exactly one player -- the caller must surface that
    instead of guessing, because a wrong lock silently changes the whole squad.
    """
    if entries is None:
        return [], None
    if isinstance(entries, (str, int)) and not isinstance(entries, bool):
        entries = [entries]
    if not isinstance(entries, (list, tuple)):
        return [], {
            "status": "invalid_argument",
            "code": "bad_locked_players",
            "message": "locked_players must be a list of player names or element ids.",
        }

    ids: list[int] = []
    for entry in entries:
        if isinstance(entry, bool) or not isinstance(entry, (str, int)):
            return [], {
                "status": "invalid_argument",
                "code": "bad_locked_players",
                "message": "Each locked player must be a name string or an element id.",
            }
        snapshot = get_player_snapshot(entry, bootstrap)
        status = snapshot.get("status")
        if status == "ok":
            ids.append(int(snapshot["player"]["id"]))
            continue
        if status == "ambiguous":
            return [], {
                "status": "ambiguous",
                "query": snapshot.get("query"),
                "candidates": snapshot.get("candidates", []),
                "message": (
                    f"{snapshot.get('message')} "
                    "No squad was built: locking the wrong player would change every "
                    "other pick."
                ),
            }
        return [], {
            "status": "not_found",
            "query": snapshot.get("query"),
            "message": (
                f"{snapshot.get('message', 'Player not found.')} "
                "No squad was built."
            ),
        }
    return ids, None


def _resolve_position_counts(raw: Any) -> tuple[dict[int, int] | None, dict[str, Any] | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, {
            "status": "invalid_argument",
            "code": "bad_position_counts",
            "message": "position_counts must be an object like {'DEF': 5, 'MID': 5}.",
        }
    counts: dict[int, int] = {}
    for key, value in raw.items():
        code = POSITION_CODES.get(str(key).strip().upper())
        if code is None:
            return None, {
                "status": "invalid_argument",
                "code": "bad_position_counts",
                "message": f"Unknown position '{key}'. Use GKP, DEF, MID and FWD.",
            }
        try:
            counts[code] = int(value)
        except (TypeError, ValueError):
            return None, {
                "status": "invalid_argument",
                "code": "bad_position_counts",
                "message": f"position_counts['{key}'] must be an integer.",
            }
    return counts, None


def build_squad(
    budget: float | None = None,
    locked_players: Any = None,
    formation: Any = None,
    position_counts: Any = None,
    objective: str = DEFAULT_OBJECTIVE,
    min_minutes: int = 1,
    bootstrap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the best legal 15-man squad under a budget, or prove none exists.

    ``budget`` is the FULL budget in millions (100.0 by default). Money already
    committed to a locked player is charged from it automatically -- do not
    subtract it first.
    """
    if bootstrap is None:
        return {
            "status": "error",
            "code": "no_bootstrap",
            "message": "build_squad requires live bootstrap data.",
        }

    if budget is None:
        budget_tenths = DEFAULT_BUDGET_TENTHS
    else:
        try:
            budget_tenths = int(round(float(budget) * 10))
        except (TypeError, ValueError):
            return {
                "status": "invalid_argument",
                "code": "bad_budget",
                "message": f"budget must be a number of millions, got {budget!r}.",
            }

    locked_ids, early = _resolve_locked(locked_players, bootstrap)
    if early is not None:
        return early

    counts, early = _resolve_position_counts(position_counts)
    if early is not None:
        return early

    try:
        minutes_floor = int(min_minutes)
    except (TypeError, ValueError):
        minutes_floor = 1

    return _build_squad(
        bootstrap,
        budget_tenths=budget_tenths,
        locked_ids=locked_ids,
        position_counts=counts,
        objective=str(objective or DEFAULT_OBJECTIVE),
        min_minutes=minutes_floor,
        formation=formation,
    )


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

# The argument surface and the description live once, in the schema registry.
# Two hand-maintained copies drift, and a drifted tool description is exactly
# the failure 7a05a96 fixed: a description promising coverage the tool lacked
# sent models to the wrong tool, silently. The registry is a pure data layer
# with no imports from the live stack, so depending on it here is safe.
BUILD_SQUAD_SPEC = ToolSpec(
    name=BUILD_SQUAD_SCHEMA.name,
    description=BUILD_SQUAD_SCHEMA.description,
    parameters=BUILD_SQUAD_SCHEMA.parameters,
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "objective": {"type": "string"},
            "objective_optimality": {"type": "string"},
            "objective_total": {"type": "number"},
            "ranking_basis": {"type": "string"},
            "squad_size": {"type": "integer"},
            "position_counts": {"type": "object"},
            "club_counts": {"type": "object"},
            "budget_tenths": {"type": "integer"},
            "budget": {"type": "number"},
            "total_cost_tenths": {"type": "integer"},
            "total_cost": {"type": "number"},
            "remaining_tenths": {"type": "integer"},
            "remaining": {"type": "number"},
            "locked_cost_tenths": {"type": "integer"},
            "locked_cost": {"type": "number"},
            "squad": {"type": "array"},
            "formation": {"type": ["string", "null"]},
            "starting_xi": {"type": "array"},
            "bench": {"type": "array"},
            "min_minutes_filter": {"type": "integer"},
            "warnings": {"type": "array"},
            "minimum_possible_cost": {"type": ["number", "null"]},
            "message": {"type": "string"},
        },
    },
)


def _build_squad_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``build_squad()``."""
    try:
        return build_squad(
            budget          = args.get("budget"),
            locked_players  = args.get("locked_players"),
            formation       = args.get("formation"),
            position_counts = args.get("position_counts"),
            objective       = args.get("objective", DEFAULT_OBJECTIVE),
            min_minutes     = args.get("min_minutes", 1),
            bootstrap       = bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"build_squad raised an unexpected error: {exc}",
        }


# Register with the shared tool registry.
TOOL_REGISTRY.register(BUILD_SQUAD_SPEC, _build_squad_handler)
