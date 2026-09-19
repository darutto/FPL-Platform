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
from fpl_grounded_assistant.evaluator import EvaluatorVerdict  # noqa: E402
from fpl_grounded_assistant.renderer import render  # noqa: E402


def _is_bare_render_reply(result: OrchestratorResult) -> bool:
    """Independent (non-circular) check: the answer body is EXACTLY what
    render() produces for the tool that was chosen -- the literal failure mode
    from the incident ("Jornada actual: GW1...", verbatim, no model text).
    Does not use result.synthesis_turn at all.

    i46 (c): that render is now prefixed with a catalogued notice saying the
    model did not write it, so "bare" means the body under the notice, not the
    whole string. The prefix is stripped here rather than relaxing the
    comparison to a substring match: an `in` check would keep passing if the
    render were wrapped in anything at all, which is the one thing this
    predicate exists to detect. The text is still, byte for byte, a
    deterministic render -- it just no longer pretends to be an answer.
    """
    if result.tool_chosen is None:
        return False
    try:
        rendered = render(result.tool_chosen, result.tool_output)
    except Exception:  # noqa: BLE001
        return False
    return _strip_notice(result.answer_text) == rendered


def _notice() -> str:
    from fpl_grounded_assistant.catalogue import t
    return t("orchestrator.raw_render_notice", "es")


def _strip_notice(answer_text: str) -> str:
    """Remove i46 (c)'s marker prefix, if present, and return the body."""
    prefix = f"{_notice()}\n\n"
    return answer_text[len(prefix):] if answer_text.startswith(prefix) else answer_text


# ---------------------------------------------------------------------------
# Non-loop path (default; FPL_ORCH_LOOP_ENABLED unset)
# ---------------------------------------------------------------------------

def test_single_tool_no_synthesis_bare_render(bootstrap):
    """The incident's exact mechanism, still reachable as a FALLBACK after
    the G3 fix (commit 2): one tool call, a synthesis turn IS now attempted,
    but this fake client never produces text on any call, so the synthesis
    call has no text and the code falls back to answer_text == literal
    render() output. Before the fix this was reached directly (single-tool
    turns skipped the synthesis call entirely, client.calls == 1); after the
    fix it is reached only via this fallback (client.calls == 2). The
    observable properties this test pins -- tool_call_count, synthesis_turn,
    and the bare-render text -- are unchanged either way.

    i46: now 3 calls, not 2, and tool_call_count 2, not 1. This fake returns
    a tool_use block on EVERY call, so the synthesis response carries a tool
    call rather than text and the one bounded extra round fires -- which this
    fake answers with another tool call, so the turn still ends on the render.
    The count rises because the extra round really did execute a tool a second
    time, which is exactly what tool_call_count is documented to report
    ("executed tool calls underlying the retained payload, including
    failures"). synthesis_turn stays False: no model prose was ever produced.
    The mechanism this test exists to pin is untouched -- still reachable, and
    still a render."""
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
    assert client.calls == 3
    assert result.tool_call_count == 2
    assert result.synthesis_turn is False
    assert _is_bare_render_reply(result) is True
    assert _strip_notice(result.answer_text) == render(
        "get_current_gameweek", result.tool_output
    )
    # i46 (c): the render still ships, but no longer unlabelled.
    assert result.answer_text.startswith(_notice())


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
    assert _strip_notice(result.answer_text) == render(
        "get_current_gameweek", result.tool_output
    )
    assert result.answer_text.startswith(_notice())


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


# ---------------------------------------------------------------------------
# i37: the evaluator retry gets a synthesis turn (was a known residual gap)
# ---------------------------------------------------------------------------
#
# #160 measured this residual at 1/40 per endpoint and left it alone. Measured
# again in prod 2026-09-17 (gpt-5.6-luna, 25 orchestrated turns, see
# field-notes/2026-09-17-i96-i37-retry-delivery.md): 7 turns were rejected by
# the evaluator and every one of the 7 retries called a tool instead of
# writing text, so 28% of turns delivered a bare render(). The retry now gets
# ONE synthesis call over its own tool results, exactly like the primary path;
# the bare render is only the fallback when that call fails or yields no text.

class _RetryClient:
    """Fake Anthropic-shaped client: primary tool call, synthesis text,
    (evaluator is mocked), retry tool call, then whatever ``fourth`` says."""

    def __init__(self, fourth):
        self.messages = self
        self.calls = 0
        self.kwargs: list[dict] = []
        self._fourth = fourth

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        if self.calls == 1:
            return NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})])
        if self.calls == 2:
            return NS(content=[NS(type="text", text="A genuine synthesised answer.")])
        if self.calls == 3:
            # Retry: the model calls a tool again instead of writing text.
            return NS(content=[NS(type="tool_use", id="c2", name="get_current_gameweek", input={})])
        return self._fourth()


def _reject(monkeypatch):
    verdict = EvaluatorVerdict(
        approved=False, grounded=True, complete=False, safe=True,
        retry_feedback="be more complete", tokens_used=17,
    )
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.evaluate_response", lambda **kwargs: verdict)


def test_evaluator_retry_that_calls_a_tool_gets_a_synthesis_turn(monkeypatch, bootstrap):
    _reject(monkeypatch)
    client = _RetryClient(lambda: NS(content=[NS(type="text", text="Estamos en la jornada 5; te explico.")]))
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=object())

    assert client.calls == 4, "primary, synthesis, retry, retry-synthesis"
    assert result.retry_attempted is True
    assert result.tool_call_count == 1
    assert result.synthesis_turn is True
    assert result.answer_text == "Estamos en la jornada 5; te explico."
    assert _is_bare_render_reply(result) is False
    # The retry's synthesis call carries the retry's tool result, not the primary's.
    fourth = client.kwargs[3]["messages"]
    assert any(
        isinstance(m, dict) and m.get("role") == "user"
        and any(isinstance(b, dict) and b.get("tool_use_id") == "c2" for b in (m.get("content") or []) if isinstance(m.get("content"), list))
        for m in fourth
    ), fourth


def test_evaluator_retry_synthesis_without_text_falls_back_to_the_render(monkeypatch, bootstrap):
    """The pre-i37 behaviour is now the fallback, not the path."""
    _reject(monkeypatch)
    client = _RetryClient(lambda: NS(content=[]))
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=object())

    assert client.calls == 4
    assert result.retry_attempted is True
    assert result.synthesis_turn is False
    assert _is_bare_render_reply(result) is True
    assert result.answer_text == render(result.tool_chosen, result.tool_output)


def test_evaluator_retry_synthesis_tokens_are_billed_to_the_retry_bucket(monkeypatch, bootstrap):
    _reject(monkeypatch)
    client = _RetryClient(lambda: NS(
        content=[NS(type="text", text="ok")],
        usage=NS(input_tokens=1000, output_tokens=7, cache_read_input_tokens=0),
    ))
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=object())
    assert result.retry_input_tokens >= 1000
    assert result.retry_output_tokens >= 7
    assert result.total_tokens >= result.retry_input_tokens + result.retry_output_tokens


# ---------------------------------------------------------------------------
# i96: the retry's executed calls are in tool_calls_trace
# ---------------------------------------------------------------------------

def test_retry_executed_calls_are_recorded_in_the_trace_after_the_primary_round(monkeypatch, bootstrap):
    _reject(monkeypatch)
    client = _RetryClient(lambda: NS(content=[NS(type="text", text="texto")]))
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=object())

    trace = list(result.tool_calls_trace)
    assert [e["name"] for e in trace] == ["get_current_gameweek", "get_current_gameweek"]
    primary, retry = trace
    assert primary["round"] == 1 and "retry" not in primary
    assert retry["round"] == 2 and retry["retry"] is True
    assert retry["tool_call_id"] == "c2"
    assert retry["success"] is True and retry["output"]["status"] == "ok"
    # Same key order as a primary entry, then the marker.
    assert list(retry) == list(primary) + ["retry"]
    # Retained-payload semantics untouched: the retry's own count.
    assert result.tool_call_count == 1
