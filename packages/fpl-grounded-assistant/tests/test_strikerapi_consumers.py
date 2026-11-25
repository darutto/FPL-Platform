"""What the zonal side must tolerate from a source with no situation field (StrikerAPI).

Synthetic clubs and shots; no vendor row, no network.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from fpl_grounded_assistant import zonal_weakness as zw
from fpl_grounded_assistant import zonal_weakness_tool as zwt
from fpl_tactical import strikerapi_ingest as si
from fpl_tactical import teams


def test_the_ingest_zone_geometry_is_the_engines():
    for depth_x in (0.60, 0.70, 0.75, 0.84, 0.93):
        for y in (0.0, 0.20, 0.36, 0.50, 0.64, 0.80, 1.0):
            assert si.flank_zone(depth_x, y) == zw.zone_of(depth_x, y)


def test_team_name_bridges_agree_with_the_store_names_the_engine_looks_up():
    store_names = set(zwt._SHORT_TO_UNDERSTAT.values())
    assert set(teams.API_CODE_TO_STORE.values()) <= store_names
    for short, name in teams.FPL_SHORT_TO_STORE.items():
        assert zwt._SHORT_TO_UNDERSTAT[short] == name


def _row(conceding, shooting, player, y, situation, match_id):
    return {"season": "2026-2027", "match_id": match_id, "date": "2026-10-01T15:00:00",
            "shooting_team": shooting, "conceding_team": conceding, "player": player,
            "is_home_shot": True, "minute": 10, "x": 0.90, "y": y, "xg": 0.30,
            "situation": situation, "shot_type": "Right Foot", "result": "Saved Shot"}


def _store(situation_of):
    """Eastport leaks on the right of the box; Northbury's Nine takes 12 shots there."""
    rows = []
    for i in range(12):
        rows.append(_row("Eastport", "Northbury", "Nine", 0.20, situation_of(i), i))
        rows.append(_row("Westvale", "Northbury", "Nine", 0.50, situation_of(i), 100 + i))
        rows.append(_row("Northbury", "Westvale", "Wing", 0.50, situation_of(i), 200 + i))
    return pd.DataFrame(rows)


def _exploiter(store):
    out = zw.get_zonal_opportunity("Eastport", store=store, locale="en")
    assert out["status"] == "ok" and out["exploiters"]
    return out["exploiters"][0]


def test_known_situations_still_give_the_origin():
    row = _exploiter(_store(lambda i: "Open Play"))
    assert row["origin"] == "open_play" and row["set_piece_share"] == 0.0


def test_unknown_situation_gives_no_origin_at_all_never_open_play():
    row = _exploiter(_store(lambda i: None))
    assert "origin" not in row and "set_piece_share" not in row


def test_one_unknown_row_in_the_zone_is_enough_to_omit_the_origin():
    row = _exploiter(_store(lambda i: None if i == 0 else "Open Play"))
    assert "origin" not in row


def test_penalties_stay_excluded_and_are_not_an_unknown_situation():
    rows = _store(lambda i: "Open Play")
    pen = _row("Eastport", "Northbury", "Nine", 0.20, "Penalty", 999)
    out = zw.get_zonal_opportunity("Eastport", store=pd.concat([rows, pd.DataFrame([pen])]), locale="en")
    assert out["exploiters"][0]["origin"] == "open_play"


def test_healthz_reports_the_source_on_disk_and_its_age(tmp_path, monkeypatch):
    import fpl_server

    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    from fpl_tactical.paths import CURRENT_SEASON, latest_pointer_path

    latest_pointer_path(CURRENT_SEASON).parent.mkdir(parents=True)
    latest_pointer_path(CURRENT_SEASON).write_text(json.dumps({
        "season": CURRENT_SEASON, "source": "strikerapi", "ingested_at": "2026-11-20T11:30:00Z",
        "data_through_gw": 12, "newest_shot_date": "2026-11-22T16:30:00",
        "canaries": {"known_flank": {"status": "not_checked"}}}))

    class R:
        source = "strikerapi"

    info = fpl_server._tactical_serving_info(R())
    assert info["source_serving"] == "strikerapi" and info["source_requested"] == "strikerapi"
    assert info["data_through_gw"] == 12 and info["canaries"] == {"known_flank": "not_checked"}
    assert isinstance(info["age_hours"], float)


@pytest.mark.parametrize("pointer", [{}, {"source": "understat via soccerdata"}])
def test_healthz_old_pointer_still_says_understat_or_nothing(tmp_path, monkeypatch, pointer):
    import fpl_server
    from fpl_tactical.paths import CURRENT_SEASON, latest_pointer_path

    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    latest_pointer_path(CURRENT_SEASON).parent.mkdir(parents=True)
    latest_pointer_path(CURRENT_SEASON).write_text(json.dumps(pointer))
    info = fpl_server._tactical_serving_info(None)
    assert info["source_serving"] == ("understat" if pointer else None)
