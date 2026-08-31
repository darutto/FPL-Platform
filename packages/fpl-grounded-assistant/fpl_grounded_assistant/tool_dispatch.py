"""Grounded tool execution seams that need application-layer context.

Most tools pass straight through to :mod:`fpl_tool_runner`. Captain ranking is
the exception: the pure contract accepts squad IDs but must never fetch them.
This module resolves the connected squad before dispatching a derived ranking.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import run_tool as _run_pure_tool

from .get_my_squad import get_my_squad


def run_tool(
    name: str,
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run a tool, enriching derived captain rankings with connected-squad IDs."""
    if name != "rank_captain_candidates" or args.get("candidates"):
        return _run_pure_tool(name, args, bootstrap)

    enriched_args = dict(args)
    team_id = bootstrap.get("_my_team_id")
    if not team_id:
        return _run_pure_tool(name, enriched_args, bootstrap)

    try:
        squad = get_my_squad(bootstrap, gw=args.get("gameweek"))
    except Exception:  # noqa: BLE001 - squad enrichment is fail-soft
        squad = {"status": "error", "code": "squad_fetch_failed"}
    if squad.get("status") == "ok":
        enriched_args["squad_player_ids"] = [
            player["id"]
            for player in squad.get("players", [])
            if player.get("id") is not None
        ]
        return _run_pure_tool(name, enriched_args, bootstrap)

    result = _run_pure_tool(name, enriched_args, bootstrap)
    result = dict(result)
    result["squad_source"] = (
        "not_connected"
        if squad.get("status") == "no_team_connected"
        else "unavailable"
    )
    return result
