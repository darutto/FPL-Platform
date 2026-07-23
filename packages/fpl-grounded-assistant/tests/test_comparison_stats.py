"""
Tests for comparison_stats.py — additive raw-stat comparison table for
compare_players (appended below the existing verdict, never replacing it).

Covers, in isolation from comparison.py/final_response.py wiring:
  * position-pairing row-set selection (GKP/GKP, DEF/DEF, MID/FWD, GKP/FWD mixed)
  * numeric coercion (strings, booleans, NaN/inf, negatives per-field)
  * missing-vs-zero semantics (omit / placeholder / real value)
  * the rounding-tie rule (no highlight when displays are equal)
  * empty-table -> None contract
  * stat_comparison_from_dict per-row malformed-input handling
  * per-90 derivation fallback + enriched-field precedence
  * xgi_per_90 matching comparison.py's own formula
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
from fpl_grounded_assistant.comparison_stats import (  # noqa: E402
    PlayerStatSource,
    StatCell,
    StatRow,
    StatComparisonMeta,
    build_player_stat_source,
    build_stat_comparison,
    stat_comparison_from_dict,
    _finite_number,
    _per_90,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _source(
    position: str,
    *,
    form=5.0, total_points=50, price_m=8.0, ownership_percent=10.0,
    goals=2, assists=1, xgi_per_90=0.3, saves_per_90=0.0, clean_sheets_per_90=0.2,
) -> PlayerStatSource:
    return PlayerStatSource(
        position=position, form=form, total_points=total_points, price_m=price_m,
        ownership_percent=ownership_percent, goals=goals, assists=assists,
        xgi_per_90=xgi_per_90, saves_per_90=saves_per_90, clean_sheets_per_90=clean_sheets_per_90,
    )


def _rows_by_key(result: "dict") -> "dict[str, dict]":
    return {r["key"]: r for r in result["rows"]}


# ---------------------------------------------------------------------------
# Position-pairing row-set selection
# ---------------------------------------------------------------------------

def test_gkp_vs_gkp_rows():
    a = _source("GKP", saves_per_90=3.0, clean_sheets_per_90=0.3)
    b = _source("GKP", saves_per_90=2.0, clean_sheets_per_90=0.25)
    result = build_stat_comparison(a, b)
    keys = set(_rows_by_key(result).keys())
    assert keys == {"form", "total_points", "price_m", "ownership_percent",
                    "saves_per_90", "clean_sheets_per_90"}
    assert _rows_by_key(result)["saves_per_90"]["better"] == "a"


def test_def_vs_def_rows():
    a = _source("DEF")
    b = _source("DEF")
    result = build_stat_comparison(a, b)
    keys = set(_rows_by_key(result).keys())
    assert "clean_sheets_per_90" in keys
    assert "goals" in keys and "assists" in keys and "xgi_per_90" in keys
    assert "saves_per_90" not in keys
    # explicit regression guard: dc_per_90/bonus never appear as row keys
    assert "dc_per_90" not in keys
    assert "bonus" not in keys


def test_mid_vs_fwd_rows():
    a = _source("MID")
    b = _source("FWD")
    result = build_stat_comparison(a, b)
    keys = set(_rows_by_key(result).keys())
    assert keys == {"form", "total_points", "price_m", "ownership_percent",
                    "goals", "assists", "xgi_per_90"}


def test_gkp_vs_fwd_mixed_rows_show_real_values_but_suppress_highlight():
    a = _source("GKP", saves_per_90=3.0, clean_sheets_per_90=0.3, goals=0, assists=0)
    b = _source("FWD", saves_per_90=0.0, clean_sheets_per_90=0.1, goals=10, assists=5)
    result = build_stat_comparison(a, b)
    rows = _rows_by_key(result)
    # union of GK rows + attacking rows
    assert set(rows.keys()) == {"form", "total_points", "price_m", "ownership_percent",
                                 "saves_per_90", "clean_sheets_per_90", "goals", "assists", "xgi_per_90"}
    # real values shown on both sides, never a placeholder standing in for "wrong position"
    assert rows["goals"]["value_a"]["display"] == "0"
    assert rows["goals"]["value_b"]["display"] == "10"
    assert rows["saves_per_90"]["value_a"]["display"] != "—"
    assert rows["saves_per_90"]["value_b"]["display"] != "—"
    # but highlight suppressed on every non-universal row regardless of the numbers
    for key in ("saves_per_90", "clean_sheets_per_90", "goals", "assists", "xgi_per_90"):
        assert rows[key]["better"] is None
    # universal rows still highlight normally
    assert rows["form"]["kind"] == "performance"


def test_unknown_position_falls_back_to_universal_rows_only():
    a = _source("XYZ")
    b = _source("ALSO_UNKNOWN")
    result = build_stat_comparison(a, b)
    keys = set(_rows_by_key(result).keys())
    assert keys == {"form", "total_points", "price_m", "ownership_percent"}


def test_lowercase_whitespace_position_normalizes():
    element = {"now_cost": 80, "form": "5.0", "selected_by_percent": "10.0",
               "total_points": 50, "goals_scored": 2, "assists": 1,
               "expected_goal_involvements": "2.7", "minutes": 900,
               "saves_per_90": 0, "clean_sheets_per_90": 0.2}
    src_lower = build_player_stat_source(element, "  gkp ")
    assert src_lower.position == "GKP"


# ---------------------------------------------------------------------------
# Missing vs zero
# ---------------------------------------------------------------------------

def test_both_none_omits_row():
    a = _source("MID", xgi_per_90=None)
    b = _source("FWD", xgi_per_90=None)
    result = build_stat_comparison(a, b)
    assert "xgi_per_90" not in _rows_by_key(result)


def test_one_none_renders_placeholder_and_suppresses_highlight():
    a = _source("MID", goals=None)
    b = _source("FWD", goals=5)
    result = build_stat_comparison(a, b)
    row = _rows_by_key(result)["goals"]
    assert row["value_a"]["display"] == "—"
    assert row["value_a"]["value"] is None
    assert row["value_b"]["display"] == "5"
    assert row["better"] is None


def test_both_zero_is_a_real_compared_value_not_missing():
    a = _source("MID", goals=0)
    b = _source("FWD", goals=0)
    result = build_stat_comparison(a, b)
    row = _rows_by_key(result)["goals"]
    assert row["value_a"]["display"] == "0"
    assert row["value_b"]["display"] == "0"
    assert row["better"] is None  # tie, not omitted


def test_empty_table_returns_none():
    a = PlayerStatSource(position="GKP", form=None, total_points=None, price_m=None,
                          ownership_percent=None, goals=None, assists=None,
                          xgi_per_90=None, saves_per_90=None, clean_sheets_per_90=None)
    b = PlayerStatSource(position="GKP", form=None, total_points=None, price_m=None,
                          ownership_percent=None, goals=None, assists=None,
                          xgi_per_90=None, saves_per_90=None, clean_sheets_per_90=None)
    assert build_stat_comparison(a, b) is None


# ---------------------------------------------------------------------------
# Rounding-tie rule
# ---------------------------------------------------------------------------

def test_rounding_tie_suppresses_highlight():
    """1.234 vs 1.233 both display '1.23' -> no highlight, even though the
    raw values technically differ. A highlight must be visually justified."""
    a = _source("MID", xgi_per_90=1.234)
    b = _source("FWD", xgi_per_90=1.233)
    result = build_stat_comparison(a, b)
    row = _rows_by_key(result)["xgi_per_90"]
    assert row["value_a"]["display"] == row["value_b"]["display"] == "1.23"
    assert row["better"] is None


def test_genuinely_different_display_values_do_highlight():
    a = _source("MID", xgi_per_90=1.50)
    b = _source("FWD", xgi_per_90=0.30)
    result = build_stat_comparison(a, b)
    row = _rows_by_key(result)["xgi_per_90"]
    assert row["better"] == "a"


# ---------------------------------------------------------------------------
# Numeric coercion
# ---------------------------------------------------------------------------

def test_finite_number_accepts_numeric_strings():
    assert _finite_number("52.3", allow_negative=False) == 52.3


def test_finite_number_rejects_bool():
    assert _finite_number(True, allow_negative=False) is None
    assert _finite_number(False, allow_negative=True) is None


def test_finite_number_rejects_nan_inf():
    assert _finite_number(float("nan"), allow_negative=True) is None
    assert _finite_number(float("inf"), allow_negative=True) is None


def test_finite_number_negative_allowed_only_when_flagged():
    assert _finite_number(-5.0, allow_negative=True) == -5.0
    assert _finite_number(-5.0, allow_negative=False) is None


def test_negative_form_and_points_accepted_as_legitimate():
    element = {"now_cost": 80, "form": "-1.5", "selected_by_percent": "10.0",
               "total_points": -3, "goals_scored": 0, "assists": 0,
               "expected_goal_involvements": 0, "minutes": 900,
               "saves_per_90": 0, "clean_sheets_per_90": 0}
    src = build_player_stat_source(element, "MID")
    assert src.form == -1.5
    assert src.total_points == -3


def test_negative_goals_price_ownership_rejected_as_missing():
    element = {"now_cost": -10, "form": "5.0", "selected_by_percent": "-1.0",
               "total_points": 50, "goals_scored": -2, "assists": -1,
               "expected_goal_involvements": 1.0, "minutes": 900,
               "saves_per_90": 0, "clean_sheets_per_90": 0}
    src = build_player_stat_source(element, "MID")
    assert src.price_m is None
    assert src.ownership_percent is None
    assert src.goals is None
    assert src.assists is None


# ---------------------------------------------------------------------------
# Per-90 derivation fallback + enriched-field precedence
# ---------------------------------------------------------------------------

def test_per_90_derivation():
    assert _per_90(9, 900) == pytest.approx(0.9)
    assert _per_90(9, 0) is None
    assert _per_90(None, 900) is None


def test_enriched_saves_per_90_field_used_when_present():
    element = {"now_cost": 45, "form": "4.0", "selected_by_percent": "1.0",
               "total_points": 20, "goals_scored": 0, "assists": 0,
               "expected_goal_involvements": 0, "minutes": 900,
               "saves_per_90": 2.5, "saves": 999, "clean_sheets_per_90": 0.2}
    src = build_player_stat_source(element, "GKP")
    # enriched field (2.5) used verbatim, NOT recomputed from saves=999/minutes
    assert src.saves_per_90 == 2.5


def test_falls_back_to_derivation_when_enriched_field_missing():
    element = {"now_cost": 45, "form": "4.0", "selected_by_percent": "1.0",
               "total_points": 20, "goals_scored": 0, "assists": 0,
               "expected_goal_involvements": 0, "minutes": 900,
               "saves": 9, "clean_sheets_per_90": 0.2}  # no saves_per_90 key at all
    src = build_player_stat_source(element, "GKP")
    assert src.saves_per_90 == pytest.approx(0.9)  # 9 * 90 / 900


def test_xgi_per_90_matches_derive_scoring_inputs_formula():
    """Regression guard for the deliberate 'self-derive, don't use the
    enriched field' choice — must match comparison.py's own formula exactly."""
    element = {"now_cost": 80, "form": "5.0", "selected_by_percent": "10.0",
               "total_points": 50, "goals_scored": 2, "assists": 1,
               "expected_goal_involvements": 2.7, "minutes": 900,
               "expected_goal_involvements_per_90": 999.0,  # decoy — must be ignored
               "saves_per_90": 0, "clean_sheets_per_90": 0.2}
    src = build_player_stat_source(element, "MID")
    expected = 2.7 / (900 / 90.0)
    assert src.xgi_per_90 == pytest.approx(expected)
    assert src.xgi_per_90 != 999.0


# ---------------------------------------------------------------------------
# stat_comparison_from_dict — malformed-input handling
# ---------------------------------------------------------------------------

def _valid_row_dict(key="goals", better="a", kind="performance"):
    return {
        "key": key, "label": "Goles", "kind": kind,
        "value_a": {"value": 5, "display": "5"},
        "value_b": {"value": 2, "display": "2"},
        "better": better,
    }


def test_from_dict_none_input():
    assert stat_comparison_from_dict(None) is None


def test_from_dict_missing_rows_key():
    assert stat_comparison_from_dict({}) is None


def test_from_dict_valid_roundtrip():
    d = {"rows": [_valid_row_dict()]}
    meta = stat_comparison_from_dict(d)
    assert isinstance(meta, StatComparisonMeta)
    assert len(meta.rows) == 1
    assert meta.rows[0].key == "goals"
    assert meta.rows[0].better == "a"


def test_from_dict_invalid_better_coerced_to_none():
    d = {"rows": [_valid_row_dict(better="bogus")]}
    meta = stat_comparison_from_dict(d)
    assert meta.rows[0].better is None


def test_from_dict_invalid_kind_coerced_to_context_and_better_forced_none():
    d = {"rows": [_valid_row_dict(kind="bogus", better="a")]}
    meta = stat_comparison_from_dict(d)
    assert meta.rows[0].kind == "context"
    assert meta.rows[0].better is None


def test_from_dict_row_missing_label_rejected_others_survive():
    bad = _valid_row_dict(key="goals")
    del bad["label"]
    good = _valid_row_dict(key="assists")
    meta = stat_comparison_from_dict({"rows": [bad, good]})
    assert len(meta.rows) == 1
    assert meta.rows[0].key == "assists"


def test_from_dict_all_rows_invalid_returns_none():
    bad = _valid_row_dict()
    del bad["value_a"]
    assert stat_comparison_from_dict({"rows": [bad]}) is None


def test_from_dict_never_raises_on_garbage():
    assert stat_comparison_from_dict("not a dict") is None
    assert stat_comparison_from_dict({"rows": "not a list"}) is None
    assert stat_comparison_from_dict({"rows": [None, 42, "x"]}) is None
