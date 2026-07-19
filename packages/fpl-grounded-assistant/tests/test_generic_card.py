"""
Tests for Track A — additive ``generic_card`` structured payload.

Covers:
  * one composer per intent (metadata fixture → expected blocks)
  * generic_card is None on non-ok outcomes
  * generic_card is None for bespoke-card / excluded intents
  * serializer round-trip (dataclass → JSON-safe dict → key/shape checks)
  * the row-width invariant (every row has len(columns) cells)

Composition is exercised through ``_extract_structured_meta`` (the single place
generic_card is built) so the tests validate the real wiring, not just the
composer functions in isolation.
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

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant.final_response import _extract_structured_meta  # noqa: E402
from fpl_grounded_assistant.generic_card import (  # noqa: E402
    GenericCardMeta,
    HeroStat,
    Pill,
    Column,
    generic_card_to_dict,
)


# ---------------------------------------------------------------------------
# Synthetic deterministic tool outputs (shape mirrors the real dispatcher).
# ---------------------------------------------------------------------------

_PLAYER_FORM_RAW = {
    "web_name": "Salah",
    "team_short": "LIV",
    "position": "MID",
    "n_games": 3,
    "history": [
        {"gameweek": 26, "minutes": 90, "goals_scored": 1, "assists": 0, "bonus": 2, "total_points": 8},
        {"gameweek": 27, "minutes": 90, "goals_scored": 0, "assists": 1, "bonus": 1, "total_points": 6},
        {"gameweek": 28, "minutes": 85, "goals_scored": 2, "assists": 0, "bonus": 3, "total_points": 13},
    ],
}

_PRICE_CHANGES_RAW = {
    "risers": [
        {"web_name": "Palmer", "team_short": "CHE", "position": "MID",
         "now_cost": 61, "now_cost_m": 6.1, "cost_change_event": 1, "cost_change_start": 3},
    ],
    "fallers": [
        {"web_name": "Nunez", "team_short": "LIV", "position": "FWD",
         "now_cost": 74, "now_cost_m": 7.4, "cost_change_event": -1, "cost_change_start": -2},
    ],
}

_TEAM_CALENDAR_RAW = {
    "mode": "easiest",
    "horizon": 5,
    "current_gameweek": 28,
    "top_n": 2,
    "teams": [
        {"rank": 1, "team_short": "ARS", "team_name": "Arsenal", "fixture_count": 5,
         "avg_fdr": 2.2, "total_fdr": 11, "fixtures": [
             {"gameweek": 28, "opponent_short": "BUR", "is_home": True, "difficulty": 2}]},
        {"rank": 2, "team_short": "MCI", "team_name": "Man City", "fixture_count": 5,
         "avg_fdr": 2.6, "total_fdr": 13, "fixtures": []},
    ],
}

_TEAM_SCHEDULE_RAW = {
    "team_short": "LIV",
    "team_name": "Liverpool",
    "horizon": 3,
    "current_gameweek": 28,
    "fixture_count": 3,
    "avg_fdr": 2.7,
    "total_fdr": 8,
    "fixtures": [
        {"gameweek": 28, "opponent_short": "BHA", "is_home": True, "difficulty": 2},
        {"gameweek": 29, "opponent_short": "MCI", "is_home": False, "difficulty": 5},
        {"gameweek": 30, "opponent_short": "WOL", "is_home": True, "difficulty": 3},
    ],
    "has_dgw": False,
    "has_bgw": False,
}

_POSITION_FIXTURE_RUN_RAW = {
    "position": "DEF",
    "position_label": "defensas",
    "mode": "easiest",
    "horizon": 5,
    "current_gameweek": 28,
    "top_n": 1,
    "teams": [
        {"rank": 1, "team_short": "ARS", "team_name": "Arsenal", "fixture_count": 5,
         "avg_fdr": 2.2, "total_fdr": 11, "fixtures": []},
    ],
}

_CURRENT_GAMEWEEK_RAW = {"status": "ok", "gameweek": 29}


def _card(intent: str, raw: dict, outcome: str = "ok") -> GenericCardMeta | None:
    return _extract_structured_meta(intent, raw, outcome)["generic_card"]


def _assert_row_width(card: GenericCardMeta) -> None:
    """Every row must have exactly len(columns) cells, all strings."""
    ncols = len(card.columns)
    for row in card.rows:
        assert len(row) == ncols, f"row {row!r} width != {ncols}"
        assert all(isinstance(c, str) for c in row)


# ---------------------------------------------------------------------------
# One composer test per intent
# ---------------------------------------------------------------------------

def test_player_form_composer() -> None:
    card = _card("player_form", _PLAYER_FORM_RAW)
    assert isinstance(card, GenericCardMeta)
    assert card.accent == "turquoise"
    assert card.title == "FORMA RECIENTE"
    assert card.subtitle == "Salah · LIV · MID"
    # hero = total points over the window (8 + 6 + 13 = 27)
    assert card.hero == HeroStat(value="27", label="PUNTOS · 3 JOR", tone="good")
    assert len(card.rows) == 3
    # mono per-GW rows, earliest first
    assert card.rows[0] == ("GW26", "90", "1", "0", "2", "8")
    assert card.rows[2] == ("GW28", "85", "2", "0", "3", "13")
    assert all(c.kind == "mono" for c in card.columns[1:])
    _assert_row_width(card)


def test_price_changes_composer() -> None:
    card = _card("price_changes", _PRICE_CHANGES_RAW)
    assert isinstance(card, GenericCardMeta)
    assert card.accent == "gold"
    assert card.title == "CAMBIOS DE PRECIO"
    # riser/faller counts as good/bad tone pills
    assert Pill(label="1 SUBEN", tone="good") in card.pills
    assert Pill(label="1 BAJAN", tone="bad") in card.pills
    # risers first, then fallers; signed CHANGE cell
    assert card.rows[0] == ("Palmer", "CHE", "£6.1", "+£0.1")
    assert card.rows[1] == ("Nunez", "LIV", "£7.4", "-£0.1")
    assert card.columns[-1].kind == "badge"
    _assert_row_width(card)


def test_team_fixture_calendar_composer() -> None:
    card = _card("team_fixture_calendar", _TEAM_CALENDAR_RAW)
    assert isinstance(card, GenericCardMeta)
    assert card.accent == "cyan"
    assert card.title == "CALENDARIO"
    assert card.subtitle == "Calendario más favorable"
    assert len(card.rows) == 2
    # rank, team, fixture_count, avg_fdr, FDR text label
    assert card.rows[0] == ("1", "ARS", "5", "2.2", "Favorable")
    assert card.rows[1][4] == "Media"   # avg_fdr 2.6 rounds to 3 → Media
    _assert_row_width(card)


def test_team_schedule_composer() -> None:
    card = _card("team_schedule", _TEAM_SCHEDULE_RAW)
    assert isinstance(card, GenericCardMeta)
    assert card.accent == "cyan"
    assert card.subtitle == "Liverpool"
    # hero = average FDR over the horizon
    assert card.hero == HeroStat(value="2.7", label="FDR MEDIO", tone=None)
    # fixture rows with venue + FDR text label (colours are UI-side)
    assert card.rows[0] == ("GW28", "BHA", "Casa", "Favorable")
    assert card.rows[1] == ("GW29", "MCI", "Fuera", "Muy exigente")
    _assert_row_width(card)


def test_position_fixture_run_composer() -> None:
    card = _card("position_fixture_run", _POSITION_FIXTURE_RUN_RAW)
    assert isinstance(card, GenericCardMeta)
    assert card.accent == "purple"
    assert card.title == "CALENDARIO POR POSICIÓN"
    assert card.subtitle == "defensas · Calendario más favorable"
    assert card.rows[0] == ("1", "ARS", "5", "2.2", "Favorable")
    _assert_row_width(card)


def test_current_gameweek_composer() -> None:
    card = _card("current_gameweek", _CURRENT_GAMEWEEK_RAW)
    assert isinstance(card, GenericCardMeta)
    assert card.accent == "coral"
    assert card.title == "JORNADA ACTUAL"
    assert card.hero == HeroStat(value="GW29", label="JORNADA EN CURSO", tone=None)
    # deadline is not in the deterministic tool output → footer intentionally None
    assert card.footer is None
    assert card.rows == ()
    assert card.columns == ()


# ---------------------------------------------------------------------------
# generic_card is None on non-ok outcomes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outcome", ["not_found", "ambiguous", "error", "missing_arguments", "unsupported_intent"])
def test_generic_card_none_on_non_ok(outcome: str) -> None:
    assert _card("player_form", _PLAYER_FORM_RAW, outcome) is None
    assert _card("current_gameweek", _CURRENT_GAMEWEEK_RAW, outcome) is None


# ---------------------------------------------------------------------------
# generic_card is None for bespoke-card / excluded intents
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("intent", [
    "captain_score",
    "compare_players",
    "rank_candidates",
    "transfer_advice",
    "chip_advice",
    "player_fixture_run",
    "differential_picks",
    "fixture_outlook",
    "zonal_opportunity",
    "injury_list",          # UI reuses its injuries table
    "transfer_suggestion",  # bespoke card owned by another track
])
def test_generic_card_none_for_bespoke_intents(intent: str) -> None:
    # Even on OK with plausible payloads, excluded intents never get a generic_card.
    assert _card(intent, {}, "ok") is None


# ---------------------------------------------------------------------------
# Serializer round-trip
# ---------------------------------------------------------------------------

def test_generic_card_to_dict_none() -> None:
    assert generic_card_to_dict(None) is None


def test_serializer_round_trip_shape() -> None:
    card = _card("player_form", _PLAYER_FORM_RAW)
    d = generic_card_to_dict(card)
    # Top-level keys and types are the documented wire contract.
    assert set(d.keys()) == {
        "accent", "title", "subtitle", "hero", "pills", "columns", "rows", "footer",
    }
    assert isinstance(d["pills"], list)
    assert isinstance(d["columns"], list)
    assert isinstance(d["rows"], list)
    assert d["hero"] == {"value": "27", "label": "PUNTOS · 3 JOR", "tone": "good"}
    # rows are lists of strings; every row matches the column count
    assert all(isinstance(r, list) for r in d["rows"])
    ncols = len(d["columns"])
    assert all(len(r) == ncols for r in d["rows"])
    # column dicts carry header/align/kind
    for c in d["columns"]:
        assert set(c.keys()) == {"header", "align", "kind"}
    # pill dicts carry label/tone
    for p in d["pills"]:
        assert set(p.keys()) == {"label", "tone"}


def test_serializer_hero_none_card() -> None:
    card = _card("price_changes", _PRICE_CHANGES_RAW)
    d = generic_card_to_dict(card)
    assert d["hero"] is None
    assert d["rows"] == [["Palmer", "CHE", "£6.1", "+£0.1"], ["Nunez", "LIV", "£7.4", "-£0.1"]]


# ---------------------------------------------------------------------------
# Safety — malformed metadata degrades to None, never raises
# ---------------------------------------------------------------------------

def test_malformed_player_form_degrades_to_none() -> None:
    # history entries missing keys → _extract_player_form_meta already degrades,
    # but even a partial dict must never raise out of build_generic_card.
    card = _card("player_form", {"web_name": "X"}, "ok")
    assert card is None or isinstance(card, GenericCardMeta)
