"""
tests/test_queries.py
======================
Tests for fpl_query_tools — read-only query composition layer.

Test suites
-----------
A.  Import smoke                                    (3 tests)
B.  resolve_player_query — id resolution            (4 tests)
C.  resolve_player_query — web_name resolution      (3 tests)
D.  resolve_player_query — exact name resolution    (4 tests)
E.  resolve_player_query — alias resolution         (4 tests)
F.  resolve_player_query — miss / None              (3 tests)
G.  get_player_summary — hit (fields + enrichment) (8 tests)
H.  get_player_summary — miss / edge cases          (3 tests)
I.  get_current_gameweek_from_bootstrap             (5 tests)
J.  Public surface guard                            (3 tests)
"""
from __future__ import annotations

import copy
import pytest

from tests.conftest import BOOTSTRAP, PLAYERS, TEAMS


# ===========================================================================
# A. Import smoke
# ===========================================================================

class TestImportSmoke:
    def test_package_imports_cleanly(self):
        import fpl_query_tools
        assert fpl_query_tools is not None

    def test_three_functions_present(self):
        import fpl_query_tools as pkg
        for name in ("resolve_player_query", "get_player_summary",
                     "get_current_gameweek_from_bootstrap"):
            assert hasattr(pkg, name), f"Missing: {name}"

    def test_all_are_callable(self):
        import fpl_query_tools as pkg
        for name in pkg.__all__:
            assert callable(getattr(pkg, name))


# ===========================================================================
# B. resolve_player_query — id resolution
# ===========================================================================

class TestResolveById:
    def test_int_id_resolves(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query(1, players, teams)
        assert rec is not None
        assert rec.id == 1
        assert rec.web_name == "Haaland"

    def test_string_int_id_resolves(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query("2", players, teams)
        assert rec is not None
        assert rec.id == 2

    def test_id_returns_player_record(self, players, teams):
        from fpl_query_tools import resolve_player_query
        from fpl_player_registry import PlayerRecord
        rec = resolve_player_query(3, players, teams)
        assert isinstance(rec, PlayerRecord)

    def test_absent_id_returns_none(self, players, teams):
        from fpl_query_tools import resolve_player_query
        assert resolve_player_query(99, players, teams) is None


# ===========================================================================
# C. resolve_player_query — web_name resolution
# ===========================================================================

class TestResolveByWebName:
    def test_exact_web_name(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query("Saka", players, teams)
        assert rec is not None and rec.id == 3

    def test_case_insensitive_web_name(self, players, teams):
        from fpl_query_tools import resolve_player_query
        assert resolve_player_query("saka", players, teams) is not None
        assert resolve_player_query("SAKA", players, teams) is not None

    def test_ambiguous_web_name_returns_none(self, players, teams):
        from fpl_query_tools import resolve_player_query
        # "Johnson" is shared by two players → ambiguous → None
        assert resolve_player_query("Johnson", players, teams) is None


# ===========================================================================
# D. resolve_player_query — exact name resolution
# ===========================================================================

class TestResolveByExactName:
    def test_second_name_resolves(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query("De Bruyne", players, teams)
        assert rec is not None and rec.id == 4

    def test_first_name_resolves(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query("Erling", players, teams)
        assert rec is not None and rec.id == 1

    def test_case_insensitive_exact_name(self, players, teams):
        from fpl_query_tools import resolve_player_query
        assert resolve_player_query("de bruyne", players, teams) is not None

    def test_plain_second_name_no_alias(self, players, teams):
        from fpl_query_tools import resolve_player_query
        # "Clarke" has no alias entry; resolved via exact_name
        rec = resolve_player_query("Clarke", players, teams)
        assert rec is not None and rec.id == 5


# ===========================================================================
# E. resolve_player_query — alias resolution
# ===========================================================================

class TestResolveByAlias:
    def test_kdb_alias(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query("KDB", players, teams)
        assert rec is not None and rec.id == 4

    def test_el_vikingo_alias(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query("el Vikingo", players, teams)
        assert rec is not None and rec.id == 1

    def test_mo_alias(self, players, teams):
        from fpl_query_tools import resolve_player_query
        rec = resolve_player_query("Mo", players, teams)
        assert rec is not None and rec.id == 2

    def test_unknown_alias_returns_none(self, players, teams):
        from fpl_query_tools import resolve_player_query
        assert resolve_player_query("el Fantasma", players, teams) is None


# ===========================================================================
# F. resolve_player_query — miss / None
# ===========================================================================

class TestResolveMiss:
    def test_absent_id_is_none(self, players, teams):
        from fpl_query_tools import resolve_player_query
        assert resolve_player_query(999, players, teams) is None

    def test_gibberish_query_is_none(self, players, teams):
        from fpl_query_tools import resolve_player_query
        assert resolve_player_query("xyzzy_no_such_player", players, teams) is None

    def test_empty_player_list_is_none(self, teams):
        from fpl_query_tools import resolve_player_query
        assert resolve_player_query("Haaland", [], teams) is None


# ===========================================================================
# G. get_player_summary — hit (fields + enrichment)
# ===========================================================================

class TestGetPlayerSummaryHit:
    def test_returns_dict_on_hit(self, players, teams):
        from fpl_query_tools import get_player_summary
        result = get_player_summary("Haaland", players, teams)
        assert isinstance(result, dict)

    def test_expected_keys_present(self, players, teams):
        from fpl_query_tools import get_player_summary
        required = {
            "id", "name", "web_name", "team", "team_short",
            "position", "cost_m", "status", "selected_by_percent",
            "query_resolved_via",
        }
        result = get_player_summary("Haaland", players, teams)
        assert required.issubset(result.keys())

    def test_position_label_correct(self, players, teams):
        from fpl_query_tools import get_player_summary
        # Haaland: element_type=4 → FWD
        result = get_player_summary(1, players, teams)
        assert result["position"] == "FWD"
        # De Bruyne: element_type=3 → MID
        result2 = get_player_summary(4, players, teams)
        assert result2["position"] == "MID"

    def test_cost_converted_to_millions(self, players, teams):
        from fpl_query_tools import get_player_summary
        result = get_player_summary("Haaland", players, teams)
        assert result["cost_m"] == 14.5   # 145 / 10

    def test_status_label_human_readable(self, players, teams):
        from fpl_query_tools import get_player_summary
        assert get_player_summary("Haaland", players, teams)["status"] == "Available"
        assert get_player_summary("Saka",    players, teams)["status"] == "Doubtful"
        assert get_player_summary("De Bruyne", players, teams)["status"] == "Injured"

    def test_team_name_enriched(self, players, teams):
        from fpl_query_tools import get_player_summary
        result = get_player_summary(1, players, teams)
        assert result["team"] == "Manchester City"
        assert result["team_short"] == "MCI"

    def test_query_resolved_via_id(self, players, teams):
        from fpl_query_tools import get_player_summary
        result = get_player_summary(1, players, teams)
        assert result["query_resolved_via"] == "id"

    def test_query_resolved_via_alias(self, players, teams):
        from fpl_query_tools import get_player_summary
        result = get_player_summary("KDB", players, teams)
        assert result["query_resolved_via"] == "alias"
        assert result["id"] == 4


# ===========================================================================
# H. get_player_summary — miss / edge cases
# ===========================================================================

class TestGetPlayerSummaryMiss:
    def test_absent_player_returns_none(self, players, teams):
        from fpl_query_tools import get_player_summary
        assert get_player_summary(99, players, teams) is None

    def test_none_cost_handled(self):
        from fpl_query_tools import get_player_summary
        sparse_players = [{"id": 10, "first_name": "X", "second_name": "Y",
                           "web_name": "XY", "team_id": 1,
                           "element_type": 3, "status": "a"}]
        sparse_teams = [{"id": 1, "name": "Test FC", "short_name": "TST"}]
        result = get_player_summary("XY", sparse_players, sparse_teams)
        assert result is not None
        assert result["cost_m"] is None

    def test_unknown_status_passed_through(self):
        from fpl_query_tools import get_player_summary
        p = [{"id": 10, "first_name": "A", "second_name": "B", "web_name": "AB",
              "team_id": 1, "element_type": 2, "status": "z", "now_cost": 45}]
        t = [{"id": 1, "name": "FC", "short_name": "FC"}]
        result = get_player_summary("AB", p, t)
        assert result["status"] == "z"   # raw passthrough for unknown codes


# ===========================================================================
# I. get_current_gameweek_from_bootstrap
# ===========================================================================

class TestGetCurrentGameweek:
    def test_returns_is_current_gw(self, bootstrap):
        from fpl_query_tools import get_current_gameweek_from_bootstrap
        assert get_current_gameweek_from_bootstrap(bootstrap) == 28

    def test_falls_back_to_is_next(self):
        from fpl_query_tools import get_current_gameweek_from_bootstrap
        bs = copy.deepcopy(BOOTSTRAP)
        for ev in bs["events"]:
            ev["is_current"] = False
        assert get_current_gameweek_from_bootstrap(bs) == 29

    def test_returns_none_when_no_flags(self):
        from fpl_query_tools import get_current_gameweek_from_bootstrap
        bs = {"events": [{"id": 1, "is_current": False, "is_next": False}]}
        assert get_current_gameweek_from_bootstrap(bs) is None

    def test_returns_none_for_empty_dict(self):
        from fpl_query_tools import get_current_gameweek_from_bootstrap
        assert get_current_gameweek_from_bootstrap({}) is None

    def test_returns_none_for_missing_events_key(self):
        from fpl_query_tools import get_current_gameweek_from_bootstrap
        assert get_current_gameweek_from_bootstrap({"teams": [], "elements": []}) is None


# ===========================================================================
# J. Public surface guard
# ===========================================================================

class TestPublicSurface:
    def test_all_exports_correct(self):
        import fpl_query_tools as pkg
        assert set(pkg.__all__) == {
            "resolve_player_query",
            "get_player_summary",
            "get_current_gameweek_from_bootstrap",
        }

    def test_no_internal_modules_leaked(self):
        import fpl_query_tools as pkg
        # Internal helpers should not be in the public surface
        for name in ("_build_and_resolve", "_STATUS_LABELS", "build_registry"):
            assert not hasattr(pkg, name), f"Leaked: {name}"

    def test_deterministic_twice(self, players, teams):
        from fpl_query_tools import get_player_summary
        r1 = get_player_summary("Haaland", players, teams)
        r2 = get_player_summary("Haaland", players, teams)
        assert r1 == r2


