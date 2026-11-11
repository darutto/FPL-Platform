"""Which fixture-outlook axis a player reads, from the role he was listed to start in (observed), not his FPL listing.

Leo, 2026-11-08: a defensive midfielder reads the defence axis, an attacking wing-back the attack axis. The player
card's fixture strip and the /fixtures calendar follow the same rule. Pure: frames in, dict out.

The rule, over the player's last ``RECENT_STARTS`` starts with a stored lineup (the window of the card's position
signal):

* each start's provider role counts for ``defence``, for ``attack``, or for neither (see ``ROLE_AXIS``);
* fewer than ``MIN_STARTS`` starts: no answer;
* one axis in more than half of the starts: that axis;
* otherwise no answer.

"No answer" (``None``) means the caller keeps the FPL fallback: DEF/GKP defence, everyone else attack.

Wide roles: the provider labels a wing-back of a back three as Left/Right Midfield, and a full-back of a back four
as Left/Right Back. So a wing-back pushed up into the midfield line reads attack, a full-back in the back line reads
defence, whatever his FPL listing.
"""
from __future__ import annotations

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


def axis_from_starts(starts: Iterable[Mapping[str, Any]]) -> str | None:
    """The axis from a player's started slots, oldest first (only the last ``RECENT_STARTS`` are read), or None."""
    recent = list(starts)[-RECENT_STARTS:]
    if len(recent) < MIN_STARTS:
        return None
    votes = [ROLE_AXIS.get(str(s.get("detailed_position"))) for s in recent]
    for axis in (DEFENCE, ATTACK):
        if votes.count(axis) * 2 > len(recent):
            return axis
    return None


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


def axes_by_element(
    snapshots: pd.DataFrame, slots: pd.DataFrame, fixtures: Mapping[int, FixtureMeta],
) -> dict[int, str]:
    """FPL element id -> observed axis, for every player who has one (the rest keep the FPL fallback)."""
    out: dict[int, str] = {}
    for element, starts in recent_starts_by_element(snapshots, slots, fixtures).items():
        axis = axis_from_starts(starts)
        if axis is not None:
            out[element] = axis
    return out
