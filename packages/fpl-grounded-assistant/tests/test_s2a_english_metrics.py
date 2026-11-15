"""
S2a: English multi-word metric phrases resolve to the field the words name, and a
per-game / per-minute rate that no bootstrap field carries is refused, not answered
with the season total.

Before this change "expected goals" answered with goals_scored (the one-token alias
"goals" matched and "expected" was dropped), "goals per game" answered with the season
goals, and "clean sheets" with the per-90 rate by prefix. Every case below resolves
through ``rank_players_by_metric`` with ``bootstrap=None``, which returns right after
resolution, so no network or provider is involved.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.rank_players_by_metric import (
    _METRIC_ALIASES,
    asks_per_unit_rate,
    rank_players_by_metric,
)


def _resolve(phrase: str) -> str:
    r = rank_players_by_metric(phrase, bootstrap=None)
    return r["metric"] if r["status"] == "ok" else r["code"]


# -- multi-word English phrasings resolve to the field the words name ---------------

@pytest.mark.parametrize("phrase, field", [
    ("expected goals", "expected_goals"),
    ("expected assists", "expected_assists"),
    ("expected goal involvements", "expected_goal_involvements"),
    ("expected goals conceded", "expected_goals_conceded"),
    ("expected goals against", "expected_goals_conceded"),
    ("expected goals allowed", "expected_goals_conceded"),
    ("xg against", "expected_goals_conceded"),
    ("goals scored", "goals_scored"),
    ("goals conceded", "goals_conceded"),
    ("goals against", "goals_conceded"),
    ("goals allowed", "goals_conceded"),
    ("total points", "total_points"),
    ("points per game", "points_per_game"),
    ("points per match", "points_per_game"),
    ("clean sheets", "clean_sheets"),
    ("clean sheet", "clean_sheets"),
    ("bonus points", "bonus"),
    ("transfers in", "transfers_in_event"),
    ("transfers out", "transfers_out_event"),
    ("transfers in this gameweek", "transfers_in_event"),
    ("selected by percent", "selected_by_percent"),
    ("expected goals per 90", "expected_goals_per_90"),
    ("expected assists per 90", "expected_assists_per_90"),
    ("expected goal involvements per 90", "expected_goal_involvements_per_90"),
    ("expected goals per 90 minutes", "expected_goals_per_90"),
])
def test_english_multi_word_phrase_resolves_to_the_named_field(phrase, field):
    assert _resolve(phrase) == field


def test_the_bare_goals_alias_still_means_goals_scored():
    assert _resolve("goals") == "goals_scored"
    assert _resolve("goal") == "unknown_metric"   # singular stays unsupported, as before


# -- per-game / per-minute rates: no field, so refused, not the total ---------------

@pytest.mark.parametrize("phrase", [
    "goals per game", "goals per match", "goals per gameweek", "goals per minute",
    "goals conceded per game", "goals conceded per match", "goals scored per game",
    "expected goals per game", "expected goals per match", "expected goals per minute",
    "expected goals conceded per game", "expected goals conceded per match",
    "expected goals against per game", "xg per game", "xg per match", "xg per minute",
    "xgc per game", "xgi each match", "xg each match",
    "assists per game", "minutes per game", "saves per match", "yellow cards per game",
    "bonus per match", "clean sheets per game", "clean sheets per match", "clean sheet each match",
    "points per gameweek", "points per minute", "total points per gameweek",
    "points a game", "points each match",
])
def test_english_per_game_or_per_minute_rate_without_a_field_is_refused(phrase):
    assert _resolve(phrase) == "unknown_metric", phrase


@pytest.mark.parametrize("phrase", [
    "goles por partido", "goles por jornada", "goles por minuto", "goles en contra por partido",
    "goles recibidos por partido", "goles concedidos por partido", "goles esperados por partido",
    "xg por partido", "paradas por partido", "minutos por partido", "porterias a cero por partido",
    "tarjetas amarillas por partido", "puntos por jornada",
])
def test_spanish_per_game_rate_without_a_field_is_refused(phrase):
    assert _resolve(phrase) == "unknown_metric", phrase


def test_points_per_game_is_the_one_per_game_field_and_is_not_refused():
    # the bootstrap's points_per_game IS a per-appearance rate
    assert _resolve("points per game") == "points_per_game"
    assert _resolve("puntos por partido") == "points_per_game"
    assert _resolve("media de puntos") == "points_per_game"


# -- "conceded" / "against" / "allowed" are meaning-changing -------------------------

def test_expected_goals_conceded_per_90_is_refused_not_the_xg_rate():
    """Before the modifier fix this resolved to expected_goals_per_90 (xG, not xGC)."""
    assert _resolve("expected goals conceded per 90") == "unknown_metric"
    assert _resolve("expected goals against per 90") == "unknown_metric"
    assert _resolve("goals against per 90") == "unknown_metric"


def test_expected_goals_per_90_still_resolves_to_the_attacking_rate():
    assert _resolve("expected goals per 90") == "expected_goals_per_90"
    assert _resolve("xg por 90") == "expected_goals_per_90"


# -- the per-unit check is a closed list, not every "per" phrase --------------------

@pytest.mark.parametrize("phrase, field", [
    ("top 10 por xg", "expected_goals"),   # "por xg" is not a unit
    ("top per xg", "expected_goals"),
])
def test_a_non_unit_per_phrase_is_not_a_rate(phrase, field):
    assert not asks_per_unit_rate(phrase)
    assert _resolve(phrase) == field


@pytest.mark.parametrize("phrase, field", [
    ("xg per 90 minutes", "expected_goals_per_90"),  # "per 90" is the supported rate
    ("clean sheets per 90", "clean_sheets_per_90"),
    ("saves per 90", "saves_per_90"),
])
def test_the_supported_per_90_rates_are_not_refused(phrase, field):
    assert _resolve(phrase) == field


def test_the_unit_check_is_word_bounded():
    assert not asks_per_unit_rate("goals scored")          # "game" is not inside it
    assert not asks_per_unit_rate("transfers in this gameweek")
    assert asks_per_unit_rate("goals per gameweek")


# -- Spanish neighbours are unchanged ------------------------------------------------

@pytest.mark.parametrize("phrase, field", [
    ("goles", "goals_scored"), ("goles en contra", "goals_conceded"),
    ("goles esperados", "expected_goals"), ("goles esperados por 90", "expected_goals_per_90"),
    ("xg", "expected_goals"), ("xgc", "expected_goals_conceded"), ("xg por 90", "expected_goals_per_90"),
    ("puntos", "total_points"), ("puntos por partido", "points_per_game"),
    ("paradas", "saves"), ("paradas por 90", "saves_per_90"),
    ("porterias a cero", "clean_sheets"), ("minutos", "minutes"), ("precio", "now_cost"),
    ("bps", "bps"), ("ict", "ict_index"), ("ppg", "points_per_game"),
])
def test_spanish_phrases_resolve_as_before(phrase, field):
    assert _resolve(phrase) == field


def test_every_existing_alias_key_keeps_a_resolvable_target():
    """Adding keys must not point an existing key at a field that does not exist."""
    for key, field in _METRIC_ALIASES.items():
        assert isinstance(field, str) and field, key
