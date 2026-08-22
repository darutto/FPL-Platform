"""Selection of the partial answer when the bounded loop ends without one.

The rule under test is ``orchestrator._select_partial``. It is imported from the
module under test -- never redefined here -- so that a passing run is evidence
about production code.

Fixtures are reconstructed from a real recorded observation
(``field-notes/GEMINI-cap5.json``) rather than hand-built, because the payload
shapes the renderer sees in production are not obvious from the outside.
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
_REPO = os.path.dirname(_PKGS)
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

from fpl_grounded_assistant.orchestrator import _select_partial  # noqa: E402
from fpl_grounded_assistant.renderer import render  # noqa: E402

_OBSERVATIONS = os.path.join(_REPO, "field-notes", "GEMINI-cap5.json")


def _recorded_successful(scenario: str):
    """Rebuild the orchestrator's ``successful`` list from a recorded trace."""
    assert os.path.exists(_OBSERVATIONS), (
        "missing recorded observations at %s -- this test asserts against real "
        "payload shapes and must not silently skip" % _OBSERVATIONS
    )
    with open(_OBSERVATIONS, encoding="utf-8") as fh:
        rows = json.load(fh)
    for row in rows:
        if row.get("scenario") != scenario or not row.get("rounds_exhausted"):
            continue
        successful = [
            (e.get("tool_call_id"), e.get("name"), e.get("args") or {}, e.get("output") or {})
            for e in (row.get("tool_calls_trace") or [])
            if e.get("success")
        ]
        if successful:
            return successful
    raise AssertionError("no exhausted observation with successes for %r" % scenario)


def test_single_success_is_returned_unchanged():
    successful = _recorded_successful("Q10")[:1]
    assert len(successful) == 1
    assert _select_partial(successful) is successful[0]


def test_a_narrowing_trace_does_not_select_the_most_recent_call():
    """The defect: an agentic trace narrows, so 'most recent' is the narrowest.

    This is the real Q10 trace -- ten price-filtered candidates in round 1,
    per-player fixture runs after, a zero-item pairwise compare last.
    """
    successful = _recorded_successful("Q10")
    assert len(successful) > 1, "need a multi-call trace for this to mean anything"

    chosen = _select_partial(successful)

    assert chosen is not successful[-1], "must not fall back to the narrowest view"
    assert chosen is successful[0]
    assert chosen[1] == "get_transfer_suggestion"
    # and it is strictly more than what the old rule surfaced
    assert len(render(chosen[1], chosen[3])) > len(
        render(successful[-1][1], successful[-1][3])
    )


def test_the_earliest_call_wins_a_tie():
    """Identical payloads render identically; the earlier call must win."""
    base = _recorded_successful("Q10")[0]
    first = ("call-early",) + base[1:]
    second = ("call-late",) + base[1:]

    chosen = _select_partial([first, second])

    assert chosen is first
    assert chosen[0] == "call-early"


def test_selection_neither_mutates_nor_depends_on_call_order_effects():
    successful = _recorded_successful("Q10")
    snapshot = list(successful)

    once = _select_partial(successful)
    twice = _select_partial(successful)

    assert once is twice, "selection must be deterministic"
    assert successful == snapshot, "input list must not be mutated"


def test_a_call_whose_payload_cannot_be_rendered_is_not_selected():
    """A render failure scores zero, so a renderable call is preferred."""
    good = _recorded_successful("Q10")[0]
    unrenderable = ("call-bad", "get_transfer_suggestion", {}, {"suggestions": object()})

    assert _select_partial([unrenderable, good]) is good


def test_every_recorded_exhausted_trace_selects_an_answer_bearing_call():
    """Replay pin over the recorded corpus.

    Under the old ``successful[-1]`` rule every one of these rendered a
    single-player or pairwise view. None may regress to that.
    """
    with open(_OBSERVATIONS, encoding="utf-8") as fh:
        rows = json.load(fh)

    checked = 0
    for row in rows:
        if not row.get("rounds_exhausted"):
            continue
        successful = [
            (e.get("tool_call_id"), e.get("name"), e.get("args") or {}, e.get("output") or {})
            for e in (row.get("tool_calls_trace") or [])
            if e.get("success")
        ]
        if not successful:
            continue
        checked += 1
        chosen = _select_partial(successful)
        old = successful[-1]
        assert len(render(chosen[1], chosen[3])) >= len(render(old[1], old[3])), (
            "scenario %r regressed below the old rule" % row.get("scenario")
        )
        assert chosen[1] == "get_transfer_suggestion", (
            "scenario %r selected %r, not the answer-bearing call"
            % (row.get("scenario"), chosen[1])
        )

    assert checked == 6, "expected 6 exhausted observations in GEMINI-cap5, saw %d" % checked


def test_the_selector_is_never_called_when_no_tool_call_succeeded(
    monkeypatch, bootstrap
):
    """The empty list is never passed in: call sites guard on ``if successful:``.

    Driven through the real orchestrator rather than asserted against a mock --
    every tool call fails, the loop gives up, and the selector must not run.
    """
    from test_multi_provider_follow_up import (
        _SequenceClient,
        _action_response,
        _enable_loop,
    )

    import fpl_grounded_assistant.orchestrator as orch

    seen = []
    real = orch._select_partial

    def _spy(successful):
        seen.append(list(successful))
        return real(successful)

    monkeypatch.setattr(orch, "_select_partial", _spy)
    _enable_loop(monkeypatch, rounds=3)

    client = _SequenceClient(orch.PROVIDER_ANTHROPIC, [
        _action_response(orch.PROVIDER_ANTHROPIC, "bad-1", "invented_tool_a", {}),
        _action_response(orch.PROVIDER_ANTHROPIC, "bad-2", "invented_tool_b", {}),
    ])
    result = orch.ask_orchestrated(
        "question", bootstrap, client=client, _eval_client=None
    )

    assert result.outcome == orch.OUTCOME_NO_TOOL
    assert [entry["success"] for entry in result.tool_calls_trace] == [False, False]
    assert seen == [], "selector must not run when nothing succeeded"


def test_the_selector_runs_on_the_exhaustion_path_with_a_non_empty_list(
    monkeypatch, bootstrap
):
    """The positive half of the guard: a grounded partial does reach the selector."""
    from test_multi_provider_follow_up import (
        _SequenceClient,
        _action_response,
        _enable_loop,
    )

    import fpl_grounded_assistant.orchestrator as orch

    seen = []
    real = orch._select_partial

    def _spy(successful):
        seen.append(list(successful))
        return real(successful)

    monkeypatch.setattr(orch, "_select_partial", _spy)
    _enable_loop(monkeypatch, rounds=2)

    client = _SequenceClient(orch.PROVIDER_ANTHROPIC, [
        _action_response(orch.PROVIDER_ANTHROPIC, "c1", "get_current_gameweek", {}),
        _action_response(
            orch.PROVIDER_ANTHROPIC, "c2", "get_player_snapshot", {"player_name": "Salah"}
        ),
        _action_response(orch.PROVIDER_ANTHROPIC, "c3", "get_current_gameweek", {}),
    ])
    result = orch.ask_orchestrated(
        "question", bootstrap, client=client, _eval_client=None
    )

    assert result.rounds_exhausted is True
    assert result.outcome == orch.OUTCOME_OK
    assert len(seen) == 1
    assert seen[0], "selector must receive a non-empty list"
    assert all(item for item in seen[0])
