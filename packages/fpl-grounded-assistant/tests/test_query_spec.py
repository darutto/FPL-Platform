"""Query layer PR 1: strict parse, declared defaults and catalogue coverage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_spec import Filter, Predicate, QuerySpecError, parse_spec, unsupported_reasons

VOCAB_PATH = Path(__file__).parent / "fixtures" / "query_vocabulary_round4.json"
VOCAB = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
#: The round-4 freeze's hash of vocabulary.json: the fixture is that file, not an edited copy.
FROZEN_VOCAB_SHA256_16 = "3d16ce5739272bc9"
ALL_IDS = VOCAB["additive"] + VOCAB["snapshot_season_only"] + VOCAB["team"]
SET_PIECE_ORDERS = ("penalties_order", "direct_freekicks_order", "corners_and_indirect_freekicks_order")


def spec(**kw):
    return {"metric": "total_points", **kw}


def team(**kw):
    return {"metric": "team_expected_goals", **kw}


def preds(*pairs):
    return [{"pred": p, "value": v} for p, v in pairs]


def flt(field, op, value):
    return [{"field": field, "op": op, "value": value}]


# ------------------------------------------------------------------------------------------------- catalogue

def test_fixture_is_the_frozen_vocabulary():
    data = VOCAB_PATH.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest()[:16] == FROZEN_VOCAB_SHA256_16


def test_every_vocabulary_id_has_a_row_in_vocabulary_order():
    assert list(cat.METRICS) == ALL_IDS
    assert [len(cat.metric_ids(g)) for g in ("additive", "snapshot", "team")] == [27, 9, 5]
    for group, key in (("additive", "additive"), ("snapshot", "snapshot_season_only"), ("team", "team")):
        assert list(cat.metric_ids(group)) == VOCAB[key]


def test_vocabulary_lists_match_the_freeze():
    assert list(cat.SHAPES) == VOCAB["shapes"]
    assert list(cat.GRAINS) == VOCAB["grains"]
    assert list(cat.OPERATORS) == VOCAB["operators"]
    assert list(cat.OPS) == VOCAB["ops"]
    assert list(cat.PREDICATES) == list(VOCAB["match_set_preds"])
    assert list(cat.FILTER_FIELDS) == list(VOCAB["filters"])
    assert list(cat.UNSUPPORTED_KINDS) == VOCAB["unsupported_kinds"]
    assert dict(cat.METRIC_PHRASES) == VOCAB["metric_phrases"]


@pytest.mark.parametrize("metric", ALL_IDS)
def test_row_is_complete_in_both_languages(metric):
    row = cat.METRICS[metric]
    assert row.field and row.unit and row.floor in ("standard", "rate", "none")
    assert row.default_order == ("asc" if metric in SET_PIECE_ORDERS else "desc")
    for lang in ("es", "en"):
        assert row.name[lang] and row.desc[lang] and row.asc[lang]
        assert row.desc[lang] != row.asc[lang]


@pytest.mark.parametrize("lang", ["es", "en"])
@pytest.mark.parametrize("grain", ["player", "team"])
def test_no_two_metrics_share_a_name_at_one_grain(lang, grain):
    rows = [r for r in cat.METRICS.values() if (r.group == "team") == (grain == "team")]
    for part in ("name", "desc", "asc"):
        names = [getattr(r, part)[lang].casefold() for r in rows]
        assert len(set(names)) == len(names)
    # a snapshot row must not read like an additive row under an operator ("points per match")
    composed = {f"{r.name[lang]} {o['suffix'][lang]}".strip().casefold()
                for r in rows for k, o in cat.OPERATORS.items()
                if k in cat.operators_for(r.id) and o["suffix"][lang]}
    assert not composed & {r.name[lang].casefold() for r in rows}


def test_names_name_the_field():
    assert "orden" in cat.METRICS["corners_and_indirect_freekicks_order"].name["es"]
    assert "esta jornada" in cat.METRICS["transfers_in_event"].name["es"]
    assert "this gameweek" in cat.METRICS["transfers_out_event"].name["en"]


@pytest.mark.parametrize("metric,operator,order,gws,expected", [
    ("goals_scored", "sum", "desc", 11, 0),
    ("goals_scored", "sum", "asc", 11, 60),
    ("goals_scored", "per_90", "asc", 11, 60),
    ("goals_scored", "per_90", "desc", 1, 45),
    ("goals_scored", "per_90", "desc", 5, 225),
    ("goals_scored", "per_90", "desc", 8, 270),
    ("goals_scored", "per_match", "desc", 20, 540),
    ("goals_scored", "per_90", "desc", 0, 270),
    ("points_per_game", "sum", "desc", 20, 540),
    ("goals_scored", "per_million", "desc", 11, 0),
    ("minutes", "sum", "asc", 11, 0),
    ("now_cost", "sum", "asc", 11, 0),
    ("penalties_order", "sum", "asc", 11, 0),
    ("team_goals", "per_match", "desc", 11, 0),
    ("team_goals", "sum", "asc", 11, 0),
])
def test_minutes_floor(metric, operator, order, gws, expected):
    assert cat.minutes_floor(metric, operator, order, gws) == expected


@pytest.mark.parametrize("finished", range(0, 39))
def test_season_floor_equals_the_ranking_tools(finished):
    from fpl_grounded_assistant.rank_players_by_metric import per_90_minutes_floor

    bootstrap = {"events": [{"finished": True}] * finished}
    assert cat.minutes_floor("goals_scored", "per_90", "desc", finished) == per_90_minutes_floor(bootstrap)


# -------------------------------------------------------------------------------------------------- defaults

def test_declared_defaults_are_filled_in():
    s = parse_spec({"metric": "total_points"})
    assert (s.shape, s.grain, s.operator, s.order, s.top_n) == ("list", "player", "sum", "desc", 10)
    assert s.match_set == (Predicate("season", True),)
    assert s.compare_to is None and s.filters == () and s.second_metric is None
    for key in ("shape", "grain", "operator", "top_n"):
        assert getattr(s, key) == cat.DEFAULTS[key]
    assert [p.to_dict() for p in s.match_set] == cat.DEFAULTS["match_set"]


@pytest.mark.parametrize("metric", ALL_IDS)
def test_defaults_round_trip(metric):
    first = parse_spec({"metric": metric})
    wire = json.loads(json.dumps(first.to_dict()))
    assert parse_spec(wire) == first
    assert parse_spec(wire).to_dict() == first.to_dict()


@pytest.mark.parametrize("raw", [
    spec(operator="minus", metric="goals_scored", metric_minus="expected_goals"),
    spec(operator="plus", metric="goals_scored", metric_plus="assists", top_n=20),
    spec(match_set=preds(("gw_range", [6, 11])),
         filters=flt("price", "between", [4.5, 6]) + flt("position", "in", ["MID", "FWD"])),
    spec(match_set=preds(("since_date", "10-10"), ("player_absent", "Player A"))),
    team(shape="comparison", filters=flt("club", "eq", "Club T"),
         match_set=preds(("player_played_60", "Player A")), compare_to=preds(("player_absent", "Player A"))),
])
def test_full_specs_round_trip(raw):
    first = parse_spec(raw)
    assert parse_spec(json.loads(json.dumps(first.to_dict()))) == first


@pytest.mark.parametrize("metric", SET_PIECE_ORDERS)
def test_set_piece_orders_default_to_ascending(metric):
    assert parse_spec({"metric": metric}).order == "asc"
    assert parse_spec({"metric": metric, "order": "desc"}).order == "desc"


@pytest.mark.parametrize("op", ["eq", "lt", "le"])
def test_low_ownership_is_the_declared_threshold(op):
    assert parse_spec(spec(filters=flt("owned_now", op, "low"))).filters == (Filter("owned_now", "lt", 10.0),)


@pytest.mark.parametrize("player,team_id", [
    ("goals_scored", "team_goals"), ("clean_sheets", "team_clean_sheets"),
    ("goals_conceded", "team_goals_conceded"), ("expected_goals", "team_expected_goals"),
    ("expected_goals_conceded", "team_expected_goals_conceded"),
])
def test_team_grain_maps_player_ids(player, team_id):
    assert parse_spec({"metric": player, "grain": "team"}).metric == team_id


def test_team_metric_implies_team_grain():
    assert parse_spec(team()).grain == "team"


def test_canonical_order_and_duplicates():
    a = parse_spec(spec(match_set=preds(("season", True), ("last_n", 5), ("last_n", 5)),
                        filters=flt("price", "le", 7) + flt("position", "eq", "MID") + flt("price", "le", 7.0)))
    b = parse_spec(spec(match_set=preds(("last_n", 5)),
                        filters=flt("position", "eq", "MID") + flt("price", "le", 7.0)))
    assert a == b


# ---------------------------------------------------------------------------------------------- strict parse

REFUSED = {
    "not_object": ([], "bad_type"),
    "unknown_key": (spec(subject="Club T"), "unknown_key"),
    "no_metric": ({}, "missing"),
    "null_value": (spec(order=None), "bad_type"),
    "unknown_metric": ({"metric": "corners_taken"}, "unknown_metric"),
    "empty_metric": ({"metric": ""}, "empty_string"),
    "metric_joined": ({"metric": "goals_scored|expected_goals", "operator": "minus"}, "unknown_metric"),
    "unknown_operator": (spec(operator="median"), "unknown_operator"),
    "empty_operator": (spec(operator=""), "empty_string"),
    "unknown_filter_op": (spec(filters=flt("price", "approx", 5)), "unknown_operator"),
    "version": (spec(v=2), "out_of_range"),
    "top_n_float": (spec(top_n=5.0), "bad_type"),
    "top_n_string": (spec(top_n="5"), "bad_type"),
    "top_n_bool": (spec(top_n=True), "bad_type"),
    "top_n_zero": (spec(top_n=0), "out_of_range"),
    "top_n_big": (spec(top_n=21), "out_of_range"),
    "last_n_float": (spec(match_set=preds(("last_n", 5.0))), "bad_type"),
    "last_n_zero": (spec(match_set=preds(("last_n", 0))), "out_of_range"),
    "gw_39": (spec(match_set=preds(("gw", 39))), "out_of_range"),
    "gw_range_reversed": (spec(match_set=preds(("gw_range", [8, 3]))), "bad_value"),
    "gw_range_one": (spec(match_set=preds(("gw_range", [8]))), "bad_type"),
    "bad_date": (spec(match_set=preds(("since_date", "02-30"))), "bad_value"),
    "date_words": (spec(match_set=preds(("since_date", "10 Oct"))), "bad_value"),
    "season_false": (spec(match_set=preds(("season", False))), "bad_value"),
    "empty_player": (spec(match_set=preds(("player_absent", "  "))), "empty_string"),
    "bad_venue": (team(match_set=preds(("venue", "neutral"))), "bad_value"),
    "unknown_pred": (spec(match_set=preds(("month", 10))), "bad_value"),
    "item_unknown_key": (spec(match_set=[{"pred": "gw", "value": 3, "quote": "GW3"}]), "unknown_key"),
    "item_missing_value": (spec(match_set=[{"pred": "gw"}]), "missing"),
    "match_set_not_list": (spec(match_set={"pred": "gw", "value": 3}), "bad_type"),
    "two_windows": (spec(match_set=preds(("last_n", 5), ("gw", 3))), "conflict"),
    "two_venues": (team(match_set=preds(("venue", "home"), ("venue", "away"))), "conflict"),
    "present_and_absent": (spec(match_set=preds(("player_absent", "Player A"),
                                                ("player_played_60", "player a"))), "conflict"),
    "minutes_float": (spec(filters=flt("minutes_in_window", "ge", 270.0)), "bad_type"),
    "price_string": (spec(filters=flt("price", "le", "7")), "bad_type"),
    "price_nan": (spec(filters=flt("price", "le", float("nan"))), "out_of_range"),
    "price_bool": (spec(filters=flt("price", "le", True)), "bad_type"),
    "owned_101": (spec(filters=flt("owned_now", "lt", 101)), "out_of_range"),
    "low_over": (spec(filters=flt("owned_now", "gt", "low")), "bad_value"),
    "between_reversed": (spec(filters=flt("price", "between", [7, 5])), "bad_value"),
    "price_not": (spec(filters=flt("price", "not", 5)), "bad_value"),
    "bad_position": (spec(filters=flt("position", "eq", "WINGER")), "bad_value"),
    "position_eq_list": (spec(filters=flt("position", "eq", ["MID"])), "bad_type"),
    "position_in_empty": (spec(filters=flt("position", "in", [])), "bad_type"),
    "empty_club": (spec(filters=flt("club", "eq", "")), "empty_string"),
    "team_metric_player_grain": (team(grain="player"), "conflict"),
    "player_metric_team_grain": ({"metric": "saves", "grain": "team"}, "conflict"),
    "team_position_filter": (team(filters=flt("position", "eq", "MID")), "conflict"),
    "team_per_90": (team(operator="per_90"), "conflict"),
    "team_per_million": (team(operator="per_million"), "conflict"),
    "minutes_per_90": ({"metric": "minutes", "operator": "per_90"}, "conflict"),
    "snapshot_per_90": ({"metric": "form", "operator": "per_90"}, "conflict"),
    "minus_without_second": (spec(operator="minus"), "missing"),
    "second_without_minus": (spec(metric_minus="assists"), "conflict"),
    "plus_with_minus_key": (spec(operator="plus", metric_minus="assists"), "conflict"),
    "minus_itself": (spec(operator="minus", metric_minus="total_points"), "conflict"),
    "minus_other_group": (spec(operator="minus", metric_minus="now_cost"), "conflict"),
    "unknown_second": (spec(operator="plus", metric_plus="corners_taken"), "unknown_metric"),
    "comparison_without_second_set": (team(shape="comparison"), "missing"),
    "list_with_second_set": (spec(compare_to=preds(("gw", 3))), "conflict"),
    "same_sets": (team(shape="comparison", match_set=preds(("gw", 3)), compare_to=preds(("gw", 3))), "conflict"),
}


@pytest.mark.parametrize("raw,code", REFUSED.values(), ids=REFUSED.keys())
def test_strict_parse_refuses(raw, code):
    with pytest.raises(QuerySpecError) as err:
        parse_spec(raw)
    assert err.value.code == code


def test_error_never_carries_the_value():
    with pytest.raises(QuerySpecError) as err:
        parse_spec(spec(operator="what the user typed"))
    assert "typed" not in str(err.value)


# ------------------------------------------------------------------------------ well formed, not executable

CLUB = flt("club", "eq", "Club T")


@pytest.mark.parametrize("raw,reasons", [
    (spec(), ()),
    (team(match_set=preds(("venue", "home"))), ()),
    (team(shape="comparison", filters=CLUB, match_set=preds(("gw_range", [1, 5])),
          compare_to=preds(("gw_range", [6, 10]))), ()),
    (team(shape="comparison", match_set=preds(("player_played_60", "Player A")),
          compare_to=preds(("player_absent", "Player A"))), ()),
    (spec(match_set=preds(("venue", "away"))), ("player_venue",)),
    ({"metric": "form", "match_set": preds(("last_n", 5))}, ("season_only_metric",)),
    (team(match_set=preds(("player_absent", "Player A"), ("player_played_60", "Player B"))), ("several_players",)),
    (team(shape="comparison", filters=CLUB, match_set=preds(("player_absent", "Player A")),
          compare_to=preds(("player_absent", "Player B"))), ("several_players",)),
    (team(shape="comparison", match_set=preds(("gw_range", [1, 5])),
          compare_to=preds(("gw_range", [6, 10]))), ("difference_list",)),
    (spec(shape="comparison", filters=CLUB, match_set=preds(("gw_range", [1, 5])),
          compare_to=preds(("gw_range", [6, 10]))), ("difference_list",)),
])
def test_unsupported_reasons(raw, reasons):
    assert unsupported_reasons(parse_spec(raw)) == reasons


def test_unsupported_ids_are_declared():
    assert {"player_venue", "several_players", "difference_list"} <= set(cat.UNSUPPORTED_KINDS)
