"""R6 two players side by side: per-90 winners, the shared gameweek axis and the trend mark. Pure, synthetic input."""
from __future__ import annotations

import pytest

from football_intelligence.player_involvement import TREND_MIN_POINTS, compare, trend


def _m(gw, touches=60, key=1, passes=40, minutes=90):
    return {"gameweek": gw, "touches": touches, "key_passes": key, "passes": passes, "minutes": minutes}


def _answer(name, matches, **avg):
    """An ``analyse``-shaped ok answer; ``matches`` are given oldest first and listed latest first, as analyse does."""
    base = {"matches": len(matches), "touches_per90": 55.0, "key_passes_per90": 1.0, "passes_per90": 40.0,
            "pass_accuracy_pct": 80.0, "backward_share_pct": 20.0}
    return {"status": "ok", "player": {"player_id": hash(name) % 1000, "web_name": name, "team_short": "XXX"},
            "matches": list(reversed(matches)), "averages": {**base, **avg},
            "sample": {"matches_with_stats": len(matches), "listed": len(matches), "small_sample": len(matches) < 5}}


# ------------------------------------------------------------------ trend

@pytest.mark.parametrize("values, expected", [
    ([50, 52, 55, 58, 61, 64], "up"),
    ([66, 61, 58, 55, 52, 50], "down"),
    ([55, 56, 55, 54, 55, 56], "flat"),
    ([0, 0, 0], "flat"),                       # a zero mean has no direction
])
def test_trend_reads_the_least_squares_slope_against_three_percent_of_the_mean(values, expected):
    assert trend(values) == expected


def test_fewer_than_three_known_values_have_no_trend():
    assert TREND_MIN_POINTS == 3
    assert trend([40, 80]) is None
    assert trend([None, 40, None, 80, None]) is None          # gaps are not points


def test_unknown_values_are_skipped_never_read_as_zero():
    # read as zero, the two gaps would pull the line down; skipped, three rising values are up
    assert trend([10, None, 20, None, 30]) == "up"


# ------------------------------------------------------------------ per 90

def test_the_higher_per90_wins_and_the_backward_share_never_does():
    out = compare(_answer("Palmer", [_m(1)], touches_per90=55.1, key_passes_per90=2.4, backward_share_pct=23.0),
                  _answer("Saka", [_m(1)], touches_per90=56.4, key_passes_per90=1.4, backward_share_pct=12.0))
    rows = {r["metric"]: r for r in out["per90"]}
    assert [r["metric"] for r in out["per90"]] == ["touches", "key_passes", "passes", "pass_accuracy", "backward_share"]
    assert rows["touches"]["winner"] == "b" and rows["key_passes"]["winner"] == "a"
    assert rows["backward_share"]["winner"] is None


def test_a_tie_at_the_shown_precision_has_no_winner_for_counts_and_percentages():
    out = compare(_answer("A", [_m(1)], touches_per90=55.04, pass_accuracy_pct=80.04),
                  _answer("B", [_m(1)], touches_per90=55.0, pass_accuracy_pct=80.0))
    rows = {r["metric"]: r for r in out["per90"]}
    assert rows["touches"]["winner"] is None and rows["pass_accuracy"]["winner"] is None
    assert rows["passes"]["winner"] is None                   # equal defaults


def test_an_unknown_per90_has_no_winner():
    out = compare(_answer("A", [_m(1)], key_passes_per90=None), _answer("B", [_m(1)], key_passes_per90=3.0))
    row = next(r for r in out["per90"] if r["metric"] == "key_passes")
    assert row["a"] is None and row["winner"] is None


# ------------------------------------------------------------------ series

def test_one_gameweek_axis_oldest_first_with_a_gap_where_only_one_played():
    out = compare(_answer("A", [_m(4, 58), _m(5, 49), _m(7, 57)]), _answer("B", [_m(4, 66), _m(6, 58), _m(7, 55)]))
    s = out["series"]
    assert s["gameweeks"] == [4, 5, 6, 7]
    assert s["a"]["touches"] == [58, 49, None, 57]
    assert s["b"]["touches"] == [66, None, 58, 55]


def test_an_unknown_value_is_a_gap_in_the_series():
    out = compare(_answer("A", [_m(1, touches=None), _m(2, 50)]), _answer("B", [_m(1, 40), _m(2, 41)]))
    assert out["series"]["a"]["touches"] == [None, 50]


def test_a_double_gameweek_is_two_points_with_the_same_label_never_averaged():
    out = compare(_answer("A", [_m(24, 30), _m(24, 70), _m(25, 50)]), _answer("B", [_m(24, 60), _m(25, 61)]))
    s = out["series"]
    assert s["gameweeks"] == [24, 24, 25]
    assert s["a"]["touches"] == [30, 70, 50]
    assert s["b"]["touches"] == [60, None, 61]


def test_trends_and_samples_come_with_the_block():
    up = [_m(gw, t) for gw, t in zip(range(1, 7), (50, 52, 55, 58, 61, 64))]
    down = [_m(gw, t) for gw, t in zip(range(1, 7), (66, 61, 58, 55, 52, 50))]
    out = compare(_answer("A", up), _answer("B", down[:2]))
    assert out["trends"]["a"]["touches"] == "up"
    assert out["trends"]["b"]["touches"] is None             # two matches: no mark
    assert out["sample"]["a"]["listed"] == 6 and out["sample"]["b"]["small_sample"] is True
    assert out["players"]["b"]["web_name"] == "B" and out["claim_status"] == "observed"
