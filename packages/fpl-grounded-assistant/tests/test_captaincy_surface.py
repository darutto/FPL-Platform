"""Regression coverage for the query-shaped captaincy surface."""
from __future__ import annotations

import copy
from unittest.mock import patch

from fpl_grounded_assistant.chip_advisor import get_chip_advice
from fpl_grounded_assistant.final_response import _extract_chip_meta
from fpl_grounded_assistant.tool_schema_registry import (
    GET_CHIP_ADVICE_SCHEMA,
    RANK_CAPTAIN_CANDIDATES_SCHEMA,
)
from fpl_tool_runner import run_tool


def test_rank_tool_derives_pool_when_model_omits_candidates(bootstrap):
    result = run_tool("rank_captain_candidates", {}, bootstrap)

    assert result["status"] == "ok"
    assert result["pool_source"] == "derived"
    assert result["ranked_candidates"]


def test_derived_pool_source_is_visible_in_deterministic_response(bootstrap):
    from fpl_grounded_assistant.renderer import render

    result = run_tool("rank_captain_candidates", {}, bootstrap)
    text = render("rank_captain_candidates", result, locale="es")

    assert "Origen del pool: derivado del bootstrap." in text


def test_grounded_dispatch_resolves_connected_squad_before_derived_rank(
    bootstrap, monkeypatch,
):
    from fpl_grounded_assistant import tool_dispatch

    haaland = next(
        player for player in bootstrap["elements"]
        if player.get("web_name") == "Haaland"
    )
    connected = dict(bootstrap)
    connected["_my_team_id"] = 123
    monkeypatch.setattr(
        tool_dispatch,
        "get_my_squad",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "players": [{"id": haaland["id"]}],
        },
    )

    result = tool_dispatch.run_tool("rank_captain_candidates", {}, connected)

    assert result["squad_source"] == "connected"
    assert next(
        entry for entry in result["ranked_candidates"]
        if entry["player_id"] == haaland["id"]
    )["owned"] is True


def test_grounded_dispatch_declares_squad_unavailable_on_fetch_failure(
    bootstrap, monkeypatch,
):
    from fpl_grounded_assistant import tool_dispatch

    connected = dict(bootstrap)
    connected["_my_team_id"] = 123

    def _failed_fetch(*_args, **_kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr(tool_dispatch, "get_my_squad", _failed_fetch)

    result = tool_dispatch.run_tool("rank_captain_candidates", {}, connected)

    assert result["squad_source"] == "unavailable"


def test_explicit_rank_does_not_fetch_or_change_candidate_set(bootstrap, monkeypatch):
    from fpl_grounded_assistant import tool_dispatch

    connected = dict(bootstrap)
    connected["_my_team_id"] = 123

    def _unexpected_fetch(*_args, **_kwargs):
        raise AssertionError("explicit candidate rankings must not fetch the squad")

    monkeypatch.setattr(tool_dispatch, "get_my_squad", _unexpected_fetch)
    result = tool_dispatch.run_tool(
        "rank_captain_candidates",
        {"candidates": [{"query": "Haaland"}, {"query": "Salah"}]},
        connected,
    )

    assert result["pool_source"] == "caller"
    assert [entry["web_name"] for entry in result["ranked_candidates"]] == [
        "Salah", "Haaland",
    ]


def test_derived_rank_renderer_declares_no_connected_team(bootstrap):
    from fpl_grounded_assistant.renderer import render

    result = run_tool("rank_captain_candidates", {}, bootstrap)
    text = render("rank_captain_candidates", result, locale="es")

    assert "No hay equipo conectado; te muestro solo el ranking global." in text
    assert "B) Mejores candidatos globales:" in text
    assert "A) Candidatos elegibles de tu plantilla" not in text


def test_derived_rank_renderer_builds_owned_and_global_blocks(bootstrap):
    from fpl_grounded_assistant.renderer import render

    haaland_id = next(
        player["id"] for player in bootstrap["elements"]
        if player.get("web_name") == "Haaland"
    )
    result = run_tool(
        "rank_captain_candidates", {"squad_player_ids": [haaland_id]}, bootstrap
    )
    text = render("rank_captain_candidates", result, locale="es")

    assert "A) Candidatos elegibles de tu plantilla (solo MID/FWD):" in text
    assert "B) Mejores candidatos globales:" in text
    assert "Haaland" in text
    assert "· tu plantilla" in text


def test_owned_and_excluded_metadata_survive_final_response_extraction(bootstrap):
    from fpl_grounded_assistant.dispatcher import INTENT_RANK_CANDIDATES
    from fpl_grounded_assistant.final_response import _extract_structured_meta

    haaland = next(
        player for player in bootstrap["elements"]
        if player.get("web_name") == "Haaland"
    )
    unavailable = next(
        player for player in bootstrap["elements"]
        if player.get("status") in ("i", "s", "u")
    )
    raw = run_tool(
        "rank_captain_candidates",
        {"squad_player_ids": [haaland["id"], unavailable["id"]]},
        bootstrap,
    )

    meta = _extract_structured_meta(INTENT_RANK_CANDIDATES, raw, "ok")

    assert meta["squad_source"] == "connected"
    assert meta["squad_excluded"][0].player_id == unavailable["id"]
    assert meta["squad_excluded"][0].reason == "unavailable"
    assert next(
        entry for entry in meta["captain_ranking"]
        if entry.web_name == "Haaland"
    ).owned is True


def test_future_captain_rank_clamps_squad_fetch_and_keeps_owned_block(bootstrap):
    from fpl_grounded_assistant import tool_dispatch
    from fpl_grounded_assistant.renderer import render

    connected = copy.deepcopy(bootstrap)
    connected["_my_team_id"] = 68_643
    connected["team_fixtures"] = {
        team["id"]: [{"gameweek": 29, "difficulty": 3}]
        for team in connected["teams"]
    }
    picks = {
        "picks": [
            {
                "element": player_id,
                "position": position,
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
                "multiplier": 1 if position <= 11 else 0,
            }
            for position, player_id in enumerate(range(1, 16), start=1)
        ],
        "entry_history": {},
        "active_chip": None,
    }

    with patch(
        "fpl_grounded_assistant.get_my_squad.get_entry_picks",
        return_value=picks,
    ) as fetch:
        result = tool_dispatch.run_tool(
            "rank_captain_candidates", {"gameweek": 29}, connected
        )

    fetch.assert_called_once_with(68_643, 28)
    assert result["status"] == "ok"
    assert result["squad_source"] == "connected"
    assert any(entry.get("owned") for entry in result["ranked_candidates"])
    text = render("rank_captain_candidates", result, locale="es")
    assert "A) Candidatos elegibles de tu plantilla (solo MID/FWD):" in text


def test_rank_schema_candidates_is_optional_and_description_is_truthful():
    assert "candidates" not in RANK_CAPTAIN_CANDIDATES_SCHEMA.parameters["required"]
    assert "deterministic global" in RANK_CAPTAIN_CANDIDATES_SCHEMA.description


def test_chip_schema_accepts_optional_player():
    assert "player" in GET_CHIP_ADVICE_SCHEMA.parameters["properties"]
    assert "player" not in GET_CHIP_ADVICE_SCHEMA.parameters["required"]


def test_all_three_captain_tools_accept_optional_time_window():
    from fpl_grounded_assistant.tool_schema_registry import GET_CAPTAIN_SCORE_SCHEMA

    for schema in (
        GET_CAPTAIN_SCORE_SCHEMA,
        RANK_CAPTAIN_CANDIDATES_SCHEMA,
        GET_CHIP_ADVICE_SCHEMA,
    ):
        assert {"gameweek", "horizon"} <= set(schema.parameters["properties"])
        assert "gameweek" not in schema.parameters["required"]
        assert "horizon" not in schema.parameters["required"]


def test_triple_captain_player_verdict_names_requested_player_and_top(bootstrap):
    result = get_chip_advice("triple_captain", bootstrap, player="Haaland")

    assert result["status"] == "ok"
    assert result["signals"]["evaluated_player"] == "Haaland"
    assert result["signals"]["top_player"] == "Salah"
    assert "Your candidate Haaland" in result["advice_text"]
    assert "best available is Salah" in result["advice_text"]


def test_triple_captain_without_player_keeps_global_top_behavior(bootstrap):
    result = get_chip_advice("triple_captain", bootstrap)

    assert result["signals"]["top_player"] == "Salah"
    assert "evaluated_player" not in result["signals"]
    assert "option exists: Salah" in result["advice_text"]


def test_squad_context_suppresses_stale_availability_disclaimer(bootstrap):
    without_context = get_chip_advice("triple_captain", bootstrap)
    with_context = get_chip_advice(
        "triple_captain",
        bootstrap,
        squad_context={"chips_remaining": ["triple_captain"]},
    )

    assert "whether you still have this chip available" in without_context["advice_text"]
    assert "whether you still have this chip available" not in with_context["advice_text"]


def test_structured_chip_meta_identifies_signal_owner_and_global_top(bootstrap):
    raw = get_chip_advice("triple_captain", bootstrap, player="Haaland")
    meta = _extract_chip_meta(raw)

    assert meta is not None
    assert meta.evaluated_player == "Haaland"
    assert meta.top_player == "Salah"
    assert meta.signal_value == raw["signals"]["evaluated_captain_score"]


def test_chip_advice_defaults_explicitly_to_current_gameweek(bootstrap):
    raw = get_chip_advice("triple_captain", bootstrap)

    assert raw["time_context"]["source"] == "current"
    assert raw["evaluated_gameweek"] == 28
    assert raw["advice_text"].startswith("Evaluated the current gameweek GW28.")


def test_chip_advice_evaluates_requested_player_in_requested_gameweek(bootstrap):
    bootstrap = copy.deepcopy(bootstrap)
    bootstrap["team_fixtures"] = {
        1: [{"gameweek": 28, "difficulty": 3}, {"gameweek": 29, "difficulty": 3}],
        8: [{"gameweek": 28, "difficulty": 3}, {"gameweek": 29, "difficulty": 3}],
        13: [{"gameweek": 28, "difficulty": 5}, {"gameweek": 29, "difficulty": 1}],
        14: [{"gameweek": 28, "difficulty": 2}, {"gameweek": 29, "difficulty": 4}],
    }

    current = get_chip_advice("triple_captain", bootstrap, player="Haaland")
    future = get_chip_advice(
        "triple_captain", bootstrap, player="Haaland", gameweek=29
    )

    assert future["evaluated_gameweek"] == 29
    assert future["signals"]["evaluated_captain_score"] > current["signals"]["evaluated_captain_score"]
    assert future["advice_text"].startswith("Evaluated the requested gameweek GW29.")


def test_chip_advice_refuses_to_present_current_fdr_as_future_analysis(bootstrap):
    raw = get_chip_advice(
        "triple_captain", bootstrap, player="Haaland", gameweek=30
    )

    assert raw["recommendation"] == "missing_context"
    assert raw["evaluated_gameweek"] == 30
    assert raw["advice_text"].startswith(
        "Could not evaluate the requested gameweek GW30."
    )
