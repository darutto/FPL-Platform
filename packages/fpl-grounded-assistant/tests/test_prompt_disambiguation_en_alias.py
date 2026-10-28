"""EN slash alias (/compare) must get the same pick-one chips as /comparar.

Before: prompt_disambiguation only recognised the canonical Spanish head, so
``/compare João Pedro vs Haaland`` was ambiguous with no chips to tap.
"""
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


@pytest.mark.parametrize("locale,head", [("es", "/comparar"), ("en", "/compare"), ("en", "/comparar")])
def test_compare_ambiguous_offers_chips_in_the_typed_language(bootstrap, locale, head):
    bs = _with_two_joao_pedros(bootstrap)
    result = ask_v2(f"{head} João Pedro vs Haaland", bs, orch_client=object(), locale=locale)
    assert result["outcome"] == "ambiguous"
    chips = result["player_suggestions"]
    assert chips, "ambiguous compare must offer pick-one chips"
    assert {c["player_id"] for c in chips} == {30, 31}
    for chip in chips:
        assert chip["kind"] == "prompt_rewrite"
        assert chip["send_text"].startswith(f"{head} ")
        assert chip["send_text"].endswith(" vs Haaland")


@pytest.mark.parametrize("locale,head", [("es", "/comparar"), ("en", "/compare")])
def test_tapping_a_chip_runs_the_comparison(bootstrap, locale, head):
    bs = _with_two_joao_pedros(bootstrap)
    first = ask_v2(f"{head} João Pedro vs Haaland", bs, orch_client=object(), locale=locale)
    chelsea = next(c for c in first["player_suggestions"] if c["player_id"] == 30)
    second = ask_v2(chelsea["send_text"], bs, orch_client=object(), locale=locale)
    assert second["outcome"] == "ok"
    assert second["selected_tool"] == "compare_players"
