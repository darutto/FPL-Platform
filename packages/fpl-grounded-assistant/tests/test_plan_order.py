"""plan_to_sign orders options by football criteria, and does not sell tops lightly. Synthetic data only.

Order: availability sold-minus-bought, then fixtures, then performance, then unspent money, then
hits / moves / ids. A top is sold only when he is unavailable (or in decline), or when no plan without
a top exists; rotation alone never frees one.
"""
from __future__ import annotations

import importlib

import pytest

from fpl_grounded_assistant.plan_to_sign import plan_to_sign
from test_plan_to_sign import _bootstrap, _squad_payload

pts = importlib.import_module("fpl_grounded_assistant.plan_to_sign")


def _by_id(bs, pid):
    return next(e for e in bs["elements"] if e["id"] == pid)


@pytest.fixture
def run(monkeypatch):
    def go(*, squad_bank=30, owned=(), finished=0, tweak=None, **kwargs):
        bs = _bootstrap()
        for pid in owned:
            _by_id(bs, pid)["selected_by_percent"] = "40.0"
        bs["events"] = [{"id": i, "is_current": False, "is_next": False, "finished": True} for i in range(1, finished + 1)]
        bs["events"].append({"id": finished + 1, "is_current": True, "is_next": False, "finished": False})
        if tweak:
            tweak(bs)
        monkeypatch.setattr(pts, "get_my_squad", lambda b, gw=None: _squad_payload(squad_bank))
        kwargs.setdefault("moves", "one")
        return plan_to_sign(target="N.Jackson", bootstrap=bs, **kwargs)
    return go


def _sold(res):
    return [[tr["out"]["web_name"] for tr in o["transfers"]] for o in res["options"]]


# ---------------------------------------------------------------------------
# the top gate
# ---------------------------------------------------------------------------

def test_a_top_is_not_offered_while_another_sale_works(run):
    res = run(owned=[13])  # Alpha is owned by 40%: a top
    assert _sold(res) == [["Bravo"]]


def test_a_top_is_offered_when_it_is_the_only_way_and_says_so(run):
    res = run(owned=[13], exclude_out_ids=[14])
    assert _sold(res) == [["Alpha"]]
    top = res["options"][0]["tops_sold"][0]
    assert top["web_name"] == "Alpha" and top["reasons"] == ["owned"] and top["why"] == "only_way"


def test_an_unavailable_top_is_a_justified_sale(run):
    res = run(owned=[13, 14])  # the injured Bravo is a top too
    first = res["options"][0]
    assert first["transfers"][0]["out"]["web_name"] == "Bravo"
    assert first["tops_sold"] == [{"id": 14, "web_name": "Bravo", "reasons": ["owned"], "why": "unavailable"}]
    assert _sold(res)[1:] == []  # Alpha stays out: he is a top and Bravo already works


def test_rotation_alone_does_not_free_a_top(run):
    def rotation(bs):
        _by_id(bs, 13)["starts"] = 3  # 3 of 10: reads as a rotation risk on the season-long share
        _by_id(bs, 15)["starts"] = 10
        _by_id(bs, 14)["starts"] = 10

    res = run(owned=[13], finished=10, tweak=rotation, exclude_out_ids=[14])
    assert [o["transfers"][0]["out"]["web_name"] for o in res["options"]] == ["Alpha"]
    assert res["options"][0]["tops_sold"][0]["why"] == "only_way"  # not "rotation"


def test_a_decline_frees_a_top_but_never_early_in_the_season(monkeypatch, run):
    real_init = pts._Context.__init__

    def init(self, bootstrap):
        real_init(self, bootstrap)
        self.declining = {13}

    monkeypatch.setattr(pts._Context, "__init__", init)
    late = run(owned=[13, 14], finished=10, exclude_out_ids=[14])
    assert late["options"][0]["tops_sold"][0]["why"] == "decline"
    early = run(owned=[13], finished=2, exclude_out_ids=[14])
    assert early["options"][0]["tops_sold"][0]["why"] == "only_way"


def test_a_non_top_has_no_why_and_no_tops_sold(run):
    res = run()
    assert all(o["tops_sold"] == [] or all("why" in t for t in o["tops_sold"]) for o in res["options"])
    assert any(o["tops_sold"] == [] for o in res["options"])


# ---------------------------------------------------------------------------
# the order
# ---------------------------------------------------------------------------

def _rank(monkeypatch, plans, *, values=None, bands=None, tiers=None, bank_after=None, free_transfers=1):
    """Run the real ranking over hand-made plans, with hand-made values, fixture bands and availability."""
    values, bands, tiers, bank_after = values or {}, bands or {}, tiers or {}, bank_after or {}
    monkeypatch.setattr(pts, "get_my_squad", lambda b, gw=None: _squad_payload(30))
    monkeypatch.setattr(pts._Context, "value", lambda self, pid: values.get(pid, 1.0))
    monkeypatch.setattr(
        pts.PlanSignals, "fixtures",
        lambda self, pid: {"avg_band": bands.get(pid, 3.0), "hard": 0, "games": 5},
    )
    monkeypatch.setattr(
        pts.PlanSignals, "availability",
        lambda self, pid: {"tier": tiers.get(pid, 2), "reason": None},
    )
    monkeypatch.setattr(
        pts, "_search",
        lambda ctx, **kw: [{"pairs": p, "after": [], "bank_after": bank_after.get(tuple(p), 0)} for p in plans],
    )
    res = plan_to_sign(target="N.Jackson", moves="hits", free_transfers=free_transfers, bootstrap=_bootstrap())
    return [[tr["out"]["id"] for tr in o["transfers"]] for o in res["options"]], res["options"]


def test_availability_beats_everything_below_it(monkeypatch):
    healthy, doubtful = [(13, 100)], [(15, 100)]
    # selling the doubtful player is worse on performance and fixtures, and still wins
    order, _ = _rank(monkeypatch, [healthy, doubtful], values={13: 0.5, 15: 4.0}, bands={13: 5.0, 15: 1.0}, tiers={15: 1})
    assert order[0] == [15]


def test_fixtures_beat_performance(monkeypatch):
    hard_run, easy_run = [(13, 100)], [(15, 100)]
    order, _ = _rank(monkeypatch, [easy_run, hard_run], values={13: 3.0, 15: 1.0}, bands={13: 4.5, 15: 2.0})
    assert order[0] == [13]  # selling the hard run wins although it gives up more production


def test_performance_decides_when_fixtures_tie(monkeypatch):
    order, _ = _rank(monkeypatch, [[(13, 100)], [(15, 100)]], values={13: 3.0, 15: 1.0})
    assert order[0] == [15]


def test_a_fixture_difference_inside_a_bucket_is_a_tie(monkeypatch):
    order, _ = _rank(monkeypatch, [[(13, 100)], [(15, 100)]], values={13: 3.0, 15: 1.0}, bands={13: 3.2, 15: 3.0})
    assert order[0] == [15]  # 0.2 apart: performance decides


def test_set_pieces_given_up_count_against_a_plan(monkeypatch):
    monkeypatch.setattr(pts, "set_piece_count", lambda el: 2 if el["id"] == 15 else 0)
    order, options = _rank(monkeypatch, [[(13, 100)], [(15, 100)]], values={13: 1.2, 15: 1.0})
    assert order[0] == [13]  # 15 is cheaper to lose on value, but he takes the penalties and corners
    by_out = {o["transfers"][0]["out"]["id"]: o for o in options}
    assert by_out[15]["signals"]["set_pieces_given"] == 2 and by_out[13]["signals"]["set_pieces_given"] == 0


def test_less_unspent_money_wins_a_tie_on_football(monkeypatch):
    a, b = [(13, 100)], [(15, 100)]
    order, _ = _rank(monkeypatch, [a, b], bank_after={tuple(a): 40, tuple(b): 5})
    assert order[0] == [15]  # 0.5m left over against 4.0m: do not over-sell


def test_hits_then_moves_then_ids_break_the_last_ties(monkeypatch):
    order, _ = _rank(monkeypatch, [[(15, 100)], [(13, 100)]])
    assert order == [[13], [15]]  # everything equal: the lower id first


def test_an_extra_move_is_dropped_when_it_only_saves_production(monkeypatch):
    one, three = [(13, 100)], [(15, 100), (12, 200), (11, 201)]
    order, options = _rank(monkeypatch, [three, one], values={13: 2.0, 15: 1.9, 12: 3.0, 11: 3.0, 200: 3.0, 201: 3.0})
    assert order == [[13]]
    assert options[0]["hit_cost"] == 0


def test_an_extra_move_survives_when_it_sells_an_unavailable_player(monkeypatch):
    one, two = [(13, 100)], [(13, 100), (11, 200)]
    order, options = _rank(monkeypatch, [one, two], tiers={11: 0}, values={11: 0.0, 200: 0.5})
    assert order[0] == [13, 11]
    assert options[0]["signals"]["avail_net"] < options[1]["signals"]["avail_net"]
    assert options[0]["hit_cost"] == 4  # still shown


def test_an_extra_move_survives_when_it_clearly_improves_the_fixtures(monkeypatch):
    one, two = [(13, 100)], [(13, 100), (11, 200)]
    order, _ = _rank(monkeypatch, [one, two], bands={11: 5.0, 200: 2.0})
    assert order[0] == [13, 11]


def test_options_carry_the_signals_and_the_rank_key(run):
    res = run()
    for option in res["options"]:
        assert set(option["signals"]) == {"avail_net", "fixture_gain", "set_pieces_given", "performance"}
        assert len(option["rank_key"]) == 4
        assert "score" not in option and "points_given_up" not in option
    assert [o["rank_key"] for o in res["options"]] == sorted(o["rank_key"] for o in res["options"])


# ---------------------------------------------------------------------------
# the fixture window starts at the first gameweek a transfer can affect
# ---------------------------------------------------------------------------

def _window_bootstrap(deadline, *, is_current=True):
    fixtures = {1: [{"gameweek": 10, "difficulty": 5, "opponent_team": 2, "is_home": True}]
                + [{"gameweek": gw, "difficulty": 2, "opponent_team": 2, "is_home": True} for gw in range(11, 17)]}
    return {
        "elements": [], "teams": [{"id": i, "short_name": f"C{i}", "name": f"C{i}"} for i in (1, 2)],
        "events": [
            {"id": 10, "is_current": is_current, "is_next": not is_current, "finished": False, "deadline_time": deadline},
            {"id": 11, "is_current": False, "is_next": is_current, "finished": False, "deadline_time": "2099-01-01T11:00:00Z"},
        ],
        "team_fixtures": fixtures,
    }


def test_the_window_skips_the_gameweek_whose_deadline_has_passed():
    from fpl_grounded_assistant.plan_signals import PlanSignals

    el = {"id": 1, "team": 1, "element_type": 4, "minutes": 0}
    past = _window_bootstrap("2020-01-01T11:00:00Z")
    past["elements"] = [el]
    signals = PlanSignals(past)
    assert signals.window_gw == 11
    assert signals.fixtures(1) == {"avg_band": 2.0, "hard": 0, "games": 5}  # GW11-15, the hard GW10 is not counted

    future = _window_bootstrap("2099-01-01T11:00:00Z")
    future["elements"] = [el]
    signals = PlanSignals(future)
    assert signals.window_gw == 10
    assert signals.fixtures(1) == {"avg_band": 2.6, "hard": 1, "games": 5}  # GW10-14 still counts the hard one


def test_value_games_factor_uses_the_same_first_gameweek(monkeypatch):
    past = _window_bootstrap("2020-01-01T11:00:00Z")
    past["elements"] = [{"id": 1, "team": 1, "element_type": 4, "minutes": 900, "now_cost": 50, "form": "3", "status": "a",
                         "expected_goal_involvements": "2.0"}]
    assert pts._Context(past).window_gw == 11


def test_a_top_flagged_only_as_rotation_does_not_count_as_an_availability_gain(monkeypatch):
    """Selling a rotation-tier top must not make an extra move look better on availability."""
    monkeypatch.setattr(
        pts.PlanSignals, "availability",
        lambda self, pid: {"tier": 1, "reason": "rotation"} if pid == 11 else {"tier": 2, "reason": None},
    )
    monkeypatch.setattr(pts.PlanSignals, "top", lambda self, pid: {"is_top": pid == 11, "reasons": ["owned"] if pid == 11 else []})
    monkeypatch.setattr(pts.PlanSignals, "fixtures", lambda self, pid: {"avg_band": 3.0, "hard": 0, "games": 5})
    monkeypatch.setattr(pts, "get_my_squad", lambda b, gw=None: _squad_payload(30))
    monkeypatch.setattr(pts, "_search", lambda ctx, **kw: [
        {"pairs": [(13, 100)], "after": [], "bank_after": 0},
        {"pairs": [(13, 100), (11, 200)], "after": [], "bank_after": 0},
    ])
    res = plan_to_sign(target="N.Jackson", moves="hits", free_transfers=1, bootstrap=_bootstrap())
    assert [o["moves"] for o in res["options"]] == [1]  # the extra move gains nothing: dropped


def test_an_extra_move_needs_a_full_point_of_fixture_gain(monkeypatch):
    one, two = [(13, 100)], [(13, 100), (11, 200)]
    # gain: one-move 3.0; two-move 3.0 + 3.0 (band 11) - 2.2 (band 200) = 3.8 -> +0.8: not enough
    order, _ = _rank(monkeypatch, [one, two], bands={11: 3.0, 200: 2.2})
    assert order == [[13]]
    # +1.0 exactly: enough
    order, _ = _rank(monkeypatch, [one, two], bands={11: 3.0, 200: 2.0})
    assert order[0] == [13, 11]


def test_a_three_move_plan_needs_two_points_over_the_one_move_plan(monkeypatch):
    one, three = [(13, 100)], [(13, 100), (11, 200), (10, 201)]
    order, _ = _rank(monkeypatch, [one, three], bands={11: 3.0, 200: 2.0, 10: 3.0, 201: 2.5})  # +1.5 over 2 extra
    assert order == [[13]]
    order, _ = _rank(monkeypatch, [one, three], bands={11: 4.0, 200: 2.0, 10: 3.0, 201: 2.0})  # +3.0 over 2 extra
    assert order[0] == [13, 11, 10]


def test_an_avoidable_oversell_is_dropped_from_multi_move_plans(monkeypatch):
    lean, fat = [(13, 100), (11, 200)], [(13, 100), (10, 201)]
    order, options = _rank(
        monkeypatch, [lean, fat], tiers={11: 0, 10: 0}, bank_after={tuple(lean): 3, tuple(fat): 100},
    )
    assert order == [[13, 11]]


def test_the_oversell_guard_keeps_everything_when_no_multi_move_plan_is_lean(monkeypatch):
    a, b = [(13, 100), (11, 200)], [(13, 100), (10, 201)]
    order, _ = _rank(monkeypatch, [a, b], tiers={11: 0, 10: 0}, bank_after={tuple(a): 40, tuple(b): 90})
    assert len(order) == 2


def test_one_move_plans_are_never_dropped_for_leaving_money(monkeypatch):
    big, lean = [(13, 100)], [(15, 100)]
    order, _ = _rank(monkeypatch, [big, lean], bank_after={tuple(big): 91, tuple(lean): 26})
    assert sorted(order) == [[13], [15]]
