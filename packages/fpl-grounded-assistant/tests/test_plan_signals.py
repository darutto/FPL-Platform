"""plan_signals: top status, availability tier and the next-5 fixture window. Synthetic data only."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant import plan_signals as ps
from fpl_grounded_assistant.plan_signals import PlanSignals, ownership_is_top


def _el(pid, pos, cost, *, team=1, xgi=2.0, minutes=900, owned=5.0, status="a", chance=None, starts=None):
    el = {
        "id": pid, "web_name": f"P{pid}", "team": team, "element_type": pos, "now_cost": cost,
        "status": status, "chance_of_playing_next_round": chance, "news": "", "form": "3.0",
        "minutes": minutes, "expected_goal_involvements": str(xgi), "selected_by_percent": str(owned),
        "total_points": 40,
    }
    if starts is not None:
        el["starts"] = starts
    return el


def _bootstrap(elements, *, finished=10, fixtures=None):
    events = [{"id": i, "is_current": False, "is_next": False, "finished": True} for i in range(1, finished + 1)]
    events.append({"id": finished + 1, "is_current": True, "is_next": False, "finished": False})
    return {
        "elements": elements,
        "teams": [{"id": i, "name": f"Club{i}", "short_name": f"C{i}"} for i in range(1, 5)],
        "events": events,
        "team_fixtures": fixtures or {},
    }


def _pool(n=20, pos=3):
    """n midfielders, ids 1..n, price and xGI both rising with the id; nobody owned above the cut."""
    return [_el(i, pos, 40 + i * 5, xgi=0.5 + i * 0.5) for i in range(1, n + 1)]


def test_price_top_ten_percent_of_the_position():
    sig = PlanSignals(_bootstrap(_pool()))
    tops = {pid for pid in range(1, 21) if "price" in sig.top(pid)["reasons"]}
    assert tops == {19, 20}  # 10% of 20


def test_xgi_top_fifteen_percent_uses_the_shrunk_rate():
    sig = PlanSignals(_bootstrap(_pool()))
    tops = {pid for pid in range(1, 21) if "xgi" in sig.top(pid)["reasons"]}
    assert tops == {18, 19, 20}  # 15% of 20 -> 3


def test_a_cameo_rate_is_not_a_top_xgi():
    els = _pool() + [_el(99, 3, 45, xgi=3.0, minutes=20)]
    sig = PlanSignals(_bootstrap(els))
    assert sig.top(99) == {"is_top": False, "reasons": []}


def test_ownership_alone_makes_a_top_even_outside_the_pool():
    els = _pool() + [_el(98, 3, 45, xgi=0.0, minutes=100, owned=33.0)]
    assert PlanSignals(_bootstrap(els)).top(98) == {"is_top": True, "reasons": ["owned"]}


def test_ownership_threshold_is_inclusive_and_behind_one_function():
    assert ownership_is_top({"selected_by_percent": "20.0"})
    assert not ownership_is_top({"selected_by_percent": "19.9"})
    assert not ownership_is_top({})


def test_reasons_are_ordered_and_a_plain_player_is_not_top():
    els = _pool()
    els[-1]["selected_by_percent"] = "40.0"
    sig = PlanSignals(_bootstrap(els))
    assert sig.top(20)["reasons"] == ["price", "xgi", "owned"]
    assert sig.top(5) == {"is_top": False, "reasons": []}


def test_positions_are_pooled_separately():
    els = _pool(20, pos=3) + [_el(500, 2, 45, xgi=1.0), _el(501, 2, 40, xgi=0.9)]
    sig = PlanSignals(_bootstrap(els))
    assert sig.top(500)["is_top"]  # best of a 2-man defender pool
    assert not sig.top(10)["is_top"]


def test_ties_at_the_cutoff_are_all_in():
    els = [_el(i, 3, 100, xgi=1.0) for i in range(1, 11)]
    sig = PlanSignals(_bootstrap(els))
    assert all("price" in sig.top(i)["reasons"] for i in range(1, 11))


def test_early_season_flag_and_no_xgi_test():
    sig = PlanSignals(_bootstrap(_pool(), finished=3))
    assert sig.early_season
    assert all("xgi" not in sig.top(i)["reasons"] for i in range(1, 21))
    assert "price" in sig.top(20)["reasons"]  # price and ownership still count
    assert not PlanSignals(_bootstrap(_pool(), finished=5)).early_season


def test_empty_bootstrap_does_not_raise():
    sig = PlanSignals(_bootstrap([_el(1, 3, 50, minutes=0, xgi=0.0)], finished=0))
    assert sig.top(1) == {"is_top": False, "reasons": []}


@pytest.mark.parametrize("status,chance,tier,reason", [
    ("a", None, 2, None),
    ("a", 100, 2, None),
    ("a", 75, 1, "doubt"),
    ("d", 50, 1, "doubt"),
    ("d", 0, 0, "unavailable"),
    ("i", 0, 0, "unavailable"),
    ("i", None, 0, "unavailable"),
    ("s", None, 0, "unavailable"),
])
def test_availability_tiers(status, chance, tier, reason):
    sig = PlanSignals(_bootstrap([_el(1, 3, 50, status=status, chance=chance, starts=10)]))
    assert sig.availability(1) == {"tier": tier, "reason": reason}


def test_rotation_risk_needs_enough_finished_gameweeks():
    el = _el(1, 3, 50, starts=4)
    assert PlanSignals(_bootstrap([el], finished=10)).availability(1) == {"tier": 1, "reason": "rotation"}
    assert PlanSignals(_bootstrap([el], finished=3)).availability(1)["tier"] == 2  # too early to call
    assert PlanSignals(_bootstrap([_el(1, 3, 50, starts=8)], finished=10)).availability(1)["tier"] == 2
    assert PlanSignals(_bootstrap([_el(1, 3, 50)], finished=10)).availability(1)["tier"] == 2  # no starts field


def _fx(gw, band, opp=2):
    return {"gameweek": gw, "difficulty": band, "opponent_team": opp, "is_home": True}


def test_fixture_window_counts_hard_fixtures_over_the_next_five():
    fixtures = {
        1: [_fx(11, 5), _fx(12, 4), _fx(13, 2), _fx(14, 3), _fx(15, 4), _fx(16, 5)],  # GW16 is outside
        3: [_fx(11, 2), _fx(12, 2), _fx(13, 1), _fx(14, 2), _fx(15, 3)],
    }
    els = [_el(1, 3, 50, team=1), _el(2, 3, 50, team=3)]
    sig = PlanSignals(_bootstrap(els, fixtures=fixtures))
    hard = sig.fixtures(1)
    assert hard == {"avg_band": 3.6, "hard": 3, "games": 5}
    easy = sig.fixtures(2)
    assert easy["hard"] == 0 and easy["avg_band"] == 2.0


def test_double_gameweek_counts_both_fixtures_and_a_blank_adds_none():
    fixtures = {1: [_fx(11, 5), _fx(11, 4), _fx(13, 2)]}
    sig = PlanSignals(_bootstrap([_el(1, 3, 50, team=1)], fixtures=fixtures))
    assert sig.fixtures(1) == {"avg_band": 3.67, "hard": 2, "games": 3}


def test_no_fixture_data_gives_none_not_zero():
    sig = PlanSignals(_bootstrap([_el(1, 3, 50)]))
    assert sig.fixtures(1) == {"avg_band": None, "hard": 0, "games": 0}


def test_keepers_and_defenders_read_the_defence_axis_forwards_the_attack_axis(monkeypatch):
    seen = []
    real = ps.get_team_outlook

    def spy(bootstrap, team, axis, **kw):
        seen.append(axis)
        return real(bootstrap, team, axis, **kw)

    monkeypatch.setattr(ps, "get_team_outlook", spy)
    sig = PlanSignals(_bootstrap([_el(1, 1, 50), _el(2, 2, 50), _el(3, 3, 50), _el(4, 4, 50)]))
    for pid in (1, 2, 3, 4):
        sig.fixtures(pid)
    assert seen == ["defence", "attack"]  # same club+axis is computed once (keeper+defender, midfielder+forward)
