"""R6 compare_player: two players side by side through the real tool, prose and card. Synthetic store, no network."""
from __future__ import annotations

import pandas as pd
import pytest

from fpl_grounded_assistant.atomic_tool_cards import maybe_atomic_tool_card
from fpl_grounded_assistant.generic_card import generic_card_to_dict
from fpl_grounded_assistant.player_involvement_tool import run_player_involvement
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.tool_schema_registry import GET_PLAYER_INVOLVEMENT_SCHEMA
from football_intelligence.ingestion.licensed.player_stats import PLAYER_MATCH_STATS_COLUMNS

COLE, ALEX, SAKA = 93, 94, 3

BOOTSTRAP = {
    "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}, {"id": 8, "name": "Chelsea", "short_name": "CHE"},
              {"id": 11, "name": "Manchester Utd", "short_name": "MUN"}, {"id": 3, "name": "Everton", "short_name": "EVE"}],
    "elements": [
        {"id": COLE, "web_name": "Palmer", "first_name": "Cole", "second_name": "Palmer", "team": 8, "element_type": 3, "status": "a"},
        {"id": ALEX, "web_name": "Palmer", "first_name": "Alex", "second_name": "Palmer", "team": 11, "element_type": 1, "status": "a"},
        {"id": SAKA, "web_name": "Saka", "first_name": "Bukayo", "second_name": "Saka", "team": 1, "element_type": 3, "status": "a"},
    ],
}
# CHE play EVE in GW1-6; ARS play EVE in GW1-4 and GW6 (no GW5 match stored for Saka).
FIXTURES = ([{"id": gw, "event": gw, "kickoff_time": f"2026-11-{gw:02d}T15:00:00Z", "team_h": 8, "team_a": 3} for gw in range(1, 7)]
            + [{"id": 100 + gw, "event": gw, "kickoff_time": f"2026-11-{gw:02d}T17:30:00Z", "team_h": 1, "team_a": 3}
               for gw in (1, 2, 3, 4, 6)])
BUILT = "2026-12-08T05:00:00Z"


@pytest.fixture(autouse=True)
def _fresh_fixture_cache():
    from fpl_grounded_assistant import position_changes_tool
    position_changes_tool._fixture_cache.update(at=0.0, rows=None)
    yield
    position_changes_tool._fixture_cache.update(at=0.0, rows=None)


class FakeHandle:
    def __init__(self, stats):
        self._stats = stats

    def manifest(self):
        return {"built_at": BUILT}

    def table(self, name):
        return self._stats


def _row(element, fixture, team, *, touches=60, passes=40, accurate=34, back=8, key=1, minutes=90):
    base = {c: 0 for c in PLAYER_MATCH_STATS_COLUMNS}
    return {**base, "element": element, "fixture_id": fixture, "team": team, "observed_at": "2026-12-01T00:00:00Z",
            "starter": True, "minutes": minutes, "rating": 6.5, "touches": touches, "passes": passes,
            "accurate_passes": accurate, "backward_passes": back, "key_passes": key, "passes_final_third": 10}


def _stats(rows):
    return pd.DataFrame(rows, columns=list(PLAYER_MATCH_STATS_COLUMNS)).astype(object)


COLE_ROWS = [_row(COLE, gw, "CHE", touches=t, key=k) for gw, t, k in zip(range(1, 7), (58, 49, 54, 57, 30, 83), (3, 2, 3, 2, 2, 3))]
SAKA_ROWS = [_row(SAKA, 100 + gw, "ARS", touches=t, key=1) for gw, t in zip((1, 2, 3, 4, 6), (66, 61, 58, 55, 50))]
STORE = _stats(COLE_ROWS + SAKA_ROWS)


def _run(stats=STORE, **args):
    return run_player_involvement(args, dict(BOOTSTRAP), handle=FakeHandle(stats), fetch_fixtures=lambda: FIXTURES)


# ------------------------------------------------------------------ the contract

def test_one_call_answers_both_players_side_by_side():
    out = _run(player="Cole Palmer", compare_player="Saka")
    assert out["status"] == "ok" and out["player"]["player_id"] == COLE and out["compare"]["player"]["player_id"] == SAKA
    cmp = out["comparison"]
    assert cmp["series"]["gameweeks"] == [1, 2, 3, 4, 5, 6]
    assert cmp["series"]["b"]["touches"] == [66, 61, 58, 55, None, 50]      # no GW5 match: a gap, not zero
    assert cmp["trends"]["b"]["touches"] == "down"
    assert {r["metric"]: r["winner"] for r in cmp["per90"]}["key_passes"] == "a"
    assert cmp["sample"]["b"]["listed"] == 5


def test_an_ambiguous_compare_player_names_that_mention_for_the_chip():
    out = _run(player="Saka", compare_player="Palmer")
    assert out["status"] == "ambiguous" and out["query"] == "Palmer" and out["slot"] == "compare_player"
    assert {c["id"] for c in out["candidates"]} == {COLE, ALEX}


def test_an_ambiguous_first_player_keeps_its_own_mention():
    out = _run(player="Palmer", compare_player="Saka")
    assert out["status"] == "ambiguous" and out["query"] == "Palmer"


def test_compare_player_and_absent_player_are_never_combined():
    out = _run(player="Cole Palmer", compare_player="Saka", absent_player="Saka")
    assert out["status"] == "invalid_args"
    assert "not both" in render("get_player_involvement", out, locale="en")


def test_a_second_player_with_nothing_stored_is_said_and_the_first_answer_stands():
    out = _run(_stats(COLE_ROWS), player="Cole Palmer", compare_player="Saka")
    assert out["status"] == "ok" and "comparison" not in out and out["compare_missing"]["player"]["web_name"] == "Saka"
    assert "Saka todavía no tiene estadísticas" in render("get_player_involvement", out, locale="es")
    card = maybe_atomic_tool_card("get_player_involvement", out, None, "es")
    assert card is not None and card.involvement_compare is None          # the one-player card


def test_an_unknown_count_is_a_gap_and_no_winner():
    rows = [_row(SAKA, 100 + gw, "ARS", key=None) for gw in (1, 2, 3, 4, 6)]
    cmp = _run(_stats(COLE_ROWS + rows), player="Cole Palmer", compare_player="Saka")["comparison"]
    assert cmp["series"]["b"]["key_passes"] == [None] * 6
    row = next(r for r in cmp["per90"] if r["metric"] == "key_passes")
    assert row["b"] is None and row["winner"] is None
    assert cmp["trends"]["b"]["key_passes"] is None


def test_the_schema_offers_compare_player_and_says_one_call():
    props = GET_PLAYER_INVOLVEMENT_SCHEMA.parameters["properties"]
    assert "compare_player" in props and GET_PLAYER_INVOLVEMENT_SCHEMA.parameters["required"] == ["player"]
    assert "ONE call with player=X and compare_player=Y" in GET_PLAYER_INVOLVEMENT_SCHEMA.description
    assert " his " not in GET_PLAYER_INVOLVEMENT_SCHEMA.description


# ------------------------------------------------------------------ prose and card

@pytest.mark.parametrize("locale, head", [("es", "Por 90, Palmer frente a Saka:"), ("en", "Per 90, Palmer vs Saka:")])
def test_the_text_holds_both_players_and_the_per90_line(locale, head):
    text = render("get_player_involvement", _run(player="Cole Palmer", compare_player="Saka"), locale=locale)
    assert text.count("Palmer (CHE)") == 1 and text.count("Saka (ARS)") == 1 and head in text


@pytest.mark.parametrize("locale, gw, view, footer", [
    ("es", "J1", "Por jornada", "Palmer: 6 partidos · Saka: 5 partidos · totales por partido, sin zonas del campo"),
    ("en", "GW1", "By match", "Palmer: 6 matches · Saka: 5 matches · match totals, no pitch zones"),
])
def test_the_card_carries_the_comparison_payload_in_the_request_language(locale, gw, view, footer):
    card = maybe_atomic_tool_card("get_player_involvement", _run(player="Cole Palmer", compare_player="Saka"), None, locale)
    p = card.involvement_compare
    assert p["a"] == {"name": "Palmer", "team": "CHE"} and p["b"] == {"name": "Saka", "team": "ARS"}
    assert [r["metric"] for r in p["per90"]][-1] == "backward_share" and p["per90"][-1]["winner"] is None
    assert p["series"]["gw_labels"][0] == gw and p["labels"]["view_series"] == view
    touches = p["series"]["metrics"][0]
    assert touches["metric"] == "touches" and touches["b"][4] is None and touches["trend_b"] == "down"
    assert p["footer"] == footer and p["provenance"].endswith("2026-12-08.")
    # the plain table for a client that draws only the table: one row per per-90 metric
    assert len(card.rows) == 5 and all(len(r) == 3 for r in card.rows)


def test_the_payload_is_null_on_the_wire_for_the_one_player_card():
    pair = generic_card_to_dict(maybe_atomic_tool_card("get_player_involvement",
                                                       _run(player="Cole Palmer", compare_player="Saka"), None, "es"))
    single = generic_card_to_dict(maybe_atomic_tool_card("get_player_involvement", _run(player="Cole Palmer"), None, "es"))
    assert pair["involvement_compare"]["a"]["name"] == "Palmer" and single["involvement_compare"] is None
