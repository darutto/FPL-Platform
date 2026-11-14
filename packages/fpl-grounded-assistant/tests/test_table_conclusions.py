"""table_conclusions: the metric ranking's verdict (0-3 conclusions about the table, never its rows).

Synthetic data only -- invented names, clubs and values. No LLM anywhere: the orchestrator end-to-end test
stubs ``ask_orchestrated`` with a canned result, as tests/test_i58_card_gate_distinct_tool.py does.
"""
from __future__ import annotations

import json

import pytest

import fpl_grounded_assistant  # noqa: F401
from fpl_grounded_assistant import table_conclusions as tc
from fpl_grounded_assistant.table_conclusions import (
    resource_ranking_conclusions,
    ranking_conclusions,
    tool_ranking_conclusions,
)

_TEAMS = [{"id": i + 1, "short_name": s} for i, s in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"))]
_TEAM_ID = {t["short_name"]: t["id"] for t in _TEAMS}
_POS_ID = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}

#: (name, team, position, value): a flat list -- no gap, no team or position holding it.
_FLAT = (
    ("Alfa", "AAA", "MID", 50), ("Bravo", "BBB", "FWD", 49), ("Charlie", "CCC", "DEF", 48),
    ("Delta", "DDD", "MID", 47), ("Echo", "EEE", "FWD", 46), ("Foxtrot", "FFF", "DEF", 45),
    ("Golf", "AAA", "GKP", 44), ("Hotel", "BBB", "MID", 43), ("India", "CCC", "FWD", 42),
    ("Juliet", "DDD", "DEF", 41),
)


def _tool_rows(spec=_FLAT, **changes):
    """``rank_players_by_metric`` rows. ``changes`` maps a name to replaced fields."""
    rows = []
    for i, (name, team, pos, value) in enumerate(spec):
        row = {"id": i + 1, "rank": i + 1, "web_name": name, "team_short": team, "position": pos,
               "metric_value": float(value)}
        row.update(changes.get(name, {}))
        rows.append(row)
    return rows


def _resource_rows(spec=_FLAT):
    return [{"web_name": n, "team_short": t, "position": p, "value": float(v)} for n, t, p, v in spec]


def _bootstrap(spec=_FLAT, owned=None):
    """Everyone owned by 30 % unless ``owned`` names another percent."""
    owned = owned or {}
    return {
        "teams": _TEAMS,
        "elements": [
            {"id": i + 1, "web_name": n, "team": _TEAM_ID[t], "element_type": _POS_ID[p], "status": "a",
             "selected_by_percent": str(owned.get(n, 30.0))}
            for i, (n, t, p, _v) in enumerate(spec)
        ],
    }


def _keys(conclusions):
    return [c["key"] for c in conclusions]


def _with_values(*values):
    return tuple((n, t, p, v) for (n, t, p, _), v in zip(_FLAT, values))


# --- gap -------------------------------------------------------------------------------------------------

def test_gap_fires_for_a_clear_solo_leader():
    spec = _with_values(100, 78, 76, 75, 74, 73, 72, 71, 70, 69)
    out = ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec))
    assert out == [{
        "key": "gap",
        "params": {"leaders": ["Alfa"], "metric": "form"},
        "evidence": {"next_rank": 2, "next_value": 78, "lead_values": [100]},
    }]


def test_gap_fires_for_a_leading_pair():
    spec = _with_values(100, 97, 70, 69, 68, 67, 66, 65, 64, 63)
    (gap,) = ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec))
    assert gap["params"]["leaders"] == ["Alfa", "Bravo"]
    assert gap["evidence"] == {"next_rank": 3, "next_value": 70, "lead_values": [100, 97]}


@pytest.mark.parametrize("values", [
    (50, 49, 48, 47, 46, 45, 44, 43, 42, 41),      # near-ties
    (100, 85, 84, 83, 82, 81, 80, 79, 78, 77),     # 15 % lead: under the threshold
    (100, 80, 60, 40, 30, 20, 15, 10, 5, 1),       # steady fall: big first step, bigger spread below
    (100, 88, 60, 59, 58, 57, 56, 55, 54, 53),     # 12 % apart: neither a solo leader nor a pair
])
def test_gap_does_not_fire(values):
    spec = _with_values(*values)
    assert "gap" not in _keys(ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec)))


def test_gap_needs_five_rows():
    spec = _with_values(100, 50, 49, 48)
    assert ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec)) == []


def test_gap_skips_lowest_first_and_set_piece_rankings():
    spec = _with_values(100, 78, 76, 75, 74, 73, 72, 71, 70, 69)
    rows, bootstrap = _tool_rows(spec), _bootstrap(spec)
    assert "gap" not in _keys(ranking_conclusions(rows, "form", bootstrap, order="asc"))
    assert "gap" not in _keys(ranking_conclusions(rows, "penalties_order", bootstrap))


@pytest.mark.parametrize("metric", sorted(tc.NOT_A_MERIT_METRICS))
def test_gap_does_not_fire_where_leading_is_not_a_merit(metric):
    spec = _with_values(100, 78, 76, 75, 74, 73, 72, 71, 70, 69)
    rows, bootstrap = _tool_rows(spec), _bootstrap(spec)
    assert "gap" in _keys(ranking_conclusions(rows, "form", bootstrap))  # the same rows do fire on a merit metric
    assert "gap" not in _keys(ranking_conclusions(rows, metric, bootstrap))


def test_gap_does_not_fire_on_a_one_unit_lead_in_whole_numbers():
    one_unit = _with_values(2, 1, 1, 1, 1, 1)
    assert "gap" not in _keys(ranking_conclusions(_tool_rows(one_unit), "goals_scored", _bootstrap(one_unit)))
    pair = _with_values(3, 3, 2, 2, 2, 2)  # a leading pair one unit clear
    assert "gap" not in _keys(ranking_conclusions(_tool_rows(pair), "goals_scored", _bootstrap(pair)))
    two_units = _with_values(4, 2, 2, 2, 2, 2)
    assert "gap" in _keys(ranking_conclusions(_tool_rows(two_units), "goals_scored", _bootstrap(two_units)))
    # the floor is for whole-number lists only: the same one-unit lead with a decimal in the list still fires
    decimals = _with_values(2.0, 1.0, 1.0, 1.0, 1.0, 0.5)
    assert "gap" in _keys(ranking_conclusions(_tool_rows(decimals), "form", _bootstrap(decimals)))


def test_gap_keeps_numbers_as_numbers():
    spec = _with_values(9.5, 7.2, 7.1, 7.0, 6.9)
    (gap,) = ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec))
    assert gap["evidence"]["lead_values"] == [9.5] and gap["evidence"]["next_value"] == 7.2


# --- concentration ---------------------------------------------------------------------------------------

def test_concentration_team_fires_at_three_of_ten():
    spec = tuple((n, "AAA" if i < 3 else t, p, v) for i, (n, t, p, v) in enumerate(_FLAT))
    spec = tuple((n, "EEE" if n == "Golf" else t, p, v) for n, t, p, v in spec)  # Golf was AAA too
    out = ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec))
    assert out == [{"key": "concentration",
                    "params": {"kind": "team", "value": "AAA", "count": 3, "total": 10},
                    "evidence": None}]


def test_concentration_team_does_not_fire_at_two():
    assert ranking_conclusions(_tool_rows(), "form", _bootstrap()) == []  # _FLAT: two rows per club at most


def test_concentration_position_fires_at_seven_of_ten():
    spec = tuple((n, t, "MID" if i < 7 else "DEF", v) for i, (n, t, p, v) in enumerate(_FLAT))
    (line,) = ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec))
    assert line["params"] == {"kind": "position", "value": "MID", "count": 7, "total": 10}


def test_concentration_position_does_not_fire_at_six_of_ten():
    spec = tuple((n, t, "MID" if i < 6 else "DEF", v) for i, (n, t, p, v) in enumerate(_FLAT))
    assert ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec)) == []


def test_concentration_position_suppressed_by_position_filter_and_single_position_metric():
    spec = tuple((n, t, "GKP", v) for n, t, p, v in _FLAT)
    rows, bootstrap = _tool_rows(spec), _bootstrap(spec)
    assert _keys(ranking_conclusions(rows, "form", bootstrap)) == ["concentration"]
    assert ranking_conclusions(rows, "form", bootstrap, position_filter="GKP") == []
    assert "concentration" not in _keys(ranking_conclusions(rows, "saves", bootstrap))


def test_concentration_team_still_fires_under_a_position_filter():
    spec = tuple((n, "AAA" if i < 4 else t, "DEF", v) for i, (n, t, p, v) in enumerate(_FLAT[:6]))
    (line,) = ranking_conclusions(_tool_rows(spec), "form", _bootstrap(spec), position_filter="DEF")
    assert line["params"] == {"kind": "team", "value": "AAA", "count": 4, "total": 6}


# --- opportunity -----------------------------------------------------------------------------------------

def test_opportunity_fires_for_a_lightly_owned_row_in_the_top_half():
    out = ranking_conclusions(_tool_rows(), "form", _bootstrap(owned={"Charlie": 4.2, "Delta": 1.0}))
    assert out == [{"key": "opportunity",
                    "params": {"name": "Charlie", "kind": "ownership"},
                    "evidence": {"value": 4.2}}]


def test_opportunity_ignores_the_bottom_half_and_the_threshold_itself():
    assert ranking_conclusions(_tool_rows(), "form", _bootstrap(owned={"Foxtrot": 1.0})) == []
    assert ranking_conclusions(_tool_rows(), "form", _bootstrap(owned={"Alfa": tc.LOW_OWNERSHIP_PCT})) == []


def test_opportunity_skipped_when_the_metric_is_ownership_or_not_a_merit():
    bootstrap = _bootstrap(owned={"Alfa": 2.0})
    for metric in ("selected_by_percent", "now_cost", "yellow_cards"):
        assert "opportunity" not in _keys(ranking_conclusions(_tool_rows(), metric, bootstrap))
    assert "opportunity" not in _keys(ranking_conclusions(_tool_rows(), "form", bootstrap, order="asc"))


def test_opportunity_resolves_resource_rows_by_name_and_team():
    out = ranking_conclusions(_resource_rows(), "form", _bootstrap(owned={"Bravo": 3.0}))
    assert out[0]["params"]["name"] == "Bravo" and out[0]["evidence"] == {"value": 3.0}


def test_opportunity_dropped_when_the_player_does_not_resolve():
    bootstrap = _bootstrap(owned={"Alfa": 2.0})
    # by id: the row's id is not in the bootstrap
    assert ranking_conclusions(_tool_rows(Alfa={"id": 999}), "form", bootstrap) == []
    # by name + team: two elements share the name at the club -> not unique
    bootstrap["elements"].append(dict(bootstrap["elements"][0], id=77))
    assert ranking_conclusions(_resource_rows(), "form", bootstrap) == []
    assert ranking_conclusions(_tool_rows(), "form", None) == []


# --- reading ---------------------------------------------------------------------------------------------

def test_reading_fires_for_a_season_total_only():
    reading = [{"key": "reading", "params": {"kind": "total_metric"}, "evidence": None}]
    assert ranking_conclusions(_tool_rows(), "total_points", _bootstrap()) == reading
    for metric in ("expected_goals_per_90", "points_per_game", "form", "now_cost", "selected_by_percent",
                   "penalties_order", "minutes", "transfers_in_event", "an_unknown_metric"):
        assert "reading" not in _keys(ranking_conclusions(_tool_rows(), metric, _bootstrap())), metric
    assert ranking_conclusions(_tool_rows(), "total_points", _bootstrap(), order="asc") == []


# --- cap, priority, shapes, robustness -------------------------------------------------------------------

def _everything():
    """A ranking where all four rules fire."""
    spec = (("Alfa", "AAA", "MID", 100), ("Bravo", "AAA", "MID", 78), ("Charlie", "AAA", "FWD", 76),
            ("Delta", "DDD", "DEF", 75), ("Echo", "EEE", "FWD", 74), ("Foxtrot", "FFF", "DEF", 73))
    return spec, _bootstrap(spec, owned={"Bravo": 4.2})


def test_cap_of_three_and_priority_order():
    spec, bootstrap = _everything()
    out = ranking_conclusions(_tool_rows(spec), "total_points", bootstrap)
    assert _keys(out) == ["gap", "concentration", "opportunity"]  # reading is the one pushed out
    assert len(out) == tc.MAX_CONCLUSIONS


def test_reading_fills_a_free_slot():
    spec, bootstrap = _everything()
    out = ranking_conclusions(_tool_rows(spec), "total_points", _bootstrap(spec))  # nobody lightly owned
    assert _keys(out) == ["gap", "concentration", "reading"]


def test_both_row_shapes_give_the_same_conclusions():
    spec, bootstrap = _everything()
    assert (ranking_conclusions(_resource_rows(spec), "total_points", bootstrap)
            == ranking_conclusions(_tool_rows(spec), "total_points", bootstrap))


@pytest.mark.parametrize("rows", [
    None, "rows", 7, [], [None, 3, "x"], [{}], [{"web_name": "Alfa"}],
    [{"web_name": None, "metric_value": "abc"}], [{"web_name": "Alfa", "metric_value": float("nan")}],
    [{"web_name": "Alfa", "metric_value": True, "team_short": 5, "position": [], "id": "x"}] * 8,
])
def test_malformed_rows_never_raise(rows):
    for bootstrap in (None, {}, {"elements": "x", "teams": 4}, {"elements": [None, 3]}):
        for metric in ("total_points", "form", None, 5):
            assert isinstance(ranking_conclusions(rows, metric, bootstrap), list)


def test_a_bad_row_is_skipped_not_the_table():
    spec, bootstrap = _everything()
    rows = _tool_rows(spec)
    rows.insert(2, {"web_name": "Broken", "metric_value": None})
    rows.insert(4, "not a row")
    assert _keys(ranking_conclusions(rows, "total_points", bootstrap)) == ["gap", "concentration", "opportunity"]


def test_a_rule_that_raises_drops_only_its_line(monkeypatch):
    spec, bootstrap = _everything()
    monkeypatch.setattr(tc, "_concentration", lambda *a, **k: 1 / 0)
    assert _keys(ranking_conclusions(_tool_rows(spec), "total_points", bootstrap)) == ["gap", "opportunity", "reading"]


def test_output_is_plain_json():
    spec, bootstrap = _everything()
    out = ranking_conclusions(_tool_rows(spec), "total_points", bootstrap)
    assert json.loads(json.dumps(out)) == out
    for line in out:
        assert set(line) == {"key", "params", "evidence"}


# --- the two wrappers ------------------------------------------------------------------------------------

def test_tool_wrapper_reads_filter_and_order_and_needs_status_ok():
    spec = tuple((n, t, "GKP", v) for n, t, p, v in _FLAT)
    raw = {"status": "ok", "metric": "form", "order": "desc", "position_filter": None, "ranked": _tool_rows(spec)}
    assert _keys(tool_ranking_conclusions(raw, _bootstrap(spec))) == ["concentration"]
    assert tool_ranking_conclusions({**raw, "position_filter": "GKP"}, _bootstrap(spec)) == []
    assert tool_ranking_conclusions({**raw, "status": "invalid_argument"}, _bootstrap(spec)) == []
    assert tool_ranking_conclusions(None, None) == []


def test_resource_wrapper_covers_the_rankings_and_not_injuries():
    spec, bootstrap = _everything()
    payload = {"resource": "top_points", "rows": _resource_rows(spec)}
    assert _keys(resource_ranking_conclusions("top_points", payload, bootstrap)) == ["gap", "concentration", "opportunity"]
    assert "opportunity" not in _keys(resource_ranking_conclusions("popular", payload, bootstrap))
    assert resource_ranking_conclusions("injuries", payload, bootstrap) == []
    assert resource_ranking_conclusions("top_points", None, bootstrap) == []


# --- the module's metric tables against the live tool (compared, not imported by the module) ---------------

def test_metric_sets_match_the_ranking_tool():
    import importlib
    tool = importlib.import_module("fpl_grounded_assistant.rank_players_by_metric")  # the package re-exports the function under this name
    from fpl_grounded_assistant.resource_registry import _RESOURCE_HANDLERS

    canonical = set(tool._METRIC_ALIASES.values())
    assert tc.LOWER_IS_BETTER == tool._LOWER_IS_BETTER
    assert tc.SEASON_TOTAL_METRICS <= canonical and tc.NOT_A_MERIT_METRICS <= canonical
    assert not any(tool.is_rate_metric(m) for m in tc.SEASON_TOTAL_METRICS)
    assert set(tc.RESOURCE_METRICS) == set(_RESOURCE_HANDLERS) - {"injuries"}
    assert set(tc.RESOURCE_METRICS.values()) <= canonical


def test_module_imports_nothing_from_the_live_stack():
    import ast
    import inspect
    imported = {
        (node.module if isinstance(node, ast.ImportFrom) else alias.name)
        for node in ast.walk(ast.parse(inspect.getsource(tc)))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported == {"__future__", "math", "typing"}


# --- end to end: the field reaches the response on both paths ---------------------------------------------

def _e2e_bootstrap():
    """conftest's synthetic bootstrap shape is not needed: ask_v2 only routes, the rows are canned."""
    spec, bootstrap = _everything()
    bootstrap["events"] = [{"id": 1, "finished": True, "is_current": True}]
    bootstrap["element_types"] = [{"id": i, "singular_name_short": s} for s, i in _POS_ID.items()]
    return spec, bootstrap


def _ask_v2_rank_turn(monkeypatch, raw_output, bootstrap, *, tool_call_count=1, trace_names=("rank_players_by_metric",)):
    from fpl_grounded_assistant import harness
    from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult

    trace = tuple(
        {"round": i + 1, "tool_call_id": f"call_{i}", "name": name, "args": {}, "output": {"status": "ok"},
         "success": True}
        for i, name in enumerate(trace_names)
    )
    orch = OrchestratorResult(
        question="q", tool_chosen="rank_players_by_metric", tool_args={}, tool_output=raw_output,
        answer_text="Texto de prueba.", llm_used=True, model="m", outcome=OUTCOME_OK,
        tool_call_count=tool_call_count, tool_calls_trace=trace, synthesis_turn=True,
    )
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch)
    return harness.ask_v2("jugadores con mas puntos", bootstrap, orch_client=object())


def test_e2e_orchestrator_ranking_turn_carries_table_conclusions(monkeypatch):
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    from fpl_server import AskRequest

    spec, bootstrap = _e2e_bootstrap()
    raw = {"status": "ok", "metric": "total_points", "order": "desc", "top_n": len(spec),
           "position_filter": None, "ranked": _tool_rows(spec)}
    result = _ask_v2_rank_turn(monkeypatch, raw, bootstrap)
    assert result["selected_tool"] == "rank_players_by_metric"
    wire = to_ask_response(result, AskRequest(question="jugadores con mas puntos")).model_dump()
    assert wire["generic_card"] is not None
    assert [c["key"] for c in wire["table_conclusions"]] == ["gap", "concentration", "opportunity"]
    assert wire["table_conclusions"][0] == {
        "key": "gap",
        "params": {"leaders": ["Alfa"], "metric": "total_points"},
        "evidence": {"next_rank": 2, "next_value": 78, "lead_values": [100]},
    }


def test_e2e_orchestrator_turn_without_a_firing_rule_sends_null(monkeypatch):
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    from fpl_server import AskRequest

    bootstrap = _bootstrap()  # the flat list, everyone owned by 30 %: no rule fires
    raw = {"status": "ok", "metric": "form", "order": "desc", "top_n": 10, "position_filter": None,
           "ranked": _tool_rows()}
    result = _ask_v2_rank_turn(monkeypatch, raw, bootstrap)
    wire = to_ask_response(result, AskRequest(question="q")).model_dump()
    assert wire["generic_card"] is not None and wire["table_conclusions"] is None


def test_e2e_no_conclusions_without_the_card_they_talk_about(monkeypatch):
    """Two distinct tools -> no ranking card (i58 gate) -> no verdict about a table nobody sees."""
    spec, bootstrap = _e2e_bootstrap()
    raw = {"status": "ok", "metric": "total_points", "order": "desc", "top_n": len(spec),
           "position_filter": None, "ranked": _tool_rows(spec)}
    result = _ask_v2_rank_turn(monkeypatch, raw, bootstrap, tool_call_count=2,
                               trace_names=("rank_players_by_metric", "get_player_snapshot"))
    assert result.get("generic_card") is None and result["table_conclusions"] is None


def test_e2e_resource_ranking_carries_table_conclusions(monkeypatch):
    from fpl_grounded_assistant import harness
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    from fpl_server import AskRequest

    spec = (("Alfa", "AAA", "MID", 100), ("Bravo", "AAA", "MID", 78), ("Charlie", "AAA", "FWD", 76),
            ("Delta", "DDD", "DEF", 75), ("Echo", "EEE", "FWD", 74), ("Foxtrot", "FFF", "DEF", 73))
    bootstrap = _bootstrap(spec, owned={"Bravo": 4.2})
    for element, (_n, _t, _p, value) in zip(bootstrap["elements"], spec):
        element["total_points"] = value
    bootstrap["events"] = [{"id": 1, "finished": True, "is_current": True}]
    monkeypatch.setenv("FPL_ORCH_ENABLED", "0")

    result = harness.ask_v2("@top_points", bootstrap)
    assert result["kind"] == "resource" and result["resource"] == "top_points"
    wire = to_ask_response(result, AskRequest(question="@top_points")).model_dump()
    assert wire["resource_rows"]["resource"] == "top_points"
    assert wire["table_conclusions"] == [
        {"key": "gap", "params": {"leaders": ["Alfa"], "metric": "total_points"},
         "evidence": {"next_rank": 2, "next_value": 78, "lead_values": [100]}},
        {"key": "concentration", "params": {"kind": "team", "value": "AAA", "count": 3, "total": 6},
         "evidence": None},
        {"key": "opportunity", "params": {"name": "Bravo", "kind": "ownership"}, "evidence": {"value": 4.2}},
    ]

    injuries = harness.ask_v2("@injuries", bootstrap)
    assert injuries["kind"] == "resource" and injuries["table_conclusions"] is None


def test_response_models_declare_the_field():
    import fpl_server
    from fpl_grounded_assistant.final_response import FinalResponse

    assert "table_conclusions" in fpl_server.AskResponse.model_fields
    assert "table_conclusions" in fpl_server.SessionAskResponse.model_fields
    assert "table_conclusions" in FinalResponse.__dataclass_fields__
