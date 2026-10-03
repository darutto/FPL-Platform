"""i130 -- the retry's cached tokens reach the audit and its USD estimate.

The audit recorded ``retry_input`` but not the cached share of the retry
calls. On OpenAI the cached count is a SUBSET of input_tokens, so with no
``retry_cache_read`` every cached retry token was priced at the full input
rate: ``usd_cost_estimate`` on a rejected turn was an upper bound (seen in
i124's measurement). The retry tool call and the retry synthesis now add
their ``cache_read_tokens`` to ``retry_cache_read_tokens`` -> tokens
``retry_cache_read`` -> the cache component of ``estimate_usd_cost``.

One evaluator-rejected luna turn, end to end: a fake OpenAI Responses client
whose four calls (primary tool, primary synthesis, retry tool, retry
synthesis) report usage with cached_tokens; tools served from fixtures;
evaluator forced to reject. The tokens dict is read off what ask_v2 returns
(the same dict the audit line is written from), and the USD is checked
against the arithmetic below, done by hand at luna's rates. No network, no
paid call.
"""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import harness, provider_client
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.audit import estimate_usd_cost
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.orchestrator import PROVIDER_OPENAI, ask_orchestrated

from conftest import BOOTSTRAP

QUESTION = "¿A quién capitaneo esta jornada?"
MODEL = "gpt-5.6-luna"
CAPTAIN_OUTPUT = {"status": "ok", "ranked_candidates": [{"web_name": "Groß", "captain_score": 73.3}]}

# (input, cached, output) per call; cached is a subset of input (OpenAI).
PRIMARY_TOOL  = (1000, 800, 50)
PRIMARY_SYNTH = (1200, 1000, 100)
RETRY_TOOL    = (1500, 1400, 40)
RETRY_SYNTH   = (1700, 1600, 120)
EVALUATOR     = 17


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i130 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr(orch_mod, "run_tool", lambda name, args, bootstrap: json.loads(json.dumps(CAPTAIN_OUTPUT)))
    rejected = EvaluatorVerdict(approved=False, grounded=False, complete=False, safe=True,
                                retry_feedback="Cita los valores concretos.", tokens_used=EVALUATOR)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kwargs: rejected)


def _usage(call: tuple[int, int, int]) -> NS:
    inp, cached, out = call
    return NS(input_tokens=inp, output_tokens=out, input_tokens_details=NS(cached_tokens=cached))


def _tool_call(cid: str, call: tuple[int, int, int]) -> NS:
    fc = NS(type="function_call", call_id=cid, name="rank_captain_candidates",
            arguments=json.dumps({"gameweek": 6, "horizon": 1}))
    return NS(output=[fc], output_text="", usage=_usage(call))


def _text(text: str, call: tuple[int, int, int]) -> NS:
    return NS(output_text="", output=[NS(type="message", content=[NS(type="output_text", text=text)])],
              usage=_usage(call))


class _Client:
    def __init__(self, *responses: NS) -> None:
        self.responses = self
        self.queue = list(responses)

    def create(self, **_kwargs):
        return self.queue.pop(0)


def _turn():
    client = _Client(
        _tool_call("p1", PRIMARY_TOOL), _text("Groß.", PRIMARY_SYNTH),
        _tool_call("r1", RETRY_TOOL), _text("Groß, 73,3.", RETRY_SYNTH),
    )
    result = ask_orchestrated(QUESTION, BOOTSTRAP, provider=PROVIDER_OPENAI, model=MODEL, client=client,
                              api_key="test-key", _eval_client=object())
    assert client.queue == [], "the turn did not make the four calls the fixture models"
    return result


def _served_tokens(monkeypatch) -> dict:
    result = _turn()
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    return harness.ask_v2(QUESTION, BOOTSTRAP, orch_client=object())["tokens"]


def test_retry_cached_tokens_are_recorded(monkeypatch):
    tokens = _served_tokens(monkeypatch)
    assert tokens["retry_input"] == RETRY_TOOL[0] + RETRY_SYNTH[0]
    assert tokens["retry_output"] == RETRY_TOOL[2] + RETRY_SYNTH[2]
    assert tokens["retry_cache_read"] == RETRY_TOOL[1] + RETRY_SYNTH[1]           # 3000
    assert tokens["primary_cache_read"] == PRIMARY_TOOL[1] + PRIMARY_SYNTH[1]     # 1800
    assert tokens["evaluator"] == EVALUATOR


def test_usd_matches_the_hand_calculation(monkeypatch):
    tokens = _served_tokens(monkeypatch)
    # luna: input 0.20, output 1.20, cache_read 0.02 USD per 1M tokens.
    # input  = 1000+1200 (primary) + 17 (evaluator) + 1500+1700 (retry) = 5417
    # cached = 800+1000 (primary) + 1400+1600 (retry)                     = 4800
    # billable input = 5417 - 4800 = 617 (OpenAI: cached is inside input)
    # output = 50+100+40+120 = 310
    # USD = 617*0.20/1e6 + 310*1.20/1e6 + 4800*0.02/1e6
    #     = 0.0001234   + 0.000372     + 0.000096      = 0.0005914
    assert estimate_usd_cost(tokens, MODEL, "openai") == pytest.approx(0.0005914, abs=1e-10)


def test_without_retry_cache_read_the_estimate_was_the_upper_bound(monkeypatch):
    tokens = _served_tokens(monkeypatch)
    before = {k: v for k, v in tokens.items() if k != "retry_cache_read"}
    # cached = 1800 only; billable input = 3617:
    # 3617*0.20/1e6 + 310*1.20/1e6 + 1800*0.02/1e6 = 0.0011314
    assert estimate_usd_cost(before, MODEL, "openai") == pytest.approx(0.0011314, abs=1e-10)
    assert estimate_usd_cost(tokens, MODEL, "openai") < estimate_usd_cost(before, MODEL, "openai")


def test_total_tokens_is_unchanged_by_the_new_field():
    """total_tokens (the quota meter's number) keeps its pre-i130 sum:
    primary in/out/cache + evaluator + retry in/out."""
    r = _turn()
    assert r.retry_cache_read_tokens == 3000
    assert r.total_tokens == (
        sum(PRIMARY_TOOL[0::2]) + sum(PRIMARY_SYNTH[0::2]) + PRIMARY_TOOL[1] + PRIMARY_SYNTH[1]
        + EVALUATOR + sum(RETRY_TOOL[0::2]) + sum(RETRY_SYNTH[0::2])
    )


def test_primary_kept_path_records_the_retry_cache_too():
    """i125(b) path: the retry synthesis writes nothing, the primary is kept --
    the retry calls still ran and were billed, cached share included."""
    client = _Client(
        _tool_call("p1", PRIMARY_TOOL), _text("Groß.", PRIMARY_SYNTH),
        _tool_call("r1", RETRY_TOOL), _text("", RETRY_SYNTH),
    )
    r = ask_orchestrated(QUESTION, BOOTSTRAP, provider=PROVIDER_OPENAI, model=MODEL, client=client,
                         api_key="test-key", _eval_client=object())
    assert r.retry_delivery == orch_mod.RETRY_DELIVERY_PRIMARY_KEPT
    assert r.retry_cache_read_tokens == RETRY_TOOL[1] + RETRY_SYNTH[1]
