"""plan_to_sign: how a squad affords a named target. Synthetic data only."""
from __future__ import annotations

import pytest

import importlib

pts = importlib.import_module("fpl_grounded_assistant.plan_to_sign")  # the package re-exports the function under the same name
from fpl_grounded_assistant.plan_to_sign import plan_to_sign
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.squad_solver import SQUAD_QUOTAS, validate_squad


def _el(pid, first, second, web, team, pos, cost, *, form=3.0, status="a", chance=None, xgi=2.0, minutes=900):
    return {
        "id": pid, "first_name": first, "second_name": second, "web_name": web,
        "team": team, "element_type": pos, "now_cost": cost, "status": status,
        "chance_of_playing_next_round": chance, "news": "", "form": str(form),
        "minutes": minutes, "expected_goal_involvements": str(xgi),
        "selected_by_percent": "5.0", "total_points": 50,
    }


def _bootstrap(*, t1_heavy=False):
    els = []
    # squad
    els += [_el(1, "Gk", "One", "GkOne", 3, 1, 40), _el(2, "Gk", "Two", "GkTwo", 4, 1, 40)]
    for i, team in zip(range(3, 8), (1 if t1_heavy else 5, 6, 7, 8, 3)):
        els.append(_el(i, "Def", f"D{i}", f"Def{i}", team, 2, 50))
    for i, team in zip(range(8, 13), (1 if t1_heavy else 4, 5, 6, 7, 8)):
        els.append(_el(i, "Mid", f"M{i}", f"Mid{i}", team, 3, 70 if i == 12 else 60, form=4.0))
    els += [
        _el(13, "Fwd", "Alpha", "Alpha", 2, 4, 60, form=6.0),
        _el(14, "Fwd", "Bravo", "Bravo", 2, 4, 50, form=5.0, status="i", chance=0),
        _el(15, "Fwd", "Charlie", "Charlie", 1, 4, 45, form=2.0),
    ]
    # target and market
    els.append(_el(100, "Nicolas", "Jackson", "N.Jackson", 1, 4, 80, form=8.0))
    for k, cost in enumerate((40, 45, 50, 55, 62), start=200):
        els.append(_el(k, "Mk", f"M{k}", f"Mkt{k}", 2 + k % 5, 3, cost, form=3.5))
    for k, cost in enumerate((40, 48), start=300):
        els.append(_el(k, "Mk", f"D{k}", f"MktD{k}", 2 + k % 5, 2, cost, form=3.0))
    return {
        "elements": els,
        "teams": [{"id": i, "name": f"Club{i}", "short_name": f"C{i}"} for i in range(1, 9)],
        "events": [{"id": 10, "is_current": True, "is_next": False, "finished": False}],
        "element_types": [],
    }


def _squad_payload(bank):
    ids = list(range(1, 16))
    return {"status": "ok", "team_id": 1, "gw": 10,
            "players": [{"id": i} for i in ids], "summary": {"bank": bank}}


@pytest.fixture
def run(monkeypatch):
    def go(squad_bank=30, t1_heavy=False, **kwargs):
        monkeypatch.setattr(pts, "get_my_squad", lambda bs, gw=None: _squad_payload(squad_bank))
        return plan_to_sign(target=kwargs.pop("target", "N.Jackson"), bootstrap=_bootstrap(t1_heavy=t1_heavy), **kwargs)
    return go


def _bought_sold(res):
    bs = {e["id"]: e for e in _bootstrap()["elements"]}
    for opt in res["options"]:
        sold = sum(tr["out"]["price_tenths"] for tr in opt["transfers"])
        bought = sum(tr["in"]["price_tenths"] for tr in opt["transfers"])
        yield opt, res["bank_tenths"] + sold - bought


def test_chip_step_first_and_free_transfers_never_guessed(run):
    res = run()
    assert res["stage"] == "choose_moves"
    assert res["free_transfers"] is None and res["free_transfers_basis"] == "unknown"
    assert [o["key"] for o in res["move_options"]] == ["one", "hits"]
    assert all(o["send_text"] for o in res["move_options"])


def test_free_chip_only_with_two_or_more_known_free_transfers(run):
    assert [o["key"] for o in run(free_transfers=1)["move_options"]] == ["one", "hits"]
    assert [o["key"] for o in run(free_transfers=2)["move_options"]] == ["one", "free", "hits"]


def test_one_move_ranks_the_injured_player_first(run):
    res = run(moves="one")
    assert res["stage"] == "plan"
    first, second = res["options"][0], res["options"][1]
    assert first["transfers"][0]["out"]["web_name"] == "Bravo"
    assert first["transfers"][0]["out"]["status"] == "Injured"
    assert first["loss"] == 0 and first["unavailable_sold"] == ["Bravo"]
    assert second["transfers"][0]["out"]["web_name"] == "Alpha"
    assert second["loss"] > first["loss"]
    assert all(o["moves"] == 1 and o["hit_cost"] == 0 for o in res["options"])


def test_one_move_never_offers_a_sale_the_money_cannot_cover(run):
    names = {o["transfers"][0]["out"]["web_name"] for o in run(moves="one")["options"]}
    assert "Charlie" not in names  # 4.5 + 3.0 < 8.0


def test_money_is_integer_tenths_and_adds_up(run):
    res = run(moves="hits", squad_bank=0, exclude_out_ids=[13, 14])
    assert res["options"]
    for opt, expected in _bought_sold(res):
        assert opt["bank_after_tenths"] == expected >= 0


def test_three_per_club_blocks_a_sale_that_leaves_four(run):
    res = run(moves="one", t1_heavy=True)
    names = {o["transfers"][0]["out"]["web_name"] for o in res["options"]}
    # Three squad players are already at the target's club; only selling the
    # forward who is at that club keeps the squad legal.
    assert names == set() or names == {"Charlie"}
    assert "Alpha" not in names and "Bravo" not in names


def test_every_option_is_a_legal_squad(run):
    res = run(moves="hits", squad_bank=0, exclude_out_ids=[13, 14])
    elements = {e["id"]: e for e in _bootstrap()["elements"]}
    for opt in res["options"]:
        outs = {tr["out"]["id"] for tr in opt["transfers"]}
        after = [i for i in range(1, 16) if i not in outs] + [tr["in"]["id"] for tr in opt["transfers"]]
        assert validate_squad(after, elements, budget_tenths=10**9, quotas=SQUAD_QUOTAS) == []
        assert 100 in after


def test_hit_cost_two_moves_by_free_transfers(run):
    for ft, hit in ((1, 4), (2, 0)):
        res = run(moves="hits", free_transfers=ft, exclude_out_ids=[13, 14])
        two = [o for o in res["options"] if o["moves"] == 2]
        assert two and all(o["hit_cost"] == hit and o["hit_basis"] == "given" for o in two)


def test_hit_cost_is_labelled_assumed_when_free_transfers_unknown(run):
    res = run(moves="hits", exclude_out_ids=[13, 14])
    assert res["free_transfers"] is None
    two = [o for o in res["options"] if o["moves"] == 2]
    assert two and all(o["hit_cost"] == 4 and o["hit_basis"] == "assumed_one_free" for o in two)


def test_three_moves_cost_eight_with_one_free_and_nothing_with_three(run):
    for ft, hit in ((1, 8), (3, 0)):
        res = run(moves="hits", squad_bank=0, free_transfers=ft, exclude_out_ids=[13, 14])
        three = [o for o in res["options"] if o["moves"] == 3]
        assert three, res["options"]
        assert all(o["hit_cost"] == hit for o in three)
        assert all(o["moves"] <= 3 for o in res["options"])


def test_only_free_transfers_caps_moves_at_the_free_count(run):
    res = run(moves="free", free_transfers=2, squad_bank=10, exclude_out_ids=[13, 14])
    assert res["options"] and all(o["moves"] <= 2 and o["hit_cost"] == 0 for o in res["options"])


def test_free_mode_without_a_known_count_is_refused(run):
    assert run(moves="free")["code"] == "free_transfers_unknown"


def test_exclude_out_ids_keeps_follow_up_options_new(run):
    first = run(moves="one")
    sold = [o["transfers"][0]["out"]["id"] for o in first["options"]]
    again = run(moves="one", exclude_out_ids=sold[:1])
    assert sold[0] not in {o["transfers"][0]["out"]["id"] for o in again["options"]}
    assert again["plan_state"]["excluded_out_ids"] == sorted(sold[:1])


def test_bank_override_changes_the_answer_and_is_marked(run):
    base = run(moves="one", squad_bank=0)
    assert base["stage"] == "infeasible"
    rich = run(moves="one", squad_bank=0, bank=45.0)
    assert rich["stage"] == "plan" and rich["bank_source"] == "user" and rich["price_basis"] == "user"


def test_sell_price_override_is_used(run):
    res = run(moves="one", squad_bank=0, sell_prices=[{"player": "Alpha", "price": 8.0}])
    assert res["stage"] == "plan"
    only = res["options"][0]["transfers"][0]["out"]
    assert only["web_name"] == "Alpha" and only["price_tenths"] == 80 and res["price_basis"] == "user"


def test_plan_state_carries_what_the_follow_up_needs(run):
    state = run(moves="one")["plan_state"]
    assert state["target_id"] == 100 and state["moves"] == "one"
    assert state["planned_out_ids"] and state["shortfall_tenths"] == 50
    assert {"bank_tenths", "price_basis", "free_transfers", "excluded_out_ids"} <= state.keys()


def test_target_resolves_a_colloquial_name_and_is_deterministic(run):
    a, b = run(target="Nico Jackson", moves="one"), run(target="N.Jackson", moves="one")
    assert a["target"]["id"] == 100
    assert a["options"] == b["options"]


def test_target_already_in_the_squad(run):
    assert run(target="Alpha")["stage"] == "already_owned"


def test_passes_through_no_team_and_unknown_target(monkeypatch):
    monkeypatch.setattr(pts, "get_my_squad", lambda bs, gw=None: {"status": "no_team_connected", "code": "no_team_connected", "message": "m"})
    assert plan_to_sign(target="N.Jackson", bootstrap=_bootstrap())["status"] == "no_team_connected"
    assert plan_to_sign(target="Zzzzz Nobody", bootstrap=_bootstrap())["status"] == "not_found"


def test_bad_arguments(run):
    assert run(moves="lots")["code"] == "bad_moves"
    assert run(free_transfers=-1)["code"] == "bad_free_transfers"
    assert run(target="")["code"] == "missing_target"


@pytest.mark.parametrize("locale", ["en", "es"])
def test_renders_every_stage_in_both_languages(run, locale):
    for kwargs in ({}, {"moves": "one"}, {"moves": "hits", "squad_bank": 0, "exclude_out_ids": [13, 14]}, {"moves": "one", "squad_bank": 0}):
        res = run(**kwargs)
        text = render("plan_to_sign", res, locale=locale)
        assert text and "plan_to_sign." not in text
    assert "£" not in text


def test_the_card_says_prices_are_current_unless_the_user_gave_numbers(run):
    plan = render("plan_to_sign", run(moves="one"), locale="en")
    assert "current prices" in plan
    mine = render("plan_to_sign", run(moves="one", squad_bank=0, bank=45.0), locale="en")
    assert "current prices" not in mine and "numbers you gave" in mine


def test_chip_step_chips_are_plan_options():
    from fpl_grounded_assistant.harness import _plan_to_sign_chips

    raw = {"stage": "choose_moves", "move_options": [{"label": "1 transfer", "send_text": "q 1"}, {"label": "Use hits", "send_text": "q h"}]}
    chips = _plan_to_sign_chips("plan_to_sign", raw)
    assert [c["label"] for c in chips] == ["1 transfer", "Use hits"]
    assert all(c["kind"] == "plan_option" for c in chips)
    assert _plan_to_sign_chips("plan_to_sign", {"stage": "plan"}) is None
    assert _plan_to_sign_chips("get_my_squad", raw) is None


def test_registered_for_the_model_and_the_runner():
    from fpl_grounded_assistant.tool_schema_registry import TOOL_NAMES
    from fpl_tool_runner import TOOL_REGISTRY

    assert "plan_to_sign" in TOOL_NAMES
    assert TOOL_REGISTRY.get_spec("plan_to_sign") is not None


def test_routing_surface_without_a_model_call():
    """The deterministic half of the routing check: the model is offered the tool,
    its description names the user's own-squad question in both languages, and the
    Jev criteria carry the boundary against the neighbouring transfer tools."""
    from fpl_grounded_assistant.jev_router.criteria import CRITERIA as criteria
    from fpl_grounded_assistant.tool_schema_registry import get_offered_tool_schemas

    offered = {s.name: s for s in get_offered_tool_schemas(False)}
    description = offered["plan_to_sign"].description
    assert "how do I get Palmer with my team" in description and "cómo ficho" in description
    assert "get_transfer_advice" in description and "get_transfer_suggestion" in description
    entry = criteria["plan_to_sign"]
    assert "get_transfer_advice" in entry["not_for"]


def _rank_with(monkeypatch, plans, values, free_transfers=1):
    """Run the real ranking over hand-made plans with hand-made player values."""
    monkeypatch.setattr(pts, "get_my_squad", lambda bs, gw=None: _squad_payload(30))
    monkeypatch.setattr(pts._Context, "value", lambda self, pid: values.get(pid, 0.0))
    monkeypatch.setattr(
        pts, "_search",
        lambda ctx, **kw: [{"pairs": p, "after": [], "bank_after": 0} for p in plans],
    )
    res = plan_to_sign(target="N.Jackson", moves="hits", free_transfers=free_transfers, bootstrap=_bootstrap())
    return [[tr["out"]["id"] for tr in o["transfers"]] for o in res["options"]], res["options"]


def test_a_downgrade_that_sells_a_club_mate_can_make_a_plan_legal(run):
    # Three squad players already play for the target's club. Selling Alpha for the
    # target alone leaves four there; also selling one of those three fixes it.
    res = run(moves="hits", t1_heavy=True, free_transfers=2, exclude_out_ids=[14, 15])
    legal = [o for o in res["options"] if o["transfers"][0]["out"]["web_name"] == "Alpha"]
    assert legal, res["options"]
    assert all(o["moves"] >= 2 for o in legal)
    sold_clubs = {tr["out"]["team_short"] for o in legal for tr in o["transfers"][1:]}
    assert "C1" in sold_clubs


def test_plan_state_lists_everyone_offered_and_keeps_the_users_prices(run):
    res = run(moves="one", squad_bank=0, sell_prices=[{"player": "Alpha", "price": 8.0}])
    state = res["plan_state"]
    offered = {tr["out"]["id"] for o in res["options"] for tr in o["transfers"]}
    assert state["shown_out_ids"] == sorted(offered)
    assert state["user_sell_prices"] == [{"player": "13", "price": 8.0}]


def test_every_player_in_the_plan_carries_season_minutes(monkeypatch):
    """The prose is grounded on minutes: the target, each player sold and each player bought carry FPL's `minutes`."""
    bootstrap = _bootstrap()
    for el in bootstrap["elements"]:
        el["minutes"] = 1000 + el["id"]  # synthetic, distinct per player
    monkeypatch.setattr(pts, "get_my_squad", lambda bs, gw=None: _squad_payload(30))
    res = plan_to_sign(target="N.Jackson", moves="hits", bootstrap=bootstrap)
    assert res["target"]["minutes"] == 1100
    assert res["options"]
    for option in res["options"]:
        for tr in option["transfers"]:
            assert tr["out"]["minutes"] == 1000 + tr["out"]["id"]
            assert tr["in"]["minutes"] == 1000 + tr["in"]["id"]
