"""
tests/test_es_en_catalogue_f1.py
==================================
Language track, Phase F1: the ES/EN string catalogue.

Test suites
-----------
A.  catalogue.t() — lookup, formatting, and failure behaviour
B.  get_transfer_suggestion — the highest-traffic in-scope renderer
C.  get_player_fixture_run
D.  compare_players — mostly tier-2; only 3 strings are renderer-owned
E.  get_player_snapshot — already-Spanish renderer, EN added
F.  select_players_within_budget — already-Spanish renderer, EN added
G.  harness._unrecognised_message
H.  Deterministic render harness — 110 fixed renders (35 real tool outputs
    + 37 renderers x {}/error + 1 unknown-tool), asserting zero tracebacks
    and zero leaked catalogue keys in either locale. This is the same
    check used to verify the F1 commits by hand; it is pinned here as a
    permanent regression test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ===========================================================================
# A. catalogue.t() — lookup, formatting, and failure behaviour
# ===========================================================================

class TestCatalogueLookup:
    def test_known_key_both_locales(self):
        from fpl_grounded_assistant.catalogue import t
        assert t("compare_players.ok_fallback", "en") == "Comparison completed."
        assert t("compare_players.ok_fallback", "es") == "Comparación completada."

    def test_default_locale_is_spanish(self):
        from fpl_grounded_assistant.catalogue import t
        assert t("compare_players.ok_fallback") == t("compare_players.ok_fallback", "es")

    def test_format_params_substituted(self):
        from fpl_grounded_assistant.catalogue import t
        text = t("compare_players.not_found_fallback", "en", player="Haaland")
        assert text == "Could not resolve player 'Haaland'."

    def test_unknown_key_raises_under_test(self):
        from fpl_grounded_assistant.catalogue import t, CatalogueKeyError
        with pytest.raises(CatalogueKeyError):
            t("no.such.key", "es")

    def test_missing_format_param_raises_under_test(self):
        from fpl_grounded_assistant.catalogue import t, CatalogueKeyError
        with pytest.raises(CatalogueKeyError):
            t("compare_players.not_found_fallback", "en")  # missing `player`

    def test_every_key_has_both_locales(self):
        from fpl_grounded_assistant.catalogue import _CATALOGUE
        missing = [k for k, v in _CATALOGUE.items() if set(v) != {"es", "en"}]
        assert missing == []

    def test_no_key_value_is_empty(self):
        # A blank template would render as invisible missing content.
        from fpl_grounded_assistant.catalogue import _CATALOGUE
        blanks = [
            (k, loc) for k, per_locale in _CATALOGUE.items()
            for loc, text in per_locale.items() if not text.strip()
        ]
        assert blanks == []


# ===========================================================================
# B. get_transfer_suggestion
# ===========================================================================

_TRANSFER_OK = {
    "status": "ok",
    "position": "MID",
    "team_short": None,
    "max_price": 8.0,
    "horizon": 5,
    "picks": [
        {"rank": 1, "web_name": "Palmer", "team_short": "CHE", "position": "MID",
         "now_cost_m": 6.5, "form": 7.2, "avg_fdr": 2.8, "difficulty_label": "easy",
         "ownership": 45.1},
    ],
}


class TestTransferSuggestionRenderer:
    def test_header_translates_position_and_connective_prose(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_transfer_suggestion", _TRANSFER_OK, locale="es")
        en = render("get_transfer_suggestion", _TRANSFER_OK, locale="en")
        assert "mediocampistas" in es and "próximas 5 jornadas" in es
        assert "midfielders" in en and "next 5 GWs" in en

    def test_price_clause_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_transfer_suggestion", _TRANSFER_OK, locale="es")
        en = render("get_transfer_suggestion", _TRANSFER_OK, locale="en")
        assert "por debajo de £8.0m" in es
        assert "under £8.0m" in en

    def test_pick_line_translates_form_and_owned_not_difficulty_label(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_transfer_suggestion", _TRANSFER_OK, locale="es")
        en = render("get_transfer_suggestion", _TRANSFER_OK, locale="en")
        assert "forma 7.2" in es and "propiedad" in es
        assert "form 7.2" in en and "owned" in en
        # tier-2: difficulty_label is never translated, in either locale.
        assert "(easy)" in es and "(easy)" in en

    def test_no_picks_suffix_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        payload = {**_TRANSFER_OK, "picks": []}
        assert render("get_transfer_suggestion", payload, locale="es").endswith("Ninguno encontrado.")
        assert render("get_transfer_suggestion", payload, locale="en").endswith("None found.")

    def test_not_found_status_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "not_found", "team_query": "Nowhereton"}
        es = render("get_transfer_suggestion", payload, locale="es")
        en = render("get_transfer_suggestion", payload, locale="en")
        assert "No encontré ningún club" in es and "Nowhereton" in es
        assert "No club matching" in en and "Nowhereton" in en

    def test_missing_context_fallback_only_fires_absent_payload_message(self):
        from fpl_grounded_assistant.renderer import render
        # Payload message always wins (tier-2) — this is the fallback-only path.
        no_message = {"status": "missing_context"}
        assert render("get_transfer_suggestion", no_message, locale="en") == "Player data not available."
        with_message = {"status": "missing_context", "message": "custom payload text"}
        assert render("get_transfer_suggestion", with_message, locale="en") == "custom payload text"


# ===========================================================================
# C. get_player_fixture_run
# ===========================================================================

_FIXTURE_RUN_OK = {
    "status": "ok",
    "web_name": "Salah",
    "team_short": "LIV",
    "position": "MID",
    "horizon": 2,
    "current_gameweek": 10,
    "fixtures": [
        {"gameweek": 10, "opponent_short": "BOU", "is_home": True, "difficulty": 2},
        {"gameweek": 11, "opponent_short": "MCI", "is_home": False, "difficulty": 4},
    ],
    "team_fdr_context": {
        "avg_fdr": 3.0, "difficulty_label": "moderate", "gw_from": 10, "gw_to": 11,
    },
}


class TestPlayerFixtureRunRenderer:
    def test_gw_tokens_unchanged_across_locales(self):
        # Established convention elsewhere in renderer.py: GW{n} stays GW{n}
        # in Spanish text too (see _render_get_gameweek_context).
        from fpl_grounded_assistant.renderer import render
        es = render("get_player_fixture_run", _FIXTURE_RUN_OK, locale="es")
        en = render("get_player_fixture_run", _FIXTURE_RUN_OK, locale="en")
        assert "GW10" in es and "GW11" in es
        assert "GW10" in en and "GW11" in en

    def test_connective_prose_differs(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_player_fixture_run", _FIXTURE_RUN_OK, locale="es")
        en = render("get_player_fixture_run", _FIXTURE_RUN_OK, locale="en")
        assert "próximos 2 partidos desde GW10" in es
        assert "next 2 fixtures from GW10" in en
        assert "tiene una racha moderate" in es
        assert "have a moderate run" in en

    def test_difficulty_label_never_translated(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_player_fixture_run", _FIXTURE_RUN_OK, locale="es")
        en = render("get_player_fixture_run", _FIXTURE_RUN_OK, locale="en")
        assert "moderate" in es and "moderate" in en

    def test_not_found_and_missing_context_fallbacks(self):
        from fpl_grounded_assistant.renderer import render
        assert render("get_player_fixture_run", {"status": "not_found"}, locale="es") == "Jugador no encontrado."
        assert render("get_player_fixture_run", {"status": "not_found"}, locale="en") == "Player not found."
        assert render("get_player_fixture_run", {"status": "missing_context"}, locale="es") == "Calendario de partidos no disponible."
        assert render("get_player_fixture_run", {"status": "missing_context"}, locale="en") == "Fixture schedule not available."


# ===========================================================================
# D. compare_players — mostly tier-2
# ===========================================================================

class TestComparePlayersRenderer:
    def test_recommendation_payload_text_ignores_locale(self):
        # The "ok" text is the tool's own `recommendation` field (tier-2) —
        # localizing this renderer cannot and must not change it.
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "ok", "recommendation": "Haaland (9.1) edges Salah (8.4) — narrow margin (0.7)."}
        es = render("compare_players", payload, locale="es")
        en = render("compare_players", payload, locale="en")
        assert es == en == payload["recommendation"]

    def test_ok_fallback_when_no_recommendation(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "ok", "recommendation": ""}
        assert render("compare_players", payload, locale="es") == "Comparación completada."
        assert render("compare_players", payload, locale="en") == "Comparison completed."

    def test_not_found_fallback_only_when_payload_has_no_message(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "not_found", "error_player": "Zzz"}
        assert render("compare_players", payload, locale="es") == "No pude identificar al jugador 'Zzz'."
        assert render("compare_players", payload, locale="en") == "Could not resolve player 'Zzz'."


# ===========================================================================
# E. get_player_snapshot — already-Spanish renderer, EN added
# ===========================================================================

_SNAPSHOT_OK = {
    "status": "ok",
    "player": {
        "web_name": "Haaland", "team_short": "MCI", "position": "FWD",
        "now_cost": 145, "selected_by_percent": 52.3, "status": "a",
        "form": 8.0, "total_points": 180, "points_per_game": 6.0,
        "expected_goals": 1.5, "expected_assists": 0.2,
        "expected_goal_involvements": 1.7, "ict_index": 12.0,
        "minutes_played_season": 2400,
    },
}


class TestPlayerSnapshotRenderer:
    def test_es_output_unchanged_from_pre_f1(self):
        # Regression pin: this renderer was already fully Spanish before
        # F1; its ES output must not move.
        from fpl_grounded_assistant.renderer import render
        text = render("get_player_snapshot", _SNAPSHOT_OK, locale="es")
        assert text == (
            "**Haaland** (MCI, FWD)\n"
            "  Precio: £14.5m | Propiedad: 52.3% | Estado: a\n"
            "  Pts totales: 180 | PPG: 6.0 | Forma: 8.0\n"
            "  xG: 1.50 | xA: 0.20 | xGI: 1.70 | ICT: 12.0\n"
            "  Minutos: 2400"
        )

    def test_en_output_translates_labels(self):
        from fpl_grounded_assistant.renderer import render
        text = render("get_player_snapshot", _SNAPSHOT_OK, locale="en")
        assert text == (
            "**Haaland** (MCI, FWD)\n"
            "  Price: £14.5m | Owned: 52.3% | Status: a\n"
            "  Total pts: 180 | PPG: 6.0 | Form: 8.0\n"
            "  xG: 1.50 | xA: 0.20 | xGI: 1.70 | ICT: 12.0\n"
            "  Minutes: 2400"
        )

    def test_ambiguous_rank_word_fixed_in_spanish(self):
        # Intentional F1 fix: the Spanish ambiguous-candidate line used to
        # say "[rank N]" (a leaked English word); it now says "[puesto N]".
        from fpl_grounded_assistant.renderer import render
        payload = {
            "status": "ambiguous", "query": "Johnson",
            "candidates": [{"web_name": "Johnson", "team_short": "CHE", "position": "MID", "match_rank": 1}],
        }
        es = render("get_player_snapshot", payload, locale="es")
        en = render("get_player_snapshot", payload, locale="en")
        assert "[puesto 1]" in es and "[rank 1]" not in es
        assert "[rank 1]" in en


# ===========================================================================
# F. select_players_within_budget — already-Spanish renderer, EN added
# ===========================================================================

_SELECT_OK = {
    "status": "ok", "position": "MID", "objective": "total_points",
    "ranking_basis": "prior_season_carryover", "count": 1,
    "selection": [{"web_name": "Palmer", "team_short": "CHE", "price": 6.5, "objective_value": 210}],
    "selection_cost": 6.5, "budget": 10.0, "remaining": 3.5,
    "completion": {"slots_left": 1, "exists": True, "cheapest_fill_cost": 3.5, "witness_total_cost": 10.0},
}


class TestSelectPlayersRenderer:
    def test_es_output_unchanged_from_pre_f1(self):
        from fpl_grounded_assistant.renderer import render
        text = render("select_players_within_budget", _SELECT_OK, locale="es")
        assert "1 MID por total_points (base: prior_season_carryover):" in text
        assert "Jugador          | Club | Precio | Valor" in text
        assert "Coste de la selección: 6.5m de 10.0m — queda 3.5m para los 1 huecos restantes." in text
        assert "Cabe: existe un 15 legal" in text

    def test_en_output_translates_header_and_lines(self):
        from fpl_grounded_assistant.renderer import render
        text = render("select_players_within_budget", _SELECT_OK, locale="en")
        assert "1 MID by total_points (basis: prior_season_carryover):" in text
        assert "Player           | Club | Price  | Value" in text
        assert "Selection cost: 6.5m of 10.0m — 3.5m left for the 1 remaining slots." in text
        assert "Fits: a legal 15 exists" in text

    def test_infeasible_fallback_only_when_payload_has_no_message(self):
        from fpl_grounded_assistant.renderer import render
        assert render("select_players_within_budget", {"status": "infeasible"}, locale="es") == "No hay ninguna selección legal con esas restricciones."
        assert render("select_players_within_budget", {"status": "infeasible"}, locale="en") == "No legal selection exists under these constraints."


# ===========================================================================
# G. harness._unrecognised_message
# ===========================================================================

class TestHarnessUnrecognisedMessage:
    def test_localized_both_ways(self):
        from fpl_grounded_assistant.harness import _unrecognised_message
        es = _unrecognised_message("es")
        en = _unrecognised_message("en")
        assert es != en
        assert "could not be mapped" in en
        assert "no pude relacionar" in es.lower()

    def test_default_is_spanish(self):
        from fpl_grounded_assistant.harness import _unrecognised_message
        assert _unrecognised_message() == _unrecognised_message("es")


# ===========================================================================
# H. Deterministic render harness (pinned as a permanent regression test)
# ===========================================================================

_AUDIT_PATH = Path(__file__).resolve().parents[3] / "field-notes" / "artifacts" / "agentic-loop-tool-audit-results.json"


@pytest.fixture(scope="module")
def audit_entries():
    assert _AUDIT_PATH.exists(), f"audit artifact not found at {_AUDIT_PATH}"
    data = json.loads(_AUDIT_PATH.read_text(encoding="utf-8"))
    assert len(data) == 35
    return data


class TestDeterministicRenderHarness:
    """Mirrors the manual F1 verification harness so it survives as a test.

    Renders 110 fixed (tool_name, payload) pairs per locale and asserts:
    zero exceptions, zero leaked catalogue keys, exactly 110 outputs.
    A harness that swallows exceptions can report two identical tracebacks
    as "identical" -- so every render is wrapped individually and any
    failure is collected and asserted on explicitly, never silently
    absorbed into the text comparison.
    """

    def _render_all(self, locale, audit_entries):
        from fpl_grounded_assistant.renderer import render, _RENDERERS

        errors: list[str] = []
        texts: list[str] = []

        def safe(tool_name, payload):
            try:
                texts.append(render(tool_name, payload, locale=locale))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{tool_name}: {exc!r}")

        for item in audit_entries:
            safe(item["tool"], item["output"])

        assert len(_RENDERERS) == 37
        error_payload = {"status": "error", "code": "harness_synthetic_error", "message": "synthetic error payload"}
        for tool_name in sorted(_RENDERERS):
            safe(tool_name, {})
            safe(tool_name, error_payload)

        safe("not_a_real_tool_xyz", {"code": "unknown_tool", "message": "no renderer for this tool"})

        return texts, errors

    @pytest.mark.parametrize("locale", ["es", "en"])
    def test_zero_errors_and_full_coverage(self, locale, audit_entries):
        texts, errors = self._render_all(locale, audit_entries)
        assert errors == [], f"{len(errors)} render(s) raised: {errors[:3]}"
        assert len(texts) == 110

    @pytest.mark.parametrize("locale", ["es", "en"])
    def test_no_leaked_catalogue_keys(self, locale, audit_entries):
        from fpl_grounded_assistant.catalogue import _CATALOGUE

        texts, errors = self._render_all(locale, audit_entries)
        assert errors == []
        leaks = [(name, text) for name in _CATALOGUE for text in texts if name in text]
        assert leaks == []
