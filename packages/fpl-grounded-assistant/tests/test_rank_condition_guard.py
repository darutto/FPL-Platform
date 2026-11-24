"""Brief 0a -- the season ranking must never answer a conditioned question.

Base behaviour (eb35eee4): ``rank_players_by_metric`` returned status ok with
SEASON totals for "puntos en las últimas 5 jornadas", "goles fuera de casa",
"xg last 4 gameweeks" and "puntos por millón". Every test below that asserts
the fix fails on the base: there, the ranking comes back with rows.

Synthetic data only (the conftest / STANDARD bootstraps), a fake Anthropic-
shaped client, no network and no paid call.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from types import SimpleNamespace as NS

import pytest

from conftest import BOOTSTRAP

from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant import rank_condition_guard as guard
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_CONDITION_NOT_APPLIED,
    OUTCOME_OK,
    ask_orchestrated,
)
from fpl_tool_runner import run_tool

STATUS = guard.STATUS_CONDITION_NOT_APPLIED


# ---------------------------------------------------------------------------
# 1. The detector: closed list, ES + EN
# ---------------------------------------------------------------------------

POSITIVES = [
    # single gameweek
    ("goles en la jornada 7", guard.KIND_SINGLE_GW),
    ("goles en la jornada siete", guard.KIND_SINGLE_GW),
    ("who scored most in GW7", guard.KIND_SINGLE_GW),
    ("most points gameweek 7", guard.KIND_SINGLE_GW),
    ("puntos en J7", guard.KIND_SINGLE_GW),
    ("puntos en la fecha 6", guard.KIND_SINGLE_GW),
    ("más puntos la jornada pasada", guard.KIND_SINGLE_GW),
    ("most points last gameweek", guard.KIND_SINGLE_GW),
    ("most points in gw 12", guard.KIND_SINGLE_GW),
    ("más puntos en la jornada próxima", guard.KIND_SINGLE_GW),
    ("puntos esta jornada", guard.KIND_SINGLE_GW),          # total_points is not current-GW
    ("points this gameweek", guard.KIND_SINGLE_GW),
    # last N
    ("puntos en las últimas 5 jornadas", guard.KIND_LAST_N),
    ("puntos en las últimas cinco jornadas", guard.KIND_LAST_N),
    ("xg last 4 gameweeks", guard.KIND_LAST_N),
    ("xg in the last four gameweeks", guard.KIND_LAST_N),
    ("goles en los últimos 3 partidos", guard.KIND_LAST_N),
    ("best points over the last five games", guard.KIND_LAST_N),
    ("puntos en las últimas jornadas", guard.KIND_LAST_N),
    ("points over recent gameweeks", guard.KIND_LAST_N),
    ("ULTIMAS 5 JORNADAS puntos", guard.KIND_LAST_N),
    # range
    ("puntos entre la jornada 4 y la 8", guard.KIND_RANGE),
    ("puntos de la jornada 4 a la 8", guard.KIND_RANGE),
    ("points from gw 4 to gw 8", guard.KIND_RANGE),
    ("points gw4-8", guard.KIND_RANGE),
    ("puntos desde la jornada 5", guard.KIND_RANGE),
    ("points since gameweek 5", guard.KIND_RANGE),
    ("puntos jornadas 3 y 4", guard.KIND_RANGE),
    # venue
    ("goles fuera de casa", guard.KIND_VENUE),
    ("goals away from home", guard.KIND_VENUE),
    ("goals away", guard.KIND_VENUE),
    ("puntos de visitante", guard.KIND_VENUE),
    ("puntos en casa", guard.KIND_VENUE),
    ("home goals", guard.KIND_VENUE),
    ("goles como local", guard.KIND_VENUE),
    # per million
    ("puntos por millón", guard.KIND_PER_MILLION),
    ("puntos por millon", guard.KIND_PER_MILLION),
    ("points per million", guard.KIND_PER_MILLION),
    ("points per £m", guard.KIND_PER_MILLION),
    ("puntos por libra", guard.KIND_PER_MILLION),
    ("best value for money", guard.KIND_PER_MILLION),
]


@pytest.mark.parametrize("text,kind", POSITIVES)
def test_detector_names_the_condition(text, kind):
    assert kind in guard.detect_conditions(text), text


NEGATIVES = [
    "los 5 mejores por xg",
    "top 5 por xg",
    "los 10 mejores goleadores",
    "top 10 by points",
    "máximo goleador esta temporada",
    "most points this season",
    "goles esperados por 90",
    "xg per 90",
    "defensive contributions per 90",
    "puntos por partido",
    "points per game",
    "points_per_game",
    "mejor puntos por partido hasta ahora",
    "en lo que va de temporada, más goles",
    "defensas de menos de 5 millones",
    "defensas por menos de 6 millones con más puntos",
    "tres defensas entre 4.5 y 6.0 millones",
    "centrocampistas entre 6 y 8 millones",
    "los 5 mejores delanteros por xgi",
    "porteros con más paradas",
    "top 5 clean sheets",
    "los más fichados",
    "dame 5 jugadores baratos",
    "more than 3 goals",
    "jugadores con más de 5 asistencias",
    "who has the most minutes",
    "garra",
]


@pytest.mark.parametrize("text", NEGATIVES)
def test_detector_stays_quiet(text):
    assert guard.detect_conditions(text) == (), text


def test_current_gameweek_words_are_allowed_only_for_current_gw_metrics():
    for text in ("transferencias esta jornada", "transfers in this gameweek", "más fichados esta jornada"):
        assert guard.detect_conditions(text, field="transfers_in_event") == ()
        assert guard.detect_conditions(text, field="transfers_out_event") == ()
        assert guard.KIND_SINGLE_GW in guard.detect_conditions(text, field="total_points")


def test_a_price_is_not_a_gameweek():
    # "gameweek 3 and 4.5m" -- the 4 is part of a price, so no range.
    kinds = guard.detect_conditions("jornada 3 y 4.5 millones")
    assert guard.KIND_RANGE not in kinds


KNOWN_MISSES = [  # listed in the PR: the closed list does not chase typos
    "puntos en la jornda 3",
    "ultmias 5 jornadas",
]


@pytest.mark.parametrize("text", KNOWN_MISSES)
def test_known_misses_are_documented_not_hidden(text):
    # Pinned so a future widening is a visible decision, not an accident.
    assert guard.detect_conditions(text) == ()


# ---------------------------------------------------------------------------
# 2. The handler: order of checks, fail-closed, switches
# ---------------------------------------------------------------------------

def _bs(question=None, raw=None, **extra):
    bs = copy.deepcopy(BOOTSTRAP)
    if question is not None:
        bs["_question"] = question
    if raw is not None:
        bs["_raw_question"] = raw
    bs.update(extra)
    return bs


def _names():
    return [e["web_name"] for e in BOOTSTRAP["elements"]]


def _assert_no_rows(out):
    assert out["status"] == STATUS
    assert "ranked" not in out
    blob = json.dumps(out)
    assert not any(n in blob for n in _names())


@pytest.mark.parametrize("metric", ["total_points", "puntos en las últimas 5 jornadas"])
@pytest.mark.parametrize("question", [
    "puntos en las últimas 5 jornadas", "xg last 4 gameweeks", "goles fuera de casa",
    "puntos por millón", "goles en la jornada 7", "points gameweeks 4 to 8",
])
def test_handler_refuses_a_conditioned_question(metric, question):
    out = run_tool("rank_players_by_metric", {"metric": metric, "top_n": 5}, _bs(question))
    _assert_no_rows(out)
    assert out["conditions"] and set(out["conditions"]) <= set(guard.CONDITION_KINDS)


def test_handler_serves_a_plain_ranking():
    out = run_tool("rank_players_by_metric", {"metric": "total_points", "top_n": 5}, _bs("los 5 mejores por puntos"))
    assert out["status"] == "ok" and out["ranked"]


def test_unknown_metric_is_validated_first_and_still_relayed():
    # The i15 bait: the metric is invented AND a gameweek is named.
    out = run_tool(
        "rank_players_by_metric", {"metric": "garra"}, _bs("Ranking de jugadores por garra en la jornada 3")
    )
    assert out["status"] == "invalid_argument" and out["code"] == "unknown_metric"


@pytest.mark.parametrize("metric,question", [
    ("transferencias de entrada esta jornada", "¿Quiénes son los más fichados? transferencias de entrada esta jornada"),
    ("transferencias de salida esta jornada", "más vendidos, transferencias de salida esta jornada"),
    ("transfers in this gameweek", "most transferred in this gameweek"),
])
def test_current_gw_transfer_momentum_is_still_served(metric, question):
    out = run_tool("rank_players_by_metric", {"metric": metric}, _bs(question))
    assert out["status"] == "ok" and out["metric"] in guard.CURRENT_GW_FIELDS


def test_price_and_position_filters_alone_change_nothing():
    out = run_tool(
        "rank_players_by_metric",
        {"metric": "total_points", "position": "DEF", "max_price": 6.0, "min_minutes": 900},
        _bs("Decime tres defensas entre 4.5 y 6.0 millones con más puntos"),
    )
    assert out["status"] == "ok"


def test_no_user_text_fails_closed_unless_an_internal_caller_opts_out():
    args = {"metric": "total_points"}
    out = run_tool("rank_players_by_metric", args, _bs())
    _assert_no_rows(out)
    assert out["conditions"] == [guard.REASON_NO_TEXT]
    assert run_tool("rank_players_by_metric", args, _bs(**{guard.OPT_OUT_KEY: True}))["status"] == "ok"


def test_only_a_literal_true_opts_out():
    for bad in ("true", 1, "yes"):
        out = run_tool("rank_players_by_metric", {"metric": "total_points"}, _bs(**{guard.OPT_OUT_KEY: bad}))
        assert out["status"] == STATUS


def test_the_raw_text_alone_is_enough_and_so_is_the_rewrite_alone():
    args = {"metric": "total_points"}
    raw_only = run_tool("rank_players_by_metric", args, _bs("ranking de puntos", raw="puntos últimas 5 jornadas"))
    rewrite_only = run_tool("rank_players_by_metric", args, _bs("puntos últimas 5 jornadas", raw="¿y los defensas?"))
    _assert_no_rows(raw_only)
    _assert_no_rows(rewrite_only)
    assert guard.rewrite_only_conditions(_bs("puntos últimas 5 jornadas", raw="¿y los defensas?"), "total_points")
    assert not guard.rewrite_only_conditions(_bs("x", raw="puntos últimas 5 jornadas"), "total_points")


def test_guard_off_is_a_switch_not_the_only_rollback(monkeypatch):
    monkeypatch.setenv("FPL_RANK_CONDITION_GUARD", "0")
    out = run_tool("rank_players_by_metric", {"metric": "total_points"}, _bs("puntos últimas 5 jornadas"))
    assert out["status"] == "ok"  # off means off: this is the documented base behaviour
    monkeypatch.setenv("FPL_RANK_SUPPRESS", "1")  # the independent switch still hides it
    out = run_tool("rank_players_by_metric", {"metric": "total_points"}, _bs("puntos últimas 5 jornadas"))
    _assert_no_rows(out)


def test_suppress_hides_every_ranking_even_a_plain_one(monkeypatch):
    monkeypatch.setenv("FPL_RANK_SUPPRESS", "1")
    out = run_tool("rank_players_by_metric", {"metric": "total_points"}, _bs("los 5 mejores por puntos"))
    _assert_no_rows(out)
    assert out["conditions"] == [guard.REASON_SUPPRESSED]


def test_suppress_works_even_when_the_guard_code_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("guard bug")

    monkeypatch.setattr(guard, "detect_conditions", boom)
    monkeypatch.setattr(guard, "evaluate", boom)
    monkeypatch.setattr(guard, "guard_enabled", boom)
    monkeypatch.setenv("FPL_RANK_SUPPRESS", "1")
    out = run_tool("rank_players_by_metric", {"metric": "total_points"}, _bs("puntos últimas 5 jornadas"))
    _assert_no_rows(out)


def test_a_guard_that_raises_never_produces_the_season_table(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("guard bug")

    monkeypatch.setattr(guard, "detect_conditions", boom)
    out = run_tool("rank_players_by_metric", {"metric": "total_points"}, _bs("puntos últimas 5 jornadas"))
    _assert_no_rows(out)
    assert out["conditions"] == [guard.REASON_GUARD_ERROR]


# -- the position the user did not name ------------------------------------

def test_a_position_the_user_did_not_name_is_dropped_on_a_fresh_turn():
    out = run_tool(
        "rank_players_by_metric",
        {"metric": "total_points", "position": "DEF"},
        _bs("¿Quiénes tienen más puntos?"),
    )
    assert out["status"] == "ok"
    assert out["position_filter"] is None and out["position_dropped"] == "DEF"
    assert len({e["position"] for e in out["ranked"]}) > 1 or len(out["ranked"]) >= 1


@pytest.mark.parametrize("text", [
    "los mejores defensas por puntos", "mejores porteros", "laterales con más xg", "mejores zagueros",
    "extremos con más puntos", "best goalies", "top strikers by xg", "best wingers", "top backs",
    "atacantes baratos", "mediapuntas con más xgi", "centrales con más puntos",
])
def test_a_named_position_in_any_form_is_kept(text):
    out = run_tool("rank_players_by_metric", {"metric": "total_points", "position": "DEF"}, _bs(text))
    assert out["status"] == "ok" and out["position_filter"] == "DEF" and "position_dropped" not in out


def test_a_position_is_kept_when_a_session_turn_has_prior_context():
    out = run_tool(
        "rank_players_by_metric",
        {"metric": "expected_goals", "position": "DEF"},
        _bs("¿y por xG?", **{guard.PRIOR_CONTEXT_KEY: True}),
    )
    assert out["position_filter"] == "DEF" and "position_dropped" not in out


def test_a_position_is_kept_when_there_is_no_user_text():
    out = run_tool(
        "rank_players_by_metric",
        {"metric": "total_points", "position": "DEF"},
        _bs(**{guard.OPT_OUT_KEY: True}),
    )
    assert out["position_filter"] == "DEF"


# ---------------------------------------------------------------------------
# 3. The orchestrator: the line owns the turn, in both flows
# ---------------------------------------------------------------------------

def _usage():
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


def _tool_use(*calls):
    blocks = [NS(type="tool_use", id=f"toolu_{i}", name=name, input=args) for i, (name, args) in enumerate(calls)]
    return NS(content=blocks, stop_reason="tool_use", usage=_usage())


def _text(text):
    return NS(content=[NS(type="text", text=text)] if text else [], stop_reason="end_turn", usage=_usage())


class _Client:
    def __init__(self, *responses, default=None):
        self.messages = self
        self.queue = list(responses)
        self.default = default
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        if self.queue:
            return self.queue.pop(0)
        return self.default if self.default is not None else _text("")


@pytest.fixture(params=["legacy", "loop"])
def flow(request, monkeypatch):
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    if request.param == "loop":
        monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    else:
        monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    return request.param


RANK = ("rank_players_by_metric", {"metric": "total_points", "top_n": 5})


def _ask(question, client, **kw):
    return ask_orchestrated(
        question, copy.deepcopy(BOOTSTRAP), client=client, provider="anthropic", _eval_client=kw.pop("eval_client", None),
        **kw,
    )


def test_the_only_tool_refused_ends_the_turn_with_the_line_and_one_provider_call(flow):
    # Replies that would invite a list if the loop went on.
    client = _Client(_tool_use(RANK), default=_text("1. Haaland 2. Salah 3. Palmer"))
    result = _ask("puntos en las últimas 5 jornadas", client)
    assert client.calls == 1  # no synthesis, no extra round
    assert result.outcome == OUTCOME_CONDITION_NOT_APPLIED
    assert result.answer_text == guard.guard_line({"conditions": [guard.KIND_LAST_N]}, "es")
    assert "ranked" not in result.tool_output and result.tool_output["status"] == STATUS
    assert "Haaland" not in result.answer_text and "1." not in result.answer_text


def test_english_line(flow):
    client = _Client(_tool_use(RANK))
    result = _ask("xg last 4 gameweeks", client, locale="en")
    assert result.outcome == OUTCOME_CONDITION_NOT_APPLIED
    assert result.answer_text.startswith("I can't apply")
    assert "last few gameweeks" in result.answer_text


def test_a_plain_ranking_is_unchanged(flow):
    client = _Client(_tool_use(RANK), _text("Aquí tienes el top."))
    result = _ask("los 5 mejores por puntos", client)
    assert result.outcome == OUTCOME_OK and result.tool_output["status"] == "ok"
    assert client.calls == 2


def test_beside_another_answer_the_other_tool_keeps_the_slot_and_code_appends_the_line(flow):
    client = _Client(
        _tool_use(("get_gameweek_context", {}), RANK),
        _text("La jornada actual es la 5."),
    )
    result = _ask("partidos del Fulham y puntos en las últimas 5 jornadas", client)
    assert result.outcome == OUTCOME_OK and result.tool_chosen == "get_gameweek_context"
    line = guard.guard_line({"conditions": [guard.KIND_LAST_N]}, "es")
    assert result.answer_text == f"La jornada actual es la 5.\n\n{line}"
    guarded = [e for e in result.tool_calls_trace if e["name"] == RANK[0]]
    assert guarded and all(e["output"]["status"] == STATUS and "ranked" not in e["output"] for e in guarded)
    assert "Haaland" not in json.dumps(result.tool_calls_trace, default=str)


def test_an_extra_round_that_asks_for_the_ranking_again_meets_the_same_guard(flow):
    # Round 1 answers with another tool; the synthesis then asks for the ranking
    # (a no-text response carrying a tool call buys one bounded extra round).
    client = _Client(
        _tool_use(("get_gameweek_context", {})),
        _tool_use(RANK),
        _text("Resumen."),
        default=_text("Resumen."),
    )
    result = _ask("partidos del Fulham y goles fuera de casa", client)
    names = [e for e in result.tool_calls_trace if e["name"] == RANK[0]]
    assert all(e["output"]["status"] == STATUS for e in names)
    assert "ranked" not in json.dumps(result.tool_calls_trace, default=str)
    assert not any("Haaland" in (result.answer_text or "") for _ in [0])


def test_an_evaluator_retry_that_calls_the_ranking_meets_the_same_guard(flow, monkeypatch):
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    verdict = EvaluatorVerdict(approved=False, grounded=False, complete=False, safe=True,
                               retry_feedback="Incluye el ranking.", tokens_used=5)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kw: verdict)
    client = _Client(
        _tool_use(("get_gameweek_context", {})),
        _text("La jornada actual es la 5."),
        _tool_use(RANK),                      # the retry asks for the ranking
        _text("Aquí va el ranking: 1. Haaland."),
        default=_text("Aquí va el ranking: 1. Haaland."),
    )
    result = _ask("partidos del Fulham y puntos en las últimas 5 jornadas", client, eval_client=object())
    retried = [e for e in result.tool_calls_trace if e["name"] == RANK[0]]
    assert all(e["output"]["status"] == STATUS and "ranked" not in e["output"] for e in retried)
    assert guard.guard_line({"conditions": [guard.KIND_LAST_N]}, "es") in result.answer_text


def test_a_ranking_used_as_a_support_call_for_a_fixture_question_is_not_ended_by_the_guard(flow):
    # "...para la fecha 6": the ranking is support, the other tool answers.
    client = _Client(
        _tool_use(("get_gameweek_context", {}), RANK),
        _text("Jornada 6 en camino."),
    )
    result = _ask("jugadores del Fulham para la fecha 6", client)
    assert result.outcome == OUTCOME_OK and result.tool_chosen == "get_gameweek_context"
    assert "Jornada 6 en camino." in result.answer_text


def test_the_loop_and_legacy_flows_agree_on_the_honest_turn(monkeypatch):
    out = {}
    for mode in ("legacy", "loop"):
        monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
        if mode == "loop":
            monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
        else:
            monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
        r = _ask("goles fuera de casa", _Client(_tool_use(RANK)))
        out[mode] = (r.outcome, r.answer_text, r.tool_output)
    assert out["legacy"] == out["loop"]


# ---------------------------------------------------------------------------
# 4. The routes: /ask and /session, ES + EN, kept-in-metric and bare metric
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [_PKG] + [
    os.path.join(_PKGS, p) for p in (
        "fpl-api-client", "fpl-data-core", "fpl-player-registry", "fpl-query-tools",
        "fpl-tool-contract", "fpl-tool-runner", "fpl-captain-engine",
    )
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fastapi.testclient import TestClient  # noqa: E402

import fpl_server  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402

ROUTE_CASES = [
    # (locale, question, metric kept in the model's call, kind expected)
    ("es", "puntos en las últimas 5 jornadas", "puntos en las últimas 5 jornadas", guard.KIND_LAST_N),
    ("es", "puntos en las últimas 5 jornadas", "total_points", guard.KIND_LAST_N),
    ("en", "xg last 4 gameweeks", "xg last 4 gameweeks", guard.KIND_LAST_N),
    ("en", "xg last 4 gameweeks", "expected_goals", guard.KIND_LAST_N),
    ("es", "goles en la jornada 7", "goals_scored", guard.KIND_SINGLE_GW),
    ("en", "most goals in GW7", "total_points", guard.KIND_SINGLE_GW),
    ("es", "puntos de la jornada 4 a la 8", "total_points", guard.KIND_RANGE),
    ("en", "points from gw 4 to gw 8", "total_points", guard.KIND_RANGE),
    ("es", "goles fuera de casa", "goals_scored", guard.KIND_VENUE),
    ("en", "away goals", "goals_scored", guard.KIND_VENUE),
    ("es", "puntos por millón", "total_points", guard.KIND_PER_MILLION),
    ("en", "points per million", "total_points", guard.KIND_PER_MILLION),
]


@pytest.fixture
def server(monkeypatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


@pytest.fixture
def fake_model(monkeypatch):
    """Route the real orchestrator to a fake model that emits one ranking call."""
    state = {"client": None, "metric": "total_points", "seen": []}
    real = orch_mod.ask_orchestrated

    def _wrapped(question, bootstrap, **kw):
        state["seen"].append(question)
        client = _Client(_tool_use(("rank_players_by_metric", {"metric": state["metric"], "top_n": 5})),
                         default=_text("1. " + STANDARD_BOOTSTRAP["elements"][0]["web_name"]))
        state["client"] = client
        kw["client"] = client
        kw["provider"] = "anthropic"
        kw.pop("api_key", None)
        kw["_eval_client"] = None
        return real(question, bootstrap, **kw)

    monkeypatch.setattr(orch_mod, "ask_orchestrated", _wrapped)
    return state


def _player_names():
    return [e["web_name"] for e in STANDARD_BOOTSTRAP["elements"]]


def _check_honest_body(body, locale):
    assert body["outcome"] == "condition_not_applied"
    assert body["supported"] is False          # not counted as an answered question
    assert body["review_passed"] is False      # never claims a reviewed answer
    for card in ("generic_card", "comparison", "captain", "captain_ranking", "player_snapshot", "differential"):
        assert not body.get(card), card
    assert body["final_text"].startswith("I can't apply" if locale == "en" else "No puedo aplicar")
    blob = json.dumps(body, ensure_ascii=False)
    assert not any(n in blob for n in _player_names())  # no rows, no order, anywhere


@pytest.mark.parametrize("locale,question,metric,kind", ROUTE_CASES)
def test_ask_route_returns_the_honest_line(server, fake_model, locale, question, metric, kind):
    fake_model["metric"] = metric
    r = server.post("/ask", json={"question": question, "locale": locale}, headers={"X-User-Id": "g-ask"})
    assert r.status_code == 200
    _check_honest_body(r.json(), locale)
    assert fake_model["client"].calls == 1


@pytest.mark.parametrize("locale,question,metric,kind", ROUTE_CASES)
def test_session_route_returns_the_honest_line(server, fake_model, locale, question, metric, kind):
    fake_model["metric"] = metric
    sid = server.post("/session").json()["session_id"]
    r = server.post(f"/session/{sid}/ask", json={"question": question, "locale": locale}, headers={"X-User-Id": "g-sess"})
    assert r.status_code == 200
    _check_honest_body(r.json(), locale)
    assert fake_model["client"].calls == 1


def test_both_routes_serialize_the_honest_turn_the_same(server, fake_model):
    q = "puntos en las últimas 5 jornadas"
    a = server.post("/ask", json={"question": q}, headers={"X-User-Id": "g-a"}).json()
    sid = server.post("/session").json()["session_id"]
    s = server.post(f"/session/{sid}/ask", json={"question": q}, headers={"X-User-Id": "g-s"}).json()
    for key in ("outcome", "supported", "review_passed", "final_text", "intent", "generic_card"):
        assert a.get(key) == s.get(key), key


def test_ask_route_hands_ask_v2_the_question_exactly_as_typed(server, fake_model, monkeypatch):
    # ``effective_question`` may be an intent_hint rewrite; the raw text travels
    # on its own key. (ask_v2 itself with a rewrite: the next test.)
    from fpl_grounded_assistant import harness

    seen = {}
    real = harness.ask_v2

    def _spy(question, bootstrap, **kw):
        seen["question"], seen["raw"] = question, kw.get("raw_question")
        return real(question, bootstrap, **kw)

    monkeypatch.setattr(harness, "ask_v2", _spy)
    r = server.post("/ask", json={"question": "puntos en las últimas 5 jornadas"}, headers={"X-User-Id": "g-h"})
    assert r.status_code == 200
    assert seen["raw"] == "puntos en las últimas 5 jornadas"


def test_session_route_hands_ask_v2_the_raw_text_and_the_prior_context_flag(server, fake_model, monkeypatch):
    from fpl_grounded_assistant import harness

    seen = []
    real = harness.ask_v2

    def _spy(question, bootstrap, **kw):
        seen.append((question, kw.get("raw_question"), kw.get("prior_context")))
        return real(question, bootstrap, **kw)

    monkeypatch.setattr(harness, "ask_v2", _spy)
    sid = server.post("/session").json()["session_id"]
    server.post(f"/session/{sid}/ask", json={"question": "puntos en las últimas 5 jornadas"}, headers={"X-User-Id": "g-p1"})
    server.post(f"/session/{sid}/ask", json={"question": "¿y los defensas?"}, headers={"X-User-Id": "g-p1"})
    assert [(raw, prior) for _q, raw, prior in seen][:1] == [("puntos en las últimas 5 jornadas", False)]
    assert seen[-1][1] == "¿y los defensas?" and seen[-1][2] is True


def test_a_session_follow_up_fires_on_the_resolvers_rewrite(server, fake_model):
    from fpl_grounded_assistant.harness import ask_v2

    fake_model["metric"] = "total_points"
    result = ask_v2(
        "puntos en las últimas 5 jornadas de los defensas",   # what the resolver produced
        copy.deepcopy(STANDARD_BOOTSTRAP),
        raw_question="¿y los defensas?",                      # what the user typed
        prior_context=True,
    )
    assert result["outcome"] == "condition_not_applied"
    assert "ranked" not in result["raw_output"]


def test_ask_v2_without_raw_text_falls_back_to_the_question_never_to_the_table(server, fake_model):
    from fpl_grounded_assistant.harness import ask_v2

    result = ask_v2("puntos en las últimas 5 jornadas", copy.deepcopy(STANDARD_BOOTSTRAP))
    assert result["outcome"] == "condition_not_applied"


def test_the_audit_projection_records_the_kind_as_an_enum(server, fake_model):
    from fpl_grounded_assistant.audit import tool_calls_from_ask_v2
    from fpl_grounded_assistant.harness import ask_v2

    result = ask_v2("goles fuera de casa", copy.deepcopy(STANDARD_BOOTSTRAP))
    calls = tool_calls_from_ask_v2(result)
    assert calls and calls[0]["output_status"] == STATUS
    assert calls[0]["guard_conditions"] == [guard.KIND_VENUE]
    assert result["routing_trace"]["grounded"] is False
    assert result["routing_trace"]["branch"] == "orchestrator_condition_guard"


def test_telemetry_counts_the_turn_without_calling_it_grounded(server, fake_model):
    from fpl_grounded_assistant import telemetry
    from fpl_grounded_assistant.harness import ask_v2

    telemetry.reset() if hasattr(telemetry, "reset") else None
    before = telemetry.snapshot()
    ask_v2("goles fuera de casa", copy.deepcopy(STANDARD_BOOTSTRAP))
    after = telemetry.snapshot()
    assert after["orchestrator_condition_guard"] == before["orchestrator_condition_guard"] + 1
    assert after["orchestrator_grounded"] == before["orchestrator_grounded"]
    assert after["unsupported"] == before["unsupported"]


# ---------------------------------------------------------------------------
# 5. The schema texts, together
# ---------------------------------------------------------------------------

def test_goals_in_one_gameweek_has_no_tool_and_never_points():
    from fpl_grounded_assistant.historical_gameweek_top_scorer import GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC
    from fpl_grounded_assistant.tool_schema_registry import GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SCHEMA

    for text in (GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SCHEMA.description, GET_HISTORICAL_GAMEWEEK_TOP_SCORER_SPEC.description):
        low = text.lower()
        assert "even when a gameweek is named" not in low
        assert "no tool" in low                      # goals in ONE gameweek: say so
        assert "never answer with points" in low     # the i82 protection survives
        assert "whole season" in low                 # season goals still have a tool
    assert "even when a gameweek is named" not in orch_mod._SYSTEM_PROMPT.lower()
    # The system prompt is unchanged (its ES bytes are pinned): the guard holds
    # without any prompt text, and the i15 override keeps its protection.
    assert "not choose a gameweek tool" in orch_mod._SYSTEM_PROMPT
    assert "code=unknown_metric" in orch_mod._SYSTEM_PROMPT
