"""B4 PR 2: get_position_changes end to end over a synthetic licensed store. No network, no provider, no LLM."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from fpl_grounded_assistant.catalogue import _CATALOGUE
from fpl_grounded_assistant.position_changes_tool import fixture_index, run_position_changes
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.tool_schema_registry import (
    FI7B_TOOL_NAMES, get_offered_tool_names,
)
from football_intelligence.ingestion.licensed.store import TABLES

ROGERS, PEDRO, COSTINHA = 10, 20, 99

BOOTSTRAP = {
    "teams": [{"id": 1, "name": "Chelsea", "short_name": "CHE"}, {"id": 2, "name": "Brighton", "short_name": "BHA"},
              {"id": 3, "name": "Everton", "short_name": "EVE"}],
    "elements": [
        {"id": ROGERS, "web_name": "Rogers", "first_name": "Morgan", "second_name": "Rogers", "team": 1, "element_type": 3, "status": "a"},
        {"id": PEDRO, "web_name": "João Pedro", "first_name": "João Pedro", "second_name": "Junqueira de Jesus", "team": 1,
         "element_type": 4, "status": "a"},
        {"id": COSTINHA, "web_name": "Costinha", "first_name": "João Pedro", "second_name": "Gonçalves Costinha", "team": 2,
         "element_type": 4, "status": "a"},
    ],
}
FPL_FIXTURES = [  # FPL's own list: id, event, kickoff, home team id, away team id
    {"id": fid, "event": gw, "kickoff_time": f"2026-11-{day:02d}T15:00:00Z", "team_h": 1 if gw % 2 else 3, "team_a": 3 if gw % 2 else 1}
    for fid, (gw, day) in enumerate([(1, 2), (2, 9), (3, 16), (4, 23), (5, 30)], start=1)
]


class FakeHandle:
    def __init__(self, tables, built_at="2026-11-30T05:00:00Z"):
        self._tables, self._built_at = tables, built_at

    def manifest(self):
        return {"built_at": self._built_at, "assumption_status": "licensed_starter"}

    def table(self, name):
        return self._tables[name]


def _tables():
    snaps, slots = [], []
    for fid in range(1, 6):
        obs = f"2026-11-{[2, 9, 16, 23, 30][fid - 1]:02d}T10:00:00Z"
        snaps.append({"fixture_id": fid, "team": "CHE", "observed_at": obs, "state": "finished", "confirmed": True,
                      "formation": "4-2-3-1", "n_starters": 2, "n_bench": 0})
        out = fid == 4
        slots.append({"fixture_id": fid, "team": "CHE", "observed_at": obs, "element": ROGERS, "starter": True,
                      "detailed_position": "Attacking Midfield" if out else "Right Midfield", "grid_slot": "3:2" if out else "3:3",
                      "side": "centre" if out else "right"})
        if not out:
            slots.append({"fixture_id": fid, "team": "CHE", "observed_at": obs, "element": PEDRO, "starter": True,
                          "detailed_position": "Centre Forward", "grid_slot": "4:1", "side": "centre"})
    frames = {
        "lineup_snapshots": snaps, "lineup_slots": slots,
        "sidelined": [{"element": PEDRO, "team": "CHE", "category": "injury", "start_date": "2026-11-20", "end_date": None,
                       "games_missed": 2, "completed": False, "observed_at": "2026-11-21T05:00:00Z"}],
        "squad_membership": [{"team": "CHE", "element": el, "jersey_number": 1, "observed_at": "2026-11-01T05:00:00Z"} for el in (ROGERS, PEDRO)],
    }
    return {name: pd.DataFrame(rows, columns=list(TABLES[name][0])).astype(object) for name, rows in frames.items()}


@pytest.fixture
def run():
    handle = FakeHandle(_tables())
    return lambda args, **kw: run_position_changes(args, dict(BOOTSTRAP), handle=handle, fetch_fixtures=lambda: FPL_FIXTURES, **kw)


def test_the_user_question_reads_rogers_when_joao_pedro_did_not_start(run):
    out = run({"player": "Rogers", "absent_player": "Joao Pedro"})
    assert out["status"] == "ok"
    focus = out["absence_focus"]
    assert focus["teammate"] == {"player_id": PEDRO, "web_name": "João Pedro", "team_short": "CHE"}
    assert [m["gameweek"] for m in focus["matches_without_him_in_xi"]] == [4]
    assert focus["matches_without_him_in_xi"][0]["listed_sidelined"]["category"] == "injury"
    assert focus["role_differs"] is True and focus["small_sample"] is True  # one match without him: said, not hidden
    assert out["data_provenance"] == {"source": "licensed_starter", "built_at": "2026-11-30T05:00:00Z",
                                      "slot_meaning": "announced_starting_xi"}


def test_joao_pedro_is_the_chelsea_player_never_costinha(run):
    # "João Pedro" alone is ambiguous in the contract resolver (Costinha's first name is the same); next to a Chelsea
    # player it is scoped to the club by id, and a player of another club is reported as not a teammate.
    out = run({"player": "Rogers", "absent_player": "João Pedro"})
    assert out["absence_focus"]["teammate"]["player_id"] == PEDRO
    other_club = run({"player": "Rogers", "absent_player": "Costinha"})
    assert other_club["status"] == "not_a_teammate"
    alone = run({"player": "João Pedro"})
    assert alone["status"] == "ambiguous" and {c["team_short"] for c in alone["candidates"]} == {"CHE", "BHA"}


def test_without_a_synced_store_the_answer_is_missing_context_not_an_empty_success():
    class Broken:
        def manifest(self):
            raise FileNotFoundError("no pointer")

    out = run_position_changes({"player": "Rogers"}, dict(BOOTSTRAP), handle=Broken(), fetch_fixtures=lambda: FPL_FIXTURES)
    assert out["status"] == "missing_context" and out["reason_codes"] == ["licensed_store_unavailable"]


def test_an_unreachable_fixture_list_degrades_the_answer(run):
    def boom():
        raise OSError("FPL unreachable")

    handle = FakeHandle(_tables())
    from fpl_grounded_assistant import position_changes_tool as mod
    mod._fixture_cache.update(at=0.0, rows=None)
    out = run_position_changes({"player": "Rogers"}, dict(BOOTSTRAP), handle=handle, fetch_fixtures=boom)
    assert out["status"] == "missing_context" and out["reason_codes"] == ["fixture_list_unavailable"]


def test_the_fixture_index_uses_club_codes_not_ids():
    index = fixture_index({**BOOTSTRAP, "fixture_index": FPL_FIXTURES})
    assert index[1].home == "CHE" and index[1].away == "EVE" and index[2].home == "EVE"


def test_the_tool_is_offered_only_with_the_football_intelligence_flag():
    assert "get_position_changes" in FI7B_TOOL_NAMES
    assert "get_position_changes" not in get_offered_tool_names(False)
    assert "get_position_changes" in get_offered_tool_names(True)


# ---- the deterministic text, both languages -------------------------------------------------------------------

FORBIDDEN_PHRASES = ("se movi", "moved during", "por la lesi", "because of", "due to", "rendir", "will perform", "weak", "debilidad")


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_text_uses_only_the_allowed_phrases_and_no_causal_words(run, locale):
    text = render("get_position_changes", run({"player": "Rogers", "absent_player": "Joao Pedro"}), locale=locale)
    low = text.casefold()
    assert not any(bad in low for bad in FORBIDDEN_PHRASES)
    if locale == "es":
        assert "empezó en otra casilla" in text and "coincidió con la ausencia de João Pedro" in text
        assert "Muestra pequeña" in text and "no un movimiento durante el partido" in text
        assert "Banda derecha" in text and "Mediapunta" in text
    else:
        assert "started in a different slot" in text and "coincided with the absence of João Pedro" in text
        assert "Small sample" in text and "not movement during the match" in text
        assert "Right Midfield" in text and "Attacking Midfield" in text


@pytest.mark.parametrize("locale", ["es", "en"])
def test_statuses_without_data_render_in_the_language(run, locale):
    missing = render("get_position_changes", {"status": "missing_context"}, locale=locale)
    teammate = render("get_position_changes", run({"player": "Rogers", "absent_player": "Costinha"}), locale=locale)
    assert missing and teammate and "Costinha" in teammate
    assert ("Todavía" in missing) == (locale == "es")


def test_the_new_catalogue_keys_come_in_pairs_with_the_same_placeholders():
    import re
    keys = [k for k in _CATALOGUE if k.startswith("renderer.position_changes.")]
    assert len(keys) == 25
    for key in keys:
        entry = _CATALOGUE[key]
        assert set(entry) == {"en", "es"} and entry["en"] and entry["es"]
        assert sorted(re.findall(r"{(\w+)}", entry["en"])) == sorted(re.findall(r"{(\w+)}", entry["es"])), key


def test_the_output_has_no_store_rows_or_provider_ids(run):
    text = json.dumps(run({"player": "Rogers", "absent_player": "Joao Pedro"}), ensure_ascii=False).casefold()
    for forbidden in ("sportmonks", "crosswalk", "sportmonks_player_id", "fixture_id", "observed_at"):
        assert forbidden not in text


# ---- the card (PR 3) ------------------------------------------------------------------------------------------

from dataclasses import asdict  # noqa: E402

from fpl_grounded_assistant.atomic_tool_cards import compose_position_changes_card, maybe_atomic_tool_card  # noqa: E402


def _card(run, locale, **args):
    return maybe_atomic_tool_card("get_position_changes", run({"player": "Rogers", **args}), None, locale)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_card_has_a_row_per_match_and_the_same_wording_as_the_text(run, locale):
    card = _card(run, locale, absent_player="Joao Pedro")
    assert [len(r) for r in card.rows] == [4] * len(card.rows) == [4] * 5
    flat = json.dumps(asdict(card), ensure_ascii=False)
    assert not any(bad in flat.casefold() for bad in FORBIDDEN_PHRASES)
    assert card.hero.value == "1"  # one observed change of slot
    fourth = next(r for r in card.rows if r[0] in ("GW4", "J4"))
    if locale == "es":
        assert card.title == "Rogers · casilla inicial" and "no un movimiento durante el partido" in card.subtitle
        assert "Empezó en otra casilla (antes: Banda derecha)" in fourth[3] and "Coincidió con la ausencia de João Pedro" in fourth[3]
        assert fourth[2] == "Mediapunta" and any(p.label.startswith("Muestra pequeña") for p in card.pills)
        assert card.columns[3].header == "Nota"
    else:
        assert card.title == "Rogers · starting slot" and "not movement during the match" in card.subtitle
        assert "Started in a different slot (before: Right Midfield)" in fourth[3]
        assert "Coincided with the absence of João Pedro" in fourth[3] and fourth[2] == "Attacking Midfield"
        assert any(p.label.startswith("Small sample") for p in card.pills)
    assert card.footer and "2026-11-30" in card.footer


def test_there_is_no_card_without_matches_or_for_a_non_ok_answer(run):
    assert compose_position_changes_card({"status": "ambiguous", "candidates": []}) is None
    assert compose_position_changes_card({"status": "missing_context", "matches": []}) is None
    assert compose_position_changes_card({"status": "ok", "matches": []}) is None


def test_a_malformed_answer_degrades_to_text_instead_of_raising():
    assert compose_position_changes_card({"status": "ok", "matches": [{"change": {"from": None}, "associations": [None]}]}) is None


def test_the_ranking_card_is_untouched_by_the_locale_argument():
    out = {"status": "ok", "metric": "form", "ranked": [{"rank": 1, "web_name": "Haaland", "team_short": "MCI",
                                                          "position": "FWD", "metric_value": 8.0}]}
    es = maybe_atomic_tool_card("rank_players_by_metric", out, None)
    en = maybe_atomic_tool_card("rank_players_by_metric", out, None, "en")
    assert es == en  # that card predates the language track and stays as it was
