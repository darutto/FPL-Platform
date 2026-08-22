"""Tool surface for partial selection under a budget.

Thin adapter only, exactly like ``build_squad_tool``. It resolves a free-text
position and any locked player names to ids, converts the LLM's millions into
the solver's integer tenths, and hands over to ``squad_solver.select_players``.
It computes nothing itself: every number in the result comes from the solver,
so the tool output and the selection it describes cannot disagree.

Why the tool exists at all
--------------------------
``build_squad`` covers the full-15 question and is reached reliably. The far
more common shape is smaller: "which four midfielders does my budget allow?",
"dos buenos delanteros". A 15-man squad builder is the wrong tool for a
four-player question, so the model correctly declined to call it -- and then had
nothing deterministic for the budget arithmetic those questions still carry.

This is not a filter with extra steps. The four highest-scoring midfielders in
a price band can strand the budget: the eleven slots left over may have no legal
affordable filling, or the locked players plus the picks may put four in one
club. That answer looks right and is wrong in exactly the way the LLM was
already wrong. ``squad_solver`` therefore makes completability part of the
search space and re-proves it with ``exact_completion`` before returning.

Reuse, not re-implementation
----------------------------
Locked-player resolution is ``build_squad_tool._resolve_locked``, which is
itself ``get_player_snapshot``. Position aliases are
``transfer_suggestion._resolve_position``. Neither is re-derived here: this repo
has already paid for two rounds of duplicate-resolver consolidation, and a
locked player resolved by a third matcher would be a third round.

Registers ``select_players_within_budget`` in ``TOOL_REGISTRY`` as a
side-effect of import; ``__init__.py`` must import this module for
``run_tool("select_players_within_budget", ...)``.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from fpl_grounded_assistant.build_squad_tool import (
    DEFAULT_BUDGET_TENTHS,
    _resolve_locked,
)
from fpl_grounded_assistant.squad_solver import (
    DEFAULT_OBJECTIVE,
    POSITION_CODES,
    select_players as _select_players,
)
from fpl_grounded_assistant.tool_schema_registry import SELECT_PLAYERS_SCHEMA
from fpl_grounded_assistant.transfer_suggestion import _resolve_position


def _to_tenths(value: Any, field: str) -> tuple[int | None, dict[str, Any] | None]:
    """Millions in, integer ``now_cost`` tenths out. Money never stays a float."""
    if value is None:
        return None, None
    try:
        return int(round(float(value) * 10)), None
    except (TypeError, ValueError):
        return None, {
            "status": "invalid_argument",
            "code": f"bad_{field}",
            "message": f"{field} must be a number of millions, got {value!r}.",
        }


def _resolve_position_code(raw: Any) -> tuple[int | None, dict[str, Any] | None]:
    """Free-text position (English, Spanish or FPL code) to ``element_type``."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, {
            "status": "invalid_argument",
            "code": "missing_position",
            "message": (
                "position is required: pick one of goalkeeper, defender, midfielder or "
                "forward (GKP/DEF/MID/FWD). One position per call."
            ),
        }
    if isinstance(raw, int) and not isinstance(raw, bool) and raw in POSITION_CODES.values():
        return int(raw), None
    text = str(raw).strip()
    code = POSITION_CODES.get(text.upper()) or POSITION_CODES.get(
        _resolve_position(text) or ""
    )
    if code is None:
        return None, {
            "status": "invalid_argument",
            "code": "bad_position",
            "message": (
                f"Unknown position {raw!r}. Use goalkeeper, defender, midfielder or "
                "forward (GKP/DEF/MID/FWD, or portero/defensa/medio/delantero)."
            ),
        }
    return code, None


def select_players_within_budget(
    position: Any = None,
    count: Any = None,
    budget: float | None = None,
    locked_players: Any = None,
    max_price: float | None = None,
    min_price: float | None = None,
    objective: str = DEFAULT_OBJECTIVE,
    min_minutes: int = 1,
    bootstrap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick the best ``count`` players of one position that a squad can still absorb.

    ``budget`` is the FULL budget in millions (100.0 by default). Money already
    committed to a locked player is charged from it automatically -- do not
    subtract it first.
    """
    if bootstrap is None:
        return {
            "status": "error",
            "code": "no_bootstrap",
            "message": "select_players_within_budget requires live bootstrap data.",
        }

    code, early = _resolve_position_code(position)
    if early is not None:
        return early

    if count is None:
        return {
            "status": "invalid_argument",
            "code": "missing_count",
            "message": "count is required: how many players should be picked?",
        }
    if isinstance(count, bool):
        return {
            "status": "invalid_argument",
            "code": "bad_count",
            "message": f"count must be a whole number of players, got {count!r}.",
        }
    try:
        picks = int(count)
    except (TypeError, ValueError):
        return {
            "status": "invalid_argument",
            "code": "bad_count",
            "message": f"count must be a whole number of players, got {count!r}.",
        }

    if budget is None:
        budget_tenths = DEFAULT_BUDGET_TENTHS
    else:
        budget_tenths, early = _to_tenths(budget, "budget")
        if early is not None:
            return early

    max_price_tenths, early = _to_tenths(max_price, "max_price")
    if early is not None:
        return early
    min_price_tenths, early = _to_tenths(min_price, "min_price")
    if early is not None:
        return early

    locked_ids, early = _resolve_locked(locked_players, bootstrap)
    if early is not None:
        # ``_resolve_locked``'s messages end with "No squad was built." -- true
        # of build_squad, wrong here. Restate the consequence for this tool.
        message = str(early.get("message", "")).replace(
            "No squad was built.", "No players were selected."
        ).replace(
            "No squad was built:", "No players were selected:"
        )
        return {**early, "message": message}

    try:
        minutes_floor = int(min_minutes)
    except (TypeError, ValueError):
        minutes_floor = 1

    return _select_players(
        bootstrap,
        position=code,
        count=picks,
        budget_tenths=budget_tenths,
        locked_ids=locked_ids,
        objective=str(objective or DEFAULT_OBJECTIVE),
        min_minutes=minutes_floor,
        min_price_tenths=min_price_tenths,
        max_price_tenths=max_price_tenths,
    )


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

# The argument surface and the description live once, in the schema registry --
# see build_squad_tool for why two hand-maintained copies are a known failure.
SELECT_PLAYERS_SPEC = ToolSpec(
    name=SELECT_PLAYERS_SCHEMA.name,
    description=SELECT_PLAYERS_SCHEMA.description,
    parameters=SELECT_PLAYERS_SCHEMA.parameters,
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "code": {"type": "string"},
            "message": {"type": "string"},
            "position": {"type": "string"},
            "count": {"type": "integer"},
            "objective": {"type": "string"},
            "objective_optimality": {"type": "string"},
            "objective_total": {"type": "number"},
            "ranking_basis": {"type": "string"},
            "budget_tenths": {"type": "integer"},
            "budget": {"type": "number"},
            "locked_cost_tenths": {"type": "integer"},
            "locked_cost": {"type": "number"},
            "locked_players": {"type": "array"},
            "price_bounds": {"type": "object"},
            "candidate_pool": {"type": "object"},
            "min_minutes_filter": {"type": "integer"},
            "completable": {"type": "boolean"},
            "selection": {"type": "array"},
            "selection_cost_tenths": {"type": "integer"},
            "selection_cost": {"type": "number"},
            "remaining_tenths": {"type": "integer"},
            "remaining": {"type": "number"},
            "completion": {"type": "object"},
            "affordable": {"type": ["object", "null"]},
            "warnings": {"type": "array"},
        },
    },
)


def _select_players_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler -- delegates to ``select_players_within_budget()``."""
    try:
        return select_players_within_budget(
            position       = args.get("position"),
            count          = args.get("count"),
            budget         = args.get("budget"),
            locked_players = args.get("locked_players"),
            max_price      = args.get("max_price"),
            min_price      = args.get("min_price"),
            objective      = args.get("objective", DEFAULT_OBJECTIVE),
            min_minutes    = args.get("min_minutes", 1),
            bootstrap      = bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"select_players_within_budget raised an unexpected error: {exc}",
        }


# Register with the shared tool registry.
TOOL_REGISTRY.register(SELECT_PLAYERS_SPEC, _select_players_handler)
