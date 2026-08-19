"""Provider-native multi-tool follow-ups and OpenAI Responses contracts."""
from __future__ import annotations

import json
import logging
import os
import sys
from types import SimpleNamespace as NS

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
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_OK,
    OUTCOME_NO_TOOL,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    _build_multi_tool_follow_up,
    _FailureGate,
    _LOOP_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    _extract_text_from_response,
    _parse_all_openai_tool_calls,
    ask_orchestrated,
)
from fpl_grounded_assistant.orch_config import get_orch_model  # noqa: E402
from fpl_grounded_assistant.orch_config import get_orch_max_rounds  # noqa: E402
from fpl_grounded_assistant.provider_client import (  # noqa: E402
    OpenAIProvider,
    _extract_openai_text,
    _extract_openai_usage,
)
from fpl_grounded_assistant.tool_schema_registry import _ALL_SCHEMAS  # noqa: E402


def _anthropic_tool_response() -> object:
    blocks = [
        NS(type="tool_use", id="ant-1", name="get_current_gameweek", input={}),
        NS(type="tool_use", id="ant-2", name="get_player_snapshot", input={"player_name": "Salah"}),
    ]
    return NS(content=blocks, stop_reason="tool_use")


def _openai_tool_response() -> object:
    return NS(output=[
        NS(type="reasoning", id="reasoning-1"),
        NS(
            type="function_call",
            call_id="oai-1",
            name="get_current_gameweek",
            arguments="{}",
        ),
        NS(
            type="function_call",
            call_id="oai-2",
            name="get_player_snapshot",
            arguments=json.dumps({"player_name": "Salah"}),
        ),
    ])


def _gemini_tool_response() -> object:
    content = NS(
        role="model",
        thought_signature="preserve-me",
        parts=[
            NS(function_call=NS(name="get_current_gameweek", args={})),
            NS(function_call=NS(name="get_player_snapshot", args={"player_name": "Salah"})),
        ],
    )
    return NS(candidates=[NS(content=content)])


class _AnthropicClient:
    def __init__(self, *, second_text: str | None = "Anthropic synthesis") -> None:
        self.messages = self
        self.calls: list[dict] = []
        self.second_text = second_text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return _anthropic_tool_response()
        if self.second_text is None:
            return NS(content=[])
        return NS(content=[NS(type="text", text=self.second_text)])


class _OpenAIClient:
    def __init__(self) -> None:
        self.responses = self
        self.calls: list[dict] = []
        self.first_response = _openai_tool_response()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return self.first_response
        return NS(
            output_text="",
            output=[
                NS(type="reasoning", id="reasoning-2"),
                NS(type="message", content=[NS(type="output_text", text="OpenAI synthesis")]),
            ],
        )


class _GeminiClient:
    def __init__(self) -> None:
        self.calls: list[list[object]] = []
        self.first_response = _gemini_tool_response()

    def generate_content(self, contents, generation_config=None, request_options=None):
        self.calls.append(contents)
        if len(self.calls) == 1:
            return self.first_response
        return NS(candidates=[NS(content=NS(parts=[NS(text="Gemini synthesis")]))])


@pytest.mark.parametrize(
    ("provider", "client_factory", "expected"),
    [
        (PROVIDER_ANTHROPIC, _AnthropicClient, "Anthropic synthesis"),
        (PROVIDER_OPENAI, _OpenAIClient, "OpenAI synthesis"),
        (PROVIDER_GEMINI, _GeminiClient, "Gemini synthesis"),
    ],
)
def test_two_tools_receive_one_provider_native_follow_up(
    monkeypatch, bootstrap, provider, client_factory, expected
):
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)
    monkeypatch.setattr(provider_client, "_GEMINI_AVAILABLE", True)
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
    assert result.answer_text == expected
    assert result.tool_call_count == 2
    assert len(client.calls) == 2

    if provider == PROVIDER_ANTHROPIC:
        follow_up = client.calls[1]["messages"]
        result_blocks = follow_up[-1]["content"]
        assert [block["tool_use_id"] for block in result_blocks] == ["ant-1", "ant-2"]
    elif provider == PROVIDER_OPENAI:
        follow_up = client.calls[1]["input"]
        assert follow_up[1:4] == client.first_response.output
        outputs = [item for item in follow_up if isinstance(item, dict)]
        assert [item["call_id"] for item in outputs if item.get("type") == "function_call_output"] == [
            "oai-1",
            "oai-2",
        ]
    else:
        follow_up = client.calls[1]
        assert follow_up[1] is client.first_response.candidates[0].content
        responses = follow_up[2]["parts"]
        assert [part["function_response"]["name"] for part in responses] == [
            "get_current_gameweek",
            "get_player_snapshot",
        ]


def test_openai_follow_up_preserves_output_items_and_call_ids():
    first_response = _openai_tool_response()
    executed = [
        ("oai-1", "get_current_gameweek", {}, {"status": "ok", "gameweek": 1}),
        ("oai-2", "get_player_snapshot", {"player_name": "Salah"}, {"status": "ok", "player": {}}),
    ]

    follow_up = _build_multi_tool_follow_up(
        PROVIDER_OPENAI,
        [{"role": "user", "content": "question"}],
        first_response,
        executed,
    )

    assert follow_up[1:4] == first_response.output
    outputs = [item for item in follow_up if isinstance(item, dict) and item.get("type") == "function_call_output"]
    assert [item["call_id"] for item in outputs] == ["oai-1", "oai-2"]
    assert len(outputs) == len(executed)


def test_openai_parser_and_text_ignore_output_position():
    response = _openai_tool_response()
    assert [call[0] for call in _parse_all_openai_tool_calls(response)] == ["oai-1", "oai-2"]

    text_response = NS(
        output_text="",
        output=[
            NS(type="reasoning"),
            NS(type="function_call", call_id="ignored", name="x", arguments="{}"),
            NS(type="message", content=[NS(type="output_text", text="hello ")]),
            NS(type="message", content=[NS(type="output_text", text="world")]),
        ],
    )
    assert _extract_text_from_response(text_response, PROVIDER_OPENAI) == "hello world"
    assert _extract_openai_text(text_response) == "hello world"


def test_openai_provider_uses_responses_request_shape():
    class Responses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return NS(output_text="provider answer", output=[])

    responses = Responses()
    provider = object.__new__(OpenAIProvider)
    provider._client = NS(responses=responses)

    result = provider.call(
        model="gpt-test",
        system_prompt="system",
        user_message="question",
        max_tokens=123,
        max_retries=0,
    )

    assert result.text == "provider answer"
    assert responses.kwargs["instructions"] == "system"
    assert responses.kwargs["input"] == [{"role": "user", "content": "question"}]
    assert responses.kwargs["max_output_tokens"] == 123
    assert "messages" not in responses.kwargs
    assert "max_tokens" not in responses.kwargs


def test_all_openai_tool_schemas_use_flat_responses_shape():
    for schema in _ALL_SCHEMAS:
        tool = schema.to_openai()
        assert tool["type"] == "function"
        assert tool["name"] == schema.name
        assert tool["parameters"] == schema.parameters
        assert tool["strict"] is False
        assert "function" not in tool


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (NS(input_tokens=12, output_tokens=7, input_tokens_details=NS(cached_tokens=5)), (12, 7, 5)),
        (NS(input_tokens=12, output_tokens=7), (12, 7, None)),
        (None, (None, None, None)),
    ],
)
def test_openai_responses_usage_variants(usage, expected):
    assert _extract_openai_usage(NS(usage=usage)) == expected


def test_successful_second_call_without_text_warns_and_falls_back(caplog, bootstrap):
    client = _AnthropicClient(second_text=None)
    with caplog.at_level(logging.WARNING):
        result = ask_orchestrated(
            "What gameweek is it and who is Salah?",
            bootstrap,
            provider=PROVIDER_ANTHROPIC,
            client=client,
            _eval_client=None,
        )

    assert result.answer_text
    assert "succeeded but returned no text" in caplog.text


def test_single_tool_makes_only_one_call(bootstrap):
    class Client:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return NS(content=[NS(
                type="tool_use",
                id="ant-only",
                name="get_current_gameweek",
                input={},
            )])

    client = Client()
    result = ask_orchestrated(
        "What gameweek is it?", bootstrap, client=client, _eval_client=None
    )
    assert result.outcome == OUTCOME_OK
    assert client.calls == 1


def test_gemini_orchestrator_default_model(monkeypatch):
    monkeypatch.delenv("FPL_ORCH_MODEL", raising=False)
    assert get_orch_model(PROVIDER_GEMINI) == "gemini-3.5-flash"


def test_gemini_orchestrator_forwards_generation_controls(monkeypatch):
    monkeypatch.setattr(provider_client, "_GEMINI_AVAILABLE", True)

    class Client:
        def __init__(self):
            self.kwargs = None

        def generate_content(self, contents, **kwargs):
            self.kwargs = kwargs
            return NS(candidates=[NS(content=NS(parts=[NS(text="done")]))])

    client = Client()
    ask_orchestrated(
        "off topic",
        {"events": [], "elements": [], "teams": [], "element_types": []},
        provider=PROVIDER_GEMINI,
        client=client,
        api_key="test-key",
        max_tokens=4096,
        temperature=0.2,
        top_p=0.9,
        _eval_client=None,
    )
    assert client.kwargs["generation_config"] == {
        "max_output_tokens": 4096,
        "temperature": 0.2,
        "top_p": 0.9,
    }


def test_experiment_output_suffix_is_flag_gated(monkeypatch, bootstrap):
    class Client:
        def __init__(self):
            self.messages = self
            self.systems = []

        def create(self, **kwargs):
            self.systems.append(kwargs["system"])
            return NS(content=[NS(type="text", text="done")])

    client = Client()
    monkeypatch.delenv("FPL_ORCH_EXPERIMENT_OUTPUT", raising=False)
    ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert "EXPERIMENT_EVALUATION_OUTPUT" not in str(client.systems[-1])

    monkeypatch.setenv("FPL_ORCH_EXPERIMENT_OUTPUT", "1")
    ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert "EXPERIMENT_EVALUATION_OUTPUT" in str(client.systems[-1])


def test_anthropic_orchestrator_forwards_generation_controls(bootstrap):
    class Client:
        def __init__(self):
            self.messages = self
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return NS(content=[NS(type="text", text="done")])

    client = Client()
    ask_orchestrated(
        "question",
        bootstrap,
        client=client,
        max_tokens=4096,
        temperature=0.2,
        top_p=0.9,
        _eval_client=None,
    )
    assert client.kwargs["max_tokens"] == 4096
    assert client.kwargs["temperature"] == 0.2
    assert client.kwargs["top_p"] == 0.9


def test_openai_orchestrator_forwards_generation_controls(monkeypatch, bootstrap):
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)

    class Client:
        def __init__(self):
            self.responses = self
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return NS(output_text="done", output=[])

    client = Client()
    ask_orchestrated(
        "question",
        bootstrap,
        provider=PROVIDER_OPENAI,
        client=client,
        api_key="test-key",
        max_tokens=4096,
        temperature=0.2,
        top_p=0.9,
        _eval_client=None,
    )
    assert client.kwargs["max_output_tokens"] == 4096
    assert client.kwargs["temperature"] == 0.2
    assert client.kwargs["top_p"] == 0.9


def test_verdict_only_records_rejection_without_primary_retry(monkeypatch, bootstrap):
    class Client:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return NS(content=[NS(
                type="tool_use",
                id="ant-only",
                name="get_current_gameweek",
                input={},
            )])

    verdict = EvaluatorVerdict(
        approved=False,
        grounded=True,
        complete=False,
        safe=True,
        retry_feedback="answer every requested part",
        tokens_used=17,
    )
    monkeypatch.setenv("FPL_ORCH_EVAL_VERDICT_ONLY", "1")
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.evaluate_response",
        lambda **kwargs: verdict,
    )
    client = Client()
    result = ask_orchestrated(
        "What gameweek is it?",
        bootstrap,
        client=client,
        _eval_client=object(),
    )

    assert result.evaluator_verdict is verdict
    assert result.retry_attempted is False
    assert result.evaluator_input_tokens == 17
    assert client.calls == 1


def _action_response(provider: str, call_id: str, name: str, args: dict, narration: str = ""):
    if provider == PROVIDER_OPENAI:
        output = []
        if narration:
            output.append(NS(type="message", content=[NS(type="output_text", text=narration)]))
        output.append(NS(
            type="function_call",
            call_id=call_id,
            name=name,
            arguments=json.dumps(args),
        ))
        return NS(output=output, output_text="")
    if provider == PROVIDER_GEMINI:
        parts = []
        if narration:
            parts.append(NS(text=narration))
        parts.append(NS(function_call=NS(name=name, args=args)))
        return NS(candidates=[NS(content=NS(
            role="model",
            thought_signature=f"sig-{call_id}",
            parts=parts,
        ))])
    blocks = []
    if narration:
        blocks.append(NS(type="text", text=narration))
    blocks.append(NS(type="tool_use", id=call_id, name=name, input=args))
    return NS(content=blocks, stop_reason="tool_use")


def _text_response(provider: str, text_value: str):
    if provider == PROVIDER_OPENAI:
        return NS(
            output_text="",
            output=[NS(type="message", content=[NS(type="output_text", text=text_value)])],
        )
    if provider == PROVIDER_GEMINI:
        return NS(candidates=[NS(content=NS(parts=[NS(text=text_value)]))])
    return NS(content=[NS(type="text", text=text_value)])


class _SequenceClient:
    def __init__(self, provider: str, responses: list[object]):
        self.provider = provider
        self.responses = self
        self.messages = self
        self.queue = list(responses)
        self.calls: list[object] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def generate_content(self, contents, **kwargs):
        self.calls.append(contents)
        response = self.queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _enable_loop(monkeypatch, rounds: int = 3):
    monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", str(rounds))
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)
    monkeypatch.setattr(provider_client, "_GEMINI_AVAILABLE", True)


@pytest.mark.parametrize("provider", [PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GEMINI])
def test_loop_converges_with_provider_native_message_accumulation(
    monkeypatch, bootstrap, provider
):
    _enable_loop(monkeypatch)
    first = _action_response(provider, "call-1", "get_current_gameweek", {})
    second = _action_response(
        provider, "call-2", "get_player_snapshot", {"player_name": "Salah"}
    )
    client = _SequenceClient(provider, [first, second, _text_response(provider, "final answer")])

    result = ask_orchestrated(
        "question",
        bootstrap,
        provider=provider,
        client=client,
        api_key="test-key",
        _eval_client=None,
    )

    assert result.outcome == OUTCOME_OK
    assert result.answer_text == "final answer"
    assert result.rounds_used == 2
    assert result.rounds_exhausted is False
    assert len(client.calls) == result.rounds_used + 1
    assert [entry["name"] for entry in result.tool_calls_trace] == [
        "get_current_gameweek", "get_player_snapshot",
    ]
    if provider == PROVIDER_ANTHROPIC:
        third_messages = client.calls[2]["messages"]
        assert len(third_messages) == 5
        assert third_messages[1]["content"] is first.content
        assert third_messages[3]["content"] is second.content
    elif provider == PROVIDER_OPENAI:
        third_input = client.calls[2]["input"]
        ids = [getattr(item, "call_id", None) for item in third_input]
        assert "call-1" in ids and "call-2" in ids
        result_ids = [item.get("call_id") for item in third_input if isinstance(item, dict)]
        assert "call-1" in result_ids and "call-2" in result_ids
    else:
        third_contents = client.calls[2]
        assert first.candidates[0].content in third_contents
        assert second.candidates[0].content in third_contents
        assert first.candidates[0].content.thought_signature == "sig-call-1"


def test_loop_cap_ignores_action_narration_and_selects_latest_success(
    monkeypatch, bootstrap
):
    _enable_loop(monkeypatch, rounds=2)
    responses = [
        _action_response(PROVIDER_ANTHROPIC, "call-1", "get_current_gameweek", {}),
        _action_response(
            PROVIDER_ANTHROPIC,
            "call-2",
            "get_player_snapshot",
            {"player_name": "Salah"},
        ),
        _action_response(
            PROVIDER_ANTHROPIC,
            "call-3",
            "get_current_gameweek",
            {},
            narration="NARRATION IS NOT THE ANSWER",
        ),
    ]
    client = _SequenceClient(PROVIDER_ANTHROPIC, responses)
    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)

    assert result.outcome == OUTCOME_OK
    assert result.rounds_used == 2
    assert result.rounds_exhausted is True
    assert len(client.calls) == 3
    assert "NARRATION IS NOT THE ANSWER" not in result.answer_text
    assert result.answer_text.startswith("Respuesta incompleta")
    assert result.tool_chosen == "get_player_snapshot"
    assert result.tool_output == result.tool_calls_trace[-1]["output"]


def test_follow_up_provider_failure_returns_latest_grounded_partial(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "call-1", "get_current_gameweek", {}),
        TimeoutError("provider down"),
    ])
    gate = _FailureGate(threshold=1, window_s=60, cooldown_s=30)
    result = ask_orchestrated(
        "question", bootstrap, client=client, _eval_client=None, _gate=gate,
    )
    assert result.outcome == OUTCOME_OK
    assert result.tool_chosen == "get_current_gameweek"
    assert result.rounds_used == 1
    assert result.rounds_exhausted is False
    assert "Respuesta incompleta" in result.answer_text
    assert gate.is_open()


def test_unknown_tool_is_fed_back_then_recovered(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "bad-1", "invented_tool", {}),
        _action_response(PROVIDER_ANTHROPIC, "ok-2", "get_current_gameweek", {}),
        _text_response(PROVIDER_ANTHROPIC, "recovered"),
    ])
    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert result.answer_text == "recovered"
    assert result.outcome == OUTCOME_OK
    assert result.rounds_used == 2
    assert [entry["success"] for entry in result.tool_calls_trace] == [False, True]
    second_messages = client.calls[1]["messages"]
    assert "unknown_tool" in str(second_messages[-1])


def test_non_ok_tool_result_is_passed_through_then_recovered(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "bad-1", "get_player_snapshot", {}),
        _action_response(PROVIDER_ANTHROPIC, "ok-2", "get_current_gameweek", {}),
        _text_response(PROVIDER_ANTHROPIC, "recovered"),
    ])
    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert result.answer_text == "recovered"
    assert [entry["success"] for entry in result.tool_calls_trace] == [False, True]
    assert "missing_argument" in str(client.calls[1]["messages"][-1])


@pytest.mark.parametrize("status", ["ambiguous", "not_found"])
def test_identity_resolution_status_is_a_usable_loop_observation(
    monkeypatch, bootstrap, status
):
    _enable_loop(monkeypatch)
    import fpl_grounded_assistant.orchestrator as orch

    raw = {
        "status": status,
        "query": "Silva",
        "candidates": [{"id": 1, "web_name": "Silva"}] if status == "ambiguous" else [],
        "message": "Choose a player" if status == "ambiguous" else "No player found",
    }
    monkeypatch.setattr(orch, "run_tool", lambda *args, **kwargs: raw)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(
            PROVIDER_ANTHROPIC,
            "lookup-1",
            "get_player_snapshot",
            {"player_name": "Silva"},
        ),
        _text_response(PROVIDER_ANTHROPIC, "Necesito que elijas el jugador exacto."),
    ])

    result = ask_orchestrated("Compara a Silva", bootstrap, client=client, _eval_client=None)

    assert result.outcome == OUTCOME_OK
    assert result.tool_chosen == "get_player_snapshot"
    assert result.tool_output is raw
    assert result.tool_call_count == 1
    assert result.tool_calls_trace[0]["success"] is True
    assert result.answer_text == "Necesito que elijas el jugador exacto."


def test_textless_loop_fallback_is_valid_spanish(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [NS(content=[])])

    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)

    assert result.answer_text == "No encontré una herramienta para responder a esto."
    assert "Ã" not in result.answer_text


def test_handler_exception_is_fed_back_and_can_recover(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    import fpl_grounded_assistant.orchestrator as orch

    original = orch.run_tool
    calls = 0

    def flaky_run_tool(name, args, supplied_bootstrap):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("handler exploded")
        return original(name, args, supplied_bootstrap)

    monkeypatch.setattr(orch, "run_tool", flaky_run_tool)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "call-1", "get_current_gameweek", {}),
        _action_response(PROVIDER_ANTHROPIC, "call-2", "get_current_gameweek", {}),
        _text_response(PROVIDER_ANTHROPIC, "recovered"),
    ])
    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert result.answer_text == "recovered"
    assert [entry["success"] for entry in result.tool_calls_trace] == [False, True]
    assert "tool_exception" in str(client.calls[1]["messages"][-1])


def test_two_consecutive_failing_rounds_abort_without_success(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        _action_response(PROVIDER_ANTHROPIC, "bad-1", "invented_one", {}),
        _action_response(PROVIDER_ANTHROPIC, "bad-2", "invented_two", {}),
        _text_response(PROVIDER_ANTHROPIC, "ignored after abort"),
    ])
    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert result.outcome == OUTCOME_NO_TOOL
    assert result.rounds_used == 2
    assert len(client.calls) == 2
    assert client.queue == [_text_response(PROVIDER_ANTHROPIC, "ignored after abort")]
    assert "two consecutive failing tool rounds" in result.error


def test_any_success_in_a_mixed_round_resets_failure_counter(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    mixed = NS(content=[
        NS(type="tool_use", id="bad-1", name="invented_tool", input={}),
        NS(type="tool_use", id="ok-1", name="get_current_gameweek", input={}),
    ])
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        mixed,
        _action_response(PROVIDER_ANTHROPIC, "bad-2", "invented_again", {}),
        _text_response(PROVIDER_ANTHROPIC, "still converged"),
    ])
    result = ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert result.outcome == OUTCOME_OK
    assert result.answer_text == "still converged"
    assert result.rounds_used == 2
    assert [entry["success"] for entry in result.tool_calls_trace] == [False, True, False]
    assert result.tool_call_count == 3


def test_loop_observability_preserves_evaluator_retry_call_count(monkeypatch, bootstrap):
    _enable_loop(monkeypatch)
    monkeypatch.delenv("FPL_ORCH_EVAL_VERDICT_ONLY", raising=False)
    verdict = EvaluatorVerdict(
        approved=False,
        grounded=True,
        complete=False,
        safe=True,
        retry_feedback="retry once",
        tokens_used=5,
    )
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.evaluate_response",
        lambda **kwargs: verdict,
    )
    mixed = NS(content=[
        NS(type="tool_use", id="ok-1", name="get_current_gameweek", input={}),
        NS(type="tool_use", id="bad-1", name="invented_one", input={}),
        NS(type="tool_use", id="bad-2", name="invented_two", input={}),
    ])
    client = _SequenceClient(PROVIDER_ANTHROPIC, [
        mixed,
        _text_response(PROVIDER_ANTHROPIC, "primary answer"),
        _action_response(PROVIDER_ANTHROPIC, "retry-1", "get_current_gameweek", {}),
    ])

    result = ask_orchestrated(
        "question",
        bootstrap,
        client=client,
        _eval_client=object(),
    )

    assert result.retry_attempted is True
    assert result.tool_call_count == 1
    assert result.tool_chosen == "get_current_gameweek"


@pytest.mark.parametrize(("raw", "expected"), [("0", 1), ("9", 5), ("bad", 3)])
def test_loop_round_config_is_clamped(monkeypatch, raw, expected):
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", raw)
    assert get_orch_max_rounds() == expected


def test_loop_prompt_is_independent_and_preserves_grounding_rules(monkeypatch, bootstrap):
    class Client:
        def __init__(self):
            self.messages = self
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return NS(content=[NS(type="text", text="done")])

    assert "single_source_per_turn" in _SYSTEM_PROMPT
    assert "single_source_per_turn" not in _LOOP_SYSTEM_PROMPT
    assert "CLASSIFY query → ONE source:" in _SYSTEM_PROMPT
    assert "CLASSIFY query → one or more relevant sources:" in _LOOP_SYSTEM_PROMPT
    assert "rank_players_by_metric FIRST;" in _LOOP_SYSTEM_PROMPT
    assert "ITERATIVE TOOL USE" in _LOOP_SYSTEM_PROMPT
    assert "TOOL_OUTPUT_TRUST" in _LOOP_SYSTEM_PROMPT
    assert "minutes_played_season + status + news" in _LOOP_SYSTEM_PROMPT

    client = Client()
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_LOOP_PROMPT", "1")
    ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert "ITERATIVE TOOL USE" in str(client.calls[-1]["system"])
    assert len(client.calls) == 1

    monkeypatch.delenv("FPL_ORCH_LOOP_PROMPT", raising=False)
    ask_orchestrated("question", bootstrap, client=client, _eval_client=None)
    assert "ITERATIVE TOOL USE" not in str(client.calls[-1]["system"])
