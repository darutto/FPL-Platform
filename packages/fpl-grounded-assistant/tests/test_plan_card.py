"""The plan_to_sign card: conclusions, the card payload and the option chips. Synthetic data only."""
from __future__ import annotations

import re

import pytest

from fpl_grounded_assistant.atomic_tool_cards import compose_plan_to_sign_card, maybe_atomic_tool_card
from fpl_grounded_assistant.plan_card import MAX_CONCLUSIONS, hero_index, option_chips, plan_conclusions
from fpl_grounded_assistant.plan_followup import followup_args, option_pick, sanitize_plan_state
from fpl_grounded_assistant.renderer import render
from test_plan_followup import GOOD, LINES, chat  # noqa: F401  (the /ask fixture and the state it uses)


def _transfer(out_id, out, inn, *, status="a", chance=None, out_price=8.0, in_price=7.0):
    return {
        "out": {"id": out_id, "web_name": out, "team_short": "C2", "price": out_price, "status_code": status,
                "chance_of_playing": chance},
        "in": {"id": 900 + out_id, "web_name": inn, "team_short": "C3", "price": in_price},
        "role": "target",
    }


def _option(out="Alpha", *, moves=1, hit=0, bank=2.6, tops=(), sold=None, status="a", chance=None, basis="given"):
    return {
        "moves": moves, "hit_cost": hit, "hit_basis": basis, "bank_after": bank, "bank_after_tenths": int(bank * 10),
        "transfers": [_transfer(13, out, "N.Jackson", status=status, chance=chance)],
        "tops_sold": list(tops),
        "sold": sold if sold is not None else [{"id": 13, "web_name": out, "hard_fixtures": 0, "availability": None, "set_pieces": 0}],
    }


def _raw(*options, moves="one", price_basis="current", **extra):
    return {
        "status": "ok", "stage": "plan", "moves": moves, "price_basis": price_basis,
        "target": {"web_name": "N.Jackson", "position": "FWD", "team_short": "C1", "price": 7.2},
        "bank": 0.5, "shortfall_tenths": 67, "shortfall": 6.7, "options": list(options), **extra,
    }


# ---------------------------------------------------------------------------
# conclusions
# ---------------------------------------------------------------------------

def test_only_way_names_the_top_and_the_target():
    raw = _raw(_option("Isak", tops=[{"id": 13, "web_name": "Isak", "reasons": ["price"], "why": "only_way"}]))
    assert plan_conclusions(raw, "en") == ["Isak is a top player: selling him is the only way to fund N.Jackson."]
    assert plan_conclusions(raw, "es") == ["Isak es top: su venta es la única forma de pagar a N.Jackson."]


def test_only_way_is_said_per_player_only_when_every_option_sells_that_player():
    isak = {"id": 13, "web_name": "Isak", "reasons": ["price"], "why": "only_way"}
    other = {**_option("Haaland"), "tops_sold": [{"id": 13, "web_name": "Isak", "reasons": ["price"], "why": "only_way"}]}
    raw = _raw(_option("Isak", tops=[isak]), other)
    assert plan_conclusions(raw, "en") == ["Isak is a top player: selling him is the only way to fund N.Jackson."]


def test_when_every_option_sells_some_top_but_not_the_same_one_there_is_one_general_line():
    isak = {"id": 13, "web_name": "Isak", "reasons": ["price"], "why": "only_way"}
    haaland = {"id": 14, "web_name": "Haaland", "reasons": ["price"], "why": "only_way"}
    raw = _raw(_option("Isak", tops=[isak]), _option("Haaland", tops=[haaland]))
    assert plan_conclusions(raw, "en") == ["Every way to fund N.Jackson sells a top player."]
    assert plan_conclusions(raw, "es") == ["Toda forma de pagar a N.Jackson pasa por vender a un top."]
    both = _option("Isak", tops=[isak, haaland], moves=2)
    # Haaland is in every option, so he really is the only way; Isak is not. One general line, one per-player line.
    assert plan_conclusions(_raw(both, _option("Haaland", tops=[haaland])), "en") == [
        "Every way to fund N.Jackson sells a top player.",
        "Haaland is a top player: selling him is the only way to fund N.Jackson.",
    ]


def test_an_out_top_says_what_fpl_says():
    top = [{"id": 13, "web_name": "Semenyo", "reasons": ["price"], "why": "unavailable"}]
    sold = [{"id": 13, "web_name": "Semenyo", "hard_fixtures": 0, "availability": "unavailable", "set_pieces": 0}]
    raw = _raw(_option("Semenyo", tops=top, sold=sold, status="i", chance=0))
    assert plan_conclusions(raw, "en") == ["Semenyo: FPL lists him as out."]
    assert plan_conclusions(raw, "es") == ["Semenyo: FPL lo da como baja."]


def test_a_doubt_gives_the_chance_fpl_gives():
    sold = [{"id": 13, "web_name": "Raya", "hard_fixtures": 0, "availability": "doubt", "set_pieces": 0}]
    raw = _raw(_option("Raya", sold=sold, status="d", chance=75))
    assert plan_conclusions(raw, "en") == ["Raya: FPL gives him a 75% chance of playing."]
    assert plan_conclusions(raw, "es") == ["Raya: FPL le da un 75% de jugar."]


def test_a_decline_is_the_short_recent_against_season_comparison_with_dot_decimals():
    trend = {"form_recent": 2.0, "form_season": 5.75, "hard_fixtures": 4}
    top = [{"id": 13, "web_name": "Alpha", "reasons": ["owned"], "why": "decline", "trend": trend}]
    raw = _raw(_option("Alpha", tops=top))
    english, spanish = plan_conclusions(raw, "en")[0], plan_conclusions(raw, "es")[0]
    assert english.startswith("Alpha is slipping: 2.0 pts a game in his last 3 against 5.") and "with 4 hard fixtures ahead" in english
    assert "2.0 pts por partido en sus últimos 3" in spanish and "4 partidos difíciles" in spanish
    assert not re.search(r"\d,\d", spanish)


def test_a_hard_run_and_few_starts_for_non_tops():
    sold = [{"id": 13, "web_name": "Alpha", "hard_fixtures": 4, "availability": None, "set_pieces": 0},
            {"id": 12, "web_name": "Mid12", "hard_fixtures": 0, "availability": "rotation", "set_pieces": 0}]
    raw = _raw(_option("Alpha", sold=sold))
    assert plan_conclusions(raw, "en") == ["Alpha has 4 hard fixtures in the next 5.", "Mid12 has had few starts this season."]
    assert plan_conclusions(raw, "es") == ["Alpha tiene 4 partidos difíciles en los próximos 5.",
                                           "Mid12: pocos minutos de titular esta temporada."]


def test_never_the_word_rotating():
    sold = [{"id": 13, "web_name": "Alpha", "hard_fixtures": 0, "availability": "rotation", "set_pieces": 0}]
    for locale in ("en", "es"):
        text = " ".join(plan_conclusions(_raw(_option("Alpha", sold=sold)), locale)).lower()
        assert "rotat" not in text and "rotaci" not in text


def test_hits_that_give_no_better_plan_say_so_plainly():
    one = _option("Isak")
    assert plan_conclusions(_raw(one, moves="hits"), "en")[0] == "Hits don't give a better plan."
    assert plan_conclusions(_raw(one, moves="hits"), "es")[0] == "Con hits no hay un plan mejor."
    assert plan_conclusions(_raw(one, moves="free"), "es")[0] == "Con tus traspasos gratis no hay un plan mejor."
    assert plan_conclusions(_raw(one, moves="one"), "en") == []  # the user asked for one move: nothing to say
    two = {**_option("Isak"), "moves": 2}
    assert plan_conclusions(_raw(one, two, moves="hits"), "en") == []  # a multi-move plan exists


def test_at_most_three_lines_in_priority_order():
    tops = [{"id": 13, "web_name": "A", "reasons": ["price"], "why": "only_way"},
            {"id": 12, "web_name": "B", "reasons": ["price"], "why": "only_way"}]
    sold = [{"id": 13, "web_name": "A", "hard_fixtures": 5, "availability": None, "set_pieces": 0},
            {"id": 12, "web_name": "B", "hard_fixtures": 5, "availability": None, "set_pieces": 0},
            {"id": 11, "web_name": "C", "hard_fixtures": 5, "availability": "doubt", "set_pieces": 0}]
    lines = plan_conclusions(_raw(_option("A", tops=tops, sold=sold, moves=2), moves="hits"), "en")
    assert len(lines) == MAX_CONCLUSIONS == 3
    assert lines[0].startswith("A is a top") and lines[1].startswith("B is a top")


def test_a_plan_with_nothing_to_say_has_no_lines():
    assert plan_conclusions(_raw(_option("Alpha")), "en") == []
    assert plan_conclusions({"options": []}, "en") == []


# ---------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------

def test_the_card_carries_the_swaps_the_leftover_money_and_the_conclusions():
    top = [{"id": 13, "web_name": "Isak", "reasons": ["price"], "why": "only_way"}]
    card = compose_plan_to_sign_card(_raw(_option("Isak", tops=top, moves=1, hit=0, bank=2.6), moves="one"), "en")
    assert card.title == "Sign N.Jackson"
    assert card.subtitle == "FWD · C1 · 7.2m · bank 0.5m · 6.7m to find"
    assert card.hero.value == "2.6m" and card.hero.label == "left in the bank"
    assert [p.label for p in card.pills] == ["1 move", "no hit"] and card.pills[1].tone == "good"
    assert [c.header for c in card.columns] == ["Out", "In", "Price"]
    assert card.rows == (("Isak · C2", "N.Jackson · C3", "8.0 → 7.0"),)
    assert all(len(row) == len(card.columns) for row in card.rows)
    lines = card.footer.split("\n")
    assert lines[0].startswith("Isak is a top player") and lines[-1].startswith("Current prices")  # one option: his alone


def test_spanish_card_uses_te_sobran_and_dot_decimals():
    card = compose_plan_to_sign_card(_raw(_option("Isak", moves=2, hit=4, bank=2.1, basis="assumed_one_free")), "es")
    assert card.title == "Fichar a N.Jackson" and card.hero.label == "te sobran" and card.hero.value == "2.1m"
    assert [p.label for p in card.pills] == ["2 traspasos", "hit −4 (suponiendo 1 gratis)"] and card.pills[1].tone == "warn"
    assert "faltan 6.7m" in card.subtitle and "," not in card.subtitle


def test_the_users_own_prices_drop_the_price_note():
    card = compose_plan_to_sign_card(_raw(_option("Isak"), price_basis="user"), "en")
    assert card.footer is None


def test_only_a_plan_stage_with_options_has_a_card():
    assert compose_plan_to_sign_card({"status": "ok", "stage": "choose_moves"}, "en") is None
    assert compose_plan_to_sign_card({"status": "ok", "stage": "infeasible", "options": []}, "en") is None
    assert compose_plan_to_sign_card({"status": "error"}, "en") is None
    assert compose_plan_to_sign_card({"status": "ok", "stage": "plan", "options": [{"bad": 1}]}, "en") is None  # never raises


def test_the_tool_has_its_composer_registered():
    card = maybe_atomic_tool_card("plan_to_sign", _raw(_option("Isak")), None, "en")
    assert card is not None and card.title == "Sign N.Jackson"


def test_focus_makes_another_option_the_hero():
    a, b = _option("Isak", bank=2.6), _option("Haaland", bank=9.1)
    raw = _raw(a, b, focus=2)
    assert hero_index(raw) == 1
    assert compose_plan_to_sign_card(raw, "en").rows[0][0].startswith("Haaland")
    assert hero_index(_raw(a, b, focus=9)) == 0 and hero_index(_raw(a, b, focus="2")) == 0 and hero_index(_raw(a, b)) == 0


def test_the_text_answer_repeats_the_conclusions_under_the_hero_option():
    top = [{"id": 13, "web_name": "Isak", "reasons": ["price"], "why": "only_way"}]
    text = render("plan_to_sign", _raw(_option("Isak", tops=top)), locale="en")
    assert "  → Isak is a top player: selling him is the only way to fund N.Jackson." in text


# ---------------------------------------------------------------------------
# chips
# ---------------------------------------------------------------------------

def test_options_other_than_the_hero_are_chips_with_their_own_names():
    a, b, c = _option("Isak"), _option("Haaland"), {**_option("Evan"), "moves": 2}
    c["transfers"].append(_transfer(12, "Cherki", "LeFee"))
    chips = option_chips(_raw(a, b, c), "en")
    assert chips == [
        {"label": "Sell Haaland", "send_text": "Show option 2"},
        {"label": "Sell Evan + Cherki", "send_text": "Show option 3"},
    ]
    assert option_chips(_raw(a, b, c, focus=3), "es") == [
        {"label": "Vender a Isak", "send_text": "Muéstrame la opción 1"},
        {"label": "Vender a Haaland", "send_text": "Muéstrame la opción 2"},
    ]
    assert option_chips(_raw(a), "en") == []


@pytest.mark.parametrize("text,n", [
    ("Show option 2", 2), ("Muéstrame la opción 3", 3), ("show me option 1 please", 1), ("opcion 2", 2),
])
def test_an_option_tap_is_recognised(text, n):
    assert option_pick(text) == n


@pytest.mark.parametrize("text", [
    "", "who else can I sell", "show option 4", "option", "show me options", "a" * 80 + " option 2",
    "How do I get Haaland? Plan: 1 transfer",
])
def test_everything_else_is_not_an_option_tap(text):
    assert option_pick(text) is None


def test_an_option_tap_keeps_the_options_already_shown():
    state = sanitize_plan_state(GOOD)
    assert set(followup_args(state, keep_shown=True)["exclude_out_ids"]) == set(state["excluded_out_ids"])
    assert set(followup_args(state)["exclude_out_ids"]) >= set(state["shown_out_ids"])


# ---------------------------------------------------------------------------
# through POST /ask: the card, the chips and the tap (no model call on the tap)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("locale", ["en", "es"])
def test_a_plan_turn_carries_a_card_and_option_chips_and_a_tap_answers_without_the_model(chat, locale):
    post, script = chat
    first = post(LINES[locale][0], locale)
    hits_chip = first["suggestions"][-1]
    plan = post(hits_chip["send_text"], locale)
    assert plan["generic_card"] is not None and plan["generic_card"]["rows"]
    chips = plan["suggestions"]
    assert chips and all(c["kind"] == "plan_option" for c in chips)
    asked = len(script.calls)

    tapped = post(chips[0]["send_text"], locale, plan_state=plan["plan_state"])
    assert len(script.calls) == asked, "tapping an option must not reach the model"
    assert tapped["outcome"] == "ok" and tapped["generic_card"] is not None
    assert tapped["generic_card"]["rows"] != plan["generic_card"]["rows"]  # another option is now the hero
    assert tapped["plan_state"]["target_id"] == plan["plan_state"]["target_id"]
    assert sorted(tapped["plan_state"]["shown_out_ids"]) == sorted(plan["plan_state"]["shown_out_ids"])
    tapped_chips = tapped["suggestions"]
    assert len(tapped_chips) == len(chips) and tapped_chips[0]["label"] != chips[0]["label"]
    assert not re.search(r"\d,\d", tapped["final_text"])  # dot decimals in both languages
