"""
Per-90 / rate rankings need a minutes floor under DESC, and "contribuciones
defensivas" is a TOTAL unless the phrase says per 90.

Prod bug 2026-10-23: "top 10 de jugadores por contribuciones defensivas" was
answered with DC/90 of 180, 90, 90, 60... for players with 1-5 minutes
(Latibeaudiere: 1 minute, DC 2 -> 180/90). The data was real, the ranking
meaningless. Two causes, both pinned here:

1. the minutes floor only existed under order="asc";
2. no TOTAL defensive_contribution metric, so the bare phrase could only reach
   the per-90 rate.

All data is synthetic; nothing here touches the network or a paid provider.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.atomic_tool_cards import compose_rank_players_card
from fpl_grounded_assistant.rank_players_by_metric import (
    _METRIC_ALIASES,
    is_rate_metric,
    per_90_minutes_floor,
    rank_players_by_metric,
)
from fpl_grounded_assistant.renderer import _render_rank_players_by_metric


def _el(i, name, minutes, dc, *, ppg="2.0", form="3.0", etype=2):
    per90 = round(dc * 90 / minutes, 2) if minutes else 0.0
    return {
        "id": i, "first_name": name, "second_name": name, "web_name": name,
        "team": 1, "team_code": 3, "element_type": etype, "status": "a",
        "now_cost": 50, "selected_by_percent": "1.0",
        "minutes": minutes,
        "defensive_contribution": dc,
        "defensive_contribution_per_90": str(per90),
        "points_per_game": ppg, "form": form, "total_points": 10,
    }


def _bootstrap(finished_gws: int = 8, total_gws: int = 38):
    return {
        "elements": [
            _el(1, "Cameo", 1, 2, ppg="12.0", form="9.0"),     # DC/90 = 180
            _el(2, "Sub", 5, 1, ppg="9.0"),                     # DC/90 = 18
            _el(3, "Regular", 700, 112),                        # DC/90 = 14.4
            _el(4, "Starter", 720, 100),                        # DC/90 = 12.5
            _el(5, "Fringe", 300, 50),                          # DC/90 = 15.0
            _el(6, "Janelt", 760, 89),                          # total leader, rate 10.5
        ],
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS", "code": 3}],
        "element_types": [{"id": 2, "singular_name_short": "DEF"}],
        "events": [
            {"id": gw, "finished": gw <= finished_gws}
            for gw in range(1, total_gws + 1)
        ],
    }


def _names(result):
    return [p["web_name"] for p in result["ranked"]]


# --- (1) the bug: desc per-90 ranked 1-minute players ------------------------

def test_desc_per_90_excludes_the_one_minute_player():
    r = rank_players_by_metric("dc/90", bootstrap=_bootstrap())
    assert r["metric"] == "defensive_contribution_per_90"
    assert "Cameo" not in _names(r) and "Sub" not in _names(r)
    assert _names(r)[0] == "Fringe"          # 15.0/90 over 300 min
    assert r["min_minutes_filter"] == 270    # reported, not silent


def test_falsifier_without_the_floor_the_cameo_tops_the_list(monkeypatch):
    """Zeroing the floor reproduces the prod answer (180, 18, ...), so the
    assertion above is the floor's doing and not data luck."""
    import importlib
    mod = importlib.import_module("fpl_grounded_assistant.rank_players_by_metric")  # the package re-exports the function under the module name
    monkeypatch.setattr(mod, "per_90_minutes_floor", lambda bootstrap: 0)
    r = mod.rank_players_by_metric("dc/90", bootstrap=_bootstrap())
    assert _names(r)[:2] == ["Cameo", "Sub"]
    assert r["ranked"][0]["metric_value"] == 180.0


def test_desc_ppg_also_floored_but_form_is_not():
    ppg = rank_players_by_metric("ppg", bootstrap=_bootstrap())
    assert "Cameo" not in _names(ppg) and ppg["min_minutes_filter"] == 270
    form = rank_players_by_metric("form", bootstrap=_bootstrap())
    assert form["min_minutes_filter"] == 0 and _names(form)[0] == "Cameo"


@pytest.mark.parametrize("metric", [
    "expected_goals_per_90", "expected_assists_per_90",
    "expected_goal_involvements_per_90", "saves_per_90", "clean_sheets_per_90",
    "defensive_contribution_per_90", "points_per_game",
])
def test_every_rate_metric_gets_the_floor(metric):
    assert is_rate_metric(metric)
    r = rank_players_by_metric(metric, bootstrap=_bootstrap())
    assert r["min_minutes_filter"] == 270


@pytest.mark.parametrize("metric", [
    "total_points", "minutes", "now_cost", "form", "defensive_contribution",
    "goals_scored", "expected_goals", "selected_by_percent",
])
def test_totals_and_non_rates_get_no_floor_under_desc(metric):
    assert not is_rate_metric(metric)
    r = rank_players_by_metric(metric, bootstrap=_bootstrap())
    assert r["min_minutes_filter"] == 0


def test_floor_never_lowers_a_larger_caller_value():
    r = rank_players_by_metric("dc/90", min_minutes=900, bootstrap=_bootstrap())
    assert r["min_minutes_filter"] == 900 and r["ranked"] == []


def test_asc_keeps_todays_sixty_minute_floor():
    r = rank_players_by_metric("dc/90", order="asc", bootstrap=_bootstrap())
    assert r["min_minutes_filter"] == 60
    # 60, not 270: Fringe/Regular/Starter/Janelt are in, Cameo/Sub are out
    assert set(_names(r)) == {"Fringe", "Regular", "Starter", "Janelt"}
    assert rank_players_by_metric("now_cost", order="asc",
                                  bootstrap=_bootstrap())["min_minutes_filter"] == 0
    assert rank_players_by_metric("minutes", order="asc",
                                  bootstrap=_bootstrap())["min_minutes_filter"] == 0


# --- floor scales with the season -------------------------------------------

@pytest.mark.parametrize("finished,expected", [
    (0, 270),     # progress unknown (pre-season / no events): plain 270
    (1, 45),      # GW1: 270 is unreachable; half of the 90 minutes available
    (3, 135),     # GW3: half of 270
    (6, 270),     # three full matches becomes reachable
    (8, 270),
    (10, 270),    # 30% of 900 == 270: the two rules meet
    (20, 540),
    (38, 1026),   # 30% of 3420
])
def test_floor_scales_with_finished_gameweeks(finished, expected):
    assert per_90_minutes_floor(_bootstrap(finished)) == expected
    r = rank_players_by_metric("dc/90", bootstrap=_bootstrap(finished))
    assert r["min_minutes_filter"] == expected


def test_floor_without_any_bootstrap_events_is_the_plain_base():
    assert per_90_minutes_floor(None) == 270
    assert per_90_minutes_floor({"elements": []}) == 270


def test_late_season_floor_drops_the_fringe_player():
    early = rank_players_by_metric("dc/90", bootstrap=_bootstrap(8))
    late = rank_players_by_metric("dc/90", bootstrap=_bootstrap(30))   # floor 810
    assert "Fringe" in _names(early)
    assert "Fringe" not in _names(late)


# --- (2) total vs per-90 ----------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "contribuciones defensivas", "contribución defensiva", "contribucion defensiva",
    "contribuciones defensivas totales", "defensive contributions",
    "defensive contribution", "defensive_contribution", "defcon", "DEFCON",
    "dc", "DC", "DC total", "total dc",
])
def test_bare_phrase_resolves_to_the_total(phrase):
    r = rank_players_by_metric(phrase, bootstrap=_bootstrap())
    assert r["status"] == "ok" and r["metric"] == "defensive_contribution", phrase
    assert r["min_minutes_filter"] == 0
    assert _names(r)[0] == "Regular"
    assert r["ranked"][0]["metric_value"] == 112   # the total, not a rate


@pytest.mark.parametrize("phrase", [
    "contribuciones defensivas por 90", "contribucion defensiva por 90",
    "contribuciones defensivas por 90 minutos", "defensive contributions per 90",
    "defensive contribution per 90", "defensive contributions per 90 minutes",
    "dc/90", "DC/90", "dc per 90", "dc por 90", "dc90", "dc_per_90",
    "defcon per 90", "defcon por 90", "defcon/90", "defcon90",
    "defensive_contribution_per_90",
])
def test_per_90_phrasing_resolves_to_the_rate(phrase):
    r = rank_players_by_metric(phrase, bootstrap=_bootstrap())
    assert r["status"] == "ok" and r["metric"] == "defensive_contribution_per_90", phrase
    assert r["min_minutes_filter"] == 270


def test_the_real_question_gets_the_real_answer_shape():
    """Total top by total; per-90 top only among players with the minutes."""
    total = rank_players_by_metric("contribuciones defensivas", bootstrap=_bootstrap())
    assert _names(total) == ["Regular", "Starter", "Janelt", "Fringe", "Cameo", "Sub"]
    rate = rank_players_by_metric("contribuciones defensivas por 90", bootstrap=_bootstrap())
    assert _names(rate) == ["Fringe", "Regular", "Starter", "Janelt"]


# --- relaxation audit: what newly resolves must be right, or refuse ----------

@pytest.mark.parametrize("phrase", [
    "contribuciones defensivas por noventa",
    "contribuciones defensivas por partido",
    "defensive contributions per game",
    "defensive contributions per minute",
    "contribuciones defensivas por minuto",
    "contribuciones defensivas promedio",
])
def test_rate_wording_is_refused_not_answered_with_the_total(phrase):
    r = rank_players_by_metric(phrase, bootstrap=_bootstrap())
    assert r["status"] == "invalid_argument" and r["code"] == "unknown_metric", phrase


@pytest.mark.parametrize("phrase", ["dc points", "dc puntos", "defcon points", "defcon puntos"])
def test_dc_points_no_longer_silently_answers_with_total_points(phrase):
    """Before: 'dc' was dropped and the answer was TOTAL POINTS, status ok. A tie
    between 'dc' and 'points' is now a visible unknown_metric."""
    r = rank_players_by_metric(phrase, bootstrap=_bootstrap())
    assert r["status"] == "invalid_argument" and r["code"] == "unknown_metric"


@pytest.mark.parametrize("phrase,field", [
    ("goles", "goals_scored"), ("goles en contra", "goals_conceded"),
    ("goles esperados", "expected_goals"), ("goles esperados por 90", "expected_goals_per_90"),
    ("xg", "expected_goals"), ("xg/90", "expected_goals_per_90"),
    ("puntos", "total_points"), ("puntos por partido", "points_per_game"),
    ("ppg", "points_per_game"), ("paradas", "saves"), ("paradas por 90", "saves_per_90"),
    ("porterias a cero", "clean_sheets"), ("minutos", "minutes"),
    ("precio", "now_cost"), ("bps", "bps"), ("ict", "ict_index"),
])
def test_neighbouring_spanish_phrases_resolve_as_before(phrase, field):
    assert rank_players_by_metric(phrase, bootstrap=None)["metric"] == field


def test_existing_per_90_aliases_keep_their_target():
    for key in ("dc/90", "dc_per_90", "defensive contribution per 90",
                "contribucion defensiva por 90", "defensive_contribution_per_90"):
        assert _METRIC_ALIASES[key] == "defensive_contribution_per_90"


# --- the caveat still reaches the user --------------------------------------

def test_floor_is_visible_in_text_and_card():
    r = rank_players_by_metric("dc/90", bootstrap=_bootstrap())
    assert "min. minutos: 270" in _render_rank_players_by_metric(r)
    card = compose_rank_players_card(r)
    assert card is not None and "min. minutos: 270" in (card.subtitle or "")
    total = rank_players_by_metric("contribuciones defensivas", bootstrap=_bootstrap())
    assert "min. minutos" not in _render_rank_players_by_metric(total)
    assert compose_rank_players_card(total).columns[-1].header == "DC"
