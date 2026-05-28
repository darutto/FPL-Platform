"""
tests/test_player_form_fallback.py
==================================
Integration tests for the owned-store fallback wired into
``_fetch_element_summary()`` in ``player_form.py``.

Covers CONTRACT §11.3 H4b Seam 1 — per-tool element-summary fallback.

Test scenarios
--------------
(a) Live succeeds → fallback not invoked.
(b) Live fails (exception) → fallback succeeds → element_summary dict returned
    with provenance WARNING log emitted.
(c) Live fails AND OwnedStoreUnavailable → returns None, no crash.
(d) Null-tolerant: NULL value/was_home/opponent_team pass through as None.
(e) load_element_summary_from_owned_store is None (import failed) → skip.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

# Import fpl_server first to populate sys.path with sibling packages
# (fpl-captain-engine, fpl-tool-runner, etc.) via its _SIB() shim — mirrors
# the import order used by tests/test_bootstrap_fallback_integration.py.
import fpl_server  # noqa: F401
import fpl_grounded_assistant.player_form as pf
from fpl_grounded_assistant.owned_store_fallback import (
    OwnedStoreProvenance,
    OwnedStoreUnavailable,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_guard():
    """Reset the element-summary circuit guard between tests."""
    pf._element_summary_guard._reset()
    yield
    pf._element_summary_guard._reset()


def _make_provenance(merged_at: str = "2026-05-25T08-00-00Z") -> OwnedStoreProvenance:
    return OwnedStoreProvenance(
        pointer_path="/some/path/_owned_latest.json",
        merged_at=merged_at,
        baseline_captured_at="2026-05-25T06-00-00Z",
        incremental_count=4,
        staleness_hours=2.0,
        row_counts={"player_gw_stats": 25000},
    )


def _sample_summary(element_id: int = 351) -> dict:
    return {
        "history": [
            {
                "element": element_id,
                "round": 36,
                "total_points": 8,
                "minutes": 90,
                "goals_scored": 1,
                "assists": 0,
                "bonus": 1,
                "bps": 28,
                "expected_goals": 0.55,
                "expected_assists": 0.12,
                "expected_goal_involvements": 0.67,
                "value": 145,
                "was_home": True,
                "opponent_team": 11,
            },
        ],
        "fixtures": [],
        "history_past": [],
    }


BOOTSTRAP: dict = {"elements": [], "teams": [], "events": []}


# ---------------------------------------------------------------------------
# (a) Live succeeds → fallback not invoked
# ---------------------------------------------------------------------------

class TestLiveSucceeds:
    def test_fallback_not_called_when_live_succeeds(self, monkeypatch):
        live_summary = _sample_summary(351)
        mock_live = MagicMock(return_value=live_summary)
        monkeypatch.setattr(pf, "get_element_summary", mock_live)

        mock_fallback = MagicMock()
        monkeypatch.setattr(pf, "load_element_summary_from_owned_store", mock_fallback)

        result = pf._fetch_element_summary(351, BOOTSTRAP)

        assert result is live_summary
        mock_fallback.assert_not_called()


# ---------------------------------------------------------------------------
# (b) Live fails (exception) → fallback succeeds
# ---------------------------------------------------------------------------

class TestFallbackSuccess:
    def test_fallback_returned_with_provenance_log(self, monkeypatch, caplog):
        mock_live = MagicMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(pf, "get_element_summary", mock_live)

        fb_summary = _sample_summary(351)
        fb_prov = _make_provenance()
        mock_fb = MagicMock(return_value=(fb_summary, fb_prov))
        monkeypatch.setattr(pf, "load_element_summary_from_owned_store", mock_fb)

        with caplog.at_level(logging.WARNING, logger=pf.__name__):
            result = pf._fetch_element_summary(351, BOOTSTRAP)

        assert result is fb_summary
        mock_fb.assert_called_once_with(351)

        fallback_records = [
            r for r in caplog.records
            if "element_summary_owned_store_fallback" in r.getMessage()
        ]
        assert len(fallback_records) >= 1, "Expected WARNING for owned_store fallback"
        msg = fallback_records[0].getMessage()
        assert "merged_at" in msg
        assert "staleness_hours" in msg
        assert "incremental_count" in msg
        assert "element_id" in msg


# ---------------------------------------------------------------------------
# (c) Live fails AND OwnedStoreUnavailable → returns None
# ---------------------------------------------------------------------------

class TestFallbackAlsoUnavailable:
    def test_returns_none_no_crash(self, monkeypatch):
        monkeypatch.setattr(
            pf, "get_element_summary",
            MagicMock(side_effect=RuntimeError("network down")),
        )
        monkeypatch.setattr(
            pf, "load_element_summary_from_owned_store",
            MagicMock(side_effect=OwnedStoreUnavailable("no owned rows for element_id=351")),
        )

        result = pf._fetch_element_summary(351, BOOTSTRAP)
        assert result is None


# ---------------------------------------------------------------------------
# (d) Null-tolerant: NULL value / was_home / opponent_team preserved as None
# ---------------------------------------------------------------------------

class TestNullTolerance:
    def test_nulls_pass_through_as_none(self, monkeypatch):
        monkeypatch.setattr(
            pf, "get_element_summary",
            MagicMock(side_effect=RuntimeError("live down")),
        )

        history_row = {
            "element": 351,
            "round": 37,
            "total_points": 5,
            "minutes": 60,
            "goals_scored": 0,
            "assists": 1,
            "bonus": 0,
            "bps": 15,
            "expected_goals": 0.1,
            "expected_assists": 0.4,
            "expected_goal_involvements": 0.5,
            "value": None,           # NULL from incremental-winning row
            "was_home": None,        # NULL
            "opponent_team": None,   # NULL
        }
        fb_summary = {"history": [history_row], "fixtures": [], "history_past": []}
        monkeypatch.setattr(
            pf, "load_element_summary_from_owned_store",
            MagicMock(return_value=(fb_summary, _make_provenance())),
        )

        result = pf._fetch_element_summary(351, BOOTSTRAP)

        assert result is not None
        assert len(result["history"]) == 1
        row = result["history"][0]
        # Keys must be present (not missing), values must be None (not NaN, not synthesized)
        assert "value" in row and row["value"] is None
        assert "was_home" in row and row["was_home"] is None
        assert "opponent_team" in row and row["opponent_team"] is None


# ---------------------------------------------------------------------------
# (e) load_element_summary_from_owned_store is None (import failed)
# ---------------------------------------------------------------------------

class TestFallbackModuleAbsent:
    def test_no_fallback_attempt_when_loader_is_none(self, monkeypatch, caplog):
        monkeypatch.setattr(
            pf, "get_element_summary",
            MagicMock(side_effect=RuntimeError("live boom")),
        )
        monkeypatch.setattr(pf, "load_element_summary_from_owned_store", None)

        with caplog.at_level(logging.WARNING, logger=pf.__name__):
            result = pf._fetch_element_summary(351, BOOTSTRAP)

        assert result is None

        fallback_records = [
            r for r in caplog.records
            if "element_summary_owned_store_fallback" in r.getMessage()
        ]
        assert len(fallback_records) == 0, (
            "No fallback log should appear when loader is None"
        )


# ---------------------------------------------------------------------------
# (f) H4d: FPL_FORCE_FALLBACK_TOOLS env flag — operator force-fallback path
# ---------------------------------------------------------------------------

class TestForceFallbackToolsFlag:
    def test_truthy_flag_bypasses_live_and_calls_fallback(self, monkeypatch, caplog):
        monkeypatch.setenv("FPL_FORCE_FALLBACK_TOOLS", "1")

        mock_live = MagicMock(return_value=_sample_summary(351))
        monkeypatch.setattr(pf, "get_element_summary", mock_live)

        fb_summary = _sample_summary(351)
        mock_fb = MagicMock(return_value=(fb_summary, _make_provenance()))
        monkeypatch.setattr(pf, "load_element_summary_from_owned_store", mock_fb)

        with caplog.at_level(logging.WARNING, logger=pf.__name__):
            result = pf._fetch_element_summary(351, BOOTSTRAP)

        assert result is fb_summary
        mock_live.assert_not_called(), "live get_element_summary must NOT be called"
        mock_fb.assert_called_once_with(351)

        forced_records = [
            r for r in caplog.records
            if "element_summary_forced_fallback" in r.getMessage()
            and "FPL_FORCE_FALLBACK_TOOLS" in r.getMessage()
        ]
        assert len(forced_records) >= 1

    def test_flag_unset_uses_live_first_semantics(self, monkeypatch):
        """Regression guard: with the flag unset, the live path is used."""
        monkeypatch.delenv("FPL_FORCE_FALLBACK_TOOLS", raising=False)

        live_summary = _sample_summary(351)
        mock_live = MagicMock(return_value=live_summary)
        monkeypatch.setattr(pf, "get_element_summary", mock_live)

        mock_fb = MagicMock()
        monkeypatch.setattr(pf, "load_element_summary_from_owned_store", mock_fb)

        result = pf._fetch_element_summary(351, BOOTSTRAP)
        assert result is live_summary
        mock_fb.assert_not_called()
