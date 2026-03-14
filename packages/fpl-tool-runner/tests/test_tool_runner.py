"""
tests/test_tool_runner.py
==========================
Tests for fpl_tool_runner — in-process tool registry and dispatch engine.

Test suites
-----------
A.  Import smoke                                            (3 tests)
B.  ToolSpec structure — to_openai / to_anthropic          (6 tests)
C.  ToolRegistry introspection                             (5 tests)
D.  run_tool — resolve_player                              (6 tests)
E.  run_tool — get_player_summary                          (5 tests)
F.  run_tool — get_current_gameweek                        (4 tests)
G.  run_tool — error handling                              (4 tests)
H.  Schema contract (JSON Schema structure)                (4 tests)
I.  Public surface guard                                    (3 tests)
"""
from __future__ import annotations

import copy
import pytest

from tests.conftest import BOOTSTRAP


# ===========================================================================
# A. Import smoke
# ===========================================================================

class TestImportSmoke:
    def test_package_imports(self):
        import fpl_tool_runner
        assert fpl_tool_runner is not None

    def test_key_symbols_present(self):
        import fpl_tool_runner as pkg
        for name in ("ToolSpec", "ToolRegistry", "TOOL_REGISTRY", "TOOL_SPECS", "run_tool"):
            assert hasattr(pkg, name), f"Missing symbol: {name}"

    def test_run_tool_callable(self):
        from fpl_tool_runner import run_tool
        assert callable(run_tool)


# ===========================================================================
# B. ToolSpec structure — to_openai / to_anthropic
# ===========================================================================

class TestToolSpecStructure:
    def test_to_openai_top_level_keys(self):
        from fpl_tool_runner import RESOLVE_PLAYER_SPEC
        d = RESOLVE_PLAYER_SPEC.to_openai()
        assert set(d.keys()) == {"type", "function"}
        assert d["type"] == "function"

    def test_to_openai_function_keys(self):
        from fpl_tool_runner import RESOLVE_PLAYER_SPEC
        fn = RESOLVE_PLAYER_SPEC.to_openai()["function"]
        assert {"name", "description", "parameters"}.issubset(fn.keys())

    def test_to_anthropic_keys(self):
        from fpl_tool_runner import RESOLVE_PLAYER_SPEC
        d = RESOLVE_PLAYER_SPEC.to_anthropic()
        assert {"name", "description", "input_schema"}.issubset(d.keys())

    def test_to_openai_name_matches_spec(self):
        from fpl_tool_runner import GET_PLAYER_SUMMARY_SPEC
        assert GET_PLAYER_SUMMARY_SPEC.to_openai()["function"]["name"] == "get_player_summary"

    def test_to_anthropic_name_matches_spec(self):
        from fpl_tool_runner import GET_CURRENT_GAMEWEEK_SPEC
        assert GET_CURRENT_GAMEWEEK_SPEC.to_anthropic()["name"] == "get_current_gameweek"

    def test_spec_is_frozen(self):
        from fpl_tool_runner import RESOLVE_PLAYER_SPEC
        with pytest.raises((AttributeError, TypeError)):
            RESOLVE_PLAYER_SPEC.name = "tampered"  # type: ignore[misc]


# ===========================================================================
# C. ToolRegistry introspection
# ===========================================================================

class TestToolRegistryIntrospection:
    def test_list_tools_returns_three(self):
        from fpl_tool_runner import TOOL_REGISTRY
        assert len(TOOL_REGISTRY.list_tools()) == 3

    def test_list_tools_contains_expected_names(self):
        from fpl_tool_runner import TOOL_REGISTRY
        names = TOOL_REGISTRY.list_tools()
        assert "resolve_player" in names
        assert "get_player_summary" in names
        assert "get_current_gameweek" in names

    def test_get_spec_returns_tool_spec(self):
        from fpl_tool_runner import TOOL_REGISTRY, ToolSpec
        spec = TOOL_REGISTRY.get_spec("resolve_player")
        assert isinstance(spec, ToolSpec)

    def test_to_openai_tools_length(self):
        from fpl_tool_runner import TOOL_REGISTRY
        tools = TOOL_REGISTRY.to_openai_tools()
        assert len(tools) == 3
        for t in tools:
            assert t["type"] == "function"

    def test_to_anthropic_tools_length(self):
        from fpl_tool_runner import TOOL_REGISTRY
        tools = TOOL_REGISTRY.to_anthropic_tools()
        assert len(tools) == 3
        for t in tools:
            assert "input_schema" in t


# ===========================================================================
# D. run_tool — resolve_player
# ===========================================================================

class TestRunToolResolvePlayer:
    def test_ok_by_name(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("resolve_player", {"query": "Haaland"}, bootstrap)
        assert result["status"] == "ok"
        assert result["player_id"] == 1

    def test_ok_by_numeric_string(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("resolve_player", {"query": "2"}, bootstrap)
        assert result["status"] == "ok"
        assert result["player_id"] == 2

    def test_ok_by_alias(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("resolve_player", {"query": "KDB"}, bootstrap)
        assert result["status"] == "ok"
        assert result["player_id"] == 4

    def test_ambiguous_status(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("resolve_player", {"query": "Johnson"}, bootstrap)
        assert result["status"] == "ambiguous"

    def test_not_found_status(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("resolve_player", {"query": "Zidane"}, bootstrap)
        assert result["status"] == "not_found"

    def test_query_field_preserved(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("resolve_player", {"query": "el Vikingo"}, bootstrap)
        assert result.get("query") == "el Vikingo"
        assert result["player_id"] == 1


# ===========================================================================
# E. run_tool — get_player_summary
# ===========================================================================

class TestRunToolGetPlayerSummary:
    def test_ok_status(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("get_player_summary", {"query": "Haaland"}, bootstrap)
        assert result["status"] == "ok"

    def test_cost_m_correct(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("get_player_summary", {"query": "Haaland"}, bootstrap)
        assert result["cost_m"] == 14.5

    def test_position_present(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("get_player_summary", {"query": "1"}, bootstrap)
        assert result["position"] == "FWD"

    def test_ambiguous_propagated(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("get_player_summary", {"query": "Johnson"}, bootstrap)
        assert result["status"] == "ambiguous"

    def test_not_found_propagated(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("get_player_summary", {"query": "Cantona"}, bootstrap)
        assert result["status"] == "not_found"


# ===========================================================================
# F. run_tool — get_current_gameweek
# ===========================================================================

class TestRunToolGetCurrentGameweek:
    def test_ok_status(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("get_current_gameweek", {}, bootstrap)
        assert result["status"] == "ok"
        assert result["gameweek"] == 28

    def test_empty_args_accepted(self, bootstrap):
        from fpl_tool_runner import run_tool
        # get_current_gameweek takes no user args — passing empty dict must work
        result = run_tool("get_current_gameweek", {}, bootstrap)
        assert "status" in result

    def test_not_found_when_no_flags(self):
        from fpl_tool_runner import run_tool
        bs = {"events": [{"id": 1, "is_current": False, "is_next": False}],
              "elements": [], "teams": [], "element_types": []}
        result = run_tool("get_current_gameweek", {}, bs)
        assert result["status"] == "not_found"

    def test_ok_result_has_exactly_two_keys(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("get_current_gameweek", {}, bootstrap)
        assert set(result.keys()) == {"status", "gameweek"}


# ===========================================================================
# G. run_tool — error handling
# ===========================================================================

class TestRunToolErrors:
    def test_unknown_tool_returns_error_status(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("nonexistent_tool", {}, bootstrap)
        assert result["status"] == "error"
        assert result["code"] == "unknown_tool"

    def test_unknown_tool_message_non_empty(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("nonexistent_tool", {}, bootstrap)
        assert len(result["message"]) > 5

    def test_missing_required_arg_returns_error(self, bootstrap):
        from fpl_tool_runner import run_tool
        # resolve_player requires "query" — omit it
        result = run_tool("resolve_player", {}, bootstrap)
        assert result["status"] == "error"
        assert result["code"] == "missing_argument"

    def test_missing_arg_message_names_the_field(self, bootstrap):
        from fpl_tool_runner import run_tool
        result = run_tool("resolve_player", {}, bootstrap)
        assert "query" in result["message"]


# ===========================================================================
# H. Schema contract
# ===========================================================================

class TestSchemaContract:
    def test_resolve_player_has_query_property(self):
        from fpl_tool_runner import RESOLVE_PLAYER_SPEC
        props = RESOLVE_PLAYER_SPEC.parameters.get("properties", {})
        assert "query" in props

    def test_resolve_player_query_required(self):
        from fpl_tool_runner import RESOLVE_PLAYER_SPEC
        assert "query" in RESOLVE_PLAYER_SPEC.parameters.get("required", [])

    def test_get_current_gameweek_no_required_args(self):
        from fpl_tool_runner import GET_CURRENT_GAMEWEEK_SPEC
        required = GET_CURRENT_GAMEWEEK_SPEC.parameters.get("required", [])
        assert required == []

    def test_all_specs_have_output_schema(self):
        from fpl_tool_runner import TOOL_SPECS
        for spec in TOOL_SPECS:
            assert isinstance(spec.output_schema, dict), \
                f"Spec '{spec.name}' missing output_schema"
            assert len(spec.output_schema) > 0


# ===========================================================================
# I. Public surface guard
# ===========================================================================

class TestPublicSurface:
    def test_all_exports_present(self):
        import fpl_tool_runner as pkg
        expected = {
            "ToolSpec", "ToolRegistry", "TOOL_REGISTRY", "TOOL_SPECS", "run_tool",
            "RESOLVE_PLAYER_SPEC", "GET_PLAYER_SUMMARY_SPEC", "GET_CURRENT_GAMEWEEK_SPEC",
        }
        for name in expected:
            assert hasattr(pkg, name), f"Missing export: {name}"

    def test_tool_registry_is_tool_registry_instance(self):
        from fpl_tool_runner import TOOL_REGISTRY, ToolRegistry
        assert isinstance(TOOL_REGISTRY, ToolRegistry)

    def test_tool_specs_is_list_of_three(self):
        from fpl_tool_runner import TOOL_SPECS, ToolSpec
        assert isinstance(TOOL_SPECS, list)
        assert len(TOOL_SPECS) == 3
        assert all(isinstance(s, ToolSpec) for s in TOOL_SPECS)


