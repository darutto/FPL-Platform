"""fpl_position_gap: a player's FPL position next to where the announced lineups put him. No network, no LLM."""
from __future__ import annotations

import pandas as pd
import pytest

from football_intelligence.ingestion.licensed.store import TABLES
from football_intelligence.position_changes import fpl_position_gap, played_line
from fpl_grounded_assistant.atomic_tool_cards import compose_position_changes_card
from fpl_grounded_assistant.catalogue import _CATALOGUE
from fpl_grounded_assistant.position_changes_tool import run_position_changes

CUYPER = 7


def _start(role, side="centre", formation="4-2-3-1"):
    return {"player_status": "started", "slot": {"detailed_position": role, "side": side, "formation": formation}}


def _gap(element_type, *starts):
    return fpl_position_gap(element_type, list(starts))


# --- the table ------------------------------------------------------------------

@pytest.mark.parametrize("role,line", [
    ("Goalkeeper", "GKP"), ("Centre Back", "DEF"), ("Left Back", "DEF"), ("Right Back", "DEF"),
    ("Defensive Midfield", "MID"), ("Central Midfield", "MID"), ("Attacking Midfield", "MID"),
    ("Left Midfield", "MID"), ("Right Midfield", "MID"), ("Attacker", "FWD"), ("Centre Forward", "FWD"),
])
def test_provider_roles_map_to_fpl_lines(role, line):
    assert played_line({"detailed_position": role, "formation": "4-4-2"}) == line


def test_unknown_role_maps_to_nothing():
    assert played_line({"detailed_position": "Libero"}) is None
    assert played_line({}) is None


# --- wing-backs ----------------------------------------------------------------

@pytest.mark.parametrize("formation", ["3-4-3", "3-5-2", "3-4-2-1"])
def test_three_at_the_back_makes_wide_midfielders_defenders(formation):
    assert played_line({"detailed_position": "Left Midfield", "formation": formation}) == "DEF"
    assert _gap(2, *[_start("Right Midfield", "right", formation)] * 4) is None


@pytest.mark.parametrize("formation", ["4-2-3-1", "5-3-2", "4-4-2", None])
def test_other_formations_keep_the_provider_label(formation):
    assert played_line({"detailed_position": "Left Midfield", "formation": formation}) == "MID"


def test_a_central_midfielder_is_not_a_wing_back_in_a_back_three():
    assert played_line({"detailed_position": "Central Midfield", "formation": "3-5-2"}) == "MID"


# --- the flag -------------------------------------------------------------------

def test_defender_playing_left_midfield_is_flagged():
    gap = _gap(2, *[_start("Left Midfield", "left")] * 6)
    assert gap == {"fpl_position": "DEF", "played_line": "MID", "starts": 6, "of": 6,
                   "direction": "further_forward", "side": "left", "claim_status": "observed"}


def test_midfielder_playing_up_front_is_flagged():
    gap = _gap(3, _start("Centre Forward"), _start("Attacker"), _start("Centre Forward"))
    assert (gap["played_line"], gap["direction"], gap["starts"], gap["of"]) == ("FWD", "further_forward", 3, 3)


def test_the_other_direction_is_flagged_without_judgement():
    gap = _gap(4, _start("Attacking Midfield"), _start("Attacking Midfield"), _start("Centre Forward"))
    assert (gap["fpl_position"], gap["played_line"], gap["direction"], gap["starts"], gap["of"]) == ("FWD", "MID", "deeper", 2, 3)


def test_no_flag_in_his_own_line():
    assert _gap(2, *[_start("Centre Back")] * 4) is None


def test_a_tie_flags_nothing():
    assert _gap(2, _start("Left Midfield"), _start("Left Midfield"), _start("Centre Back"), _start("Centre Back")) is None


def test_a_single_start_flags_nothing():
    assert _gap(2, _start("Left Midfield")) is None


def test_bench_and_unknown_roles_are_not_counted():
    bench = {"player_status": "bench", "slot": None}
    assert _gap(2, bench, bench, _start("Left Midfield"), _start("Left Midfield")) ["of"] == 2
    assert _gap(2, _start("Libero"), _start("Libero"), _start("Left Midfield")) is None


def test_goalkeepers_are_never_flagged_either_way():
    assert _gap(1, _start("Centre Back"), _start("Centre Back")) is None
    assert _gap(2, _start("Goalkeeper"), _start("Goalkeeper")) is None


def test_missing_element_type_flags_nothing():
    assert _gap(None, _start("Left Midfield"), _start("Left Midfield")) is None
    assert _gap(9, _start("Left Midfield"), _start("Left Midfield")) is None


# --- end to end over a synthetic store (the prod case) --------------------------

def _store(formation):
    snaps, slots = [], []
    for fid in range(1, 7):
        obs = f"2026-11-{fid + 1:02d}T10:00:00Z"
        snaps.append({"fixture_id": fid, "team": "BHA", "observed_at": obs, "state": "finished", "confirmed": True,
                      "formation": formation, "n_starters": 1, "n_bench": 0})
        slots.append({"fixture_id": fid, "team": "BHA", "observed_at": obs, "element": CUYPER, "starter": True,
                      "detailed_position": "Left Midfield", "grid_slot": "3:1", "side": "left"})
    frames = {"lineup_snapshots": snaps, "lineup_slots": slots, "sidelined": [],
              "squad_membership": [{"team": "BHA", "element": CUYPER, "jersey_number": 1, "observed_at": "2026-11-01T05:00:00Z"}]}
    return {n: pd.DataFrame(rows, columns=list(TABLES[n][0])).astype(object) for n, rows in frames.items()}


class _Handle:
    def __init__(self, tables):
        self._t = tables

    def manifest(self):
        return {"built_at": "2026-11-08T05:00:00Z"}

    def table(self, name):
        return self._t[name]


BOOTSTRAP = {"teams": [{"id": 1, "name": "Brighton", "short_name": "BHA"}, {"id": 2, "name": "Everton", "short_name": "EVE"}],
             "elements": [{"id": CUYPER, "web_name": "De Cuyper", "first_name": "Maxim", "second_name": "De Cuyper",
                           "team": 1, "element_type": 2, "status": "a"}]}
FIXTURES = [{"id": f, "event": f, "kickoff_time": f"2026-11-{f + 1:02d}T15:00:00Z", "team_h": 1, "team_a": 2} for f in range(1, 7)]


@pytest.fixture(autouse=True)
def _no_cached_fixture_list(monkeypatch):
    from fpl_grounded_assistant import position_changes_tool

    monkeypatch.setitem(position_changes_tool._fixture_cache, "rows", None)


def _run(formation="4-2-3-1", bootstrap=BOOTSTRAP):
    return run_position_changes({"player": "De Cuyper"}, dict(bootstrap), handle=_Handle(_store(formation)),
                                fetch_fixtures=lambda: FIXTURES)


def test_de_cuyper_case_in_a_four_back():
    out = _run()
    assert out["fpl_position"] == "DEF"
    assert out["fpl_position_gap"]["starts"] == 6 and out["fpl_position_gap"]["of"] == 6
    assert out["fpl_position_gap"]["played_line"] == "MID"


def test_the_same_slots_in_a_back_three_are_a_wing_back_not_a_gap():
    out = _run("3-4-3")
    assert out["fpl_position"] == "DEF" and "fpl_position_gap" not in out


def test_fpl_position_is_returned_even_without_a_gap():
    assert _run("3-4-3")["fpl_position"] == "DEF"


def _text(out, locale):
    from fpl_grounded_assistant.renderer import _render_get_position_changes
    return _render_get_position_changes(out, locale)


def test_text_spanish():
    text = _text(_run(), "es")
    assert "En FPL es defensa; ha empezado 6 de 6 como medio por la izquierda." in text


def test_text_english():
    text = _text(_run(), "en")
    assert "FPL lists him as a defender; he has started 6 of 6 as a midfielder on the left." in text


def test_text_has_no_gap_line_without_a_gap():
    assert "FPL" not in _text(_run("3-4-3"), "en").split("\n")[1]


@pytest.mark.parametrize("locale,pill", [("es", "FPL: DEF · juega MED"), ("en", "FPL: DEF · plays MID")])
def test_card_pill_is_first_and_short(locale, pill):
    card = compose_position_changes_card(_run(), locale)
    assert card.pills[0].label == pill and card.pills[0].tone == "neutral"


def test_card_has_no_gap_pill_without_a_gap():
    card = compose_position_changes_card(_run("3-4-3"), "en")
    assert not any(p.label.startswith("FPL:") for p in card.pills)


def test_catalogue_has_both_languages_for_the_new_keys():
    keys = [k for k in _CATALOGUE if ".position_changes." in k and ("gap" in k or "line_" in k or "side_" in k or "code_" in k)]
    assert len(keys) >= 12
    assert all(_CATALOGUE[k]["en"] and _CATALOGUE[k]["es"] for k in keys)
