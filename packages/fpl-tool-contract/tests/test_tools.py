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

    def test_prefix_resolution_keeps_public_contract(self, bootstrap):
        from fpl_tool_contract import tool_resolve_player
        result = tool_resolve_player("Haal", bootstrap)
        assert result["status"] == "ok"
        assert result["resolved_via"] == "exact_name"
        assert result["player_id"] == 1

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
# J. rank_captain_candidates — caller and deterministic derived pools
# ===========================================================================

class TestRankCaptainCandidatesPool:
    @staticmethod
    def _large_pool_bootstrap(bootstrap, size=20):
        expanded = copy.deepcopy(bootstrap)
        template = next(
            element
            for element in expanded["elements"]
            if element.get("element_type") in (3, 4)
            and element.get("status") == "a"
        )
        for offset in range(size):
            player = copy.deepcopy(template)
            player_id = 10_000 + offset
            player.update({
                "id": player_id,
                "first_name": "Pool",
                "second_name": f"Player {offset}",
                "web_name": f"Pool{offset}",
                "form": str(offset),
            })
            expanded["elements"].append(player)
        return expanded

    def test_explicit_candidates_preserve_caller_mode(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        result = tool_rank_captain_candidates(
            [{"query": "Haaland"}, {"query": "Salah"}], bootstrap
        )

        assert result["status"] == "ok"
        assert result["pool_source"] == "caller"
        assert {entry["web_name"] for entry in result["ranked_candidates"]} == {
            "Haaland", "Salah",
        }

    @pytest.mark.parametrize("candidates", [None, []])
    def test_missing_or_empty_candidates_derive_same_pool(self, bootstrap, candidates):
        from fpl_tool_contract import tool_rank_captain_candidates

        result = tool_rank_captain_candidates(candidates, bootstrap)

        assert result["status"] == "ok"
        assert result["pool_source"] == "derived"
        # Available MID/FWD only: injured De Bruyne, defenders and GKP excluded.
        assert {entry["web_name"] for entry in result["ranked_candidates"]} == {
            "Haaland", "Salah", "Saka", "Johnson",
        }

    def test_derived_pool_is_capped_at_12(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates
        from fpl_tool_contract.scoring_core import captain_pool_elements

        expanded = self._large_pool_bootstrap(bootstrap)
        result = tool_rank_captain_candidates(None, expanded)

        assert result["pool_source"] == "derived"
        assert len(result["ranked_candidates"]) <= 12
        assert result["total"] == 12
        # pool_size is the pool before the output cap, so it tracks whoever is
        # eligible rather than a number written down once.
        assert result["pool_size"] == len(captain_pool_elements(expanded))
        assert result["pool_size"] > 12

    def test_explicit_pool_is_not_capped(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        expanded = self._large_pool_bootstrap(bootstrap)
        candidates = [{"query": 10_000 + offset} for offset in range(16)]
        result = tool_rank_captain_candidates(candidates, expanded)

        assert result["pool_source"] == "caller"
        assert len(result["ranked_candidates"]) == 16
        assert result["total"] == 16
        assert result["pool_size"] == 16

    def test_owned_player_ranked_40th_is_retained_after_global_top_12(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        expanded = self._large_pool_bootstrap(bootstrap, size=50)
        eligible_ids = [
            element["id"]
            for element in expanded["elements"]
            if element.get("element_type") in (3, 4)
            and element.get("status") not in ("i", "s", "u")
        ]
        full_ranking = tool_rank_captain_candidates(
            [{"query": player_id} for player_id in eligible_ids], expanded
        )
        owned_player = next(
            entry for entry in full_ranking["ranked_candidates"]
            if entry["rank"] == 40
        )

        result = tool_rank_captain_candidates(
            None, expanded, squad_player_ids=[owned_player["player_id"]]
        )

        retained = next(
            entry for entry in result["ranked_candidates"]
            if entry["player_id"] == owned_player["player_id"]
        )
        assert retained["rank"] == 40
        assert retained["owned"] is True
        assert result["squad_source"] == "connected"
        assert len(result["ranked_candidates"]) == 13

    def test_unavailable_owned_player_is_reported_as_excluded(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        unavailable = next(
            element for element in bootstrap["elements"]
            if element.get("status") in ("i", "s", "u")
        )
        result = tool_rank_captain_candidates(
            None, bootstrap, squad_player_ids=[unavailable["id"]]
        )

        assert result["squad_excluded"] == [{
            "player_id": unavailable["id"],
            "web_name": unavailable["web_name"],
            "status": unavailable["status"],
            "reason": "unavailable",
        }]
        assert all(
            entry.get("player_id") != unavailable["id"]
            for entry in result["ranked_candidates"]
        )

    def test_no_squad_ids_declares_not_connected(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        result = tool_rank_captain_candidates(None, bootstrap)

        assert result["squad_source"] == "not_connected"
        assert result["squad_excluded"] == []
        assert all(entry["owned"] is False for entry in result["ranked_candidates"])

    def test_connected_squad_accounts_for_all_15_players_with_reasons(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        expanded = copy.deepcopy(bootstrap)
        template = next(
            element for element in expanded["elements"]
            if element.get("web_name") == "Salah"
        )
        squad_ids = []
        position_shape = [1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4]
        for offset, element_type in enumerate(position_shape):
            player = copy.deepcopy(template)
            player_id = 20_000 + offset
            player.update({
                "id": player_id,
                "first_name": "Squad",
                "second_name": f"Player {offset}",
                "web_name": f"Squad{offset}",
                "element_type": element_type,
                "status": "a",
            })
            expanded["elements"].append(player)
            squad_ids.append(player_id)

        result = tool_rank_captain_candidates(
            None, expanded, squad_player_ids=squad_ids
        )
        ranked_owned = [
            entry for entry in result["ranked_candidates"]
            if entry.get("status") == "ok" and entry.get("owned")
        ]

        # Position is no longer a reason to exclude anyone, so all fifteen are
        # evaluated. The accounting invariant is what matters and it still
        # holds: every owned player is either ranked or excluded, never both
        # and never neither.
        assert len(ranked_owned) == 15
        assert result["squad_excluded"] == []
        assert len(ranked_owned) + len(result["squad_excluded"]) == 15
        assert {entry["position"] for entry in ranked_owned} == {"GKP", "DEF", "MID", "FWD"}

    def test_owned_player_resolution_failure_is_recorded(self, bootstrap, monkeypatch):
        import fpl_tool_contract.tools as tools_module

        original_resolve = tools_module._resolve_with_status

        def _fail_owned(query, candidate_bootstrap):
            if query == 1:
                return "not_found", {}, []
            return original_resolve(query, candidate_bootstrap)

        monkeypatch.setattr(tools_module, "_resolve_with_status", _fail_owned)
        result = tools_module.tool_rank_captain_candidates(
            None, bootstrap, squad_player_ids=[1]
        )

        assert result["squad_excluded"] == [{
            "player_id": 1,
            "web_name": "Haaland",
            "status": "a",
            "reason": "unresolved",
        }]
        failed = next(
            entry for entry in result["ranked_candidates"]
            if entry.get("player_id") == 1
        )
        assert failed["status"] == "not_found"
        assert failed["owned"] is True

    def test_same_derived_request_20_times_keeps_list_and_order(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        expanded = self._large_pool_bootstrap(bootstrap)
        observed = []
        for _ in range(20):
            result = tool_rank_captain_candidates(
                None, expanded, squad_player_ids=[10_000]
            )
            observed.append([
                (
                    entry["player_id"], entry["web_name"],
                    entry["rank"], entry["owned"],
                )
                for entry in result["ranked_candidates"]
            ])

        assert len(observed[0]) == 13
        assert all(ranking == observed[0] for ranking in observed[1:])


# ===========================================================================
# K. captaincy temporal window
# ===========================================================================

class TestCaptaincyTemporalWindow:
    @staticmethod
    def _with_fixtures(bootstrap):
        bootstrap = copy.deepcopy(bootstrap)
        bootstrap["team_fixtures"] = {
            1: [
                {"gameweek": 28, "difficulty": 3},
                {"gameweek": 29, "difficulty": 3},
            ],
            8: [
                {"gameweek": 28, "difficulty": 3},
                {"gameweek": 29, "difficulty": 3},
            ],
            13: [
                {"gameweek": 28, "difficulty": 5},
                {"gameweek": 29, "difficulty": 1},
            ],
            14: [
                {"gameweek": 28, "difficulty": 2},
                {"gameweek": 29, "difficulty": 4},
            ],
        }
        return bootstrap

    def test_omitted_gameweek_explicitly_records_current(self, bootstrap):
        from fpl_tool_contract import tool_get_captain_score

        result = tool_get_captain_score("Haaland", bootstrap)

        assert result["time_context"]["source"] == "current"
        assert result["time_context"]["evaluated_gameweek"] == 28
        assert "current gameweek GW28" in result["time_context"]["notice"]

    def test_finished_current_event_yields_upcoming_gameweek(self, bootstrap):
        """Captain scoring must not repeat the stale-current resolver bug."""
        from fpl_tool_contract.scoring_core import captain_time_context

        bs = copy.deepcopy(bootstrap)
        bs["events"][1]["finished"] = True

        result = captain_time_context(bs)

        assert result["current_gameweek"] == 29
        assert result["evaluated_gameweek"] == 29

    def test_finished_events_leave_no_actionable_gameweek(self, bootstrap):
        from fpl_tool_contract.scoring_core import captain_time_context

        bs = copy.deepcopy(bootstrap)
        for event in bs["events"]:
            event["finished"] = True

        result = captain_time_context(bs)

        assert result["current_gameweek"] is None
        assert result["evaluated_gameweek"] is None

    def test_requested_gameweek_changes_fixture_score(self, bootstrap):
        from fpl_tool_contract import tool_get_captain_score

        bs = self._with_fixtures(bootstrap)
        current = tool_get_captain_score("Haaland", bs)
        future = tool_get_captain_score("Haaland", bs, gameweek=29)

        assert current["score_inputs"]["fixture_difficulty"] == 5
        assert future["score_inputs"]["fixture_difficulty"] == 1
        assert future["captain_score"] > current["captain_score"]
        assert future["time_context"]["source"] == "caller"

    def test_horizon_averages_fixture_difficulty(self, bootstrap):
        from fpl_tool_contract import tool_get_captain_score

        bs = self._with_fixtures(bootstrap)
        result = tool_get_captain_score("Haaland", bs, gameweek=28, horizon=2)

        assert result["score_inputs"]["fixture_difficulty"] == 3
        assert result["time_context"]["gameweek_to"] == 29

    def test_rank_temporal_window_is_forwarded(self, bootstrap):
        from fpl_tool_contract import tool_rank_captain_candidates

        bs = self._with_fixtures(bootstrap)
        result = tool_rank_captain_candidates(None, bs, gameweek=29, horizon=1)

        assert result["time_context"]["evaluated_gameweek"] == 29
        assert result["time_context"]["horizon"] == 1

    def test_invalid_window_is_structured_error(self, bootstrap):
        from fpl_tool_contract import tool_get_captain_score

        result = tool_get_captain_score("Haaland", bootstrap, gameweek=39)

        assert result == {
            "status": "error",
            "code": "invalid_argument",
            "message": "gameweek must be between 1 and 38",
        }

    def test_future_gameweek_without_fixtures_refuses_current_fdr_fallback(self, bootstrap):
        from fpl_tool_contract import tool_get_captain_score

        result = tool_get_captain_score("Haaland", bootstrap, gameweek=30)

        assert result["status"] == "error"
        assert result["code"] == "missing_context"
        assert result["time_context"]["notice"] == (
            "Could not evaluate the requested gameweek GW30."
        )


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
            "tool_get_captain_score",
            "tool_rank_captain_candidates",
        }

    def test_internal_helper_not_exported(self):
        import fpl_tool_contract as pkg
        assert not hasattr(pkg, "_resolve_with_status")

    def test_expected_tool_count_in_all(self):
        import fpl_tool_contract as pkg
        assert len(pkg.__all__) == 5




class TestOpenPoolAndPresentation:
    """Position no longer gates the pool, and the shown lists are a view."""

    @staticmethod
    def _pool_with_owner(bootstrap):
        expanded = copy.deepcopy(bootstrap)
        template = next(
            element
            for element in expanded["elements"]
            if element.get("status") == "a"
        )
        squad_ids = []
        # A keeper and a defender the user owns, plus enough scored players to
        # fill both lists past their presentation limits.
        for offset, (element_type, form, owned, selected) in enumerate([
            (1, "6.0", True, "31.0"),
            (2, "7.0", True, "24.0"),
            (3, "8.0", True, "2.1"),
            (4, "9.0", True, "48.0"),
            (3, "9.5", False, "1.4"),
            (4, "8.5", False, "55.0"),
            (2, "8.2", False, "12.0"),
        ]):
            player = copy.deepcopy(template)
            player_id = 30_000 + offset
            player.update({
                "id": player_id,
                "first_name": "Open",
                "second_name": f"Player {offset}",
                "web_name": f"Open{offset}",
                "element_type": element_type,
                "status": "a",
                "form": form,
                "selected_by_percent": selected,
            })
            expanded["elements"].append(player)
            if owned:
                squad_ids.append(player_id)
        return expanded, squad_ids

    def test_keepers_and_defenders_reach_the_ranking_with_their_position(
        self, bootstrap
    ):
        from fpl_tool_contract import tool_rank_captain_candidates

        expanded, squad_ids = self._pool_with_owner(bootstrap)
        result = tool_rank_captain_candidates(
            None, expanded, squad_player_ids=squad_ids
        )

        positions = {
            entry["position"]
            for entry in result["ranked_candidates"]
            if entry.get("status") == "ok"
        }
        assert {"GKP", "DEF"} & positions
        assert all(
            entry["reason"] != "not_eligible_position"
            for entry in result["squad_excluded"]
        )

    def test_presentation_names_short_lists_without_shortening_the_payload(
        self, bootstrap
    ):
        from fpl_tool_contract import tool_rank_captain_candidates
        from fpl_tool_contract.tools import (
            GLOBAL_LIST_LIMIT,
            OWNED_LIST_LIMIT,
        )

        expanded, squad_ids = self._pool_with_owner(bootstrap)
        result = tool_rank_captain_candidates(
            None, expanded, squad_player_ids=squad_ids
        )
        presentation = result["presentation"]
        ok_ids = [
            entry["player_id"]
            for entry in result["ranked_candidates"]
            if entry.get("status") == "ok"
        ]

        assert len(presentation["owned_top"]) <= OWNED_LIST_LIMIT
        assert len(presentation["global_top"]) <= GLOBAL_LIST_LIMIT
        # The lists name entries; they never remove any.
        assert set(presentation["owned_top"]) <= set(ok_ids)
        assert set(presentation["global_top"]) <= set(ok_ids)
        assert len(ok_ids) > len(presentation["global_top"])

    def test_hipster_is_the_least_owned_player_that_clears_the_floor(
        self, bootstrap
    ):
        from fpl_tool_contract import tool_rank_captain_candidates
        from fpl_tool_contract.tools import (
            HIPSTER_MAX_MINUTES_RISK,
            HIPSTER_MIN_SCORE,
        )

        expanded, squad_ids = self._pool_with_owner(bootstrap)
        result = tool_rank_captain_candidates(
            None, expanded, squad_player_ids=squad_ids
        )
        by_id = {
            entry["player_id"]: entry
            for entry in result["ranked_candidates"]
            if entry.get("status") == "ok"
        }

        for key, shown, owned_only in (
            ("global_hipster", "global_top", False),
            ("owned_hipster", "owned_top", True),
        ):
            hipster = result["presentation"][key]
            if hipster["player_id"] is None:
                assert hipster["reason"] == "no_candidate_clears_floor"
                continue
            pick = by_id[hipster["player_id"]]
            # Not already on show, and good enough to be worth suggesting.
            assert hipster["player_id"] not in result["presentation"][shown]
            assert pick["captain_score"] >= HIPSTER_MIN_SCORE
            assert pick["score_inputs"]["minutes_risk"] <= HIPSTER_MAX_MINUTES_RISK
            # Least owned among everyone else who also cleared the floor.
            rivals = [
                entry for entry in by_id.values()
                if entry["player_id"] not in result["presentation"][shown]
                and (entry["owned"] if owned_only else True)
                and entry["selected_by_percent"] is not None
                and entry["captain_score"] >= HIPSTER_MIN_SCORE
                and entry["score_inputs"]["minutes_risk"] <= HIPSTER_MAX_MINUTES_RISK
            ]
            assert pick["selected_by_percent"] == min(
                entry["selected_by_percent"] for entry in rivals
            )

    def test_no_hipster_is_said_rather_than_filled_with_a_weak_player(
        self, bootstrap
    ):
        from fpl_tool_contract.tools import _pick_hipster

        below_floor = [{
            "status": "ok",
            "player_id": 1,
            "captain_score": 10.0,
            "selected_by_percent": 0.1,
            "score_inputs": {"minutes_risk": 0.0},
        }]

        assert _pick_hipster(below_floor, set()) == {
            "player_id": None,
            "reason": "no_candidate_clears_floor",
        }

    def test_unparseable_ownership_never_wins_the_hipster_slot(self):
        from fpl_tool_contract.tools import _pick_hipster

        entries = [
            {
                "status": "ok", "player_id": 1, "captain_score": 60.0,
                "selected_by_percent": None,
                "score_inputs": {"minutes_risk": 0.0},
            },
            {
                "status": "ok", "player_id": 2, "captain_score": 60.0,
                "selected_by_percent": 9.0,
                "score_inputs": {"minutes_risk": 0.0},
            },
        ]

        # A missing ownership figure is not "nobody owns him".
        assert _pick_hipster(entries, set())["player_id"] == 2
