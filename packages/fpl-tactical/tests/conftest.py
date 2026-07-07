"""
tests/conftest.py
=================
Shared fixtures for fpl-tactical tests. All tests are offline: the canned
soccerdata-shaped sample in fixtures/soccerdata_sample.json stands in for
the network reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "soccerdata_sample.json"

SAMPLE_SEASON = "2025-2026"


def load_sample_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (shots, schedule) DataFrames shaped like soccerdata output."""
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    shots = pd.DataFrame(raw["shots"])
    schedule = pd.DataFrame(raw["schedule"])
    return shots, schedule


@pytest.fixture
def sample_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_sample_frames()


@pytest.fixture
def tmp_tactical_root(tmp_path, monkeypatch):
    """Point FPL_TACTICAL_ROOT at a temp directory; return its Path."""
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    return tmp_path
