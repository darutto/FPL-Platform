"""
i107 -- ``get_team_results``: one team's recent RESULTS with a home/away split.

Prod had no tool for "cómo le ha ido de local" / "goles en los últimos N
partidos": the model fired 2-3 web_fetch per turn and gave up. The scores were
already on every FPL fixture (team_h_score / team_a_score / finished); this
tool aggregates them per team, live or from the owned store for a past season.

Pinned here:
* the FOUR registration sites (module ToolSpec + TOOL_REGISTRY, the package
  import, the LLM ToolSchema, the renderer map) -- miss one and the tool does
  not exist at runtime, or the LLM cannot pick it, or its output has no text;
* the arithmetic, read off the produced payload against hand-computed values;
* last_n applied AFTER the venue filter; venue_split present whatever venue;
* team resolution through the shared alias resolver (ambiguous / not_found);
* the season path: parser variants, the stamp's season READ OFF THE POINTER
  (mutating the pointer changes the stamp; the directory does not), no
  pointer -> unknown, missing season -> not_found naming what exists, a
  relegated club resolving in its own season's ids;
* every emitted key declared in output_schema (i95);
* no network in tests: the live fetch is patched, and the cache is exercised.
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [
    _PKG,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
    os.path.join(_PKGS, "fpl-historical"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

import fpl_grounded_assistant  # noqa: E402,F401  (triggers registration)
import importlib  # noqa: E402
mod = importlib.import_module("fpl_grounded_assistant.get_team_results")  # the module, not the re-exported function
from fpl_grounded_assistant.get_team_results import (  # noqa: E402
    GET_TEAM_RESULTS_SPEC,
    build_matches,
    get_team_results,
    summarize,
)
from fpl_grounded_assistant.renderer import _RENDERERS, render  # noqa: E402
from fpl_grounded_assistant.tool_schema_registry import _ALL_SCHEMAS  # noqa: E402
from fpl_tool_runner import TOOL_REGISTRY  # noqa: E402

TEAMS = [
    {"id": 1, "name": "Arsenal", "short_name": "ARS"},
    {"id": 8, "name": "Chelsea", "short_name": "CHE"},
    {"id": 13, "name": "Man City", "short_name": "MCI"},
    {"id": 11, "name": "Man Utd", "short_name": "MUN"},
    {"id": 14, "name": "Liverpool", "short_name": "LIV"},
    {"id": 17, "name": "Spurs", "short_name": "TOT"},
]


def _fx(i, gw, h, a, hs, as_, finished=True):
    return {"id": i, "event": gw, "team_h": h, "team_a": a, "team_h_score": hs, "team_a_score": as_,
            "finished": finished, "kickoff_time": f"2026-08-{10 + gw:02d}T14:00:00Z"}


# Arsenal: GW1 H 2-0 LIV (W, CS), GW2 A 1-1 MCI (D), GW3 H 0-1 CHE (L),
# GW4 A 3-1 MUN (W), GW5 H 1-0 TOT (W, CS), GW6 A 0-2 LIV (L), GW7 unfinished.
FIXTURES = [
    _fx(1, 1, 1, 14, 2, 0),
    _fx(2, 2, 13, 1, 1, 1),
    _fx(3, 3, 1, 8, 0, 1),
    _fx(4, 4, 11, 1, 1, 3),
    _fx(5, 5, 1, 17, 1, 0),
    _fx(6, 6, 14, 1, 2, 0),
    _fx(7, 7, 1, 13, None, None, finished=False),
    _fx(8, 1, 8, 13, 0, 0),  # another game, not Arsenal's
]


def _bootstrap(fixtures=FIXTURES) -> dict:
    return {
        "teams": [dict(t) for t in TEAMS],
        "events": [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"}],
        "elements": [],
        "_all_fixtures": list(fixtures),
    }


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    mod._clear_results_cache()
    monkeypatch.setattr(mod, "_get_all_fixtures_live", lambda: (_ for _ in ()).throw(AssertionError("network")))
    yield
    mod._clear_results_cache()


# ---------------------------------------------------------------------------
# Four registration sites
# ---------------------------------------------------------------------------

def test_registered_in_tool_registry_with_output_schema():
    spec = TOOL_REGISTRY.get_spec("get_team_results")
    assert spec is GET_TEAM_RESULTS_SPEC
    assert spec.output_schema["properties"]["matches"]["type"] == "array"
    assert "get_team_results" in TOOL_REGISTRY.list_tools()


def test_package_imports_the_module():
    assert "fpl_grounded_assistant.get_team_results" in sys.modules
    assert fpl_grounded_assistant.get_team_results is get_team_results   # package re-exports the function


def test_llm_schema_registered_with_matching_parameters():
    schema = next(s for s in _ALL_SCHEMAS if s.name == "get_team_results")
    assert set(schema.parameters["properties"]) == set(GET_TEAM_RESULTS_SPEC.parameters["properties"])
    assert schema.parameters["required"] == GET_TEAM_RESULTS_SPEC.parameters["required"] == ["team"]
    assert schema.parameters["properties"]["venue"]["enum"] == ["all", "home", "away"]
    assert "local" in schema.description and "get_fixture_outlook" in schema.description


def test_renderer_registered():
    assert "get_team_results" in _RENDERERS


def test_tool_runs_through_the_registry():
    out = TOOL_REGISTRY.run("get_team_results", {"team": "Arsenal", "last_n": 2}, _bootstrap())
    assert out["status"] == "ok"
    assert [m["gameweek"] for m in out["matches"]] == [5, 6]


# ---------------------------------------------------------------------------
# Arithmetic, read off the payload
# ---------------------------------------------------------------------------

def test_default_last_five_all_venues():
    out = get_team_results("Arsenal", _bootstrap())
    assert out["status"] == "ok" and out["source"] == "live"
    assert out["team"] == {"id": 1, "name": "Arsenal", "short_name": "ARS"}
    assert out["played_total"] == 6                      # GW7 unfinished excluded
    assert [m["gameweek"] for m in out["matches"]] == [2, 3, 4, 5, 6]   # oldest first, last 5
    assert [m["result"] for m in out["matches"]] == ["D", "L", "W", "W", "L"]
    assert out["summary"] == {"played": 5, "won": 2, "drawn": 1, "lost": 2, "gf": 5, "ga": 5,
                              "clean_sheets": 1, "avg_gf": 1.0, "avg_ga": 1.0}
    # venue_split: last 5 home = GW1,3,5 (W L W, 3-1, 2 CS); last 5 away = GW2,4,6 (D W L, 4-4)
    assert out["venue_split"]["home"] == {"played": 3, "won": 2, "drawn": 0, "lost": 1, "gf": 3, "ga": 1,
                                          "clean_sheets": 2, "avg_gf": 1.0, "avg_ga": 0.33}
    assert out["venue_split"]["away"] == {"played": 3, "won": 1, "drawn": 1, "lost": 1, "gf": 4, "ga": 4,
                                          "clean_sheets": 0, "avg_gf": 1.33, "avg_ga": 1.33}


def test_match_rows_carry_opponent_and_venue():
    out = get_team_results("Arsenal", _bootstrap(), last_n=1)
    (m,) = out["matches"]
    assert m == {"gameweek": 6, "kickoff_time": "2026-08-16T14:00:00Z", "opponent_id": 14,
                 "opponent_short": "LIV", "opponent_name": "Liverpool", "is_home": False,
                 "venue": "away", "goals_for": 0, "goals_against": 2, "result": "L"}


def test_last_n_applies_after_the_venue_filter():
    out = get_team_results("ARS", _bootstrap(), venue="home", last_n=2)
    assert out["venue"] == "home"
    assert [m["gameweek"] for m in out["matches"]] == [3, 5]
    assert out["summary"]["played"] == 2 and out["summary"]["clean_sheets"] == 1
    # venue_split is still both sides, each its own last 2.
    assert out["venue_split"]["home"] == out["summary"]
    assert out["venue_split"]["away"]["played"] == 2
    assert out["venue_split"]["away"]["gf"] == 3 and out["venue_split"]["away"]["ga"] == 3


def test_away_filter():
    out = get_team_results("Arsenal", _bootstrap(), venue="away", last_n=10)
    assert [m["gameweek"] for m in out["matches"]] == [2, 4, 6]
    assert out["summary"]["won"] == 1


def test_last_n_is_clamped_and_coerced():
    assert get_team_results("Arsenal", _bootstrap(), last_n=0)["last_n"] == 1
    assert get_team_results("Arsenal", _bootstrap(), last_n=99)["last_n"] == mod.MAX_LAST_N
    assert get_team_results("Arsenal", _bootstrap(), last_n="3")["last_n"] == 3
    bad = get_team_results("Arsenal", _bootstrap(), last_n="many")
    assert bad["status"] == "error" and bad["code"] == "invalid_argument"


def test_unknown_venue_is_an_error():
    bad = get_team_results("Arsenal", _bootstrap(), venue="neutral")
    assert bad["status"] == "error" and bad["code"] == "invalid_argument"


def test_fixture_without_both_scores_is_skipped():
    fixtures = FIXTURES + [_fx(9, 8, 1, 8, 2, None, finished=True)]
    out = get_team_results("Arsenal", _bootstrap(fixtures), last_n=10)
    assert 8 not in [m["gameweek"] for m in out["matches"]]


def test_team_with_no_finished_games_returns_empty_ok():
    out = get_team_results("Spurs", _bootstrap([_fx(1, 1, 17, 1, None, None, finished=False)]))
    assert out["status"] == "ok" and out["matches"] == [] and out["played_total"] == 0
    assert out["summary"]["played"] == 0 and out["summary"]["avg_gf"] == 0.0


def test_pure_helpers_agree_with_the_tool():
    rows = build_matches(FIXTURES, 1, TEAMS)
    assert len(rows) == 6
    assert summarize(rows)["gf"] == 7 and summarize(rows)["ga"] == 5


# ---------------------------------------------------------------------------
# Team resolution -- the shared alias resolver
# ---------------------------------------------------------------------------

def test_alias_resolves_through_shared_resolver():
    out = get_team_results("Tottenham", _bootstrap(), last_n=10)   # alias map -> TOT
    assert out["status"] == "ok" and out["team"]["short_name"] == "TOT"
    assert [m["result"] for m in out["matches"]] == ["L"]           # GW5 at Arsenal 0-1


def test_ambiguous_team_reports_candidates():
    out = get_team_results("man", _bootstrap())
    assert out["status"] == "ambiguous" and out["code"] == "ambiguous_team"
    assert {c["short_name"] for c in out["candidates"]} == {"MCI", "MUN"}


def test_unknown_team_is_not_found():
    out = get_team_results("Zzz United", _bootstrap())
    assert out["status"] == "not_found" and out["code"] == "team_not_found" and out["query"] == "Zzz United"


def test_missing_team_name():
    out = get_team_results("", _bootstrap())
    assert out["status"] == "error" and out["code"] == "missing_team_name"


# ---------------------------------------------------------------------------
# Live source: injection, cache, one fetch, failure
# ---------------------------------------------------------------------------

def test_live_fetch_is_called_once_and_cached(monkeypatch):
    calls = []

    def fake():
        calls.append(1)
        return FIXTURES

    monkeypatch.setattr(mod, "_get_all_fixtures_live", fake)
    b = _bootstrap()
    b.pop("_all_fixtures")
    assert get_team_results("Arsenal", b)["played_total"] == 6
    assert get_team_results("Chelsea", b)["played_total"] == 2
    assert calls == [1]


def test_live_fetch_failure_is_a_status_not_a_crash(monkeypatch):
    monkeypatch.setattr(mod, "_get_all_fixtures_live", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    b = _bootstrap()
    b.pop("_all_fixtures")
    out = get_team_results("Arsenal", b)
    assert out["status"] == "error" and out["code"] == "fetch_failed"


def test_live_stamp_reads_the_live_season():
    out = get_team_results("Arsenal", _bootstrap())
    assert out["season"] == "2026-2027"
    prov = out["data_provenance"]
    assert prov["status"] == "current" and prov["is_current"] is True
    assert prov["label"].startswith("Datos: temporada 2026-27")


def test_live_stamp_unverified_when_no_gw1_deadline():
    b = _bootstrap()
    b["events"] = []
    out = get_team_results("Arsenal", b)
    assert out["season"] is None
    assert out["data_provenance"]["status"] == "unverified"
    assert "táctico" not in out["data_provenance"]["label"]


# ---------------------------------------------------------------------------
# Season source: owned store in a temp root
# ---------------------------------------------------------------------------

def _write_season(root, season: str, fixtures, teams, pointer: dict | None):
    pd = pytest.importorskip("pandas")
    d = root / "seasons" / season / "parquet_merged"
    d.mkdir(parents=True)
    pd.DataFrame([{
        "season": season, "fixture_id": f["id"], "event_id": f["event"], "team_h": f["team_h"],
        "team_a": f["team_a"], "team_h_score": f["team_h_score"], "team_a_score": f["team_a_score"],
        "kickoff_time": f["kickoff_time"], "finished": f["finished"],
    } for f in fixtures]).to_parquet(d / "fixtures.parquet")
    pd.DataFrame([{"season": season, "team_id": t["id"], "name": t["name"], "short_name": t["short_name"]}
                  for t in teams]).to_parquet(d / "teams.parquet")
    if pointer is not None:
        (root / "seasons" / season / "_owned_latest.json").write_text(json.dumps(pointer), "utf-8")


# In 2024-2025 Leicester (id 11) was in the league; Man Utd took id 11 in the live bootstrap above.
PAST_TEAMS = [
    {"id": 1, "name": "Arsenal", "short_name": "ARS"},
    {"id": 11, "name": "Leicester", "short_name": "LEI"},
    {"id": 14, "name": "Liverpool", "short_name": "LIV"},
]
PAST_FIXTURES = [
    _fx(1, 36, 11, 1, 0, 2), _fx(2, 37, 14, 11, 3, 1), _fx(3, 38, 11, 14, 2, 2),
]


@pytest.fixture
def owned_root(tmp_path, monkeypatch):
    root = tmp_path / "historical"
    _write_season(root, "2024-2025", PAST_FIXTURES, PAST_TEAMS,
                  {"season": "2024-2025", "merged_at": "2026-06-07T21-19-10Z", "row_counts": {"fixtures": 3}})
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(root))
    return root


def test_past_season_reads_the_owned_store_and_that_seasons_ids(owned_root):
    out = get_team_results("Leicester", _bootstrap(), season="2024-2025", last_n=5)
    assert out["status"] == "ok" and out["source"] == "owned_store"
    assert out["team"] == {"id": 11, "name": "Leicester", "short_name": "LEI"}   # not Man Utd's 11
    assert [m["result"] for m in out["matches"]] == ["L", "L", "D"]
    assert out["summary"]["gf"] == 3 and out["summary"]["ga"] == 7
    assert out["venue_split"]["home"]["played"] == 2 and out["venue_split"]["away"]["played"] == 1


def test_past_season_stamp_is_stale_against_the_live_season(owned_root):
    out = get_team_results("Liverpool", _bootstrap(), season="2024-25")
    prov = out["data_provenance"]
    assert out["season"] == "2024-2025"
    assert prov["status"] == "stale_season" and prov["is_current"] is False
    assert prov["live_season"] == "2026-2027"
    assert prov["label"].startswith("⚠ Datos de 2024-25, no de la temporada en curso (2026-27)")
    assert prov["ingested_at"] == "2026-06-07T21-19-10Z"


@pytest.mark.parametrize("arg", ["2024-2025", "2024-25", "24/25", "2024"])
def test_season_parser_variants(owned_root, arg):
    assert get_team_results("Arsenal", _bootstrap(), season=arg)["season"] == "2024-2025"


def test_previous_sentinel_resolves_the_season_before_current(owned_root, monkeypatch):
    sp = importlib.import_module("fpl_grounded_assistant.get_player_season_points")
    monkeypatch.setattr(sp, "CURRENT_SEASON", "2025-2026")
    assert get_team_results("Arsenal", _bootstrap(), season="previous")["season"] == "2024-2025"
    assert get_team_results("Arsenal", _bootstrap(), season="pasada")["season"] == "2024-2025"


def test_stamp_season_is_read_off_the_pointer_not_the_argument(owned_root):
    """Mutate the pointer: the directory is still 2024-2025, the stamp follows the file."""
    p = owned_root / "seasons" / "2024-2025" / "_owned_latest.json"
    p.write_text(json.dumps({"season": "1999-2000", "merged_at": "x"}), "utf-8")
    out = get_team_results("Arsenal", _bootstrap(), season="2024-2025")
    assert out["season"] == "1999-2000"
    assert out["data_provenance"]["season_label"] == "1999-00"


def test_missing_pointer_stamps_unknown_not_the_argument(owned_root):
    (owned_root / "seasons" / "2024-2025" / "_owned_latest.json").unlink()
    out = get_team_results("Arsenal", _bootstrap(), season="2024-2025")
    assert out["status"] == "ok"
    assert out["season"] is None and out["data_provenance"]["status"] == "unknown"


def test_season_not_stored_names_what_exists(owned_root):
    out = get_team_results("Arsenal", _bootstrap(), season="2019-2020")
    assert out["status"] == "not_found" and out["code"] == "season_not_found"
    assert "2024-2025" in out["message"]


def test_unparseable_season():
    out = get_team_results("Arsenal", _bootstrap(), season="the one with the snow")
    assert out["status"] == "invalid_argument" and out["code"] == "unparseable_season"


def test_relegated_club_is_not_found_live_but_found_in_its_season(owned_root):
    assert get_team_results("Leicester", _bootstrap())["status"] == "not_found"
    assert get_team_results("Leicester", _bootstrap(), season="2024-2025")["status"] == "ok"


# ---------------------------------------------------------------------------
# i95: nothing emitted without a declaration
# ---------------------------------------------------------------------------

def _walk(value, schema, path=""):
    undeclared = []
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for k, v in value.items():
            if k not in props:
                undeclared.append(f"{path}.{k}")
            else:
                undeclared += _walk(v, props[k], f"{path}.{k}")
    elif isinstance(value, list):
        items = schema.get("items") or {}
        for i, v in enumerate(value):
            undeclared += _walk(v, items, f"{path}[{i}]")
    return undeclared


def test_every_emitted_key_is_declared_in_output_schema(owned_root):
    schema = GET_TEAM_RESULTS_SPEC.output_schema
    for out in (
        get_team_results("Arsenal", _bootstrap()),
        get_team_results("Arsenal", _bootstrap(), venue="home", last_n=2),
        get_team_results("Leicester", _bootstrap(), season="2024-2025"),
        get_team_results("man", _bootstrap()),
        get_team_results("Zzz", _bootstrap()),
        get_team_results("Arsenal", _bootstrap(), season="xx"),
    ):
        bad = [p for p in _walk(out, schema) if not p.startswith(".data_provenance.") and not p.startswith(".team.") and not p.startswith(".candidates[")]
        assert bad == [], bad
    for key in ("matches", "candidates"):
        assert schema["properties"][key]["type"] == "array"


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def test_render_ok_lists_matches_summary_split_and_stamp():
    text = render("get_team_results", get_team_results("Arsenal", _bootstrap(), venue="home", last_n=2))
    assert text.startswith("Arsenal — últimos 2 partidos de local:")
    assert "J3 vs CHE 0-1 (L)" in text and "J5 vs TOT 1-0 (W)" in text
    assert "Resumen: 2 PJ, 1G 0E 1P, GF 1 GC 1, 1 porterías a cero" in text
    assert "Local: 2 PJ" in text and "Visitante: 2 PJ" in text
    assert text.rstrip().endswith("Datos: temporada 2026-27 (FPL en vivo)")


def test_render_non_ok_statuses():
    assert "varios equipos" in render("get_team_results", get_team_results("man", _bootstrap())) or \
        "matches several teams" in render("get_team_results", get_team_results("man", _bootstrap()))
    assert "No encontré" in render("get_team_results", get_team_results("Zzz", _bootstrap()))
    assert render("get_team_results", {"status": "error", "code": "fetch_failed", "message": "x"}) == "Error (fetch_failed): x"
    assert render("get_team_results", {}) .startswith("Error (")
