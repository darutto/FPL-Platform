"""
Tests for Track D / FI0 + FI1 — fixture_outlook engine.

Covers:
* FI0  two-axis difficulty model: quintile bucketing, venue-aware opponent
       strength selection, graceful fallback to official FDR.
* FI1  run/tendency detection: ≥3 run length, strong/mild grading, neutral &
       blank breaks; Spanish schedule-only verdict (no buy/sell language).
* Public entry points: get_team_outlook, get_all_team_outlooks.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os

import pytest

# Load fixture_outlook directly from its file, bypassing
# fpl_grounded_assistant/__init__.py (which pulls the dispatcher/harness graph
# and a stale captain-engine path).  fixture_outlook is pure stdlib, so it
# loads standalone with no sys.path setup — mirroring the repo test convention.
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_MOD_PATH = _os.path.join(
    _os.path.dirname(_HERE), "fpl_grounded_assistant", "fixture_outlook.py"
)
_spec = _ilu.spec_from_file_location("fixture_outlook", _MOD_PATH)
fixture_outlook = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(fixture_outlook)

_bucket = fixture_outlook._bucket
_classify = fixture_outlook._classify
_fixture_band = fixture_outlook._fixture_band
_quintile_thresholds = fixture_outlook._quintile_thresholds
_teams_by_id = fixture_outlook._teams_by_id
build_axis_thresholds = fixture_outlook.build_axis_thresholds
build_verdict = fixture_outlook.build_verdict
detect_runs = fixture_outlook.detect_runs
get_all_team_outlooks = fixture_outlook.get_all_team_outlooks
get_team_outlook = fixture_outlook.get_team_outlook


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

def _fx(gw: int, opp: int, is_home: bool, difficulty: int = 3) -> dict:
    return {"gameweek": gw, "opponent_team": opp, "is_home": is_home,
            "difficulty": difficulty}


def _fallback_bootstrap() -> dict:
    """3 teams, NO strength fields → difficulty model falls back to FDR.

    This makes per-fixture bands exactly equal to the ``difficulty`` we set,
    so run/series logic can be tested deterministically.
    Current GW = 1.
    """
    return {
        "teams": [
            {"id": 1, "name": "Arsenal",   "short_name": "ARS"},
            {"id": 2, "name": "Brentford", "short_name": "BRE"},
            {"id": 3, "name": "Chelsea",   "short_name": "CHE"},
        ],
        "events": [{"id": 1, "is_current": True}],
        "team_fixtures": {},
    }


def _strength_team(tid: int, name: str, short: str, *,
                   atk_h: int, atk_a: int, def_h: int, def_a: int) -> dict:
    return {"id": tid, "name": name, "short_name": short,
            "strength_attack_home": atk_h, "strength_attack_away": atk_a,
            "strength_defence_home": def_h, "strength_defence_away": def_a}


# ---------------------------------------------------------------------------
# FI0 — bucketing
# ---------------------------------------------------------------------------

def test_quintile_thresholds_need_min_data():
    assert _quintile_thresholds([1, 2, 3]) is None       # < 5 values
    th = _quintile_thresholds([10, 20, 30, 40, 50])
    assert th is not None and len(th) == 4
    assert th == sorted(th)                               # ascending


def test_bucket_low_strength_is_easy():
    th = [1150, 1200, 1250, 1350]
    assert _bucket(1100, th) == 1     # weakest opponent → easiest
    assert _bucket(1300, th) == 4
    assert _bucket(9999, th) == 5     # above top cut → hardest


def test_bucket_is_monotonic():
    th = [1150, 1200, 1250, 1350]
    bands = [_bucket(v, th) for v in (1000, 1175, 1225, 1300, 1400)]
    assert bands == sorted(bands)


# ---------------------------------------------------------------------------
# FI0 — venue-aware opponent strength selection
# ---------------------------------------------------------------------------

def test_fixture_band_uses_opponent_venue_field_for_attack():
    # Opponent strong-defence at home, weak away.
    opp = _strength_team(2, "Brentford", "BRE",
                         atk_h=1100, atk_a=1100, def_h=1300, def_a=1100)
    teams_by_id = {2: opp}
    th = [1150, 1200, 1250, 1350]

    # We play HOME → opponent AWAY → uses strength_defence_away (1100) → easy.
    band_home = _fixture_band(_fx(1, 2, True), "attack", teams_by_id, th)
    # We play AWAY → opponent HOME → uses strength_defence_home (1300) → hard.
    band_away = _fixture_band(_fx(1, 2, False), "attack", teams_by_id, th)

    assert band_home == 1
    assert band_away == 4
    assert band_home < band_away


def test_fixture_band_defence_axis_reads_opponent_attack():
    opp = _strength_team(2, "Brentford", "BRE",
                         atk_h=1400, atk_a=1100, def_h=1100, def_a=1100)
    teams_by_id = {2: opp}
    th = [1150, 1200, 1250, 1350]
    # We HOME → opponent AWAY → strength_attack_away (1100) → easy clean sheet.
    assert _fixture_band(_fx(1, 2, True), "defence", teams_by_id, th) == 1
    # We AWAY → opponent HOME → strength_attack_home (1400) → hard.
    assert _fixture_band(_fx(1, 2, False), "defence", teams_by_id, th) == 5


def test_fixture_band_falls_back_to_fdr_without_strength():
    # No thresholds / unknown opponent → use the fixture's own difficulty.
    assert _fixture_band(_fx(1, 99, True, difficulty=4), "attack", {}, None) == 4
    # Out-of-range / missing FDR → neutral band 3.
    assert _fixture_band({"opponent_team": 99, "is_home": True}, "attack", {}, None) == 3


def test_build_axis_thresholds_pools_both_venues():
    teams = [
        _strength_team(i, f"T{i}", f"T{i}",
                       atk_h=1000 + i, atk_a=1010 + i,
                       def_h=1100 + i, def_a=1110 + i)
        for i in range(1, 6)
    ]
    th = build_axis_thresholds({"teams": teams}, "attack")
    assert th is not None and len(th) == 4
    # Too few teams → None.
    assert build_axis_thresholds({"teams": teams[:2]}, "attack") is None


# ---------------------------------------------------------------------------
# FI1 — classification + run detection
# ---------------------------------------------------------------------------

def test_classify_bands():
    assert _classify(1) == "good"
    assert _classify(2) == "good"
    assert _classify(3) == "neutral"
    assert _classify(4) == "bad"
    assert _classify(5) == "bad"
    assert _classify(None) == "blank"


def _series(bands: list[int | None], start_gw: int = 1) -> list[dict]:
    return [
        {"gameweek": start_gw + i, "band": b, "klass": _classify(b),
         "is_dgw": False, "is_bgw": b is None, "fixtures": []}
        for i, b in enumerate(bands)
    ]


def test_detect_runs_grades_mild_and_strong():
    # 3 good (mild) then 5 bad (strong).
    series = _series([2, 2, 2, 5, 5, 5, 5, 5])
    runs = detect_runs(series)
    assert len(runs) == 2
    good, bad = runs
    assert good["type"] == "good" and good["length"] == 3 and good["intensity"] == "mild"
    assert good["start_gw"] == 1 and good["end_gw"] == 3
    assert bad["type"] == "bad" and bad["length"] == 5 and bad["intensity"] == "strong"
    assert bad["start_gw"] == 4 and bad["end_gw"] == 8


def test_short_streaks_are_not_runs():
    # Two good GWs is below the 3-GW threshold.
    assert detect_runs(_series([2, 2, 4, 2, 2])) == []


def test_neutral_breaks_runs():
    # good,good,NEUTRAL,good,good → no run of length ≥3.
    assert detect_runs(_series([2, 2, 3, 2, 2])) == []
    # good x2, neutral, good x3 → only the trailing triple counts.
    runs = detect_runs(_series([2, 2, 3, 1, 1, 1]))
    assert len(runs) == 1 and runs[0]["length"] == 3


def test_blank_breaks_runs():
    runs = detect_runs(_series([2, 2, None, 2, 2]))
    assert runs == []


# ---------------------------------------------------------------------------
# FI1 — verdict (Spanish, schedule-only)
# ---------------------------------------------------------------------------

_FORBIDDEN = ("fichar", "vender", "compra", "venta", "transfer", "buy", "sell",
              "capitán", "captain")


def _assert_schedule_only(text: str):
    low = text.lower()
    for word in _FORBIDDEN:
        assert word not in low, f"verdict leaked advice word: {word!r} in {text!r}"


def test_verdict_attack_good_run_is_schedule_only():
    series = _series([2, 2, 2, 2, 2])
    runs = detect_runs(series)
    v = build_verdict(runs, "attack", series)
    assert "ofensiv" in v.lower()
    assert "J1" in v and "J5" in v
    _assert_schedule_only(v)


def test_verdict_defence_and_empty_cases():
    series = _series([1, 1, 1])
    v = build_verdict(detect_runs(series), "defence", series)
    assert "porter" in v.lower()
    _assert_schedule_only(v)

    assert "Sin fixtures" in build_verdict([], "attack", [])
    no_runs_series = _series([3, 3, 3])
    assert "sin rachas" in build_verdict([], "attack", no_runs_series).lower()


def test_verdict_picks_earliest_run():
    # bad run first (gw1-3), good run later (gw5-7); earliest should win.
    series = _series([5, 5, 5, 3, 1, 1, 1])
    v = build_verdict(detect_runs(series), "attack", series)
    assert "duras" in v.lower() and "J1" in v


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def test_get_team_outlook_end_to_end_fallback():
    bs = _fallback_bootstrap()
    # Arsenal (id 1): easy run then hard run, via FDR fallback.
    bs["team_fixtures"] = {
        1: [_fx(1, 2, True, 2), _fx(2, 3, False, 2), _fx(3, 2, True, 1),
            _fx(4, 3, False, 5), _fx(5, 2, False, 5), _fx(6, 3, True, 4)],
    }
    out = get_team_outlook(bs, 1, "attack", horizon=10)
    assert out["team_short"] == "ARS"
    assert out["axis"] == "attack"
    assert [e["band"] for e in out["series"]] == [2, 2, 1, 5, 5, 4]
    types = {r["type"] for r in out["runs"]}
    assert types == {"good", "bad"}
    _assert_schedule_only(out["verdict"])


def test_get_team_outlook_marks_dgw():
    bs = _fallback_bootstrap()
    # Two fixtures in GW1 → DGW; mean of (2,4)=3.
    bs["team_fixtures"] = {1: [_fx(1, 2, True, 2), _fx(1, 3, False, 4),
                               _fx(2, 2, True, 3)]}
    out = get_team_outlook(bs, 1, "attack", horizon=5)
    gw1 = out["series"][0]
    assert gw1["is_dgw"] is True
    assert gw1["band"] == 3
    assert len(gw1["fixtures"]) == 2


def test_get_team_outlook_marks_bgw():
    bs = _fallback_bootstrap()
    # Arsenal blanks GW2 while Brentford plays it → active BGW.
    bs["team_fixtures"] = {
        1: [_fx(1, 2, True, 2), _fx(3, 3, True, 2)],
        2: [_fx(1, 1, False, 3), _fx(2, 3, True, 3), _fx(3, 1, False, 3)],
    }
    out = get_team_outlook(bs, 1, "attack", horizon=3)
    gw_by_num = {e["gameweek"]: e for e in out["series"]}
    assert gw_by_num[2]["is_bgw"] is True
    assert gw_by_num[2]["band"] is None


def test_get_all_team_outlooks_orders_easiest_first():
    bs = _fallback_bootstrap()
    bs["team_fixtures"] = {
        1: [_fx(1, 2, True, 2), _fx(2, 3, False, 2)],   # easy → low avg
        2: [_fx(1, 1, False, 5), _fx(2, 3, True, 5)],   # hard → high avg
        3: [_fx(1, 3, True, 3), _fx(2, 1, False, 3)],   # mid
    }
    res = get_all_team_outlooks(bs, "attack", horizon=5)
    assert res["status"] == "ok"
    shorts = [t["team_short"] for t in res["teams"]]
    assert shorts[0] == "ARS"     # easiest first
    assert shorts[-1] == "BRE"    # hardest last


def test_get_all_team_outlooks_missing_context():
    bs = _fallback_bootstrap()  # no team_fixtures
    res = get_all_team_outlooks(bs, "attack")
    assert res["status"] == "missing_context"


def test_teams_by_id_helper():
    bs = _fallback_bootstrap()
    by_id = _teams_by_id(bs)
    assert by_id[1]["short_name"] == "ARS"
