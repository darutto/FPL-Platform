"""Query layer PR 8 (pure part): tapped pills and typed corrections of the last validated spec."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.query_spec import QuerySpecError, parse_spec
from fpl_grounded_assistant.query_taps import (EDITABLE, PARTS, alternatives, apply_stated, apply_tap,
                                               changed_parts)


def pred(name, value):
    return {"pred": name, "value": value}


def flt(field, op, value):
    return {"field": field, "op": op, "value": value}


LEO = parse_spec({"metric": "total_points", "match_set": [pred("last_n", 5)],
                  "filters": [flt("owned_now", "lt", 10)]})
RATE = parse_spec({"metric": "goals_scored", "operator": "per_90",
                   "match_set": [pred("since_date", "2026-10-10")],
                   "filters": [flt("position", "eq", "FWD"), flt("price", "le", 7)]})
PERIODS = parse_spec({"metric": "team_goals", "shape": "comparison", "filters": [flt("club", "eq", "Club T")],
                      "match_set": [pred("gw_range", [1, 5])], "compare_to": [pred("gw_range", [6, 10])]})
PRESENCE = parse_spec({"metric": "team_expected_goals", "shape": "comparison",
                       "match_set": [pred("player_played_60", "Player A")],
                       "compare_to": [pred("player_absent", "Player A")]})


def selected(spec, part, floor=0):
    return [a.value for a in alternatives(spec, floor)[part] if a.selected]


# ------------------------------------------------------------------------------------------------- the pills

def test_a_player_list_opens_window_ownership_price_and_position():
    pills = alternatives(LEO)
    assert list(pills) == ["window", "ownership", "price", "position"]
    assert [a.value for a in pills["window"]] == [pred("last_n", 3), pred("last_n", 5), pred("last_n", 10),
                                                  pred("season", True)]
    assert [a.value for a in pills["position"]] == ["GKP", "DEF", "MID", "FWD", None]
    assert selected(LEO, "window") == [pred("last_n", 5)]
    assert selected(LEO, "ownership") == [{"op": "lt", "value": 10}]
    assert selected(LEO, "price") == selected(LEO, "position") == [None]


def test_a_value_that_is_not_offered_selects_nothing():
    odd = parse_spec({"metric": "total_points", "filters": [flt("owned_now", "le", 8)]})
    assert selected(odd, "ownership") == []


def test_minutes_options_start_above_the_floor_applied():
    assert "minutes" not in alternatives(LEO, 0)
    assert [a.value for a in alternatives(RATE, 270)["minutes"]] == [
        {"op": "ge", "value": 450}, {"op": "ge", "value": 900}, None]


@pytest.mark.parametrize("spec,pills", [
    (parse_spec({"metric": "team_goals"}), ["window"]),
    (PRESENCE, ["window"]),
    (PERIODS, []),                                          # two periods: there is no one window to change
    (parse_spec({"metric": "now_cost"}), ["ownership", "price", "position"]),
])
def test_pills_that_cannot_apply_do_not_open(spec, pills):
    assert list(alternatives(spec)) == pills


@pytest.mark.parametrize("spec,floor", [(LEO, 0), (RATE, 225), (PRESENCE, 0),
                                        (parse_spec({"metric": "team_goals"}), 0)])
def test_every_offered_option_applies_and_changes_only_its_part(spec, floor):
    for part, options in alternatives(spec, floor).items():
        assert part in EDITABLE
        for option in options:
            new = apply_tap(spec, part, option.value)
            assert changed_parts(spec, new) == (() if option.selected else (part,)), (part, option.value)
            assert part not in ("window",) or selected(new, part) == [option.value]


# -------------------------------------------------------------------------------------------------- a tap

def test_a_window_tap_keeps_the_other_conditions_and_moves_both_sides():
    new = apply_tap(PRESENCE, "window", pred("last_n", 10))
    for side in (new.match_set, new.compare_to):
        assert [p.pred for p in side] == ["last_n", side[1].pred]
    assert (new.match_set[1].pred, new.compare_to[1].pred) == ("player_played_60", "player_absent")


@pytest.mark.parametrize("spec,part,value", [
    (LEO, "metric", "goals_scored"),
    (LEO, "club", "Club T"),
    (LEO, "window", pred("venue", "home")),
    (LEO, "window", {"pred": "last_n", "value": 5, "quote": "x"}),
    (LEO, "window", pred("last_n", 5.0)),
    (LEO, "position", "WINGER"),
    (LEO, "price", 7),
    (LEO, "ownership", {"op": "lt", "value": 101}),
    (PERIODS, "window", pred("last_n", 5)),
    (parse_spec({"metric": "team_goals"}), "position", "MID"),
    (parse_spec({"metric": "form"}), "window", pred("last_n", 5)),
])
def test_a_tap_that_cannot_apply_is_refused(spec, part, value):
    with pytest.raises(QuerySpecError):
        apply_tap(spec, part, value)


# ---------------------------------------------------------------------------------------- a typed follow-up

def test_no_from_gw6_changes_only_the_window():
    new = apply_stated(LEO, {"match_set": [pred("gw_range", [6, 11])]})
    assert changed_parts(LEO, new) == ("window",)
    assert new.filters == LEO.filters and new.metric == LEO.metric


@pytest.mark.parametrize("part,value,stated,cleared", [
    ("window", pred("last_n", 10), {"match_set": [pred("last_n", 10)]}, ()),
    ("window", pred("season", True), {"match_set": [pred("season", True)]}, ()),
    ("ownership", {"op": "lt", "value": 5}, {"filters": [flt("owned_now", "lt", 5)]}, ()),
    ("ownership", None, {}, ("ownership",)),
    ("price", {"op": "le", "value": 6.0}, {"filters": [flt("price", "le", 6)]}, ()),
    ("position", "MID", {"filters": [flt("position", "eq", "MID")]}, ()),
    ("position", None, {}, ("position",)),
])
def test_a_tap_and_the_same_stated_change_give_the_same_spec(part, value, stated, cleared):
    assert apply_tap(LEO, part, value) == apply_stated(LEO, stated, cleared)


def test_a_new_metric_keeps_the_rate_and_everything_else():
    new = apply_stated(RATE, {"metric": "assists"})
    assert (new.metric, new.operator, new.order) == ("assists", "per_90", "desc")
    assert changed_parts(RATE, new) == ("metric",)


def test_a_new_metric_drops_the_old_second_metric():
    minus = parse_spec({"metric": "goals_scored", "operator": "minus", "metric_minus": "expected_goals"})
    new = apply_stated(minus, {"metric": "assists"})
    assert (new.operator, new.second_metric) == ("sum", None)


def test_a_new_metric_takes_its_own_natural_order():
    takers = apply_stated(LEO, {"metric": "penalties_order"})
    assert takers.order == "asc"
    assert apply_stated(takers, {"metric": "goals_scored"}).order == "desc"


def test_a_stated_direction_is_inherited_by_a_new_metric():
    fewest = apply_stated(LEO, {"order": "asc"})
    assert apply_stated(fewest, {"metric": "goals_scored"}).order == "asc"


def test_a_second_correction_builds_on_the_first():
    once = apply_stated(LEO, {"filters": [flt("position", "eq", "MID")]})
    twice = apply_stated(once, {"match_set": [pred("last_n", 3)]})
    assert changed_parts(LEO, twice) == ("window", "position")


def test_team_grain_reads_player_ids_as_team_ids():
    home = parse_spec({"metric": "team_goals_conceded", "order": "asc", "match_set": [pred("venue", "home")]})
    new = apply_stated(home, {"metric": "goals_scored", "match_set": [pred("venue", "away")]})
    assert new.metric == "team_goals" and [p.value for p in new.match_set] == ["away"]


@pytest.mark.parametrize("spec,stated,cleared", [
    (LEO, {"grain": "team"}, ()),
    (LEO, {"shape": "comparison"}, ()),
    (LEO, {"metric": "corners_taken"}, ()),
    (LEO, {"match_set": {"pred": "gw", "value": 3}}, ()),
    (LEO, {"filters": [{"op": "eq"}]}, ()),
    (LEO, {}, ("metric",)),
    (PERIODS, {"match_set": [pred("last_n", 5)]}, ()),
    (PRESENCE, {"match_set": [pred("player_absent", "Player B")]}, ()),
])
def test_what_is_not_a_correction_is_refused(spec, stated, cleared):
    with pytest.raises(QuerySpecError):
        apply_stated(spec, stated, cleared)


def test_nothing_stated_changes_nothing():
    for spec in (LEO, RATE, PERIODS, PRESENCE):
        assert apply_stated(spec, {}) == spec


def test_changed_parts_are_the_declared_enum():
    other = apply_stated(RATE, {"metric": "assists", "top_n": 5, "match_set": [pred("last_n", 3)],
                                "filters": [flt("club", "eq", "Club T"), flt("set_piece", "eq", "corners"),
                                            flt("minutes_in_window", "ge", 450), flt("owned_now", "lt", 5)]},
                         ("price", "position"))
    assert changed_parts(RATE, other) == ("metric", "window", "ownership", "price", "position", "club",
                                          "set_piece", "minutes", "top_n")
    assert set(changed_parts(RATE, other)) <= set(PARTS)
