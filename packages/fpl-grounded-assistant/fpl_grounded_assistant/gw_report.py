"""
fpl_grounded_assistant.gw_report
================================
R1: ``get_gw_report`` -- a retrospective, factual report of one CLOSED gameweek
for the connected user's own FPL team.

What it is
----------
The 15 picks the manager really had **in that gameweek** (``entry/{id}/event/{gw}/picks``,
never the current squad), the effective XI after the official automatic
substitutions, captain / vice-captain, bench, the chip played, and the points
reconciled against the official numbers (``entry_history`` of the picks response
and ``entry/{id}/history``). Then two to five short stories, each carrying the
numbers that back it.

What it is not
--------------
* Not a forecast: there are no "expected points" and no projections anywhere
  in this module. "Less than their average of the last N gameweeks" is a
  historical comparison, never an expectation.
* Not "what we knew before": there is no pre-deadline snapshot, so the report
  is called retrospective and never claims foresight.
* Not an arbitrary-team lookup: the team id is read ONLY from
  ``bootstrap["_my_team_id"]`` (the connected team, injected by the harness);
  the tool schema has no team parameter, so text typed by the user can never
  select another manager's team (privacy).

Scoring rules honoured (no simplified recomputation)
-----------------------------------------------------
* Player points are the official live ``total_points`` of the gameweek, so a
  double gameweek is already the sum of both fixtures and a blank gameweek is 0.
* The effective XI uses the OFFICIAL ``automatic_subs`` of the picks response
  (who came in, who went out); nothing is re-simulated.
* Bench Boost: all 15 count and there are no automatic substitutions.
* Triple Captain: the captain's multiplier is the one FPL recorded (3).
* The armband moves to the vice-captain only when the captain played 0 minutes
  and the vice-captain's points count.
* Wildcard / Free Hit do not change scoring.
* Transfer hits: the official ``points`` are gross; ``net = gross - hit``.

If the computed gross sum does not equal the official one the report says so
(``reconciliation.reconciled is False``) instead of presenting its own number
as the official one.

Honest degradation
------------------
An open gameweek, a gameweek with no finished data, missing live data for a
picked player, a bad team id or a network failure all come back as structured
statuses (``missing_context`` / ``not_found`` / ``error``) -- never as a
half-filled report.

Grounding
---------
Every figure in a story lives in its ``evidence`` dict; the renderer and the
card only format those figures. The LLM writes nothing numeric.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from fpl_api_client.fpl_client import (
    get_element_summary,
    get_entry_history,
    get_entry_picks,
    get_event_live,
    get_fixtures,
)
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .get_my_squad import _FPL_TO_BACKEND_CHIP, _GW_MAX, _GW_MIN
from .find_players import _position_label, _safe_int, _team_short

_LOG = logging.getLogger(__name__)

#: How many previous played fixtures feed each historical comparison.
POINTS_WINDOW: int = 5
MINUTES_WINDOW: int = 3
#: A starter who played this many minutes and scored this few points is a
#: "did not add" story (2 points is the appearance floor for 60+ minutes).
NO_ADD_MIN_MINUTES: int = 60
NO_ADD_MAX_POINTS: int = 2
#: Minutes per fixture must move at least this much against the recent
#: average for a "minutes change" story.
MINUTES_SHIFT_MIN: int = 30
MAX_STORIES: int = 5


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _finished_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("finished")]


def _event(events: list[dict[str, Any]], gw: int) -> "dict[str, Any] | None":
    for e in events:
        if _safe_int(e.get("id"), 0) == gw:
            return e
    return None


def _missing(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "missing_context", "reason_codes": [reason], **extra}


def _player_name(el: "dict[str, Any] | None", element_id: Any) -> str:
    return str(el.get("web_name", "")) if el else f"#{element_id}"


# ---------------------------------------------------------------------------
# Pure builder
# ---------------------------------------------------------------------------

def build_gw_report(
    *,
    team_id: int,
    gw: int,
    picks: dict[str, Any],
    history_row: "dict[str, Any] | None",
    live: dict[str, Any],
    bootstrap: dict[str, Any],
    team_fixture_counts: "dict[int, int] | None" = None,
    player_histories: "dict[int, list[dict[str, Any]]] | None" = None,
    data_checked: bool = True,
    now: "datetime | None" = None,
) -> dict[str, Any]:
    """Build the report from already-fetched official payloads (no I/O).

    Returns ``{"status": "ok", ...}`` or ``missing_context`` when a picked
    player has no live row (the points cannot be reconciled honestly).
    """
    elements = {e.get("id"): e for e in bootstrap.get("elements", []) or []}
    teams = bootstrap.get("teams", []) or []
    element_types = bootstrap.get("element_types", []) or []
    live_by_id = {row.get("id"): row for row in live.get("elements", []) or []}
    player_histories = player_histories or {}

    raw_picks = sorted(picks.get("picks", []) or [], key=lambda p: _safe_int(p.get("position"), 0))
    if len(raw_picks) != 15:
        return _missing("picks_incomplete", gw=gw)
    for p in raw_picks:
        if p.get("element") not in live_by_id:
            return _missing("live_data_missing", gw=gw)

    chip_code = picks.get("active_chip")
    chip = _FPL_TO_BACKEND_CHIP.get(chip_code) if chip_code else None
    bench_boost = chip == "bench_boost"
    subs = [] if bench_boost else list(picks.get("automatic_subs") or [])
    sub_in_ids = {s.get("element_in") for s in subs}
    sub_out_ids = {s.get("element_out") for s in subs}

    def stats(eid: Any) -> dict[str, Any]:
        return (live_by_id.get(eid) or {}).get("stats") or {}

    def minutes(eid: Any) -> int:
        return _safe_int(stats(eid).get("minutes"), 0)

    def points(eid: Any) -> int:
        return _safe_int(stats(eid).get("total_points"), 0)

    def fixtures_played(eid: Any) -> int:
        return len((live_by_id.get(eid) or {}).get("explain") or [])

    # -- effective XI ------------------------------------------------------
    # The role is decided by the OFFICIAL substitution list, not by the pick
    # position: for a closed gameweek the picks response already carries the
    # post-substitution positions (the player who came on sits at 1-11, the
    # one who went off at 12-15), so reading the position alone would label
    # both of them wrongly. Going by id works for either arrangement.
    def role_of(p: dict[str, Any]) -> str:
        eid, pos = p.get("element"), _safe_int(p.get("position"), 0)
        if bench_boost:
            return "starter" if pos <= 11 else "bench_boost"
        if eid in sub_in_ids:
            return "autosub_in"
        if eid in sub_out_ids:
            return "autosub_out"
        return "starter" if pos <= 11 else "bench"

    counting_ids = {p["element"] for p in raw_picks if role_of(p) in ("starter", "autosub_in", "bench_boost")}

    # -- armband -----------------------------------------------------------
    cap_pick = next((p for p in raw_picks if p.get("is_captain")), None)
    vice_pick = next((p for p in raw_picks if p.get("is_vice_captain")), None)
    cap_mult = _safe_int(cap_pick.get("multiplier"), 2) if cap_pick else 2
    if cap_mult < 2:  # the recorded captain multiplier is 2 (3 with Triple Captain)
        cap_mult = 2
    effective_captain_id = None
    armband_moved = False
    if cap_pick and minutes(cap_pick["element"]) > 0 and cap_pick["element"] in counting_ids:
        effective_captain_id = cap_pick["element"]
    elif vice_pick and minutes(vice_pick["element"]) > 0 and vice_pick["element"] in counting_ids:
        effective_captain_id = vice_pick["element"]
        armband_moved = True

    # -- per-player rows ---------------------------------------------------
    rows: list[dict[str, Any]] = []
    for p in raw_picks:
        eid = p["element"]
        el = elements.get(eid)
        role = role_of(p)
        counts = eid in counting_ids
        applied = 0
        if counts:
            applied = cap_mult if eid == effective_captain_id else 1
        rows.append({
            "id": eid,
            "web_name": _player_name(el, eid),
            "team_short": _team_short(el, teams) if el else "",
            "position": _position_label(el, element_types) if el else "",
            "pick_position": _safe_int(p.get("position"), 0),
            "role": role,
            "minutes": minutes(eid),
            "points": points(eid),
            "multiplier": applied,
            "contribution": points(eid) * applied,
            "fixtures": fixtures_played(eid),
            "team_fixtures": (team_fixture_counts or {}).get(_safe_int(el.get("team"), -1)) if el else None,
            "is_captain": bool(p.get("is_captain")),
            "is_vice_captain": bool(p.get("is_vice_captain")),
            "is_effective_captain": eid == effective_captain_id,
        })
    by_id = {r["id"]: r for r in rows}

    # -- points reconciliation --------------------------------------------
    gross = sum(r["contribution"] for r in rows)
    entry_history = picks.get("entry_history") or {}
    official_picks = entry_history.get("points")
    official_history = history_row.get("points") if history_row else None
    hit_cost = _safe_int(entry_history.get("event_transfers_cost"), 0)
    officials = [v for v in (official_picks, official_history) if isinstance(v, int)]
    reconciled = bool(officials) and all(v == gross for v in officials)
    reference = official_history if isinstance(official_history, int) else official_picks
    bench_points = sum(r["points"] for r in rows if r["role"] == "bench")
    reconciliation = {
        "computed_gross": gross,
        "official_gross": reference,
        "official_picks": official_picks,
        "official_history": official_history,
        "difference": (gross - reference) if isinstance(reference, int) else None,
        "reconciled": reconciled,
        "transfer_cost": hit_cost,
        "net": gross - hit_cost,
        "official_points_on_bench": entry_history.get("points_on_bench"),
        "bench_points": bench_points,
    }

    stories = _stories(rows, by_id, subs, cap_mult, armband_moved, bench_boost, gw, player_histories)

    return {
        "status": "ok",
        "team_id": team_id,
        "gw": gw,
        "retrospective": True,
        "data_checked": bool(data_checked),
        "report_as_of": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d"),
        "chip": chip,
        "captain": _brief(by_id.get(cap_pick["element"])) if cap_pick else None,
        "vice_captain": _brief(by_id.get(vice_pick["element"])) if vice_pick else None,
        "effective_captain": _brief(by_id.get(effective_captain_id)) if effective_captain_id is not None else None,
        "armband_moved": armband_moved,
        "players": rows,
        "auto_subs": [
            {"in": _brief(by_id.get(s.get("element_in"))), "out": _brief(by_id.get(s.get("element_out")))}
            for s in subs
        ],
        "reconciliation": reconciliation,
        "stories": stories,
    }


def _brief(r: "dict[str, Any] | None") -> "dict[str, Any] | None":
    if r is None:
        return None
    return {k: r[k] for k in ("web_name", "team_short", "position", "minutes", "points", "multiplier", "contribution")}


# ---------------------------------------------------------------------------
# Stories (evidence only; no wording here)
# ---------------------------------------------------------------------------

def _history_rows(histories: dict[int, list[dict[str, Any]]], eid: int, gw: int) -> list[dict[str, Any]]:
    """Fixture rows played strictly before *gw*, oldest first, minutes > 0."""
    rows = [
        h for h in histories.get(eid, [])
        if _safe_int(h.get("round"), 0) < gw and _safe_int(h.get("minutes"), 0) > 0
    ]
    return sorted(rows, key=lambda h: (_safe_int(h.get("round"), 0), _safe_int(h.get("fixture"), 0)))


def _stories(
    rows: list[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
    subs: list[dict[str, Any]],
    cap_mult: int,
    armband_moved: bool,
    bench_boost: bool,
    gw: int,
    histories: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    stories: list[dict[str, Any]] = []
    counting = [r for r in rows if r["role"] in ("starter", "autosub_in", "bench_boost")]
    eff = next((r for r in rows if r["is_effective_captain"]), None)

    # 1. Captain against the best of the effective XI.
    if eff is not None and counting:
        best_pts = max(r["points"] for r in counting)
        tops = [r for r in counting if r["points"] == best_pts]
        if eff["points"] >= best_pts:
            stories.append({"kind": "captain_top", "evidence": {
                "captain": eff["web_name"], "captain_points": eff["points"], "multiplier": cap_mult,
                "contribution": eff["contribution"], "armband_moved": armband_moved,
                "tied_with": [r["web_name"] for r in tops if r["id"] != eff["id"]],
            }})
        else:
            best = sorted(tops, key=lambda r: r["pick_position"])[0]
            stories.append({"kind": "captain_gap", "evidence": {
                "captain": eff["web_name"], "captain_points": eff["points"], "multiplier": cap_mult,
                "contribution": eff["contribution"], "armband_moved": armband_moved,
                "best": best["web_name"], "best_points": best["points"],
                "extra_points": (best["points"] - eff["points"]) * cap_mult,
            }})

    # 2. Official automatic substitutions.
    for s in subs:
        r_in, r_out = by_id.get(s.get("element_in")), by_id.get(s.get("element_out"))
        if r_in and r_out:
            stories.append({"kind": "autosub", "evidence": {
                "player_in": r_in["web_name"], "points_in": r_in["points"], "minutes_in": r_in["minutes"],
                "player_out": r_out["web_name"], "minutes_out": r_out["minutes"],
                "out_team_fixtures": r_out["team_fixtures"],
            }})

    # 3. Bench: Bench Boost contribution, or points left unused.
    bench = [r for r in rows if r["pick_position"] >= 12 and r["role"] in ("bench", "bench_boost")]
    if bench_boost and bench:
        stories.append({"kind": "bench_boost", "evidence": {
            "bench_points": sum(r["points"] for r in bench),
            "best": max(bench, key=lambda r: r["points"])["web_name"],
            "best_points": max(r["points"] for r in bench),
        }})
    elif not bench_boost:
        unused = [r for r in rows if r["role"] == "bench"]
        total = sum(r["points"] for r in unused)
        if total > 0:
            top = max(unused, key=lambda r: r["points"])
            stories.append({"kind": "bench_points", "evidence": {
                "bench_points": total, "best": top["web_name"], "best_points": top["points"],
            }})

    # 4. Played the minutes but only the appearance points.
    cands = [
        r for r in counting
        if not r["is_effective_captain"] and r["position"] in ("MID", "FWD")
        and r["minutes"] >= NO_ADD_MIN_MINUTES and r["points"] <= NO_ADD_MAX_POINTS
    ]
    if cands:
        r = sorted(cands, key=lambda c: (c["points"], -c["minutes"], c["pick_position"]))[0]
        ev: dict[str, Any] = {"player": r["web_name"], "minutes": r["minutes"], "points": r["points"]}
        prev = _history_rows(histories, r["id"], gw)[-POINTS_WINDOW:]
        if prev:
            n_fix = max(r["fixtures"], 1)
            ev.update({
                "this_gw_points_per_fixture": round(r["points"] / n_fix, 1),
                "recent_average": round(sum(_safe_int(h.get("total_points"), 0) for h in prev) / len(prev), 1),
                "recent_n": len(prev),
            })
        stories.append({"kind": "no_add", "evidence": ev})

    # 5. Minutes that moved against the recent run.
    best_shift: "tuple[int, dict[str, Any]] | None" = None
    for r in rows:
        if r["fixtures"] == 0 or r["role"] == "autosub_out":
            continue  # the substitution story already covers a player who did not play
        prev = _history_rows(histories, r["id"], gw)[-MINUTES_WINDOW:]
        if not prev:
            continue
        avg = sum(_safe_int(h.get("minutes"), 0) for h in prev) / len(prev)
        now_per_fixture = r["minutes"] / r["fixtures"]
        shift = abs(now_per_fixture - avg)
        if shift >= MINUTES_SHIFT_MIN and (best_shift is None or shift > best_shift[0]):
            best_shift = (int(shift), {
                "player": r["web_name"], "minutes": r["minutes"], "fixtures": r["fixtures"],
                "per_fixture": round(now_per_fixture),
                "recent_average": round(avg), "recent_n": len(prev),
                "direction": "up" if now_per_fixture > avg else "down",
            })
    if best_shift is not None:
        stories.append({"kind": "minutes_change", "evidence": best_shift[1]})

    return stories[:MAX_STORIES]


# ---------------------------------------------------------------------------
# Fetching + tool entry point
# ---------------------------------------------------------------------------

def _team_fixture_counts(gw: int) -> "dict[int, int] | None":
    try:
        counts: dict[int, int] = {}
        for fx in get_fixtures(gw):
            for side in ("team_h", "team_a"):
                tid = _safe_int(fx.get(side), -1)
                counts[tid] = counts.get(tid, 0) + 1
        return counts
    except Exception:  # noqa: BLE001 -- context only; the report degrades visibly (team_fixtures=None)
        return None


def _fetch_histories(ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    def one(eid: int) -> "tuple[int, list[dict[str, Any]] | None]":
        try:
            return eid, list(get_element_summary(eid).get("history") or [])
        except Exception:  # noqa: BLE001 -- historical stories simply drop for this player
            return eid, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return {eid: hist for eid, hist in pool.map(one, ids) if hist is not None}


def get_gw_report(
    bootstrap: "dict[str, Any] | None",
    gameweek: "int | None" = None,
    *,
    now: "datetime | None" = None,
) -> dict[str, Any]:
    """Tool entry point: the connected user's retrospective report for a closed gameweek."""
    team_id = bootstrap.get("_my_team_id") if bootstrap else None
    if not team_id:
        return {"status": "no_team_connected", "code": "no_team_connected"}

    events: list[dict[str, Any]] = (bootstrap or {}).get("events", []) or []
    if gameweek is None:
        done = _finished_events(events)
        if not done:
            return _missing("no_finished_gameweek")
        gw = max(_safe_int(e.get("id"), 0) for e in done)
    else:
        gw = _safe_int(gameweek, 0)
        if gw < _GW_MIN or gw > _GW_MAX:
            return {"status": "error", "code": "invalid_gw", "min_gw": _GW_MIN, "max_gw": _GW_MAX}
    ev = _event(events, gw)
    if ev is None or not ev.get("finished"):
        return _missing("gw_not_finished", gw=gw)

    try:
        picks = get_entry_picks(int(team_id), gw)
        live = get_event_live(gw)
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 404:
            return {"status": "not_found", "code": "team_not_found", "team_id": team_id}
        return {"status": "error", "code": "network_error"}
    except requests.RequestException:
        return {"status": "error", "code": "network_error"}

    history_row = None
    try:
        for row in get_entry_history(int(team_id)).get("current", []) or []:
            if _safe_int(row.get("event"), 0) == gw:
                history_row = row
    except requests.RequestException:
        history_row = None  # reconciliation falls back to the picks response's own official row

    ids = [p.get("element") for p in picks.get("picks", []) or [] if isinstance(p.get("element"), int)]
    return build_gw_report(
        team_id=int(team_id), gw=gw, picks=picks, history_row=history_row, live=live,
        bootstrap=bootstrap or {}, team_fixture_counts=_team_fixture_counts(gw),
        player_histories=_fetch_histories(ids), data_checked=bool(ev.get("data_checked")), now=now,
    )


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_GW_REPORT_SPEC = ToolSpec(
    name="get_gw_report",
    description=(
        "Retrospective report of one CLOSED gameweek for the connected user's OWN FPL team: "
        "the 15 picks of that gameweek, effective XI after automatic substitutions, "
        "captain/vice, bench, chip played, points reconciled with the official numbers, and "
        "two to five evidence-backed stories. Use for 'cómo me fue en la jornada X', "
        "'resumen de mi última jornada', 'my gameweek review'. Never for another manager's "
        "team, never for an open or future gameweek, never a forecast."
    ),
    parameters={
        "type": "object",
        "properties": {
            "gameweek": {
                "type": "integer",
                "description": "Closed gameweek (1-38). Defaults to the last finished gameweek.",
                "minimum": _GW_MIN,
                "maximum": _GW_MAX,
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
)


def _handler(args: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_gw_report(bootstrap, gameweek=args.get("gameweek"))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("get_gw_report raised %s", type(exc).__name__)
        return {"status": "error", "code": "tool_exception"}


TOOL_REGISTRY.register(GET_GW_REPORT_SPEC, _handler)
