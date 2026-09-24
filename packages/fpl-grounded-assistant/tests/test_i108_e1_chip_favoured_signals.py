"""i108 E1 -- chip advice names the favoured group, by id, without changing a verdict.

Before this slice ``_score_outfield_players`` computed team_id + fdr for
every player and bench boost threw both away after averaging: the advice
said "average FDR 2.3" and nothing about WHO made that average, so the
particular half of the answer ("do you hold them?") had nothing to cross a
squad against. Wildcard had no fixture signal at all.

What this file pins
-------------------
A. bench_boost -- ``signals.favoured_players`` is the subset of the scored
   top-10 whose fixture is at or under ``_BB_FAVORABLE_FDR``;
   ``signals.favoured_teams`` are their distinct teams. Identity is the
   integer ``element`` / ``team`` id from the bootstrap; names ride along.
   Two players sharing a ``web_name`` (the conftest Johnsons) stay distinct.
B. wildcard -- ``signals.favoured_teams`` are the teams whose average FDR
   over the run is favourable; the run is the caller's ``horizon`` or the
   chip's own default, never the captain window's 1-GW fallback. No
   ``team_fixtures`` → empty list, not a crash and not a neutral 3.0.
C. No behaviour change -- recommendation, advice_text and every signal that
   existed before are byte-identical with the new keys removed. The
   run_phase7b / run_phase8c runners are the other half of that pin.
D. Declared -- ``CHIP_ADVICE_SPEC.output_schema`` declares the new arrays
   under ``signals`` with integer identity fields (i95 rule), and the real
   output emits no signal array the schema does not declare.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest

from fpl_grounded_assistant.chip_advisor import (
    CHIP_ADVICE_SPEC,
    _BB_FAVORABLE_FDR,
    _WC_FAVOURED_RUN_GWS,
    _score_outfield_players,
    get_chip_advice,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fx(gw: int, difficulty: int, opp: int = 1) -> dict[str, Any]:
    return {"gameweek": gw, "opponent_team": opp, "is_home": True, "difficulty": difficulty}


@pytest.fixture
def bb_bootstrap(bootstrap) -> dict[str, Any]:
    """Conftest squad with this-GW FDR: MCI/LIV easy, CHE/MUN easy too, ARS hard.

    The two Johnsons (elements 6 and 7, teams 8 and 11) both qualify, so a
    name-keyed cross would collapse them into one.
    """
    bs = copy.deepcopy(bootstrap)
    bs["fixture_difficulty_map"] = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}
    return bs


@pytest.fixture
def wc_bootstrap(bootstrap) -> dict[str, Any]:
    """Five-GW runs from the current GW (28): LIV easy, ARS easy, MCI/CHE not."""
    bs = copy.deepcopy(bootstrap)
    bs["team_fixtures"] = {
        14: [_fx(gw, 2) for gw in range(28, 33)],                 # avg 2.0
        1:  [_fx(gw, d) for gw, d in zip(range(28, 33), (2, 3, 2, 3, 2))],  # avg 2.4
        13: [_fx(gw, d) for gw, d in zip(range(28, 33), (2, 4, 3, 4, 3))],  # avg 3.2
        8:  [_fx(gw, 3) for gw in range(28, 33)],                 # avg 3.0
        # MUN: no fixtures listed at all
    }
    bs["chips"] = [{"name": "wildcard", "start_event": 20, "stop_event": 38}]
    return bs


# ---------------------------------------------------------------------------
# A. bench_boost
# ---------------------------------------------------------------------------

class TestBenchBoostFavoured:
    def test_scored_players_carry_the_element_id(self, bb_bootstrap):
        scored = _score_outfield_players(bb_bootstrap)
        assert scored, "pool empty -- fixture broken"
        ids = {p["element"] for p in scored}
        assert all(isinstance(i, int) for i in ids)
        assert ids <= {e["id"] for e in bb_bootstrap["elements"]}

    def test_favoured_players_are_the_easy_fixture_subset_of_the_top10_by_id(self, bb_bootstrap):
        out = get_chip_advice("bench_boost", bb_bootstrap)
        assert out["status"] == "ok"
        players = out["signals"]["favoured_players"]
        # De Bruyne (4) is injured → out of the pool; Saka (3, ARS, FDR 4) is
        # in the pool but not favoured. Everyone else has FDR 2.
        assert {p["element"] for p in players} == {1, 2, 6, 7}
        assert all(p["fdr"] <= _BB_FAVORABLE_FDR for p in players)
        # Both Johnsons present as distinct ids -- the name would merge them.
        johnsons = [p for p in players if p["web_name"] == "Johnson"]
        assert sorted(j["element"] for j in johnsons) == [6, 7]
        assert sorted(j["team"] for j in johnsons) == [8, 11]

    def test_favoured_players_rows_carry_ids_and_render_fields(self, bb_bootstrap):
        out = get_chip_advice("bench_boost", bb_bootstrap)
        for p in out["signals"]["favoured_players"]:
            assert isinstance(p["element"], int)
            assert isinstance(p["team"], int)
            assert p["team_short"] in {"ARS", "MCI", "LIV", "CHE", "MUN"}
            assert p["position"] in {"GKP", "DEF", "MID", "FWD"}
            assert isinstance(p["web_name"], str)

    def test_favoured_teams_are_the_distinct_teams_of_the_favoured_players(self, bb_bootstrap):
        out = get_chip_advice("bench_boost", bb_bootstrap)
        teams = out["signals"]["favoured_teams"]
        assert [t["team"] for t in teams] == [8, 11, 13, 14]   # fdr tie → by id
        assert {t["team_short"] for t in teams} == {"CHE", "MUN", "MCI", "LIV"}
        assert all(t["fdr"] == 2 for t in teams)
        assert all(t["top_player_count"] == 1 for t in teams)
        # ARS (FDR 4) is not favoured even though Saka is in the top 10.
        assert 1 not in {t["team"] for t in teams}

    def test_a_team_with_two_top_players_counts_both(self, bb_bootstrap):
        bs = copy.deepcopy(bb_bootstrap)
        for el in bs["elements"]:
            if el["id"] == 2:          # move Salah to MCI
                el["team"] = 13
        out = get_chip_advice("bench_boost", bs)
        mci = next(t for t in out["signals"]["favoured_teams"] if t["team"] == 13)
        assert mci["top_player_count"] == 2
        assert 14 not in {t["team"] for t in out["signals"]["favoured_teams"]}

    def test_nobody_qualifies_gives_empty_lists_not_an_error(self, bb_bootstrap):
        bs = copy.deepcopy(bb_bootstrap)
        bs["fixture_difficulty_map"] = {13: 4, 14: 5, 1: 4, 8: 4, 11: 5}
        out = get_chip_advice("bench_boost", bs)
        assert out["status"] == "ok"
        assert out["recommendation"] == "conditions_unfavorable"
        assert out["signals"]["favoured_teams"] == []
        assert out["signals"]["favoured_players"] == []

    def test_identity_is_the_id_not_the_name(self, bb_bootstrap):
        # Mutation guard for E2's cross: renaming a favoured player must not
        # change who is favoured. Same ids, different web_name.
        bs = copy.deepcopy(bb_bootstrap)
        for el in bs["elements"]:
            if el["id"] == 1:
                el["web_name"] = "Somebody Else"
        before = {p["element"] for p in get_chip_advice("bench_boost", bb_bootstrap)["signals"]["favoured_players"]}
        after = {p["element"] for p in get_chip_advice("bench_boost", bs)["signals"]["favoured_players"]}
        assert before == after == {1, 2, 6, 7}


# ---------------------------------------------------------------------------
# B. wildcard
# ---------------------------------------------------------------------------

class TestWildcardFavoured:
    def test_favoured_teams_are_the_easy_runs_by_team_id(self, wc_bootstrap):
        out = get_chip_advice("wildcard", wc_bootstrap)
        assert out["status"] == "ok"
        assert out["signals"]["favoured_run_gameweeks"] == _WC_FAVOURED_RUN_GWS == 5
        teams = out["signals"]["favoured_teams"]
        assert [t["team"] for t in teams] == [14, 1]          # easiest first
        assert [t["team_short"] for t in teams] == ["LIV", "ARS"]
        assert [t["avg_fdr"] for t in teams] == [2.0, 2.4]
        assert all(t["fixture_count"] == 5 for t in teams)
        assert all(isinstance(t["team"], int) for t in teams)

    def test_the_run_is_the_callers_horizon_when_given(self, wc_bootstrap):
        # Over 3 GWs MCI averages (2+4+3)/3 = 3.0 → still out; ARS (2,3,2) = 2.33.
        out = get_chip_advice("wildcard", wc_bootstrap, horizon=3)
        assert out["signals"]["favoured_run_gameweeks"] == 3
        by_id = {t["team"]: t for t in out["signals"]["favoured_teams"]}
        assert set(by_id) == {14, 1}
        assert by_id[1]["avg_fdr"] == 2.33
        assert by_id[1]["fixture_count"] == 3

    def test_the_run_is_not_the_captain_windows_one_gw_fallback(self, wc_bootstrap):
        # horizon=None resolves to 1 inside captain_time_context; the chip
        # must not read a "run" of one gameweek from that.
        out = get_chip_advice("wildcard", wc_bootstrap)
        assert out["time_context"]["horizon"] == 1
        assert out["signals"]["favoured_run_gameweeks"] == 5

    def test_tie_on_average_ranks_the_fuller_run_first(self, wc_bootstrap):
        bs = copy.deepcopy(wc_bootstrap)
        bs["team_fixtures"][1] = [_fx(28, 2)]          # ARS: one easy fixture, avg 2.0
        out = get_chip_advice("wildcard", bs)
        teams = out["signals"]["favoured_teams"]
        assert [(t["team"], t["fixture_count"]) for t in teams] == [(14, 5), (1, 1)]

    def test_no_team_fixtures_gives_empty_list_not_neutral_favour(self, bootstrap):
        bs = copy.deepcopy(bootstrap)
        bs["chips"] = [{"name": "wildcard", "start_event": 20, "stop_event": 38}]
        assert "team_fixtures" not in bs
        out = get_chip_advice("wildcard", bs)
        assert out["status"] == "ok"
        assert out["signals"]["favoured_teams"] == []
        assert out["recommendation"] == "conditions_marginal"

    def test_a_team_absent_from_team_fixtures_is_not_favoured(self, wc_bootstrap):
        out = get_chip_advice("wildcard", wc_bootstrap)
        assert 11 not in {t["team"] for t in out["signals"]["favoured_teams"]}   # MUN


# ---------------------------------------------------------------------------
# C. No behaviour change
# ---------------------------------------------------------------------------

_NEW_SIGNAL_KEYS = {"favoured_teams", "favoured_players", "favoured_run_gameweeks"}


def _without_new_keys(out: dict[str, Any]) -> dict[str, Any]:
    stripped = copy.deepcopy(out)
    stripped["signals"] = {k: v for k, v in stripped["signals"].items() if k not in _NEW_SIGNAL_KEYS}
    return stripped


class TestNoBehaviourChange:
    @pytest.mark.parametrize("chip", ["bench_boost", "wildcard", "triple_captain", "free_hit"])
    def test_pre_existing_output_is_what_it_was(self, chip, bb_bootstrap, wc_bootstrap):
        bs = copy.deepcopy(wc_bootstrap)
        bs["fixture_difficulty_map"] = bb_bootstrap["fixture_difficulty_map"]
        out = get_chip_advice(chip, bs)
        assert out["status"] == "ok"
        # The signals that existed before E1 are still there, untouched in shape.
        legacy = _without_new_keys(out)["signals"]
        if chip == "bench_boost":
            assert set(legacy) == {"average_fdr_top10", "top_player_count"}
            assert legacy["top_player_count"] == 5
        elif chip == "wildcard":
            assert set(legacy) == {"current_gameweek", "active_window", "gameweeks_remaining"}
        elif chip == "free_hit":
            # i108 E2 adds favoured_teams (DGW teams by id) to FH; nothing else.
            assert _NEW_SIGNAL_KEYS & set(out["signals"]) == {"favoured_teams"}
        else:
            # TC gains nothing.
            assert not (_NEW_SIGNAL_KEYS & set(out["signals"]))
        # advice_text still carries the legacy caveat: E1 does not touch prose.
        if chip == "bench_boost":
            assert "not available to this system" in out["advice_text"]
        if chip == "wildcard":
            assert "not available to this system" in out["advice_text"]

    def test_bench_boost_verdict_ignores_the_new_signals(self, bb_bootstrap):
        # Top-10 here is the five pool players with FDR 2,2,4,2,2 → 12/5 = 2.4.
        # The verdict is computed before the favoured lists exist; pin it
        # against the threshold arithmetic, not against the lists.
        out = get_chip_advice("bench_boost", bb_bootstrap)
        avg = out["signals"]["average_fdr_top10"]
        assert avg == 2.4
        assert out["recommendation"] == "conditions_favorable"


# ---------------------------------------------------------------------------
# D. Declared in output_schema
# ---------------------------------------------------------------------------

def _prop(schema: dict[str, Any], *path: str) -> dict[str, Any]:
    node = schema
    for key in path:
        node = node["properties"][key]
    return node


class TestDeclaredInOutputSchema:
    def test_new_arrays_are_declared_under_signals_with_integer_identity(self):
        schema = CHIP_ADVICE_SPEC.output_schema
        teams = _prop(schema, "signals", "favoured_teams")
        players = _prop(schema, "signals", "favoured_players")
        assert teams["type"] == "array"
        assert players["type"] == "array"
        assert teams["items"]["properties"]["team"] == {"type": "integer"}
        assert players["items"]["properties"]["element"] == {"type": "integer"}
        assert players["items"]["properties"]["team"] == {"type": "integer"}
        assert "team" in teams["items"]["required"]
        assert {"element", "team"} <= set(players["items"]["required"])
        assert _prop(schema, "signals", "favoured_run_gameweeks") == {"type": "integer"}

    @pytest.mark.parametrize("chip", ["bench_boost", "wildcard"])
    def test_real_output_emits_no_signal_array_the_schema_does_not_declare(self, chip, bb_bootstrap, wc_bootstrap):
        bs = copy.deepcopy(wc_bootstrap)
        bs["fixture_difficulty_map"] = bb_bootstrap["fixture_difficulty_map"]
        out = get_chip_advice(chip, bs)
        declared = set(_prop(CHIP_ADVICE_SPEC.output_schema, "signals").get("properties", {}))
        emitted_arrays = {k for k, v in out["signals"].items() if isinstance(v, list)}
        assert emitted_arrays <= declared, sorted(emitted_arrays - declared)

    @pytest.mark.parametrize("chip", ["bench_boost", "wildcard"])
    def test_real_rows_carry_every_required_item_field(self, chip, bb_bootstrap, wc_bootstrap):
        bs = copy.deepcopy(wc_bootstrap)
        bs["fixture_difficulty_map"] = bb_bootstrap["fixture_difficulty_map"]
        out = get_chip_advice(chip, bs)
        for field in ("favoured_teams", "favoured_players"):
            rows = out["signals"].get(field)
            if rows is None:
                continue
            items = _prop(CHIP_ADVICE_SPEC.output_schema, "signals", field)["items"]
            for row in rows:
                assert set(items["required"]) <= set(row), (field, row)
                assert set(row) <= set(items["properties"]), (field, sorted(set(row) - set(items["properties"])))
