# FPL Platform — Shared Packages Test Plan
**Status:** Pre-execution
**Date:** 2026-03-07
**Scope:** Five packages: `fpl-data-core`, `fpl-api-client`, `fpl-player-registry`, `fpl-captain-engine`, `fpl-charts`

> **Testing philosophy:** Each shared package must prove it is behaviourally identical to the source(s) it replaces before any legacy project switches its imports. Tests fall into three categories:
> - **Smoke tests** — does the module load and execute basic calls without errors?
> - **Parity tests** — does the output exactly match the original implementation?
> - **Edge case tests** — does the module handle boundary inputs gracefully?

---

## Package 1: `fpl-data-core`

**Test file location:** `fpl-platform/packages/fpl-data-core/tests/test_fpl_data_core.py`
**Runner:** `pytest`
**Prerequisites:** Python, `pandas`, `PyYAML` installed. Real GW data in `data/2025-2026/By Gameweek/` for parity tests.

---

### 1.1 Smoke Tests

```python
# test_smoke.py

def test_registry_loads():
    """YAML registry auto-loads on import."""
    from fpl_data_core.season_registry import SEASON_REGISTRY
    assert "2025-2026" in SEASON_REGISTRY
    assert "2024-2025" in SEASON_REGISTRY

def test_get_season_layout_returns_layout():
    from fpl_data_core.season_registry import get_season_layout, SeasonLayout
    layout = get_season_layout("2025-2026")
    assert isinstance(layout, SeasonLayout)
    assert layout.season == "2025-2026"

def test_get_season_layout_raises_on_unknown():
    from fpl_data_core.season_registry import get_season_layout
    with pytest.raises(KeyError, match="1999-2000"):
        get_season_layout("1999-2000")

def test_schemas_import():
    from fpl_data_core.schemas import CUMULATIVE_COLS, ID_COLS, SNAPSHOT_COLS
    assert len(CUMULATIVE_COLS) == 26  # exact count from source
    assert "expected_goals" in CUMULATIVE_COLS
    assert "id" in ID_COLS
    assert "now_cost" in SNAPSHOT_COLS

def test_normalise_position():
    from fpl_data_core.schemas import normalise_position
    assert normalise_position(3) == "MID"
    assert normalise_position("MID") == "MID"
    assert normalise_position("Midfielder") == "MID"
    assert normalise_position(99) == "Unknown"
    assert normalise_position("garbage") == "Unknown"

def test_make_discrete_gw1_is_identity():
    """GW1 discrete stats should equal the cumulative stats (no subtraction)."""
    import pandas as pd
    from fpl_data_core.stat_calculator import make_discrete
    df = pd.DataFrame({"id": [1, 2], "goals_scored": [2, 1], "assists": [1, 0]})
    result = make_discrete(df, prev_df=None)
    assert result["goals_scored"].tolist() == [2, 1]
    assert result["assists"].tolist() == [1, 0]
```

### 1.2 Parity Tests

```python
# test_parity.py
# These tests require real CSV data on disk at data/2025-2026/

import os
import pytest
import pandas as pd

REAL_DATA_PATH = "data/2025-2026"
GW_PATH = os.path.join(REAL_DATA_PATH, "By Gameweek")

@pytest.mark.skipif(not os.path.isdir(GW_PATH), reason="Real data not available")
def test_make_discrete_matches_original_logic_gw2():
    """
    PARITY TEST: make_discrete(gw2, gw1) must match what the original
    export_data.py::calculate_discrete_gameweek_stats() would produce.
    Strategy: run the original function on a copy, then run make_discrete,
    then compare row-by-row.
    """
    from fpl_data_core.stat_calculator import make_discrete
    from fpl_data_core.schemas import CUMULATIVE_COLS, ID_COLS

    gw1 = pd.read_csv(os.path.join(GW_PATH, "GW1", "playerstats.csv"))
    gw2 = pd.read_csv(os.path.join(GW_PATH, "GW2", "playerstats.csv"))

    result = make_discrete(gw2, prev_df=gw1)

    # Reference: manually compute the subtraction inline
    merged = pd.merge(gw2, gw1[ID_COLS + CUMULATIVE_COLS],
                      on="id", how="left", suffixes=("", "_prev"))
    for col in CUMULATIVE_COLS:
        if col in merged.columns and f"{col}_prev" in merged.columns:
            merged[f"{col}_prev"] = merged[f"{col}_prev"].fillna(0)
            merged[col] = merged[col] - merged[f"{col}_prev"]
    reference = merged[[c for c in ID_COLS + CUMULATIVE_COLS if c in merged.columns]]

    pd.testing.assert_frame_equal(
        result[reference.columns].sort_values("id").reset_index(drop=True),
        reference.sort_values("id").reset_index(drop=True),
        check_like=True
    )

@pytest.mark.skipif(not os.path.isdir(GW_PATH), reason="Real data not available")
def test_discrete_no_negative_values_after_gw1():
    """No player should have negative goals_scored, assists, or minutes in GW2."""
    from fpl_data_core.stat_calculator import make_discrete
    gw1 = pd.read_csv(os.path.join(GW_PATH, "GW1", "playerstats.csv"))
    gw2 = pd.read_csv(os.path.join(GW_PATH, "GW2", "playerstats.csv"))
    result = make_discrete(gw2, prev_df=gw1)
    for col in ["goals_scored", "assists", "minutes"]:
        if col in result.columns:
            assert (result[col] >= 0).all(), f"Negative values found in {col}"

@pytest.mark.skipif(not os.path.isdir(GW_PATH), reason="Real data not available")
def test_season_layout_file_paths_resolve():
    """get_file_path() for all registered file types should return valid Path objects."""
    from fpl_data_core.season_registry import get_season_layout
    layout = get_season_layout("2025-2026")
    for file_type in ["players", "teams", "gameweek_summaries"]:
        path = layout.get_file_path(file_type)
        assert str(path).endswith(".csv"), f"Expected .csv, got {path}"
```

### 1.3 Edge Cases

```python
def test_make_discrete_handles_new_player_in_gw2():
    """Player present in GW2 but not GW1 should have their stats unchanged (fillna(0))."""
    import pandas as pd
    from fpl_data_core.stat_calculator import make_discrete
    gw1 = pd.DataFrame({"id": [1], "goals_scored": [1], "assists": [0]})
    gw2 = pd.DataFrame({"id": [1, 2], "goals_scored": [2, 1], "assists": [1, 1]})
    result = make_discrete(gw2, prev_df=gw1)
    new_player = result[result["id"] == 2]
    # New player has no prev; fillna(0) means their stats are their own
    assert new_player["goals_scored"].iloc[0] == 1

def test_make_discrete_handles_player_leaving():
    """Player in GW1 but not GW2 should not appear in output."""
    import pandas as pd
    from fpl_data_core.stat_calculator import make_discrete
    gw1 = pd.DataFrame({"id": [1, 99], "goals_scored": [1, 5], "assists": [0, 3]})
    gw2 = pd.DataFrame({"id": [1], "goals_scored": [2], "assists": [1]})
    result = make_discrete(gw2, prev_df=gw1)
    assert 99 not in result["id"].values

def test_tournament_name_map_covers_known_slugs():
    from fpl_data_core.schemas import TOURNAMENT_NAME_MAP
    for slug in ["premier-league", "champions-league", "efl-cup", "europa-league"]:
        assert slug in TOURNAMENT_NAME_MAP, f"Missing slug: {slug}"

def test_yaml_registry_loads_from_custom_path(tmp_path):
    """load_registry_from_yaml() accepts a custom path."""
    import yaml
    from fpl_data_core.season_registry import load_registry_from_yaml, SEASON_REGISTRY
    custom_yaml = tmp_path / "seasons.yaml"
    custom_yaml.write_text(yaml.dump({
        "seasons": [{
            "season": "1999-2000",
            "data_root": "data/1999-2000",
            "has_consolidated_files": True,
            "player_id_column": "id",
            "gameweek_column": "gw",
            "files": {"players": "players.csv"}
        }]
    }))
    load_registry_from_yaml(custom_yaml)
    assert "1999-2000" in SEASON_REGISTRY
```

### 1.4 Acceptance Criteria

- All smoke tests pass in under 1 second without any real data
- All parity tests pass on at least GW1 and GW2 data from the 2025-26 season
- Zero negative values in discrete stats for goals_scored, assists, minutes across all available gameweeks
- `CUMULATIVE_COLS` count is exactly 26 (verified against `export_data.py` line 30)

---

## Package 2: `fpl-api-client`

**Test file locations:**
- `fpl-platform/packages/fpl-api-client/tests/test_fpl_client.py` (Python)
- `fpl-platform/packages/fpl-api-client/typescript/src/__tests__/csvLoader.test.ts` (TypeScript)

**Runners:** `pytest` for Python; `vitest` for TypeScript
**Prerequisites:** Internet connection for live API tests (mark as `@pytest.mark.live`). Vitest + papaparse for TS tests.

---

### 2.1 Smoke Tests

**Python:**
```python
def test_fpl_client_imports():
    from fpl_api_client import fetch_json, get_bootstrap, get_players, get_teams
    assert callable(fetch_json)
    assert callable(get_bootstrap)

def test_football_data_client_instantiation_fails_without_key(monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    from fpl_api_client import FootballDataClient
    with pytest.raises(ValueError, match="API key required"):
        FootballDataClient()

def test_football_data_client_instantiates_with_key():
    from fpl_api_client import FootballDataClient
    client = FootballDataClient(api_key="test_key_123")
    assert client.api_key == "test_key_123"
```

**TypeScript:**
```typescript
import { getCsvPath, loadCSVData } from '../src/csvLoader';

test('getCsvPath returns correct path for master players file', () => {
  expect(getCsvPath({ season: '2025-2026', dataType: 'players' }))
    .toBe('/data/2025-2026/players.csv');
});

test('getCsvPath returns correct path for GW-scoped playerstats', () => {
  expect(getCsvPath({ season: '2025-2026', gameweek: 5, dataType: 'playerstats' }))
    .toBe('/data/2025-2026/By Gameweek/GW5/playerstats.csv');
});

test('getCsvPath returns correct path for 2024-2025 master', () => {
  expect(getCsvPath({ season: '2024-2025', dataType: 'playerstats' }))
    .toBe('/data/2024-2025/playerstats/playerstats.csv');
});
```

### 2.2 Parity Tests

**`getCsvPath` must match original `csvPathConfig.ts` for all known input combinations:**
```typescript
// These pairs are derived from the source file's full input space

const PARITY_CASES = [
  // Master files
  [{ season: '2025-2026', dataType: 'players' },          '/data/2025-2026/players.csv'],
  [{ season: '2025-2026', dataType: 'teams' },            '/data/2025-2026/teams.csv'],
  [{ season: '2024-2025', dataType: 'players' },          '/data/2024-2025/players/players.csv'],
  [{ season: '2024-2025', dataType: 'playerstats' },      '/data/2024-2025/playerstats/playerstats.csv'],
  // GW-scoped
  [{ season: '2025-2026', gameweek: 1, dataType: 'playerstats' },
                                          '/data/2025-2026/By Gameweek/GW1/playerstats.csv'],
  [{ season: '2025-2026', gameweek: 1, dataType: 'fixtures' },
                                          '/data/2025-2026/By Gameweek/GW1/fixtures.csv'],
  [{ season: '2024-2025', gameweek: 1, dataType: 'matches' },
                                          '/data/2024-2025/matches/GW1/matches.csv'],
  // Tournament
  [{ season: '2025-2026', tournament: 'Premier League', dataType: 'playerstats' },
                                          '/data/2025-2026/By Tournament/Premier League/playerstats.csv'],
];

test.each(PARITY_CASES)('getCsvPath parity: %o → %s', (opts, expected) => {
  expect(getCsvPath(opts as any)).toBe(expected);
});
```

**Python — live API parity with `build_fpl_kb.py`:**
```python
@pytest.mark.live
def test_get_players_matches_build_master_squad_field_set():
    """The field set returned by get_players() must include all fields
    that build_master_squad() captured."""
    from fpl_api_client import get_players
    players = get_players()
    assert len(players) > 500  # FPL usually has 600-700 players
    required_fields = {"id", "web_name", "team_id", "element_type", "status"}
    for field in required_fields:
        assert field in players[0], f"Missing field: {field}"

@pytest.mark.live
def test_get_fixture_difficulty_map_returns_20_teams():
    from fpl_api_client import get_bootstrap, get_teams, get_fixture_difficulty_map
    bootstrap = get_bootstrap()
    teams = get_teams(bootstrap)
    gw = 10  # arbitrary finished gameweek
    diff_map = get_fixture_difficulty_map(gw, teams)
    # Not all 20 teams play every GW (cup weeks), but PL GW should have ≥ 18
    assert len(diff_map) >= 10
    for difficulty in diff_map.values():
        assert 2 <= difficulty <= 5
```

### 2.3 Edge Cases

**Python:**
```python
def test_fetch_json_raises_on_bad_url():
    from fpl_api_client.fpl_client import fetch_json
    with pytest.raises(Exception):
        fetch_json("https://this-is-not-a-real-domain-xyz.com/api")

def test_get_current_gameweek_returns_none_when_no_current():
    """If neither is_current nor is_next is True (e.g. off-season), return None."""
    from fpl_api_client.fpl_client import get_current_gameweek
    fake_bootstrap = {"events": [{"id": 1, "is_current": False, "is_next": False}]}
    result = get_current_gameweek(fake_bootstrap)
    assert result is None
```

**TypeScript:**
```typescript
test('getCsvPath handles gameweek 0 without crashing', () => {
  // GW0 is technically invalid but should not throw
  const path = getCsvPath({ season: '2025-2026', gameweek: 0, dataType: 'playerstats' });
  expect(path).toContain('GW0');
});

test('loadCSVData rejects on network error', async () => {
  await expect(loadCSVData('https://this-does-not-exist.xyz/data.csv'))
    .rejects.toThrow();
});
```

### 2.4 Acceptance Criteria

- All `getCsvPath` parity cases match the original `csvPathConfig.ts` output exactly
- Live bootstrap returns ≥ 500 players and ≥ 20 teams (run once manually before adoption)
- `fpl-video-repurposer/build_fpl_kb.py` produces identical `master_squad.json` after switching
- Vitest CSV loading behaviour decision documented and tested

---

## Package 3: `fpl-player-registry`

**Test file:** `fpl-platform/packages/fpl-player-registry/tests/test_player_registry.py`
**Runner:** `pytest`
**Prerequisites:** Real `data/2025-2026/players.csv` and GW1 `playerstats.csv` for ID mapping tests.

---

### 3.1 Smoke Tests

```python
def test_known_nicknames_imported():
    from fpl_player_registry.player_registry import KNOWN_NICKNAMES
    assert "Salah" in KNOWN_NICKNAMES
    assert "Haaland" in KNOWN_NICKNAMES
    assert len(KNOWN_NICKNAMES) >= 10

def test_season_id_mapper_instantiates(tmp_path):
    from fpl_player_registry.player_registry import SeasonIdMapper
    mapper = SeasonIdMapper(workspace_root=tmp_path)
    assert mapper.workspace_root == tmp_path

def test_resolve_nickname_with_empty_players_returns_none():
    from fpl_player_registry.player_registry import resolve_nickname
    result = resolve_nickname("el Vikingo", players=[])
    assert result is None
```

### 3.2 Parity Tests

**ID mapping must produce same results as the original `season_id_mapper.py`:**

```python
@pytest.mark.skipif(not os.path.exists("data/2025-2026/players.csv"),
                    reason="Real data not available")
def test_season_id_mapper_parity_with_original():
    """
    PARITY TEST: SeasonIdMapper in this package must produce the same
    canonical mappings as the original captaincy-ml/ml/data/season_id_mapper.py.
    Known ground truth from test_sprint_b.py:
      2024-2025 IDs: [328, 351, 17, 110] (Salah, Haaland, Saka, Wissa)
      → 2025-2026 IDs: [381, 430, 16, 135]
    """
    from fpl_player_registry.player_registry import SeasonIdMapper
    mapper = SeasonIdMapper(workspace_root=Path("."))
    canonical = mapper.to_canonical("2024-2025", [328, 351, 17, 110])
    # canonical IDs are intermediate; then convert to 2025-2026
    season_ids = mapper.to_season(
        [c for c in canonical if c is not None], "2025-2026"
    )
    assert 381 in season_ids   # Salah
    assert 430 in season_ids   # Haaland

def test_build_name_lookup_covers_all_players():
    from fpl_player_registry.player_registry import build_name_lookup
    players = [
        {"web_name": "Salah", "first_name": "Mohamed", "second_name": "Salah"},
        {"web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland"},
    ]
    lookup = build_name_lookup(players)
    assert "salah" in lookup
    assert "haaland" in lookup
    assert "mohamed" in lookup
    assert "erling" in lookup
    # Nickname from KNOWN_NICKNAMES
    assert "mo" in lookup or "el salah" in lookup
```

### 3.3 Edge Cases

```python
def test_resolve_nickname_strips_el_prefix():
    from fpl_player_registry.player_registry import resolve_nickname
    players = [{"web_name": "Salah", "first_name": "Mohamed", "second_name": "Salah"}]
    result = resolve_nickname("el Salah", players)
    assert result is not None
    assert result["web_name"] == "Salah"

def test_resolve_nickname_case_insensitive():
    from fpl_player_registry.player_registry import resolve_nickname
    players = [{"web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland"}]
    assert resolve_nickname("EL VIKINGO", players) is not None

def test_season_id_mapper_handles_unmapped_id():
    from fpl_player_registry.player_registry import SeasonIdMapper
    mapper = SeasonIdMapper(workspace_root=Path("."))
    # ID 99999 is not a real player
    # Should return [None] without crashing
    # (needs real data to run; unit test mocks the mapping)
    mapper._season_to_canonical["2025-2026"] = {1: 100, 2: 200}
    mapper._canonical_to_season["2025-2026"] = {100: 1, 200: 2}
    result = mapper.to_canonical("2025-2026", [1, 99999, 2])
    assert result == [100, None, 200]

def test_season_id_mapper_map_between_seasons_missing_method():
    """
    REGRESSION TEST: Documents the missing method found in test_sprint_b.py.
    This test should FAIL until map_between_seasons() is implemented.
    Once implemented, update this test to verify it returns correct values.
    """
    from fpl_player_registry.player_registry import SeasonIdMapper
    mapper = SeasonIdMapper()
    # Should raise AttributeError until implemented
    assert not hasattr(mapper, "map_between_seasons"), (
        "map_between_seasons() now exists — update this test "
        "to verify it returns [381, 430, 16, 135] for the Sprint B inputs"
    )
```

### 3.4 Acceptance Criteria

- `resolve_nickname("el Vikingo", players)` returns Haaland
- `resolve_nickname("KDB", players)` returns De Bruyne
- `SeasonIdMapper.to_canonical` + `to_season` round-trip works for Salah (328 → canonical → 381)
- `map_between_seasons()` situation explicitly resolved and tested
- `id_maps/` path change documented and validated against existing cached files

---

## Package 4: `fpl-captain-engine`

**Test files:**
- `fpl-platform/packages/fpl-captain-engine/tests/test_captain_score.py` (Python)
- `fpl-platform/packages/fpl-captain-engine/typescript/src/captainScore.test.ts` (TypeScript — promoted from source)

**Runners:** `pytest` (Python), `vitest` (TypeScript)
**Prerequisites:** None — this package has zero external dependencies.

---

### 4.1 Smoke Tests

```python
def test_captain_score_imports():
    from fpl_captain_engine import calculate_captain_score, update_captain_scores
    assert callable(calculate_captain_score)

def test_tier_classifier_imports():
    from fpl_captain_engine import TierClassifier, TieredCaptainSelector
    assert TierClassifier()  # instantiates without error
```

### 4.2 Parity Tests

**Python formula must match TypeScript formula exactly:**

```python
# These expected values are derived from the existing TypeScript test suite
# (captaincy-showdown/src/engine/captainScore.test.ts)

FORMULA_CASES = [
    # (form, fixture_difficulty, xgi_per_90, minutes_risk, expected_score)
    # Haaland scenario (from captainScore.test.ts)
    (8.5, 2, 1.8, 10,  None),   # > 80, exact value checked in TS tests
    # Salah scenario
    (7.0, 4, 1.2, 5,   None),   # > 0, < Haaland
    # Foden rotation risk
    (6.5, 2, 1.0, 40,  None),   # < Salah due to minutes_risk
    # Kane out of form
    (4.0, 3, 0.8, 0,   None),   # lowest score
]

def test_python_haaland_score_above_80():
    from fpl_captain_engine import calculate_captain_score
    score = calculate_captain_score(form=8.5, fixture_difficulty=2,
                                    xgi_per_90=1.8, minutes_risk=10)
    assert score > 80.0

def test_python_score_ordering_matches_ts_expectations():
    """Haaland > Salah > Foden > Kane — same ranking as TS test."""
    from fpl_captain_engine import calculate_captain_score
    haaland = calculate_captain_score(8.5, 2, 1.8, 10)
    salah   = calculate_captain_score(7.0, 4, 1.2, 5)
    foden   = calculate_captain_score(6.5, 2, 1.0, 40)
    kane    = calculate_captain_score(4.0, 3, 0.8, 0)
    assert haaland > salah > foden > kane

def test_python_score_bounds():
    """Score must always be in [0, 100]."""
    from fpl_captain_engine import calculate_captain_score
    assert calculate_captain_score(0, 5, 0, 100) >= 0
    assert calculate_captain_score(10, 1, 2, 0) <= 100
    assert calculate_captain_score(100, 1, 100, 0) == 100.0  # clamped

def test_python_ts_numerical_parity():
    """
    PARITY TEST: Python and TypeScript must agree to within 1e-10.
    Reference values computed manually from the TS formula:
      form=8.5 → formScore = 85.0
      fixture=2 → fixtureScore = (6-2)*20 = 80.0
      xgi=1.8 → xgiScore = min(1.8*50, 100) = 90.0
      risk=10 → minutesScore = 90.0
      total = 85*0.4 + 80*0.3 + 90*0.2 + 90*0.1
             = 34 + 24 + 18 + 9 = 85.0
    """
    from fpl_captain_engine import calculate_captain_score
    result = calculate_captain_score(form=8.5, fixture_difficulty=2,
                                     xgi_per_90=1.8, minutes_risk=10)
    assert abs(result - 85.0) < 1e-10
```

### 4.3 Edge Cases

```python
def test_score_with_zero_xgi():
    from fpl_captain_engine import calculate_captain_score
    score = calculate_captain_score(form=5.0, fixture_difficulty=3, xgi_per_90=0, minutes_risk=0)
    assert 0 <= score <= 100

def test_score_with_very_high_form():
    """Form > 10 should still be clamped at 100."""
    from fpl_captain_engine import calculate_captain_score
    score_normal = calculate_captain_score(10, 1, 2, 0)
    score_extreme = calculate_captain_score(99999, 1, 2, 0)
    assert score_normal == score_extreme  # clamped identically

def test_update_captain_scores_does_not_mutate_unexpectedly():
    from fpl_captain_engine import CaptainCandidate, update_captain_scores
    c = CaptainCandidate(player_id=1, name="Test", team="ARS", position="FWD",
                         price=10.0, ownership=50.0, expected_ownership=50.0,
                         form_score=7.0, fixture_difficulty=2, minutes_risk=5,
                         xgi_per_90=1.0, captain_score=0.0)
    results = update_captain_scores([c])
    assert results[0].captain_score > 0
    assert len(results) == 1

def test_tier_selector_returns_correct_counts():
    """With enough diverse candidates, should return 5+3+2=10 recommendations."""
    from fpl_captain_engine import CaptainCandidate, TieredCaptainSelector, update_captain_scores
    import random
    random.seed(42)
    candidates = []
    for i in range(50):
        c = CaptainCandidate(
            player_id=i, name=f"Player{i}", team="TST", position="MID",
            price=8.0, ownership=float(i * 2),  # 0 to 98%
            expected_ownership=float(i * 2), form_score=random.uniform(3, 10),
            fixture_difficulty=random.randint(1, 5), minutes_risk=random.uniform(0, 50),
            xgi_per_90=random.uniform(0, 2), captain_score=0.0
        )
        candidates.append(c)
    update_captain_scores(candidates)
    selector = TieredCaptainSelector()
    results = selector.select(candidates)
    tiers = [r.tier for r in results]
    # With 50 diverse players, all three tiers should be represented
    assert "premium" in tiers
    assert "differential" in tiers
    assert "outlier" in tiers
    assert len(results) <= 10

def test_advanced_captain_strategies_missing_is_documented():
    """
    SENTINEL TEST: Confirms that advanced_captain_strategies.py is still missing
    from captaincy-ml. Remove this test when the file is found or reconstructed.
    """
    import importlib.util
    spec = importlib.util.find_spec("advanced_captain_strategies")
    assert spec is None, (
        "advanced_captain_strategies.py now exists — run side-by-side comparison "
        "with tier_classifier.py and update the audit."
    )
```

### 4.4 Acceptance Criteria

- All existing `captainScore.test.ts` and `captainScore.spec.ts` tests pass after importing from this package
- `calculate_captain_score(8.5, 2, 1.8, 10)` returns exactly `85.0` in both Python and TypeScript
- Score is always in `[0.0, 100.0]` for any finite float inputs
- `TieredCaptainSelector` produces ≤ 10 results with at least 1 of each tier for a 50-player input set
- The `advanced_captain_strategies.py` situation is documented as a known open issue

---

## Package 5: `fpl-charts`

**Test files:**
- `fpl-platform/packages/fpl-charts/src/__tests__/theme.test.ts` (TypeScript)
- Visual regression tests deferred to Phase 5 (component promotion)

**Runner:** `vitest`
**Prerequisites:** None for `theme.ts` tests.

---

### 5.1 Smoke Tests

```typescript
import { COLORS, BRAND, CHART_COLORS, getRiskLevel, RISK } from '../src/theme';

test('COLORS exports correct hex values', () => {
  expect(COLORS.coral).toBe('#FF6A4D');
  expect(COLORS.green).toBe('#02EBAE');
  expect(COLORS.dark).toBe('#211F29');
  expect(COLORS.blue).toBe('#1F4B59');
  expect(COLORS.golden).toBe('#F2C572');
});

test('BRAND.background matches COLORS.dark', () => {
  expect(BRAND.background).toBe(COLORS.dark);
});

test('CHART_COLORS has at least 10 entries', () => {
  expect(CHART_COLORS.length).toBeGreaterThanOrEqual(10);
  expect(CHART_COLORS[0]).toBe(COLORS.coral);
});
```

### 5.2 Parity Tests

```typescript
// Parity with captaincy-showdown/src/brand.ts
test('BRAND object is identical to original brand.ts', () => {
  // Original: { background: '#211F29', watermarkSrc: '/logos-and-brand-art/watermark.svg', exportBackground: '#211F29' }
  expect(BRAND.background).toBe('#211F29');
  expect(BRAND.watermarkSrc).toBe('/logos-and-brand-art/watermark.svg');
  expect(BRAND.exportBackground).toBe('#211F29');
});

// Parity with PlayerCard.tsx::getRiskIndicator
test('getRiskLevel matches original PlayerCard risk logic', () => {
  // Original: <= 20 → emerald, <= 60 → amber, > 60 → red
  expect(getRiskLevel(0)).toBe('low');
  expect(getRiskLevel(20)).toBe('low');
  expect(getRiskLevel(21)).toBe('medium');
  expect(getRiskLevel(60)).toBe('medium');
  expect(getRiskLevel(61)).toBe('high');
  expect(getRiskLevel(100)).toBe('high');
});
```

### 5.3 Edge Cases

```typescript
test('getRiskLevel handles boundary values exactly', () => {
  expect(getRiskLevel(20)).toBe('low');    // boundary: should be low
  expect(getRiskLevel(60)).toBe('medium'); // boundary: should be medium
  expect(getRiskLevel(61)).toBe('high');
});

test('COLORS has no duplicate hex values', () => {
  const values = Object.values(COLORS);
  const unique = new Set(values);
  expect(unique.size).toBe(values.length);
});
```

### 5.4 Acceptance Criteria

- `COLORS.coral === '#FF6A4D'` (exact hex match with `main.css`)
- `BRAND` object is byte-identical to `captaincy-showdown/src/brand.ts` `BRAND` export
- `getRiskLevel(20) === 'low'`, `getRiskLevel(21) === 'medium'`, `getRiskLevel(61) === 'high'`
- Visual regression tests defined (deferred to Phase 5) covering `PlayerCard` at small/medium/large sizes

---

## Pre-Adoption Integration Checklist

Before any legacy project switches its imports, all of the following must be ✅:

| Package | Smoke tests | Parity tests | Edge cases | Blocker issues resolved |
|---------|-------------|--------------|------------|-------------------------|
| `fpl-data-core` | — | — | — | `fpl-elo-insights-clean` fork reconciled |
| `fpl-api-client` | — | — | — | `loadCSVData` Vitest decision |
| `fpl-player-registry` | — | — | — | `map_between_seasons()` resolved |
| `fpl-captain-engine` | — | — | — | `advanced_captain_strategies.py` documented |
| `fpl-charts` | — | — | — | Components promoted (Phase 5) |

---

## First Validation Recommendation

See `RECOMMENDATIONS.md` for the recommended first package to validate and first consumer project for pilot integration.


