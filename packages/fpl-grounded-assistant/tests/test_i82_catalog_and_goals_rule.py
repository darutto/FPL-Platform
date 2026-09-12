"""i82 -- the two owned-store season tools reach the LLM catalogue, and
"maximo goleador" of a PAST season is answered deterministically.

Three things pinned here:

1. Catalogue: both schemas are in ``_ALL_SCHEMAS`` / the offered set, with
   the exact parameter names and ``required`` of their registered ToolSpecs
   (the runner enforces ``required`` before the handler; a drift here means
   a model-chosen call dies at the runner).
2. Renderer reach: ``render(tool_name, raw)`` -- the orchestrated path, not
   the dispatcher -- covers both tools (success, empty, invalid gw,
   season_not_found, error).
3. Goals rule: (a) routing -- the phrase never reaches the orchestrator, so
   ``get_historical_gameweek_top_scorer`` cannot be called for it; (b) the
   final ``answer_text`` is the fixed wording. Both, because a routing-only
   test cannot guarantee what the user reads.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant import tool_schema_registry as reg
from fpl_grounded_assistant.decision_router import (
    PAST_SEASON_GOALS_REPLY,
    decide,
    is_past_season_goals_question,
)
from fpl_grounded_assistant.get_player_season_points import GET_PLAYER_SEASON_POINTS_SPEC
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.historical_gameweek_top_scorer import (
    GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC,
)
from fpl_grounded_assistant.renderer import render


# --- 1. catalogue -----------------------------------------------------------

@pytest.mark.parametrize(
    "name, spec",
    [
        ("get_player_season_points", GET_PLAYER_SEASON_POINTS_SPEC),
        ("get_historical_gameweek_top_scorer", GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC),
    ],
)
def test_schema_is_offered_and_mirrors_the_toolspec(name: str, spec) -> None:
    schema = reg.get_schema(name) if hasattr(reg, "get_schema") else reg._REGISTRY[name]
    assert schema.name == name
    offered = {s.name for s in reg._BASE_OFFERED_SCHEMAS}
    assert name in offered
    assert set(schema.parameters["properties"]) == set(spec.parameters["properties"])
    assert sorted(schema.parameters.get("required", [])) == sorted(spec.parameters.get("required", []))
    assert reg.validate_tool_schema_shape(schema)


def test_season_points_requires_query_and_season() -> None:
    schema = reg._REGISTRY["get_player_season_points"]
    assert sorted(schema.parameters["required"]) == ["query", "season"]


def test_top_scorer_has_no_required_arguments() -> None:
    schema = reg._REGISTRY["get_historical_gameweek_top_scorer"]
    assert schema.parameters["required"] == []
    assert set(schema.parameters["properties"]) == {"season", "gw"}


def test_descriptions_carry_the_boundaries() -> None:
    sp = reg._REGISTRY["get_player_season_points"].description
    ts = reg._REGISTRY["get_historical_gameweek_top_scorer"].description
    assert "get_player_snapshot" in sp          # current season -> snapshot
    assert "rank_players_by_metric" in ts       # goals -> ranker
    assert "get_gameweek_context" in ts         # fixtures/deadlines -> context
    assert "POINTS" in ts


# --- 2. renderer reach through the orchestrated path -------------------------

def test_render_reaches_season_points() -> None:
    raw = {
        "status": "ok", "season": "2025-2026",
        "player": {"web_name": "Salah", "team_short": "LIV", "position": "MID"},
        "summary": {"total_points": 300, "gws_played": 38, "points_per_game": 7.9,
                    "total_goals": 25, "total_assists": 15, "total_clean_sheets": 10,
                    "total_bonus": 40, "total_minutes": 3300},
    }
    text = render("get_player_season_points", raw)
    assert "Salah" in text and "300" in text and "2025-2026" in text
    assert "No renderer" not in text


def test_render_top_scorer_single_gw_with_rows() -> None:
    raw = {"status": "ok", "season": "2026-2027", "gw": 3, "entries": [
        {"event_id": 3, "player_id": 1, "web_name": "Palmer", "team_short": "CHE",
         "position": "MID", "points": 17, "highlight": "2 goles, 1 asistencia"},
    ]}
    text = render("get_historical_gameweek_top_scorer", raw)
    assert text.startswith("Jugador de la jornada 3 (2026-2027): Palmer (CHE, MID) — 17 puntos")
    assert "2 goles" in text


def test_render_top_scorer_season_table() -> None:
    raw = {"status": "ok", "season": "2025-2026", "gw": None, "entries": [
        {"event_id": 1, "web_name": "A", "team_short": "X", "position": "MID", "points": 10},
        {"event_id": 2, "web_name": "B", "team_short": "Y", "position": "FWD", "points": 12},
    ]}
    text = render("get_historical_gameweek_top_scorer", raw)
    lines = text.split("\n")
    assert lines[0] == "Jugador de la jornada, temporada 2025-2026:"
    assert lines[1].startswith("J1: A (X, MID) — 10 puntos")
    assert lines[2].startswith("J2: B (Y, FWD) — 12 puntos")


def test_render_top_scorer_empty_rows() -> None:
    text = render("get_historical_gameweek_top_scorer",
                  {"status": "ok", "season": "2025-2026", "gw": None, "entries": []})
    assert "Sin datos" in text and "2025-2026" in text


def test_render_top_scorer_invalid_gw() -> None:
    text = render("get_historical_gameweek_top_scorer",
                  {"status": "invalid_argument", "code": "invalid_gw",
                   "message": "gw must be between 1 and 38 (got 39)."})
    assert "got 39" in text


def test_render_top_scorer_season_not_found() -> None:
    text = render("get_historical_gameweek_top_scorer",
                  {"status": "not_found", "code": "season_not_found",
                   "message": "No historical data for season '2010-2011'."})
    assert "2010-2011" in text


def test_render_top_scorer_error() -> None:
    text = render("get_historical_gameweek_top_scorer",
                  {"status": "error", "code": "parquet_read_failed", "message": "boom"})
    assert text == "Error (parquet_read_failed): boom"


def test_every_offered_schema_has_a_renderer() -> None:
    from fpl_grounded_assistant import renderer
    missing = {s.name for s in reg._ALL_SCHEMAS} - set(renderer._RENDERERS)
    assert not missing


# --- 3. goals rule ------------------------------------------------------------

@pytest.mark.parametrize("q", [
    "¿Quién fue el máximo goleador de la temporada pasada?",
    "máximo goleador de la J3 de la 2024-25",
    "quien hizo mas goles la temporada anterior",
    "goleador de la última temporada",
    "who was the top goalscorer last season",
])
def test_rule_matches_past_season_goals(q: str) -> None:
    assert is_past_season_goals_question(q)


@pytest.mark.parametrize("q", [
    "¿Quién es el máximo goleador de la liga?",          # current season -> ranker
    "goleador de la jornada 3",                           # no past-season marker
    "¿Cuántos puntos hizo Salah la temporada pasada?",    # points, not goals
    "¿Quién hizo más puntos en la jornada 3 de la 2024-25?",
])
def test_rule_leaves_points_and_current_season_alone(q: str) -> None:
    assert not is_past_season_goals_question(q)


def test_decide_returns_unsupported_with_the_fixed_reply(bootstrap: dict) -> None:
    d = decide("¿Quién fue el máximo goleador de la temporada pasada?", bootstrap)
    assert d["outcome"] == "unsupported"
    assert d["kind"] == "text"
    assert d["rule"] == "past_season_goals"
    assert d["message"] == PAST_SEASON_GOALS_REPLY


def test_end_to_end_never_reaches_the_orchestrator_and_says_the_fixed_text(
    monkeypatch, bootstrap: dict
) -> None:
    called: list[str] = []

    def fake_orchestrator(question: str, *args, **kwargs):  # pragma: no cover - must not run
        called.append(question)
        raise AssertionError("orchestrator must not be reached")

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator)
    result = ask_v2("¿Quién fue el máximo goleador de la temporada pasada?", bootstrap, orch_client=object())
    assert called == []
    assert result["selected_tool"] is None
    assert result["outcome"] == "unsupported"
    assert result["answer_text"] == PAST_SEASON_GOALS_REPLY
    assert "puntos" in result["answer_text"]


def test_current_season_goals_still_reaches_the_orchestrator(monkeypatch, bootstrap: dict) -> None:
    from fpl_grounded_assistant.orchestrator import OrchestratorResult
    seen: list[str] = []

    def fake_orchestrator(question: str, *args, **kwargs):
        seen.append(question)
        return OrchestratorResult(
            question=question, outcome="ok", tool_chosen="rank_players_by_metric",
            tool_args={"metric": "goals_scored"}, tool_output={"status": "ok", "rows": []},
            answer_text="ok", llm_used=True, model="fake",
        )

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator)
    result = ask_v2("¿Quién es el máximo goleador de la liga?", bootstrap, orch_client=object())
    assert seen and result["selected_tool"] == "rank_players_by_metric"
