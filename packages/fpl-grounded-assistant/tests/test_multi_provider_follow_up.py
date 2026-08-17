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
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_OK,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    _build_multi_tool_follow_up,
    _extract_text_from_response,
    _parse_all_openai_tool_calls,
    ask_orchestrated,
)
from fpl_grounded_assistant.orch_config import get_orch_model  # noqa: E402
from fpl_grounded_assistant.provider_client import (  # noqa: E402
    OpenAIProvider,
    _extract_openai_text,
    _extract_openai_usage,
)
from fpl_grounded_assistant.tool_schema_registry import _ALL_SCHEMAS  # noqa: E402


def _anthropic_tool_response() -> object:
    blocks = [
        NS(type="tool_use", id="ant-1", name="get_current_gameweek", input={}),
        NS(type="tool_use", id="ant-2", name="resolve_player", input={"query": "Salah"}),
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
            name="resolve_player",
            arguments=json.dumps({"query": "Salah"}),
        ),
    ])


def _gemini_tool_response() -> object:
    content = NS(
        role="model",
        thought_signature="preserve-me",
        parts=[
            NS(function_call=NS(name="get_current_gameweek", args={})),
            NS(function_call=NS(name="resolve_player", args={"query": "Salah"})),
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

    def generate_content(self, contents, request_options=None):
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
            "resolve_player",
        ]


def test_openai_follow_up_preserves_output_items_and_call_ids():
    first_response = _openai_tool_response()
    executed = [
        ("oai-1", "get_current_gameweek", {}, {"status": "ok", "gameweek": 1}),
        ("oai-2", "resolve_player", {"query": "Salah"}, {"status": "ok", "player": {}}),
    ]

    follow_up = _build_multi_tool_follow_up(
        PROVIDER_OPENAI, "question", first_response, executed
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
