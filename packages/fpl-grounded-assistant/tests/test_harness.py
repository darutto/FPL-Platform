"""
tests/test_harness.py
======================
End-to-end tests for fpl_grounded_assistant.

Test suites
-----------
A.  Import smoke                                              (3 tests)
B.  Router — intent detection                                (6 tests)
C.  Router — player extraction                               (4 tests)
D.  Harness — "Who is Salah?"                                (5 tests)
E.  Harness — "Give me a summary for Haaland"                (5 tests)
F.  Harness — "What is the current gameweek?"                (4 tests)
G.  Harness — ambiguous player (Johnson)                     (4 tests)
H.  Harness — not-found player (Cantona)                     (4 tests)
I.  Harness — unrecognised question                          (3 tests)
J.  Result structure contract                                (4 tests)
K.  Renderer — safety (no player data in non-ok responses)   (3 tests)
L.  Public surface guard                                      (2 tests)
"""
from __future__ import annotations

import pytest


# ===========================================================================
# A. Import smoke
# ===========================================================================

class TestImportSmoke:
    def test_package_imports(self):
        import fpl_grounded_assistant
        assert fpl_grounded_assistant is not None

    def test_ask_present(self):
        from fpl_grounded_assistant import ask
        assert callable(ask)

    def test_route_and_render_present(self):
        from fpl_grounded_assistant import route, render
        assert callable(route) and callable(render)


# ===========================================================================
# B. Router — intent detection
# ===========================================================================

class TestRouterIntentDetection:
    def test_who_is_routes_to_resolve(self):
        from fpl_grounded_assistant import route
        r = route("Who is Salah?")
        assert r is not None and r.tool_name == "resolve_player"

    def test_summary_for_routes_to_summary(self):
        from fpl_grounded_assistant import route
        r = route("Give me a summary for Haaland")
        assert r is not None and r.tool_name == "get_player_summary"

    def test_gameweek_question_routes_to_gw(self):
        from fpl_grounded_assistant import route
        r = route("What is the current gameweek?")
        assert r is not None and r.tool_name == "get_current_gameweek"

    def test_tell_me_about_routes_to_summary(self):
        from fpl_grounded_assistant import route
        r = route("Tell me about Saka")
        assert r is not None and r.tool_name == "get_player_summary"

    def test_current_gw_routes_to_gw(self):
        from fpl_grounded_assistant import route
        r = route("What's the current GW?")
        assert r is not None and r.tool_name == "get_current_gameweek"

    def test_unrecognised_returns_none(self):
        from fpl_grounded_assistant import route
        r = route("Hello, how are you?")
        assert r is None


# ===========================================================================
# C. Router — player extraction
# ===========================================================================

class TestRouterPlayerExtraction:
    def test_who_is_extracts_name(self):
        from fpl_grounded_assistant import route
        r = route("Who is Salah?")
        assert r is not None and r.tool_args["query"] == "salah"

    def test_summary_for_extracts_name(self):
        from fpl_grounded_assistant import route
        r = route("Give me a summary for Haaland")
        assert r is not None and r.tool_args["query"] == "haaland"

    def test_tell_me_about_extracts_name(self):
        from fpl_grounded_assistant import route
        r = route("Tell me about De Bruyne")
        assert r is not None and r.tool_args["query"] == "de bruyne"

    def test_gameweek_has_empty_tool_args(self):
        from fpl_grounded_assistant import route
        r = route("What is the current gameweek?")
        assert r is not None and r.tool_args == {}


# ===========================================================================
# D. Harness — "Who is Salah?"
# ===========================================================================

class TestHarnessWhoIsSalah:
    def test_selected_tool(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Salah?", bootstrap)
        assert result["selected_tool"] == "resolve_player"

    def test_tool_input_has_query(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Salah?", bootstrap)
        assert "query" in result["tool_input"]

    def test_raw_output_status_ok(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Salah?", bootstrap)
        assert result["raw_output"]["status"] == "ok"

    def test_raw_output_player_id(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Salah?", bootstrap)
        assert result["raw_output"]["player_id"] == 2

    def test_answer_text_contains_salah(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Salah?", bootstrap)
        assert "Salah" in result["answer_text"] or "salah" in result["answer_text"].lower()


# ===========================================================================
# E. Harness — "Give me a summary for Haaland"
# ===========================================================================

class TestHarnessSummaryForHaaland:
    def test_selected_tool(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Haaland", bootstrap)
        assert result["selected_tool"] == "get_player_summary"

    def test_raw_output_status_ok(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Haaland", bootstrap)
        assert result["raw_output"]["status"] == "ok"

    def test_answer_contains_cost(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Haaland", bootstrap)
        # cost_m = 14.5, should appear in answer
        assert "14.5" in result["answer_text"]

    def test_answer_contains_position(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Haaland", bootstrap)
        assert "FWD" in result["answer_text"]

    def test_answer_text_non_empty(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Haaland", bootstrap)
        assert isinstance(result["answer_text"], str) and len(result["answer_text"]) > 10


# ===========================================================================
# F. Harness — "What is the current gameweek?"
# ===========================================================================

class TestHarnessCurrentGameweek:
    def test_selected_tool(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("What is the current gameweek?", bootstrap)
        assert result["selected_tool"] == "get_current_gameweek"

    def test_tool_input_empty(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("What is the current gameweek?", bootstrap)
        assert result["tool_input"] == {}

    def test_raw_output_gameweek_28(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("What is the current gameweek?", bootstrap)
        assert result["raw_output"]["gameweek"] == 28

    def test_answer_contains_gw_number(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("What is the current gameweek?", bootstrap)
        assert "28" in result["answer_text"]


# ===========================================================================
# G. Harness — ambiguous player (Johnson)
# ===========================================================================

class TestHarnessAmbiguousPlayer:
    def test_raw_output_status_ambiguous(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Johnson?", bootstrap)
        assert result["raw_output"]["status"] == "ambiguous"

    def test_answer_mentions_disambiguate(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Johnson?", bootstrap)
        # Must acknowledge ambiguity and instruct the user how to clarify
        text = result["answer_text"].lower()
        assert "multiple" in text or "disambiguate" in text or "full name" in text

    def test_answer_does_not_leak_cost(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Johnson?", bootstrap)
        # Neither Johnson's cost should appear in the answer
        assert "5.0" not in result["answer_text"] and "4.5" not in result["answer_text"]

    def test_answer_does_not_leak_ownership(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Johnson?", bootstrap)
        # Ownership % values should not appear
        assert "0.5%" not in result["answer_text"] and "0.3%" not in result["answer_text"]


# ===========================================================================
# H. Harness — not-found player (Cantona)
# ===========================================================================

class TestHarnessNotFound:
    def test_raw_output_status_not_found(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Cantona?", bootstrap)
        assert result["raw_output"]["status"] == "not_found"

    def test_answer_mentions_query_term(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Cantona?", bootstrap)
        assert "cantona" in result["answer_text"].lower()

    def test_answer_graceful_no_crash(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Cantona?", bootstrap)
        # answer must be a non-empty string — no exception raised
        assert isinstance(result["answer_text"], str) and len(result["answer_text"]) > 5

    def test_answer_does_not_contain_player_stats(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Cantona?", bootstrap)
        # No FPL data fields should bleed into a not_found response
        assert "£" not in result["answer_text"] and "FWD" not in result["answer_text"]


# ===========================================================================
# I. Harness — unrecognised question
# ===========================================================================

class TestHarnessUnrecognised:
    def test_selected_tool_is_none(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Hello, how are you?", bootstrap)
        assert result["selected_tool"] is None

    def test_raw_output_code_unrecognised(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Hello, how are you?", bootstrap)
        assert result["raw_output"]["code"] == "unrecognised_query"

    def test_answer_text_non_empty_and_helpful(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Hello, how are you?", bootstrap)
        text = result["answer_text"]
        assert isinstance(text, str) and len(text) > 10


# ===========================================================================
# J. Result structure contract
# ===========================================================================

class TestResultStructureContract:
    def test_all_four_keys_present_ok(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Salah?", bootstrap)
        assert {"selected_tool", "tool_input", "raw_output", "answer_text"} == set(result.keys())

    def test_all_four_keys_present_ambiguous(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Who is Johnson?", bootstrap)
        assert {"selected_tool", "tool_input", "raw_output", "answer_text"} == set(result.keys())

    def test_answer_text_always_string(self, bootstrap):
        from fpl_grounded_assistant import ask
        for q in ["Who is Salah?", "Who is Johnson?", "Who is Cantona?",
                  "What is the current gameweek?", "Give me a summary for Haaland"]:
            result = ask(q, bootstrap)
            assert isinstance(result["answer_text"], str), f"answer_text not str for: {q!r}"

    def test_tool_input_always_dict(self, bootstrap):
        from fpl_grounded_assistant import ask
        for q in ["Who is Salah?", "What is the current gameweek?", "Nonsense question xyz"]:
            result = ask(q, bootstrap)
            assert isinstance(result["tool_input"], dict), f"tool_input not dict for: {q!r}"


# ===========================================================================
# K. Renderer — safety (no player data in non-ok responses)
# ===========================================================================

class TestRendererSafety:
    def test_ambiguous_answer_has_no_player_id(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Johnson", bootstrap)
        # player_id values 6 and 7 should not appear as numeric values in answer
        assert "player_id" not in result["answer_text"]
        assert result["raw_output"]["status"] == "ambiguous"

    def test_not_found_has_no_cost_m(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Zidane", bootstrap)
        assert "cost_m" not in result["answer_text"]
        assert result["raw_output"]["status"] == "not_found"

    def test_ok_answer_is_factually_grounded(self, bootstrap):
        from fpl_grounded_assistant import ask
        result = ask("Give me a summary for Haaland", bootstrap)
        text = result["answer_text"]
        # Team short name and position must be grounded from actual bootstrap data
        assert "MCI" in text   # Manchester City short name
        assert "FWD" in text   # element_type 4 → FWD


# ===========================================================================
# L. Public surface guard
# ===========================================================================

class TestPublicSurface:
    def test_all_exports_importable(self):
        import fpl_grounded_assistant as pkg
        for name in ("ask", "route", "render", "RouteResult"):
            assert hasattr(pkg, name), f"Missing export: {name}"

    def test_route_result_is_frozen(self):
        from fpl_grounded_assistant import RouteResult
        r = RouteResult(tool_name="resolve_player", tool_args={"query": "test"})
        import pytest
        with pytest.raises((AttributeError, TypeError)):
            r.tool_name = "tampered"  # type: ignore[misc]


