"""
Tests for T2b — get_zonal_weakness / get_zonal_opportunity orchestrator tools.

Integration-level: verifies both tools are registered and runnable via
run_tool against a fixture tactical store (FPL_TACTICAL_ROOT → tmp dir),
that the LLM-facing schemas are in the registry, that team aliases bridge
from FPL bootstrap names to Understat store names, that the store-less path
degrades to missing_context, and that the atomic-tool pattern holds (no
intent mapping, not in SUPPORTED_INTENTS).
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pandas as pd
import pytest

# sys.path bootstrap (mirror fpl_server.py's _SIB pattern) so the full package
# graph imports — zonal_weakness_tool registers in TOOL_REGISTRY on import.
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
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402  (triggers tool self-registration)
from fpl_tool_runner import run_tool  # noqa: E402
from fpl_grounded_assistant.tool_schema_registry import (  # noqa: E402
    TOOL_NAMES,
    get_tool_schema,
)
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    SUPPORTED_INTENTS,
    _TOOL_TO_INTENT,
)


# ---------------------------------------------------------------------------
# Fixture store + bootstrap
# ---------------------------------------------------------------------------

def _row(conceding, shooting, x, y, xg, *, match_id=1, player="Someone"):
    return {
        "season": "2025-2026", "match_id": match_id, "date": "2025-09-01T15:00:00",
        "shooting_team": shooting, "conceding_team": conceding,
        "player": player, "is_home_shot": True, "minute": 10,
        "x": x, "y": y, "xg": xg, "situation": "Open Play",
        "shot_type": "Right Foot", "result": "Saved Shot",
    }


def _store_df() -> pd.DataFrame:
    """Crystal Palace very weak in-box/right; 'Right Poacher' operates there."""
    rows = []
    for _ in range(10):  # >= MIN_PLAYER_SHOTS for the opportunity matcher
        rows.append(_row("Crystal Palace", "Burnley", 0.90, 0.20, 0.10,
                         match_id=1, player="Right Poacher"))
    rows += [
        _row("Aston Villa", "Crystal Palace", 0.90, 0.20, 0.10, match_id=2),
        _row("Burnley", "Aston Villa", 0.90, 0.20, 0.10, match_id=3),
        _row("Sunderland", "Burnley", 0.90, 0.20, 0.10, match_id=4),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def tactical_store(tmp_path, monkeypatch):
    """Point FPL_TACTICAL_ROOT at a tmp store holding the fixture parquet."""
    season_dir = tmp_path / "seasons" / "2025-2026"
    season_dir.mkdir(parents=True)
    _store_df().to_parquet(season_dir / "understat_shots.parquet", index=False)
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def empty_store(tmp_path, monkeypatch):
    """FPL_TACTICAL_ROOT with no parquet at all."""
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    return tmp_path


def _bootstrap() -> dict:
    return {
        "teams": [
            {"id": 1, "name": "Crystal Palace", "short_name": "CRY"},
            {"id": 2, "name": "Aston Villa",    "short_name": "AVL"},
            {"id": 3, "name": "Burnley",        "short_name": "BUR"},
            {"id": 4, "name": "Sunderland",     "short_name": "SUN"},
        ],
        "events": [{"id": 1, "is_current": True}],
    }


# ---------------------------------------------------------------------------
# Registration + schema
# ---------------------------------------------------------------------------

def test_both_tools_have_registry_schemas():
    assert "get_zonal_weakness" in TOOL_NAMES
    assert "get_zonal_opportunity" in TOOL_NAMES
    for name in ("get_zonal_weakness", "get_zonal_opportunity"):
        schema = get_tool_schema(name)
        # descriptions must carry the language-discipline marker
        assert "never buy/sell" in schema.description


def test_atomic_pattern_no_intent_no_classifier():
    # weakness + outlook stay atomic (text-narrated, no intent mapping)
    assert "get_zonal_weakness" not in _TOOL_TO_INTENT
    assert "get_player_zonal_outlook" not in _TOOL_TO_INTENT
    # T4b partial promotion: opportunity is renderable (card) but stays out
    # of the deterministic classifier universe
    assert _TOOL_TO_INTENT["get_zonal_opportunity"] == "zonal_opportunity"
    joined = " ".join(SUPPORTED_INTENTS)
    assert "zonal" not in joined


# ---------------------------------------------------------------------------
# run_tool — happy paths
# ---------------------------------------------------------------------------

def test_run_tool_weakness_ok_shape(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    assert out["team"] == "Crystal Palace"
    assert {"zone", "xga_per_game", "league_avg", "delta_vs_avg", "rank"} <= set(out["zones"][0])
    assert out["weakest_zones"][0]["zone"] == "in-box / right"
    assert out["weakest_zones"][0]["delta_vs_avg"] > 0
    assert isinstance(out["verdict"], str) and out["verdict"]


def test_run_tool_weakness_resolves_alias_via_bootstrap(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "CRY"}, _bootstrap())
    assert out["status"] == "ok"
    assert out["team"] == "Crystal Palace"


def test_run_tool_opportunity_ok_shape(tactical_store):
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    assert out["opponent"] == "Crystal Palace"
    zones = {o["zone"]: o for o in out["opportunities"]}
    assert "in-box / right" in zones
    assert "Right Poacher" in zones["in-box / right"]["players"]


# ---------------------------------------------------------------------------
# T4b — wrapper enrichment of the exploiter table (team_short / position)
# ---------------------------------------------------------------------------

def _bootstrap_with_elements() -> dict:
    """Bootstrap whose elements match 'Right Poacher' by full name."""
    bs = _bootstrap()
    bs["elements"] = [
        {"first_name": "Right", "second_name": "Poacher",
         "web_name": "Poacher", "element_type": 3},
    ]
    return bs


def test_run_tool_opportunity_exploiters_enriched_matched_player(tactical_store):
    out = run_tool(
        "get_zonal_opportunity", {"opponent": "Crystal Palace"},
        _bootstrap_with_elements(),
    )
    assert out["status"] == "ok"
    exploiters = out["exploiters"]
    assert exploiters, "fixture store should yield at least one exploiter"
    top = exploiters[0]
    assert top["rank"] == 1
    assert top["player"] == "Right Poacher"
    assert top["web_name"] == "Poacher"          # FPL join hit
    assert top["position"] == "MID"
    assert top["team_short"] == "BUR"            # inverted Understat bridge
    assert top["fit_score"] == 10.0              # best cross of this answer


def test_run_tool_opportunity_exploiters_unmatched_player_degrades(tactical_store):
    # No elements in bootstrap → the fragile name join misses; the player is
    # kept with the store name and an empty position, never dropped.
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    top = out["exploiters"][0]
    assert top["player"] == "Right Poacher"
    assert top["web_name"] == "Right Poacher"
    assert top["position"] == ""
    assert top["team_short"] == "BUR"


def test_run_tool_opportunity_card_fields_present(tactical_store):
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    assert [z["lateral"] for z in out["zones"]] == ["left", "central", "right"]
    for z in out["zones"]:
        assert z["opportunity_level"] in ("opp", "warm", "cool")
    assert out["weakness_label"] == "Débil dentro del área"
    assert "penalty_xga_per_game" in out["penalty_context"]
    assert isinstance(out["verdict"], str) and out["verdict"]
    # language discipline: opportunity framing only
    for banned in ("ficha", "vende", "compra"):
        assert banned not in out["verdict"].lower()


# ---------------------------------------------------------------------------
# run_tool — degraded paths (never raise into the orchestrator)
# ---------------------------------------------------------------------------

def test_run_tool_weakness_not_found(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "Real Madrid"}, _bootstrap())
    assert out["status"] == "not_found"
    assert "message" in out


def test_run_tool_missing_context_when_no_store(empty_store):
    out = run_tool("get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "missing_context"
    assert "message" in out
    out2 = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out2["status"] == "missing_context"


def test_run_tool_blank_team_is_not_found(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "  "}, _bootstrap())
    assert out["status"] == "not_found"
    # a missing REQUIRED arg is rejected by the runner's schema validation
    # before the handler runs — still a structured status, never a raise
    out2 = run_tool("get_zonal_opportunity", {}, _bootstrap())
    assert out2["status"] == "error"


# ---------------------------------------------------------------------------
# get_player_zonal_outlook (T-player)
# ---------------------------------------------------------------------------

def _bootstrap_with_fixtures() -> dict:
    """Bootstrap with a current GW and team_fixtures: Burnley (id 3, home of
    'Right Poacher' in the fixture store) faces Crystal Palace in GW1 and
    Sunderland in GW2."""
    bs = _bootstrap()
    bs["events"] = [{"id": 1, "is_current": True}]
    bs["team_fixtures"] = {
        3: [
            {"gameweek": 1, "opponent_team": 1, "is_home": True},
            {"gameweek": 2, "opponent_team": 4, "is_home": False},
            {"gameweek": 9, "opponent_team": 2, "is_home": True},  # outside horizon
        ],
    }
    return bs


class TestPlayerZonalOutlook:
    def test_run_tool_outlook_ok_shape(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook",
            {"player": "Right Poacher", "horizon": 2},
            _bootstrap_with_fixtures(),
        )
        assert out["status"] == "ok"
        assert out["player"] == "Right Poacher"
        assert out["team"] == "Burnley"
        gws = [e["gameweek"] for e in out["outlook"]]
        assert gws == [1, 2]  # GW9 fixture is outside the horizon
        by_gw = {e["gameweek"]: e for e in out["outlook"]}
        assert by_gw[1]["opponent"] == "Crystal Palace"
        assert by_gw[1]["status"] == "favorable"
        assert by_gw[1]["matches"][0]["zone"] == "in-box / right"
        assert isinstance(out["verdict"], str) and out["verdict"]

    def test_run_tool_outlook_horizon_clamped(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook",
            {"player": "Right Poacher", "horizon": 99},
            _bootstrap_with_fixtures(),
        )
        assert out["status"] == "ok"  # clamped to MAX, not an error

    def test_run_tool_outlook_player_not_found(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook", {"player": "Nobody"}, _bootstrap_with_fixtures()
        )
        assert out["status"] == "not_found"
        assert "message" in out

    def test_run_tool_outlook_missing_fixtures(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook", {"player": "Right Poacher"}, _bootstrap()
        )
        assert out["status"] == "missing_context"
        assert "message" in out

    def test_run_tool_outlook_missing_store(self, empty_store):
        out = run_tool(
            "get_player_zonal_outlook",
            {"player": "Right Poacher"},
            _bootstrap_with_fixtures(),
        )
        assert out["status"] == "missing_context"


# ---------------------------------------------------------------------------
# T4b — DefensiveZonesMeta extraction (zonal_opportunity renderable intent)
# ---------------------------------------------------------------------------

class TestDefensiveZonesMeta:
    def _ok_output(self, tactical_store) -> dict:
        return run_tool(
            "get_zonal_opportunity", {"opponent": "Crystal Palace"},
            _bootstrap_with_elements(),
        )

    def test_meta_extracted_on_ok(self, tactical_store):
        from fpl_grounded_assistant.final_response import _extract_structured_meta

        meta = _extract_structured_meta(
            "zonal_opportunity", self._ok_output(tactical_store), "ok"
        )
        zo = meta["zonal_opportunity"]
        assert zo is not None
        assert zo.opponent == "Crystal Palace"
        assert zo.weakness_label == "Débil dentro del área"
        assert len(zo.zones) == 3
        assert [z.lateral for z in zo.zones] == ["left", "central", "right"]
        assert all(z.opportunity_level in ("opp", "warm", "cool") for z in zo.zones)
        assert zo.exploiters and zo.exploiters[0].rank == 1
        assert zo.exploiters[0].web_name == "Poacher"
        assert zo.exploiters[0].team_short == "BUR"
        assert zo.exploiters[0].position == "MID"
        assert zo.exploiters[0].fit_score == 10.0
        assert zo.ai_active is True
        # every other structured field stays None on this intent
        assert meta["differential"] is None and meta["comparison"] is None

    def test_meta_none_on_non_ok_outcome(self, tactical_store):
        from fpl_grounded_assistant.final_response import _extract_structured_meta

        out = run_tool("get_zonal_opportunity", {"opponent": "Real Madrid"}, _bootstrap())
        assert out["status"] == "not_found"
        meta = _extract_structured_meta("zonal_opportunity", out, "not_found")
        assert meta["zonal_opportunity"] is None

    def test_meta_none_on_missing_context(self, empty_store):
        from fpl_grounded_assistant.final_response import _extract_structured_meta

        out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
        assert out["status"] == "missing_context"
        meta = _extract_structured_meta("zonal_opportunity", out, "missing_context")
        assert meta["zonal_opportunity"] is None

    def test_meta_none_on_pre_enrichment_payload(self):
        # A stale payload without the T4b "zones" field must not render a
        # half-empty card.
        from fpl_grounded_assistant.final_response import (
            _extract_zonal_opportunity_meta,
        )

        legacy = {"status": "ok", "opponent": "Crystal Palace", "opportunities": []}
        assert _extract_zonal_opportunity_meta(legacy) is None

    def test_finalresponse_has_zonal_opportunity_field(self):
        import dataclasses

        from fpl_grounded_assistant.final_response import FinalResponse

        names = {f.name for f in dataclasses.fields(FinalResponse)}
        assert "zonal_opportunity" in names
