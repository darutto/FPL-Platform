"""B4: ``get_position_changes`` -- where a player started, when that changed, and which teammates were missing.

A thin adapter. The analysis is :mod:`football_intelligence.position_changes` (pure, tested on its own); this module
resolves the people by FPL id, reads the synced licensed store and the FPL fixture list, and hands them over.

Resolution (the "João Pedro is not Costinha" rule): both players are resolved with ``tool_resolve_player``, which
matches whole names only and answers ``ambiguous`` with candidates rather than guessing; nothing here searches a name
for a substring. The teammate named as absent is additionally scoped to the player's own club by FPL id and club code:
"João Pedro" next to Rogers means the Chelsea player, and a player of another club is reported as not a teammate.

Provenance: the answer carries ``licensed_starter`` and the build time, never a store row or a provider id. If the
store is not synced (the flag is off, or nothing was published yet) the answer is ``missing_context``, not an empty
success.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from football_intelligence.position_changes import (
    DEFAULT_LIMIT, FPL_POSITIONS, MAX_LIMIT, FixtureMeta, analyse, fpl_position_gap,
)

_FIXTURE_TTL_SECONDS = 600
_fixture_cache: dict[str, Any] = {"at": 0.0, "rows": None}


def _missing(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "missing_context", "reason_codes": [reason], "matches": [], "evidence": [], **extra}


def _team_codes(bootstrap: Mapping[str, Any]) -> dict[int, str]:
    return {int(t["id"]): str(t["short_name"]) for t in bootstrap.get("teams", ())}


def _names(bootstrap: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    codes = _team_codes(bootstrap)
    return {int(e["id"]): {"web_name": e.get("web_name"), "team_short": codes.get(int(e.get("team", 0)))}
            for e in bootstrap.get("elements", ())}


#: FPL statuses that mean "not available to play": injured, suspended, unavailable. Doubtful ('d') is NOT an absence.
_OUT_STATUSES = {"i": "injury", "s": "suspension", "u": "unavailable"}
#: Words of FPL's news text -> the reason shown. Read only from the part BEFORE the first " - " ("Knee injury - Unknown
#: return date"): the tail ("Expected back 23 Nov") holds words like "back" that are not the injury.
_REASON_WORDS = ("knee", "ankle", "hamstring", "calf", "groin", "thigh", "foot", "back", "hip", "shoulder", "muscle", "illness")


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def fpl_out_notice(bootstrap: Mapping[str, Any], element: int) -> dict[str, Any] | None:
    """FPL's CURRENT out-news for the player, or None. Policy: it is attributed to a match only when its own date
    (``news_added``) is earlier than that match's kickoff (see :func:`attach_fpl_out`); FPL gives no history."""
    row = next((e for e in bootstrap.get("elements", ()) if int(e.get("id", 0)) == element), None)
    if row is None:
        return None
    kind = _OUT_STATUSES.get(str(row.get("status") or ""))
    added = _utc(row.get("news_added"))
    if kind is None or added is None:
        return None
    reason = kind
    if kind != "suspension":
        head = re.split(r"\s+-\s+", str(row.get("news") or ""), maxsplit=1)[0].lower()
        head = re.sub(r"expected back.*$", "", head).strip()  # "Expected back 3 Dec": 'back' is the return, not an injury
        reason = next((w for w in _REASON_WORDS if re.search(r"(?<![a-z])" + w + r"(?![a-z])", head)), kind)
    return {"reason": reason, "since": added.date().isoformat(), "_added": added}


def attach_fpl_out(matches: list[dict[str, Any]], notice: dict[str, Any] | None) -> int:
    """Put ``fpl_out`` on every match where he was on the bench or not listed AND the news predates the kickoff.
    Returns how many were marked. A match with no kickoff, or an earlier one than the news, is left untouched."""
    if notice is None:
        return 0
    marked = 0
    for m in matches:
        kickoff = _utc(m.get("kickoff"))
        if m.get("player_status") in ("bench", "not_listed") and kickoff is not None and notice["_added"] < kickoff:
            m["fpl_out"] = {"reason": notice["reason"], "since": notice["since"], "claim_status": "observed", "source": "fpl"}
            marked += 1
    return marked


def _fetch_all_fixtures() -> list[dict[str, Any]]:
    from fpl_api_client.fpl_client import get_all_fixtures
    return get_all_fixtures()


def fixture_index(bootstrap: Mapping[str, Any], fetch: Callable[[], list[dict[str, Any]]] | None = None) -> dict[int, FixtureMeta] | None:
    """FPL fixture id -> gameweek, kickoff and the two club codes. ``None`` when the list cannot be read."""
    rows = bootstrap.get("fixture_index")
    if rows is None:
        now = time.time()
        if _fixture_cache["rows"] is not None and now - _fixture_cache["at"] < _FIXTURE_TTL_SECONDS:
            rows = _fixture_cache["rows"]
        else:
            try:
                rows = (fetch or _fetch_all_fixtures)()
            except Exception:  # the FPL API being unreachable degrades this answer; it never raises into the turn
                return None
            _fixture_cache.update(at=now, rows=rows)
    codes = _team_codes(bootstrap)
    index: dict[int, FixtureMeta] = {}
    for row in rows:
        home, away = codes.get(int(row.get("team_h", 0))), codes.get(int(row.get("team_a", 0)))
        if home is None or away is None:
            continue
        event = row.get("event")
        index[int(row["id"])] = FixtureMeta(int(event) if event is not None else None, row.get("kickoff_time"), home, away)
    return index


def _resolve(query: Any, bootstrap: dict[str, Any], *, within_team: str | None = None) -> dict[str, Any]:
    from fpl_tool_contract import tool_resolve_player

    resolved = tool_resolve_player(query, bootstrap)
    if within_team is None:
        return resolved
    if resolved["status"] == "ambiguous":
        mates = [c for c in resolved["candidates"] if c.get("team_short") == within_team]
        if len(mates) == 1:
            return {"status": "ok", "player_id": mates[0]["id"], "team_short": within_team, "resolved_via": "teammate_scope"}
        if not mates:
            return {"status": "not_a_teammate", "query": str(query)}
        return {**resolved, "candidates": mates}
    if resolved["status"] == "ok" and resolved.get("team_short") != within_team:
        return {"status": "not_a_teammate", "query": str(query), "team_short": resolved.get("team_short")}
    return resolved


def run_position_changes(
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

    absent_element: int | None = None
    if args.get("absent_player"):
        absent = _resolve(args["absent_player"], bootstrap, within_team=own_team)
        if absent["status"] != "ok":
            return {**absent, "player": {"web_name": (_names(bootstrap).get(element) or {}).get("web_name")}}
        absent_element = int(absent["player_id"])
        if absent_element == element:
            # "who replaces X?" sometimes arrives with X as both arguments; the answer is slot_cover, and a focus on
            # his own absence would count the matches he started without himself (always 0).
            absent_element = None

    if handle is None:
        from football_intelligence.distribution.licensed_runtime import handle_from_env
        handle = handle_from_env()
    try:
        manifest = handle.manifest()
        tables = {name: handle.table(name) for name in ("lineup_snapshots", "lineup_slots", "sidelined", "squad_membership")}
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
    result = analyse(
        element=element, snapshots=tables["lineup_snapshots"], slots=tables["lineup_slots"],
        sidelined=tables["sidelined"], squad_membership=tables["squad_membership"], fixtures=fixtures,
        names=_names(bootstrap), limit=limit, absent_element=absent_element)
    if isinstance(result.get("matches"), list):
        attach_fpl_out(result["matches"], fpl_out_notice(bootstrap, element))
    if isinstance(result.get("matches"), list):
        row = next((e for e in bootstrap.get("elements", ()) if int(e.get("id", 0)) == element), None)
        element_type = row.get("element_type") if row else None
        if isinstance(element_type, int) and element_type in FPL_POSITIONS:
            result["fpl_position"] = FPL_POSITIONS[element_type]
            gap = fpl_position_gap(element_type, result["matches"])
            if gap is not None:
                result["fpl_position_gap"] = gap
    result["data_provenance"] = {"source": "licensed_starter", "built_at": manifest.get("built_at"),
                                 "slot_meaning": "announced_starting_xi"}
    result.setdefault("evidence", [])
    return result
