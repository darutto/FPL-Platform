"""Regression coverage for metric-ranking tool selection and error relay."""

from __future__ import annotations

from fpl_grounded_assistant.orchestrator import (
    OUTCOME_OK,
    OUTCOME_TOOL_RESULT_ERROR,
    _SYSTEM_PROMPT,
    ask_orchestrated,
)


class _RankMetricClient:
    """Anthropic-shaped client that follows the metric-routing prompt."""

    def __init__(self, metric: str) -> None:
        self.metric = metric
        self.messages = self
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        block = type(
            "_ToolBlock",
            (),
            {
                "type": "tool_use",
                "id": "toolu_rank_metric",
                "name": "rank_players_by_metric",
                "input": {"metric": self.metric, "top_n": 5},
            },
        )()
        return type(
            "_Response",
            (),
            {"content": [block], "stop_reason": "tool_use"},
        )()


def _ask(monkeypatch, bootstrap, question: str, metric: str):
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    client = _RankMetricClient(metric)
    result = ask_orchestrated(
        question,
        bootstrap,
        client=client,
        provider="anthropic",
        _eval_client=None,
    )
    return result, client


def test_prompt_routes_every_metric_ranking_through_rank_tool_first():
    assert "RANKING-BY-METRIC OVERRIDE (highest tool-routing priority)" in _SYSTEM_PROMPT
    assert "call rank_players_by_metric FIRST and as the ONLY tool" in _SYSTEM_PROMPT
    assert "even when the metric" in _SYSTEM_PROMPT
    assert "code=unknown_metric" in _SYSTEM_PROMPT
    assert "not choose a gameweek tool" in _SYSTEM_PROMPT


def test_unknown_metric_is_relayed_instead_of_using_unrelated_tool(monkeypatch, bootstrap):
    result, client = _ask(
        monkeypatch,
        bootstrap,
        "Dame los 5 mejores jugadores por duelos aéreos ganados",
        "aerial_duels_won",
    )

    # G3 raw-dump fix: a single tool call now always gets a synthesis-turn
    # attempt too. This fake client returns the same tool_use block on every
    # call, so the synthesis call has no text and falls back to the primary
    # tool's own output/error below, unaffected -- only the call count changes.
    # i46 adds one more: a synthesis response carrying a tool call now buys a
    # single bounded extra round, which this fake answers with a tool call
    # again, so the turn still ends on the render. What this test is about --
    # which metric the model routed to -- is untouched.
    assert client.calls == 3
    assert result.tool_chosen == "rank_players_by_metric"
    # 2, not 1: i46's extra round ran the same tool a second time, and
    # tool_call_count reports executed calls, not distinct tools. The routing
    # assertion above is the one this test is about.
    assert result.tool_call_count == 2
    assert result.outcome == OUTCOME_TOOL_RESULT_ERROR
    assert result.tool_output["code"] == "unknown_metric"
    # i46 (c): the tool's own message still reaches the user verbatim, now
    # behind a notice saying the model did not write it. Stripped rather than
    # matched loosely, so a future wrapper around the message would still fail.
    from fpl_grounded_assistant.catalogue import t as _t
    _prefix = _t("orchestrator.raw_render_notice", "es") + "\n\n"
    assert result.answer_text.startswith(_prefix)
    assert result.answer_text[len(_prefix):] == result.tool_output["message"]
    assert "aerial_duels_won" in result.answer_text.lower()
    assert "not recognized" in result.answer_text.lower()
    assert "gameweek" not in result.answer_text.lower()


def test_misspelled_metric_still_uses_unique_prefix_match(monkeypatch, bootstrap):
    result, client = _ask(
        monkeypatch,
        bootstrap,
        "Top 5 por expected goal involvement",
        "expected_goal_involvement",
    )

    # G3 raw-dump fix + i46's extra round: see the comment in the previous
    # test -- the fake client's synthesis-call response has no text but does
    # carry a tool call, so the bounded extra round fires and the turn ends on
    # the render. Unaffected apart from the call count.
    assert client.calls == 3
    assert result.tool_chosen == "rank_players_by_metric"
    # 2, not 1: i46's extra round ran the same tool a second time, and
    # tool_call_count reports executed calls, not distinct tools. The routing
    # assertion above is the one this test is about.
    assert result.tool_call_count == 2
    assert result.outcome == OUTCOME_OK
    assert result.tool_output["status"] == "ok"
    assert result.tool_output["metric"] == "expected_goal_involvements"
    assert "expected_goal_involvements" in result.answer_text
