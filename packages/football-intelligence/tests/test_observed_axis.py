"""The fixture strip's axis from the observed starting role. Synthetic slots and a synthetic store only."""
from __future__ import annotations

import pandas as pd
import pytest

from football_intelligence.ingestion.licensed.store import TABLES
from football_intelligence.observed_axis import (
    ATTACK, DEFENCE, MIN_STARTS, RECENT_STARTS, ROLE_AXIS, axes_by_element, axis_from_starts,
    recent_starts_by_element,
)
from football_intelligence.position_changes import FixtureMeta


def _starts(*roles: str, formation: str = "4-2-3-1") -> list[dict]:
    return [{"detailed_position": r, "side": None, "grid_slot": "3:1", "formation": formation} for r in roles]


def test_a_defensive_midfielder_reads_defence():
    assert axis_from_starts(_starts(*["Defensive Midfield"] * 4)) == DEFENCE


def test_a_wing_back_pushed_into_the_midfield_line_reads_attack():
    # The provider labels the wing-back of a back three as Left/Right Midfield.
    assert axis_from_starts(_starts("Left Midfield", "Left Midfield", "Left Midfield", formation="3-4-2-1")) == ATTACK


def test_a_full_back_in_the_back_line_reads_defence():
    assert axis_from_starts(_starts("Right Back", "Right Back", "Centre Back")) == DEFENCE


def test_forwards_and_attacking_midfielders_read_attack():
    assert axis_from_starts(_starts("Attacking Midfield", "Centre Forward", "Attacker")) == ATTACK


def test_too_few_starts_gives_no_answer_so_fpl_decides():
    assert MIN_STARTS == 3
    assert axis_from_starts(_starts("Defensive Midfield", "Defensive Midfield")) is None


def test_no_data_gives_no_answer_so_fpl_decides():
    assert axis_from_starts([]) is None


def test_no_majority_gives_no_answer():
    # Central Midfield counts for neither axis; two of four is not more than half.
    assert axis_from_starts(_starts("Defensive Midfield", "Defensive Midfield", "Central Midfield", "Central Midfield")) is None
    assert axis_from_starts(_starts("Defensive Midfield", "Attacking Midfield", "Central Midfield")) is None


def test_only_the_latest_starts_are_read():
    old = ["Centre Forward"] * 10
    assert axis_from_starts(_starts(*old, *["Defensive Midfield"] * RECENT_STARTS)) == DEFENCE


def test_unknown_role_names_count_for_neither():
    assert axis_from_starts(_starts("Sweeper Keeper Libero", "Unknown", "Defensive Midfield")) is None
    assert "Central Midfield" not in ROLE_AXIS


@pytest.mark.parametrize("role,axis", sorted(ROLE_AXIS.items()))
def test_every_mapped_role_decides_three_of_three(role, axis):
    assert axis_from_starts(_starts(role, role, role)) == axis


# ---- one read of the store for every player ---------------------------------------------------------------------

DM, WB, BENCHED = 1, 2, 3


def _store():
    snaps, slots, fixtures = [], [], {}
    for fid in range(1, 6):
        obs = f"2026-11-{fid:02d}T10:00:00Z"
        fixtures[fid] = FixtureMeta(fid, f"2026-11-{fid:02d}T15:00:00Z", "AAA", "BBB")
        snaps.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "state": "finished", "confirmed": True,
                      "formation": "3-4-2-1", "n_starters": 2, "n_bench": 1})
        slots.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "element": DM, "starter": True,
                      "detailed_position": "Defensive Midfield", "grid_slot": "3:2", "side": "centre"})
        slots.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "element": WB, "starter": True,
                      "detailed_position": "Left Midfield", "grid_slot": "3:4", "side": "left"})
        slots.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "element": BENCHED, "starter": fid <= 2,
                      "detailed_position": "Centre Back" if fid <= 2 else None, "grid_slot": None, "side": None})
    frame = lambda name, rows: pd.DataFrame(rows, columns=list(TABLES[name][0])).astype(object)  # noqa: E731
    return frame("lineup_snapshots", snaps), frame("lineup_slots", slots), fixtures


def test_the_index_answers_every_player_from_one_read():
    snaps, slots, fixtures = _store()
    assert axes_by_element(snaps, slots, fixtures) == {DM: DEFENCE, WB: ATTACK}  # two starts: BENCHED keeps FPL


def test_fixtures_the_fpl_list_does_not_know_are_skipped():
    snaps, slots, fixtures = _store()
    known = {fid: meta for fid, meta in fixtures.items() if fid <= 2}
    assert recent_starts_by_element(snaps, slots, known)[DM] == recent_starts_by_element(snaps, slots, fixtures)[DM][:2]
    assert axes_by_element(snaps, slots, known) == {}
