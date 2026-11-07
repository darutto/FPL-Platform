"""en locale: one turn note as the LAST input item of every OpenAI Responses request. No network, synthetic data.

A local request capture (en locale, a Spanish question, the OpenAI path) showed the system-prompt EN line reaches the
model on every round but is followed only by English context, so the model's last read is the question or the tool
results. These tests drive the production path (``ask_orchestrated`` -> ``call_orch_provider`` -> ``responses.create``)
with a recording client and pin: the note is last on every round, once per request (also over two turns and on the
evaluator-driven retry), absent for es, never stored or echoed, and not added to the evaluator's own request.
Anthropic and Gemini keep only the system-prompt line: the whole LLM runs on OpenAI.
"""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace as NS

import pytest

from conftest import BOOTSTRAP
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.orchestrator import PROVIDER_OPENAI, _EN_TURN_NOTE, _with_locale_note, ask_orchestrated

ES_Q = "¿Mbeumo ha cambiado de posición?"
OUTPUT = {"status": "ok", "current_gameweek": {"id": 5, "finished": True}, "next_gameweek": {"id": 6}}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    real = socket.socket.connect

    def loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"must not touch the network: {address!r}")
        return real(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    for var in ("FPL_JEV_MODE", "FPL_ORCH_LOOP_ENABLED", "FPL_ORCH_LOOP_PROMPT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr(orch_mod, "run_tool", lambda name, args, bootstrap: json.loads(json.dumps(OUTPUT)))


class _Responses:
    """OpenAI Responses-shaped: one tool call, then prose. Records every create() kwargs."""

    def __init__(self, text: str = "Answer.") -> None:
        self.calls: list[dict] = []
        self._text = text
        self._n = 0

    def create(self, **kw):
        self.calls.append(kw)
        self._n += 1
        usage = NS(input_tokens=1, output_tokens=1)
        if self._n % 2 == 1:
            call = NS(type="function_call", call_id=f"c{self._n}", name="get_gameweek_context", arguments="{}")
            return NS(output=[call], output_text="", usage=usage)
        return NS(output=[NS(type="message", content=[NS(type="output_text", text=self._text)])],
                  output_text=self._text, usage=usage)


def _ask(question: str, locale: str, client=None):
    client = client or NS(responses=_Responses())
    result = ask_orchestrated(question, BOOTSTRAP, client=client, provider=PROVIDER_OPENAI, model="gpt-5.6-luna", locale=locale)
    return result, client.responses.calls


def _notes(call: dict) -> list:
    return [i for i in call["input"] if isinstance(i, dict) and i.get("role") == "developer"]


def test_en_puts_one_note_last_on_round_1_and_round_2():
    result, calls = _ask(ES_Q, "en")
    assert result.outcome == "ok" and len(calls) == 2
    for call in calls:
        assert call["input"][-1] == {"role": "developer", "content": _EN_TURN_NOTE}
        assert len(_notes(call)) == 1
        assert "LOCALE=en" in call["instructions"]  # the system-prompt line stays
    assert [i.get("role") for i in calls[0]["input"] if isinstance(i, dict) and "role" in i] == ["user", "developer"]
    assert calls[1]["input"][0] == {"role": "user", "content": ES_Q}  # the question is never rewritten
    assert any(getattr(i, "type", None) == "function_call" or (isinstance(i, dict) and i.get("type") == "function_call_output")
               for i in calls[1]["input"])


def test_the_note_names_no_question_language():
    assert "Spanish" not in _EN_TURN_NOTE and "English" not in _EN_TURN_NOTE.replace("British English", "")
    assert "whatever language the question is in" in _EN_TURN_NOTE


def test_the_note_asks_for_no_personal_pronoun_for_a_player_without_commenting_on_it():
    assert _EN_TURN_NOTE.startswith("LOCALE=en: write the whole answer in British English, whatever language the question is in.")
    assert 'by name or "the player"' in _EN_TURN_NOTE
    assert "no personal pronoun (he, him, his, she, her, they, them, their) is needed for a player" in _EN_TURN_NOTE
    assert "do not mention this rule" in _EN_TURN_NOTE
    assert '"they"' not in _EN_TURN_NOTE  # "they" is no longer offered as a way to refer to a player


def test_es_requests_are_untouched():
    result, calls = _ask(ES_Q, "es")
    assert len(calls) == 2
    for call in calls:
        assert _notes(call) == [] and "LOCALE=en" not in call["instructions"]
        assert call["instructions"].startswith(orch_mod._SYSTEM_PROMPT)
    assert calls[0]["input"] == [{"role": "user", "content": ES_Q}]


def test_two_en_turns_each_carry_a_single_note_that_does_not_accumulate():
    client = NS(responses=_Responses())
    _ask("Who should I captain?", "en", client)
    _ask(ES_Q, "en", client)
    calls = client.responses.calls
    assert len(calls) == 4
    for call in calls:
        assert len(_notes(call)) == 1 and call["input"][-1]["role"] == "developer"
    turn2 = calls[2:]
    assert not any("Who should I captain?" in json.dumps(i, default=str) for c in turn2 for i in c["input"])  # no replay


def test_the_note_is_not_stored_echoed_or_audited():
    result, calls = _ask(ES_Q, "en")
    assert result.question == ES_Q
    assert _EN_TURN_NOTE not in (result.answer_text or "")
    assert "LOCALE=en" not in json.dumps(result.tool_output, default=str)
    assert all("LOCALE=en: write" not in json.dumps(i, default=str) for c in calls for i in c["input"][:-1])  # only ever the last item


def test_anthropic_gemini_and_unknown_providers_get_no_note():
    base = [{"role": "user", "content": ES_Q}]
    for provider in ("anthropic", "gemini", None):
        assert _with_locale_note(provider, "en", base) is base
    assert _with_locale_note(PROVIDER_OPENAI, "es", base) is base
    assert _with_locale_note(PROVIDER_OPENAI, "en", base) == [*base, {"role": "developer", "content": _EN_TURN_NOTE}]
    assert base == [{"role": "user", "content": ES_Q}]  # the caller's list is never mutated


class _RejectingEvaluator:
    """OpenAI Responses-shaped evaluator (it follows the provider) that rejects once, recording its whole request."""

    def __init__(self) -> None:
        self.responses = self
        self.kwargs: list[dict] = []

    def create(self, **kw):
        self.kwargs.append(kw)
        verdict = {"grounded": False, "complete": True, "safe": True, "retry_feedback": "Cite the concrete values."}
        text = json.dumps(verdict)
        return NS(output=[NS(type="message", content=[NS(type="output_text", text=text)])], output_text=text,
                  usage=NS(input_tokens=5, output_tokens=5))


def test_the_evaluator_request_is_unchanged_and_the_retry_round_carries_one_note(monkeypatch):
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    evaluator = _RejectingEvaluator()
    client = NS(responses=_Responses())
    result = ask_orchestrated(ES_Q, BOOTSTRAP, client=client, _eval_client=evaluator, provider=PROVIDER_OPENAI,
                              model="gpt-5.6-luna", locale="en")
    assert result.retry_attempted is True and evaluator.kwargs
    assert all(_EN_TURN_NOTE not in json.dumps(kw, default=str) for kw in evaluator.kwargs)  # evaluator: deliberately unchanged
    calls = client.responses.calls
    assert len(calls) >= 3
    for call in calls:
        assert len(_notes(call)) == 1 and call["input"][-1] == {"role": "developer", "content": _EN_TURN_NOTE}
    retry = next(c for c in calls if "Previous attempt feedback" in json.dumps(c["input"], default=str))
    assert retry["input"][-1]["role"] == "developer"
