"""The engine over what ``GwLiveCache`` really serves: the synthetic league sent through its own parser and
checks, as live payloads."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.gw_live_cache import GwLiveCache
from fpl_grounded_assistant.query_engine import COMPLETE, DATA_UNAVAILABLE, needed_gameweeks, run_query
from fpl_grounded_assistant.query_spec import parse_spec

from test_query_engine import GOLDEN, world


def served(edit=None):
    """(bootstrap, load) over fake fetchers; *edit* may change the source before it is read."""
    bootstrap, source = world()
    if edit:
        edit(bootstrap, source)

    def fetch_fixtures(**_):
        return [f for data in source.gameweeks.values() for f in data.fixtures]

    def fetch_live(gameweek, **_):
        data = source.gameweeks[gameweek]
        return {"elements": [
            {"id": element_id, "stats": dict(row),
             "explain": [{"fixture": fixture, "stats": [{"identifier": "minutes", "value": minutes}]}
                         for fixture, minutes in data.fixture_minutes.get(element_id, {}).items()]}
            for element_id, row in data.rows.items()]}

    cache = GwLiveCache(fetch_live=fetch_live, fetch_fixtures=fetch_fixtures, session=object())
    return bootstrap, cache


def run(raw, bootstrap, cache):
    spec = parse_spec(raw)
    return run_query(spec, bootstrap, cache.load(needed_gameweeks(spec, bootstrap), bootstrap))


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_golden_over_the_real_cache(case):
    bootstrap, cache = served()
    result = run(case["spec"], bootstrap, cache)
    expect = case["expect"]
    assert result.state == expect["state"], result.reason
    if result.state == COMPLETE:
        assert result.sum_check in ("passed", "not_applicable")
    if "rows" in expect:
        assert [r.name for r in result.rows] == [n for n, _ in expect["rows"]]
        assert [r.value for r in result.rows] == pytest.approx([v for _, v in expect["rows"]], abs=1e-5)
    if "sides" in expect:
        assert [s.total for s in result.comparison.sides] == pytest.approx(
            [s["total"] for s in expect["sides"]], abs=1e-5)


def test_a_double_arrives_as_two_fixtures_of_minutes_and_one_total():
    bootstrap, cache = served()
    batch = cache.load([6], bootstrap)
    assert any(len(minutes) == 2 for minutes in batch.gameweeks[6].fixture_minutes.values())
    result = run({"metric": "total_points", "match_set": [{"pred": "gw", "value": 6}]}, bootstrap, cache)
    assert result.state == COMPLETE and max(r.matches for r in result.rows) == 2


def test_a_season_total_that_disagrees_blocks_that_metric_only():
    def edit(bootstrap, _):
        bootstrap["elements"][0]["saves"] += 1

    bootstrap, cache = served(edit)
    broken = run({"metric": "saves"}, bootstrap, cache)
    assert (broken.state, broken.reason, broken.bad_metrics) == (DATA_UNAVAILABLE, "invariant_failed", ("saves",))
    fine = run({"metric": "total_points"}, bootstrap, cache)
    assert (fine.state, fine.sum_check) == (COMPLETE, "passed")


def test_a_gameweek_waiting_for_its_check_leaves_the_sums_unchecked():
    def edit(bootstrap, _):
        bootstrap["events"][7]["data_checked"] = False

    bootstrap, cache = served(edit)
    result = run({"metric": "total_points"}, bootstrap, cache)
    assert (result.state, result.sum_check, result.provisional) == (COMPLETE, "not_checked", True)


def test_a_swapped_gameweek_reaches_the_answer_as_unavailable():
    def edit(_, source):
        a, b = source.gameweeks[2], source.gameweeks[3]
        a.rows, b.rows = b.rows, a.rows
        a.fixture_minutes, b.fixture_minutes = b.fixture_minutes, a.fixture_minutes

    bootstrap, cache = served(edit)
    result = run({"metric": "total_points"}, bootstrap, cache)
    assert (result.state, result.reason, result.missing_gameweeks) == (DATA_UNAVAILABLE, "fixture_mismatch", (2, 3))
    assert result.rows == ()
