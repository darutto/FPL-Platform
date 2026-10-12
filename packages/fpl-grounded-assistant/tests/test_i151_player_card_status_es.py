"""
i151: the PlayerCard status badge is Spanish at the origin.

``status`` stays the English code (the UI keys tone / news visibility on it);
``status_label`` is the catalogue's Spanish for the badge text. An unmapped
value passes through unchanged (visible, not blank, not guessed).
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.catalogue import t
from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta

from test_player_snapshot_meta import _ok_raw_output, _ask_request


def _meta(status: str):
    raw = _ok_raw_output()
    raw["player"]["status"] = status
    meta = _extract_player_snapshot_meta(raw)
    assert meta is not None
    return meta


@pytest.mark.parametrize("english, spanish", [
    ("Available", "Disponible"),
    ("Doubtful", "Dudoso"),
    ("Injured", "Lesionado"),
    ("Suspended", "Suspendido"),
    ("Unavailable", "No disponible"),
    ("Not in squad", "Fuera de la plantilla"),
    ("Unknown", "Desconocido"),
])
def test_status_label_is_spanish_and_status_stays_english(english, spanish):
    meta = _meta(english)
    assert meta.status_label == spanish
    assert meta.status == english


def test_unmapped_status_passes_through_not_blank():
    assert _meta("Some New Word").status_label == "Some New Word"


def test_empty_status_stays_empty():
    assert _meta("").status_label == ""


def test_label_comes_from_the_catalogue_not_a_second_table():
    assert _meta("Doubtful").status_label == t("status_label.doubtful", "es")


def test_session_serializer_carries_status_label():
    from fpl_server import _player_snapshot_meta_dict
    payload = _player_snapshot_meta_dict(_meta("Injured"))
    assert payload["status"] == "Injured"
    assert payload["status_label"] == "Lesionado"


def test_ask_response_carries_status_label():
    """The /ask path (harness_adapter), read off what is served."""
    from fpl_grounded_assistant.dispatcher import INTENT_PLAYER_SNAPSHOT
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    d = {
        "answer_text": "x", "outcome": "ok", "supported": True,
        "intent": INTENT_PLAYER_SNAPSHOT, "review_passed": True, "llm_used": True,
        "player_snapshot": _meta("Doubtful"),
    }
    resp = to_ask_response(d, _ask_request("saka"))
    assert resp.player_snapshot["status"] == "Doubtful"
    assert resp.player_snapshot["status_label"] == "Dudoso"
