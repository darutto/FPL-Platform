"""get_position_changes: who held the usual slot in the matches without him (text ES/EN, card, schema). No network."""
from __future__ import annotations

import copy

from fpl_grounded_assistant.atomic_tool_cards import compose_position_changes_card
from fpl_grounded_assistant.position_changes_tool import run_position_changes
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.tool_schema_registry import GET_POSITION_CHANGES_SCHEMA

from test_b4_position_changes_tool import BOOTSTRAP, FPL_FIXTURES, FakeHandle, _tables


def _result():
    return run_position_changes({"player": "João Pedro Junqueira de Jesus"}, copy.deepcopy(BOOTSTRAP),
                                handle=FakeHandle(_tables()), fetch_fixtures=lambda: FPL_FIXTURES)


def _out(**cover):
    base = {"status": "ok", "usual_slot": {"detailed_position": "Centre Forward", "side": "centre"}, "starts_used": 4,
            "matches_without": 3, "matches_covered": 3, "closest_used": False, "small_sample": False, "claim_status": "observed",
            "occupants": [{"player": {"web_name": "Delap"}, "count": 2}, {"player": {"web_name": "Nkunku"}, "count": 1}]}
    base.update(cover)
    matches = [
        {"gameweek": 5, "opponent": "EVE", "is_home": True, "lineup_status": "confirmed", "player_status": "bench",
         "slot": None, "slot_occupants": [{"player": {"web_name": "Delap"}, "match": "exact", "claim_status": "observed"}]},
        {"gameweek": 6, "opponent": "LIV", "is_home": False, "lineup_status": "confirmed", "player_status": "not_listed",
         "slot": None, "slot_occupants": [{"player": {"web_name": "Nkunku"}, "match": "closest", "claim_status": "observed"}]},
        {"gameweek": 7, "opponent": "ARS", "is_home": True, "lineup_status": "confirmed", "player_status": "not_listed",
         "slot": None, "slot_occupants": []},
    ]
    return {"status": "ok", "player": {"web_name": "João Pedro", "team_short": "CHE"}, "matches": matches,
            "sample": {"matches_with_stored_lineup": 7, "small_sample": False}, "slot_cover": base}


def test_text_spanish_names_the_slot_from_the_role_and_has_no_cause():
    text = render("get_position_changes", _out(), "es")
    assert "En los 3 partidos sin João Pedro, la casilla de delantero centro quedó ocupada por Delap (2) y Nkunku (1)." in text
    assert "casilla: Delap" in text and "casilla más parecida: Nkunku" in text
    assert "sustitu" not in text.lower() and "voseo" not in text


def test_text_english_is_neutral():
    text = render("get_position_changes", _out(), "en")
    assert "In the 3 matches without João Pedro, the centre forward slot was held by Delap (2) and Nkunku (1)." in text
    assert "slot: Delap" in text and "closest slot: Nkunku" in text
    assert "replac" not in text.lower()


def test_a_left_back_slot_is_not_called_nine():
    out = _out(usual_slot={"detailed_position": "Left Back", "side": "left"})
    assert "la casilla de lateral izquierdo" in render("get_position_changes", out, "es")
    assert "the left back slot" in render("get_position_changes", out, "en")


def test_one_match_is_said_as_one_match():
    out = _out(matches_without=1, small_sample=True, occupants=[{"player": {"web_name": "Delap"}, "count": 1}])
    es, en = render("get_position_changes", out, "es"), render("get_position_changes", out, "en")
    assert "En el partido sin João Pedro, la casilla de delantero centro quedó ocupada por Delap." in es
    assert "Muestra pequeña: 1 partido sin João Pedro" in es
    assert "In the match without João Pedro, the centre forward slot was held by Delap." in en
    assert "Small sample: 1 match without João Pedro" in en


def test_closest_and_no_usual_slot_are_said():
    assert "cambió la formación" in render("get_position_changes", _out(closest_used=True), "es")
    assert "formation changed" in render("get_position_changes", _out(closest_used=True), "en")
    none = _out(status="no_usual_slot", reason="too_few_starts", starts_used=1, occupants=[])
    assert "Aún no hay casilla habitual medida para João Pedro (titularidades guardadas: 1)" in render("get_position_changes", none, "es")
    assert "No usual slot measured yet for João Pedro (stored starts: 1)" in render("get_position_changes", none, "en")


def test_card_note_carries_the_slot():
    card = compose_position_changes_card(_out(), "es")
    notes = [row[-1] for row in card.rows]
    assert notes[0] == "casilla: Delap" and notes[1] == "casilla más parecida: Nkunku"
    assert "casilla" not in notes[2]
    assert [row[-1] for row in compose_position_changes_card(_out(), "en").rows][0] == "slot: Delap"


def test_rows_without_slot_data_render_exactly_as_before():
    out = _out()
    for m in out["matches"]:
        m.pop("slot_occupants")
    out.pop("slot_cover")
    text = render("get_position_changes", out, "es")
    assert "casilla:" not in text and "ocupada por" not in text and "slot" not in text


def test_the_tool_surfaces_slot_cover_and_stays_observed():
    result = _result()
    cover = result.get("slot_cover")
    assert cover is None or cover["claim_status"] == "observed"
    for m in result["matches"]:
        for o in m.get("slot_occupants", []):
            assert o["claim_status"] == "observed"


def test_the_schema_allows_the_slot_wording_and_forbids_replacement_claims():
    d = GET_POSITION_CHANGES_SCHEMA.description
    assert "slot_cover" in d and "ocupada por" in d and "held by" in d
    assert "never 'replaced him'" in d


# --- "¿Quién sustituye a João Pedro?" with him as both player and absent_player (prod 2026-11-01) ---------------

def test_absent_player_equal_to_the_player_is_ignored_by_the_tool():
    result = run_position_changes({"player": "João Pedro Junqueira de Jesus", "absent_player": "João Pedro Junqueira de Jesus"},
                                  copy.deepcopy(BOOTSTRAP), handle=FakeHandle(_tables()), fetch_fixtures=lambda: FPL_FIXTURES)
    assert result["status"] == "ok"
    assert "absence_focus" not in result


def test_card_has_no_absence_pill_for_his_own_absence():
    out = _out()
    out["player"]["player_id"] = 7
    out["absence_focus"] = {"teammate": {"player_id": 7, "web_name": "João Pedro"}, "matches_without_him_in_xi": [],
                            "matches_with_him_in_xi": [], "min_each_side": 3, "usual_role_without_him": None}
    for locale in ("es", "en"):
        card = compose_position_changes_card(out, locale)
        assert not any("João Pedro" in p.label for p in card.pills)
        assert len(card.rows) == 3


def test_card_keeps_the_absence_pill_for_a_teammate():
    out = _out()
    out["player"]["player_id"] = 7
    out["absence_focus"] = {"teammate": {"player_id": 8, "web_name": "Palmer"}, "matches_without_him_in_xi": [{}],
                            "matches_with_him_in_xi": [{}, {}, {}], "min_each_side": 3, "usual_role_without_him": None}
    card = compose_position_changes_card(out, "es")
    assert any(p.label == "Solo 1 partido sin Palmer" for p in card.pills)
