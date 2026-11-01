"""B4: where a player started and who was missing, from the licensed matchday store. Pure: frames in, dict out.

What this module may claim, and what it may not. The store holds the **announced starting XI** (a provisional one
before the club confirms it, then the confirmed one). So every slot here is "where the player was listed to start",
never a movement during the match. Three kinds of statement come out, each marked with ``claim_status``:

* ``observed``    a fact of the stored lineup: the player started in this slot, or did not start.
* ``associated``  two observed facts that coincide: a regular teammate was not in the starting XI (or was on the
                  provider's sidelined list on that date) in the same match where the player started elsewhere.
                  Coinciding is all it says; it names no cause.
* ``hypothesis``  a possible link that the data does not establish (a teammate who was absent usually held the
                  position the player took). Always presented as unproven.

Absence from the starting XI is not an injury: ``presence`` says whether the teammate was on the bench or not listed,
and the sidelined list is reported separately. A teammate "not listed" may also be a player the identity crosswalk
could not map (the store drops those), so ``may_be_unmapped`` is set when fewer starters were resolved than the
lineup announced.

Identity: everything joins on the FPL element id and the club code stored on the lineup row; the club comes from the
row of the match, never from a name, so a player who moved club is read for the club he played for that day.
No name is ever matched here; names are only attached afterwards for display.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

import pandas as pd

from .grid import grid_row, line_depth

OBSERVED = "observed"
ASSOCIATED = "associated"
HYPOTHESIS = "hypothesis"

#: Fewer matches with a stored lineup than this and the answer says the sample is small.
SMALL_SAMPLE_BELOW = 5
#: Prior starts needed before a "changed" statement is made at all.
MIN_BASELINE_STARTS = 2
#: How many prior starts form the baseline, and how many prior team matches define a "regular" teammate.
BASELINE_STARTS = 5
REGULAR_WINDOW = 5
#: Across formations, how far the normalised line depth (0.0 back line .. 1.0 front line) must move to count as another line.
LINE_STEP_MIN = 0.25

#: With an absent teammate, matches needed on EACH side (without him / with him) before the answer drops the warning.
ABSENCE_MIN_EACH_SIDE = 3
#: Associated teammates named per match; the rest are only counted.
MAX_ASSOCIATIONS = 2
DEFAULT_LIMIT = 6
MAX_LIMIT = 10


@dataclass(frozen=True)
class FixtureMeta:
    """What the store does not hold about an FPL fixture. ``home``/``away`` are the FPL club codes."""

    gameweek: int | None
    kickoff: str | None  # ISO 8601, UTC
    home: str
    away: str


@dataclass(frozen=True)
class _Lineup:
    fixture_id: int
    team: str
    observed_at: str
    confirmed: bool
    formation: str | None
    n_starters: int
    starters: Mapping[int, Mapping[str, Any]]
    bench: frozenset[int]

    @property
    def unresolved_starters(self) -> bool:
        return len(self.starters) < self.n_starters


def _clean(value: Any) -> Any:
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def _lineups(snapshots: pd.DataFrame, slots: pd.DataFrame) -> dict[tuple[int, str], _Lineup]:
    """One lineup per (fixture, club): the latest confirmed observation, else the latest provisional one."""
    chosen: dict[tuple[int, str], dict[str, Any]] = {}
    for row in snapshots.to_dict("records"):
        key = (int(row["fixture_id"]), str(row["team"]))
        rank = (bool(row["confirmed"]), str(row["observed_at"]))
        if key not in chosen or rank > (bool(chosen[key]["confirmed"]), str(chosen[key]["observed_at"])):
            chosen[key] = row
    by_obs: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for row in slots.to_dict("records"):
        by_obs.setdefault((int(row["fixture_id"]), str(row["team"]), str(row["observed_at"])), []).append(row)
    lineups: dict[tuple[int, str], _Lineup] = {}
    for (fixture_id, team), snap in chosen.items():
        rows = by_obs.get((fixture_id, team, str(snap["observed_at"])), [])
        starters = {int(r["element"]): r for r in rows if bool(r["starter"])}
        bench = frozenset(int(r["element"]) for r in rows if not bool(r["starter"]))
        lineups[(fixture_id, team)] = _Lineup(
            fixture_id, team, str(snap["observed_at"]), bool(snap["confirmed"]), _clean(snap["formation"]),
            int(snap["n_starters"]), starters, bench)
    return lineups


def _order_key(fixture_id: int, fixtures: Mapping[int, FixtureMeta]) -> tuple[str, int, int]:
    meta = fixtures[fixture_id]
    return (meta.kickoff or "9999", meta.gameweek if meta.gameweek is not None else 99, fixture_id)


def _slot(row: Mapping[str, Any], formation: str | None) -> dict[str, Any]:
    return {"grid_slot": _clean(row["grid_slot"]), "detailed_position": _clean(row["detailed_position"]),
            "side": _clean(row["side"]), "formation": formation}


def _role(slot: Mapping[str, Any]) -> tuple[Any, Any]:
    return (slot.get("detailed_position"), slot.get("side"))


def _mode(values: Iterable[Any]) -> Any:
    """The strictly most common value, or None when there is a tie (no mode is better than a coin flip)."""
    ranked = Counter(values).most_common(2)
    if not ranked or (len(ranked) == 2 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


def _role_dict(role: tuple[Any, Any]) -> dict[str, Any]:
    return {"detailed_position": role[0], "side": role[1]}


def _sidelined_on(sidelined: pd.DataFrame, element: int, day: date | None) -> dict[str, Any] | None:
    """The provider's open absence record covering ``day`` for the element, if any (latest observation wins)."""
    if day is None or sidelined.empty:
        return None
    best: dict[str, Any] | None = None
    for row in sidelined[sidelined["element"].astype(int) == element].to_dict("records"):
        start = _to_date(row["start_date"])
        end = _to_date(row["end_date"])
        if start is None or start > day or (end is not None and end < day):
            continue
        if best is None or str(row["observed_at"]) > str(best["observed_at"]):
            best = row
    if best is None:
        return None
    return {"category": best["category"], "since": best["start_date"], "ended": _clean(best["end_date"])}


def _to_date(value: Any) -> date | None:
    value = _clean(value)
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _person(element: int, names: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    info = names.get(element, {})
    return {"player_id": element, "web_name": info.get("web_name"), "team_short": info.get("team_short")}


def analyse(
    *,
    element: int,
    snapshots: pd.DataFrame,
    slots: pd.DataFrame,
    sidelined: pd.DataFrame,
    squad_membership: pd.DataFrame,
    fixtures: Mapping[int, FixtureMeta],
    names: Mapping[int, Mapping[str, Any]],
    limit: int = DEFAULT_LIMIT,
    absent_element: int | None = None,
) -> dict[str, Any]:
    """Slots per match for one player, changes against his own recent starts, and who was missing.

    ``absent_element`` focuses on one teammate: the player's slots in the matches that teammate did not start
    against those he did.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    lineups = _lineups(snapshots, slots)
    without_meta = sum(1 for (fid, _t) in lineups if fid not in fixtures)
    usable = {key: lu for key, lu in lineups.items() if key[0] in fixtures}

    # The club: the one on the most recent lineup row of the player; else the latest squad record.
    appearances = [(key, lu) for key, lu in usable.items() if element in lu.starters or element in lu.bench]
    if appearances:
        appearances.sort(key=lambda item: _order_key(item[0][0], fixtures))
        team = appearances[-1][0][1]
    else:
        squad = squad_membership[squad_membership["element"].astype(int) == element]
        if squad.empty:
            return _missing("player_not_in_licensed_store", without_meta)
        team = str(squad.sort_values("observed_at").iloc[-1]["team"])
    first_seen = min(
        [str(r["observed_at"]) for r in squad_membership[
            (squad_membership["element"].astype(int) == element) & (squad_membership["team"] == team)
        ].to_dict("records")]
        + [lu.observed_at for (_fid, t), lu in appearances if t == team],
        default=None,
    )

    matches = sorted((lu for (fid, t), lu in usable.items() if t == team), key=lambda lu: _order_key(lu.fixture_id, fixtures))
    if not matches:
        return _missing("no_lineups_for_the_players_club", without_meta)

    def status_of(lu: _Lineup) -> str:
        if element in lu.starters:
            return "started"
        if element in lu.bench:
            return "bench"
        # Before the player is first seen with this club he is not "missing" from its lineups.
        return "not_listed" if first_seen is not None and first_seen <= lu.observed_at else "not_with_club"

    records: list[dict[str, Any]] = []
    for i, lu in enumerate(matches):
        meta = fixtures[lu.fixture_id]
        status = status_of(lu)
        if status == "not_with_club":
            continue
        slot = _slot(lu.starters[element], lu.formation) if status == "started" else None
        is_home = meta.home == team
        record: dict[str, Any] = {
            "gameweek": meta.gameweek, "kickoff": meta.kickoff, "opponent": meta.away if is_home else meta.home,
            "is_home": is_home, "lineup_status": "confirmed" if lu.confirmed else "provisional",
            "player_status": status, "slot": slot, "claim_status": OBSERVED,
            "change": None, "associations": [], "_index": i, "_fixture_id": lu.fixture_id,
        }
        records.append(record)

    # Changes against the player's own prior starts, and the teammates missing in the same match.
    started_so_far: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        lu = matches[record["_index"]]
        if record["player_status"] == "started":
            prior = started_so_far[-BASELINE_STARTS:]
            if len(prior) >= MIN_BASELINE_STARTS:
                base_role = _mode(_role(s) for _i, s in prior)
                base_slot = _mode(s["grid_slot"] for _i, s in prior)
                now = record["slot"]
                kind = None
                line: dict[str, Any] | None = None
                if base_role is not None and _role(now)[0] != base_role[0]:
                    kind = "position"
                elif base_role is not None and _role(now)[1] != base_role[1]:
                    kind = "side"
                elif base_slot is not None and now["grid_slot"] != base_slot:
                    # Same role, another cell of the grid: say whether that is a different line, only another
                    # column of the same line (not a change), or a shift we cannot compare across formations.
                    line = _line_shift(now, [s for _i, s in prior if _role(s) == _role(now)])
                    if line["result"] in ("further_forward", "deeper"):
                        kind = "line"
                    elif line["result"] == "column_only":
                        record["column_shift"] = True
                    elif line["result"] == "not_comparable":
                        record["line_comparable"] = False
                if kind is not None:
                    record["change"] = {
                        "kind": kind, "claim_status": OBSERVED, "baseline_starts": len(prior),
                        "from": _role_dict(base_role) if base_role is not None else {"grid_slot": base_slot},
                        "to": _role_dict(_role(now)),
                    }
                    if kind == "line":
                        record["change"]["direction"] = line["result"]
                        record["change"]["basis"] = line["basis"]
                    found = _associations(
                        matches, record["_index"], lu, fixtures, element, base_role, _role(now), sidelined, names)
                    record["associations"] = found[:MAX_ASSOCIATIONS]
                    record["associations_more"] = max(0, len(found) - MAX_ASSOCIATIONS)
            started_so_far.append((record["_index"], record["slot"]))
    recent = records[-limit:]
    cover = _slot_cover(matches, records, recent, fixtures, element, names)
    absence = (_absence_focus(matches, records, fixtures, absent_element, team, sidelined, names)
               if absent_element is not None else None)
    for record in records:
        record.pop("_index")
        record.pop("_fixture_id")

    result: dict[str, Any] = {
        "status": "ok" if recent else "missing_context",
        "player": _person(element, names),
        "matches": recent,
        "sample": {"matches_with_stored_lineup": len(records),
                   "small_sample": len(records) < SMALL_SAMPLE_BELOW,
                   "lineups_needed": max(0, SMALL_SAMPLE_BELOW - len(records)),
                   "first_stored_gameweek": next((m["gameweek"] for m in records if m["gameweek"] is not None), None)},
        "fixtures_without_metadata": without_meta,
    }
    if absence is not None:
        result["absence_focus"] = absence
    if cover is not None:
        result["slot_cover"] = cover
    return result


def _slot_cover(matches, records, recent, fixtures, element, names) -> dict[str, Any] | None:
    """Who held the player's usual slot in the announced XI of the matches he did not start (``observed`` only).

    The usual slot is the strict mode of ``(detailed_position, side)`` over his last ``BASELINE_STARTS`` starts, needing
    at least ``MIN_BASELINE_STARTS`` of them. A teammate who shared that role with him in those starts (two centre
    forwards, two central midfielders) is not counted as occupying his slot. When nobody else in a lineup has the role
    (another formation) the closest cell is named and marked ``closest``. It names no cause and no decision.
    """
    absent = [r for r in recent if r["player_status"] in ("bench", "not_listed")]
    if not absent:
        return None
    by_index = {r["_index"]: r for r in records}
    prior = [(matches[i], r["slot"]) for i, r in sorted(by_index.items()) if r["player_status"] == "started"]
    prior = prior[-BASELINE_STARTS:]
    usual = _mode(_role(slot) for _lu, slot in prior) if len(prior) >= MIN_BASELINE_STARTS else None
    if usual is None:
        reason = "too_few_starts" if len(prior) < MIN_BASELINE_STARTS else "no_single_usual_role"
        return {"status": "no_usual_slot", "reason": reason, "starts_used": len(prior), "matches_without": len(absent),
                "claim_status": OBSERVED}
    shared = {el for lu, slot in prior if _role(slot) == usual
              for el, row in lu.starters.items()
              if el != element and (_clean(row["detailed_position"]), _clean(row["side"])) == usual}
    depths = [d for d in (line_depth(slot.get("grid_slot"), slot.get("formation")) for _lu, slot in prior
                          if _role(slot) == usual) if d is not None]
    usual_depth = sum(depths) / len(depths) if depths else None
    counts: Counter[int] = Counter()
    closest_used = False
    covered = 0
    for rec in absent:
        lu = matches[rec["_index"]]
        pool = {el: row for el, row in lu.starters.items() if el != element and el not in shared}
        found = [el for el, row in pool.items() if (_clean(row["detailed_position"]), _clean(row["side"])) == usual]
        kind = "exact"
        if not found:
            kind = "closest"
            found = [el for el, row in pool.items() if _clean(row["detailed_position"]) == usual[0]]
            if not found and usual_depth is not None:
                near = sorted(
                    (abs(d - usual_depth), el) for el, row in pool.items()
                    if row.get("detailed_position") != "Goalkeeper"
                    and (d := line_depth(_clean(row["grid_slot"]), lu.formation)) is not None
                    and abs(d - usual_depth) < LINE_STEP_MIN)
                if near and (len(near) == 1 or near[0][0] < near[1][0]):
                    found = [near[0][1]]
        rec["slot_occupants"] = [{"player": _person(el, names), "match": kind, "formation": lu.formation,
                                  "claim_status": OBSERVED} for el in sorted(found)]
        if found:
            covered += 1
            closest_used = closest_used or kind == "closest"
            counts.update(found)
    return {
        "status": "ok", "usual_slot": _role_dict(usual), "starts_used": len(prior), "matches_without": len(absent),
        "matches_covered": covered, "closest_used": closest_used,
        "occupants": [{"player": _person(el, names), "count": n}
                      for el, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))],
        "small_sample": len(absent) < ABSENCE_MIN_EACH_SIDE, "claim_status": OBSERVED,
    }


def _line_shift(now: Mapping[str, Any], same_role_priors: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Same role as the earlier starts but another grid cell: is it another line of the formation?

    Grid rows are numbered per formation (``4-2-3-1`` and ``4-3-3`` put different players on row 4), so raw rows are
    compared only inside one formation. Across formations the cell is first turned into a depth between 0.0 (back
    line) and 1.0 (front line) with :func:`football_intelligence.grid.line_depth`, and a shift is claimed only when
    the depth moved by at least ``LINE_STEP_MIN``; a smaller difference is the same line seen through another shape.

    ``result`` is ``further_forward`` / ``deeper`` (a different line), ``column_only`` (same formation, same row,
    another column: not a change), ``same_line`` (different formations, no real depth change) or ``not_comparable``
    (formation unknown or cells unparseable, or fewer than ``MIN_BASELINE_STARTS`` earlier starts to compare with).
    ``basis`` says which rule decided: ``same_formation`` or ``normalised``.
    """
    formation = now.get("formation")
    same_formation = [s for s in same_role_priors if s.get("formation") == formation]
    now_row = grid_row(now.get("grid_slot"))
    if formation and now_row is not None and len(same_formation) >= MIN_BASELINE_STARTS:
        rows = [grid_row(s.get("grid_slot")) for s in same_formation]
        if all(r is not None for r in rows):
            base_row = _mode(rows)
            if base_row is not None:
                if now_row == base_row:
                    return {"result": "column_only", "basis": "same_formation"}
                return {"result": "further_forward" if now_row > base_row else "deeper", "basis": "same_formation"}
    depth_now = line_depth(now.get("grid_slot"), formation)
    depths = [line_depth(s.get("grid_slot"), s.get("formation")) for s in same_role_priors]
    depths = [d for d in depths if d is not None]
    if depth_now is None or len(depths) < MIN_BASELINE_STARTS:
        return {"result": "not_comparable", "basis": "normalised"}
    moved = depth_now - sum(depths) / len(depths)
    if abs(moved) < LINE_STEP_MIN:
        return {"result": "same_line", "basis": "normalised"}
    return {"result": "further_forward" if moved > 0 else "deeper", "basis": "normalised"}


def _associations(matches, index, lineup, fixtures, element, base_role, now_role, sidelined, names) -> list[dict[str, Any]]:
    """Regular teammates (started most of the previous matches) who are not in this match's starting XI."""
    prior = matches[max(0, index - REGULAR_WINDOW):index]
    if len(prior) < MIN_BASELINE_STARTS:
        return []
    starts: Counter[int] = Counter()
    roles: dict[int, list[tuple[Any, Any]]] = {}
    for lu in prior:
        for el, row in lu.starters.items():
            starts[el] += 1
            roles.setdefault(el, []).append((_clean(row["detailed_position"]), _clean(row["side"])))
    needed = max(MIN_BASELINE_STARTS, -(-len(prior) // 2))
    day = _to_date((fixtures[lineup.fixture_id].kickoff or "")[:10])
    found: list[dict[str, Any]] = []
    for mate, count in sorted(starts.items()):
        if mate == element or count < needed or mate in lineup.starters:
            continue
        entry: dict[str, Any] = {
            "teammate": _person(mate, names), "claim_status": ASSOCIATED,
            "relation": "not_in_starting_xi",
            "presence": "on_bench" if mate in lineup.bench else "not_listed",
            "may_be_unmapped": lineup.unresolved_starters and mate not in lineup.bench,
            "started_of_previous": [count, len(prior)],
            "listed_sidelined": _sidelined_on(sidelined, mate, day),
        }
        mate_role = _mode(roles[mate])
        entry["role_match"] = mate_role is not None and mate_role == now_role
        if mate_role is not None and mate_role == now_role and base_role is not None and base_role != now_role:
            entry["hypothesis"] = {"claim_status": HYPOTHESIS, "kind": "player_took_the_teammates_usual_position",
                                   "position": _role_dict(mate_role)}
        found.append(entry)
    # Most telling first: the provider listed him as out that day, then his usual role is the one the player took.
    found.sort(key=lambda e: (e["listed_sidelined"] is None, not e["role_match"], -e["started_of_previous"][0],
                              e["teammate"]["player_id"]))
    return found


def _absence_focus(matches, records, fixtures, absent, team, sidelined, names) -> dict[str, Any]:
    by_fixture = {m["_fixture_id"]: m for m in records}
    absent_games, present_games = [], []
    for lu in matches:
        meta = fixtures[lu.fixture_id]
        mine = by_fixture.get(lu.fixture_id)
        if mine is None or mine["player_status"] != "started":
            continue
        if absent in lu.starters:
            present_games.append(mine)
            continue
        day = _to_date((meta.kickoff or "")[:10])
        absent_games.append({**_public(mine), "teammate_presence": "on_bench" if absent in lu.bench else "not_listed",
                             "may_be_unmapped": lu.unresolved_starters and absent not in lu.bench,
                             "listed_sidelined": _sidelined_on(sidelined, absent, day), "claim_status": ASSOCIATED})
    role_absent = _mode(_role(m["slot"]) for m in absent_games)
    role_present = _mode(_role(m["slot"]) for m in present_games)
    return {
        "teammate": _person(absent, names),
        "matches_without_him_in_xi": absent_games,
        "matches_with_him_in_xi": [{"gameweek": m["gameweek"], "opponent": m["opponent"], "slot": m["slot"]} for m in present_games],
        "usual_role_without_him": _role_dict(role_absent) if role_absent else None,
        "usual_role_with_him": _role_dict(role_present) if role_present else None,
        "role_differs": (role_absent != role_present) if role_absent and role_present else None,
        "small_sample": len(absent_games) < ABSENCE_MIN_EACH_SIDE or len(present_games) < ABSENCE_MIN_EACH_SIDE,
        "min_each_side": ABSENCE_MIN_EACH_SIDE,
        "without_needed": max(0, ABSENCE_MIN_EACH_SIDE - len(absent_games)),
        "with_needed": max(0, ABSENCE_MIN_EACH_SIDE - len(present_games)),
        "claim_status": ASSOCIATED,
    }


def _public(record: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def _missing(reason: str, without_meta: int) -> dict[str, Any]:
    return {"status": "missing_context", "reason_codes": [reason], "matches": [], "evidence": [],
            "fixtures_without_metadata": without_meta}
