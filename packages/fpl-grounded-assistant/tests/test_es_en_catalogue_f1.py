"""
tests/test_es_en_catalogue_f1.py
==================================
Language track, Phase F1: the ES/EN string catalogue.
Phase F2 (captain/status renderers + closed vocabularies) reuses this same
harness and file rather than duplicating it.

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
I.  resolve_player / get_player_summary — status_label
J.  get_injury_list — 3 group headers (not 5 status values; "other" is
    suspended+unavailable composite)
K.  get_captain_score / rank_captain_candidates — tier, set-piece, reasons
L.  explainer.py — captain_reason catalogue coverage + the "en" default
    that protects comparison.py/transfer_advisor.py (tier-2b) from a
    silent language flip
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
# A2. difficulty_label — F1 commit 3
# ===========================================================================
# The closed 3-value enum shared by get_transfer_suggestion and
# get_player_fixture_run (transfer_suggestion.py's _difficulty_label() and
# player_fixture_run.py's FDR-context builder use the same thresholds).

class TestDifficultyLabelTranslation:
    def test_all_three_values_both_locales(self):
        from fpl_grounded_assistant.renderer import _localized_difficulty_label
        assert _localized_difficulty_label("easy", "en") == "easy"
        assert _localized_difficulty_label("easy", "es") == "fácil"
        assert _localized_difficulty_label("moderate", "en") == "moderate"
        assert _localized_difficulty_label("moderate", "es") == "moderado"
        assert _localized_difficulty_label("hard", "en") == "hard"
        assert _localized_difficulty_label("hard", "es") == "difícil"

    def test_unmapped_value_falls_back_to_raw_token(self):
        # The enum is closed today, but the thresholds that produce it live
        # in the tool, not here. If a build ever adds a fourth band without
        # a matching catalogue entry, the raw token must still render (a
        # visible, debuggable "extreme" beats a silently blank field).
        from fpl_grounded_assistant.renderer import _localized_difficulty_label
        assert _localized_difficulty_label("extreme", "es") == "extreme"
        assert _localized_difficulty_label("extreme", "en") == "extreme"
        assert _localized_difficulty_label("", "es") == ""

    def test_hard_wired_into_transfer_suggestion_pick_line(self):
        from fpl_grounded_assistant.renderer import render
        payload = {
            "status": "ok", "position": "FWD", "horizon": 5,
            "picks": [{"rank": 1, "web_name": "X", "team_short": "Y", "position": "FWD",
                       "now_cost_m": 5.0, "form": 1.0, "avg_fdr": 4.5,
                       "difficulty_label": "hard", "ownership": 1.0}],
        }
        assert "(difícil)" in render("get_transfer_suggestion", payload, locale="es")
        assert "(hard)" in render("get_transfer_suggestion", payload, locale="en")

    def test_hard_wired_into_fixture_run_fdr_context(self):
        from fpl_grounded_assistant.renderer import render
        payload = {
            "status": "ok", "web_name": "X", "team_short": "Y", "position": "DEF",
            "horizon": 1, "fixtures": [{"gameweek": 1, "opponent_short": "Z", "is_home": True, "difficulty": 5}],
            "team_fdr_context": {"avg_fdr": 5.0, "difficulty_label": "hard", "gw_from": 1, "gw_to": 1},
        }
        assert "racha difícil" in render("get_player_fixture_run", payload, locale="es")
        assert "a hard run" in render("get_player_fixture_run", payload, locale="en")


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

    def test_pick_line_translates_form_owned_and_difficulty_label(self):
        # F1 commit 3: difficulty_label is an adjective inside the sentence
        # ("(fácil)"), not a cross-referenced identifier — it translates
        # along with "form"/"owned" now, unlike ranking_basis/objective/
        # position which stay raw.
        from fpl_grounded_assistant.renderer import render
        es = render("get_transfer_suggestion", _TRANSFER_OK, locale="es")
        en = render("get_transfer_suggestion", _TRANSFER_OK, locale="en")
        assert "forma 7.2" in es and "propiedad" in es
        assert "form 7.2" in en and "owned" in en
        assert "(fácil)" in es and "easy" not in es
        assert "(easy)" in en

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
        # F1 commit 3: difficulty_label translates along with the sentence.
        assert "tiene una racha moderado" in es
        assert "have a moderate run" in en

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
# F2. get_my_squad — new i39 renderer, catalogue-native from day one
# ===========================================================================

_MY_SQUAD_OK = {
    "status": "ok", "team_id": 12345, "gw": 3,
    "players": [
        {
            "id": 1, "web_name": "Raya", "team_short": "ARS", "position": "GKP",
            "now_cost": 50, "status": "Available", "chance_of_playing_this_round": None,
            "form": 4.0, "total_points": 20, "is_captain": False, "is_vice_captain": False,
            "multiplier": 1, "pick_position": 1, "is_starter": True,
        },
        {
            "id": 2, "web_name": "Haaland", "team_short": "MCI", "position": "FWD",
            "now_cost": 145, "status": "Available", "chance_of_playing_this_round": None,
            "form": 8.0, "total_points": 60, "is_captain": True, "is_vice_captain": False,
            "multiplier": 2, "pick_position": 2, "is_starter": True,
        },
        {
            "id": 3, "web_name": "Salah", "team_short": "LIV", "position": "MID",
            "now_cost": 130, "status": "Doubtful", "chance_of_playing_this_round": 75,
            "form": 6.5, "total_points": 55, "is_captain": False, "is_vice_captain": True,
            "multiplier": 1, "pick_position": 3, "is_starter": True,
        },
        {
            "id": 4, "web_name": "Sub One", "team_short": "WHU", "position": "DEF",
            "now_cost": 45, "status": "Available", "chance_of_playing_this_round": None,
            "form": 2.0, "total_points": 10, "is_captain": False, "is_vice_captain": False,
            "multiplier": 1, "pick_position": 12, "is_starter": False,
        },
    ],
    "summary": {"gw_points": 58, "total_points": 210, "bank": 5, "active_chip": "bench_boost"},
}


class TestMySquadRenderer:
    def test_es_header_and_starters_bench_split(self):
        from fpl_grounded_assistant.renderer import render
        text = render("get_my_squad", _MY_SQUAD_OK, locale="es")
        assert "**Tu equipo — GW3** (chip activo: Bench Boost)" in text
        assert "Titulares:" in text
        assert "Banquillo:" in text
        # Starters precede bench in the rendered order.
        assert text.index("Titulares:") < text.index("Banquillo:")
        assert "  Sub One (WHU, DEF)" in text

    def test_en_header_and_labels_translate(self):
        from fpl_grounded_assistant.renderer import render
        text = render("get_my_squad", _MY_SQUAD_OK, locale="en")
        assert "**Your squad — GW3** (active chip: Bench Boost)" in text
        assert "Starting XI:" in text
        assert "Bench:" in text

    def test_captain_and_vice_captain_tags(self):
        from fpl_grounded_assistant.renderer import render
        text = render("get_my_squad", _MY_SQUAD_OK, locale="es")
        assert "Haaland (MCI, FWD)" in text
        haaland_line = next(l for l in text.splitlines() if "Haaland" in l)
        salah_line = next(l for l in text.splitlines() if "Salah" in l)
        assert haaland_line.endswith("(C)")
        assert salah_line.endswith("(VC)")

    def test_status_label_localized(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_my_squad", _MY_SQUAD_OK, locale="es")
        en = render("get_my_squad", _MY_SQUAD_OK, locale="en")
        assert "Dudoso" in es
        assert "Doubtful" in en

    def test_summary_line_bank_and_points(self):
        from fpl_grounded_assistant.renderer import render
        text = render("get_my_squad", _MY_SQUAD_OK, locale="es")
        assert "GW3: 58pts | Total: 210pts | En el banco: £0.5m" in text

    def test_no_chip_clause_when_no_active_chip(self):
        from fpl_grounded_assistant.renderer import render
        payload = dict(_MY_SQUAD_OK)
        payload["summary"] = dict(_MY_SQUAD_OK["summary"], active_chip=None)
        text = render("get_my_squad", payload, locale="es")
        assert "chip activo" not in text
        assert "**Tu equipo — GW3**" in text

    def test_no_team_connected_localized(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "no_team_connected", "code": "no_team_connected"}
        es = render("get_my_squad", payload, locale="es")
        en = render("get_my_squad", payload, locale="en")
        assert "Conecta tu equipo" in es
        assert "Connect your team" in en

    def test_team_not_found_localized_with_id(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "not_found", "code": "team_not_found", "team_id": 999}
        es = render("get_my_squad", payload, locale="es")
        en = render("get_my_squad", payload, locale="en")
        assert "999" in es and "No encontré" in es
        assert "999" in en and "couldn't find" in en

    def test_network_error_localized(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "error", "code": "network_error", "message": "boom"}
        es = render("get_my_squad", payload, locale="es")
        en = render("get_my_squad", payload, locale="en")
        # The catalogue text is used, not the tool's raw internal message.
        assert "boom" not in es and "boom" not in en
        assert "No pude obtener" in es
        assert "couldn't fetch" in en

    def test_invalid_gw_localized(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "error", "code": "invalid_gw"}
        es = render("get_my_squad", payload, locale="es")
        en = render("get_my_squad", payload, locale="en")
        assert "jornada debe estar entre 1 y 38" in es
        assert "Gameweek must be between 1 and 38" in en

    def test_unknown_error_code_falls_back_to_generic(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "error", "code": "tool_exception", "message": "kaput"}
        text = render("get_my_squad", payload, locale="es")
        assert text == "Error (tool_exception): kaput"

    def test_gw_clamped_note_shown_localized(self):
        from fpl_grounded_assistant.renderer import render
        payload = {**_MY_SQUAD_OK, "requested_gw": 4, "gw_clamped": True}
        es = render("get_my_squad", payload, locale="es")
        en = render("get_my_squad", payload, locale="en")
        assert "GW4" in es and "aún no fue publicada" in es
        assert "GW4" in en and "aren't published yet" in en

    def test_no_clamp_note_when_not_clamped(self):
        from fpl_grounded_assistant.renderer import render
        text = render("get_my_squad", _MY_SQUAD_OK, locale="es")
        assert "aún no fue publicada" not in text


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

        assert len(_RENDERERS) == 38
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
        assert len(texts) == 112

    @pytest.mark.parametrize("locale", ["es", "en"])
    def test_no_leaked_catalogue_keys(self, locale, audit_entries):
        from fpl_grounded_assistant.catalogue import _CATALOGUE

        texts, errors = self._render_all(locale, audit_entries)
        assert errors == []
        leaks = [(name, text) for name in _CATALOGUE for text in texts if name in text]
        assert leaks == []


# ===========================================================================
# I. resolve_player / get_player_summary — status_label
# ===========================================================================
# status_label is already an English word by the time it reaches the
# renderer (fpl_query_tools._STATUS_LABELS builds it upstream from the raw
# "a"/"d"/"i"/"s"/"u" code) -- translation keys off that English value.

_RESOLVE_OK = {
    "status": "ok", "web_name": "Raya", "name": "David Raya Martín",
    "team": "Arsenal", "team_short": "ARS", "position": "GKP",
    "status_label": "Available", "resolved_via": "web_name", "query": "Raya",
}

_SUMMARY_OK = {
    "status": "ok", "web_name": "Raya", "name": "David Raya Martín",
    "team": "Arsenal", "team_short": "ARS", "position": "GKP",
    "cost_m": 6.0, "status_label": "Available", "selected_by_percent": "34.6",
    "resolved_via": "web_name", "query": "Raya",
    "total_points": 162, "form": "0.0", "minutes": 3330,
}


class TestStatusLabelTranslation:
    def test_all_five_values_both_locales(self):
        from fpl_grounded_assistant.renderer import _localized_status_label
        pairs = [
            ("Available", "Disponible"), ("Doubtful", "Dudoso"),
            ("Injured", "Lesionado"), ("Suspended", "Suspendido"),
            ("Unavailable", "No disponible"),
        ]
        for en_val, es_val in pairs:
            assert _localized_status_label(en_val, "en") == en_val
            assert _localized_status_label(en_val, "es") == es_val

    def test_unmapped_value_falls_back_to_raw_token(self):
        from fpl_grounded_assistant.renderer import _localized_status_label
        assert _localized_status_label("Retired", "es") == "Retired"
        assert _localized_status_label("", "es") == ""


class TestResolvePlayerRenderer:
    def test_ok_translates_status_and_connective_prose(self):
        from fpl_grounded_assistant.renderer import render
        es = render("resolve_player", _RESOLVE_OK, locale="es")
        en = render("resolve_player", _RESOLVE_OK, locale="en")
        assert es == (
            "Raya (David Raya Martín) juega en Arsenal (ARS) como GKP. "
            "Estado: Disponible. [Resuelto vía: web_name]"
        )
        assert en == (
            "Raya (David Raya Martín) plays for Arsenal (ARS) as a GKP. "
            "Status: Available. [Resolved via: web_name]"
        )

    def test_position_and_codes_stay_raw_in_spanish(self):
        # GKP/ARS are cross-referenced identifiers -- must not translate.
        from fpl_grounded_assistant.renderer import render
        es = render("resolve_player", _RESOLVE_OK, locale="es")
        assert "GKP" in es and "ARS" in es

    def test_ambiguous_and_not_found_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        amb = render("resolve_player", {"status": "ambiguous", "query": "Silva"}, locale="es")
        assert "Varios jugadores comparten el nombre 'Silva'" in amb
        nf = render("resolve_player", {"status": "not_found", "query": "Zzz"}, locale="en")
        assert "No player found matching 'Zzz'" in nf


class TestPlayerSummaryRenderer:
    def test_ok_translates_status_and_extras(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_player_summary", _SUMMARY_OK, locale="es")
        en = render("get_player_summary", _SUMMARY_OK, locale="en")
        assert es == (
            "Raya (David Raya Martín) | Arsenal (ARS) | GKP | £6.0m | "
            "34.6% de propiedad | Estado: Disponible. "
            "Pts totales: 162 | Forma: 0.0 | Min: 3330."
        )
        assert en == (
            "Raya (David Raya Martín) | Arsenal (ARS) | GKP | £6.0m | "
            "34.6% ownership | Status: Available. "
            "Total pts: 162 | Form: 0.0 | Mins: 3330."
        )

    def test_ambiguous_has_no_examples_clause_unlike_resolve_player(self):
        # Pre-existing distinction preserved: get_player_summary's ambiguous
        # text never had the "(e.g. 'Who is ...')" clause resolve_player has.
        from fpl_grounded_assistant.renderer import render
        es = render("get_player_summary", {"status": "ambiguous", "query": "Silva"}, locale="es")
        assert "por ejemplo" not in es


# ===========================================================================
# J. get_injury_list
# ===========================================================================

_INJURY_OK = {
    "status": "ok", "total": 2,
    "injured": [{"web_name": "Saliba", "team_short": "ARS", "position": "DEF"}],
    "doubtful": [{"web_name": "Mount", "team_short": "MUN", "position": "MID", "chance_of_playing": 75}],
    "other": [],
}


class TestInjuryListRenderer:
    def test_headers_translate_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_injury_list", _INJURY_OK, locale="es")
        en = render("get_injury_list", _INJURY_OK, locale="en")
        assert es == "Lesionados: Saliba (ARS, DEF) | Dudosos: Mount (MUN, MID) 75%."
        assert en == "Injured: Saliba (ARS, DEF) | Doubtful: Mount (MUN, MID) 75%."

    def test_suspended_header_is_a_composite_not_five_values(self):
        # "other" covers both suspended ("s") and unavailable ("u") -- one
        # header, not a per-status-value translation.
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "ok", "total": 1, "injured": [], "doubtful": [],
                   "other": [{"web_name": "Digne", "team_short": "AVL"}]}
        es = render("get_injury_list", payload, locale="es")
        en = render("get_injury_list", payload, locale="en")
        assert es == "Suspendidos/no disponibles: Digne (AVL)."
        assert en == "Suspended/unavailable: Digne (AVL)."

    def test_none_fallback_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "ok", "total": 0, "injured": [], "doubtful": [], "other": []}
        assert render("get_injury_list", payload, locale="es") == "No hay problemas de lesiones en los datos actuales."
        assert render("get_injury_list", payload, locale="en") == "No injury concerns in the current bootstrap."


# ===========================================================================
# K. get_captain_score / rank_captain_candidates
# ===========================================================================

_CAPTAIN_OK = {
    "status": "ok", "web_name": "Haaland", "team_short": "MCI",
    "captain_score": 36.59, "tier": "differential",
    "role_signals": {"set_piece_notes": ["penalty_taker_1"]},
    "score_inputs": {"form": 0.0, "fixture_difficulty": 3, "xgi_per_90": 0.858551, "minutes_risk": 0.0},
}

_RANK_OK = {
    "status": "ok",
    "ranked_candidates": [
        {"status": "ok", "rank": 1, "web_name": "Haaland", "team_short": "MCI",
         "captain_score": 36.59, "tier": "differential",
         "role_signals": {"set_piece_notes": ["penalty_taker_1"]},
         "score_inputs": {"form": 0.0, "fixture_difficulty": 3, "xgi_per_90": 0.858551, "minutes_risk": 0.0}},
        {"status": "ok", "rank": 3, "web_name": "Raya", "team_short": "ARS",
         "captain_score": 28.02, "tier": "low_confidence",
         "role_signals": {"set_piece_notes": []},
         "score_inputs": {"form": 0.0, "fixture_difficulty": 3, "xgi_per_90": 0.01, "minutes_risk": 0.0}},
    ],
}


class TestCaptainScoreRenderer:
    def test_ok_translates_tier_and_reasons(self):
        from fpl_grounded_assistant.renderer import render
        es = render("get_captain_score", _CAPTAIN_OK, locale="es")
        en = render("get_captain_score", _CAPTAIN_OK, locale="en")
        assert es == (
            "Haaland (MCI) — Diferencial [36.59]. Pateador de penales; "
            "Mala forma reciente; Alta participación ofensiva; "
            "Minutos asegurados; Perfil diferencial de alto potencial."
        )
        assert en == (
            "Haaland (MCI) — Differential [36.59]. Penalty taker; "
            "Weak recent form; High attacking involvement; "
            "Secure minutes; High-upside differential profile."
        )

    def test_ambiguous_and_not_found_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        amb = render("get_captain_score", {"status": "ambiguous", "query": "Silva"}, locale="es")
        assert "Varios jugadores comparten el nombre 'Silva'" in amb
        nf = render("get_captain_score", {"status": "not_found", "query": "Zzz"}, locale="en")
        assert "No player found matching 'Zzz'" in nf


class TestRankCaptainCandidatesRenderer:
    def test_ok_translates_tier_short_setpiece_and_reasons(self):
        from fpl_grounded_assistant.renderer import render
        es = render("rank_captain_candidates", _RANK_OK, locale="es")
        en = render("rank_captain_candidates", _RANK_OK, locale="en")
        assert es == (
            "1. Haaland (MCI) [dif] 36.59 · pateador de penales — "
            "Mala forma reciente; Alta participación ofensiva\n"
            "3. Raya (ARS) [baj] 28.02 — "
            "Mala forma reciente; Baja participación ofensiva"
        )
        assert en == (
            "1. Haaland (MCI) [diff] 36.59 · penalty taker — "
            "Weak recent form; High attacking involvement\n"
            "3. Raya (ARS) [low] 28.02 — "
            "Weak recent form; Weak attacking process"
        )

    def test_short_codes_never_longer_than_english(self):
        # "upside" is a documented, deliberate exception (catalogue.py):
        # "pot" (potencial) is one character longer than "up" -- there is no
        # equally-short natural Spanish abbreviation. Every other tier code
        # must match or beat the English length.
        from fpl_grounded_assistant.renderer import _TIER_SHORT_KEYS
        from fpl_grounded_assistant.catalogue import t
        allowed_overage = {"upside": 1}
        for tier, key in _TIER_SHORT_KEYS.items():
            en_len = len(t(key, "en"))
            es_len = len(t(key, "es"))
            max_len = en_len + allowed_overage.get(tier, 0)
            assert es_len <= max_len, f"{tier}: es short code longer than allowed ({es_len} > {max_len})"

    def test_none_fallback_both_locales(self):
        from fpl_grounded_assistant.renderer import render
        payload = {"status": "ok", "ranked_candidates": []}
        assert render("rank_captain_candidates", payload, locale="es") == "No se pudo puntuar a ningún candidato a capitán."
        assert render("rank_captain_candidates", payload, locale="en") == "No captain candidates could be scored."


# ===========================================================================
# L. explainer.py — captain_reason coverage + tier-2b default protection
# ===========================================================================

class TestCaptainReasonCoverage:
    """Pins all 15 reason phrases in both locales, driven from the source
    constants (not hand-copied), so a 16th phrase added later without a
    catalogue entry fails loudly here rather than leaking English.
    """

    def test_all_role_reasons_both_locales(self):
        from fpl_grounded_assistant.explainer import _ROLE_REASON
        from fpl_grounded_assistant.catalogue import t
        assert len(_ROLE_REASON) == 4
        for note, key in _ROLE_REASON.items():
            en = t(key, "en")
            es = t(key, "es")
            assert en and es and en != es

    def test_all_non_role_reasons_both_locales(self):
        from fpl_grounded_assistant.catalogue import t
        non_role_keys = [
            "captain_reason.form_strong", "captain_reason.form_weak",
            "captain_reason.fixture_favorable", "captain_reason.fixture_tough",
            "captain_reason.xgi_high", "captain_reason.xgi_low",
            "captain_reason.minutes_secure", "captain_reason.minutes_rotation_risk",
            "captain_reason.minutes_significant_risk",
            "captain_reason.tier_differential", "captain_reason.tier_low_confidence",
        ]
        assert len(non_role_keys) == 11  # 4 role + 11 = 15 total, matching explainer.py's 12 append sites
        for key in non_role_keys:
            en = t(key, "en")
            es = t(key, "es")
            assert en and es and en != es

    def test_compact_exclusion_is_locale_independent(self):
        # _COMPACT_EXCLUDED filters by catalogue key, not translated text --
        # this must hold for both locales, not just the locale it was
        # written against.
        from fpl_grounded_assistant.explainer import explain_captain_compact
        out_role = {
            "status": "ok",
            "role_signals": {"set_piece_notes": ["penalty_taker_1"]},
            "score_inputs": {},
            "tier": "differential",
        }
        for locale in ("en", "es"):
            compact = explain_captain_compact(out_role, locale=locale, max_reasons=5)
            # Role reason and tier-summary reason both excluded regardless
            # of locale -- only neutral score_inputs produce no extra reasons,
            # so compact should be empty here.
            assert compact == []


class TestExplainCaptainDefaultLocale:
    """comparison.py and transfer_advisor.py call explain_captain()/
    explain_captain_compact() with no locale argument and splice the result
    into their own (tier-2b, out-of-scope) English recommendation prose --
    the default must stay English, not follow DEFAULT_LOCALE="es".
    """

    def test_default_is_english_not_default_locale(self):
        from fpl_grounded_assistant.explainer import explain_captain
        from fpl_grounded_assistant.locale_types import DEFAULT_LOCALE
        assert DEFAULT_LOCALE == "es"  # sanity: this is the trap this test guards
        out = {
            "status": "ok", "tier": "differential",
            "role_signals": {"set_piece_notes": ["penalty_taker_1"]},
            "score_inputs": {"form": 2.0, "fixture_difficulty": 3, "xgi_per_90": 0.3, "minutes_risk": 0.0},
        }
        assert explain_captain(out) == explain_captain(out, locale="en")
        assert explain_captain(out) != explain_captain(out, locale="es")

    def test_comparison_reasons_field_stays_english_by_default(self):
        # Exercises the real out-of-scope call site directly.
        from fpl_grounded_assistant.explainer import explain_captain
        raw = {
            "status": "ok", "tier": "safe",
            "role_signals": {"set_piece_notes": []},
            "score_inputs": {"form": 8.0, "fixture_difficulty": 1, "xgi_per_90": 0.6, "minutes_risk": 0.0},
        }
        reasons = explain_captain(raw)  # comparison.py's exact call shape
        assert "Strong recent form" in reasons
        assert "Buena forma reciente" not in reasons


# ===========================================================================
# M. Spanish register — tuteo, not voseo (product-voice fix, no phase letter
#    of its own; a follow-up to F2, scanning the whole catalogue)
# ===========================================================================

class TestSpanishRegisterIsTuteo:
    """The product uses tuteo ("usa", "revisa") -- never voseo ("usá",
    "revisá"). See the "Register" bullet in catalogue.py's module docstring
    for why this is a deliberate, enforced decision rather than a per-string
    habit.

    The detector matches Spanish words ending in a stressed a/e/i (bare, or
    followed by a bare "s") -- the shape of voseo imperative/present forms
    ("usá", "tenés", "vivís"). That shape collides with a few ordinary,
    non-voseo Spanish words already in the catalogue: 1st-person preterite
    verbs ending in "-é" ("encontré" = "I found", not a 2nd-person form at
    all), and short non-verb function words ("más", "sí"). Those are the
    only three surface forms the current catalogue actually produces --
    confirmed by running the scan below against every "es" value and reading
    every hit, not by guessing a list up front. A real voseo word is not on
    this list; do not add anything here to make a real hit disappear.
    """

    _ALLOWED_NON_VOSEO_HITS = {
        "encontré",  # 1st-person preterite ("no encontré..." = "I didn't find...")
        "más",       # adverb "more", not a verb form
        "sí",        # "yes", not a verb form
    }

    def _voseo_hits(self):
        import re
        from fpl_grounded_assistant.catalogue import _CATALOGUE

        pattern = re.compile(r"\b[a-záéíóúñA-ZÁÉÍÓÚÑ]+(?:á|é|í|ás|és|ís)\b")
        allowed = {w.lower() for w in self._ALLOWED_NON_VOSEO_HITS}
        hits = []
        for key, pair in _CATALOGUE.items():
            es_text = pair.get("es", "")
            for m in pattern.finditer(es_text):
                word = m.group(0)
                if word.lower() not in allowed:
                    hits.append((key, word))
        return hits

    def test_no_voseo_verb_forms_in_catalogue(self):
        hits = self._voseo_hits()
        assert hits == [], f"voseo verb form(s) found (tuteo required): {hits}"

    def test_known_non_voseo_words_still_present(self):
        # Guards against the allowlist silently swallowing a real regression:
        # if these words ever disappear from the catalogue, the allowlist
        # entries protecting them would too, and the point of naming them
        # explicitly here is that removal should be a visible, deliberate
        # edit -- not just have the corresponding line quietly deleted.
        from fpl_grounded_assistant.catalogue import _CATALOGUE
        joined_es = " ".join(pair.get("es", "") for pair in _CATALOGUE.values())
        assert "encontré" in joined_es
        assert "más" in joined_es
        assert "Sí" in joined_es or "sí" in joined_es

    def test_mutation_reintroducing_voseo_is_caught(self):
        # Proves the detector actually fires: a synthetic catalogue entry
        # using a real voseo form ("usá") must be flagged, not silently
        # absorbed by the allowlist or missed by the pattern.
        import re
        pattern = re.compile(r"\b[a-záéíóúñA-ZÁÉÍÓÚÑ]+(?:á|é|í|ás|és|ís)\b")
        mutated = {"fake.key": {"en": "use", "es": "Usá el nombre completo."}}
        allowed = {w.lower() for w in self._ALLOWED_NON_VOSEO_HITS}
        hits = [
            (key, m.group(0))
            for key, pair in mutated.items()
            for m in pattern.finditer(pair.get("es", ""))
            if m.group(0).lower() not in allowed
        ]
        assert hits == [("fake.key", "Usá")]
