"""The decline check behind the top gate. Synthetic data only; the element-summary seam is injected, never live."""
from __future__ import annotations

import importlib
import time

import pytest

from fpl_grounded_assistant import plan_trend as pt
from fpl_grounded_assistant.plan_to_sign import plan_to_sign
from test_plan_to_sign import _bootstrap, _squad_payload

pts = importlib.import_module("fpl_grounded_assistant.plan_to_sign")


def _row(rnd, points, xgi, minutes=90, starts=1):
    return {"round": rnd, "total_points": points, "expected_goal_involvements": str(xgi), "minutes": minutes, "starts": starts}


def _history(*, season=(8, 0.6), recent=(2, 0.1), n_season=5, n_recent=3, recent_minutes=90):
    rows = [_row(i + 1, season[0], season[1]) for i in range(n_season)]
    rows += [_row(n_season + i + 1, recent[0], recent[1], minutes=recent_minutes) for i in range(n_recent)]
    return {"history": rows}


# ---------------------------------------------------------------------------
# assess_trend
# ---------------------------------------------------------------------------

def test_form_down_xgi_down_and_a_hard_run_is_a_decline():
    info = pt.assess_trend(_history(), hard_fixtures=3)
    assert info["status"] == "ok" and info["declining"]
    assert info["form_down"] and info["xgi_down"] and info["hard_run"]
    assert info["form_recent"] == 2.0 and info["form_season"] == 5.75


@pytest.mark.parametrize("summary,hard", [
    (_history(recent=(8, 0.1)), 4),   # xGI down but form is fine
    (_history(recent=(2, 0.6)), 4),   # form down but xGI is fine
    (_history(), 2),                  # both down, but the run is not hard
])
def test_each_of_the_three_is_needed(summary, hard):
    assert not pt.assess_trend(summary, hard_fixtures=hard)["declining"]


def test_a_small_dip_is_not_a_decline():
    # 6 recent against a 6.5 season is under the 20% drop
    assert not pt.assess_trend(_history(season=(7, 0.6), recent=(5, 0.55)), hard_fixtures=5)["declining"]


def test_too_few_appearances_is_insufficient_not_decline():
    info = pt.assess_trend(_history(n_season=1, n_recent=3), hard_fixtures=5)
    assert info["status"] == "insufficient" and not info["declining"]


def test_a_missing_summary_is_unavailable():
    for summary in (None, {}, {"history": "x"}):
        info = pt.assess_trend(summary, hard_fixtures=5)
        assert info["status"] == "unavailable" and not info["declining"]


def test_recent_xgi_needs_ninety_minutes_to_be_read():
    info = pt.assess_trend(_history(recent_minutes=20), hard_fixtures=5)
    assert info["xgi_recent"] is None and not info["xgi_down"] and not info["declining"]


def test_recent_starts_counts_the_last_five_gameweeks():
    rows = [_row(i, 5, 0.3, starts=1 if i in (4, 6, 8) else 0, minutes=90 if i in (4, 6, 8) else 20) for i in range(1, 9)]
    assert pt.assess_trend({"history": rows}, hard_fixtures=0)["recent_starts"] == 3  # rounds 4..8: starts at 4, 6, 8
    legacy = [{"round": i, "total_points": 3, "minutes": 90 if i % 2 else 10} for i in range(1, 8)]
    assert pt.assess_trend({"history": legacy}, hard_fixtures=0)["recent_starts"] == 3  # no starts field: 60+ minutes


def test_string_numbers_and_unsorted_rounds_are_handled():
    summary = _history()
    summary["history"] = list(reversed(summary["history"]))
    assert pt.assess_trend(summary, hard_fixtures=3)["declining"]


# ---------------------------------------------------------------------------
# fetch_summaries
# ---------------------------------------------------------------------------

def test_fetch_is_capped_and_a_failure_is_none(monkeypatch):
    seen = []

    def seam(pid, bootstrap):
        seen.append(pid)
        if pid == 3:
            raise RuntimeError("boom")
        return None if pid == 4 else {"history": []}

    monkeypatch.setattr(pt, "_fetch_summary", seam)
    out = pt.fetch_summaries({}, [1, 2, 3, 4, 5, 6, 7, 1])
    assert sorted(seen) == [1, 2, 3, 4, 5] and sorted(out) == [1, 2, 3, 4, 5]
    assert out[3] is None and out[4] is None and out[1] == {"history": []}


def test_fetch_gives_up_at_the_deadline(monkeypatch):
    monkeypatch.setattr(pt, "FETCH_DEADLINE_S", 0.2)
    monkeypatch.setattr(pt, "_fetch_summary", lambda pid, b: (time.sleep(1.0), {"history": []})[1] if pid == 2 else {"history": []})
    started = time.monotonic()
    out = pt.fetch_summaries({}, [1, 2])
    assert time.monotonic() - started < 0.9
    assert out[1] == {"history": []} and out[2] is None


# ---------------------------------------------------------------------------
# through plan_to_sign
# ---------------------------------------------------------------------------

def _fixtures(team, difficulties, first_gw=11):
    return [{"gameweek": first_gw + i, "difficulty": d, "opponent_team": 1 if team != 1 else 2, "is_home": True}
            for i, d in enumerate(difficulties)]


@pytest.fixture
def run(monkeypatch):
    def go(*, finished=10, hard=5, summaries=None, owned=(13,), jackson_xgi=None, **kwargs):
        bs = _bootstrap()
        for pid in owned:
            next(e for e in bs["elements"] if e["id"] == pid)["selected_by_percent"] = "40.0"
        if jackson_xgi is not None:
            next(e for e in bs["elements"] if e["id"] == 100)["expected_goal_involvements"] = str(jackson_xgi)
        bs["events"] = [{"id": i, "is_current": False, "is_next": False, "finished": True} for i in range(1, finished + 1)]
        bs["events"].append({"id": finished + 1, "is_current": True, "is_next": False, "finished": False})
        bs["team_fixtures"] = {2: _fixtures(2, [5] * hard + [2] * (5 - hard), finished + 1)}
        if summaries is not None:
            bs["_element_summaries"] = summaries
        monkeypatch.setattr(pts, "get_my_squad", lambda b, gw=None: _squad_payload(30))
        kwargs.setdefault("moves", "one")
        kwargs.setdefault("exclude_out_ids", [14])  # Bravo (injured) out of the way: Alpha is the only FWD sale
        return plan_to_sign(target="N.Jackson", bootstrap=bs, **kwargs)
    return go


def test_a_declining_top_is_sold_with_the_trend_attached(run):
    res = run(summaries={"13": _history()})
    top = res["options"][0]["tops_sold"][0]
    assert top["web_name"] == "Alpha" and top["why"] == "decline"
    assert top["trend"]["declining"] and top["trend"]["hard_fixtures"] == 5
    assert [c["id"] for c in res["trend_checks"]] == [13] and res["trend_checks"][0]["status"] == "ok"


def test_without_a_hard_run_he_is_only_the_only_way(run):
    res = run(hard=2, summaries={"13": _history()})
    assert res["options"][0]["tops_sold"][0]["why"] == "only_way"
    assert res["trend_checks"][0]["declining"] is False and res["trend_checks"][0]["hard_run"] is False


def test_a_failed_fetch_falls_back_to_only_the_only_way(run):
    res = run(summaries={})  # nothing injected for him: the seam returns None
    assert res["options"][0]["tops_sold"][0]["why"] == "only_way"
    assert res["trend_checks"][0]["status"] == "unavailable" and not res["trend_checks"][0]["declining"]


def test_a_fetch_that_raises_falls_back_the_same_way(run, monkeypatch):
    def boom(pid, bootstrap):
        raise ConnectionError("network down")

    monkeypatch.setattr(pt, "_fetch_summary", boom)
    res = run()
    assert [o["tops_sold"][0]["why"] for o in res["options"]] == ["only_way"]
    assert res["trend_checks"][0]["status"] == "unavailable"


def test_early_season_never_fetches_and_never_calls_a_decline(run, monkeypatch):
    calls = []
    monkeypatch.setattr(pt, "_fetch_summary", lambda pid, b: calls.append(pid))
    res = run(finished=3, summaries={"13": _history()})
    assert calls == [] and res["trend_checks"] == []
    assert res["options"][0]["tops_sold"][0]["why"] == "only_way"


def test_no_top_to_sell_means_no_call(run, monkeypatch):
    calls = []
    monkeypatch.setattr(pt, "_fetch_summary", lambda pid, b: calls.append(pid))
    res = run(owned=(), finished=10, jackson_xgi=3.0)  # Alpha is no top by price, xGI or ownership
    assert res['options'] and res['options'][0]['tops_sold'] == [] and calls == [] and res["trend_checks"] == []


def test_an_unavailable_top_is_not_fetched(run, monkeypatch):
    calls = []
    monkeypatch.setattr(pt, "_fetch_summary", lambda pid, b: calls.append(pid))
    run(owned=(13, 14), exclude_out_ids=[])
    assert 14 not in calls  # Bravo is injured: nothing to decide


def test_the_follow_up_state_is_unchanged(run):
    res = run(summaries={"13": _history()})
    assert "trend_checks" not in res["plan_state"]
