"""i58: the harness card gate reads the tool SEQUENCE, not the call COUNTER.

Before this change ``harness.ask_v2`` carded an orchestrator turn only when
``OrchestratorResult.tool_call_count == 1``. The i46 extra round
(``orchestrator._run_synthesis_extra_round``) calls the same cardable tool a
second time with different arguments and ends in model prose; those turns read
``tool_call_count == 2`` and silently lost their card (see
field-notes/2026-08-31-i46-extra-round-fix.md, "Knock-on worth knowing").

The gate is now ``atomic_tool_cards.is_single_distinct_tool_turn`` and the
three shapes are pinned end to end through ``ask_v2`` with a stubbed
orchestrator (no LLM, no network):

  * one call, cardable tool                 -> card   (unchanged; pinned)
  * two calls, SAME cardable tool           -> card   (the rescued turn; NEW)
  * two calls, two DIFFERENT tools          -> no card (multi-tool; pinned)

Mutations recorded in the PR, each applied and reverted on its own:

  * gate back to ``tool_call_count == 1``   -> the rescued-turn test dies
  * drop the single-distinct-tool condition -> the multi-tool test dies

Plus: the ask_v2 dict of the rescued turn, passed through the real
``harness_adapter.to_ask_response``, carries BOTH ``synthesis_turn=True`` and a
non-null ``generic_card`` -- the two fields the UI needs to show card + prose
(``MessageList.tsx``: the "Veredicto" band is shown when ``synthesis_turn`` is
not ``false``; the card renders beneath it).
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant.atomic_tool_cards import (  # noqa: E402
    is_single_distinct_tool_turn,
)

CARDABLE = "rank_players_by_metric"
OTHER = "get_player_snapshot"


# ---------------------------------------------------------------------------
# Helpers (same shapes as tests/test_atomic_tool_cards.py)
# ---------------------------------------------------------------------------

def _entry(rank: int, name: str, value: float) -> dict:
    return {
        "rank": rank, "web_name": name, "team_short": "MCI",
        "position": "FWD", "metric_value": value,
    }


def _rank_output(metric: str = "total_points", n: int = 3) -> dict:
    ranked = [_entry(i + 1, f"P{i}", float(100 - i)) for i in range(n)]
    return {"status": "ok", "metric": metric, "top_n": n, "ranked": ranked}


def _trace(*names: str) -> tuple[dict, ...]:
    """A ``tool_calls_trace`` shaped like ``orchestrator._trace_entry``."""
    return tuple(
        {
            "round": 1 if i == 0 else 2,
            "tool_call_id": f"call_{i}",
            "name": name,
            "args": {},
            "output": {"status": "ok"},
            "success": True,
        }
        for i, name in enumerate(names)
    )


def _fake_orch_result(*, tool_chosen, tool_output, tool_call_count, trace, synthesis_turn=True):
    from fpl_grounded_assistant.orchestrator import OrchestratorResult, OUTCOME_OK
    return OrchestratorResult(
        question="q", tool_chosen=tool_chosen, tool_args={}, tool_output=tool_output,
        answer_text="Haaland lidera; Palmer es la alternativa.", llm_used=True,
        model="m", outcome=OUTCOME_OK,
        tool_call_count=tool_call_count,
        tool_calls_trace=trace,
        synthesis_turn=synthesis_turn,
    )


def _ask_v2_with_orch(monkeypatch, orch_result, question="jugadores con mas puntos"):
    from fpl_grounded_assistant import harness
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: orch_result,
    )
    from fpl_grounded_assistant import STANDARD_BOOTSTRAP
    return harness.ask_v2(question, STANDARD_BOOTSTRAP, orch_client=object())


# ---------------------------------------------------------------------------
# The gate, end to end through ask_v2
# ---------------------------------------------------------------------------

def test_single_call_cardable_tool_gets_card(monkeypatch):
    """Pinned: today's behaviour. One executed call, cardable output -> card."""
    orch = _fake_orch_result(
        tool_chosen=CARDABLE, tool_output=_rank_output(), tool_call_count=1,
        trace=_trace(CARDABLE),
    )
    result = _ask_v2_with_orch(monkeypatch, orch)
    assert result.get("generic_card") is not None
    assert result["routing_trace"]["tool_call_count"] == 1


def test_rescued_turn_same_tool_twice_gets_card(monkeypatch):
    """The i46 rescued turn: the extra round called the SAME cardable tool
    again, so tool_call_count == 2 but there is one distinct tool. Must card.
    (Mutation 'gate back to == 1' kills this test.)"""
    orch = _fake_orch_result(
        tool_chosen=CARDABLE, tool_output=_rank_output(), tool_call_count=2,
        trace=_trace(CARDABLE, CARDABLE), synthesis_turn=True,
    )
    result = _ask_v2_with_orch(monkeypatch, orch)
    assert result["routing_trace"]["tool_call_count"] == 2
    assert result.get("generic_card") is not None
    # The prose is still there: the card is added, nothing is replaced.
    assert result["answer_text"] == "Haaland lidera; Palmer es la alternativa."
    assert result["routing_trace"]["synthesis_turn"] is True


def test_two_distinct_tools_get_no_card(monkeypatch):
    """A genuine multi-tool turn whose FIRST tool is cardable must not card:
    its answer_text covers a tool the card would not show.
    (Mutation 'drop the single-distinct-tool condition' kills this test.)"""
    orch = _fake_orch_result(
        tool_chosen=CARDABLE, tool_output=_rank_output(), tool_call_count=2,
        trace=_trace(CARDABLE, OTHER), synthesis_turn=True,
    )
    result = _ask_v2_with_orch(monkeypatch, orch)
    assert result["routing_trace"]["tool_call_count"] == 2
    assert result.get("generic_card") is None


def test_multi_call_with_empty_trace_is_not_carded(monkeypatch):
    """Conservative: a multi-call turn whose trace cannot show a single tool is
    not carded (this is also the shape tests/test_atomic_tool_cards.py's
    multi-tool test has used since before i58)."""
    orch = _fake_orch_result(
        tool_chosen=CARDABLE, tool_output=_rank_output(), tool_call_count=2,
        trace=(),
    )
    result = _ask_v2_with_orch(monkeypatch, orch)
    assert result.get("generic_card") is None


def test_rescued_turn_with_non_cardable_output_gets_no_card(monkeypatch):
    """The other half of the gate is untouched: one distinct tool whose output
    is not cardable (status != ok) still gets no card."""
    orch = _fake_orch_result(
        tool_chosen=CARDABLE,
        tool_output={"status": "invalid_argument", "code": "unknown_metric"},
        tool_call_count=2, trace=_trace(CARDABLE, CARDABLE),
    )
    result = _ask_v2_with_orch(monkeypatch, orch)
    assert result.get("generic_card") is None


# ---------------------------------------------------------------------------
# The rescued turn reaches the /ask wire with both fields the UI needs
# ---------------------------------------------------------------------------

def test_rescued_turn_wire_carries_synthesis_turn_and_generic_card(monkeypatch):
    """The client decides "card + prose" from AskResponse.synthesis_turn and
    AskResponse.generic_card. Both must survive the real adapter."""
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    from fpl_server import AskRequest

    orch = _fake_orch_result(
        tool_chosen=CARDABLE, tool_output=_rank_output(), tool_call_count=2,
        trace=_trace(CARDABLE, CARDABLE), synthesis_turn=True,
    )
    ask_v2_dict = _ask_v2_with_orch(monkeypatch, orch)
    response = to_ask_response(ask_v2_dict, AskRequest(question="jugadores con mas puntos"))
    wire = response.model_dump()
    assert wire["synthesis_turn"] is True
    assert wire["generic_card"] is not None
    assert wire["generic_card"]["title"] == "TOP 3 · Puntos"
    assert wire["final_text"] == "Haaland lidera; Palmer es la alternativa."


# ---------------------------------------------------------------------------
# The predicate on its own (pure; what the measurement script also calls)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool_chosen, count, seq, expected",
    [
        (CARDABLE, 1, [CARDABLE], True),                 # single call
        (CARDABLE, 2, [CARDABLE, CARDABLE], True),       # rescued: same tool twice
        (CARDABLE, 3, [CARDABLE] * 3, True),             # loop mode, one tool
        (CARDABLE, 2, [CARDABLE, OTHER], False),         # two distinct tools
        (CARDABLE, 2, [OTHER, CARDABLE], False),         # order does not matter
        (CARDABLE, 2, [], False),                        # cannot prove single tool
        (CARDABLE, 2, [None, CARDABLE], True),           # nameless entries ignored
        (None, 1, [CARDABLE], False),                    # nothing retained
        (CARDABLE, 0, [], False),                        # no executed call
        # Evaluator-retry delivery: the trace describes the PRIMARY calls, the
        # count the retry's. count == 1 keeps carding as before i58.
        (CARDABLE, 1, [CARDABLE, OTHER], True),
        (OTHER, 1, [CARDABLE], True),
    ],
)
def test_is_single_distinct_tool_turn(tool_chosen, count, seq, expected):
    assert is_single_distinct_tool_turn(tool_chosen, count, seq) is expected
