from __future__ import annotations

import sys

import pytest

from fpl_grounded_assistant import football_intelligence_tools  # noqa: F401
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.orch_config import (
    FOOTBALL_INTELLIGENCE_ENABLED_ENV,
    _TRUTHY,
    is_football_intelligence_enabled,
)
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_TOOL_RESULT_ERROR,
    OUTCOME_UNKNOWN_TOOL,
    _build_tools,
    ask_orchestrated,
)
from fpl_grounded_assistant.tool_schema_registry import (
    FI7B_TOOL_NAMES,
    TOOL_NAMES,
    _ALL_SCHEMAS,
    get_offered_tool_names,
    get_offered_tool_schemas,
    validate_tool_schema_shape,
)
from fpl_tool_runner import run_tool


EXPECTED_FI7B_NAMES = frozenset(
    {
        "get_expected_minutes",
        "get_tactical_role",
        "get_fixture_context",
        "get_player_intelligence",
    }
)
FORBIDDEN_MODULES = frozenset(
    {
        "football_intelligence.modules.expected_minutes",
        "football_intelligence.modules.tactical_role",
        "football_intelligence.modules.fixture_context",
    }
)


def _anthropic_names(tools: list[dict[str, object]]) -> tuple[str, ...]:
    return tuple(str(tool["name"]) for tool in tools)


class _AnthropicToolClient:
    def __init__(self, tool_name: str, tool_input: dict[str, object]) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self.messages = self

    def create(self, **kwargs: object) -> object:
        tool_name = self._tool_name
        tool_input = dict(self._tool_input)

        class _ToolBlock:
            type = "tool_use"
            id = "toolu_fi7b1"
            name = tool_name
            input = tool_input

        class _Response:
            content = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()


def test_static_registry_is_33_under_both_flag_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert len(_ALL_SCHEMAS) == 33
    assert len(TOOL_NAMES) == 33
    assert FI7B_TOOL_NAMES == EXPECTED_FI7B_NAMES
    assert all(validate_tool_schema_shape(schema) for schema in _ALL_SCHEMAS)

    for value in (None, "1"):
        if value is None:
            monkeypatch.delenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, raising=False)
        else:
            monkeypatch.setenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, value)
        assert len(_ALL_SCHEMAS) == 33


def test_offered_set_is_exactly_29_off_and_33_on() -> None:
    off_names = get_offered_tool_names(False)
    on_names = get_offered_tool_names(True)

    assert len(off_names) == 29
    assert not (off_names & EXPECTED_FI7B_NAMES)
    assert off_names == TOOL_NAMES - EXPECTED_FI7B_NAMES
    assert len(on_names) == 33
    assert on_names == TOOL_NAMES
    assert len(get_offered_tool_schemas(False)) == 29
    assert len(get_offered_tool_schemas(True)) == 33


def test_provider_tool_payload_tracks_only_the_master_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, raising=False)
    off_names = _anthropic_names(_build_tools(None))
    monkeypatch.setenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, "true")
    on_names = _anthropic_names(_build_tools(None))

    assert len(off_names) == 29
    assert not (set(off_names) & EXPECTED_FI7B_NAMES)
    assert len(on_names) == 33
    assert set(on_names) == TOOL_NAMES


@pytest.mark.parametrize("value", sorted(_TRUTHY | {item.upper() for item in _TRUTHY}))
def test_flag_reuses_supported_truthy_forms(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, f" {value} ")
    assert is_football_intelligence_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "enabled", "2"])
def test_flag_defaults_false_and_rejects_other_forms(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, value)
    assert is_football_intelligence_enabled() is False


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("get_expected_minutes", {"player": "Saka"}),
        ("get_tactical_role", {"player": "Saka"}),
        ("get_fixture_context", {"team": "ARS", "fixture": "fixture_1"}),
        ("get_player_intelligence", {"player": "Saka"}),
    ],
)
def test_all_shell_handlers_are_registered_and_honestly_not_implemented(
    name: str,
    args: dict[str, object],
) -> None:
    result = run_tool(name, args, {})
    assert result == {
        "status": "not_implemented",
        "reason_codes": ["not_implemented"],
        "message": "Football intelligence tool implementation is deferred to FI-7b2.",
    }
    assert "confidence" not in result
    assert "evidence" not in result


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("get_expected_minutes", {"player": "Saka"}),
        ("get_tactical_role", {"player": "Saka"}),
        ("get_fixture_context", {"team": "ARS", "fixture": "fixture_1"}),
        ("get_player_intelligence", {"player": "Saka"}),
    ],
)
def test_llm_dispatch_is_unreachable_off_and_callable_on(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    args: dict[str, object],
) -> None:
    monkeypatch.delenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, raising=False)
    off = ask_orchestrated("question", {}, client=_AnthropicToolClient(name, args))
    assert off.outcome == OUTCOME_UNKNOWN_TOOL
    assert off.tool_output == {}

    monkeypatch.setenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, "1")
    on = ask_orchestrated("question", {}, client=_AnthropicToolClient(name, args))
    assert on.outcome == OUTCOME_TOOL_RESULT_ERROR
    assert on.tool_output["status"] == "not_implemented"
    assert "confidence" not in on.tool_output
    assert "evidence" not in on.tool_output


def test_routing_audit_snapshots_master_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, raising=False)
    off_trace = ask_v2("unsupported football question", {})["routing_trace"]
    monkeypatch.setenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, "yes")
    on_trace = ask_v2("unsupported football question", {})["routing_trace"]

    assert off_trace["feature_flag_football_intelligence_enabled"] is False
    assert on_trace["feature_flag_football_intelligence_enabled"] is True


def test_shell_path_imports_no_fi6_modules() -> None:
    assert not (set(sys.modules) & FORBIDDEN_MODULES)
    before = set(sys.modules)
    result = run_tool("get_player_intelligence", {"player": "Saka"}, {})
    newly_imported = set(sys.modules) - before

    assert result["status"] == "not_implemented"
    assert not (newly_imported & FORBIDDEN_MODULES)
    assert not (set(sys.modules) & FORBIDDEN_MODULES)
