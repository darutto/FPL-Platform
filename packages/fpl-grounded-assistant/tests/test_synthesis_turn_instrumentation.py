"""
Instrumentation tests for OrchestratorResult.tool_call_count / .synthesis_turn
(G3 raw-dump instrumentation).

Background
----------
Production incident: POST /session/{id}/ask returned a bare gameweek-lookup
render() ("Jornada actual: GW1...") in reply to a squad-evaluation question.
Root cause: orchestrator.py's single-tool path renders a tool's raw output
directly and never gives the model a turn to write an answer (step 9,
"Render answer; determine outcome from first tool's status").

Before this instrumentation, a response could not say whether the model
called one tool or three -- routing_trace["orchestrator_tool_calls"] is
hardcoded to [orch_result.tool_chosen] (first tool only), which is exactly
the variable this bug depends on.

This file tests the STATED hypothesis as a testable claim:

    a bare render() reply happens if and only if the model requested
    exactly one tool and no synthesis turn occurred

using fake clients only -- no paid API calls, following the patterns in
tests/test_multi_provider_follow_up.py.

Finding (see the last two tests): the hypothesis AS LITERALLY STATED is
FALSE in both directions. The corrected, verified relationship is:

    is_bare_render_reply(result) ==> not result.synthesis_turn   (always holds)
    not result.synthesis_turn      =/=> is_bare_render_reply(result)  (does not)

i.e. every bare tool-render reply has synthesis_turn=False, but
synthesis_turn=False also covers other non-model-authored replies (a static
"no tool found" message, an error string) that are not renders of any tool
at all. tool_call_count is neither necessary nor sufficient for a bare
render reply once synthesis_turn is tracked directly -- it is a real,
independently useful observability field (how many tools ran), but it is
not the gating variable for commit 2's fix.
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace as NS

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

from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_OK,
    OrchestratorResult,
    ask_orchestrated,
)
from fpl_grounded_assistant.renderer import render  # noqa: E402


def _is_bare_render_reply(result: OrchestratorResult) -> bool:
    """Independent (non-circular) check: answer_text is EXACTLY what render()
    produces for the tool that was chosen -- the literal failure mode from
    the incident ("Jornada actual: GW1...", verbatim, no wrapper, no model
    text). Does not use result.synthesis_turn at all."""
    if result.tool_chosen is None:
        return False
    try:
        rendered = render(result.tool_chosen, result.tool_output)
    except Exception:  # noqa: BLE001
        return False
    return result.answer_text == rendered


# ---------------------------------------------------------------------------
# Non-loop path (default; FPL_ORCH_LOOP_ENABLED unset)
# ---------------------------------------------------------------------------

def test_single_tool_no_synthesis_bare_render(bootstrap):
    """The incident's exact mechanism: one tool call, no second LLM call,
    answer_text is the literal render() output."""
    class Client:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return NS(content=[NS(
                type="tool_use", id="c1", name="get_current_gameweek", input={},
            )])

    client = Client()
    result = ask_orchestrated(
        "What gameweek is it?", bootstrap, client=client, _eval_client=None,
    )
    assert client.calls == 1
    assert result.tool_call_count == 1
    assert result.synthesis_turn is False
    assert _is_bare_render_reply(result) is True
    assert result.answer_text == render("get_current_gameweek", result.tool_output)


def test_multi_tool_second_call_succeeds_is_synthesis(bootstrap):
    """Two tools, second call gives real text -> synthesis, not a bare render."""
    class Client:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return NS(content=[
                    NS(type="tool_use", id="c1", name="get_current_gameweek", input={}),
                    NS(type="tool_use", id="c2", name="get_player_snapshot",
                       input={"player_name": "Salah"}),
                ])
            return NS(content=[NS(type="text", text="It is GW1 and Salah is fit.")])

    client = Client()
    result = ask_orchestrated(
        "What gameweek is it and who is Salah?", bootstrap, client=client, _eval_client=None,
    )
    assert client.calls == 2
    assert result.tool_call_count == 2
    assert result.synthesis_turn is True
    assert result.answer_text == "It is GW1 and Salah is fit."
    assert _is_bare_render_reply(result) is False


def test_multi_tool_second_call_fails_is_bare_render_with_two_tools(bootstrap):
    """COUNTEREXAMPLE #1 to the naive hypothesis: two tools were called
    (tool_call_count == 2, not 1) and the second (synthesis) LLM call fails,
    so the code falls back to a bare render() of the FIRST tool only. This
    is a genuine bare-render reply with tool_call_count > 1 -- "exactly one
    tool" is not a necessary condition for a bare render."""
    class Client:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return NS(content=[
                    NS(type="tool_use", id="c1", name="get_current_gameweek", input={}),
                    NS(type="tool_use", id="c2", name="get_player_snapshot",
                       input={"player_name": "Salah"}),
                ])
            raise TimeoutError("provider down for the synthesis call")

    client = Client()
    result = ask_orchestrated(
        "What gameweek is it and who is Salah?", bootstrap, client=client, _eval_client=None,
    )
    assert client.calls >= 2   # >= 1 primary + >= 1 failed synthesis attempt
    # (call_orch_provider retries transient errors internally, so the exact
    # count depends on retry config -- what matters is the OUTCOME below.)
    assert result.tool_call_count == 2   # NOT 1
    assert result.synthesis_turn is False
    assert _is_bare_render_reply(result) is True
    assert result.tool_chosen == "get_current_gameweek"  # first tool only
    assert result.answer_text == render("get_current_gameweek", result.tool_output)


def test_multi_tool_second_call_empty_text_is_bare_render(bootstrap):
    """Second call succeeds but returns no text -> same fallback as above."""
    class Client:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return NS(content=[
                    NS(type="tool_use", id="c1", name="get_current_gameweek", input={}),
                    NS(type="tool_use", id="c2", name="get_player_snapshot",
                       input={"player_name": "Salah"}),
                ])
            return NS(content=[])

    client = Client()
    result = ask_orchestrated(
        "What gameweek is it and who is Salah?", bootstrap, client=client, _eval_client=None,
    )
    assert result.tool_call_count == 2
    assert result.synthesis_turn is False
    assert _is_bare_render_reply(result) is True


def test_no_tool_call_with_real_text_is_synthesis_not_bare_render(bootstrap):
    """Model calls no tool at all but writes real text (e.g. an off-topic
    refusal). Zero tools, but this IS the model's own text."""
    class Client:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            return NS(content=[NS(type="text", text="Lo siento, solo respondo sobre FPL.")])

    client = Client()
    result = ask_orchestrated("What's the capital of France?", bootstrap, client=client, _eval_client=None)
    assert result.tool_call_count == 0
    assert result.synthesis_turn is True
    assert result.answer_text == "Lo siento, solo respondo sobre FPL."
    assert _is_bare_render_reply(result) is False


def test_no_tool_call_no_text_is_static_fallback_not_bare_render(bootstrap):
    """Model calls no tool AND writes no text -- the static "no tool found"
    fallback fires. synthesis_turn is correctly False (not model text), but
    this is NOT a bare render() reply either -- there is no tool_chosen to
    render. This is the case that breaks the "not synthesis_turn implies
    bare render" direction (see the summary test at the bottom)."""
    class Client:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            return NS(content=[])

    client = Client()
    result = ask_orchestrated("...", bootstrap, client=client, _eval_client=None)
    assert result.tool_call_count == 0
    assert result.synthesis_turn is False
    assert result.tool_chosen is None
    assert _is_bare_render_reply(result) is False
    assert result.answer_text == "No encontré una herramienta para responder a esto."


# ---------------------------------------------------------------------------
# Loop path (FPL_ORCH_LOOP_ENABLED=1)
# ---------------------------------------------------------------------------

def _enable_loop(monkeypatch, rounds: int = 3):
    monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", str(rounds))
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")


class _SequenceClient:
    def __init__(self, responses: list[object]):
        self.messages = self
        self.queue = list(responses)
        self.calls: list[object] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_loop_single_tool_then_real_text_is_synthesis(monkeypatch, bootstrap):
    """NOT a counterexample to the biconditional (synthesis_turn=True zeroes
    out the naive rule's AND correctly) -- but it demonstrates why
    tool_call_count ALONE would be the wrong signal if synthesis_turn were
    dropped: exactly ONE tool was called, yet the loop's automatic
    follow-up round gives the model a real turn to write the answer."""
    _enable_loop(monkeypatch)
    client = _SequenceClient([
        NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})]),
        NS(content=[NS(type="text", text="It's GW1, plenty of time before the deadline.")]),
    ])
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.tool_call_count == 1   # exactly one tool
    assert result.synthesis_turn is True  # yet IS a synthesis turn
    assert result.answer_text == "It's GW1, plenty of time before the deadline."
    assert _is_bare_render_reply(result) is False


def test_loop_single_tool_then_empty_round_falls_back_to_bare_render(monkeypatch, bootstrap):
    """Same shape as above, but round 2 gives no text -- falls back to the
    same bare render() as the non-loop path. tool_call_count == 1 AND
    synthesis_turn == False, matching the naive hypothesis in this specific
    sub-case (it is not always wrong -- it is just not the deciding rule)."""
    _enable_loop(monkeypatch)
    client = _SequenceClient([
        NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})]),
        NS(content=[]),
    ])
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.tool_call_count == 1
    assert result.synthesis_turn is False
    assert _is_bare_render_reply(result) is True


def test_loop_round_cap_exhausted_partial_is_not_synthesis(monkeypatch, bootstrap):
    """COUNTEREXAMPLE #2 to the naive hypothesis: exactly ONE tool was
    executed (round 2's attempted second call never runs -- the cap check
    fires before execution) and synthesis_turn is False, so the naive rule
    predicts a bare render reply here. But the actual answer is a static
    "Respuesta incompleta (...)" prefix wrapped around a render() -- not
    byte-equal to render() alone, so it is NOT a bare render reply. Breaks
    "exactly one tool and no synthesis implies bare render"."""
    _enable_loop(monkeypatch, rounds=1)
    client = _SequenceClient([
        NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})]),
        NS(content=[NS(type="tool_use", id="c2", name="get_current_gameweek", input={})]),
    ])
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.rounds_exhausted is True
    assert result.tool_call_count == 1   # round 2's call was never executed
    assert result.synthesis_turn is False
    assert result.answer_text.startswith("Respuesta incompleta")
    assert _is_bare_render_reply(result) is False  # wrapped, not literally bare
    assert result.answer_text.endswith(render(result.tool_chosen, result.tool_output))
    naive_predicts_bare = (result.tool_call_count == 1) and (not result.synthesis_turn)
    assert naive_predicts_bare is True
    assert naive_predicts_bare != _is_bare_render_reply(result)


# ---------------------------------------------------------------------------
# The hypothesis itself
# ---------------------------------------------------------------------------

def test_naive_hypothesis_is_false_in_both_directions(bootstrap, monkeypatch):
    """The literally-stated hypothesis --

        a bare render() reply happens iff (tool_call_count == 1) and
        (not synthesis_turn)

    -- is FALSE. Two independent counterexamples, one per direction:

    (1) tool_call_count == 2, not synthesis_turn -> IS a bare render reply.
        (multi-tool second/synthesis call fails; falls back to rendering
        only the first tool.) Breaks "bare render implies exactly one tool."

    (2) tool_call_count == 1, not synthesis_turn -> is NOT a bare render
        reply (it's a "Respuesta incompleta" wrapper). The loop's round cap
        fires before round 2's tool ever executes, so exactly one tool ran
        and synthesis_turn is False, but the wrapper prefix means answer_text
        is not byte-equal to a bare render(). Breaks "exactly one tool and
        no synthesis implies bare render."

    This test re-derives both counterexamples directly (not by importing
    private test functions) so it stands alone as the falsification record.
    """
    # Counterexample 1: multi-tool, second call fails.
    class FailingSecondCallClient:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return NS(content=[
                    NS(type="tool_use", id="c1", name="get_current_gameweek", input={}),
                    NS(type="tool_use", id="c2", name="get_player_snapshot",
                       input={"player_name": "Salah"}),
                ])
            raise TimeoutError("synthesis call failed")

    r1 = ask_orchestrated(
        "What gameweek is it and who is Salah?",
        bootstrap,
        client=FailingSecondCallClient(),
        _eval_client=None,
    )
    naive_predicts_bare_1 = (r1.tool_call_count == 1) and (not r1.synthesis_turn)
    actual_bare_1 = _is_bare_render_reply(r1)
    assert r1.tool_call_count == 2
    assert naive_predicts_bare_1 is False    # naive rule says "not a bare render"
    assert actual_bare_1 is True             # it IS one -- naive rule is wrong here
    assert naive_predicts_bare_1 != actual_bare_1

    # Counterexample 2: loop mode, round cap exhausted after exactly one
    # executed tool call -- a "Respuesta incompleta" wrapper, not bare.
    _enable_loop(monkeypatch, rounds=1)
    client2 = _SequenceClient([
        NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})]),
        NS(content=[NS(type="tool_use", id="c2", name="get_current_gameweek", input={})]),
    ])
    r2 = ask_orchestrated("What gameweek is it?", bootstrap, client=client2, _eval_client=None)
    naive_predicts_bare_2 = (r2.tool_call_count == 1) and (not r2.synthesis_turn)
    actual_bare_2 = _is_bare_render_reply(r2)
    assert r2.tool_call_count == 1
    assert naive_predicts_bare_2 is True     # naive rule says "IS a bare render"
    assert actual_bare_2 is False            # it is NOT one -- naive rule is wrong here too
    assert naive_predicts_bare_2 != actual_bare_2


def test_synthesis_turn_is_the_correct_one_directional_predicate(bootstrap, monkeypatch):
    """The verified, precise relationship (see module docstring):

        is_bare_render_reply(result) ==> not result.synthesis_turn

    holds in every case tested here -- but the converse does NOT hold
    (not-synthesis also covers static no-tool/error messages that are not
    renders of anything). synthesis_turn, not tool_call_count and not a
    stricter "is this literally a render()" check, is therefore the correct
    single gating signal for commit 2: it is a strict superset of "bare
    render reply" that also catches the other non-model-authored replies,
    which is exactly what needs a fix (the user got no explanation either
    way)."""
    cases: list[OrchestratorResult] = []

    class SingleToolClient:
        def create(self, **kwargs):
            return NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})])
    single_tool_client = SingleToolClient()
    single_tool_client.messages = single_tool_client
    cases.append(ask_orchestrated("gw?", bootstrap, client=single_tool_client, _eval_client=None))

    class NoToolNoTextClient:
        def create(self, **kwargs):
            return NS(content=[])
    no_tool_client = NoToolNoTextClient()
    no_tool_client.messages = no_tool_client
    cases.append(ask_orchestrated("...", bootstrap, client=no_tool_client, _eval_client=None))

    for result in cases:
        if _is_bare_render_reply(result):
            assert result.synthesis_turn is False, (
                f"bare render reply must have synthesis_turn=False: {result!r}"
            )

    # The converse fails for the no-tool/no-text case: synthesis_turn=False
    # but it is not a bare render reply (no tool was ever chosen).
    no_tool_result = cases[1]
    assert no_tool_result.synthesis_turn is False
    assert _is_bare_render_reply(no_tool_result) is False
