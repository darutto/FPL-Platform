"""Which fixture-outlook axis a player reads: his starting role, and for wide defenders what he does with the ball.

Leo, 2026-11-08 and 2026-11-10 ("puesto + lo que hace"). The player card's fixture strip and the /fixtures calendar
follow the same rule. Pure: frames and numbers in, an axis out.

1. Role vote, over the player's last ``RECENT_STARTS`` starts with a stored lineup (the window of the card's position
   signal). Each start's provider role counts for ``defence``, for ``attack``, or for neither (``ROLE_AXIS``). Fewer
   than ``MIN_STARTS`` starts: no answer. One axis in more than half of the starts: that axis. Otherwise no answer.

2. Wide defenders: an FPL DEF whose recent starts are mostly on a flank (``WIDE_ROLES``: Left/Right Back of a back
   four, Left/Right Midfield, which is how the provider labels the wing-back of a back three). For him the slot says
   little: a back-four full-back can live on assists, a back-three wing-back on clean sheets. So his PROFILE decides,
   not the cell: ``attack`` when his FPL expected goal involvements per 90 are in the top third of the defenders with
   at least ``PROFILE_MIN_MINUTES`` (``PROFILE_TOP_SHARE``), ``defence`` otherwise (he earns from clean sheets and
   defensive contributions). Under ``PROFILE_MIN_MINUTES`` himself his per-90 is noise, so he reads ``defence``.

"No answer" (``None``) means the caller keeps the FPL fallback: DEF/GKP defence, everyone else attack.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

import pandas as pd

from .position_changes import FixtureMeta, _lineups, _order_key, _slot

DEFENCE = "defence"
ATTACK = "attack"

#: Starts read, newest first, and the fewest that give an answer. Same window as the card's position signal.
RECENT_STARTS = 5
MIN_STARTS = 3

#: Provider ``detailed_position`` -> axis. Roles not listed (Central Midfield, unknown names) count for neither.
ROLE_AXIS: dict[str, str] = {
    "Goalkeeper": DEFENCE,
    "Centre Back": DEFENCE,
    "Left Back": DEFENCE,
    "Right Back": DEFENCE,
    "Defensive Midfield": DEFENCE,
    "Left Midfield": ATTACK,
    "Right Midfield": ATTACK,
    "Attacking Midfield": ATTACK,
    "Attacker": ATTACK,
    "Centre Forward": ATTACK,
}

#: Flank roles of a defender: full-backs of a back four and wing-backs of a back three (labelled as wide midfield).
WIDE_ROLES = frozenset({"Left Back", "Right Back", "Left Midfield", "Right Midfield"})

#: A defender's per-90 counts toward the profile pool only from this many minutes: five full matches, so one goal or
#: assist in a cameo does not put a centre-back at the top of the table.
PROFILE_MIN_MINUTES = 450
#: The attacking share of that pool: the top third by FPL xGI/90. A third is "clearly above the typical defender"
#: without needing a tuned cut-off; most back-three wing-backs who live on clean sheets stay below it.
PROFILE_TOP_SHARE = 1 / 3


def _recent(starts: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]] | None:
    recent = list(starts)[-RECENT_STARTS:]
    return recent if len(recent) >= MIN_STARTS else None


def axis_from_starts(starts: Iterable[Mapping[str, Any]]) -> str | None:
    """Step 1, the role vote: the axis from a player's started slots, oldest first, or None."""
    recent = _recent(starts)
    if recent is None:
        return None
    votes = [ROLE_AXIS.get(str(s.get("detailed_position"))) for s in recent]
    for axis in (DEFENCE, ATTACK):
        if votes.count(axis) * 2 > len(recent):
            return axis
    return None


def mostly_wide(starts: Iterable[Mapping[str, Any]]) -> bool:
    """More than half of the latest starts (at least ``MIN_STARTS``) on a flank (``WIDE_ROLES``)."""
    recent = _recent(starts)
    if recent is None:
        return False
    return sum(1 for s in recent if s.get("detailed_position") in WIDE_ROLES) * 2 > len(recent)


def profile_threshold(defenders: Iterable[tuple[float, float]]) -> float | None:
    """The xGI/90 a defender needs to be in the top ``PROFILE_TOP_SHARE`` of the pool.

    ``defenders`` is ``(minutes, xgi_per_90)`` for every FPL DEF; only those with ``PROFILE_MIN_MINUTES`` count.
    None when the pool is empty (season start): then no wide defender reads attack on his profile.
    """
    pool = sorted((x for minutes, x in defenders if minutes >= PROFILE_MIN_MINUTES), reverse=True)
    if not pool:
        return None
    return pool[max(1, math.ceil(len(pool) * PROFILE_TOP_SHARE)) - 1]


def profile_axis(minutes: float, xgi_per_90: float, threshold: float | None) -> str:
    """Step 2 for one wide defender: attack in the top third of the pool, defence otherwise."""
    if threshold is None or minutes < PROFILE_MIN_MINUTES or xgi_per_90 <= 0:
        return DEFENCE
    return ATTACK if xgi_per_90 >= threshold else DEFENCE


def decide_axis(
    observed: Mapping[str, Any] | None,
    *,
    fpl_position: str,
    minutes: float,
    xgi_per_90: float,
    threshold: float | None,
) -> str | None:
    """The whole rule for one player. ``observed`` is his entry of :func:`observed_by_element` (None: no lineups)."""
    if not observed:
        return None
    if fpl_position == "DEF" and observed.get("wide"):
        return profile_axis(minutes, xgi_per_90, threshold)
    return observed.get("axis")


def recent_starts_by_element(
    snapshots: pd.DataFrame,
    slots: pd.DataFrame,
    fixtures: Mapping[int, FixtureMeta],
    keep: int = RECENT_STARTS,
) -> dict[int, list[dict[str, Any]]]:
    """Every player's last ``keep`` started slots, oldest first, from one read of the lineup tables.

    Same lineup choice as :func:`football_intelligence.position_changes.analyse` (latest confirmed, else latest
    provisional) and the same kickoff order. Fixtures the FPL list does not know are skipped. Club moves do not
    matter here: a role is a role.
    """
    lineups = [lu for (fid, _team), lu in _lineups(snapshots, slots).items() if fid in fixtures]
    lineups.sort(key=lambda lu: _order_key(lu.fixture_id, fixtures))
    starts: dict[int, list[dict[str, Any]]] = {}
    for lu in lineups:
        for element, row in lu.starters.items():
            starts.setdefault(element, []).append(_slot(row, lu.formation))
    return {element: rows[-keep:] for element, rows in starts.items()}


def observed_by_element(
    snapshots: pd.DataFrame, slots: pd.DataFrame, fixtures: Mapping[int, FixtureMeta],
) -> dict[int, dict[str, Any]]:
    """FPL element id -> ``{"axis": role vote or None, "wide": mostly on a flank}`` for every player with enough
    starts. The FPL side of the rule (position, minutes, xGI/90) is applied per card by :func:`decide_axis`."""
    out: dict[int, dict[str, Any]] = {}
    for element, starts in recent_starts_by_element(snapshots, slots, fixtures).items():
        if _recent(starts) is None:
            continue
        out[element] = {"axis": axis_from_starts(starts), "wide": mostly_wide(starts)}
    return out
