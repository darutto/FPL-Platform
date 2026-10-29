"""Ambiguous player inside /transferencia (/transfer) offers pick-one chips, es + en."""
from __future__ import annotations

import copy

import pytest

from fpl_grounded_assistant.harness import ask_v2


def _with_two_joao_pedros(bootstrap: dict) -> dict:
    result = copy.deepcopy(bootstrap)
    result["elements"].extend([
        {"id": 30, "first_name": "João Pedro", "second_name": "Junqueira de Jesus",
         "web_name": "João Pedro", "team": 8, "element_type": 4,
         "status": "a", "total_points": 80, "minutes": 900},
        {"id": 31, "first_name": "João Pedro", "second_name": "Gomes Costa",
         "web_name": "Costinha", "team": 11, "element_type": 4,
         "status": "a", "total_points": 70, "minutes": 800},
    ])
    return result


_CASES = [
    ("es", "/transferencia", "por"),
    ("en", "/transfer", "for"),
    ("en", "/transferencia", "por"),
]


@pytest.mark.parametrize("locale,head,conn", _CASES)
@pytest.mark.parametrize("slot", ["out", "in"])
def test_ambiguous_transfer_slot_offers_chips_by_id(bootstrap, locale, head, conn, slot):
    bs = _with_two_joao_pedros(bootstrap)
    question = (
        f"{head} João Pedro {conn} Haaland" if slot == "out"
        else f"{head} Haaland {conn} João Pedro"
    )
    result = ask_v2(question, bs, orch_client=object(), locale=locale)
    assert result["outcome"] == "ambiguous"
    chips = result["player_suggestions"]
    assert chips and {c["player_id"] for c in chips} == {30, 31}
    for chip in chips:
        assert chip["kind"] == "prompt_rewrite"
        assert chip["send_text"].startswith(f"{head} ")
        # the other side of the swap is untouched by the rewrite
        assert "Haaland" in chip["send_text"]


@pytest.mark.parametrize("locale,head,conn", _CASES)
def test_tapping_a_transfer_chip_resolves_that_player(bootstrap, locale, head, conn):
    bs = _with_two_joao_pedros(bootstrap)
    first = ask_v2(f"{head} João Pedro {conn} Haaland", bs, orch_client=object(), locale=locale)
    costinha = next(c for c in first["player_suggestions"] if c["player_id"] == 31)
    second = ask_v2(costinha["send_text"], bs, orch_client=object(), locale=locale)
    assert second["outcome"] == "ok"
    assert second["selected_tool"] == "get_transfer_advice"
    assert second["raw_output"]["player_out"]["web_name"] == "Costinha"
