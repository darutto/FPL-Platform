"""B4 PR 2: starting-slot changes and who was missing. Synthetic store only: invented clubs' lineups, no provider data."""
from __future__ import annotations

import json

import pandas as pd

from football_intelligence.ingestion.licensed.store import TABLES
from football_intelligence.position_changes import (
    ASSOCIATED, HYPOTHESIS, OBSERVED, FixtureMeta, analyse,
)

ROGERS, PEDRO, MATE, COSTINHA = 10, 20, 30, 99
NAMES = {
    ROGERS: {"web_name": "Rogers", "team_short": "CHE"},
    PEDRO: {"web_name": "João Pedro", "team_short": "CHE"},
    MATE: {"web_name": "Mate", "team_short": "CHE"},
    COSTINHA: {"web_name": "Costinha", "team_short": "BHA"},
}
CF = ("Centre Forward", "centre")
RM = ("Right Midfield", "right")
AM = ("Attacking Midfield", "centre")


def _frame(table: str, rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(TABLES[table][0])).astype(object)


class Store:
    """Builds the four tables for one club (CHE) across fixtures 1..n, one observation each."""

    def __init__(self):
        self.snapshots: list[dict] = []
        self.slots: list[dict] = []
        self.sidelined: list[dict] = []
        self.squad: list[dict] = []
        self.fixtures: dict[int, FixtureMeta] = {}

    def match(self, fid, gw, day, *, rogers=RM, pedro=CF, pedro_where="starts", confirmed=True, n_starters=11,
              rogers_where="starts", team="CHE", extra=(), core=True, formation="4-2-3-1", rogers_slot=None):
        self.fixtures[fid] = FixtureMeta(gw, f"2026-11-{day:02d}T15:00:00Z", team if gw % 2 else "EVE", "EVE" if gw % 2 else team)
        obs = f"2026-11-{day:02d}T10:00:00Z"
        self.snapshots.append({"fixture_id": fid, "team": team, "observed_at": obs, "state": "scheduled",
                               "confirmed": confirmed, "formation": formation, "n_starters": n_starters, "n_bench": 7})

        def put(el, where, role, slot):
            if where == "starts":
                self.slots.append({"fixture_id": fid, "team": team, "observed_at": obs, "element": el, "starter": True,
                                   "detailed_position": role[0], "grid_slot": slot, "side": role[1]})
            elif where == "bench":
                self.slots.append({"fixture_id": fid, "team": team, "observed_at": obs, "element": el, "starter": False,
                                   "detailed_position": None, "grid_slot": None, "side": None})

        if core:
            put(ROGERS, rogers_where, rogers, rogers_slot or ("3:3" if rogers == RM else "3:2"))
            put(PEDRO, pedro_where, pedro, "4:1" if pedro == CF else "3:2")
        for el in extra:
            put(el, "starts", ("Left Back", "left"), "2:1")

    def build(self, element=ROGERS, **kw):
        for el in (ROGERS, PEDRO):
            self.squad.append({"team": "CHE", "element": el, "jersey_number": 1, "observed_at": "2026-11-01T05:00:00Z"})
        return analyse(
            element=element, snapshots=_frame("lineup_snapshots", self.snapshots), slots=_frame("lineup_slots", self.slots),
            sidelined=_frame("sidelined", self.sidelined), squad_membership=_frame("squad_membership", self.squad),
            fixtures=self.fixtures, names=NAMES, **kw)


def _six_matches_with_pedro_out_in_the_fourth(**kw):
    store = Store()
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16), (4, 23), (5, 30), (6, 31)], start=1):
        out = fid == 4
        store.match(fid, gw, day, rogers=AM if out else RM, pedro_where="not_listed" if out else "starts", **kw)
    return store


def test_it_reports_the_slot_each_match_and_a_change_against_the_players_own_starts():
    result = _six_matches_with_pedro_out_in_the_fourth().build()
    assert result["status"] == "ok" and result["player"]["web_name"] == "Rogers"
    by_gw = {m["gameweek"]: m for m in result["matches"]}
    assert by_gw[1]["slot"]["detailed_position"] == "Right Midfield" and by_gw[1]["change"] is None
    assert by_gw[3]["change"] is None  # same role as his earlier starts
    change = by_gw[4]["change"]
    assert change["kind"] == "position" and change["claim_status"] == OBSERVED
    assert change["from"] == {"detailed_position": "Right Midfield", "side": "right"}
    assert change["to"]["detailed_position"] == "Attacking Midfield" and change["baseline_starts"] == 3
    assert by_gw[5]["change"] is None  # back in Right Midfield, the mode of his earlier starts


def test_no_change_is_claimed_without_enough_prior_starts():
    store = Store()
    store.match(1, 1, 2, rogers=RM)
    store.match(2, 2, 9, rogers=AM)  # only one earlier start: not enough to call it a change
    assert all(m["change"] is None for m in store.build()["matches"])


def test_the_missing_teammate_is_associated_not_blamed():
    result = _six_matches_with_pedro_out_in_the_fourth().build()
    fourth = next(m for m in result["matches"] if m["gameweek"] == 4)
    (assoc,) = fourth["associations"]
    assert assoc["teammate"]["web_name"] == "João Pedro" and assoc["teammate"]["team_short"] == "CHE"
    assert assoc["claim_status"] == ASSOCIATED and assoc["relation"] == "not_in_starting_xi"
    assert assoc["presence"] == "not_listed" and assoc["listed_sidelined"] is None
    assert assoc["started_of_previous"] == [3, 3]
    assert "hypothesis" not in assoc  # Pedro's usual position (centre forward) is not the one Rogers took


def test_a_bench_teammate_is_distinguished_from_one_not_listed_and_sidelined_is_reported_apart():
    store = Store()
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16), (4, 23)], start=1):
        store.match(fid, gw, day, rogers=AM if fid == 4 else RM, pedro_where="bench" if fid == 4 else "starts")
    store.sidelined.append({"element": PEDRO, "team": "CHE", "category": "injury", "start_date": "2026-11-20",
                            "end_date": None, "games_missed": 1, "completed": False, "observed_at": "2026-11-21T05:00:00Z"})
    (assoc,) = next(m for m in store.build()["matches"] if m["gameweek"] == 4)["associations"]
    assert assoc["presence"] == "on_bench"  # absent from the XI is not the same as not being there
    assert assoc["listed_sidelined"] == {"category": "injury", "since": "2026-11-20", "ended": None}


def test_a_closed_sidelined_record_before_the_match_does_not_count():
    store = _six_matches_with_pedro_out_in_the_fourth()
    store.sidelined.append({"element": PEDRO, "team": "CHE", "category": "injury", "start_date": "2026-10-01",
                            "end_date": "2026-10-20", "games_missed": 2, "completed": True, "observed_at": "2026-10-21T05:00:00Z"})
    fourth = next(m for m in store.build()["matches"] if m["gameweek"] == 4)
    assert fourth["associations"][0]["listed_sidelined"] is None


def test_a_hypothesis_appears_only_when_the_player_took_the_absent_teammates_usual_position():
    store = Store()
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16), (4, 23)], start=1):
        # Pedro usually plays the attacking-midfield role; in the fourth he is out and Rogers plays it.
        store.match(fid, gw, day, rogers=AM if fid == 4 else RM, pedro=AM, pedro_where="not_listed" if fid == 4 else "starts")
    (assoc,) = next(m for m in store.build()["matches"] if m["gameweek"] == 4)["associations"]
    assert assoc["hypothesis"]["claim_status"] == HYPOTHESIS
    assert assoc["hypothesis"]["kind"] == "player_took_the_teammates_usual_position"


def test_a_starter_the_store_could_not_map_is_flagged_instead_of_called_absent():
    store = Store()
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16), (4, 23)], start=1):
        store.match(fid, gw, day, rogers=AM if fid == 4 else RM, pedro_where="not_listed" if fid == 4 else "starts",
                    n_starters=11)  # the announced XI had 11 starters but only a few resolved to FPL elements
    (assoc,) = next(m for m in store.build()["matches"] if m["gameweek"] == 4)["associations"]
    assert assoc["may_be_unmapped"] is True


def test_the_confirmed_lineup_wins_over_the_provisional_one_of_the_same_match():
    store = Store()
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16)], start=1):
        store.match(fid, gw, day)
    # a later provisional observation of match 3 says Rogers is on the bench; the earlier confirmed one stands
    store.snapshots.append({"fixture_id": 3, "team": "CHE", "observed_at": "2026-11-16T12:00:00Z", "state": "scheduled",
                            "confirmed": False, "formation": "4-2-3-1", "n_starters": 11, "n_bench": 7})
    store.slots.append({"fixture_id": 3, "team": "CHE", "observed_at": "2026-11-16T12:00:00Z", "element": ROGERS,
                        "starter": False, "detailed_position": None, "grid_slot": None, "side": None})
    third = next(m for m in store.build()["matches"] if m["gameweek"] == 3)
    assert third["player_status"] == "started" and third["lineup_status"] == "confirmed"


def test_a_provisional_lineup_is_labelled_provisional():
    store = Store()
    store.match(1, 1, 2, confirmed=False)
    assert store.build()["matches"][0]["lineup_status"] == "provisional"


def test_absence_focus_splits_the_players_slots_by_whether_the_teammate_started():
    store = Store()
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16), (4, 23), (5, 30), (6, 31)], start=1):
        out = fid in (3, 4, 5)
        store.match(fid, gw, day, rogers=AM if out else RM, pedro_where="not_listed" if out else "starts")
    focus = store.build(absent_element=PEDRO)["absence_focus"]
    assert focus["teammate"]["web_name"] == "João Pedro" and focus["claim_status"] == ASSOCIATED
    assert [m["gameweek"] for m in focus["matches_without_him_in_xi"]] == [3, 4, 5]
    assert [m["gameweek"] for m in focus["matches_with_him_in_xi"]] == [1, 2, 6]
    assert focus["usual_role_without_him"]["detailed_position"] == "Attacking Midfield"
    assert focus["usual_role_with_him"]["detailed_position"] == "Right Midfield"
    assert focus["role_differs"] is True and focus["small_sample"] is False


def test_a_short_history_says_the_sample_is_small():
    store = Store()
    store.match(1, 1, 2)
    store.match(2, 2, 9)
    result = store.build()
    assert result["sample"]["small_sample"] is True and result["sample"]["matches_with_stored_lineup"] == 2


def test_identity_is_by_element_id_never_by_name():
    # Costinha (another club, another element) shares a first name with João Pedro; he is never confused with him.
    store = Store()
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16), (4, 23)], start=1):
        store.match(fid, gw, day, rogers=AM if fid == 4 else RM, pedro_where="not_listed" if fid == 4 else "starts")
        store.match(100 + fid, gw, day, team="BHA", extra=(COSTINHA,), core=False)
    result = store.build()
    teammates = {a["teammate"]["web_name"] for m in result["matches"] for a in m["associations"]}
    assert teammates == {"João Pedro"}
    # and asking about Costinha reads his own club's matches only
    costinha = store.build(element=COSTINHA)
    assert costinha["player"]["team_short"] == "BHA" and all(m["player_status"] == "started" for m in costinha["matches"])


def test_a_player_with_no_stored_lineups_is_missing_context_not_an_empty_success():
    store = Store()
    store.match(1, 1, 2)
    result = store.build(element=7777)
    assert result["status"] == "missing_context" and result["reason_codes"] == ["player_not_in_licensed_store"]


def test_the_output_names_no_provider_ids_and_no_forbidden_causal_words():
    text = json.dumps(_six_matches_with_pedro_out_in_the_fourth().build(absent_element=PEDRO)).casefold()
    for forbidden in ("sportmonks", "provider", "crosswalk", "because", "due to", "injured", "moved during", "will perform"):
        assert forbidden not in text


# ---- same role, another cell of the grid: line, column, or not comparable (B4 refinement) --------------------------

import pytest  # noqa: E402

from football_intelligence.grid import line_depth  # noqa: E402


def _rogers_run(cells):
    """Rogers as an attacking midfielder in every match; ``cells`` is [(formation, grid_slot)] oldest first."""
    store = Store()
    for fid, (formation, slot) in enumerate(cells, start=1):
        store.match(fid, fid, fid + 1, rogers=AM, rogers_slot=slot, formation=formation)
    return store.build()["matches"][-1]


@pytest.mark.parametrize("formation, back, front", [
    ("4-2-3-1", "2:1", "5:1"), ("4-3-3", "2:1", "4:1"), ("4-4-2", "2:1", "4:1"), ("3-4-2-1", "2:1", "5:1"),
    ("3-5-2", "2:1", "4:1"), ("5-3-2", "2:1", "4:1"), ("4-1-4-1", "2:1", "5:1"),
])
def test_depth_runs_from_the_back_line_to_the_front_line_in_every_common_formation(formation, back, front):
    assert line_depth(back, formation) == 0.0 and line_depth(front, formation) == 1.0
    assert line_depth("1:1", formation) is None  # the goalkeeper has no line


def test_depth_is_not_the_raw_row_across_formations():
    assert line_depth("4:2", "4-2-3-1") == pytest.approx(2 / 3)  # third of four lines
    assert line_depth("4:2", "4-3-3") == 1.0  # same raw row, the front line of three
    assert line_depth("3:2", "4-4-2") == line_depth("3:2", "3-5-2") == 0.5
    assert line_depth("6:1", "4-2-3-1") is None and line_depth("3:2", None) is None and line_depth("3:2", "4-x-3") is None


def test_the_same_role_on_a_deeper_row_of_the_same_formation_is_a_line_change_not_a_role_change():
    last = _rogers_run([("4-2-3-1", "4:2")] * 3 + [("4-2-3-1", "3:2")])
    assert last["change"]["kind"] == "line" and last["change"]["direction"] == "deeper"
    assert last["change"]["basis"] == "same_formation" and last["change"]["claim_status"] == OBSERVED
    assert last["change"]["from"] == last["change"]["to"] == {"detailed_position": "Attacking Midfield", "side": "centre"}
    forward = _rogers_run([("4-2-3-1", "3:2")] * 3 + [("4-2-3-1", "4:2")])
    assert forward["change"]["direction"] == "further_forward"


def test_the_same_role_and_row_in_another_column_is_not_counted_as_a_change():
    last = _rogers_run([("4-2-3-1", "4:2")] * 3 + [("4-2-3-1", "4:3")])
    assert last["change"] is None and last["column_shift"] is True and last["associations"] == []


def test_the_gw6_rogers_case_a_new_grid_cell_with_the_same_attacking_midfield_role_is_no_slot_change():
    # five earlier starts as Attacking Midfield in 4-2-3-1, then the same role on the next cell of the same row
    last = _rogers_run([("4-2-3-1", "4:2")] * 5 + [("4-2-3-1", "4:1")])
    assert last["slot"]["detailed_position"] == "Attacking Midfield"
    assert last["change"] is None and last["column_shift"] is True


def test_across_formations_the_depth_is_normalised_before_comparing():
    # 4-2-3-1 row 4 is depth 0.67; the same role on row 3 of a 4-4-2 is depth 0.5: less than a line, so no claim
    last = _rogers_run([("4-2-3-1", "4:2")] * 3 + [("4-4-2", "3:2")])
    assert last["change"] is None and "column_shift" not in last and "line_comparable" not in last
    # row 4 of a 4-2-3-1 (0.67) against row 3 of a 4-3-3 (0.5): still the same line; row 4 of a 4-3-3 (1.0) is further forward
    assert _rogers_run([("4-2-3-1", "4:2")] * 3 + [("4-3-3", "3:2")])["change"] is None
    forward = _rogers_run([("4-2-3-1", "3:2")] * 3 + [("4-3-3", "4:2")])
    assert forward["change"]["direction"] == "further_forward" and forward["change"]["basis"] == "normalised"
    deeper = _rogers_run([("4-3-3", "4:2")] * 3 + [("5-3-2", "2:2")])
    assert deeper["change"]["direction"] == "deeper"


def test_the_line_is_reported_not_comparable_when_the_formation_is_unknown_or_the_history_too_short():
    unknown = _rogers_run([("4-2-3-1", "4:2")] * 3 + [(None, "3:2")])
    assert unknown["change"] is None and unknown["line_comparable"] is False
    mixed = _rogers_run([("4-2-3-1", "4:2"), ("4-2-3-1", "4:2"), ("4-3-3", "3:2")])  # one earlier start per formation
    assert mixed["change"] is None and "line_comparable" not in mixed  # 3 matches: the last has 2 priors, 0 same formation
