"""Honest age on the zonal data (Leo, 2026-11-24).

The store froze while the season moved on, and users read old data with no
date. From 2 finished gameweeks behind the stamp says «datos hasta la GW8 ·
20 oct»; from 4 behind verdicts use the past tense and the fixture cell offers
no zonal tap. The rule is the same for any shot source.

Synthetic data only: invented clubs and shots. No network, no provider.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from fpl_grounded_assistant import fixture_cell_zonal as cell_mod
from fpl_grounded_assistant import zonal_weakness as zw
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY


def _events(last_finished: int, n: int = 12) -> list[dict]:
    """One gameweek a week from 2026-08-14; GW1..last_finished are finished."""
    out = []
    for gw in range(1, n + 1):
        day = 14 + 7 * (gw - 1)
        month = 8 + (day - 1) // 31
        out.append({
            "id": gw,
            "deadline_time": f"2026-{month:02d}-{(day - 1) % 31 + 1:02d}T17:30:00Z",
            "finished": gw <= last_finished,
        })
    return out


EV = _events(last_finished=10)


def _date_in_gw(gw: int) -> str:
    deadline = next(e for e in EV if e["id"] == gw)["deadline_time"]
    return deadline[:10] + "T20:00:00"


def _age(data_gw: int, last_finished: int = 10) -> dict:
    events = _events(last_finished)
    return zw._data_age({"newest_shot_date": _date_in_gw(data_gw)}, None, events)


# --- which gameweek the newest shot belongs to -----------------------------


def test_gw_comes_from_the_deadline_window_not_from_match_count():
    # a store with 83 matches would say GW8 by n_matches // 10; the window says 9
    assert zw._gw_of_date(_date_in_gw(9), EV) == 9
    assert zw._gw_of_date(_date_in_gw(9)[:10] + "T00:00:00", EV) == 8  # before GW9's deadline


def test_unknowable_age_is_none_not_a_guess():
    assert zw._data_age({"newest_shot_date": _date_in_gw(5)}, None, None) is None
    assert zw._data_age({}, None, EV) is None
    assert zw._data_age({"newest_shot_date": "2026-09-01T10:00:00"}, None, _events(0)) is None


def test_age_reads_newest_shot_date_from_the_shots_when_the_pointer_has_none():
    shots = pd.DataFrame({"date": [_date_in_gw(3), _date_in_gw(6)]})
    assert zw._data_age({"season": "2026-2027"}, shots, EV) == {
        "data_gw": 6, "date": _date_in_gw(6)[:10], "behind": 4}


# --- the stamp ---------------------------------------------------------------


POINTER = {"season": "2026-2027", "n_matches": 80, "n_shots": 2000}


@pytest.mark.parametrize("behind,status", [(0, "thin"), (1, "thin"), (2, "aged"), (3, "aged"), (6, "aged")])
def test_stamp_threshold_is_two_gameweeks(behind, status):
    prov = zw.build_data_provenance(POINTER, "2026-2027", data_age=_age(10 - behind))
    assert prov["status"] == status
    assert prov["gws_behind"] == behind


def test_aged_label_names_gw_and_date_in_both_languages():
    age = _age(8)
    es = zw.build_data_provenance(POINTER, "2026-2027", "es", age)
    en = zw.build_data_provenance(POINTER, "2026-2027", "en", age)
    day = int(age["date"][8:10])
    assert es["label"].startswith("⚠ Datos hasta la GW8 · ")
    assert en["label"].startswith("⚠ Data up to GW8 · ")
    assert str(day) in es["label"]
    assert es["data_through_gw"] == 8 and es["data_through_date"] == age["date"]


def test_a_full_store_that_is_old_is_aged_not_current():
    full = {**POINTER, "n_matches": 380}
    assert zw.build_data_provenance(full, "2026-2027", data_age=_age(8))["status"] == "aged"
    assert zw.build_data_provenance(full, "2026-2027", data_age=_age(10))["status"] == "current"


def test_wrong_season_stays_the_louder_stamp():
    assert zw.build_data_provenance(POINTER, "2027-2028", data_age=_age(2))["status"] == "stale_season"


def test_without_age_the_stamp_is_exactly_as_before():
    prov = zw.build_data_provenance(POINTER, "2026-2027")
    assert prov["status"] == "thin"
    assert "gws_behind" not in prov and "past_tense" not in prov


def test_results_pointer_without_ingested_at_is_tolerated():
    prov = zw.build_data_provenance({"season": "2026-2027"}, "2026-2027")
    assert prov["status"] == "current" and prov["ingested_at"] is None


def test_past_tense_starts_at_four_behind():
    assert zw.build_data_provenance(POINTER, "2026-2027", data_age=_age(7))["past_tense"] is False  # 3 behind
    assert zw.build_data_provenance(POINTER, "2026-2027", data_age=_age(6))["past_tense"] is True   # 4 behind


# --- through the real entry points -------------------------------------------


def _shot(conceding, shooting, x, y, xg, match_id, date):
    return {"season": "2026-2027", "match_id": match_id, "date": date, "shooting_team": shooting,
            "conceding_team": conceding, "player": f"{shooting} Nine", "is_home_shot": True, "minute": 10,
            "x": x, "y": y, "xg": xg, "situation": "Open Play", "shot_type": "Right Foot",
            "result": "Saved Shot"}


def _store_at(tmp_path, data_gw, pointer_extra=None):
    rows = []
    for i, (conceding, shooting) in enumerate([("Eastport", "Northbury"), ("Westvale", "Northbury"),
                                                 ("Northbury", "Westvale")]):
        rows.append(_shot(conceding, shooting, 0.90, 0.50, 0.30, i, _date_in_gw(data_gw)))
        if conceding == "Eastport":
            rows.append(_shot(conceding, shooting, 0.90, 0.20, 0.40, i, _date_in_gw(data_gw)))
    rows = [r for r in rows for _ in range(12)]  # enough shots per player to be ranked
    path = tmp_path / "understat_shots.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    (tmp_path / "_tactical_latest.json").write_text(json.dumps({**POINTER, **(pointer_extra or {})}))
    return path


@pytest.mark.parametrize("pointer_extra", [None, {"newest_shot_date": None}])
def test_weakness_answer_is_stamped_from_the_store_it_read(tmp_path, pointer_extra):
    path = _store_at(tmp_path, data_gw=8)
    out = zw.get_zonal_weakness("Eastport", store=path, live_season="2026-2027", gw_events=EV)
    assert out["status"] == "ok"
    assert out["data_provenance"]["status"] == "aged"
    assert out["data_provenance"]["data_through_gw"] == 8


def test_weakness_verdict_is_past_tense_only_from_four_behind(tmp_path):
    for data_gw, past in ((7, False), (6, True)):
        path = _store_at(tmp_path, data_gw=data_gw)
        out = zw.get_zonal_weakness("Eastport", store=path, live_season="2026-2027", gw_events=EV, locale="en")
        assert out["verdict"].startswith("Attack ") != past
        assert ("conceded" in out["verdict"]) == past


def test_opportunity_verdict_is_past_tense_at_four_behind(tmp_path):
    path = _store_at(tmp_path, data_gw=6)
    out = zw.get_zonal_opportunity("Eastport", store=path, live_season="2026-2027", gw_events=EV, locale="en")
    assert out["status"] == "ok"
    assert "conceded" in out["verdict"]


# --- the fixture cell tap ------------------------------------------------------


_TEAMS = [{"id": 1, "name": "Northbury", "short_name": "NOR"}, {"id": 2, "name": "Eastport", "short_name": "EAS"}]


def _links(tmp_path, data_gw, monkeypatch):
    path = _store_at(tmp_path, data_gw=data_gw)
    monkeypatch.setattr(zw, "_read_pointer", lambda store: json.loads((tmp_path / "_tactical_latest.json").read_text()))
    bootstrap = {"teams": _TEAMS, "elements": [], "events": EV, BOOTSTRAP_LOCALE_KEY: "es"}
    outlook = {"series": [{"gameweek": 11, "fixtures": [{"opponent_short": "EAS", "is_home": False, "band": 2}]}]}
    return cell_mod.match_zonal_links(outlook, _TEAMS[0], bootstrap, store=pd.read_parquet(path))


def test_fixture_cell_keeps_the_tap_at_three_behind_and_drops_it_at_four(tmp_path, monkeypatch):
    assert len(_links(tmp_path, 7, monkeypatch)) == 1
    assert _links(tmp_path, 6, monkeypatch) == []


# --- exploiters withheld at four behind ----------------------------------------


def _opportunity(tmp_path, data_gw):
    path = _store_at(tmp_path, data_gw=data_gw)
    return zw.get_zonal_opportunity("Eastport", store=path, live_season="2026-2027", gw_events=EV, locale="en")


def test_opportunity_names_players_up_to_three_behind(tmp_path):
    out = _opportunity(tmp_path, 7)
    assert out["exploiters"] and "exploiters_withheld" not in out
    assert any(o["players"] for o in out["opportunities"])


def test_opportunity_withholds_players_at_four_behind_but_keeps_the_zones(tmp_path):
    out = _opportunity(tmp_path, 6)
    assert out["exploiters"] == [] and out["exploiters_withheld"] is True
    assert out["opportunities"] and all(o["players"] == [] for o in out["opportunities"])
    assert out["zones"] and out["data_provenance"]["status"] == "aged"


def test_text_never_announces_an_empty_player_list(tmp_path):
    from fpl_grounded_assistant.renderer import _render_get_zonal_opportunity

    text = _render_get_zonal_opportunity(_opportunity(tmp_path, 6))
    assert "sin jugadores" not in text and "Oportunidad zonal" not in text
    assert "conceded" in text  # the past-tense verdict leads
    assert "vs media" in text   # the opponent's zones stay


def test_card_drops_the_player_section_instead_of_showing_an_empty_one(tmp_path):
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta

    out = _opportunity(tmp_path, 6)
    out["card_zones"] = out["zones"]
    meta = _extract_zonal_opportunity_meta(out)
    assert meta is not None and meta.has_exploiters is False and meta.exploiters == ()
    fresh = _opportunity(tmp_path, 7)
    assert _extract_zonal_opportunity_meta(fresh).has_exploiters is True
