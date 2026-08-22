"""``tool_calls_trace`` records every executed tool call, in every arm.

Before this suite, only the bounded-loop path (arms C/D) attached a trace:
``_apply_evaluator`` accepted ``tool_calls_trace`` for the evaluator prompt and
for ``tool_call_count``, but never copied it onto the ``OrchestratorResult`` it
returned.  The loop compensated by overwriting the field afterwards, so the
legacy single-round path (arms A/B) silently shipped an empty trace and the
only visible tool was ``tool_chosen`` -- i.e. ``executed[0]``, the FIRST tool
of the round.

These tests pin the additive contract:
  * every executed call is in the trace, in execution order, loop or not;
  * failed calls (non-ok status, raising handlers) stay visible;
  * ``tool_chosen`` / ``tool_args`` / ``tool_output`` keep their old values;
  * loop traces are byte-identical to the recorded pre-change example.

Deterministic: fake provider clients only, no network.
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [
    _PKG,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fpl_grounded_assistant import provider_client  # noqa: E402
from fpl_grounded_assistant.evaluator import EvaluatorVerdict  # noqa: E402
import fpl_grounded_assistant.orchestrator as orch  # noqa: E402
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_OK,
    OUTCOME_TOOL_ERROR,
    OUTCOME_TOOL_RESULT_ERROR,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    ask_orchestrated,
)

# The sibling suite already models every provider's wire shape; reuse it rather
# than re-deriving three sets of response fakes.
from test_multi_provider_follow_up import (  # noqa: E402
    _AnthropicClient,
    _GeminiClient,
    _OpenAIClient,
    _SequenceClient,
    _action_response,
    _text_response,
)

#: Key order of a trace entry, as produced by the loop path.
_TRACE_KEYS = ["round", "tool_call_id", "name", "args", "output", "success"]


def _disable_loop(monkeypatch):
    """Arms A/B: legacy single-round path."""
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)
    monkeypatch.setattr(provider_client, "_GEMINI_AVAILABLE", True)


def _enable_loop(monkeypatch, rounds: int = 3):
    """Arms C/D: cumulative bounded loop."""
    monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", str(rounds))
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)
    monkeypatch.setattr(provider_client, "_GEMINI_AVAILABLE", True)


# ---------------------------------------------------------------------------
# 1. Single-tool turn, loop OFF
# ---------------------------------------------------------------------------

def test_non_loop_single_tool_records_a_one_entry_trace(monkeypatch, bootstrap):
    _disable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "ant-only", "get_current_gameweek", {}),
    ])

    result = ask_orchestrated(
        "What gameweek is it?", bootstrap, client=client, _eval_client=None
    )

    assert result.outcome == OUTCOME_OK
    assert len(result.tool_calls_trace) == 1
    entry = result.tool_calls_trace[0]
    assert list(entry) == _TRACE_KEYS
    assert entry["name"] == result.tool_chosen == "get_current_gameweek"
    assert entry["args"] == result.tool_args == {}
    assert entry["output"] == result.tool_output
    assert entry["round"] == 1
    assert entry["tool_call_id"] == "ant-only"
    assert entry["success"] is True
    assert result.tool_call_count == 1


# ---------------------------------------------------------------------------
# 2. Multi-tool turn, loop OFF -- the case that is invisible without the fix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("provider", "client_factory", "call_ids"),
    [
        (PROVIDER_ANTHROPIC, _AnthropicClient, ["ant-1", "ant-2"]),
        (PROVIDER_OPENAI, _OpenAIClient, ["oai-1", "oai-2"]),
        # Gemini has no wire-level call ids; the parser synthesises positional ones.
        (PROVIDER_GEMINI, _GeminiClient, ["gemini_call_0", "gemini_call_1"]),
    ],
)
def test_non_loop_multi_tool_records_every_executed_call(
    monkeypatch, bootstrap, provider, client_factory, call_ids
):
    _disable_loop(monkeypatch)
    client = client_factory()

    result = ask_orchestrated(
        "What gameweek is it and who is Salah?",
        bootstrap,
        provider=provider,
        client=client,
        api_key="test-key",
        _eval_client=None,
    )

    assert result.outcome == OUTCOME_OK
    # Both calls executed in one round; both must be recorded, in order.
    assert [e["name"] for e in result.tool_calls_trace] == [
        "get_current_gameweek", "get_player_snapshot",
    ]
    assert [e["args"] for e in result.tool_calls_trace] == [
        {}, {"player_name": "Salah"},
    ]
    assert [e["round"] for e in result.tool_calls_trace] == [1, 1]
    assert [e["tool_call_id"] for e in result.tool_calls_trace] == call_ids
    assert all(list(e) == _TRACE_KEYS for e in result.tool_calls_trace)
    # Unchanged legacy fields: still the FIRST executed call.
    assert result.tool_chosen == "get_current_gameweek"
    assert result.tool_args == {}
    assert result.tool_output == result.tool_calls_trace[0]["output"]
    assert result.tool_call_count == 2


def test_non_loop_multi_tool_fallback_still_records_every_call(monkeypatch, bootstrap):
    """Second synthesis call yields no text -> renderer fallback path."""
    _disable_loop(monkeypatch)
    client = _AnthropicClient(second_text=None)

    result = ask_orchestrated(
        "What gameweek is it and who is Salah?",
        bootstrap,
        client=client,
        _eval_client=None,
    )

    assert [e["name"] for e in result.tool_calls_trace] == [
        "get_current_gameweek", "get_player_snapshot",
    ]
    assert result.tool_chosen == "get_current_gameweek"
    assert result.tool_output == result.tool_calls_trace[0]["output"]


# ---------------------------------------------------------------------------
# 3. Failing calls stay visible
# ---------------------------------------------------------------------------

def test_non_loop_non_ok_tool_status_is_recorded(monkeypatch, bootstrap):
    _disable_loop(monkeypatch)
    # get_player_snapshot without player_name -> non-ok status, not an exception.
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "bad-1", "get_player_snapshot", {}),
    ])

    result = ask_orchestrated("who?", bootstrap, client=client, _eval_client=None)

    assert result.outcome == OUTCOME_TOOL_RESULT_ERROR
    assert len(result.tool_calls_trace) == 1
    entry = result.tool_calls_trace[0]
    assert entry["name"] == "get_player_snapshot"
    assert entry["output"]["status"] != "ok"
    assert entry["success"] is False
    assert entry["output"] == result.tool_output


def test_non_loop_raising_tool_is_recorded_with_earlier_calls(monkeypatch, bootstrap):
    """A handler that raises must not erase the round's executed calls."""
    _disable_loop(monkeypatch)
    original = orch.run_tool
    seen = 0

    def flaky_run_tool(name, args, supplied_bootstrap):
        nonlocal seen
        seen += 1
        if seen == 2:
            raise RuntimeError("handler exploded")
        return original(name, args, supplied_bootstrap)

    monkeypatch.setattr(orch, "run_tool", flaky_run_tool)
    client = _AnthropicClient()

    result = ask_orchestrated(
        "What gameweek is it and who is Salah?",
        bootstrap,
        client=client,
        _eval_client=None,
    )

    assert result.outcome == OUTCOME_TOOL_ERROR
    assert [e["name"] for e in result.tool_calls_trace] == [
        "get_current_gameweek", "get_player_snapshot",
    ]
    assert result.tool_calls_trace[0]["success"] is True
    failed = result.tool_calls_trace[1]
    assert failed["success"] is False
    assert failed["output"]["status"] == "error"
    assert failed["output"]["code"] == "tool_exception"
    assert "handler exploded" in failed["output"]["message"]
    # Unchanged legacy fields for this early return.
    assert result.tool_chosen == "get_player_snapshot"
    assert result.tool_output == {}
    assert result.error == "handler exploded"


@pytest.mark.parametrize("approved", [True, False])
def test_non_loop_trace_survives_the_evaluator(monkeypatch, bootstrap, approved):
    """Arms A/B run with an evaluator client and FPL_ORCH_EVAL_VERDICT_ONLY=1.

    Both the approval branch and the verdict-only rejection branch must carry
    the trace; they are separate return sites inside ``_apply_evaluator``.
    """
    _disable_loop(monkeypatch)
    monkeypatch.setenv("FPL_ORCH_EVAL_VERDICT_ONLY", "1")
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    verdict = EvaluatorVerdict(
        approved=approved,
        grounded=True,
        complete=approved,
        safe=True,
        retry_feedback=None if approved else "answer every requested part",
        tokens_used=17,
    )
    monkeypatch.setattr(orch, "evaluate_response", lambda **kwargs: verdict)
    client = _AnthropicClient()

    result = ask_orchestrated(
        "What gameweek is it and who is Salah?",
        bootstrap,
        client=client,
        _eval_client=object(),
    )

    assert result.evaluator_verdict is verdict
    assert result.retry_attempted is False
    assert [e["name"] for e in result.tool_calls_trace] == [
        "get_current_gameweek", "get_player_snapshot",
    ]
    assert result.tool_chosen == "get_current_gameweek"
    assert result.tool_output == result.tool_calls_trace[0]["output"]


def test_non_loop_unknown_tool_records_nothing_because_nothing_ran(
    monkeypatch, bootstrap
):
    _disable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "bad-1", "invented_tool", {}),
    ])

    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)

    assert result.tool_chosen == "invented_tool"
    assert result.tool_calls_trace == ()


# ---------------------------------------------------------------------------
# 4/5. Loop arms unchanged
# ---------------------------------------------------------------------------

#: Recorded from the bounded-loop path BEFORE this change, on the frozen
#: ``conftest.BOOTSTRAP``.  Any diff here means arm C/D observability moved,
#: which this change must not do.  If ``get_player_snapshot``'s payload schema
#: legitimately changes later, re-record this literal in the SAME commit as that
#: schema change -- never as a side effect of an orchestrator edit.
RECORDED_LOOP_TRACE = [
    {'round': 1,
     'tool_call_id': 'call-1',
     'name': 'get_current_gameweek',
     'args': {},
     'output': {'status': 'ok', 'gameweek': 28},
     'success': True},
    {'round': 2,
     'tool_call_id': 'call-2',
     'name': 'get_player_snapshot',
     'args': {'player_name': 'Salah'},
     'output': {'status': 'ok',
                'player': {'id': 2,
                           'web_name': 'Salah',
                           'team_short': 'LIV',
                           'position': 'MID',
                           'minutes_played_season': 0,
                           'status': 'Available',
                           'news': '',
                           'news_added': None,
                           'chance_of_playing_this_round': None,
                           'form': 9.5,
                           'total_points': 0,
                           'points_per_game': 0.0,
                           'expected_goals': 0.9,
                           'expected_assists': 0.55,
                           'expected_goal_involvements': 1.45,
                           'expected_goals_conceded': 0.0,
                           'ict_index': 0.0,
                           'influence': 0.0,
                           'creativity': 0.0,
                           'threat': 0.0,
                           'saves': 0,
                           'yellow_cards': 0,
                           'red_cards': 0,
                           'expected_goals_per_90': 0.0,
                           'expected_assists_per_90': 0.0,
                           'expected_goal_involvements_per_90': 0.0,
                           'ict_index_per_90': 0.0,
                           'defensive_contribution': 0,
                           'defensive_contribution_per_90': 0.0,
                           'now_cost': 135,
                           'selected_by_percent': 64.1,
                           'transfers_in_event': 0,
                           'transfers_out_event': 0,
                           'penalties_order': None,
                           'direct_freekicks_order': None,
                           'corners_and_indirect_freekicks_order': None,
                           'fixtures': [],
                           'team_fdr_context': None}},
     'success': True},
]


def test_loop_trace_is_byte_identical_to_recorded_example(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "call-1", "get_current_gameweek", {}),
        _action_response(
            PROVIDER_ANTHROPIC, "call-2", "get_player_snapshot", {"player_name": "Salah"}
        ),
        _text_response(PROVIDER_ANTHROPIC, "final answer"),
    ])

    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)

    assert result.outcome == OUTCOME_OK
    assert result.rounds_used == 2
    assert list(result.tool_calls_trace) == RECORDED_LOOP_TRACE
    # 5. Loop legacy fields unchanged: on convergence the FIRST successful call
    #    is the retained payload (``successful[0]``), while the trace holds all.
    assert result.tool_chosen == "get_current_gameweek"
    assert result.tool_args == {}
    assert result.tool_output == RECORDED_LOOP_TRACE[0]["output"]
    assert result.answer_text == "final answer"
    assert result.tool_call_count == 2
