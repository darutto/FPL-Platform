"""Query layer PR 3: the engine, on a made-up league (``query_golden/world.json``)."""
from __future__ import annotations

import ast
import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_engine import (COMPLETE, DATA_UNAVAILABLE, NEEDS_CLARIFICATION, UNSUPPORTED,
                                                 needed_gameweeks, run_query)
from fpl_grounded_assistant.query_spec import parse_spec

GOLDEN_DIR = Path(__file__).parent / "query_golden"
WORLD = json.loads((GOLDEN_DIR / "world.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((GOLDEN_DIR / "golden.json").read_text(encoding="utf-8"))
EXTRA = os.environ.get("FPL_QUERY_GOLDEN_EXTRA")            # the reviewer's held-out cases, same format
if EXTRA:
    GOLDEN = GOLDEN + json.loads(Path(EXTRA).read_text(encoding="utf-8"))

SUBJECT, MOVER = 106, 207


@dataclass
class Gw:
    gameweek: int
    status: str
    revision: str
    fixtures: list
    rows: dict
    fixture_minutes: dict


@dataclass
class Batch:
    gameweeks: dict
    unavailable: dict = field(default_factory=dict)
    bad_metrics: frozenset = frozenset()
    invariant: str = "passed"


def world():
    """A fresh (bootstrap, batch) a test may edit."""
    raw = copy.deepcopy(WORLD)
    gameweeks = {int(gw): Gw(
        int(gw), d["status"], d["revision"], d["fixtures"], {int(p): r for p, r in d["rows"].items()},
        {int(p): {int(f): m for f, m in per.items()} for p, per in d["fixture_minutes"].items()})
        for gw, d in raw["gameweeks"].items()}
    return raw["bootstrap"], Batch(gameweeks)


def run(raw, bootstrap=None, batch=None):
    if bootstrap is None:
        bootstrap, batch = world()
    return run_query(parse_spec(raw), bootstrap, batch)


def element(bootstrap, pid):
    return next(e for e in bootstrap["elements"] if e["id"] == pid)


def pred(name, value):
    return {"pred": name, "value": value}


def flt(field_, op, value):
    return {"field": field_, "op": op, "value": value}


def with_without(metric="team_expected_goals", **kw):
    return {"metric": metric, "shape": "comparison", "filters": [flt("club", "eq", "Alder Town")],
            "match_set": [pred("player_played_60", "SubjectAld")],
            "compare_to": [pred("player_absent", "SubjectAld")], **kw}


# -------------------------------------------------------------------------------------------------- the golden

def test_the_golden_has_25_cases_and_its_oracle_never_imports_the_product():
    assert len([c for c in GOLDEN if c["id"].startswith("g")]) == 25
    tree = ast.parse((GOLDEN_DIR / "oracle.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"json", "collections", "pathlib", "__future__"}


def test_committed_golden_is_what_the_oracle_computes():
    namespace = {"__file__": str(GOLDEN_DIR / "oracle.py"), "__name__": "oracle"}
    exec(compile((GOLDEN_DIR / "oracle.py").read_text(encoding="utf-8"), "oracle.py", "exec"), namespace)
    computed = [{"id": i, "spec": s, "expect": e} for i, s, e in namespace["cases"]()]
    committed = json.loads((GOLDEN_DIR / "golden.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(computed)) == committed


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_golden(case):
    expect = case["expect"]
    result = run(case["spec"])
    assert result.state == expect["state"], result.reason
    if "reason" in expect:
        assert result.reason == expect["reason"]
    if "rows" in expect:
        assert [r.name for r in result.rows] == [n for n, _ in expect["rows"]]
        assert [r.value for r in result.rows] == pytest.approx([v for _, v in expect["rows"]], abs=1e-5)
    if "sides" in expect:
        for side, want in zip(result.comparison.sides, expect["sides"]):
            assert (side.n, side.home, list(side.gameweeks)) == (want["n"], want["home"], want["gameweeks"])
            assert (side.total, side.per_match) == pytest.approx((want["total"], want["per_match"]), abs=1e-5)
            assert side.mean_fdr == pytest.approx(want["mean_fdr"])
        assert [list(m) for m in result.comparison.mixed] == expect["mixed"]


# ----------------------------------------------------------------------------------------------------- windows

@pytest.mark.parametrize("metric", cat.metric_ids("additive"))
def test_window_1_to_n_equals_the_season_total(metric):
    bootstrap, batch = world()
    # a floor-free list of every player, read 20 at a time through the position and club filters
    for window in ([pred("gw_range", [1, 8])], [pred("season", True)], [pred("last_n", 8)]):
        for club in bootstrap["teams"]:
            result = run({"metric": metric, "match_set": window, "top_n": 20,
                          "filters": [flt("club", "eq", club["short_name"])]}, bootstrap, batch)
            assert result.state == COMPLETE and len(result.rows) == 8
            for row in result.rows:
                assert row.value == pytest.approx(float(element(bootstrap, row.id)[metric]), abs=1e-6)


def test_last_n_ends_at_the_last_finished_gameweek():
    bootstrap, batch = world()
    bootstrap["events"][7]["finished"] = False
    result = run({"metric": "total_points", "match_set": [pred("last_n", 3)]}, bootstrap, batch)
    assert result.gameweeks == (5, 6, 7)


def test_a_gameweek_asked_by_number_may_be_provisional():
    bootstrap, batch = world()
    batch.gameweeks[8].status = "provisional"
    result = run({"metric": "total_points", "match_set": [pred("gw", 8)]}, bootstrap, batch)
    assert (result.state, result.provisional) == (COMPLETE, True)
    assert result.revisions == {8: "1:synthetic8"}


def test_since_date_without_a_year_is_a_programming_error():
    with pytest.raises(ValueError):
        run({"metric": "total_points", "match_set": [pred("since_date", "09-19")]})


def test_since_date_cuts_by_kickoff():
    # GW7's first match is on 2026-09-26; one day later drops it and keeps the later ones
    first = run({"metric": "team_goals", "match_set": [pred("since_date", "2026-09-26")]})
    later = run({"metric": "team_goals", "match_set": [pred("since_date", "2026-09-27")]})
    assert first.gameweeks == (7, 8) and later.gameweeks == (7, 8)
    assert sum(r.matches for r in later.rows) == sum(r.matches for r in first.rows) - 2


def test_synthetic_blank_gameweek():
    teams_ = run({"metric": "team_goals", "match_set": [pred("gw", 3)]})
    assert sorted(r.club for r in teams_.rows) == ["ALD", "BIR", "CED", "DUN"]
    blank = run({"metric": "minutes", "match_set": [pred("gw", 3)], "filters": [flt("club", "eq", "ELM")]})
    assert blank.state == COMPLETE and {r.value for r in blank.rows} == {0.0}


def test_double_gameweek_cut_by_a_date_is_not_guessed():
    # GW6 runs over two days: from the second one, players of the earlier-and-later doubles cannot be split
    result = run({"metric": "total_points", "match_set": [pred("since_date", "2026-09-20")],
                  "filters": [flt("club", "eq", "ELM")]})
    assert (result.state, result.reason) == (DATA_UNAVAILABLE, "double_gameweek_split")
    assert result.missing_gameweeks == (6,) and result.rows == ()


# ------------------------------------------------------------------------------------------- thresholds, ties

@pytest.mark.parametrize("field_,attribute", [("price", "price"), ("owned_now", "owned"),
                                              ("minutes_in_window", "minutes")])
def test_less_than_excludes_the_threshold_and_at_most_keeps_it(field_, attribute):
    base = run({"metric": "total_points", "top_n": 5})
    edge = getattr(base.rows[0], attribute)
    below = run({"metric": "total_points", "top_n": 20, "filters": [flt(field_, "lt", edge)]})
    at_most = run({"metric": "total_points", "top_n": 20, "filters": [flt(field_, "le", edge)]})
    assert base.rows[0].id not in {r.id for r in below.rows}
    assert base.rows[0].id in {r.id for r in at_most.rows}
    assert all(getattr(r, attribute) < edge for r in below.rows)


def _tied_world(values):
    bootstrap, batch = world()
    for data in batch.gameweeks.values():
        for row in data.rows.values():
            row["red_cards"] = 0
    for e in bootstrap["elements"][:len(values)]:
        batch.gameweeks[1].rows.setdefault(e["id"], {k: 0 for k in cat.metric_ids("additive")})
        batch.gameweeks[1].rows[e["id"]]["red_cards"] = values[bootstrap["elements"].index(e)]
    return bootstrap, batch


def test_a_tie_at_the_cutoff_is_shown_whole():
    result = run({"metric": "red_cards", "top_n": 3}, *_tied_world([5, 4, 3, 3, 3, 1]))
    assert [r.value for r in result.rows] == [5, 4, 3, 3, 3] and result.tied_omitted == 0


def test_a_tie_stops_at_15_rows_and_says_how_many_are_left():
    result = run({"metric": "red_cards", "top_n": 3}, *_tied_world([9] + [2] * 20))
    assert len(result.rows) == 15 and result.tied_omitted == 6


def test_top_20_may_show_20():
    result = run({"metric": "red_cards", "top_n": 20}, *_tied_world([2] * 30))
    assert len(result.rows) == 20 and result.tied_omitted == 10


# ---------------------------------------------------------------------------------------------- current club

def test_the_movers_earlier_xg_is_not_his_new_clubs():
    bootstrap, batch = world()
    old_fixtures = {f["id"] for gw in (1, 2) for f in batch.gameweeks[gw].fixtures if 1 in (f["team_h"], f["team_a"])}
    for gw in (1, 2):
        batch.gameweeks[gw].rows[MOVER]["expected_goals"] = 7.0          # big enough to show if counted
    result = run({"metric": "team_expected_goals", "match_set": [pred("gw_range", [1, 2])]}, bootstrap, batch)
    assert result.state == COMPLETE
    # club 2's cross-check must not take his 14.0 (he scored them for club 1)
    birch = next(r for r in result.rows if r.club == "BIR")
    assert birch.value_range is None or birch.value_range[1] < 7
    assert all(set(batch.gameweeks[gw].fixture_minutes[MOVER]) <= old_fixtures for gw in (1, 2))


def test_a_player_total_still_counts_what_he_did_at_his_old_club():
    result = run({"metric": "minutes", "match_set": [pred("gw_range", [1, 2])],
                  "filters": [flt("club", "eq", "BIR")], "top_n": 20})
    assert next(r for r in result.rows if r.id == MOVER).value == 180


def test_matches_before_he_joined_are_not_without_him():
    bootstrap, batch = world()
    result = run({"metric": "team_goals", "match_set": [pred("player_absent", "Mover")]}, bootstrap, batch)
    assert result.state == COMPLETE and result.rows == ()               # he played every match since joining
    compare = run({"metric": "team_goals", "shape": "comparison", "match_set": [pred("player_played_60", "Mover")],
                   "compare_to": [pred("player_absent", "Mover")]}, bootstrap, batch)
    assert (compare.state, compare.reason) == (DATA_UNAVAILABLE, "too_few_matches")


# ------------------------------------------------------------------------------------------------ team xG

def _first_match_of_alder(batch):
    return next(f for f in batch.gameweeks[1].fixtures if 1 in (f["team_h"], f["team_a"]))


def _set_opponents_xgc(batch, bootstrap, values):
    """Give Alder's GW1 opponents' 90-minute players these xGC values, in order."""
    fixture = _first_match_of_alder(batch)
    opponent = fixture["team_a"] if fixture["team_h"] == 1 else fixture["team_h"]
    full = [p for p, per in sorted(batch.gameweeks[1].fixture_minutes.items())
            if per == {fixture["id"]: 90} and element(bootstrap, p)["team"] == opponent]
    for pid, value in zip(full, values + [values[0]] * len(full)):
        batch.gameweeks[1].rows[pid]["expected_goals_conceded"] = value


def _set_shooters(batch, bootstrap, total):
    fixture = _first_match_of_alder(batch)
    mine = [p for p, per in batch.gameweeks[1].fixture_minutes.items()
            if fixture["id"] in per and element(bootstrap, p)["team"] == 1]
    for pid in mine:
        batch.gameweeks[1].rows[pid]["expected_goals"] = 0.0
    batch.gameweeks[1].rows[mine[0]]["expected_goals"] = total


def _alder_gw1_xg(bootstrap, batch):
    result = run({"metric": "team_expected_goals", "match_set": [pred("gw", 1)],
                  "filters": [flt("club", "eq", "ALD")]}, bootstrap, batch)
    assert result.state == COMPLETE, result.reason
    return result, result.rows[0]


def _unmove(bootstrap):
    element(bootstrap, MOVER).update(team=1, team_join_date="2025-07-01")


def test_team_xg_is_the_opponents_commonest_value_and_one_outlier_does_not_move_it():
    bootstrap, batch = world()
    _unmove(bootstrap)
    _set_opponents_xgc(batch, bootstrap, [1.5, 1.5, 1.5, 1.5, 9.9])
    _set_shooters(batch, bootstrap, 1.55)
    result, row = _alder_gw1_xg(bootstrap, batch)
    assert (row.value, row.value_range, result.cross_check) == (1.5, None, "agree")


def test_shooters_that_disagree_are_a_range_never_an_average():
    bootstrap, batch = world()
    _unmove(bootstrap)
    _set_opponents_xgc(batch, bootstrap, [1.5])
    _set_shooters(batch, bootstrap, 1.88)
    result, row = _alder_gw1_xg(bootstrap, batch)
    assert (row.value, row.value_range, result.cross_check) == (1.5, (1.5, 1.88), "range")


@pytest.mark.parametrize("shooters,expected", [
    (1.55, (1.4, 1.7)),        # the shooters sit inside the tie: the tie is the range
    (2.4, (1.4, 2.4)),         # they sit outside it: the range reaches them
])
def test_tied_opponent_values_are_a_range_and_none_is_picked(shooters, expected):
    bootstrap, batch = world()
    _unmove(bootstrap)
    fixture = _first_match_of_alder(batch)
    opponent = fixture["team_a"] if fixture["team_h"] == 1 else fixture["team_h"]
    full = [p for p, per in sorted(batch.gameweeks[1].fixture_minutes.items())
            if per == {fixture["id"]: 90} and element(bootstrap, p)["team"] == opponent]
    assert len(full) >= 4
    for pid in full[4:]:                                      # leave exactly two against two
        batch.gameweeks[1].fixture_minutes[pid][fixture["id"]] = 89
    for pid, value in zip(full[:4], [1.4, 1.4, 1.7, 1.7]):
        batch.gameweeks[1].rows[pid]["expected_goals_conceded"] = value
    _set_shooters(batch, bootstrap, shooters)
    result, row = _alder_gw1_xg(bootstrap, batch)
    assert (row.value_range, result.cross_check) == (expected, "range")


def test_team_xg_with_no_full_match_opponent_is_unavailable():
    bootstrap, batch = world()
    for per in batch.gameweeks[1].fixture_minutes.values():
        for fixture in per:
            per[fixture] = min(per[fixture], 89)
    result = run({"metric": "team_expected_goals", "match_set": [pred("gw", 1)]}, bootstrap, batch)
    assert (result.state, result.reason, result.missing_gameweeks) == (DATA_UNAVAILABLE, "team_xg_unmeasured", (1,))


def test_team_xg_conceded_is_the_opponents_team_xg():
    made = run({"metric": "team_expected_goals", "match_set": [pred("gw", 1)]})
    conceded = run({"metric": "team_expected_goals_conceded", "match_set": [pred("gw", 1)]})
    first_fixtures = {(f["team_h"], f["team_a"]) for f in WORLD["gameweeks"]["1"]["fixtures"]}
    by_team = {r.id: r.value for r in made.rows}
    against = {r.id: r.value for r in conceded.rows}
    for home, away in first_fixtures:
        assert against[home] == by_team[away] and against[away] == by_team[home]


# --------------------------------------------------------------------------------------------- the comparison

def test_with_and_without():
    """A with / without comparison shaped like the approved case: mixed match listed, n and FDR per set."""
    result = run(with_without())
    assert result.state == COMPLETE, result.reason
    c = result.comparison
    assert (c.club, c.sides[0].gameweeks, c.sides[1].gameweeks) == ("ALD", (1, 2, 3, 8), (4, 5, 6))
    assert (c.sides[0].n, c.sides[1].n, c.mixed, c.before_join) == (4, 3, ((7, 13),), ())
    assert c.small_sample is True and result.players["SubjectAld"]["id"] == SUBJECT
    for side in c.sides:
        assert side.n == side.home + side.away == len(side.per_match_values)
        assert side.total == pytest.approx(sum(side.per_match_values))
        assert side.per_match == pytest.approx(side.total / side.n, abs=1e-6)
        assert side.mean_fdr is not None
    a, b = (s.per_match_values for s in c.sides)
    assert c.ranges_overlap == (min(a) <= max(b) and min(b) <= max(a))
    assert c.sides[0].total_range is not None                         # GW2: the shooters disagree
    assert result.cross_check == "range"


def test_the_club_can_come_from_the_player():
    named = run(with_without())
    implied = run({**with_without(), "filters": []})
    assert implied.comparison == named.comparison


def test_a_club_the_player_is_not_at_is_asked_about():
    result = run({**with_without(), "filters": [flt("club", "eq", "BIR")]})
    assert (result.state, result.reason) == (NEEDS_CLARIFICATION, "player_not_at_club")
    assert result.clarify["candidates"][0]["club"] == "ALD" and result.comparison is None


def test_under_three_matches_on_a_side_there_is_no_comparison():
    bootstrap, batch = world()
    window = {"match_set": [pred("player_played_60", "SubjectAld")]}
    batch.gameweeks[4].fixture_minutes[SUBJECT] = {_alder_fixture(batch, 4): 90}
    result = run(with_without(**window), bootstrap, batch)
    assert (result.state, result.reason, result.comparison) == (DATA_UNAVAILABLE, "too_few_matches", None)


def _alder_fixture(batch, gw):
    return next(f["id"] for f in batch.gameweeks[gw].fixtures if 1 in (f["team_h"], f["team_a"]))


# -------------------------------------------------------------------------------------------------- operators

def test_plus_of_xg_and_xa_is_xgi_within_a_cent():
    ids = {"filters": [flt("club", "eq", "ALD")], "top_n": 20}
    summed = run({"metric": "expected_goals", "operator": "plus", "metric_plus": "expected_assists", **ids})
    direct = run({"metric": "expected_goal_involvements", **ids})
    a = {r.id: r.value for r in summed.rows}
    b = {r.id: r.value for r in direct.rows}
    assert a.keys() == b.keys() and all(abs(a[i] - b[i]) <= 0.01 for i in a)
    assert all(r.parts and sum(r.parts) == pytest.approx(r.value) for r in summed.rows)


def test_todays_value_metrics():
    bootstrap, batch = world()
    dear = run({"metric": "now_cost", "top_n": 1}, bootstrap, None)
    assert dear.rows[0].value == max(e["now_cost"] for e in bootstrap["elements"]) / 10
    takers = run({"metric": "penalties_order", "top_n": 20}, bootstrap, None)
    assert [r.value for r in takers.rows] == [1.0] * 6 + [2.0] * 6 and takers.min_minutes == 0
    assert needed_gameweeks(parse_spec({"metric": "form"}), bootstrap) == ()


# ------------------------------------------------------------------------------------------- the honest states

def test_a_missing_gameweek_gives_no_rows():
    bootstrap, batch = world()
    del batch.gameweeks[6]
    batch.unavailable = {6: "fixture_mismatch"}
    result = run({"metric": "total_points"}, bootstrap, batch)
    assert (result.state, result.reason, result.missing_gameweeks) == (DATA_UNAVAILABLE, "fixture_mismatch", (6,))
    assert result.rows == () and result.gameweeks == tuple(range(1, 9))
    assert run({"metric": "total_points", "match_set": [pred("last_n", 2)]}, bootstrap, batch).state == COMPLETE


def test_a_future_gameweek_is_unavailable():
    result = run({"metric": "total_points", "match_set": [pred("gw_range", [7, 10])]})
    assert (result.state, result.missing_gameweeks) == (DATA_UNAVAILABLE, (9, 10))


@pytest.mark.parametrize("raw,blocked", [
    ({"metric": "saves"}, True),
    ({"metric": "total_points", "operator": "minus", "metric_minus": "saves"}, True),
    ({"metric": "total_points"}, False),
    ({"metric": "team_goals"}, False),
])
def test_a_broken_metric_blocks_only_what_uses_it(raw, blocked):
    bootstrap, batch = world()
    batch.bad_metrics = frozenset({"saves"})
    result = run(raw, bootstrap, batch)
    assert (result.state == DATA_UNAVAILABLE) is blocked
    if blocked:
        assert result.bad_metrics == ("saves",) and result.rows == ()


def test_broken_minutes_block_every_rate():
    bootstrap, batch = world()
    batch.bad_metrics = frozenset({"minutes"})
    assert run({"metric": "goals_scored", "operator": "per_90"}, bootstrap, batch).state == DATA_UNAVAILABLE
    assert run({"metric": "goals_scored"}, bootstrap, batch).state == COMPLETE


def test_before_the_first_finished_gameweek_there_is_no_season():
    bootstrap, batch = world()
    for event in bootstrap["events"]:
        event["finished"] = False
    result = run({"metric": "total_points"}, bootstrap, batch)
    assert (result.state, result.reason) == (DATA_UNAVAILABLE, "no_finished_gameweek")


def test_an_unsupported_spec_is_not_run():
    result = run({"metric": "total_points", "match_set": [pred("venue", "home")]}, {"events": []}, None)
    assert (result.state, result.unsupported, result.rows) == (UNSUPPORTED, ("player_venue",), ())


@pytest.mark.parametrize("raw,reason", [
    ({"metric": "total_points", "filters": [flt("club", "eq", "Zzz")]}, "club_not_found"),
    ({"metric": "team_goals", "match_set": [pred("player_absent", "Nobody Here")]}, "player_not_found"),
    ({"metric": "team_goals", "match_set": [pred("player_absent", "Subject")]}, "player_ambiguous"),
])
def test_a_name_that_does_not_resolve_is_asked_about(raw, reason):
    result = run(raw)
    assert (result.state, result.reason, result.rows) == (NEEDS_CLARIFICATION, reason, ())


def test_a_with_set_filtered_to_another_club_is_an_opponent_question():
    result = run({"metric": "total_points", "match_set": [pred("player_absent", "SubjectAld")],
                  "filters": [flt("club", "eq", "BIR")]})
    assert (result.state, result.unsupported) == (UNSUPPORTED, ("opponent",))


def test_the_input_is_not_changed():
    bootstrap, batch = world()
    before = copy.deepcopy((bootstrap, batch))
    run({"metric": "total_points"}, bootstrap, batch)
    assert (bootstrap, batch) == before


# ---------------------------------------------------------------------------------------------- the sum check

@pytest.mark.parametrize("invariant,raw,expected", [
    ("passed", {"metric": "total_points"}, "passed"),
    ("failed", {"metric": "total_points"}, "passed"),             # only an unused metric failed
    ("not_checked", {"metric": "total_points"}, "not_checked"),
    ("not_checked", {"metric": "team_expected_goals", "match_set": [pred("gw", 1)]}, "not_checked"),
    ("not_checked", with_without("team_goals"), "not_checked"),   # the sets are built on player minutes
    ("not_checked", {"metric": "team_goals"}, "not_applicable"),  # final scores only
    ("not_checked", {"metric": "now_cost"}, "not_applicable"),
])
def test_a_complete_answer_says_whether_its_sums_were_checked(invariant, raw, expected):
    bootstrap, batch = world()
    batch.invariant = invariant
    batch.bad_metrics = frozenset({"saves"}) if invariant == "failed" else frozenset()
    result = run(raw, bootstrap, batch)
    assert (result.state, result.sum_check) == (COMPLETE, expected)


# ----------------------------------------------------------------------------------------- double gameweek (6)

ELM = 5


def _doubles(batch, team=ELM):
    return [f for f in batch.gameweeks[6].fixtures if team in (f["team_h"], f["team_a"])]


def test_a_double_counts_two_matches_and_one_gameweek_total():
    bootstrap, batch = world()
    assert len(_doubles(batch)) == 2
    player = ELM * 100 + 2                                    # played both
    assert len(batch.gameweeks[6].fixture_minutes[player]) == 2
    spec = {"match_set": [pred("gw", 6)], "filters": [flt("club", "eq", "ELM")], "top_n": 20}
    total = run({"metric": "total_points", **spec}, bootstrap, batch)
    mine = next(r for r in total.rows if r.id == player)
    assert (mine.matches, mine.minutes) == (2, 180)
    assert mine.value == batch.gameweeks[6].rows[player]["total_points"]
    rate = run({"metric": "total_points", "operator": "per_match", **spec}, bootstrap, batch)
    assert next(r for r in rate.rows if r.id == player).value == pytest.approx(mine.value / 2)
    goals = run({"metric": "team_goals", "match_set": [pred("gw", 6)]}, bootstrap, batch)
    assert {r.club: r.matches for r in goals.rows}["ELM"] == 2


def test_fixture_minutes_separate_the_two_matches_of_a_double():
    bootstrap, batch = world()
    subject = ELM * 100 + 5                                   # played only one of the two
    (only,) = batch.gameweeks[6].fixture_minutes[subject]
    other = next(f["id"] for f in _doubles(batch) if f["id"] != only)
    name = element(bootstrap, subject)["web_name"]
    # one absence is under the minimum: make him absent in two earlier matches as well
    for gw in (1, 2):
        batch.gameweeks[gw].fixture_minutes.pop(subject, None)
    result = run({"metric": "team_goals", "shape": "comparison", "match_set": [pred("player_played_60", name)],
                  "compare_to": [pred("player_absent", name)]}, bootstrap, batch)
    assert result.state == COMPLETE, result.reason
    played, absent = result.comparison.sides
    assert (6, only) in played.matches and (6, other) in absent.matches


def test_player_rows_of_a_split_double_are_not_guessed():
    bootstrap, batch = world()
    name = element(bootstrap, ELM * 100 + 5)["web_name"]
    result = run({"metric": "expected_assists", "match_set": [pred("player_absent", name)]}, bootstrap, batch)
    assert (result.state, result.reason, result.missing_gameweeks) == (
        DATA_UNAVAILABLE, "double_gameweek_split", (6,))


def test_team_xg_of_a_double_against_a_double_is_unavailable_not_estimated():
    """Both of a doubling opponent's matches share one gameweek total, so nobody there measures one of them."""
    bootstrap, batch = world()
    for per in batch.gameweeks[6].fixture_minutes.values():
        if len(per) == 1:                                     # nobody played just one of two matches for 90'
            for fixture in per:
                per[fixture] = min(per[fixture], 89)
    result = run({"metric": "team_expected_goals", "match_set": [pred("gw", 6)]}, bootstrap, batch)
    assert (result.state, result.reason, result.rows) == (DATA_UNAVAILABLE, "team_xg_unmeasured", ())
