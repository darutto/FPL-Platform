"""Grounded tool execution seams that need application-layer context.

Most tools pass straight through to :mod:`fpl_tool_runner`. Captain ranking is
the exception: the pure contract accepts squad IDs but must never fetch them.
This module resolves the connected squad before dispatching a derived ranking.

Chip advice (i108 E2) is the second exception: ``chip_advisor`` crosses the
user's squad against the favoured group but never fetches. When a team is
linked and the request did not carry the squad members, the linked squad is
fetched here ONCE per turn and cached under ``chip_advisor.LINKED_SQUAD_KEY``
on the bootstrap this call received.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import run_tool as _run_pure_tool

from .chip_advisor import LINKED_SQUAD_FAILED, LINKED_SQUAD_KEY
from .get_my_squad import get_my_squad, load_linked_squad


def _attach_linked_squad(bootstrap: dict[str, Any]) -> None:
    """Cache the linked squad on *bootstrap* for get_chip_advice (i108 E2).

    Writes only when ``_my_team_id`` is present, and that key only ever
    exists on a per-turn shallow copy: ``harness.ask_v2`` copies before
    injecting it (harness.py ``if team_id is not None: actual_bootstrap =
    dict(actual_bootstrap)``), ``/session`` does the same in fpl_server.py,
    and ``ask_orchestrated`` copies again for every turn (the i86
    ``QUESTION_CONTEXT_KEY`` copy). So the cache lives for one turn, is shared
    by every round of that turn (a second chip call does not refetch), and
    never reaches the server-level bootstrap.

    Skipped when the request's ``_squad_context`` already carries
    ``players`` (the request wins for the members) or when nothing is linked.
    A failed fetch is cached too (``LINKED_SQUAD_FAILED``) so it is not
    retried within the turn and the tool can say "linked but not fetched".
    """
    if not bootstrap.get("_my_team_id") or LINKED_SQUAD_KEY in bootstrap:
        return
    context = bootstrap.get("_squad_context")
    if isinstance(context, dict) and isinstance(context.get("players"), list):
        return
    try:
        squad = load_linked_squad(bootstrap)
    except Exception:  # noqa: BLE001 - squad enrichment is fail-soft
        squad = None
    bootstrap[LINKED_SQUAD_KEY] = squad if squad is not None else dict(LINKED_SQUAD_FAILED)


def run_tool(
    name: str,
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run a tool, enriching derived captain rankings with connected-squad IDs."""
    if name == "get_chip_advice":
        _attach_linked_squad(bootstrap)
        return _run_pure_tool(name, args, bootstrap)
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
