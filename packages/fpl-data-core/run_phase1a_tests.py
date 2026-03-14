#!/usr/bin/env python3
"""
Phase 1a standalone test runner — no pytest required.

Validates fpl_data_core.season_registry, .schemas, and .analytics using
only the Python standard library + pandas + pyyaml (already installed).

Run from fpl-data-core/:
    python3 run_phase1a_tests.py

Exit code: 0 if all pass, 1 if any fail.
"""

import sys
import traceback
from pathlib import Path

# Make fpl_data_core importable from this directory
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Minimal test harness
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_skip = 0
_current_suite = ""


def suite(name: str) -> None:
    global _current_suite
    _current_suite = name
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")


def ok(name: str) -> None:
    global _pass
    _pass += 1
    print(f"  ✓  {name}")


def fail(name: str, err: str) -> None:
    global _fail
    _fail += 1
    print(f"  ✗  {name}")
    print(f"       {err}")


def skip(name: str, reason: str) -> None:
    global _skip
    _skip += 1
    print(f"  ⊘  {name}  [{reason}]")


def run(name: str, fn):
    """Run a zero-arg test function, catching any exception as failure."""
    try:
        fn()
        ok(name)
    except Exception as e:
        fail(name, str(e))


def expect_raises(name: str, exc_type, fn):
    try:
        fn()
        fail(name, f"Expected {exc_type.__name__} but no exception was raised")
    except exc_type:
        ok(name)
    except Exception as e:
        fail(name, f"Expected {exc_type.__name__}, got {type(e).__name__}: {e}")


def assert_close(a: float, b: float, tol: float = 1e-10) -> None:
    assert abs(a - b) < tol, f"Expected {b}, got {a} (diff={abs(a-b):.2e})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(*rows):
    """Build a playermatchstats DataFrame from (player_id, xg, xa, mins) tuples."""
    return pd.DataFrame(rows, columns=["player_id", "xg", "xa", "minutes_played"])


# ============================================================
# §A  season_registry — Smoke Tests
# ============================================================

suite("A · season_registry  —  Smoke Tests")

from fpl_data_core.season_registry import (
    SEASON_REGISTRY, get_season_layout, list_available_seasons,
    register_season, load_registry_from_yaml, SeasonLayout,
)

run("A1  SEASON_REGISTRY contains 2025-2026",
    lambda: assert_close(1, 1) or None or
    (lambda: (assert "2025-2026" in SEASON_REGISTRY or (_ for _ in ()).throw(AssertionError("2025-2026 missing"))))())


# Re-implement cleanly (lambda chains are awkward):
def _a1():
    assert "2025-2026" in SEASON_REGISTRY, "2025-2026 missing"
    assert "2024-2025" in SEASON_REGISTRY, "2024-2025 missing"
run("A1  SEASON_REGISTRY contains both expected seasons", _a1)

def _a2():
    layout = get_season_layout("2025-2026")
    assert isinstance(layout, SeasonLayout)
    assert layout.season == "2025-2026"
run("A2  get_season_layout returns SeasonLayout instance", _a2)

def _a3():
    layout = get_season_layout("2025-2026")
    for attr in ["has_consolidated_files", "player_id_column", "gameweek_column",
                 "gameweek_pattern", "files", "data_root"]:
        assert hasattr(layout, attr), f"Missing attribute: {attr}"
run("A3  SeasonLayout has all required attributes", _a3)

expect_raises("A4  get_season_layout raises KeyError on unknown season",
              KeyError, lambda: get_season_layout("1999-2000"))

def _a5():
    try:
        get_season_layout("1888-1889")
    except KeyError as e:
        assert "Available" in str(e), f"Error message missing 'Available': {e}"
run("A5  KeyError message mentions available seasons", _a5)

def _a6():
    for season in ["2024-2025", "2025-2026"]:
        assert get_season_layout(season).season == season
run("A6  Both registered seasons loadable with correct season string", _a6)

def _a7():
    seasons = list_available_seasons()
    assert "2025-2026" in seasons
    assert "2024-2025" in seasons
run("A7  list_available_seasons returns both seasons", _a7)

def _a8():
    assert get_season_layout("2025-2026").has_consolidated_files is False
run("A8  2025-2026 is not consolidated", _a8)

def _a9():
    assert get_season_layout("2024-2025").has_consolidated_files is True
run("A9  2024-2025 is consolidated", _a9)

def _a10():
    layout = get_season_layout("2025-2026")
    assert "playerstats_gw" in layout.files
    assert "{gw}" in layout.files["playerstats_gw"]
run("A10 2025-2026 has playerstats_gw file key with {gw} placeholder", _a10)

def _a11():
    path = get_season_layout("2025-2026").get_file_path("players")
    assert isinstance(path, Path)
    assert str(path).endswith(".csv")
run("A11 get_file_path returns Path ending in .csv", _a11)

expect_raises("A12 get_file_path raises ValueError for unknown file type",
              ValueError, lambda: get_season_layout("2025-2026").get_file_path("nonexistent_type"))

def _a13():
    path = get_season_layout("2025-2026").get_file_path("playerstats_gw", gameweek=5)
    assert "GW5" in str(path), f"Expected GW5 in path, got {path}"
    assert str(path).endswith(".csv")
run("A13 get_file_path with gameweek=5 interpolates GW5", _a13)

def _a14():
    custom = SeasonLayout(
        season="2099-2100",
        data_root=Path("data/2099-2100"),
        files={"players": "players.csv"},
        player_id_column="id",
        gameweek_column="gw",
        has_consolidated_files=False,
    )
    register_season(custom)
    retrieved = get_season_layout("2099-2100")
    assert retrieved.season == "2099-2100"
run("A14 register_season adds a new season to the registry", _a14)

# ============================================================
# §B  season_registry — Edge Cases
# ============================================================

suite("B · season_registry  —  Edge Cases")

import tempfile, os

def _b1():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "seasons.yaml"
        p.write_text(yaml.dump({
            "seasons": [{
                "season": "2030-2031",
                "data_root": "data/2030-2031",
                "has_consolidated_files": False,
                "player_id_column": "id",
                "gameweek_column": "gw",
                "files": {"players": "players.csv"},
            }]
        }))
        load_registry_from_yaml(p)
        assert "2030-2031" in SEASON_REGISTRY
run("B1  load_registry_from_yaml accepts a custom YAML path", _b1)

def _b2():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "custom.yaml"
        p.write_text(yaml.dump({
            "seasons": [{
                "season": "2031-2032",
                "data_root": "custom/path/2031-2032",
                "has_consolidated_files": True,
                "player_id_column": "player_id",
                "gameweek_column": "event",
                "files": {},
            }]
        }))
        load_registry_from_yaml(p)
        layout = get_season_layout("2031-2032")
        assert "custom/path/2031-2032" in str(layout.data_root)
run("B2  custom YAML data_root is preserved on the SeasonLayout", _b2)

def _b3():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "empty.yaml"
        p.write_text(yaml.dump({"seasons": []}))
        load_registry_from_yaml(p)  # should not raise
run("B3  empty seasons list in YAML does not crash", _b3)

def _b4():
    assert isinstance(get_season_layout("2025-2026").data_root, Path)
run("B4  data_root is stored as a Path, not a string", _b4)

def _b5():
    for season in ["2024-2025", "2025-2026"]:
        layout = get_season_layout(season)
        assert "{gw}" in layout.gameweek_pattern
run("B5  gameweek_pattern contains {gw} for all seasons", _b5)


# ============================================================
# §C  schemas — Smoke Tests
# ============================================================

suite("C · schemas  —  Smoke Tests")

from fpl_data_core.schemas import (
    ID_COLS, CUMULATIVE_COLS, SNAPSHOT_COLS,
    TOURNAMENT_NAME_MAP, EXCLUDED_TOURNAMENTS, EXCLUDED_GAMEWEEKS,
    POSITION_MAP, normalise_position,
)

def _c1():
    assert len(CUMULATIVE_COLS) == 26, f"Expected 26, got {len(CUMULATIVE_COLS)}"
run("C1  CUMULATIVE_COLS has exactly 26 entries", _c1)

def _c2():
    assert "expected_goals" in CUMULATIVE_COLS
    assert "ict_index" in CUMULATIVE_COLS
run("C2  CUMULATIVE_COLS contains expected_goals and ict_index", _c2)

def _c3():
    assert "id" in ID_COLS
    assert "web_name" in ID_COLS
run("C3  ID_COLS contains id and web_name", _c3)

def _c4():
    assert "now_cost" in SNAPSHOT_COLS
    assert "form" in SNAPSHOT_COLS
run("C4  SNAPSHOT_COLS contains now_cost and form", _c4)

def _c5():
    overlap = set(CUMULATIVE_COLS) & set(ID_COLS)
    assert not overlap, f"Overlap CUMULATIVE ∩ ID: {overlap}"
run("C5  No overlap between CUMULATIVE_COLS and ID_COLS", _c5)

def _c6():
    overlap = set(CUMULATIVE_COLS) & set(SNAPSHOT_COLS)
    assert not overlap, f"Overlap CUMULATIVE ∩ SNAPSHOT: {overlap}"
run("C6  No overlap between CUMULATIVE_COLS and SNAPSHOT_COLS", _c6)

def _c7():
    for slug in ["premier-league", "champions-league", "efl-cup", "europa-league"]:
        assert slug in TOURNAMENT_NAME_MAP, f"Missing slug: {slug}"
run("C7  TOURNAMENT_NAME_MAP covers all four canonical slugs", _c7)

def _c8():
    assert TOURNAMENT_NAME_MAP["friendly"] == "Friendlies"
run("C8  friendly maps to Friendlies", _c8)

def _c9():
    assert "friendly" in EXCLUDED_TOURNAMENTS
    assert 0 in EXCLUDED_GAMEWEEKS
run("C9  EXCLUDED_TOURNAMENTS and EXCLUDED_GAMEWEEKS have expected entries", _c9)


# ============================================================
# §D  schemas — normalise_position
# ============================================================

suite("D · normalise_position")

POSITION_CASES = [
    # (input, expected)
    (3,            "MID"),
    ("MID",        "MID"),
    ("Midfielder", "MID"),
    (1,            "GKP"),
    (2,            "DEF"),
    (4,            "FWD"),
    ("fwd",        "FWD"),
    ("Forward",    "FWD"),
    ("Striker",    "FWD"),
    ("Goalkeeper", "GKP"),
    ("GK",         "GKP"),
    ("3",          "MID"),   # numeric string
    (99,           "Unknown"),
    ("garbage",    "Unknown"),
]

for _inp, _exp in POSITION_CASES:
    _inp_copy = _inp
    _exp_copy = _exp
    def _make_case(inp, exp):
        def _test():
            result = normalise_position(inp)
            assert result == exp, f"normalise_position({inp!r}) = {result!r}, expected {exp!r}"
        return _test
    run(f"D  normalise_position({_inp_copy!r}) → {_exp_copy!r}", _make_case(_inp_copy, _exp_copy))


# ============================================================
# §E  analytics — compute_rolling_xgi_per_90
# ============================================================

suite("E · analytics  —  compute_rolling_xgi_per_90")

from fpl_data_core.analytics import compute_rolling_xgi_per_90

def _e1():
    df = _df((1, 0.5, 0.3, 90))
    assert compute_rolling_xgi_per_90(df, player_id=999) == 0.0
run("E1  Unknown player → 0.0", _e1)

def _e2():
    df = pd.DataFrame(columns=["player_id", "xg", "xa", "minutes_played"])
    assert compute_rolling_xgi_per_90(df, player_id=1) == 0.0
run("E2  Empty DataFrame → 0.0", _e2)

def _e3():
    df = _df((1, 1.0, 0.5, 0), (1, 0.5, 0.3, 0))
    assert compute_rolling_xgi_per_90(df, player_id=1) == 0.0
run("E3  Zero total minutes → 0.0 (no division by zero)", _e3)

def _e4():
    df = _df((1, 0.9, 0.0, 90))
    assert_close(compute_rolling_xgi_per_90(df, player_id=1), 0.9)
run("E4  Single match: xg=0.9, xa=0.0, mins=90 → 0.9", _e4)

def _e5():
    df = _df(
        (1, 0.5, 0.3, 90),
        (1, 0.5, 0.3, 90),
        (1, 0.5, 0.3, 90),
    )
    # (1.5+0.9)/270*90 = 2.4/3 = 0.8
    assert_close(compute_rolling_xgi_per_90(df, player_id=1), 0.8)
run("E5  3-match lookback: (xg=0.5, xa=0.3, mins=90)×3 → 0.8", _e5)

def _e6():
    df = _df(
        (1, 0.0, 0.0, 90),   # old (excluded by lookback)
        (1, 0.0, 0.0, 90),   # old (excluded by lookback)
        (1, 1.0, 0.0, 90),
        (1, 1.0, 0.0, 90),
        (1, 1.0, 0.0, 90),
    )
    # If only last 3 used → (3.0+0)/270*90 = 1.0
    # If all 5 used      → (3.0+0)/450*90 = 0.6
    result = compute_rolling_xgi_per_90(df, player_id=1, lookback=3)
    assert_close(result, 1.0)
run("E6  Lookback=3 uses only most-recent 3 of 5 rows", _e6)

def _e7():
    df = _df(
        (1, 0.0, 0.0, 90),
        (1, 1.8, 0.0, 90),   # most recent
    )
    assert_close(compute_rolling_xgi_per_90(df, player_id=1, lookback=1), 1.8)
run("E7  Lookback=1 uses only the most recent row", _e7)

def _e8():
    df = _df((1, 0.5, 0.3, 90))
    result = compute_rolling_xgi_per_90(df, player_id=1)
    assert isinstance(result, float)
run("E8  Return type is float", _e8)

def _e9():
    df = _df((1, 0.5, 0.3, 90))
    original = df.copy()
    compute_rolling_xgi_per_90(df, player_id=1)
    pd.testing.assert_frame_equal(df, original)
run("E9  Input DataFrame is not mutated", _e9)

def _e10():
    df = _df(
        (1, 1.0, 0.0, 90),
        (2, 0.0, 0.0, 90),
        (2, 0.0, 0.0, 90),
    )
    p1 = compute_rolling_xgi_per_90(df, player_id=1)
    p2 = compute_rolling_xgi_per_90(df, player_id=2)
    assert_close(p1, 1.0)
    assert p2 == 0.0
run("E10 Stats for two players are isolated from each other", _e10)

def _e11():
    df = _df((1, 0.9, 0.0, 90), (1, 0.9, 0.0, 90))
    # lookback=10 but only 2 rows → all 2 used: (1.8)/180*90 = 0.9
    assert_close(compute_rolling_xgi_per_90(df, player_id=1, lookback=10), 0.9)
run("E11 Lookback > available rows uses all rows (tail semantics)", _e11)

def _e12():
    df = _df((1, 0.3, 0.0, 45), (1, 0.3, 0.0, 45))
    # 0.6 xg, 90 mins total → 0.6/90*90 = 0.6
    assert_close(compute_rolling_xgi_per_90(df, player_id=1), 0.6)
run("E12 Partial minutes (2×45 min): xg=0.3×2, xa=0, mins=90 → 0.6", _e12)

def _e13():
    # Default lookback is 3
    df = _df(
        (1, 0.0, 0.0, 90),
        (1, 0.0, 0.0, 90),
        (1, 1.0, 0.0, 90),
        (1, 1.0, 0.0, 90),
        (1, 1.0, 0.0, 90),
    )
    with_default = compute_rolling_xgi_per_90(df, player_id=1)
    with_explicit = compute_rolling_xgi_per_90(df, player_id=1, lookback=3)
    assert with_default == with_explicit
run("E13 Default lookback equals explicit lookback=3", _e13)


# ============================================================
# §F  Cross-language parity with TypeScript performanceEnricher
# ============================================================

suite("F · analytics  —  Parity with TypeScript performanceEnricher.ts")

def _f1():
    # Haaland-like 3-match window: total_xg+xa=5.22, total_mins=270 → 1.74
    df = _df(
        (1, 1.50, 0.24, 90),
        (1, 1.50, 0.24, 90),
        (1, 1.50, 0.24, 90),
    )
    assert_close(compute_rolling_xgi_per_90(df, player_id=1), 1.74)
run("F1  Haaland-profile (5.22 xgi / 270 mins) → 1.74  (matches epicA.test.ts stdout)", _f1)

def _f2():
    # Mid-tier: (0.9+0.36)/270*90 = 1.26/3 = 0.42
    df = _df(
        (1, 0.30, 0.12, 90),
        (1, 0.30, 0.12, 90),
        (1, 0.30, 0.12, 90),
    )
    assert_close(compute_rolling_xgi_per_90(df, player_id=1), 0.42)
run("F2  Mid-tier profile (1.26 xgi / 270 mins) → 0.42", _f2)


# ============================================================
# Summary
# ============================================================

total = _pass + _fail + _skip
print(f"\n{'═'*60}")
print(f"  Phase 1a — fpl_data_core test results")
print(f"{'═'*60}")
print(f"  Total : {total}")
print(f"  Pass  : {_pass} ✓")
print(f"  Skip  : {_skip} ⊘")
print(f"  Fail  : {_fail} ✗")
print(f"{'═'*60}\n")

sys.exit(0 if _fail == 0 else 1)


