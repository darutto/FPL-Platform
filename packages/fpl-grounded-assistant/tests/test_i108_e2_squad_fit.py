"""i108 E2 -- the user's squad crossed against the chip's favoured group, by id.

E1 named the favoured group (bench_boost / wildcard) by element / team id.
E2 answers the particular half: do YOU hold it?

What this file pins
-------------------
A. Verdicts (the rule agreed for i108, no new constants):
   * favoured group empty → ``not_applicable`` whatever the squad;
   * bench_boost: unit = the bench; ``missing_count`` = bench − favoured bench;
   * wildcard / free_hit: ``held`` = favoured squad members,
     ``missing_count`` = favoured teams with no player of yours;
   * ``missing_count == 0`` → ``set``, else ``needs_transfers``.
   Identity is the element id; a member's team is read from the bootstrap by
   that id. Two conftest players share ``web_name`` "Johnson" -- a name-keyed
   cross credits the wrong one.
B. free_hit gains ``signals.favoured_teams`` by integer team id, read from
   ``team_fixtures`` -- never mapped from the short-name ``dgw_teams``.
C. Contract of where the members come from, exercised through
   ``tool_dispatch.run_tool`` (the seam that fetches; chip_advisor never does):
   request ``players`` wins; otherwise ``_my_team_id`` → ``load_linked_squad``
   once per turn; nothing → ``None`` without network; a failed fetch →
   ``squad_source=None`` + ``linked_squad_error="fetch_failed"``. The linked
   squad never enters ``_squad_context``, so its consumers see what they saw.
D. Declared -- ``squad_source``, ``squad_fit`` (+ ``held``/``missing_count``/
   ``verdict``), ``linked_squad_error`` and the favoured arrays are in
   ``CHIP_ADVICE_SPEC.output_schema``; real output emits no top-level key the
   schema does not declare.
E. ``squad_source`` is a name rank_captain_candidates also emits, with a
   different vocabulary; final_response reads it only for that intent, so the
   chip's value never reaches ``AskResponse.squad_source``.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest

import importlib

import fpl_grounded_assistant  # noqa: F401  (tool self-registration)
from fpl_grounded_assistant import tool_dispatch
from fpl_grounded_assistant.chip_advisor import (
    CHIP_ADVICE_SPEC,
    LINKED_SQUAD_KEY,
    get_chip_advice,
)
from fpl_grounded_assistant.dispatcher import INTENT_CHIP_ADVICE, INTENT_RANK_CANDIDATES
from fpl_grounded_assistant.final_response import (
    _apply_squad_overrides,
    _extract_structured_meta,
)

# The package re-exports the get_my_squad FUNCTION under the same name; the
# module is needed to stub its get_entry_picks.
get_my_squad_module = importlib.import_module("fpl_grounded_assistant.get_my_squad")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: this-GW FDR: MCI/LIV/CHE/MUN easy, ARS hard → favoured players {1, 2, 6, 7},
#: favoured teams {8, 11, 13, 14} (E1 rule: top-10 with fdr <= 2.5).
_BB_FDR = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}


def _fx(gw: int, difficulty: int, opp: int = 1) -> dict[str, Any]:
    return {"gameweek": gw, "opponent_team": opp, "is_home": True, "difficulty": difficulty}


def _squad(bench: list[int], starters: list[int] | None = None) -> list[dict[str, Any]]:
    """15 rows shaped like get_my_squad's ``players``: 11 starters then the bench.

    Ids >= 900 are not in the bootstrap (team unknown → never favoured), so
    each test controls exactly which members could be favoured.
    """
    starters = starters if starters is not None else list(range(901, 912))
    rows = []
    for pos, element in enumerate(starters + bench, start=1):
        rows.append({
            "id": element,
            "web_name": f"P{element}",
            "pick_position": pos,
            "is_starter": pos <= 11,
        })
    return rows


def _with_request_squad(bs: dict[str, Any], members: list[dict[str, Any]]) -> dict[str, Any]:
    bs = copy.deepcopy(bs)
    bs["_squad_context"] = {"players": members}
    return bs


@pytest.fixture
def bb_bootstrap(bootstrap) -> dict[str, Any]:
    bs = copy.deepcopy(bootstrap)
    bs["fixture_difficulty_map"] = dict(_BB_FDR)
    return bs


@pytest.fixture
def wc_bootstrap(bootstrap) -> dict[str, Any]:
    """Five-GW runs from GW28: LIV (14) avg 2.0 and ARS (1) avg 2.4 favoured."""
    bs = copy.deepcopy(bootstrap)
    bs["team_fixtures"] = {
        14: [_fx(gw, 2) for gw in range(28, 33)],
        1:  [_fx(gw, d) for gw, d in zip(range(28, 33), (2, 3, 2, 3, 2))],
        13: [_fx(gw, d) for gw, d in zip(range(28, 33), (2, 4, 3, 4, 3))],
        8:  [_fx(gw, 3) for gw in range(28, 33)],
    }
    bs["chips"] = [{"name": "wildcard", "start_event": 20, "stop_event": 38}]
    return bs


@pytest.fixture
def fh_bootstrap(bootstrap) -> dict[str, Any]:
    """GW28: MCI (13) and LIV (14) play twice; ARS/CHE/MUN once."""
    bs = copy.deepcopy(bootstrap)
    bs["team_fixtures"] = {
        13: [_fx(28, 2), _fx(28, 3)],
        14: [_fx(28, 2), _fx(28, 2)],
        1:  [_fx(28, 3)],
        8:  [_fx(28, 3)],
        11: [_fx(28, 3)],
    }
    return bs


# ---------------------------------------------------------------------------
# A. Verdicts
# ---------------------------------------------------------------------------

class TestBenchBoostVerdicts:
    def test_whole_bench_favoured_is_set(self, bb_bootstrap):
        out = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, _squad([1, 2, 6, 7])))
        assert out["squad_fit"] == {"held": [1, 2, 6, 7], "missing_count": 0, "verdict": "set"}

    def test_two_of_four_needs_two(self, bb_bootstrap):
        # 3 = Saka (ARS, FDR 4) not favoured; 998 unknown to the bootstrap.
        out = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, _squad([1, 2, 3, 998])))
        assert out["squad_fit"] == {"held": [1, 2], "missing_count": 2, "verdict": "needs_transfers"}

    def test_none_of_four_needs_four_not_not_applicable(self, bb_bootstrap):
        out = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, _squad([3, 997, 998, 999])))
        assert out["squad_fit"] == {"held": [], "missing_count": 4, "verdict": "needs_transfers"}

    def test_a_bench_player_on_a_favoured_team_counts_even_outside_the_top10(self, bb_bootstrap):
        # De Bruyne (4) is injured → not in the scored pool, but MCI (13) is a
        # favoured team, so "o cuyo team ∈ favoured_teams" holds him.
        out = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, _squad([4, 997, 998, 999])))
        assert out["squad_fit"]["held"] == [4]

    def test_starters_do_not_count_for_bench_boost(self, bb_bootstrap):
        starters = [1, 2, 6, 7] + list(range(901, 908))
        out = get_chip_advice(
            "bench_boost",
            _with_request_squad(bb_bootstrap, _squad([996, 997, 998, 999], starters=starters)),
        )
        assert out["squad_fit"] == {"held": [], "missing_count": 4, "verdict": "needs_transfers"}

    def test_empty_group_is_not_applicable_whatever_the_squad(self, bb_bootstrap):
        bs = copy.deepcopy(bb_bootstrap)
        bs["fixture_difficulty_map"] = {13: 4, 14: 5, 1: 4, 8: 4, 11: 5}
        for bench in ([1, 2, 6, 7], [3, 997, 998, 999]):
            out = get_chip_advice("bench_boost", _with_request_squad(bs, _squad(bench)))
            assert out["signals"]["favoured_players"] == []
            assert out["squad_fit"] == {"held": [], "missing_count": 0, "verdict": "not_applicable"}

    def test_cross_is_by_id_not_by_name(self, bb_bootstrap):
        # MUN (11) now hard: Johnson 7 (MUN) is NOT favoured, Johnson 6 (CHE) is.
        # A name-keyed cross would credit bench Johnson 7 with Johnson 6's fixture.
        bs = copy.deepcopy(bb_bootstrap)
        bs["fixture_difficulty_map"][11] = 4
        members = _squad([7, 997, 998, 999])
        members[11]["web_name"] = "Johnson"
        out = get_chip_advice("bench_boost", _with_request_squad(bs, members))
        assert 6 in {p["element"] for p in out["signals"]["favoured_players"]}
        assert out["squad_fit"]["held"] == []
        assert out["squad_fit"]["missing_count"] == 4

    def test_member_team_comes_from_the_bootstrap_not_the_row(self, bb_bootstrap):
        # A row claiming a favoured team_short does not make an unknown id favoured.
        members = _squad([997, 998, 999, 996])
        for m in members[11:]:
            m["team_short"] = "LIV"
            m["team"] = 14
        out = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, members))
        assert out["squad_fit"]["held"] == []

    def test_bench_that_cannot_be_determined_gives_none(self, bb_bootstrap):
        members = [{"id": i} for i in (1, 2, 3, 6, 7)]
        out = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, members))
        assert out["squad_source"] == "request"
        assert out["squad_fit"] is None

    def test_advice_text_drops_the_bench_depth_caveat_with_a_squad(self, bb_bootstrap):
        without = get_chip_advice("bench_boost", bb_bootstrap)
        with_squad = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, _squad([1, 2, 6, 7])))
        assert "Bench depth" in without["advice_text"]
        assert "Bench depth" not in with_squad["advice_text"]
        assert "not available to this system" not in with_squad["advice_text"]
        # The verdict itself does not move with the squad.
        assert without["recommendation"] == with_squad["recommendation"]


class TestWildcardVerdicts:
    def test_every_favoured_team_covered_is_set(self, wc_bootstrap):
        # 2 = Salah (LIV), 3 = Saka (ARS): both favoured teams covered.
        out = get_chip_advice("wildcard", _with_request_squad(wc_bootstrap, _squad([997, 998, 999, 996], starters=[2, 3] + list(range(901, 910)))))
        assert out["squad_fit"] == {"held": [2, 3], "missing_count": 0, "verdict": "set"}

    def test_missing_count_is_favoured_teams_without_a_player(self, wc_bootstrap):
        out = get_chip_advice("wildcard", _with_request_squad(wc_bootstrap, _squad([997, 998, 999, 996], starters=[2] + list(range(901, 911)))))
        assert out["squad_fit"] == {"held": [2], "missing_count": 1, "verdict": "needs_transfers"}

    def test_wildcard_counts_the_whole_squad_bench_included(self, wc_bootstrap):
        out = get_chip_advice("wildcard", _with_request_squad(wc_bootstrap, _squad([2, 3, 998, 999])))
        assert out["squad_fit"]["verdict"] == "set"

    def test_no_run_data_is_not_applicable(self, bootstrap):
        bs = copy.deepcopy(bootstrap)
        bs["chips"] = [{"name": "wildcard", "start_event": 20, "stop_event": 38}]
        out = get_chip_advice("wildcard", _with_request_squad(bs, _squad([2, 3, 998, 999])))
        assert out["squad_fit"]["verdict"] == "not_applicable"

    def test_advice_text_stops_saying_composition_is_unknown(self, wc_bootstrap):
        out = get_chip_advice("wildcard", _with_request_squad(wc_bootstrap, _squad([2, 3, 998, 999])))
        assert "squad composition" not in out["advice_text"]
        assert "which wildcard you still hold is not known" in out["advice_text"]


class TestFreeHit:
    def test_favoured_teams_are_the_dgw_teams_by_id(self, fh_bootstrap):
        out = get_chip_advice("free_hit", fh_bootstrap)
        teams = out["signals"]["favoured_teams"]
        assert [t["team"] for t in teams] == [13, 14]
        assert all(isinstance(t["team"], int) for t in teams)
        assert [t["fixture_count"] for t in teams] == [2, 2]
        # Same teams the short-name signal names -- computed, not mapped.
        assert sorted(t["team_short"] for t in teams) == out["signals"]["dgw_teams"]

    def test_squad_fit_counts_dgw_teams_without_a_player(self, fh_bootstrap):
        out = get_chip_advice("free_hit", _with_request_squad(fh_bootstrap, _squad([997, 998, 999, 996], starters=[1] + list(range(901, 911)))))
        assert out["squad_fit"] == {"held": [1], "missing_count": 1, "verdict": "needs_transfers"}

    def test_normal_gameweek_is_not_applicable(self, bootstrap):
        bs = copy.deepcopy(bootstrap)
        bs["team_fixtures"] = {t: [_fx(28, 3)] for t in (1, 8, 11, 13, 14)}
        out = get_chip_advice("free_hit", _with_request_squad(bs, _squad([1, 2, 998, 999])))
        assert out["signals"]["favoured_teams"] == []
        assert out["squad_fit"]["verdict"] == "not_applicable"

    def test_short_names_are_never_mapped_to_ids(self, fh_bootstrap):
        # ARS (1) and MCI (13) share a short code: a short → id lookup cannot
        # tell them apart; ids read from team_fixtures still can.
        bs = copy.deepcopy(fh_bootstrap)
        for t in bs["teams"]:
            if t["id"] in (1, 13):
                t["short_name"] = "XXX"
        out = get_chip_advice("free_hit", bs)
        assert [t["team"] for t in out["signals"]["favoured_teams"]] == [13, 14]


class TestNoSquadAndOtherChips:
    def test_no_squad_gives_none_everywhere(self, bb_bootstrap):
        out = get_chip_advice("bench_boost", bb_bootstrap)
        assert out["squad_source"] is None
        assert out["squad_fit"] is None
        assert out["linked_squad_error"] is None

    def test_triple_captain_carries_source_but_no_fit(self, bb_bootstrap):
        out = get_chip_advice("triple_captain", _with_request_squad(bb_bootstrap, _squad([1, 2, 6, 7])))
        assert out["squad_source"] == "request"
        assert out["squad_fit"] is None

    def test_missing_context_gives_no_fit(self, bootstrap):
        bs = copy.deepcopy(bootstrap)
        for el in bs["elements"]:
            el["status"] = "i"      # empty captain pool → BB missing_context
        out = get_chip_advice("bench_boost", _with_request_squad(bs, _squad([1, 2, 6, 7])))
        assert out["recommendation"] == "missing_context"
        assert out["squad_fit"] is None


# ---------------------------------------------------------------------------
# C. Where the members come from -- through the seam that fetches
# ---------------------------------------------------------------------------

@pytest.fixture
def spy(monkeypatch):
    """Replace load_linked_squad where tool_dispatch looks it up; record calls."""
    calls: list[Any] = []
    state: dict[str, Any] = {"result": {"status": "ok", "players": _squad([1, 2, 6, 7])}}

    def fake(bootstrap, gw=None):
        calls.append(bootstrap.get("_my_team_id"))
        result = state["result"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(tool_dispatch, "load_linked_squad", fake)
    return calls, state


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real picks fetch in this file is a bug."""
    def boom(*_a, **_k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(get_my_squad_module, "get_entry_picks", boom)


class TestSquadSourceContract:
    def test_request_players_win_and_the_helper_is_not_called(self, bb_bootstrap, spy):
        calls, _ = spy
        bs = _with_request_squad(bb_bootstrap, _squad([1, 2, 3, 998]))
        bs["_my_team_id"] = 68643
        out = tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        assert out["squad_source"] == "request"
        assert out["squad_fit"]["held"] == [1, 2]
        assert calls == []
        assert LINKED_SQUAD_KEY not in bs

    def test_prod_shape_request_without_players_plus_team_id_is_linked_team(self, bb_bootstrap, spy):
        # What the UI sends today: itb / free_transfers / chips_remaining, no players.
        calls, _ = spy
        bs = copy.deepcopy(bb_bootstrap)
        ui_context = {"itb": 15, "free_transfers": 1, "chips_remaining": ["bench_boost", "wildcard"]}
        bs["_squad_context"] = copy.deepcopy(ui_context)
        bs["_my_team_id"] = 68643
        out = tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        assert calls == [68643]
        assert out["squad_source"] == "linked_team"
        assert out["squad_fit"] == {"held": [1, 2, 6, 7], "missing_count": 0, "verdict": "set"}
        # The request's state fields are untouched and the squad is NOT put in them.
        assert bs["_squad_context"] == ui_context

    def test_team_id_only_fetches_once_per_turn(self, bb_bootstrap, spy):
        calls, _ = spy
        bs = copy.deepcopy(bb_bootstrap)
        bs["_my_team_id"] = 68643
        first = tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        second = tool_dispatch.run_tool("get_chip_advice", {"chip": "wildcard"}, bs)
        assert calls == [68643]
        assert first["squad_source"] == second["squad_source"] == "linked_team"

    def test_nothing_linked_is_none_without_network(self, bb_bootstrap, spy):
        calls, _ = spy
        bs = copy.deepcopy(bb_bootstrap)
        out = tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        assert calls == []
        assert out["squad_source"] is None and out["squad_fit"] is None
        assert out["linked_squad_error"] is None
        assert LINKED_SQUAD_KEY not in bs

    def test_ui_context_without_players_and_no_team_is_none(self, bb_bootstrap, spy):
        calls, _ = spy
        bs = copy.deepcopy(bb_bootstrap)
        bs["_squad_context"] = {"itb": 15, "chips_remaining": ["bench_boost"]}
        out = tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        assert calls == []
        assert out["squad_source"] is None and out["squad_fit"] is None

    @pytest.mark.parametrize("failure", [None, RuntimeError("picks down")])
    def test_linked_but_fetch_failed_is_named_not_silent(self, bb_bootstrap, spy, failure):
        calls, state = spy
        state["result"] = failure
        bs = copy.deepcopy(bb_bootstrap)
        bs["_my_team_id"] = 68643
        out = tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        assert out["status"] == "ok"
        assert out["squad_source"] is None
        assert out["squad_fit"] is None
        assert out["linked_squad_error"] == "fetch_failed"
        # Not retried within the turn.
        tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        assert calls == [68643]

    def test_other_tools_do_not_trigger_the_fetch(self, bb_bootstrap, spy):
        calls, _ = spy
        bs = copy.deepcopy(bb_bootstrap)
        bs["_my_team_id"] = 68643
        tool_dispatch.run_tool("get_current_gameweek", {}, bs)
        assert calls == []
        assert LINKED_SQUAD_KEY not in bs

    def test_real_wrapper_end_to_end_with_stubbed_picks(self, bb_bootstrap, monkeypatch):
        # load_linked_squad is get_my_squad: same fetch, same picks parsing.
        picks = {
            "picks": [
                {"element": e, "position": pos, "multiplier": 1, "is_captain": False, "is_vice_captain": False}
                for pos, e in enumerate(list(range(901, 912)) + [1, 2, 3, 998], start=1)
            ],
            "entry_history": {"points": 50, "total_points": 400, "bank": 5},
            "active_chip": None,
        }
        seen: list[tuple[int, int]] = []

        def fake_picks(team_id, gw):
            seen.append((team_id, gw))
            return picks

        monkeypatch.setattr(get_my_squad_module, "get_entry_picks", fake_picks)
        bs = copy.deepcopy(bb_bootstrap)
        bs["_my_team_id"] = 68643
        out = tool_dispatch.run_tool("get_chip_advice", {"chip": "bench_boost"}, bs)
        assert seen == [(68643, 28)]
        assert out["squad_source"] == "linked_team"
        assert out["squad_fit"] == {"held": [1, 2], "missing_count": 2, "verdict": "needs_transfers"}

    def test_consumers_tolerate_the_new_players_key(self):
        # _apply_squad_overrides reads itb / chips_remaining / free_transfers
        # with .get; a squad_context carrying only players changes nothing.
        transfer, chip, text = _apply_squad_overrides(
            transfer=None, chip=None, final_text="t", squad_context={"players": _squad([1, 2, 6, 7])},
        )
        assert (transfer, chip, text) == (None, None, "t")

    def test_availability_note_unchanged_by_the_linked_squad(self, bb_bootstrap, spy):
        # The picks API does not say which chips remain: with only a linked
        # squad (no request squad_context) the TC note must still say so.
        bs = copy.deepcopy(bb_bootstrap)
        bs["_my_team_id"] = 68643
        out = tool_dispatch.run_tool("get_chip_advice", {"chip": "triple_captain"}, bs)
        assert "whether you still have this chip available is not known" in out["advice_text"]


# ---------------------------------------------------------------------------
# D. Declared in output_schema
# ---------------------------------------------------------------------------

def _prop(*path: str) -> dict[str, Any]:
    node = CHIP_ADVICE_SPEC.output_schema
    for key in path:
        node = node["properties"][key]
    return node


class TestDeclared:
    def test_squad_fields_are_declared_with_their_types(self):
        assert _prop("squad_source") == {
            "type": ["string", "null"], "enum": ["request", "linked_team", None],
        }
        fit = _prop("squad_fit")
        assert fit["type"] == ["object", "null"]
        assert set(fit["required"]) == {"held", "missing_count", "verdict"}
        assert _prop("squad_fit", "held") == {"type": "array", "items": {"type": "integer"}}
        assert _prop("squad_fit", "missing_count") == {"type": "integer"}
        assert _prop("squad_fit", "verdict")["enum"] == ["set", "needs_transfers", "not_applicable"]
        assert _prop("linked_squad_error") == {
            "type": ["string", "null"], "enum": ["fetch_failed", None],
        }
        assert _prop("signals", "favoured_teams")["type"] == "array"
        assert _prop("signals", "favoured_players")["type"] == "array"

    @pytest.mark.parametrize("chip", ["bench_boost", "wildcard", "free_hit", "triple_captain"])
    def test_real_output_emits_no_undeclared_top_level_key(self, chip, bb_bootstrap, wc_bootstrap, fh_bootstrap):
        bs = copy.deepcopy(wc_bootstrap)
        bs["fixture_difficulty_map"] = dict(_BB_FDR)
        if chip == "free_hit":
            bs["team_fixtures"] = fh_bootstrap["team_fixtures"]
        out = get_chip_advice(chip, _with_request_squad(bs, _squad([1, 2, 6, 7], starters=[3] + list(range(901, 911)))))
        declared = set(CHIP_ADVICE_SPEC.output_schema["properties"])
        # Pre-E2 keys the schema never declared; pinned so a NEW omission fails.
        pre_existing_undeclared = {"evaluated_gameweek", "time_context", "fixture_context"}
        assert set(out) - declared <= pre_existing_undeclared, sorted(set(out) - declared - pre_existing_undeclared)
        if out["squad_fit"] is not None:
            assert set(out["squad_fit"]) == set(_prop("squad_fit")["properties"])
            assert all(isinstance(e, int) for e in out["squad_fit"]["held"])
        emitted_signal_arrays = {k for k, v in out["signals"].items() if isinstance(v, list)}
        undeclared_signal_arrays = emitted_signal_arrays - set(_prop("signals").get("properties", {}))
        # Pre-i108 signal lists, undeclared before E1 and left as they were:
        # free hit's short-name lists and triple captain's factor phrases.
        assert undeclared_signal_arrays <= {
            "dgw_teams", "bgw_teams", "affected_teams",
            "top_factors", "top_factors_es", "evaluated_factors", "evaluated_factors_es",
        }


# ---------------------------------------------------------------------------
# E. squad_source name collision with rank_captain_candidates
# ---------------------------------------------------------------------------

class TestSquadSourceDoesNotLeak:
    def test_chip_squad_source_is_not_read_into_the_response(self, bb_bootstrap):
        out = get_chip_advice("bench_boost", _with_request_squad(bb_bootstrap, _squad([1, 2, 6, 7])))
        assert out["squad_source"] == "request"
        meta = _extract_structured_meta(INTENT_CHIP_ADVICE, out, "ok")
        assert meta.get("squad_source") is None

    def test_control_rank_candidates_does_read_it(self):
        meta = _extract_structured_meta(
            INTENT_RANK_CANDIDATES, {"status": "ok", "squad_source": "not_connected"}, "ok",
        )
        assert meta.get("squad_source") == "not_connected"
