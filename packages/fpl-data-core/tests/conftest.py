"""
Shared fixtures and configuration for fpl-data-core tests.

The pytest.ini sets pythonpath=. (the fpl-data-core/ root), so
`fpl_data_core` is importable as a normal Python package from
fpl-data-core/fpl_data_core/__init__.py.

No sys.path manipulation is needed in this file — pytest handles it.
"""
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PKG_ROOT = Path(__file__).parent.parent          # fpl-data-core/
DATA_ROOT_2526 = PKG_ROOT / "data" / "2025-2026" # real data (may not exist in CI)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_playermatchstats_df():
    """A small playermatchstats DataFrame for analytics tests (no file I/O)."""
    import pandas as pd
    return pd.DataFrame({
        "player_id": [1, 1, 1, 2, 2],
        "xg":            [0.5, 0.5, 0.5, 0.2, 0.3],
        "xa":            [0.3, 0.3, 0.3, 0.1, 0.0],
        "minutes_played": [90,  90,  90,  60,  75],
    })


