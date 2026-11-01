"""R6: ``get_player_involvement`` -- touches, passes and backward passes per match, with or without a teammate, or
side by side with another player (``compare_player``, any club).

A thin adapter, like :mod:`position_changes_tool` (whose resolution it reuses, so "João Pedro is not Costinha" holds
here too): both players are resolved by whole name with ``tool_resolve_player``, the teammate is scoped to the player's
own club by FPL id and club code, and the store is read through the synced licensed handle. The analysis is
:mod:`football_intelligence.player_involvement` (pure, tested on its own).

With ``compare_player`` both players are analysed over the same store and limit and the answer gains ``compare`` (the
second player's answer) and ``comparison`` (:func:`football_intelligence.player_involvement.compare`). An ambiguous
``compare_player`` answers ``ambiguous`` with ``query`` = that mention, so a rewrite chip swaps the right name. It cannot
be combined with ``absent_player``.

If the store is not synced, or holds no statistics yet (builds written before R6, or no finished match ingested with
details), the answer is ``missing_context``, never an empty success. Nothing raw leaves: no row, no provider id, no
fixture id; the output is derived values per player and match.
"""
from __future__ import annotations

from typing import Any, Callable

from football_intelligence.player_involvement import DEFAULT_LIMIT, MAX_LIMIT, analyse, compare

from .position_changes_tool import _missing, _names, _resolve, fixture_index


def run_player_involvement(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
    *,
    handle: Any = None,
    fetch_fixtures: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Execute the tool. ``handle`` and ``fetch_fixtures`` are the seams the tests use."""
    player = _resolve(args.get("player"), bootstrap)
    if player["status"] != "ok":
        return player
    element = int(player["player_id"])
    own_team = player.get("team_short")

    if args.get("compare_player") and args.get("absent_player"):
        return {"status": "invalid_args", "reason_codes": ["compare_player_with_absent_player"], "matches": [],
                "evidence": []}
    other_element: int | None = None
    if args.get("compare_player"):
        other = _resolve(args["compare_player"], bootstrap)
        if other["status"] != "ok":
            return {**other, "query": str(args["compare_player"]), "slot": "compare_player"}
        other_element = int(other["player_id"])

    absent_element: int | None = None
    if args.get("absent_player"):
        absent = _resolve(args["absent_player"], bootstrap, within_team=own_team)
        if absent["status"] != "ok":
            return {**absent, "player": {"web_name": (_names(bootstrap).get(element) or {}).get("web_name")}}
        absent_element = int(absent["player_id"])

    if handle is None:
        from football_intelligence.distribution.licensed_runtime import handle_from_env
        handle = handle_from_env()
    try:
        manifest = handle.manifest()
        stats = handle.table("player_match_stats")
    except Exception:
        return _missing("licensed_store_unavailable", player_id=element)

    fixtures = fixture_index(bootstrap, fetch_fixtures)
    if fixtures is None:
        return _missing("fixture_list_unavailable", player_id=element)

    limit = args.get("matches", DEFAULT_LIMIT)
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    result = analyse(element=element, stats=stats, fixtures=fixtures, names=_names(bootstrap), limit=limit,
                     absent_element=absent_element)
    if other_element is not None and result.get("status") == "ok":
        second = analyse(element=other_element, stats=stats, fixtures=fixtures, names=_names(bootstrap), limit=limit)
        if second.get("status") == "ok":
            result["compare"] = second
            result["comparison"] = compare(result, second)
        else:  # the first player's answer stands; the second has nothing stored yet, and that is said
            result["compare_missing"] = {"player": second.get("player"), "reason_codes": second.get("reason_codes", [])}
    result["data_provenance"] = {"source": "licensed_starter", "built_at": manifest.get("built_at"),
                                 "stat_meaning": "provider_match_totals"}
    result.setdefault("evidence", [])
    return result
