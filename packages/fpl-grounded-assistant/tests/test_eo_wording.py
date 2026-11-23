"""The EO tools' wording rules for the model: opportunity framing only (synthetic data, no LLM, no network)."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant import league_eo_tool, near_rank_eo_tool
from fpl_grounded_assistant.tool_schema_registry import LEAGUE_EO_SCHEMA, NEAR_RANK_EO_SCHEMA

BOOT = {"teams": [{"id": 1, "short_name": "T1"}],
        "elements": [{"id": i, "web_name": f"P{i}", "second_name": f"S{i}", "team": 1} for i in range(1, 6)]}
DATA = {"gw": 1, "user_rank": 10, "n_sampled": 5, "players": {
    "1": {"owned_pct": 90.0, "captain_pct": 0.0, "bench_pct": 0.0, "eo": 95.0},
    "2": {"owned_pct": 5.0, "captain_pct": 0.0, "bench_pct": 0.0, "eo": 5.0}}}
LEAGUE_DATA = {"gw": 1, "league_id": 7, "league_name": "L", "league_size": 5, "exact": True, "approx": False,
               "n_sampled": 5, "label": "exact, n=5", "players": DATA["players"]}
SQUAD = {"status": "ok", "players": [{"id": 2}]}


def notes():
    return {
        "near": near_rank_eo_tool.shape_result(DATA, BOOT, [], SQUAD)["note"],
        "league": league_eo_tool.shape_result(LEAGUE_DATA, BOOT, [], SQUAD)["note"],
    }


@pytest.mark.parametrize("which", ["near", "league"])
def test_the_note_bans_threat_words_and_names_the_groups_like_the_card(which):
    note = notes()[which]
    for word in ("amenaza", "peligro", "riesgo", "threat", "danger", "risk"):
        assert word in note.split("NEVER use threat words:")[1]
    assert "Your differential" in note and "Tu diferencial" in note
    assert "Cover Haaland" in note and "Cubrirte con Haaland" in note
    assert "`group_has`" in note and "`risks`" not in note


def test_the_group_names_match_the_card_catalogue():
    from fpl_grounded_assistant.catalogue import t

    n = notes()
    assert t("league_eo.group.risk", "en") in n["league"] and t("league_eo.group.risk", "es") in n["league"]
    assert t("near_eo.group.risk", "en") in n["near"] and t("near_eo.group.risk", "es") in n["near"]
    assert t("league_eo.group.diff", "en") in n["league"] and t("league_eo.group.diff", "es") in n["near"]


def test_the_internal_key_risks_never_reaches_the_model_and_no_tool_text_threatens():
    out = near_rank_eo_tool.shape_result(DATA, BOOT, [], SQUAD)
    assert "risks" not in out and out["group_has"]
    for text in (LEAGUE_EO_SCHEMA.description, NEAR_RANK_EO_SCHEMA.description,
                 near_rank_eo_tool.NEAR_RANK_EO_SPEC.description, league_eo_tool.LEAGUE_EO_SPEC.description):
        assert not any(w in text.lower() for w in ("hurts", "threat", "danger", "amenaza", "peligro"))


# -- user_owns on every row, the shown order, the badge tones ---------------------------------------------

def _rows(out):
    return [("top_players", r) for r in out["top_players"]] + [("group_has", r) for r in out["group_has"]] + \
        [("differentials", r) for r in out["differentials"]]


@pytest.mark.parametrize("shape", [
    lambda squad: near_rank_eo_tool.shape_result(DATA, BOOT, ["P1"], squad),
    lambda squad: league_eo_tool.shape_result(LEAGUE_DATA, BOOT, ["P1"], squad),
])
def test_every_row_says_whether_the_user_owns_the_player(shape):
    out = shape({"status": "ok", "players": [{"id": 2}]})
    rows = _rows(out) + [("named", r) for r in out["named_players"]]
    assert rows and all(isinstance(r["user_owns"], bool) for _, r in rows)
    assert all(r["user_owns"] is False for k, r in rows if k == "group_has")
    assert all(r["user_owns"] is True for k, r in rows if k == "differentials")
    assert {r["player"]: r["user_owns"] for k, r in rows if k == "top_players"} == {"P1": False, "P2": True}
    unknown = shape(None)
    assert all(r["user_owns"] is None for r in unknown["top_players"] + unknown["named_players"])


def test_the_note_states_what_user_owns_means_for_each_group():
    for note in notes().values():
        assert "`group_has` rows have user_owns=false (the user does NOT own them)" in note
        assert "`differentials` rows have user_owns=true" in note


def test_differentials_display_by_the_eo_the_card_shows_and_selection_stays_on_ownership():
    # six own players under 20 % owned: the five rarest are chosen by owned_pct, then shown by ascending EO
    players = {str(i): {"owned_pct": o, "captain_pct": 0.0, "bench_pct": 0.0, "eo": e}
               for i, (o, e) in enumerate([(3.2, 9.0), (4.8, 4.0), (0.8, 7.0), (0.8, 1.0), (12.8, 20.0), (19.0, 2.0)], 1)}
    boot = {"teams": [], "elements": [{"id": i, "web_name": f"P{i}", "second_name": f"S{i}", "team": 1} for i in range(1, 7)]}
    squad = {"status": "ok", "players": [{"id": i} for i in range(1, 7)]}
    got = near_rank_eo_tool.squad_comparison(players, squad, *near_rank_eo_tool._name_index(boot))["differentials"]
    assert [r["player"] for r in got] == ["P4", "P2", "P3", "P1", "P5"]   # P6 (19.0 % owned) is the sixth rarest: out
    assert [r["eo"] for r in got] == sorted(r["eo"] for r in got)


def test_the_cards_give_the_two_groups_different_tones():
    from fpl_grounded_assistant.atomic_tool_cards import compose_league_eo_card, compose_near_rank_eo_card
    from fpl_grounded_assistant.generic_card import generic_card_to_dict

    for compose, raw in ((compose_near_rank_eo_card, near_rank_eo_tool.shape_result(DATA, BOOT, [], SQUAD)),
                         (compose_league_eo_card, league_eo_tool.shape_result(LEAGUE_DATA, BOOT, [], SQUAD))):
        for locale in ("en", "es"):
            card = compose(raw, locale)
            tones = generic_card_to_dict(card)["badge_tones"]
            labels = {r[0] for r in card.rows}
            assert labels <= set(tones) and len(labels) == 2
            assert {tones[label] for label in labels} == {"neutral", "good"}


def test_other_cards_do_not_carry_badge_tones():
    from fpl_grounded_assistant.generic_card import GenericCardMeta, generic_card_to_dict

    plain = GenericCardMeta(accent="gray", title="x", subtitle=None, hero=None, pills=(), columns=(), rows=())
    assert generic_card_to_dict(plain)["badge_tones"] is None


# -- trimmed prose, overall-rank routing, the switch chips ----------------------------------------------------

def test_the_note_asks_for_at_most_two_short_conclusions_and_no_per_player_list():
    for note in notes().values():
        assert "AT MOST 2 short conclusions" in note and "NO per-player list" in note
        assert "no numbers the card shows" in note
        assert "Haaland es la cobertura más importante de tu liga; Isak es tu diferencial más relevante." in note
        assert "label (exact / approx.)" in note


def test_overall_rank_phrasings_route_to_near_rank_and_the_league_tool_says_it_is_mini_league_only():
    near = NEAR_RANK_EO_SCHEMA.description
    for phrase in ("overall rank", "my overall ranking", "ranking general", "mi puesto general", "clasificacion general"):
        assert phrase in near
        assert phrase not in LEAGUE_EO_SCHEMA.description.replace("never for the overall rank: 'overall rank', "
                                                                  "'ranking general', 'puesto general' and "
                                                                  "'clasificacion general' go to get_near_rank_eo", "")
    assert "MINI-LEAGUE only" in LEAGUE_EO_SCHEMA.description and "get_near_rank_eo" in LEAGUE_EO_SCHEMA.description


def test_the_spec_and_the_schema_descriptions_are_the_same_text():
    assert near_rank_eo_tool.NEAR_RANK_EO_SPEC.description is NEAR_RANK_EO_SCHEMA.description
    assert league_eo_tool.LEAGUE_EO_SPEC.description is LEAGUE_EO_SCHEMA.description


def test_main_league_name_comes_from_the_job_data_only_when_it_is_the_stored_one():
    data = {**DATA, "leagues": [{"id": 7, "name": "Friends"}, {"id": 8, "name": "Work"}]}
    boot = {**BOOT, "_my_league_id": 8}
    assert near_rank_eo_tool.shape_result(data, boot, [], SQUAD)["main_league"] == {"league_id": 8, "name": "Work"}
    assert "main_league" not in near_rank_eo_tool.shape_result(data, BOOT, [], SQUAD)
    assert "main_league" not in near_rank_eo_tool.shape_result(data, {**BOOT, "_my_league_id": 99}, [], SQUAD)


def _chips(tool, raw, locale="es"):
    from fpl_grounded_assistant.harness import _eo_switch_chips

    return _eo_switch_chips(tool, raw, locale)


def test_the_league_card_carries_one_chip_to_the_near_rank_view():
    raw = league_eo_tool.shape_result(LEAGUE_DATA, BOOT, [], SQUAD)
    assert [(c["label"], c["send_text"], c["kind"]) for c in _chips("get_league_eo", raw)] == \
        [("EO cerca de tu puesto", "EO cerca de tu puesto", "eo_switch")]
    assert _chips("get_league_eo", raw, "en")[0]["send_text"] == "EO near your rank"


def test_the_near_rank_card_carries_a_league_chip_only_when_the_main_league_is_known():
    data = {**DATA, "leagues": [{"id": 8, "name": "Work"}]}
    known = near_rank_eo_tool.shape_result(data, {**BOOT, "_my_league_id": 8}, [], SQUAD)
    assert [(c["send_text"], c["kind"]) for c in _chips("get_near_rank_eo", known)] == [("EO en Work", "eo_switch")]
    assert _chips("get_near_rank_eo", known, "en")[0]["send_text"] == "EO in Work"
    assert _chips("get_near_rank_eo", near_rank_eo_tool.shape_result(data, BOOT, [], SQUAD)) is None


@pytest.mark.parametrize("tool,raw", [
    ("get_league_eo", {"status": "computing", "eta_s": 30}),
    ("get_league_eo", {"status": "ok", "stage": "needs_league", "leagues": []}),
    ("get_near_rank_eo", {"status": "unavailable", "reason": "no_rank"}),
    ("get_my_squad", {"status": "ok", "tier": "league"}),
])
def test_no_switch_chip_unless_an_eo_card_is_shown(tool, raw):
    assert _chips(tool, raw) is None
