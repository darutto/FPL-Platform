"""R6: per-player match statistics in the licensed store. Synthetic data only: invented ids, names and values."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from football_intelligence.distribution.licensed_runtime import LicensedRuntimeHandle
from football_intelligence.distribution.service import encode_pointer
from football_intelligence.ingestion.licensed.derive import FplFixture, derive
from football_intelligence.ingestion.licensed.player_stats import (
    PLAYER_MATCH_STATS_COLUMNS, STAT_COLUMNS, lineup_stats, new_information, type_names,
)
from football_intelligence.ingestion.licensed.store import (
    OPTIONAL_TABLES, POINTER_NAME, LicensedStoreError, read_table, validate_build, write_build,
)

OBSERVED = "2026-10-24T12:00:00Z"
ARS, CHE = 900001, 900002
CROSSWALK = {700001: 501, 700002: 502, 700003: 503}
#: Invented ids on purpose: the real ones are read from the provider, never written in code.
NAMES = {9100 + i: name for i, name in enumerate(STAT_COLUMNS)}
ID = {name: type_id for type_id, name in NAMES.items()}
FPL = [FplFixture(301, "ARS", "CHE")]


def _detail(name, value):
    return {"type_id": ID[name], "data": {"value": value}}


def _row(pid, team, *details, starter=True):
    return {"id": pid, "player_id": pid, "team_id": team, "type_id": 11 if starter else 12,
            "formation_field": None, "details": list(details)}


def _fixture(rows, state="FT"):
    return {"id": 800001, "league_id": 8, "starting_at": "2026-10-24 14:00:00", "state": {"developer_name": state},
            "participants": [{"id": ARS, "name": "Arsenal", "short_code": "ARS", "meta": {"location": "home"}},
                             {"id": CHE, "name": "Chelsea", "short_code": "CHE", "meta": {"location": "away"}}],
            "lineups": rows, "formations": [], "metadata": []}


def _derive(rows, state="FT", names=NAMES):
    return derive(observed_at=OBSERVED, season="2026-27", pl_fixtures=[_fixture(rows, state)], squads=[], sidelined=[],
                  team_fixtures=[], fpl_fixtures=FPL, team_codes={ARS: "ARS", CHE: "CHE"}, crosswalk=CROSSWALK,
                  stat_type_names=names)


FULL = [_detail(n, v) for n, v in (
    ("MINUTES_PLAYED", 90), ("RATING", 7.4), ("TOUCHES", 61), ("PASSES", 40), ("ACCURATE_PASSES", 35),
    ("KEY_PASSES", 2), ("LONG_BALLS", 4), ("THROUGH_BALLS", 1), ("BACKWARD_PASSES", 9), ("PASSES_IN_FINAL_THIRD", 12),
    ("SHOTS_TOTAL", 3), ("SHOTS_ON_TARGET", 2), ("DUELS_WON", 5), ("TACKLES", 3), ("INTERCEPTIONS", 1),
    ("BALL_RECOVERY", 6), ("SUCCESSFUL_DRIBBLES", 2))]
COUNTS = [n for n, (_c, kind) in STAT_COLUMNS.items() if kind == "count" and n != "MINUTES_PLAYED"]


# ------------------------------------------------------------------ the type map

def test_type_names_come_from_the_rows_the_provider_sent():
    rows = [{"type_id": 5, "type_name": "TOUCHES"}, {"type_id": 5, "type_name": "TOUCHES"},
            {"type_id": 6, "type_name": "PASSES"}, {"type_id": 7}, {"type_id": "x", "type_name": "Y"}]
    assert type_names(rows) == {5: "TOUCHES", 6: "PASSES"}


def test_one_id_with_two_names_is_an_error_not_a_guess():
    with pytest.raises(ValueError):
        type_names([{"type_id": 5, "type_name": "TOUCHES"}, {"type_id": 5, "type_name": "PASSES"}])


def test_every_curated_statistic_is_read_and_unmapped_types_are_ignored():
    stats = lineup_stats(_row(700001, ARS, *FULL, {"type_id": 424242, "data": {"value": 99}}), NAMES)
    assert set(stats) == set(PLAYER_MATCH_STATS_COLUMNS) - {"element", "fixture_id", "team", "observed_at"}
    assert (stats["touches"], stats["backward_passes"], stats["passes_final_third"], stats["rating"]) == (61, 9, 12, 7.4)
    assert stats["starter"] is True and stats["minutes"] == 90


# ------------------------------------------------------- absent = zero, per field

@pytest.mark.parametrize("name", COUNTS)
def test_a_statistic_the_provider_left_out_is_zero_for_a_player_with_minutes(name):
    column = STAT_COLUMNS[name][0]
    others = [d for d in FULL if d["type_id"] != ID[name]]
    with_it, without = lineup_stats(_row(700001, ARS, *FULL), NAMES), lineup_stats(_row(700001, ARS, *others), NAMES)
    assert with_it[column] > 0 and without[column] == 0 and isinstance(without[column], int)
    assert {k: v for k, v in without.items() if k != column} == {k: v for k, v in with_it.items() if k != column}


def test_an_unrated_appearance_has_no_rating_not_a_zero_rating():
    stats = lineup_stats(_row(700001, ARS, _detail("MINUTES_PLAYED", 2), _detail("TOUCHES", 1), starter=False), NAMES)
    assert stats["rating"] is None and stats["starter"] is False and stats["minutes"] == 2


@pytest.mark.parametrize("details", [[], [_detail("TOUCHES", 3)], [_detail("MINUTES_PLAYED", 0)]])
def test_a_player_without_minutes_has_no_row(details):
    assert lineup_stats(_row(700001, ARS, *details, starter=False), NAMES) is None


def test_a_non_numeric_value_is_ignored_not_coerced():
    stats = lineup_stats(_row(700001, ARS, _detail("MINUTES_PLAYED", 90), _detail("TOUCHES", "many"),
                              _detail("PASSES", True)), NAMES)
    assert stats["touches"] == 0 and stats["passes"] == 0


# --------------------------------------------------------------------- derive

def test_derive_keys_rows_by_the_fpl_element_and_fixture_and_drops_provider_ids():
    out = _derive([_row(700001, ARS, *FULL), _row(700002, CHE, _detail("MINUTES_PLAYED", 30), starter=False),
                   _row(700003, CHE, starter=False), _row(799999, CHE, *FULL)])
    rows = {r["element"]: r for r in out.player_match_stats}
    assert set(rows) == {501, 502}                      # 700003 played no minutes; 799999 is unmatched
    assert rows[501]["fixture_id"] == 301 and rows[501]["team"] == "ARS" and rows[501]["observed_at"] == OBSERVED
    assert rows[502]["team"] == "CHE" and rows[502]["touches"] == 0
    assert set(rows[501]) == set(PLAYER_MATCH_STATS_COLUMNS)
    assert not any("sportmonks" in c or "provider" in c for c in PLAYER_MATCH_STATS_COLUMNS)
    assert out.report.players_unmatched == 1 and out.report.rows["player_match_stats"] == 2


@pytest.mark.parametrize("state", ["NS", "LIVE", "INPLAY_1ST_HALF"])
def test_a_match_that_is_not_finished_yields_no_statistics(state):
    assert _derive([_row(700001, ARS, *FULL)], state=state).player_match_stats == ()


def test_without_a_type_map_no_statistics_are_derived_and_lineups_are_unchanged():
    out = _derive([_row(700001, ARS, *FULL)], names=None)
    assert out.player_match_stats == () and len(out.lineup_slots) == 1


# ------------------------------------------------------------------- the store

def _tables():
    return _derive([_row(700001, ARS, *FULL)])


def _shift(tables, stamp, **change):
    return replace(tables, player_match_stats=tuple({**r, "observed_at": stamp, **change}
                                                   for r in tables.player_match_stats))


def test_a_build_carries_the_table_and_validates(tmp_path):
    build = write_build(_tables(), CROSSWALK, tmp_path, build_id="one", built_at=OBSERVED)
    assert validate_build(build)["row_counts"]["player_match_stats"] == 1
    frame = read_table(build, "player_match_stats")
    assert tuple(frame.columns) == PLAYER_MATCH_STATS_COLUMNS and int(frame.touches.iloc[0]) == 61


def _strip_table(build):
    """Make ``build`` look like one written before R6."""
    (build / "datasets/player_match_stats.parquet").unlink()
    path = build / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["files"]["datasets/player_match_stats.parquet"], manifest["row_counts"]["player_match_stats"]
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_a_build_written_before_r6_still_validates_reads_empty_and_can_be_extended(tmp_path):
    old = write_build(_tables(), CROSSWALK, tmp_path, build_id="old", built_at=OBSERVED)
    _strip_table(old)
    validate_build(old)
    assert read_table(old, "player_match_stats").empty and OPTIONAL_TABLES == {"player_match_stats"}
    new = write_build(_tables(), CROSSWALK, tmp_path, build_id="new", built_at=OBSERVED, previous=old)
    assert validate_build(new)["row_counts"]["player_match_stats"] == 1


def test_a_required_table_missing_is_still_refused(tmp_path):
    build = write_build(_tables(), CROSSWALK, tmp_path, build_id="one", built_at=OBSERVED)
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    del manifest["files"]["datasets/lineup_slots.parquet"], manifest["row_counts"]["lineup_slots"]
    (build / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(LicensedStoreError):
        validate_build(build)


def test_a_manifest_that_lists_the_file_but_not_its_count_is_refused(tmp_path):
    build = write_build(_tables(), CROSSWALK, tmp_path, build_id="one", built_at=OBSERVED)
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    del manifest["row_counts"]["player_match_stats"]
    (build / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(LicensedStoreError):
        validate_build(build)


def test_a_reread_that_changed_nothing_adds_no_row_but_a_changed_one_does(tmp_path):
    first = write_build(_tables(), CROSSWALK, tmp_path, build_id="one", built_at=OBSERVED)
    second = write_build(_shift(_tables(), "2026-10-25T05:00:00Z"), CROSSWALK, tmp_path, build_id="two",
                         built_at=OBSERVED, previous=first)
    assert len(read_table(second, "player_match_stats")) == 1                       # nothing new to say
    third = write_build(_shift(_tables(), "2026-10-26T05:00:00Z", touches=62), CROSSWALK, tmp_path,
                        build_id="three", built_at=OBSERVED, previous=second)
    assert sorted(read_table(third, "player_match_stats").touches.astype(int)) == [61, 62]   # the correction is kept


def test_new_information_compares_the_latest_observation_per_player_and_fixture():
    old = [{"element": 1, "fixture_id": 9, "observed_at": "a", "touches": 5, "rating": None},
           {"element": 1, "fixture_id": 9, "observed_at": "b", "touches": 6, "rating": None}]
    same_as_latest = {"element": 1, "fixture_id": 9, "observed_at": "c", "touches": 6, "rating": None}
    same_as_oldest = {"element": 1, "fixture_id": 9, "observed_at": "c", "touches": 5, "rating": None}
    other = {"element": 2, "fixture_id": 9, "observed_at": "c", "touches": 6, "rating": None}
    assert new_information(old, [same_as_latest, same_as_oldest, other]) == [same_as_oldest, other]


def test_the_runtime_handle_serves_the_table_and_an_old_build_as_empty(tmp_path):
    build = write_build(_tables(), CROSSWALK, tmp_path, build_id="one", built_at=OBSERVED)
    (tmp_path / POINTER_NAME).write_bytes(encode_pointer("one", hashlib.sha256((build / "manifest.json").read_bytes()).hexdigest()))
    assert len(LicensedRuntimeHandle(tmp_path).table("player_match_stats")) == 1
    _strip_table(build)
    (tmp_path / POINTER_NAME).write_bytes(encode_pointer("one", hashlib.sha256((build / "manifest.json").read_bytes()).hexdigest()))
    assert LicensedRuntimeHandle(tmp_path).table("player_match_stats").empty
