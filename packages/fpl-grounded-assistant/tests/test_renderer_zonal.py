"""
Tests for the T-zonal text renderers (hotfix: "No renderer for tool" in prod).

Covers _render_get_zonal_weakness / _render_get_zonal_opportunity for every
status the tools emit (ok / not_found / missing_context / generic error) and
a registry-coverage guard so a future atomic tool cannot ship without a
renderer again.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os
import sys as _sys

# Load renderer + tool_schema_registry directly from their files, bypassing
# fpl_grounded_assistant/__init__.py (repo test convention). Both are
# stdlib-only modules, so they load standalone.
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG_DIR = _os.path.join(_os.path.dirname(_HERE), "fpl_grounded_assistant")


def _load(name: str):
    spec = _ilu.spec_from_file_location(name, _os.path.join(_PKG_DIR, f"{name}.py"))
    mod = _ilu.module_from_spec(spec)
    # dataclass decorators resolve annotations via sys.modules[cls.__module__],
    # so the module must be registered before exec_module runs.
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


renderer = _load("renderer")
tool_schema_registry = _load("tool_schema_registry")

render = renderer.render
_RENDERERS = renderer._RENDERERS


# ---------------------------------------------------------------------------
# Sample payloads (real tool return shapes — see zonal_weakness.py)
# ---------------------------------------------------------------------------

WEAKNESS_OK = {
    "status": "ok",
    "team": "Crystal Palace",
    "zones": [],
    "weakest_zones": [
        {"zone": "in-box / left", "xga_per_game": 0.134, "league_avg": 0.079,
         "delta_vs_avg": 0.055, "rank": 1},
        {"zone": "in-box / central", "xga_per_game": 1.176, "league_avg": 1.159,
         "delta_vs_avg": 0.018, "rank": 9},
    ],
    "penalty_context": {"penalty_xga": 5.3282, "penalty_xga_per_game": 0.1402},
    "verdict": (
        "Crystal Palace concede por encima de la media dentro del área "
        "por su costado derecho."
    ),
}

OPPORTUNITY_OK = {
    "status": "ok",
    "opponent": "Crystal Palace",
    "opportunities": [
        {"zone": "in-box / left", "delta_vs_avg": 0.055,
         "players": ["Bukayo Saka", "Jarrod Bowen", "Mohamed Salah"]},
    ],
}


# ---------------------------------------------------------------------------
# get_zonal_weakness renderer
# ---------------------------------------------------------------------------

class TestRenderZonalWeakness:
    def test_ok_leads_with_verdict_and_lists_zones(self):
        text = render("get_zonal_weakness", WEAKNESS_OK)
        assert text.startswith(WEAKNESS_OK["verdict"])
        assert "in-box / left" in text
        assert "0.134" in text and "0.079" in text and "+0.055" in text
        assert "penaltis" in text and "0.140" in text
        assert "No renderer" not in text

    def test_not_found(self):
        out = {"status": "not_found", "team": "Real Madrid",
               "message": "No zonal data for 'Real Madrid' in the tactical store."}
        text = render("get_zonal_weakness", out)
        assert "Real Madrid" in text
        assert "No renderer" not in text

    def test_missing_context(self):
        out = {"status": "missing_context", "team": "Crystal Palace",
               "message": "Tactical (Understat zonal) store not available on this deployment."}
        text = render("get_zonal_weakness", out)
        assert text == out["message"]

    def test_missing_context_default_message(self):
        text = render("get_zonal_weakness", {"status": "missing_context"})
        assert "no disponibles" in text

    def test_generic_error_fallback(self):
        text = render("get_zonal_weakness",
                      {"status": "error", "code": "boom", "message": "kaput"})
        assert text == "Error (boom): kaput"


# ---------------------------------------------------------------------------
# get_zonal_opportunity renderer
# ---------------------------------------------------------------------------

class TestRenderZonalOpportunity:
    def test_ok_lists_zones_and_players(self):
        text = render("get_zonal_opportunity", OPPORTUNITY_OK)
        assert "Crystal Palace" in text
        assert "in-box / left" in text
        assert "+0.055" in text
        assert "Bukayo Saka" in text and "Mohamed Salah" in text
        assert "No renderer" not in text

    def test_ok_with_no_opportunities(self):
        text = render("get_zonal_opportunity",
                      {"status": "ok", "opponent": "Arsenal", "opportunities": []})
        assert "Arsenal" in text
        assert "no concede por encima de la media" in text

    def test_not_found(self):
        out = {"status": "not_found", "opponent": "Nadie FC",
               "message": "No zonal data for 'Nadie FC' in the tactical store."}
        text = render("get_zonal_opportunity", out)
        assert "Nadie FC" in text
        assert "No renderer" not in text

    def test_missing_context(self):
        text = render("get_zonal_opportunity", {"status": "missing_context"})
        assert "no disponibles" in text

    def test_generic_error_fallback(self):
        text = render("get_zonal_opportunity",
                      {"status": "error", "code": "boom", "message": "kaput"})
        assert text == "Error (boom): kaput"


OUTLOOK_OK = {
    "status": "ok",
    "player": "Bukayo Saka",
    "team": "Arsenal",
    "player_zones": [{"zone": "in-box / left", "share": 0.62}],
    "outlook": [
        {"gameweek": 24, "opponent": "Sunderland", "is_home": False,
         "status": "favorable",
         "matches": [{"zone": "in-box / left", "delta_vs_avg": 0.044,
                      "player_share": 0.62}]},
        {"gameweek": 25, "opponent": "Chelsea", "is_home": True,
         "status": "neutral", "matches": []},
        {"gameweek": 26, "opponent": "Promoted FC", "is_home": True,
         "status": "no_data", "matches": []},
    ],
    "verdict": (
        "Bukayo Saka genera su xG justo en zonas donde el rival concede por "
        "encima de la media — cruce favorable en J24 (Sunderland)."
    ),
}


class TestRenderPlayerZonalOutlook:
    def test_ok_full_report(self):
        text = render("get_player_zonal_outlook", OUTLOOK_OK)
        assert text.startswith(OUTLOOK_OK["verdict"])
        assert "in-box / left (62% de su xG)" in text
        assert "J24 vs Sunderland (fuera): favorable" in text
        assert "+0.044" in text and "62% del xG de Bukayo Saka" in text
        assert "J25 vs Chelsea (casa): sin cruce destacado" in text
        assert "J26 vs Promoted FC (casa): sin datos zonales del rival" in text
        assert "No renderer" not in text

    def test_not_found(self):
        out = {"status": "not_found", "player": "Nobody", "message": "No shot profile for 'Nobody'."}
        assert render("get_player_zonal_outlook", out) == out["message"]

    def test_ambiguous_lists_candidates(self):
        out = {"status": "ambiguous", "player": "Silva",
               "candidates": ["Bernardo Silva", "Fábio Silva"]}
        text = render("get_player_zonal_outlook", out)
        assert "Bernardo Silva" in text and "Fábio Silva" in text
        assert "especifica" in text

    def test_missing_context_default(self):
        text = render("get_player_zonal_outlook", {"status": "missing_context"})
        assert "no disponibles" in text

    def test_generic_error_fallback(self):
        text = render("get_player_zonal_outlook",
                      {"status": "error", "code": "boom", "message": "kaput"})
        assert text == "Error (boom): kaput"


# ---------------------------------------------------------------------------
# Coverage guard — every orchestrator-callable tool must have a renderer
# ---------------------------------------------------------------------------

#: Tools rendered through the intent pipeline (cards) rather than _RENDERERS.
#: Currently empty — every _ALL_SCHEMAS tool is text-rendered. Add names here
#: ONLY with a comment pointing at their card renderer.
_KNOWN_INTENT_RENDERED: frozenset[str] = frozenset()


class TestRendererCoverage:
    def test_every_schema_tool_has_a_renderer(self):
        schema_names = {s.name for s in tool_schema_registry._ALL_SCHEMAS}
        missing = schema_names - set(_RENDERERS) - _KNOWN_INTENT_RENDERED
        assert not missing, (
            f"Tools in _ALL_SCHEMAS without a text renderer: {sorted(missing)}. "
            f"Register them in renderer._RENDERERS (or document them in "
            f"_KNOWN_INTENT_RENDERED) — otherwise the orchestrator surfaces "
            f"\"No renderer for tool\" as final_text in prod."
        )
