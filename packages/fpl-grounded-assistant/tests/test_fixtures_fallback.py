"""
tests/test_fixtures_fallback.py
===============================
Integration tests for the owned-store fallback wired into
``_fetch_fixtures_for_gw()`` in ``get_fixtures_for_gw.py``.

Covers CONTRACT §11.3 H4b Seam 2 — per-gameweek fixtures fallback.

Test scenarios
--------------
(a) Live succeeds → fallback not invoked, cache populated.
(b) Live raises exception → fallback succeeds → fixtures returned,
    cache NOT populated, WARNING log emitted with provenance fields.
(c) Live returns non-list → fallback succeeds.
(d) Live fails AND OwnedStoreUnavailable → returns None.
(e) Null-tolerant: NULL team_h_score/team_a_score passed through as None.
(f) load_fixtures_for_gw_from_owned_store is None (import failed) → skip.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.path setup (mirror fpl_server.py's _SIB pattern) so cross-package
# imports inside get_fixtures_for_gw.py resolve. We deliberately avoid
# importing `fpl_grounded_assistant` (the package) because its __init__.py
# pulls the whole dispatcher + harness graph that is unrelated to this test.
# ---------------------------------------------------------------------------
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))                      # tests/
_PKG  = _os.path.dirname(_HERE)                                           # fpl-grounded-assistant/
_PKGS = _os.path.dirname(_PKG)                                            # packages/
for _pkg in [
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
    if _pkg not in _sys.path:
        _sys.path.insert(0, _pkg)

# Load the modules-under-test directly via importlib so we do NOT trigger
# fpl_grounded_assistant/__init__.py.
import importlib.util as _ilu

_PKG_DIR = _os.path.join(_PKG, "fpl_grounded_assistant")


def _load_module(name: str, filename: str):
    spec = _ilu.spec_from_file_location(name, _os.path.join(_PKG_DIR, filename))
    assert spec is not None and spec.loader is not None
    mod = _ilu.module_from_spec(spec)
    _sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # Remove half-loaded module so a re-run doesn't see a stale entry.
        _sys.modules.pop(name, None)
        raise
    return mod


# Load owned_store_fallback first (get_fixtures_for_gw imports from it).
_osf_mod = _load_module(
    "fpl_grounded_assistant.owned_store_fallback",
    "owned_store_fallback.py",
)
OwnedStoreProvenance = _osf_mod.OwnedStoreProvenance
OwnedStoreUnavailable = _osf_mod.OwnedStoreUnavailable

gff = _load_module(
    "fpl_grounded_assistant.get_fixtures_for_gw",
    "get_fixtures_for_gw.py",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level _fixture_cache between tests."""
    gff._fixture_cache.clear()
    yield
    gff._fixture_cache.clear()


def _make_provenance(merged_at: str = "2026-05-25T08-00-00Z") -> OwnedStoreProvenance:
    return OwnedStoreProvenance(
        pointer_path="/some/path/_owned_latest.json",
        merged_at=merged_at,
        baseline_captured_at="2026-05-25T06-00-00Z",
        incremental_count=2,
        staleness_hours=1.25,
        row_counts={"fixtures": 380},
    )


def _sample_fixture(fid: int = 101, gw: int = 12) -> dict:
    return {
        "id":                fid,
        "event":             gw,
        "team_h":            1,
        "team_a":            2,
        "team_h_score":      None,
        "team_a_score":      None,
        "team_h_difficulty": 3,
        "team_a_difficulty": 4,
        "finished":          False,
        "kickoff_time":      "2026-05-25T15:00:00Z",
    }


# ---------------------------------------------------------------------------
# (a) Live succeeds → fallback not invoked, cache populated
# ---------------------------------------------------------------------------

def test_live_success_skips_fallback_and_caches(monkeypatch):
    live_fixtures = [_sample_fixture(101, 12), _sample_fixture(102, 12)]
    monkeypatch.setattr(gff, "get_fixtures", MagicMock(return_value=live_fixtures))

    mock_fb = MagicMock()
    monkeypatch.setattr(gff, "load_fixtures_for_gw_from_owned_store", mock_fb)

    result = gff._fetch_fixtures_for_gw(12, bootstrap=None, fixtures_override=None)

    assert result == live_fixtures
    mock_fb.assert_not_called()
    assert 12 in gff._fixture_cache
    assert gff._fixture_cache[12] == live_fixtures


# ---------------------------------------------------------------------------
# (b) Live raises → fallback succeeds → log emitted, cache NOT populated
# ---------------------------------------------------------------------------

def test_live_exception_falls_back_and_logs(monkeypatch, caplog):
    monkeypatch.setattr(
        gff, "get_fixtures",
        MagicMock(side_effect=RuntimeError("network down")),
    )

    fb_fixtures = [_sample_fixture(201, 5)]
    fake_prov = _make_provenance(merged_at="2026-05-25T08-00-00Z")
    monkeypatch.setattr(
        gff, "load_fixtures_for_gw_from_owned_store",
        MagicMock(return_value=(fb_fixtures, fake_prov)),
    )

    with caplog.at_level(logging.WARNING, logger=gff.__name__):
        result = gff._fetch_fixtures_for_gw(5, bootstrap=None, fixtures_override=None)

    assert result == fb_fixtures
    # Fallback results must NOT be cached
    assert 5 not in gff._fixture_cache

    fallback_records = [
        r for r in caplog.records
        if "fixtures_owned_store_fallback" in r.getMessage()
    ]
    assert len(fallback_records) >= 1
    msg = fallback_records[0].getMessage()
    assert "merged_at" in msg
    assert "staleness_hours" in msg
    assert "incremental_count" in msg
    assert "gw_number" in msg


# ---------------------------------------------------------------------------
# (c) Live returns non-list → fallback succeeds
# ---------------------------------------------------------------------------

def test_live_non_list_falls_back(monkeypatch):
    monkeypatch.setattr(gff, "get_fixtures", MagicMock(return_value={"not": "a list"}))

    fb_fixtures = [_sample_fixture(301, 7)]
    monkeypatch.setattr(
        gff, "load_fixtures_for_gw_from_owned_store",
        MagicMock(return_value=(fb_fixtures, _make_provenance())),
    )

    result = gff._fetch_fixtures_for_gw(7, bootstrap=None, fixtures_override=None)
    assert result == fb_fixtures
    assert 7 not in gff._fixture_cache


# ---------------------------------------------------------------------------
# (d) Live fails AND OwnedStoreUnavailable → returns None
# ---------------------------------------------------------------------------

def test_live_fail_and_fallback_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr(
        gff, "get_fixtures",
        MagicMock(side_effect=RuntimeError("nope")),
    )
    monkeypatch.setattr(
        gff, "load_fixtures_for_gw_from_owned_store",
        MagicMock(side_effect=OwnedStoreUnavailable("no owned fixtures for gw=99")),
    )
    # Keep OwnedStoreUnavailable resolvable in the module namespace
    monkeypatch.setattr(gff, "OwnedStoreUnavailable", OwnedStoreUnavailable)

    result = gff._fetch_fixtures_for_gw(99, bootstrap=None, fixtures_override=None)
    assert result is None
    assert 99 not in gff._fixture_cache


# ---------------------------------------------------------------------------
# (e) Null-tolerant: NULL scores remain None in the fallback dict
# ---------------------------------------------------------------------------

def test_null_scores_pass_through_as_none(monkeypatch):
    monkeypatch.setattr(
        gff, "get_fixtures",
        MagicMock(side_effect=RuntimeError("offline")),
    )

    fb_fixtures = [{
        "id":                401,
        "event":             8,
        "team_h":            3,
        "team_a":            4,
        "team_h_score":      None,
        "team_a_score":      None,
        "team_h_difficulty": 2,
        "team_a_difficulty": 5,
        "finished":          False,
        "kickoff_time":      "2026-05-25T15:00:00Z",
    }]
    monkeypatch.setattr(
        gff, "load_fixtures_for_gw_from_owned_store",
        MagicMock(return_value=(fb_fixtures, _make_provenance())),
    )

    result = gff._fetch_fixtures_for_gw(8, bootstrap=None, fixtures_override=None)
    assert result is not None
    assert len(result) == 1
    assert result[0]["team_h_score"] is None
    assert result[0]["team_a_score"] is None
    assert "team_h_score" in result[0]
    assert "team_a_score" in result[0]


# ---------------------------------------------------------------------------
# (f) Helper symbol is None (import failed) → skip fallback, return None
# ---------------------------------------------------------------------------

def test_loader_is_none_skips_fallback(monkeypatch):
    monkeypatch.setattr(
        gff, "get_fixtures",
        MagicMock(side_effect=RuntimeError("nope")),
    )
    monkeypatch.setattr(gff, "load_fixtures_for_gw_from_owned_store", None)

    result = gff._fetch_fixtures_for_gw(10, bootstrap=None, fixtures_override=None)
    assert result is None
    assert 10 not in gff._fixture_cache


# ---------------------------------------------------------------------------
# (g) H4d: FPL_FORCE_FALLBACK_TOOLS env flag — operator force-fallback path
# ---------------------------------------------------------------------------

def test_force_flag_bypasses_live_and_calls_fallback(monkeypatch, caplog):
    monkeypatch.setenv("FPL_FORCE_FALLBACK_TOOLS", "1")

    mock_live = MagicMock(return_value=[_sample_fixture(101, 12)])
    monkeypatch.setattr(gff, "get_fixtures", mock_live)

    fb_fixtures = [_sample_fixture(201, 12)]
    mock_fb = MagicMock(return_value=(fb_fixtures, _make_provenance()))
    monkeypatch.setattr(gff, "load_fixtures_for_gw_from_owned_store", mock_fb)

    with caplog.at_level(logging.WARNING, logger=gff.__name__):
        result = gff._fetch_fixtures_for_gw(12, bootstrap=None, fixtures_override=None)

    assert result == fb_fixtures
    mock_live.assert_not_called(), "live get_fixtures must NOT be called"
    mock_fb.assert_called_once_with(12)
    # Forced fallback results MUST NOT be cached
    assert 12 not in gff._fixture_cache

    forced_records = [
        r for r in caplog.records
        if "fixtures_forced_fallback" in r.getMessage()
        and "FPL_FORCE_FALLBACK_TOOLS" in r.getMessage()
    ]
    assert len(forced_records) >= 1


def test_force_flag_unset_uses_live_first_semantics(monkeypatch):
    """Regression guard: with FPL_FORCE_FALLBACK_TOOLS unset, the live
    path runs (live-first semantics preserved).
    """
    monkeypatch.delenv("FPL_FORCE_FALLBACK_TOOLS", raising=False)

    live_fixtures = [_sample_fixture(101, 12)]
    mock_live = MagicMock(return_value=live_fixtures)
    monkeypatch.setattr(gff, "get_fixtures", mock_live)
    mock_fb = MagicMock()
    monkeypatch.setattr(gff, "load_fixtures_for_gw_from_owned_store", mock_fb)

    result = gff._fetch_fixtures_for_gw(12, bootstrap=None, fixtures_override=None)
    assert result == live_fixtures
    mock_live.assert_called_once()
    mock_fb.assert_not_called()
