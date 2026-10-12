"""
i151c: FPL ``news`` in Spanish for the 7 known templates (Leo: option A).

All-or-nothing: anything unrecognised -- including a known shape with an
unseen body part or month -- stays in English, byte for byte. The ``news``
field itself is never altered; ``news_label`` carries the display text.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.news_es import news_label, translate_news


@pytest.mark.parametrize("english, spanish", [
    # 1. injury - N% chance of playing
    ("Knee injury - 75% chance of playing",
     "Lesión de rodilla - 75% de probabilidad de jugar"),
    ("Unspecified injury - 25% chance of playing",
     "Lesión sin especificar - 25% de probabilidad de jugar"),
    # 2. injury - Unknown return date
    ("Hamstring injury - Unknown return date",
     "Lesión de isquiotibiales - Fecha de regreso desconocida"),
    # 3. injury - Expected back D Mon
    ("Ankle injury - Expected back 18 Oct",
     "Lesión de tobillo - Regreso previsto 18 oct"),
    ("Achilles injury - Expected back 7 Nov",
     "Lesión del tendón de Aquiles - Regreso previsto 7 nov"),
    ("Back injury - Expected back 28 Dec",
     "Lesión de espalda - Regreso previsto 28 dic"),
    # 4. loan for the rest of the season
    ("Has joined Borussia Dortmund on loan for the rest of the season",
     "Cedido a Borussia Dortmund hasta final de temporada"),
    # 4b. ... including FPL's own typo, leading lowercase, double space, period
    ("has joined  Kasimpasa on loan for the rest of the seaon.",
     "Cedido a Kasimpasa hasta final de temporada"),
    ("has joined West Ham on loan for the rest of the seaon.",
     "Cedido a West Ham hasta final de temporada"),
    # 5. loan until <month>
    ("Has joined Oxford United on loan until January",
     "Cedido a Oxford United hasta enero"),
    # 6. permanent
    ("Has joined Al Hilal permanently",
     "Ha fichado por Al Hilal de forma permanente"),
    # 7. suspended
    ("Suspended until 25 Oct", "Suspendido hasta 25 oct"),
])
def test_template_is_translated(english, spanish):
    assert translate_news(english) == spanish
    assert news_label(english) == spanish


@pytest.mark.parametrize("part, phrase", [
    ("Knee", "Lesión de rodilla"), ("Hamstring", "Lesión de isquiotibiales"),
    ("Unspecified", "Lesión sin especificar"), ("Ankle", "Lesión de tobillo"),
    ("Thigh", "Lesión de muslo"), ("Back", "Lesión de espalda"),
    ("Calf", "Lesión de gemelo"), ("Foot", "Lesión de pie"),
    ("Leg", "Lesión de pierna"), ("Groin", "Lesión de ingle"),
    ("Shoulder", "Lesión de hombro"), ("Arm", "Lesión de brazo"),
    ("Achilles", "Lesión del tendón de Aquiles"),
    ("Shin", "Lesión de espinilla"), ("Muscular", "Lesión muscular"),
])
def test_all_known_body_parts(part, phrase):
    assert translate_news(f"{part} injury - Unknown return date") == (
        f"{phrase} - Fecha de regreso desconocida")


@pytest.mark.parametrize("unmatched", [
    "has departed the club as a free agent.",
    "has returned to Getafe CF",
    "not included in squad.",
    "Suspended",
    "Knee injury",
    "",
])
def test_unmatched_stays_english_untouched(unmatched):
    assert translate_news(unmatched) is None
    assert news_label(unmatched) == unmatched


@pytest.mark.parametrize("partial", [
    "Hip injury - Unknown return date",             # unseen body part
    "Hip injury - 50% chance of playing",
    "Hip injury - Expected back 18 Oct",
    "Knee injury - Expected back 18 Sept",          # unseen month spelling
    "Knee injury - Expected back 18 Xyz",
    "Suspended until 25 Xyz",
    "Has joined Oxford United on loan until Smarch",
])
def test_known_shape_with_unrenderable_part_stays_entirely_english(partial):
    """Never a mix: one unknown part leaves the whole note English."""
    assert translate_news(partial) is None
    assert news_label(partial) == partial


def test_none_and_empty():
    assert translate_news(None) is None
    assert news_label(None) == ""


@pytest.mark.parametrize("en, es", [
    ("Jan", "ene"), ("Feb", "feb"), ("Mar", "mar"), ("Apr", "abr"),
    ("May", "may"), ("Jun", "jun"), ("Jul", "jul"), ("Aug", "ago"),
    ("Sep", "sep"), ("Oct", "oct"), ("Nov", "nov"), ("Dec", "dic"),
])
def test_every_abbreviated_month(en, es):
    assert translate_news(f"Suspended until 3 {en}") == f"Suspendido hasta 3 {es}"


@pytest.mark.parametrize("en, es", [
    ("January", "enero"), ("February", "febrero"), ("March", "marzo"),
    ("April", "abril"), ("May", "mayo"), ("June", "junio"), ("July", "julio"),
    ("August", "agosto"), ("September", "septiembre"),
    ("October", "octubre"), ("November", "noviembre"), ("December", "diciembre"),
])
def test_every_full_month(en, es):
    assert translate_news(f"Has joined Rangers on loan until {en}") == (
        f"Cedido a Rangers hasta {es}")


def test_no_english_left_in_a_translation():
    out = translate_news("Knee injury - 75% chance of playing")
    for word in ("injury", "chance", "playing", "Knee"):
        assert word not in out


# --- wiring: the surfaces show the label, the payload keeps the original ----

def _raw(news, status="Doubtful"):
    from test_player_snapshot_meta import _ok_raw_output
    raw = _ok_raw_output()
    raw["player"]["status"] = status
    raw["player"]["news"] = news
    return raw


def test_snapshot_meta_carries_news_and_news_label():
    from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
    meta = _extract_player_snapshot_meta(_raw("Knee injury - 75% chance of playing"))
    assert meta.news == "Knee injury - 75% chance of playing"      # original
    assert meta.news_label == "Lesión de rodilla - 75% de probabilidad de jugar"


def test_snapshot_meta_untranslatable_news_label_equals_news():
    from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
    meta = _extract_player_snapshot_meta(_raw("has returned to Getafe CF"))
    assert meta.news_label == meta.news == "has returned to Getafe CF"


def test_snapshot_meta_empty_news():
    from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
    assert _extract_player_snapshot_meta(_raw("", "Available")).news_label == ""


def test_session_serializer_and_ask_response_carry_news_label():
    from fpl_grounded_assistant.dispatcher import INTENT_PLAYER_SNAPSHOT
    from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    from fpl_server import _player_snapshot_meta_dict
    from test_player_snapshot_meta import _ask_request
    meta = _extract_player_snapshot_meta(_raw("Suspended until 25 Oct", "Suspended"))
    assert _player_snapshot_meta_dict(meta)["news_label"] == "Suspendido hasta 25 oct"
    resp = to_ask_response({
        "answer_text": "x", "outcome": "ok", "supported": True,
        "intent": INTENT_PLAYER_SNAPSHOT, "review_passed": True,
        "llm_used": True, "player_snapshot": meta,
    }, _ask_request("x"))
    assert resp.player_snapshot["news"] == "Suspended until 25 Oct"
    assert resp.player_snapshot["news_label"] == "Suspendido hasta 25 oct"


def test_injury_card_and_resource_rows_show_spanish_news():
    from fpl_grounded_assistant.final_response import InjuryEntry, InjuryListMeta
    from fpl_grounded_assistant.generic_card import compose_injury_list
    from fpl_grounded_assistant.resource_registry import _resource_injuries
    e = InjuryEntry(web_name="X", team_short="ARS", position="MID",
                    status_label="Injured",
                    news="Hamstring injury - Unknown return date")
    card = compose_injury_list(InjuryListMeta(injured=(e,), doubtful=(), other=(), total=1))
    assert card.rows[0][5] == "Lesión de isquiotibiales - Fecha de regreso desconocida"
    assert e.news == "Hamstring injury - Unknown return date"       # tool value intact
    bs = {"teams": [{"id": 1, "short_name": "ARS"}], "elements": [
        {"web_name": "A", "team": 1, "element_type": 3, "status": "i",
         "news": "Has joined Al Hilal permanently", "news_added": "2026-10-01T10:00:00Z"},
        {"web_name": "B", "team": 1, "element_type": 3, "status": "i",
         "news": "not included in squad.", "news_added": "2026-10-02T10:00:00Z"}]}
    rows = {r["web_name"]: r["news"] for r in _resource_injuries(bs).rows}
    assert rows == {"A": "Ha fichado por Al Hilal de forma permanente",
                    "B": "not included in squad."}
