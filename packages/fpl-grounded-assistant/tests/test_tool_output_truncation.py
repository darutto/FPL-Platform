"""i49 -- the LLM-payload truncation lever covers what tools DECLARE, and no name lies.

Before this card ``orchestrator._TRUNCATABLE_FIELDS`` was a hand-written list
of seven field names. Two of them lied (``candidates`` for
rank_captain_candidates, which returns ``ranked_candidates``; ``players`` for
get_injury_list, which returns ``injured``/``doubtful``/``other``), so the two
tools the lever's own header names as its reason to exist were never capped,
while get_my_squad's 15-man squad -- the real owner of ``players`` -- was
silently cut to 10.

Where the declarations live
---------------------------
Every tool registers a ``ToolSpec`` with an ``output_schema`` in
``fpl_tool_runner.TOOL_REGISTRY`` (each tool module's ``*_SPEC``; the five
originals in ``fpl_tool_runner.specs``). ``tool_schema_registry`` is the
LLM-facing INPUT registry and declares no outputs. Suite A pins that.

Suites
------
A. Declarations -- every LLM-offered tool has an executable spec with an
   output_schema; the test's OWN schema walk (independent of the
   orchestrator's) finds the array census.
B. Coverage property -- for every (tool, field) the test's own walk finds, a
   synthetic output with 50 items is capped to 10 with a note naming the
   field, EXCEPT the pairs this file lists literally as kept-whole; those keep
   all 50 and get no note. Both directions pinned against produced output.
C. The lie -- rank_captain_candidates.ranked_candidates is capped; the tool no
   longer depends on the name ``candidates``; held_back (emitted, undeclared)
   is bridged and the bridge expires when the field gets declared.
D. Omission guard -- run the tools that work on the shared bootstrap and check
   every top-level list the REAL output carries is declared; the known
   undeclared ones are pinned literally and must stay undeclared (remove the
   pin once someone declares them).
E. Threshold and note text unchanged (the card says so).
F. Wiring -- each provider branch of ``_build_multi_tool_follow_up`` passes
   the tool name through, proven with an excluded field (the union fallback
   would cut it).
"""
from __future__ import annotations

import copy
import json
from typing import Any

import pytest

import fpl_grounded_assistant  # noqa: F401  (triggers tool self-registration)
from fpl_tool_runner import TOOL_REGISTRY
from fpl_grounded_assistant.orchestrator import (
    _TOOL_OUTPUT_MAX_LIST_ITEMS,
    _TRUNCATION_EXCLUDED_FIELDS,
    _UNDECLARED_TRUNCATABLE_FIELDS,
    _build_multi_tool_follow_up,
    _declared_array_fields,
    _truncatable_fields_for,
    _truncate_tool_output,
)
from fpl_grounded_assistant.tool_dispatch import run_tool
from fpl_grounded_assistant.tool_schema_registry import TOOL_NAMES_WITH_SEARCH


# ---------------------------------------------------------------------------
# The test's OWN schema walk -- deliberately not the orchestrator's helper, so
# a broken derivation (e.g. one that stops following ``oneOf``) is caught.
# ---------------------------------------------------------------------------

def _walk_arrays(schema: Any) -> set[str]:
    out: set[str] = set()
    if not isinstance(schema, dict):
        return out
    for key in ("oneOf", "anyOf", "allOf"):
        for branch in schema.get(key) or []:
            out |= _walk_arrays(branch)
    for name, prop in (schema.get("properties") or {}).items():
        t = prop.get("type") if isinstance(prop, dict) else None
        if t == "array" or (isinstance(t, list) and "array" in t):
            out.add(name)
    return out


def _declared_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name in sorted(TOOL_REGISTRY.list_tools()):
        for field in sorted(_walk_arrays(TOOL_REGISTRY.get_spec(name).output_schema)):
            pairs.append((name, field))
    return pairs


DECLARED_PAIRS: list[tuple[str, str]] = _declared_pairs()

#: The pairs this file expects to stay WHOLE, written out by hand so that
#: editing the orchestrator's exclusion table in EITHER direction fails here.
EXPECTED_WHOLE: frozenset[tuple[str, str]] = frozenset({
    ("build_squad", "squad"),
    ("build_squad", "starting_xi"),
    ("get_my_squad", "players"),
    ("get_fixtures_for_gw", "fixtures"),
    ("get_fixture_outlook", "series"),
    ("get_gameweek_context", "blank_gw_alerts"),
    ("get_gameweek_context", "double_gw_alerts"),
    ("get_historical_gameweek_top_scorer", "entries"),
    # i95: 11 static strings, one over the cap, emitted on refusal paths so
    # the model can pick a permitted domain; a cut allowlist would lie.
    ("web_fetch", "allowed_domains"),
})

#: Lists that tools EMIT without declaring them. Pinned so a new omission
#: fails suite D by name, and so declaring one of these forces the pin out.
#: Empty since i95: held_back, dgw_gameweeks, bgw_gameweeks and
#: allowed_domains are all declared now (measured 2026-09-17 against real
#: outputs: every one of them reached the model's tool payload undeclared).
#: The mechanism stays so the next omission fails suite D by name.
KNOWN_UNDECLARED: frozenset[tuple[str, str]] = frozenset()

N = 50
CAP = _TOOL_OUTPUT_MAX_LIST_ITEMS


def _big(field: str) -> dict[str, Any]:
    return {"status": "ok", field: [{"i": i, "field": field} for i in range(N)]}


# ---------------------------------------------------------------------------
# A. Where the declarations live
# ---------------------------------------------------------------------------

class TestDeclarationsLiveInToolSpecOutputSchema:
    def test_every_llm_offered_tool_has_an_executable_spec_with_output_schema(self):
        missing = []
        for name in sorted(TOOL_NAMES_WITH_SEARCH):
            spec = TOOL_REGISTRY.get_spec(name)
            if spec is None or not isinstance(spec.output_schema, dict) or not spec.output_schema:
                missing.append(name)
        assert missing == [], f"tools offered to the LLM without an output_schema: {missing}"

    def test_executable_registry_and_llm_registry_name_the_same_tools(self):
        assert set(TOOL_REGISTRY.list_tools()) == set(TOOL_NAMES_WITH_SEARCH)

    def test_census_is_at_least_the_card_count(self):
        # The card counted 36 declared array fields; the walk finds 50 pairs /
        # 38 distinct names at a9b2fcc. Pin the floor, not the exact number,
        # so adding a tool does not break this -- suite B covers each new one.
        assert len(DECLARED_PAIRS) >= 36
        assert len({f for _, f in DECLARED_PAIRS}) >= 36

    def test_orchestrator_walk_agrees_with_independent_walk(self):
        for name in TOOL_REGISTRY.list_tools():
            schema = TOOL_REGISTRY.get_spec(name).output_schema
            assert _declared_array_fields(schema) == frozenset(_walk_arrays(schema)), name

    def test_one_of_branches_are_followed(self):
        # These four declare their arrays ONLY inside oneOf branches.
        assert "picks" in _truncatable_fields_for("get_differential_picks")
        assert {"candidates", "fixtures"} <= _truncatable_fields_for("get_player_fixture_run")
        assert {"candidates", "comparison_reasons"} <= _truncatable_fields_for("compare_players")
        assert {"candidates", "transfer_reasons"} <= _truncatable_fields_for("get_transfer_advice")


# ---------------------------------------------------------------------------
# B. Coverage property, both directions, asserted on the produced dict
# ---------------------------------------------------------------------------

class TestEveryDeclaredArrayIsCoveredOrDeliberatelyWhole:
    @pytest.mark.parametrize(
        "tool,field",
        [p for p in DECLARED_PAIRS if p not in EXPECTED_WHOLE],
        ids=[f"{t}::{f}" for t, f in DECLARED_PAIRS if (t, f) not in EXPECTED_WHOLE],
    )
    def test_declared_array_is_capped(self, tool: str, field: str):
        out = _truncate_tool_output(_big(field), tool_name=tool)
        assert len(out[field]) == CAP, f"{tool}.{field}: expected {CAP}, got {len(out[field])}"
        assert out["_truncation_note"] == (
            f"showing top {CAP} of available results; ask for more if needed. "
            f"Truncated: {field}: showing top {CAP} of {N} total."
        )

    @pytest.mark.parametrize(
        "tool,field", sorted(EXPECTED_WHOLE), ids=[f"{t}::{f}" for t, f in sorted(EXPECTED_WHOLE)],
    )
    def test_structural_array_stays_whole(self, tool: str, field: str):
        assert (tool, field) in DECLARED_PAIRS, f"{tool}.{field} is not declared -- an exclusion for an undeclared field is a lie"
        out = _truncate_tool_output(_big(field), tool_name=tool)
        assert len(out[field]) == N, f"{tool}.{field}: structural list was cut to {len(out[field])}"
        assert "_truncation_note" not in out

    def test_exclusion_table_matches_this_file_exactly(self):
        assert _TRUNCATION_EXCLUDED_FIELDS == EXPECTED_WHOLE

    def test_every_exclusion_is_declared_by_its_tool(self):
        for tool, field in _TRUNCATION_EXCLUDED_FIELDS:
            assert field in _walk_arrays(TOOL_REGISTRY.get_spec(tool).output_schema), (tool, field)

    def test_an_exclusion_is_per_tool_not_per_name(self):
        # ``fixtures`` is whole for get_fixtures_for_gw and capped for
        # get_team_schedule; ``players`` is whole for get_my_squad only.
        assert len(_truncate_tool_output(_big("fixtures"), tool_name="get_fixtures_for_gw")["fixtures"]) == N
        assert len(_truncate_tool_output(_big("fixtures"), tool_name="get_team_schedule")["fixtures"]) == CAP
        assert len(_truncate_tool_output(_big("players"), tool_name="get_my_squad")["players"]) == N

    def test_undeclared_field_of_a_known_tool_is_left_alone(self):
        # Derivation, not a name list: a list the tool does not declare (and
        # that is not bridged) is forwarded untouched, whatever its name.
        out = _truncate_tool_output(_big("risers"), tool_name="get_injury_list")
        assert len(out["risers"]) == N
        assert "_truncation_note" not in out

    def test_short_lists_are_untouched_additive_invariant(self):
        raw = {"status": "ok", "injured": [1, 2, 3]}
        out = _truncate_tool_output(raw, tool_name="get_injury_list")
        assert out == raw
        assert out is not raw

    def test_input_dict_is_not_mutated(self):
        raw = _big("injured")
        _truncate_tool_output(raw, tool_name="get_injury_list")
        assert len(raw["injured"]) == N


# ---------------------------------------------------------------------------
# C. The lie: rank_captain_candidates
# ---------------------------------------------------------------------------

class TestRankCaptainCandidates:
    def test_ranked_candidates_fifty_is_capped_to_ten(self):
        raw = {
            "status": "ok",
            "ranked_candidates": [{"rank": i + 1, "web_name": f"P{i}"} for i in range(N)],
            "pool_size": N,
        }
        out = _truncate_tool_output(raw, tool_name="rank_captain_candidates")
        assert len(out["ranked_candidates"]) == CAP
        assert out["ranked_candidates"][0]["rank"] == 1
        assert out["ranked_candidates"][-1]["rank"] == CAP
        assert f"ranked_candidates: showing top {CAP} of {N} total" in out["_truncation_note"]

    def test_candidates_name_is_not_needed_and_not_used(self):
        fields = _truncatable_fields_for("rank_captain_candidates")
        assert "ranked_candidates" in fields
        assert "candidates" not in fields
        # And the name alone does nothing for this tool: an echoed input list
        # called ``candidates`` would be forwarded whole.
        out = _truncate_tool_output(_big("candidates"), tool_name="rank_captain_candidates")
        assert len(out["candidates"]) == N

    def test_held_back_is_emitted_by_the_real_tool(self, bootstrap):
        # Asserted on produced output, not on the bridge table: the shared
        # bootstrap has form-0 players, which land in held_back.
        out = run_tool("rank_captain_candidates", {}, copy.deepcopy(bootstrap))
        assert out["status"] == "ok"
        assert isinstance(out.get("held_back"), list)

    def test_held_back_is_declared_and_capped_through_the_declaration(self):
        # i95: the declaration, not the bridge, is what caps it now. The
        # produced 311-row list still reaches the model as 10.
        assert "held_back" in _walk_arrays(TOOL_REGISTRY.get_spec("rank_captain_candidates").output_schema)
        assert ("rank_captain_candidates", "held_back") not in _UNDECLARED_TRUNCATABLE_FIELDS
        raw = {
            "status": "ok",
            "ranked_candidates": [{"rank": i + 1} for i in range(12)],
            "held_back": [{"rank": None, "held_back_reason": "avoid", "i": i} for i in range(311)],
        }
        out = _truncate_tool_output(raw, tool_name="rank_captain_candidates")
        assert len(out["held_back"]) == CAP
        assert len(out["ranked_candidates"]) == CAP
        assert "held_back: showing top 10 of 311 total" in out["_truncation_note"]

    def test_bridge_entries_expire_once_declared(self):
        # A bridge entry for a field the tool now declares is dead weight and a
        # second name list in the making: fail so it gets removed. i95 retired
        # the only entry; the table is expected EMPTY until a new bridge is
        # needed, and a new one must be undeclared by its tool.
        for tool, field in _UNDECLARED_TRUNCATABLE_FIELDS:
            spec = TOOL_REGISTRY.get_spec(tool)
            assert spec is not None, f"bridge names an unregistered tool: {tool}"
            assert field not in _walk_arrays(spec.output_schema), (
                f"{tool}.{field} is now declared -- remove it from "
                f"_UNDECLARED_TRUNCATABLE_FIELDS and from KNOWN_UNDECLARED"
            )
        assert _UNDECLARED_TRUNCATABLE_FIELDS == frozenset()


# ---------------------------------------------------------------------------
# D. Omission guard -- the schema must not lie by omission on real outputs
# ---------------------------------------------------------------------------

def _fx(gw: int, opp: int, is_home: bool, difficulty: int) -> dict[str, Any]:
    return {"gameweek": gw, "opponent_team": opp, "is_home": is_home, "difficulty": difficulty}


def _history_row(gw: int) -> dict[str, Any]:
    return {
        "element": 1, "round": gw, "total_points": 8, "minutes": 90,
        "goals_scored": 1, "assists": 0, "bonus": 1, "bps": 28,
        "expected_goals": 0.55, "expected_assists": 0.12,
        "expected_goal_involvements": 0.67, "value": 145,
        "was_home": True, "opponent_team": 11,
    }


def _guard_bootstrap(base: dict[str, Any]) -> dict[str, Any]:
    bs = copy.deepcopy(base)
    # Injected element summary: without it get_player_form/get_player_history
    # go to the live element-summary API. The injection path is checked first.
    bs["_element_summaries"] = {
        "1": {"history": [_history_row(gw) for gw in (24, 25, 26, 27)], "fixtures": [], "history_past": []},
    }
    # Injected GW fixtures: without them get_fixtures_for_gw calls the live
    # fixtures API. Two matches among the five conftest teams.
    bs["_gw_fixtures"] = {
        "28": [
            {"id": 901, "event": 28, "team_h": 1, "team_a": 13, "team_h_difficulty": 4,
             "team_a_difficulty": 2, "kickoff_time": "2026-03-07T15:00:00Z", "finished": False},
            {"id": 902, "event": 28, "team_h": 14, "team_a": 11, "team_h_difficulty": 2,
             "team_a_difficulty": 4, "kickoff_time": "2026-03-07T17:30:00Z", "finished": False},
        ],
    }
    # A tiny schedule so the fixture-shaped tools reach their ok path.
    bs["team_fixtures"] = {
        1:  [_fx(28, 13, True, 4), _fx(29, 14, False, 5), _fx(30, 8, True, 2)],
        13: [_fx(28, 1, False, 2), _fx(29, 8, True, 2), _fx(30, 11, False, 3)],
        14: [_fx(28, 11, True, 2), _fx(29, 1, True, 3), _fx(30, 13, False, 4)],
        8:  [_fx(28, 11, False, 3), _fx(29, 13, False, 4), _fx(30, 1, False, 4)],
        11: [_fx(28, 14, False, 4), _fx(29, 8, True, 3), _fx(30, 13, True, 4)],
    }
    return bs


# Tools whose ok path is reachable offline on the guard bootstrap, with the
# args that get them there. search_web and web_fetch are left out (both
# touch the network before any list is emitted); get_my_squad without a
# team id never opens a socket; the stores (zonal, historical, season
# points) answer missing_context/not_found offline and are included.
GUARD_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("resolve_player", {"query": "Haaland"}),
    ("get_player_summary", {"query": "Haaland"}),
    ("get_current_gameweek", {}),
    ("get_captain_score", {"query": "Haaland"}),
    ("rank_captain_candidates", {}),
    ("compare_players", {"query_a": "Haaland", "query_b": "Salah"}),
    ("get_transfer_advice", {"query_out": "Saka", "query_in": "Salah"}),
    ("get_chip_advice", {"chip": "wildcard"}),
    ("get_player_fixture_run", {"query": "Haaland"}),
    ("get_differential_picks", {}),
    ("get_player_form", {"query": "Haaland"}),
    ("get_injury_list", {}),
    ("get_price_changes", {}),
    ("get_team_fixture_calendar", {}),
    ("get_team_schedule", {"team_query": "Arsenal"}),
    ("get_position_fixture_run", {"position_query": "MID"}),
    ("get_transfer_suggestion", {"position_query": "MID"}),
    ("get_fixture_outlook", {"axis": "attack", "team_query": "Arsenal"}),
    ("get_fixture_outlook", {"axis": "attack"}),
    ("find_players", {"name_query": "Johnson"}),
    ("get_player_snapshot", {"player_name": "Johnson"}),
    ("get_player_snapshot", {"player_name": "Haaland"}),
    ("get_player_history", {"player_name": "Haaland"}),
    ("get_fixtures_for_gw", {"gw_number": 28}),
    ("get_gameweek_context", {}),
    ("get_team_snapshot", {"team_name": "Arsenal"}),
    ("rank_players_by_metric", {"metric": "form"}),
    ("build_squad", {}),
    ("select_players_within_budget", {"position": "MID", "count": 2}),
    ("get_zonal_weakness", {"team": "Arsenal"}),
    ("get_zonal_opportunity", {"opponent": "Arsenal"}),
    ("get_player_zonal_outlook", {"player": "Haaland"}),
    # get_expected_minutes / get_tactical_role / get_fixture_context /
    # get_player_intelligence need the football_intelligence runtime package,
    # which is not on the pytest path; their output_schemas declare no arrays.
    ("get_player_season_points", {"query": "Haaland", "season": "2024-25"}),
    ("get_historical_gameweek_top_scorer", {}),
    ("get_my_squad", {}),
]


@pytest.fixture(scope="module")
def produced(bootstrap) -> dict[tuple[str, str], dict[str, Any]]:
    bs = _guard_bootstrap(bootstrap)
    return {
        (name, json.dumps(args, sort_keys=True)): run_tool(name, dict(args), copy.deepcopy(bs))
        for name, args in GUARD_CALLS
    }


class TestSchemaDoesNotLieByOmission:
    def test_guard_reaches_the_ok_path_for_the_list_heavy_tools(self, produced):
        # Guard against the guard: if these regress to error dicts the
        # omission check below passes vacuously.
        ok_tools = {name for (name, _a), out in produced.items() if out.get("status") == "ok"}
        assert {
            "rank_captain_candidates", "get_injury_list", "get_differential_picks",
            "get_player_form", "get_team_schedule", "get_fixture_outlook",
            "get_fixtures_for_gw", "get_gameweek_context", "rank_players_by_metric",
        } <= ok_tools, sorted(ok_tools)

    def test_every_emitted_list_is_declared_or_pinned(self, produced):
        offenders: list[str] = []
        for (name, args), out in produced.items():
            declared = _walk_arrays(TOOL_REGISTRY.get_spec(name).output_schema)
            for key, value in out.items():
                if isinstance(value, list) and key not in declared and (name, key) not in KNOWN_UNDECLARED:
                    offenders.append(f"{name}.{key} (len {len(value)}, args {args})")
        assert offenders == [], "lists emitted but not declared in output_schema:\n" + "\n".join(offenders)

    def test_pinned_omissions_are_still_undeclared(self):
        stale = [
            (t, f) for t, f in KNOWN_UNDECLARED
            if f in _walk_arrays(TOOL_REGISTRY.get_spec(t).output_schema)
        ]
        assert stale == [], f"now declared -- drop from KNOWN_UNDECLARED: {stale}"

    def test_pinned_omissions_are_really_emitted(self, produced):
        seen: set[tuple[str, str]] = set()
        for (name, _a), out in produced.items():
            for key, value in out.items():
                if isinstance(value, list):
                    seen.add((name, key))
        assert KNOWN_UNDECLARED <= seen, f"pinned but never produced here: {sorted(KNOWN_UNDECLARED - seen)}"

    def test_the_lists_i95_declared_are_capped_or_deliberately_whole(self, produced):
        # held_back can grow (the "avoid" split of a ~500-player pool): capped
        # through its declaration. dgw/bgw_gameweeks are bounded by the
        # horizon cap (10) so the lever's cap never bites: declared, capped in
        # principle, never in practice. allowed_domains is 11 static strings:
        # declared AND deliberately whole (see _TRUNCATION_EXCLUDED_FIELDS).
        out = produced[("rank_captain_candidates", "{}")]
        assert isinstance(out["held_back"], list)
        assert "held_back" in _truncatable_fields_for("rank_captain_candidates")
        assert {"dgw_gameweeks", "bgw_gameweeks"} <= _truncatable_fields_for("get_team_schedule")
        assert "allowed_domains" in _walk_arrays(TOOL_REGISTRY.get_spec("web_fetch").output_schema)
        assert "allowed_domains" not in _truncatable_fields_for("web_fetch")
        refusal = {"status": "refused", "code": "url_not_allowlisted",
                   "allowed_domains": [f"d{i}.example" for i in range(11)]}
        assert len(_truncate_tool_output(refusal, tool_name="web_fetch")["allowed_domains"]) == 11


# ---------------------------------------------------------------------------
# E. Threshold and note text unchanged
# ---------------------------------------------------------------------------

class TestThresholdAndNoteArePinned:
    def test_threshold_is_ten(self):
        assert _TOOL_OUTPUT_MAX_LIST_ITEMS == 10

    def test_note_text_is_byte_for_byte_the_old_one(self):
        out = _truncate_tool_output({"status": "ok", "injured": list(range(25))}, tool_name="get_injury_list")
        assert out["_truncation_note"] == (
            "showing top 10 of available results; ask for more if needed. "
            "Truncated: injured: showing top 10 of 25 total."
        )

    def test_note_lists_every_capped_field_in_output_order(self):
        raw = {"status": "ok", "risers": list(range(15)), "fallers": list(range(12))}
        out = _truncate_tool_output(raw, tool_name="get_price_changes")
        assert out["_truncation_note"] == (
            "showing top 10 of available results; ask for more if needed. "
            "Truncated: risers: showing top 10 of 15 total; fallers: showing top 10 of 12 total."
        )

    def test_legacy_call_without_tool_name_still_caps_declared_names(self):
        # run_phase_orch3a_tests.py calls _truncate_tool_output(raw) -- the
        # union fallback keeps that shape working.
        out = _truncate_tool_output({"status": "ok", "players": list(range(25))})
        assert len(out["players"]) == 10
        assert "25" in out["_truncation_note"]

    def test_unknown_tool_uses_the_union(self):
        assert _truncatable_fields_for("no_such_tool") == _truncatable_fields_for(None)
        assert {"ranked_candidates", "injured", "held_back", "players"} <= _truncatable_fields_for(None)


# ---------------------------------------------------------------------------
# F. Wiring: every provider branch passes the tool name through
# ---------------------------------------------------------------------------

class _Resp:
    content: list[Any] = []
    output: list[Any] = []
    candidates: list[Any] = []


def _executed() -> list[tuple[str | None, str | None, dict[str, Any], dict[str, Any]]]:
    return [
        ("id-squad", "build_squad", {}, {"status": "ok", "squad": [{"i": i} for i in range(15)]}),
        ("id-inj", "get_injury_list", {}, {"status": "ok", "injured": [{"i": i} for i in range(25)]}),
    ]


class TestFollowUpPassesToolName:
    def test_anthropic_branch(self):
        msgs = _build_multi_tool_follow_up("anthropic", [], _Resp(), _executed())
        results = {r["tool_use_id"]: json.loads(r["content"]) for r in msgs[-1]["content"]}
        assert len(results["id-squad"]["squad"]) == 15       # excluded: whole
        assert len(results["id-inj"]["injured"]) == 10       # declared: capped

    def test_openai_branch(self):
        msgs = _build_multi_tool_follow_up("openai", [], _Resp(), _executed())
        results = {m["call_id"]: json.loads(m["output"]) for m in msgs if isinstance(m, dict) and m.get("type") == "function_call_output"}
        assert len(results["id-squad"]["squad"]) == 15
        assert len(results["id-inj"]["injured"]) == 10

    def test_gemini_branch(self):
        msgs = _build_multi_tool_follow_up("gemini", [], _Resp(), _executed())
        parts = {p["function_response"]["name"]: p["function_response"]["response"] for p in msgs[-1]["parts"]}
        assert len(parts["build_squad"]["squad"]) == 15
        assert len(parts["get_injury_list"]["injured"]) == 10
