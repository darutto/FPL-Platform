"""
i101 -- the /fixtures cell tap must point at its gameweek, not make the model
guess it.

Before this change ``get_fixture_outlook`` only had ``horizon`` (a window
from the current GW), so answering "J5" required the model to compute
``horizon = 5 - current + 1`` against a current GW the call never stated. In
prod (2026-09-14, current J4) it guessed ``horizon=1`` and described J4. The
fix is a ``target_gw`` argument the model COPIES from the text.

Three layers, each asserted from what was produced (the series, the returned
status/message, the registered schema), never from the argument that asked:

* engine  -- ``get_team_outlook(..., target_gw=N)`` anchors the window at N
             and ignores current_gw for the window (the fixture has
             ``current_gw=2`` and asks for J6: a window built from current_gw
             would not contain J6 at horizon 1);
* wrapper -- two distinct ``not_found`` messages (played vs beyond data), the
             valid case compared against ``bootstrap["team_fixtures"]``
             directly, ``verdict_scope="match"`` through the unchanged i78-A
             path;
* catalog -- ``target_gw`` declared identically in ToolSpec and ToolSchema, and
             the description tells the model to copy the number, not compute
             a horizon.
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401  (registers the tool)
from fpl_tool_runner import TOOL_REGISTRY, run_tool  # noqa: E402
from fpl_grounded_assistant import fixture_outlook as fo  # noqa: E402
from fpl_grounded_assistant.fixture_outlook_tool import (  # noqa: E402
    FIXTURE_OUTLOOK_SPEC,
    _TARGET_GW_NOT_FOUND,
)
from fpl_grounded_assistant.tool_schema_registry import get_tool_schema  # noqa: E402


# ---------------------------------------------------------------------------
# Bootstrap: FDR fallback (no strength fields), current GW = 2, fixtures J1..J8
# ---------------------------------------------------------------------------

def _fx(gw: int, opp: int, is_home: bool, difficulty: int) -> dict:
    return {"gameweek": gw, "opponent_team": opp, "is_home": is_home,
            "difficulty": difficulty}


def _bootstrap() -> dict:
    """Current GW is 2 (J1 already played). Arsenal's J6 is the target the
    tests aim at: a window anchored at current_gw with horizon=1 is [2, 3),
    which does NOT contain J6 -- so any test that finds J6 in the series has
    proven the window was anchored at target_gw."""
    ars = [_fx(1, 2, True, 2), _fx(2, 3, False, 2), _fx(3, 2, True, 1),
           _fx(4, 3, False, 5), _fx(5, 2, False, 5), _fx(6, 3, True, 4),
           _fx(7, 2, True, 3), _fx(8, 3, False, 3)]
    bre = [_fx(g, 1 if g % 2 else 3, g % 2 == 0, 3) for g in range(1, 9)]
    che = [_fx(g, 1 if g % 2 == 0 else 2, g % 2 == 1, 3) for g in range(1, 9)]
    return {
        "teams": [
            {"id": 1, "name": "Arsenal",   "short_name": "ARS"},
            {"id": 2, "name": "Brentford", "short_name": "BRE"},
            {"id": 3, "name": "Chelsea",   "short_name": "CHE"},
        ],
        "events": [{"id": 1, "is_current": False, "finished": True},
                   {"id": 2, "is_current": True}],
        "team_fixtures": {1: ars, 2: bre, 3: che},
    }


def _expected_fixture(bs: dict, team_id: int, gw: int) -> list[dict]:
    """The fixtures the bootstrap actually holds for (team, gw) -- the
    independent yardstick the wrapper tests compare against."""
    return [f for f in bs["team_fixtures"][team_id] if f["gameweek"] == gw]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def test_engine_target_gw_anchors_the_window_at_the_target_not_current_gw():
    bs = _bootstrap()
    out = fo.get_team_outlook(bs, 1, "attack", target_gw=6)
    assert out["target_gw"] == 6
    assert out["target_gw_status"] == fo.TARGET_GW_OK
    assert [e["gameweek"] for e in out["series"]] == [6]
    # The band is J6's own difficulty (4), not J2's (2): the window really
    # moved. Read off the produced series.
    assert out["series"][0]["band"] == 4
    assert out["series"][0]["fixtures"][0]["opponent_short"] == "CHE"
    assert out["horizon"] == 1


def test_engine_current_gw_is_not_used_for_the_window_when_target_gw_is_given(monkeypatch):
    """If the engine consulted current_gw for the window it would build
    [2, 3); pin that a differently-resolved current GW changes nothing about
    WHICH gameweek is described (only the past/beyond classification)."""
    bs = _bootstrap()
    out_at_2 = fo.get_team_outlook(bs, 1, "attack", target_gw=6)
    out_at_5 = fo.get_team_outlook(bs, 1, "attack", target_gw=6, _current_gw=5)
    assert [e["gameweek"] for e in out_at_2["series"]] == [6]
    assert out_at_2["series"] == out_at_5["series"]


def test_engine_target_gw_in_the_past_yields_no_series_and_says_past():
    bs = _bootstrap()
    out = fo.get_team_outlook(bs, 1, "attack", target_gw=1)
    assert out["series"] == []
    assert out["target_gw_status"] == fo.TARGET_GW_PAST
    assert out["runs"] == []


def test_engine_target_gw_beyond_max_horizon_yields_no_series_and_says_beyond_data():
    bs = _bootstrap()
    beyond = 2 + fo._MAX_HORIZON  # current_gw + _MAX_HORIZON is the first GW out
    out = fo.get_team_outlook(bs, 1, "attack", target_gw=beyond)
    assert out["series"] == []
    assert out["target_gw_status"] == fo.TARGET_GW_BEYOND_DATA
    # One inside the rail is still served (even with no fixture loaded the
    # status is ok -- "no data for this GW" is the series' business).
    inside = fo.get_team_outlook(bs, 1, "attack", target_gw=beyond - 1)
    assert inside["target_gw_status"] == fo.TARGET_GW_OK


def test_engine_target_gw_equal_to_current_gw_is_the_current_match():
    bs = _bootstrap()
    out = fo.get_team_outlook(bs, 1, "attack", target_gw=2)
    assert out["target_gw_status"] == fo.TARGET_GW_OK
    assert [e["gameweek"] for e in out["series"]] == [2]


def test_engine_target_gw_on_a_double_gameweek_keeps_both_fixtures_in_one_entry():
    bs = _bootstrap()
    bs["team_fixtures"][1].append(_fx(6, 2, False, 2))  # ARS also away at BRE in J6
    out = fo.get_team_outlook(bs, 1, "attack", target_gw=6)
    assert len(out["series"]) == 1
    entry = out["series"][0]
    assert entry["gameweek"] == 6
    assert entry["is_dgw"] is True
    assert sorted(f["opponent_short"] for f in entry["fixtures"]) == ["BRE", "CHE"]


def test_engine_horizon_and_target_gw_together_fail_loud():
    bs = _bootstrap()
    with pytest.raises(ValueError):
        fo.get_team_outlook(bs, 1, "attack", horizon=3, target_gw=6)
    with pytest.raises(ValueError):
        fo.get_team_outlook(bs, 1, "attack", 3, target_gw=6)


def test_engine_without_target_gw_is_byte_for_byte_the_old_behaviour():
    """The horizon path is untouched: same window from current_gw, same
    keys except the two new ones (None)."""
    bs = _bootstrap()
    out = fo.get_team_outlook(bs, 1, "attack", horizon=3)
    assert [e["gameweek"] for e in out["series"]] == [2, 3, 4]
    assert out["target_gw"] is None
    assert out["target_gw_status"] is None
    default = fo.get_team_outlook(bs, 1, "attack")
    assert default["horizon"] == fo.DEFAULT_HORIZON


def test_engine_all_teams_path_is_unaffected():
    bs = _bootstrap()
    out = fo.get_all_team_outlooks(bs, "attack", horizon=3)
    assert out["status"] == "ok"
    assert all([e["gameweek"] for e in t["series"]] == [2, 3, 4] for t in out["teams"])


# ---------------------------------------------------------------------------
# Wrapper (through the real runner)
# ---------------------------------------------------------------------------

def _run(args: dict, bs: dict) -> dict:
    return run_tool("get_fixture_outlook", args, bs)


def test_wrapper_valid_target_gw_describes_exactly_that_match():
    bs = _bootstrap()
    res = _run({"axis": "attack", "team_query": "ARS", "target_gw": 6}, bs)
    assert res["status"] == "ok"
    assert res["verdict_scope"] == "match"
    assert [e["gameweek"] for e in res["series"]] == [6]
    # Compare against the bootstrap's own fixture for (ARS, J6), not a number
    # copied from the question.
    expected = _expected_fixture(bs, 1, 6)
    assert len(expected) == 1
    exp = expected[0]
    got = res["series"][0]["fixtures"][0]
    assert got["opponent_short"] == {2: "BRE", 3: "CHE"}[exp["opponent_team"]]
    assert got["is_home"] == exp["is_home"]
    assert got["band"] == exp["difficulty"]
    assert "J6:" in res["verdict"]
    assert "racha" not in res["verdict"].lower()


def test_wrapper_target_gw_wins_over_a_horizon_the_model_also_sent():
    """The failure mode i101 fixes: a model that still sends horizon=1 along
    with target_gw=6 must get J6, not the current GW."""
    bs = _bootstrap()
    res = _run({"axis": "attack", "team_query": "ARS", "target_gw": 6, "horizon": 1}, bs)
    assert res["status"] == "ok"
    assert [e["gameweek"] for e in res["series"]] == [6]


def test_wrapper_target_gw_in_the_past_is_not_found_with_the_played_message():
    bs = _bootstrap()
    res = _run({"axis": "attack", "team_query": "ARS", "target_gw": 1}, bs)
    assert res["status"] == "not_found"
    assert res["message"] == _TARGET_GW_NOT_FOUND[fo.TARGET_GW_PAST].format(gw=1)
    assert "ya se jugó" in res["message"]
    assert res.get("series") == []
    assert "verdict_scope" not in res


def test_wrapper_target_gw_beyond_data_is_not_found_with_the_no_data_message():
    bs = _bootstrap()
    beyond = 2 + fo._MAX_HORIZON
    res = _run({"axis": "attack", "team_query": "ARS", "target_gw": beyond}, bs)
    assert res["status"] == "not_found"
    assert res["message"] == _TARGET_GW_NOT_FOUND[fo.TARGET_GW_BEYOND_DATA].format(gw=beyond)
    assert "No hay datos" in res["message"]
    assert res.get("series") == []


def test_wrapper_the_two_not_found_messages_are_different():
    past = _TARGET_GW_NOT_FOUND[fo.TARGET_GW_PAST].format(gw=1)
    beyond = _TARGET_GW_NOT_FOUND[fo.TARGET_GW_BEYOND_DATA].format(gw=1)
    assert past != beyond


def test_wrapper_target_gw_without_team_query_is_an_argument_error():
    bs = _bootstrap()
    res = _run({"axis": "attack", "target_gw": 6}, bs)
    assert res["status"] == "invalid_argument"
    assert res["code"] == "target_gw_requires_team"
    assert "teams" not in res


def test_wrapper_non_numeric_target_gw_is_an_argument_error_not_a_silent_window():
    bs = _bootstrap()
    res = _run({"axis": "attack", "team_query": "ARS", "target_gw": "J5"}, bs)
    assert res["status"] == "invalid_argument"
    assert res["code"] == "target_gw_not_a_number"
    assert "series" not in res


def test_wrapper_target_gw_as_numeric_string_is_accepted():
    bs = _bootstrap()
    res = _run({"axis": "attack", "team_query": "ARS", "target_gw": "6"}, bs)
    assert res["status"] == "ok"
    assert [e["gameweek"] for e in res["series"]] == [6]


def test_wrapper_target_gw_on_defence_axis_uses_defence_wording():
    bs = _bootstrap()
    res = _run({"axis": "defence", "team_query": "ARS", "target_gw": 6}, bs)
    assert res["status"] == "ok"
    assert res["verdict_scope"] == "match"
    assert "portería a cero" in res["verdict"]


def test_wrapper_without_target_gw_still_uses_horizon_from_current_gw():
    bs = _bootstrap()
    res = _run({"axis": "attack", "team_query": "ARS", "horizon": 1}, bs)
    assert res["status"] == "ok"
    assert [e["gameweek"] for e in res["series"]] == [2]
    assert res["target_gw"] is None


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def test_catalog_declares_target_gw_in_spec_and_schema_identically():
    schema = get_tool_schema("get_fixture_outlook")
    assert schema is not None
    spec = TOOL_REGISTRY.get_spec("get_fixture_outlook")
    assert spec is FIXTURE_OUTLOOK_SPEC
    for params in (schema.parameters, spec.parameters):
        assert "target_gw" in params["properties"]
        assert params["properties"]["target_gw"]["type"] == "integer"
        assert "target_gw" not in params.get("required", [])
    assert set(schema.parameters["properties"]) == set(spec.parameters["properties"])


def test_catalog_description_tells_the_model_to_copy_the_number_not_compute_horizon():
    desc = get_tool_schema("get_fixture_outlook").description
    assert "target_gw=5" in desc
    assert "Do NOT compute horizon" in desc
    # The old instruction that asked for arithmetic is gone.
    assert "or up to the named GW" not in desc
    assert "horizon=1 for the current/next GW" not in desc


def test_catalog_output_schema_declares_the_new_fields():
    props = FIXTURE_OUTLOOK_SPEC.output_schema["properties"]
    assert "target_gw" in props
    assert "target_gw_status" in props
