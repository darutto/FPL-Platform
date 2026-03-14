"""
tests/test_registry.py
========================
Tests for fpl_player_registry — bootstrap-based core.

Test suites
-----------
A.  Import smoke                          (3 tests)
B.  build_registry determinism            (5 tests)
C.  lookup_by_id                          (4 tests)
D.  lookup_by_web_name — exact            (5 tests)
E.  lookup_by_exact_name                  (6 tests)
F.  lookup_by_alias / nickname            (8 tests)
G.  Duplicate web_name handling           (4 tests)
H.  Missing-player / None returns         (4 tests)
I.  Stable IDs and team linkage           (5 tests)
J.  Public surface guard                  (3 tests)
"""
from __future__ import annotations

import copy
import pytest

from tests.conftest import PLAYERS, TEAMS


# ===========================================================================
# A. Import smoke
# ===========================================================================

class TestImportSmoke:
    def test_package_imports_cleanly(self):
        import fpl_player_registry
        assert fpl_player_registry is not None

    def test_all_exports_present(self):
        import fpl_player_registry as pkg
        for name in ("PlayerRecord", "PlayerRegistry", "build_registry", "KNOWN_NICKNAMES"):
            assert hasattr(pkg, name), f"Missing export: {name}"

    def test_known_nicknames_is_non_empty_dict(self):
        from fpl_player_registry import KNOWN_NICKNAMES
        assert isinstance(KNOWN_NICKNAMES, dict)
        assert len(KNOWN_NICKNAMES) >= 10


# ===========================================================================
# B. build_registry determinism
# ===========================================================================

class TestBuildRegistryDeterminism:
    def test_returns_player_registry_instance(self, players, teams):
        from fpl_player_registry import build_registry, PlayerRegistry
        reg = build_registry(players, teams)
        assert isinstance(reg, PlayerRegistry)

    def test_len_matches_player_count(self, registry, players):
        assert len(registry) == len(players)

    def test_build_twice_same_len(self, players, teams):
        from fpl_player_registry import build_registry
        r1 = build_registry(players, teams)
        r2 = build_registry(players, teams)
        assert len(r1) == len(r2)

    def test_all_players_returns_list(self, registry, players):
        result = registry.all_players()
        assert isinstance(result, list)
        assert len(result) == len(players)

    def test_empty_bootstrap_builds_empty_registry(self):
        from fpl_player_registry import build_registry
        reg = build_registry([], [])
        assert len(reg) == 0
        assert reg.all_players() == []


# ===========================================================================
# C. lookup_by_id
# ===========================================================================

class TestLookupById:
    def test_hit_returns_correct_record(self, registry):
        rec = registry.lookup_by_id(1)
        assert rec is not None
        assert rec.id == 1
        assert rec.web_name == "Haaland"

    def test_hit_returns_player_record(self, registry):
        from fpl_player_registry import PlayerRecord
        rec = registry.lookup_by_id(2)
        assert isinstance(rec, PlayerRecord)

    def test_miss_returns_none(self, registry):
        assert registry.lookup_by_id(99) is None

    def test_all_fixture_ids_resolvable(self, registry, players):
        for p in players:
            rec = registry.lookup_by_id(p["id"])
            assert rec is not None, f"id {p['id']} not found"
            assert rec.id == p["id"]


# ===========================================================================
# D. lookup_by_web_name — exact
# ===========================================================================

class TestLookupByWebName:
    def test_exact_hit(self, registry):
        rec = registry.lookup_by_web_name("Haaland")
        assert rec is not None
        assert rec.id == 1

    def test_case_insensitive(self, registry):
        assert registry.lookup_by_web_name("haaland") is not None
        assert registry.lookup_by_web_name("HAALAND") is not None
        assert registry.lookup_by_web_name("HaAlAnD") is not None

    def test_miss_returns_none(self, registry):
        assert registry.lookup_by_web_name("NotAPlayer") is None

    def test_duplicate_web_name_returns_none(self, registry):
        # Both "Johnson" entries share a web_name → ambiguous → None
        assert registry.lookup_by_web_name("Johnson") is None

    def test_unique_web_name_not_ambiguous(self, registry):
        # "Salah" is unique → should resolve cleanly
        rec = registry.lookup_by_web_name("Salah")
        assert rec is not None
        assert rec.id == 2


# ===========================================================================
# E. lookup_by_exact_name
# ===========================================================================

class TestLookupByExactName:
    def test_web_name_resolution(self, registry):
        rec = registry.lookup_by_exact_name("Saka")
        assert rec is not None
        assert rec.id == 3

    def test_second_name_resolution(self, registry):
        # "De Bruyne" is the second_name of player 4
        rec = registry.lookup_by_exact_name("De Bruyne")
        assert rec is not None
        assert rec.id == 4

    def test_first_name_resolution(self, registry):
        # "Erling" is Haaland's first_name; no other player shares it
        rec = registry.lookup_by_exact_name("Erling")
        assert rec is not None
        assert rec.id == 1

    def test_case_insensitive_second_name(self, registry):
        rec = registry.lookup_by_exact_name("de bruyne")
        assert rec is not None
        assert rec.id == 4

    def test_miss_returns_none(self, registry):
        assert registry.lookup_by_exact_name("Zidane") is None

    def test_web_name_takes_priority_over_first_name(self):
        # Build a registry where a web_name coincides with another player's first_name
        from fpl_player_registry import build_registry
        players = [
            {"id": 10, "first_name": "Alpha", "second_name": "Smith",
             "web_name": "Beta", "team_id": 1, "element_type": 3, "status": "a"},
            {"id": 11, "first_name": "Beta",  "second_name": "Jones",
             "web_name": "Jones", "team_id": 1, "element_type": 3, "status": "a"},
        ]
        teams = [{"id": 1, "name": "Test FC", "short_name": "TST"}]
        reg = build_registry(players, teams)
        # "Beta" matches web_name of player 10 first
        rec = reg.lookup_by_exact_name("Beta")
        assert rec is not None
        assert rec.id == 10


# ===========================================================================
# F. lookup_by_alias / nickname
# ===========================================================================

class TestLookupByAlias:
    def test_known_alias_resolves(self, registry):
        # "KDB" is an alias for De Bruyne
        rec = registry.lookup_by_alias("KDB")
        assert rec is not None
        assert rec.id == 4

    def test_el_prefix_alias_resolves(self, registry):
        # "el Vikingo" → Haaland
        rec = registry.lookup_by_alias("el Vikingo")
        assert rec is not None
        assert rec.id == 1

    def test_case_insensitive_alias(self, registry):
        rec = registry.lookup_by_alias("kdb")
        assert rec is not None
        assert rec.id == 4

    def test_alias_mo_resolves_to_salah(self, registry):
        rec = registry.lookup_by_alias("Mo")
        assert rec is not None
        assert rec.id == 2

    def test_alias_taa_resolves(self):
        # Build a registry that includes Alexander-Arnold
        from fpl_player_registry import build_registry
        players = [{"id": 20, "first_name": "Trent", "second_name": "Alexander-Arnold",
                    "web_name": "Alexander-Arnold", "team_id": 14, "element_type": 2, "status": "a"}]
        teams = [{"id": 14, "name": "Liverpool", "short_name": "LIV"}]
        reg = build_registry(players, teams)
        rec = reg.lookup_by_alias("TAA")
        assert rec is not None
        assert rec.id == 20

    def test_alias_trent_resolves(self):
        from fpl_player_registry import build_registry
        players = [{"id": 20, "first_name": "Trent", "second_name": "Alexander-Arnold",
                    "web_name": "Alexander-Arnold", "team_id": 14, "element_type": 2, "status": "a"}]
        teams = [{"id": 14, "name": "Liverpool", "short_name": "LIV"}]
        reg = build_registry(players, teams)
        assert reg.lookup_by_alias("Trent") is not None

    def test_unknown_alias_returns_none(self, registry):
        assert registry.lookup_by_alias("Zizou") is None

    def test_alias_for_absent_player_returns_none(self):
        # Registry has no Salah → alias "Mo" should return None
        from fpl_player_registry import build_registry
        players = [{"id": 1, "first_name": "Erling", "second_name": "Haaland",
                    "web_name": "Haaland", "team_id": 13, "element_type": 4, "status": "a"}]
        teams = [{"id": 13, "name": "Man City", "short_name": "MCI"}]
        reg = build_registry(players, teams)
        assert reg.lookup_by_alias("Mo") is None


# ===========================================================================
# G. Duplicate web_name handling
# ===========================================================================

class TestDuplicateWebName:
    def test_ambiguous_web_name_recorded(self, registry):
        assert "johnson" in registry.ambiguous_web_names

    def test_ambiguous_lookup_by_web_name_returns_none(self, registry):
        assert registry.lookup_by_web_name("Johnson") is None

    def test_ambiguous_players_resolvable_by_id(self, registry):
        adam = registry.lookup_by_id(6)
        glen = registry.lookup_by_id(7)
        assert adam is not None and adam.web_name == "Johnson"
        assert glen is not None and glen.web_name == "Johnson"
        assert adam.id != glen.id

    def test_unique_players_not_flagged_as_ambiguous(self, registry):
        assert "haaland" not in registry.ambiguous_web_names
        assert "salah"   not in registry.ambiguous_web_names


# ===========================================================================
# H. Missing-player / None returns
# ===========================================================================

class TestMissingPlayer:
    def test_lookup_by_id_absent(self, registry):
        assert registry.lookup_by_id(99) is None

    def test_lookup_by_web_name_absent(self, registry):
        assert registry.lookup_by_web_name("Cantona") is None

    def test_lookup_by_exact_name_absent(self, registry):
        assert registry.lookup_by_exact_name("Platini") is None

    def test_lookup_by_alias_absent(self, registry):
        assert registry.lookup_by_alias("el Fantasma") is None


# ===========================================================================
# I. Stable IDs and team linkage
# ===========================================================================

class TestStableIdsAndTeamLinkage:
    def test_record_id_matches_bootstrap_id(self, registry, players):
        for p in players:
            rec = registry.lookup_by_id(p["id"])
            assert rec.id == p["id"]

    def test_team_id_linked_correctly(self, registry):
        haaland = registry.lookup_by_id(1)
        assert haaland.team_id == 13
        assert haaland.team_name == "Manchester City"
        assert haaland.team_short_name == "MCI"

    def test_get_team_returns_raw_dict(self, registry):
        team = registry.get_team(13)
        assert team is not None
        assert team["name"] == "Manchester City"

    def test_get_team_absent_returns_none(self, registry):
        assert registry.get_team(999) is None

    def test_player_record_is_frozen(self, registry):
        rec = registry.lookup_by_id(1)
        with pytest.raises((AttributeError, TypeError)):
            rec.web_name = "Mutated"  # type: ignore[misc]


# ===========================================================================
# J. Public surface guard
# ===========================================================================

class TestPublicSurface:
    def test_all_exports_in_all(self):
        import fpl_player_registry as pkg
        assert set(pkg.__all__) == {
            "PlayerRecord", "PlayerRegistry", "build_registry", "KNOWN_NICKNAMES"
        }

    def test_season_id_mapper_not_exposed(self):
        import fpl_player_registry as pkg
        assert not hasattr(pkg, "SeasonIdMapper")

    def test_build_registry_is_callable(self):
        from fpl_player_registry import build_registry
        assert callable(build_registry)


