"""
tests/test_tools.py
====================
Tests for fpl_tool_contract — LLM-friendly tool wrappers.

Test suites
-----------
A.  Import smoke                                            (3 tests)
B.  tool_resolve_player — status "ok"                      (7 tests)
C.  tool_resolve_player — status "ambiguous"               (4 tests)
D.  tool_resolve_player — status "not_found"               (3 tests)
E.  tool_get_player_summary — status "ok" + enrichment     (7 tests)
F.  tool_get_player_summary — ambiguous / not_found        (3 tests)
G.  tool_get_current_gameweek — ok / not_found / edge      (5 tests)
H.  Structured output contract (status always present)     (4 tests)
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
        import fpl_tool_contract
        assert fpl_tool_contract is not None

    def test_three_tools_present(self):
        import fpl_tool_contract as pkg
        for name in ("tool_resolve_player", "tool_get_player_summary",
                     "tool_get_current_gameweek"):
            assert hasattr(pkg, name)

    def test_all_callable(self):
        import fpl_tool_contract as pkg
        for name in pkg.__all__:
            assert callable(getattr(pkg, name))


# ===========================================================================
# B. tool_resolve_player — status "ok"
# ===========================================================================

class TestToolResolvePlayerOk:
    def test_returns_dict(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Haaland", bootstrap)
        assert isinstance(result, dict)

    def test_status_ok(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Haaland", bootstrap)
        assert result["status"] == "ok"

    def test_required_ok_keys(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        required = {"status", "player_id", "web_name", "name",
                    "team", "team_short", "position", "status_label",
                    "resolved_via", "query"}
        result = tool_resolve_player("Haaland", bootstrap)
        assert required.issubset(result.keys())

    def test_resolved_via_web_name(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Haaland", bootstrap)
        assert result["resolved_via"] == "web_name"
        assert result["player_id"] == 1

    def test_resolved_via_id(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player(2, bootstrap)
        assert result["resolved_via"] == "id"
        assert result["player_id"] == 2

    def test_resolved_via_alias(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("KDB", bootstrap)
        assert result["status"] == "ok"
        assert result["resolved_via"] == "alias"
        assert result["player_id"] == 4

    def test_query_field_preserved(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("el Vikingo", bootstrap)
        assert result["query"] == "el Vikingo"
        assert result["player_id"] == 1


# ===========================================================================
# C. tool_resolve_player — status "ambiguous"
# ===========================================================================

class TestToolResolvePlayerAmbiguous:
    def test_ambiguous_status(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Johnson", bootstrap)
        assert result["status"] == "ambiguous"

    def test_ambiguous_required_keys(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Johnson", bootstrap)
        assert {"status", "query", "message"}.issubset(result.keys())

    def test_ambiguous_message_not_empty(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Johnson", bootstrap)
        assert len(result["message"]) > 10

    def test_ambiguous_query_preserved(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Johnson", bootstrap)
        assert result["query"] == "Johnson"


# ===========================================================================
# D. tool_resolve_player — status "not_found"
# ===========================================================================

class TestToolResolvePlayerNotFound:
    def test_not_found_status(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Zidane", bootstrap)
        assert result["status"] == "not_found"

    def test_not_found_required_keys(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Zidane", bootstrap)
        assert {"status", "query", "message"}.issubset(result.keys())

    def test_not_found_id_absent_in_bootstrap(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player(99, bootstrap)
        assert result["status"] == "not_found"


# ===========================================================================
# E. tool_get_player_summary — status "ok" + enrichment
# ===========================================================================

class TestToolGetPlayerSummaryOk:
    def test_status_ok(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        result = tool_get_player_summary(1, bootstrap)
        assert result["status"] == "ok"

    def test_required_ok_keys(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        required = {"status", "player_id", "web_name", "name",
                    "team", "team_short", "position", "cost_m",
                    "status_label", "selected_by_percent",
                    "resolved_via", "query"}
        result = tool_get_player_summary("Haaland", bootstrap)
        assert required.issubset(result.keys())

    def test_cost_m_correct(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        result = tool_get_player_summary(1, bootstrap)
        assert result["cost_m"] == 14.5

    def test_status_label_available(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        result = tool_get_player_summary("Haaland", bootstrap)
        assert result["status_label"] == "Available"

    def test_status_label_doubtful(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        result = tool_get_player_summary("Saka", bootstrap)
        assert result["status_label"] == "Doubtful"

    def test_position_fwd(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        result = tool_get_player_summary(1, bootstrap)
        assert result["position"] == "FWD"

    def test_team_enriched(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        result = tool_get_player_summary(1, bootstrap)
        assert result["team"] == "Manchester City"
        assert result["team_short"] == "MCI"


# ===========================================================================
# F. tool_get_player_summary — ambiguous / not_found
# ===========================================================================

class TestToolGetPlayerSummaryNonOk:
    def test_ambiguous_returns_ambiguous_status(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        assert tool_get_player_summary("Johnson", bootstrap)["status"] == "ambiguous"

    def test_not_found_returns_not_found_status(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        assert tool_get_player_summary("Cantona", bootstrap)["status"] == "not_found"

    def test_summary_ambiguous_has_message(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        result = tool_get_player_summary("Johnson", bootstrap)
        assert "message" in result and len(result["message"]) > 10


# ===========================================================================
# G. tool_get_current_gameweek — ok / not_found / edge
# ===========================================================================

class TestToolGetCurrentGameweek:
    def test_status_ok(self, bootstrap):
        from fpl_tool_contract import tool_get_current_gameweek
        result = tool_get_current_gameweek(bootstrap)
        assert result["status"] == "ok"
        assert result["gameweek"] == 28

    def test_falls_back_to_is_next(self):
        from fpl_tool_contract import tool_get_current_gameweek
        bs = copy.deepcopy(BOOTSTRAP)
        for ev in bs["events"]:
            ev["is_current"] = False
        result = tool_get_current_gameweek(bs)
        assert result["status"] == "ok"
        assert result["gameweek"] == 29

    def test_not_found_when_no_flags(self):
        from fpl_tool_contract import tool_get_current_gameweek
        bs = {"events": [{"id": 1, "is_current": False, "is_next": False}]}
        result = tool_get_current_gameweek(bs)
        assert result["status"] == "not_found"
        assert "message" in result

    def test_not_found_for_empty_bootstrap(self):
        from fpl_tool_contract import tool_get_current_gameweek
        result = tool_get_current_gameweek({})
        assert result["status"] == "not_found"

    def test_ok_has_no_extra_noise(self, bootstrap):
        from fpl_tool_contract import tool_get_current_gameweek
        result = tool_get_current_gameweek(bootstrap)
        # "ok" result should contain exactly status + gameweek — clean contract
        assert set(result.keys()) == {"status", "gameweek"}


# ===========================================================================
# H. Structured output contract
# ===========================================================================

class TestStructuredOutputContract:
    def test_every_tool_result_has_status_key(self, bootstrap):
        from fpl_tool_contract import (tool_get_current_gameweek,
                                        tool_get_player_summary,
                                        tool_resolve_player)
        for result in [
            tool_resolve_player("Haaland", bootstrap),
            tool_resolve_player("Johnson", bootstrap),
            tool_resolve_player("Zidane", bootstrap),
            tool_get_player_summary(1, bootstrap),
            tool_get_current_gameweek(bootstrap),
        ]:
            assert "status" in result, f"Missing 'status' in {result}"

    def test_status_values_are_from_vocabulary(self, bootstrap):
        from fpl_tool_contract import (tool_get_current_gameweek,
                                        tool_get_player_summary,
                                        tool_resolve_player)
        valid = {"ok", "ambiguous", "not_found"}
        for result in [
            tool_resolve_player("Haaland", bootstrap),
            tool_resolve_player("Johnson", bootstrap),
            tool_resolve_player("Zidane",  bootstrap),
            tool_get_player_summary("KDB", bootstrap),
            tool_get_current_gameweek(bootstrap),
        ]:
            assert result["status"] in valid, f"Unknown status: {result['status']}"

    def test_deterministic_same_inputs(self, bootstrap):
        from fpl_tool_contract import tool_get_player_summary
        r1 = tool_get_player_summary("Haaland", bootstrap)
        r2 = tool_get_player_summary("Haaland", bootstrap)
        assert r1 == r2

    def test_non_ok_results_have_message_not_player_fields(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        for query in ("Johnson", "Zidane"):
            result = tool_resolve_player(query, bootstrap)
            assert result["status"] != "ok"
            assert "message" in result
            # Player fields must not be present on non-ok results
            for field in ("player_id", "position", "cost_m"):
                assert field not in result, \
                    f"Field '{field}' should not appear in non-ok result for '{query}'"


# ===========================================================================
# I. Public surface guard
# ===========================================================================

class TestPublicSurface:
    def test_all_exports_correct(self):
        import fpl_tool_contract as pkg
        assert set(pkg.__all__) == {
            "tool_resolve_player",
            "tool_get_player_summary",
            "tool_get_current_gameweek",
        }

    def test_internal_helper_not_exported(self):
        import fpl_tool_contract as pkg
        assert not hasattr(pkg, "_resolve_with_status")

    def test_only_three_tools_in_all(self):
        import fpl_tool_contract as pkg
        assert len(pkg.__all__) == 3


