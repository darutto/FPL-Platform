"""PR 3: deprecated player adapters stay callable but leave LLM schemas."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.conversation_state import ConversationSession
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_OK,
    OUTCOME_UNKNOWN_TOOL,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    _SYSTEM_PROMPT,
    _build_tools,
    ask_orchestrated,
)
from fpl_grounded_assistant.tool_schema_registry import (
    DEPRECATED_LLM_TOOL_NAMES,
    TOOL_NAMES,
    get_offered_tool_names,
    get_tool_schema,
)
from fpl_tool_runner import run_tool


GENERAL_PLAYER_TOOLS = frozenset({
    "find_players",
    "resolve_player",
    "get_player_summary",
    "get_player_snapshot",
})
SPECIALIZED_PLAYER_TOOLS = frozenset({
    "compare_players",
    "get_captain_score",
    "get_player_fixture_run",
    "get_player_form",
    "get_player_history",
    "get_transfer_advice",
})


def _provider_names(provider: str, *, fi_enabled: bool, web_enabled: bool) -> set[str]:
    tools = _build_tools(
        provider,
        football_intelligence_enabled=fi_enabled,
        web_search_enabled=web_enabled,
    )
    if provider == PROVIDER_OPENAI:
        return {str(tool["name"]) for tool in tools}
    if provider == PROVIDER_GEMINI:
        declarations = tools[0]["function_declarations"]
        return {str(tool["name"]) for tool in declarations}
    return {str(tool["name"]) for tool in tools}


@pytest.mark.parametrize(
    "provider", [PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GEMINI]
)
@pytest.mark.parametrize("fi_enabled", [False, True])
@pytest.mark.parametrize("web_enabled", [False, True])
def test_provider_schemas_offer_snapshot_as_only_general_lookup(
    provider: str, fi_enabled: bool, web_enabled: bool
):
    names = _provider_names(
        provider, fi_enabled=fi_enabled, web_enabled=web_enabled
    )
    assert not (names & DEPRECATED_LLM_TOOL_NAMES)
    assert names & GENERAL_PLAYER_TOOLS == {"get_player_snapshot"}
    assert SPECIALIZED_PLAYER_TOOLS <= names


def test_deprecated_adapters_remain_registered_and_directly_callable(bootstrap: dict):
    assert DEPRECATED_LLM_TOOL_NAMES <= TOOL_NAMES
    assert all(get_tool_schema(name) is not None for name in DEPRECATED_LLM_TOOL_NAMES)
    assert run_tool("resolve_player", {"query": "Haaland"}, bootstrap)["status"] == "ok"
    assert run_tool("get_player_summary", {"query": "Haaland"}, bootstrap)["status"] == "ok"
    found = run_tool("find_players", {"name_query": "Haaland"}, bootstrap)
    assert found["status"] == "ok"
    assert found["matches"][0]["web_name"] == "Haaland"


def test_offered_name_validation_rejects_deprecated_adapters():
    for fi_enabled in (False, True):
        names = get_offered_tool_names(fi_enabled)
        assert not (names & DEPRECATED_LLM_TOOL_NAMES)
        assert "get_player_snapshot" in names


def test_orchestration_guidance_routes_general_and_specialized_questions():
    assert "general named-player profile/current stats: get_player_snapshot" in _SYSTEM_PROMPT
    assert "Recent form: get_player_form" in _SYSTEM_PROMPT
    assert "Per-GW history: get_player_history" in _SYSTEM_PROMPT
    assert "Player fixtures: get_player_fixture_run" in _SYSTEM_PROMPT
    assert "Comparisons: compare_players" in _SYSTEM_PROMPT
    assert not any(name in _SYSTEM_PROMPT for name in DEPRECATED_LLM_TOOL_NAMES)


class _SnapshotChoosingClient:
    def __init__(self, tool_name: str = "get_player_snapshot") -> None:
        self.messages = self
        self.offered_names: set[str] = set()
        self.tool_name = tool_name

    def create(self, **kwargs: object) -> object:
        self.offered_names = {
            str(tool["name"])
            for tool in kwargs["tools"]  # type: ignore[index]
        }

        class _ToolBlock:
            type = "tool_use"
            id = "toolu_snapshot_only"
            name = self.tool_name
            input = (
                {"player_name": "Haaland"}
                if self.tool_name == "get_player_snapshot"
                else {"query": "Haaland"}
            )

        class _Response:
            content = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()


def test_mocked_general_player_orchestration_can_choose_only_snapshot(bootstrap: dict):
    client = _SnapshotChoosingClient()
    result = ask_orchestrated(
        "Please give me the current profile for Haaland",
        bootstrap,
        client=client,
        provider=PROVIDER_ANTHROPIC,
    )
    assert not (client.offered_names & DEPRECATED_LLM_TOOL_NAMES)
    assert result.outcome == OUTCOME_OK
    assert result.tool_chosen == "get_player_snapshot"
    assert result.tool_output["status"] == "ok"


@pytest.mark.parametrize("tool_name", sorted(DEPRECATED_LLM_TOOL_NAMES))
def test_hallucinated_deprecated_tool_is_rejected_before_execution(
    bootstrap: dict, tool_name: str
):
    client = _SnapshotChoosingClient(tool_name)
    result = ask_orchestrated(
        "Please give me the current profile for Haaland",
        bootstrap,
        client=client,
        provider=PROVIDER_ANTHROPIC,
    )
    assert tool_name not in client.offered_names
    assert result.outcome == OUTCOME_UNKNOWN_TOOL
    assert result.tool_chosen == tool_name
    assert result.tool_output == {}


def test_unavailable_session_uses_snapshot_not_legacy_summary(
    monkeypatch: pytest.MonkeyPatch, bootstrap: dict
):
    monkeypatch.delenv("FPL_ORCH_ENABLED", raising=False)
    response = ConversationSession().respond("I want stats for Haaland", bootstrap)
    assert response.intent == "player_snapshot"
    assert response.outcome == "ok"
    assert response.player_snapshot is not None


def test_unavailable_session_explicit_miss_never_emits_legacy_resolve(
    monkeypatch: pytest.MonkeyPatch, bootstrap: dict
):
    monkeypatch.delenv("FPL_ORCH_ENABLED", raising=False)
    response = ConversationSession().respond("Please tell me about Zidane", bootstrap)
    assert response.intent == "player_snapshot"
    assert response.outcome == "not_found"
    assert response.llm_used is False
