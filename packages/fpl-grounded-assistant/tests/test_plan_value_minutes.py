"""plan_to_sign values players on the minutes-shrunk xGI, and skips cameo replacements.

Regression: a downgrade with about ten minutes of football was valued on its RAW xGI/90
(a one-shot cameo reads as an elite rate), so a 3-move route "gained" value (a negative
loss, about -20) and ranked first. Synthetic data only.
"""
from __future__ import annotations

import importlib

import pytest

from fpl_grounded_assistant.plan_to_sign import plan_to_sign
from test_plan_to_sign import _bootstrap, _el, _squad_payload

pts = importlib.import_module("fpl_grounded_assistant.plan_to_sign")

CAMEO_IDS = (400, 401, 402)


def _with_cameos(*, finished_gameweeks: int):
    bs = _bootstrap()
    # Cheap midfielders with ten minutes and an absurd rate: 2.0 xGI in 10 minutes = 18 per 90.
    for pid, cost in zip(CAMEO_IDS, (40, 42, 44)):
        bs["elements"].append(_el(pid, "Cameo", f"C{pid}", f"Cameo{pid}", 2 + pid % 5, 3, cost, form=3.5, xgi=2.0, minutes=10))
    bs["events"] = [{"id": i, "is_current": False, "is_next": False, "finished": True} for i in range(1, finished_gameweeks + 1)]
    bs["events"].append({"id": finished_gameweeks + 1, "is_current": True, "is_next": False, "finished": False})
    return bs


@pytest.fixture
def run(monkeypatch):
    def go(bs, squad_bank=0, **kwargs):
        monkeypatch.setattr(pts, "get_my_squad", lambda b, gw=None: _squad_payload(squad_bank))
        return plan_to_sign(target="N.Jackson", bootstrap=bs, **kwargs)
    return go


def test_a_ten_minute_cameo_is_not_valued_on_its_raw_rate():
    ctx = pts._Context(_with_cameos(finished_gameweeks=0))
    cameo, regular = ctx.value(400), ctx.value(200)  # same form (3.5), 10 vs 900 minutes
    raw_rate_value = 3.5 + pts.XGI_WEIGHT * 18.0
    assert cameo < raw_rate_value / 5
    assert cameo < 3.5 + pts.XGI_WEIGHT * 1.0  # the shrunk rate is a fraction of one xGI/90
    # Shrinkage alone bounds the cameo's edge (about 1.3 here, against about 90 on the raw rate);
    # keeping it out of the downgrade pool is the minutes floor's job (next tests).
    assert cameo - regular < 2.0


def test_valuation_uses_the_shrunk_rate_for_a_regular_too():
    from fpl_grounded_assistant.position_score import shrink_rate_by_minutes

    ctx = pts._Context(_bootstrap())
    regular = ctx.elements[200]  # 900 minutes, 2.0 xGI -> 0.2 per 90
    expected = 3.5 + pts.XGI_WEIGHT * shrink_rate_by_minutes(0.2, 900)
    assert ctx.value(200) == pytest.approx(expected, abs=0.02)
    assert regular["minutes"] == 900


def test_cameos_are_never_offered_once_the_season_has_data(run):
    res = run(_with_cameos(finished_gameweeks=10), moves="hits", exclude_out_ids=[13, 14])
    assert res["options"], res
    bought = {tr["in"]["id"] for o in res["options"] for tr in o["transfers"]}
    assert not (bought & set(CAMEO_IDS))


def test_no_option_gains_value_by_selling(run):
    """A negative loss means the squad ends up better by selling: the signature of the bug."""
    for finished in (0, 10):
        res = run(_with_cameos(finished_gameweeks=finished), moves="hits", exclude_out_ids=[13, 14])
        assert res["options"]
        assert all(o["loss"] >= 0 for o in res["options"]), [o["loss"] for o in res["options"]]


def test_the_floor_is_the_repos_existing_one_and_only_applies_with_season_data():
    from fpl_grounded_assistant.rank_players_by_metric import per_90_minutes_floor

    with_season = pts._Context(_with_cameos(finished_gameweeks=10))
    assert with_season.minutes_floor == per_90_minutes_floor(_with_cameos(finished_gameweeks=10)) == 270
    assert pts._Context(_with_cameos(finished_gameweeks=0)).minutes_floor == 0


def test_a_normal_squad_still_ranks_the_injured_sale_first_then_by_rank_key(run):
    res = run(_with_cameos(finished_gameweeks=10), squad_bank=30, moves="one")
    options = res["options"]
    assert options[0]["transfers"][0]["out"]["web_name"] == "Bravo" and options[0]["loss"] == 0
    assert [o["rank_key"] for o in options] == sorted(o["rank_key"] for o in options)
