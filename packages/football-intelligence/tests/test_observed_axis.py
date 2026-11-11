"""The fixture strip's axis from the observed starting role. Synthetic slots and a synthetic store only."""
from __future__ import annotations

import pandas as pd
import pytest

from football_intelligence.ingestion.licensed.store import TABLES
from football_intelligence.observed_axis import (
    ATTACK, DEFENCE, MIN_STARTS, PROFILE_MIN_MINUTES, RECENT_STARTS, ROLE_AXIS, axis_from_starts, decide_axis,
    mostly_wide, observed_by_element, profile_threshold, recent_starts_by_element, xa_per_90,
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


# ---- step 2: wide defenders read their profile ---------------------------------------------------------------------

#: Synthetic defender pool: (minutes, xA/90). Six with enough minutes; the top third is the best two.
POOL = [(900, 0.40), (900, 0.30), (900, 0.20), (900, 0.10), (900, 0.05), (900, 0.00), (200, 0.90)]


def _decide(starts, *, fpl="DEF", minutes=900, xa=0.0, pool=POOL):
    observed = {"axis": axis_from_starts(starts), "wide": mostly_wide(starts)} if len(starts) >= MIN_STARTS else None
    return decide_axis(observed, fpl_position=fpl, minutes=minutes, xa_per_90=xa, threshold=profile_threshold(pool))


def test_the_profile_pool_is_the_top_third_of_defenders_with_enough_minutes():
    # The 200-minute cameo is left out of the pool even with the best number.
    assert profile_threshold(POOL) == 0.30
    assert profile_threshold([(100, 1.0)]) is None
    assert PROFILE_MIN_MINUTES == 450


def test_our_own_per_90_separates_what_fpl_rounding_ties():
    # Two synthetic wide defenders, both "0.07" in FPL's two-decimal per-90, on either side of a 0.07 cut.
    above, below = xa_per_90(0.72, 900), xa_per_90(0.62, 900)  # 0.072 and 0.062: FPL shows 0.07 and 0.06
    tie_a, tie_b = xa_per_90(0.70, 900), xa_per_90(0.66, 900)  # 0.070 and 0.066: FPL shows both as 0.07
    assert round(tie_a, 2) == round(tie_b, 2) == 0.07
    pool = [(900, 0.090), (900, 0.080), (900, tie_a), (900, 0.050), (900, 0.040), (900, 0.030),
            (900, 0.020), (900, 0.010), (900, 0.000)]
    assert profile_threshold(pool) == tie_a  # the third-best of nine: a tie with the cut is in
    wide = _starts(*["Left Back"] * 4)
    assert _decide(wide, xa=tie_a, pool=pool) == ATTACK
    assert _decide(wide, xa=tie_b, pool=pool) == DEFENCE
    assert _decide(wide, xa=above, pool=pool) == ATTACK and _decide(wide, xa=below, pool=pool) == DEFENCE


def test_per_90_without_minutes_is_zero():
    assert xa_per_90(1.5, 0) == 0.0


def test_an_attacking_back_four_full_back_reads_attack():
    assert _decide(_starts("Right Back", "Right Back", "Right Back", "Right Back"), xa=0.35) == ATTACK


def test_a_conservative_back_three_wing_back_reads_defence():
    assert _decide(_starts(*["Left Midfield"] * 4, formation="3-4-2-1"), xa=0.05) == DEFENCE


def test_a_wide_defender_under_the_minutes_floor_reads_defence():
    assert _decide(_starts(*["Left Back"] * 3), minutes=PROFILE_MIN_MINUTES - 1, xa=0.9) == DEFENCE


def test_with_an_empty_pool_no_wide_defender_reads_attack():
    assert _decide(_starts(*["Left Back"] * 3), xa=0.9, pool=[]) == DEFENCE


def test_centre_backs_and_non_defenders_keep_the_role_vote():
    assert _decide(_starts(*["Centre Back"] * 4), xa=0.9) == DEFENCE  # not wide: the profile is not read
    assert _decide(_starts(*["Right Midfield"] * 4), fpl="MID", xa=0.0) == ATTACK  # a winger, not a defender
    assert _decide(_starts(*["Defensive Midfield"] * 4), fpl="MID") == DEFENCE


def test_wide_needs_a_majority_of_flank_starts_and_the_minimum():
    assert mostly_wide(_starts("Left Back", "Left Midfield", "Centre Back"))
    assert not mostly_wide(_starts("Left Back", "Centre Back", "Centre Back"))
    assert not mostly_wide(_starts("Left Back", "Left Back"))


def test_too_few_starts_still_leaves_the_fpl_fallback_for_defenders():
    assert _decide(_starts("Left Back", "Left Back"), xa=0.9) is None


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
    # Two starts only: BENCHED is left out and keeps the FPL fallback.
    assert observed_by_element(snaps, slots, fixtures) == {
        DM: {"axis": DEFENCE, "wide": False}, WB: {"axis": ATTACK, "wide": True}}


def test_fixtures_the_fpl_list_does_not_know_are_skipped():
    snaps, slots, fixtures = _store()
    known = {fid: meta for fid, meta in fixtures.items() if fid <= 2}
    assert recent_starts_by_element(snaps, slots, known)[DM] == recent_starts_by_element(snaps, slots, fixtures)[DM][:2]
    assert observed_by_element(snaps, slots, known) == {}
