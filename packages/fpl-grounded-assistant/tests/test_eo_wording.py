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
