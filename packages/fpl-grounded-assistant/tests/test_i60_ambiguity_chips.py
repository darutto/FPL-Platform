"""i60 -- ambiguous players get chips that resolve to the RIGHT player.

Two deliveries, two mechanisms:

* Current-season tools (get_player_form, get_player_snapshot): candidates come
  from the live bootstrap, ids are stable within the season, so the existing
  stable-id wizard is armed (``player_suggestions`` with ``player_id``).
* Past-season tool (get_player_season_points): ids belong to that season's
  store and must NOT be handed to the current-bootstrap resolver. Chips carry
  a canonical question instead (kind=historical_player_rewrite, no id), and
  the resolver breaks the tie by club on the way back -- via a structured
  ``team_short`` argument, or the "(XXX)" token in the query as fallback.

The round-trip test runs the chip's ``send_text`` through the REAL handler
(``run_tool``), never through the candidate's own data.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

import fpl_grounded_assistant.get_player_season_points  # noqa: F401 -- ensure the module (not the re-exported function) is loaded
sp = sys.modules["fpl_grounded_assistant.get_player_season_points"]
from fpl_grounded_assistant.harness import STATUS_BEARING_TOOLS, WIZARD_ARMING_TOOLS, ask_v2
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.suggestions import (
    KIND_HISTORICAL_PLAYER_REWRITE,
    historical_player_suggestions,
    suggestions_to_list,
)
from fpl_grounded_assistant.tool_dispatch import run_tool

SEASON = "2025-2026"


# ---------------------------------------------------------------------------
# synthetic past-season store: two "Salah"s in different squads
# ---------------------------------------------------------------------------

def _write_store(root: Path) -> None:
    merged = root / "seasons" / SEASON / "parquet_merged"
    merged.mkdir(parents=True)
    pd.DataFrame([
        {"player_id": 101, "web_name": "Salah", "first_name": "Mohamed", "second_name": "Salah",
         "team_id": 1, "element_type": 3, "total_points": 300},
        {"player_id": 202, "web_name": "Salah", "first_name": "Mohamed", "second_name": "Salah",
         "team_id": 2, "element_type": 4, "total_points": 40},
        {"player_id": 303, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland",
         "team_id": 3, "element_type": 4, "total_points": 250},
    ]).to_parquet(merged / "players.parquet")
    pd.DataFrame([
        {"team_id": 1, "short_name": "LIV"},
        {"team_id": 2, "short_name": "BOU"},
        {"team_id": 3, "short_name": "MCI"},
    ]).to_parquet(merged / "teams.parquet")
    rows = []
    for pid, pts in ((101, 300), (202, 40), (303, 250)):
        rows.append({"event_id": 1, "player_id": pid, "total_points": pts, "minutes": 90,
                     "goals_scored": 1, "assists": 0, "clean_sheets": 0, "bonus": 1})
    pd.DataFrame(rows).to_parquet(merged / "player_gw_stats.parquet")
    pd.DataFrame([{"event_id": 1, "finished": True}]).to_parquet(merged / "events.parquet")


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "historical"
    _write_store(root)
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(root))
    importlib.reload(sp)
    return root


# ---------------------------------------------------------------------------
# historical round-trip through the real handler
# ---------------------------------------------------------------------------

def test_ambiguous_past_season_carries_season_and_chip_ready_candidates(store: Path) -> None:
    out = sp.get_player_season_points("Salah", SEASON)
    assert out["status"] == "ambiguous"
    assert out["season"] == SEASON
    ids = sorted(c["id"] for c in out["candidates"])
    assert ids == [101, 202]
    assert {c["team_short"] for c in out["candidates"]} == {"LIV", "BOU"}
    assert all(c["name"] == "Mohamed Salah" for c in out["candidates"])


def test_historical_chips_carry_the_canonical_question_and_no_id(store: Path) -> None:
    out = sp.get_player_season_points("Salah", SEASON)
    chips = suggestions_to_list(historical_player_suggestions(out["candidates"], out["season"]))
    assert chips is not None and len(chips) == 2
    for chip in chips:
        assert chip["kind"] == KIND_HISTORICAL_PLAYER_REWRITE
        assert "player_id" not in chip
        assert chip["send_text"].startswith("puntos de Mohamed Salah (")
        assert chip["send_text"].endswith(f") en la temporada {SEASON}")
    assert {c["label"] for c in chips} == {"Salah (LIV)", "Salah (BOU)"}


@pytest.mark.parametrize("structured", [True, False], ids=["team_short-arg", "query-only-fallback"])
def test_chip_round_trip_resolves_to_the_candidates_historical_id(store: Path, structured: bool) -> None:
    out = sp.get_player_season_points("Salah", SEASON)
    chips = suggestions_to_list(historical_player_suggestions(out["candidates"], out["season"]))
    by_label = {c["label"]: c for c in chips}
    bou_candidate = next(c for c in out["candidates"] if c["team_short"] == "BOU")

    # what the orchestrator would extract from the chip's send_text
    send_text = by_label["Salah (BOU)"]["send_text"]
    args = {"query": "Mohamed Salah (BOU)", "season": SEASON}
    if structured:
        args["query"] = "Mohamed Salah"
        args["team_short"] = "BOU"
    assert "(BOU)" in send_text

    result = run_tool("get_player_season_points", args, {})
    assert result["status"] == "ok", result
    assert result["player"]["id"] == bou_candidate["id"] == 202
    assert result["player"]["team_short"] == "BOU"
    assert result["summary"]["total_points"] == 40


def test_wrong_club_stays_a_visible_ambiguity_not_a_silent_pick(store: Path) -> None:
    result = run_tool("get_player_season_points", {"query": "Salah", "season": SEASON, "team_short": "ARS"}, {})
    assert result["status"] == "ambiguous"
    assert sorted(c["id"] for c in result["candidates"]) == [101, 202]


def test_split_club_from_query() -> None:
    assert sp.split_club_from_query("Mohamed Salah (LIV)") == ("Mohamed Salah", "LIV")
    assert sp.split_club_from_query("puntos de Salah (bou)") == ("puntos de Salah (bou)", None)
    assert sp.split_club_from_query("Salah") == ("Salah", None)


def test_toolspec_and_llm_schema_both_expose_optional_team_short() -> None:
    from fpl_grounded_assistant import tool_schema_registry as reg
    spec = sp.GET_PLAYER_SEASON_POINTS_SPEC.parameters
    schema = reg._REGISTRY["get_player_season_points"].parameters
    assert "team_short" in spec["properties"] and "team_short" not in spec["required"]
    assert "team_short" in schema["properties"] and "team_short" not in schema["required"]


# ---------------------------------------------------------------------------
# harness delivery: the ambiguity reaches the UI
# ---------------------------------------------------------------------------

def _orch(tool: str, output: dict) -> OrchestratorResult:
    return OrchestratorResult(
        question="q", tool_chosen=tool, tool_args={}, tool_output=output,
        answer_text="orchestrated", llm_used=True, model="fake", outcome="ok",
    )


def test_wizard_arming_set_is_the_documented_one() -> None:
    assert WIZARD_ARMING_TOOLS == frozenset({"get_player_snapshot", "get_player_form"})
    assert "get_player_season_points" in STATUS_BEARING_TOOLS
    assert "get_player_season_points" not in WIZARD_ARMING_TOOLS


def test_player_form_ambiguous_arms_stable_id_chips(monkeypatch, bootstrap: dict) -> None:
    from fpl_player_registry import candidate_dict
    output = {"status": "ambiguous", "query": "gabriel", "candidates": [
        candidate_dict(player_id=11, web_name="Gabriel", team_short="ARS", position="DEF"),
        candidate_dict(player_id=22, web_name="Gabriel", team_short="MCI", position="MID"),
    ]}
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated",
                        lambda *a, **k: _orch("get_player_form", output))
    result = ask_v2("forma de gabriel en las ultimas 5 jornadas", bootstrap, orch_client=object())
    assert result["selected_tool"] == "get_player_form"
    assert result["outcome"] == "ambiguous"
    chips = result["player_suggestions"]
    assert [c["player_id"] for c in chips] == [11, 22]
    assert all("kind" not in c for c in chips)


def test_season_points_ambiguous_arms_historical_chips_without_ids(monkeypatch, bootstrap: dict) -> None:
    from fpl_player_registry import candidate_dict
    output = {"status": "ambiguous", "query": "salah", "season": SEASON, "candidates": [
        candidate_dict(player_id=101, web_name="Salah", team_short="LIV", position="MID",
                       first_name="Mohamed", second_name="Salah"),
        candidate_dict(player_id=202, web_name="Salah", team_short="BOU", position="FWD",
                       first_name="Mohamed", second_name="Salah"),
    ]}
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated",
                        lambda *a, **k: _orch("get_player_season_points", output))
    result = ask_v2("puntos de salah la temporada pasada", bootstrap, orch_client=object())
    assert result["outcome"] == "ambiguous"
    chips = result["player_suggestions"]
    assert len(chips) == 2
    assert all(c["kind"] == KIND_HISTORICAL_PLAYER_REWRITE and "player_id" not in c for c in chips)
    assert all(c["send_text"].endswith(f"en la temporada {SEASON}") for c in chips)


def test_other_orch_tools_keep_the_ok_hardcode(monkeypatch, bootstrap: dict) -> None:
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated",
                        lambda *a, **k: _orch("get_player_history", {"status": "ambiguous"}))
    result = ask_v2("historial de salah", bootstrap, orch_client=object())
    assert result["outcome"] == "ok"
    assert "player_suggestions" not in result
