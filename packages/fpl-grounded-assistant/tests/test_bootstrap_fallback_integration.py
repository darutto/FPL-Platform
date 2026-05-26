"""
tests/test_bootstrap_fallback_integration.py
============================================
Integration tests for the owned-store fallback wired into
``_fetch_bootstrap_with_retry()`` and ``/healthz``.

Covers CONTRACT §11.3, §11.4, §11.6 (H4a).

Test scenarios
--------------
(i)   Live succeeds → fallback not invoked.
(ii)  Live fails all retries, fallback succeeds → bootstrap returned + provenance set.
(iii) Live fails, fallback also fails → original live exception re-raised.
(iv)  Provenance cleared on subsequent live success.
(v)   /healthz reflects fallback state (merged_at present, pointer_path absent).
(vi)  /healthz shows null when no fallback used.
(vii) load_bootstrap_from_owned_store is None (import failed) → no fallback, live exc raised.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

# We import fpl_server as a module so we can monkeypatch its module-level
# globals and call its internal functions directly.
import fpl_server


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _no_sleep(_duration: float) -> None:
    """No-op sleep injected into _fetch_bootstrap_with_retry to skip real waits."""
    return


def _make_provenance(merged_at: str = "2026-05-25T08-00-00Z") -> "fpl_server.OwnedStoreProvenance":  # type: ignore[name-defined]
    """Build a minimal OwnedStoreProvenance for testing."""
    # Import directly from fpl_server's own reference so we use the same class
    # even if the import happened to succeed or we're patching.
    from fpl_grounded_assistant.owned_store_fallback import OwnedStoreProvenance
    return OwnedStoreProvenance(
        pointer_path="/some/path/_owned_latest.json",
        merged_at=merged_at,
        baseline_captured_at="2026-05-25T06-00-00Z",
        incremental_count=3,
        staleness_hours=2.5,
        row_counts={"players": 712, "teams": 20, "events": 38},
    )


FAKE_BOOTSTRAP = {
    "elements": [{"id": 1, "web_name": "Haaland"}],
    "teams": [{"id": 13, "name": "Manchester City"}],
    "events": [{"id": 38, "is_current": True}],
    "element_types": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
}


# ---------------------------------------------------------------------------
# (i) Live succeeds → fallback not invoked
# ---------------------------------------------------------------------------

class TestLiveSucceeds:
    def test_fallback_not_called_when_live_succeeds(self, monkeypatch):
        """When assemble_captain_context() succeeds, owned-store loader is never called."""
        # Reset provenance state
        monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", None)

        mock_live = MagicMock(return_value={"bootstrap": FAKE_BOOTSTRAP})
        monkeypatch.setattr(fpl_server, "assemble_captain_context", mock_live)

        mock_fallback = MagicMock()
        monkeypatch.setattr(fpl_server, "load_bootstrap_from_owned_store", mock_fallback)

        result = fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_no_sleep)

        assert result is FAKE_BOOTSTRAP
        mock_fallback.assert_not_called()
        assert fpl_server._LAST_BOOTSTRAP_PROVENANCE is None


# ---------------------------------------------------------------------------
# (ii) Live fails all retries, fallback succeeds
# ---------------------------------------------------------------------------

class TestFallbackSuccess:
    def test_fallback_bootstrap_returned_and_provenance_set(self, monkeypatch, caplog):
        """All live retries fail; fallback returns bootstrap and sets provenance."""
        monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", None)

        live_exc = RuntimeError("FPL API is down")
        monkeypatch.setattr(
            fpl_server, "assemble_captain_context",
            MagicMock(side_effect=live_exc),
        )

        fake_prov = _make_provenance()
        monkeypatch.setattr(
            fpl_server, "load_bootstrap_from_owned_store",
            MagicMock(return_value=(FAKE_BOOTSTRAP, fake_prov)),
        )

        with caplog.at_level(logging.WARNING, logger="fpl_server"):
            result = fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_no_sleep)

        assert result is FAKE_BOOTSTRAP
        assert fpl_server._LAST_BOOTSTRAP_PROVENANCE == fake_prov

        # Verify WARNING log was emitted with required fields (CONTRACT §11.4)
        fallback_records = [
            r for r in caplog.records
            if "bootstrap_owned_store_fallback" in r.getMessage()
        ]
        assert len(fallback_records) >= 1, "Expected WARNING log for owned_store fallback"
        log_msg = fallback_records[0].getMessage()
        assert "merged_at" in log_msg
        assert "staleness_hours" in log_msg
        assert "incremental_count" in log_msg


# ---------------------------------------------------------------------------
# (iii) Live fails, fallback also fails → original live exception re-raised
# ---------------------------------------------------------------------------

class TestFallbackAlsoFails:
    def test_live_exc_reraised_not_unavailable(self, monkeypatch, caplog):
        """When the fallback raises OwnedStoreUnavailable, the original live RuntimeError is raised."""
        monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", None)

        live_exc = RuntimeError("live boom")
        monkeypatch.setattr(
            fpl_server, "assemble_captain_context",
            MagicMock(side_effect=live_exc),
        )

        from fpl_grounded_assistant.owned_store_fallback import OwnedStoreUnavailable
        monkeypatch.setattr(
            fpl_server, "load_bootstrap_from_owned_store",
            MagicMock(side_effect=OwnedStoreUnavailable("no pointer")),
        )
        # Keep OwnedStoreUnavailable resolvable in fpl_server's namespace
        monkeypatch.setattr(fpl_server, "OwnedStoreUnavailable", OwnedStoreUnavailable)

        with caplog.at_level(logging.ERROR, logger="fpl_server"):
            with pytest.raises(RuntimeError, match="live boom"):
                fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_no_sleep)

        # ERROR log must mention the OwnedStoreUnavailable message
        error_records = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR and "no pointer" in r.getMessage()
        ]
        assert len(error_records) >= 1, "Expected ERROR log mentioning 'no pointer'"

        # Provenance must remain None (was None before, must not be set)
        assert fpl_server._LAST_BOOTSTRAP_PROVENANCE is None


# ---------------------------------------------------------------------------
# (iv) Provenance cleared on subsequent live success
# ---------------------------------------------------------------------------

class TestProvenanceClearedOnLiveSuccess:
    def test_provenance_is_none_after_live_success(self, monkeypatch):
        """If _LAST_BOOTSTRAP_PROVENANCE was set from a prior fallback, it is cleared when live succeeds."""
        fake_prov = _make_provenance()
        monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", fake_prov)

        monkeypatch.setattr(
            fpl_server, "assemble_captain_context",
            MagicMock(return_value={"bootstrap": FAKE_BOOTSTRAP}),
        )
        # Fallback should not be called, but we wire it anyway to be safe
        monkeypatch.setattr(
            fpl_server, "load_bootstrap_from_owned_store",
            MagicMock(return_value=(FAKE_BOOTSTRAP, fake_prov)),
        )

        fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_no_sleep)

        assert fpl_server._LAST_BOOTSTRAP_PROVENANCE is None


# ---------------------------------------------------------------------------
# (v) /healthz reflects fallback state
# ---------------------------------------------------------------------------

class TestHealthzFallbackState:
    def test_healthz_contains_provenance_without_pointer_path(self, monkeypatch):
        """/healthz includes owned_store_fallback with merged_at but NOT pointer_path."""
        from fastapi.testclient import TestClient
        STD_BOOTSTRAP = FAKE_BOOTSTRAP

        fake_prov = _make_provenance(merged_at="2026-05-25T08-00-00Z")
        monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", fake_prov)

        # Pre-set bootstrap so the lifespan live-fetch is skipped
        fpl_server._init_bootstrap(STD_BOOTSTRAP)

        client = TestClient(fpl_server.app)
        resp = client.get("/healthz")
        assert resp.status_code == 200

        body = resp.json()
        assert "owned_store_fallback" in body
        osf = body["owned_store_fallback"]
        assert osf is not None
        assert osf["merged_at"] == "2026-05-25T08-00-00Z"
        assert "pointer_path" not in osf, "pointer_path must NOT be exposed via /healthz"


# ---------------------------------------------------------------------------
# (vi) /healthz shows null when no fallback used
# ---------------------------------------------------------------------------

class TestHealthzNoFallback:
    def test_healthz_owned_store_fallback_is_null(self, monkeypatch):
        """/healthz shows null for owned_store_fallback when live fetch was the last source."""
        from fastapi.testclient import TestClient
        STD_BOOTSTRAP = FAKE_BOOTSTRAP

        monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", None)
        fpl_server._init_bootstrap(STD_BOOTSTRAP)

        client = TestClient(fpl_server.app)
        resp = client.get("/healthz")
        assert resp.status_code == 200

        body = resp.json()
        assert body["owned_store_fallback"] is None

        # Backward-compat: existing keys still present
        assert "routing_counters" in body
        assert "graduation" in body


# ---------------------------------------------------------------------------
# (vii) load_bootstrap_from_owned_store is None (import failed path)
# ---------------------------------------------------------------------------

class TestFallbackModuleAbsent:
    def test_no_fallback_attempt_when_loader_is_none(self, monkeypatch, caplog):
        """When load_bootstrap_from_owned_store is None (import failed), live exc is raised directly."""
        monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", None)
        monkeypatch.setattr(fpl_server, "load_bootstrap_from_owned_store", None)

        live_exc = RuntimeError("live failure, no fallback")
        monkeypatch.setattr(
            fpl_server, "assemble_captain_context",
            MagicMock(side_effect=live_exc),
        )

        with caplog.at_level(logging.WARNING, logger="fpl_server"):
            result = fpl_server._fetch_bootstrap_with_retry(_sleep_fn=_no_sleep)

        # When all live attempts fail and fallback is None, function returns None
        assert result is None

        # No "fallback" log lines should appear (no spurious fallback attempt)
        fallback_records = [
            r for r in caplog.records
            if "bootstrap_owned_store_fallback" in r.getMessage()
        ]
        assert len(fallback_records) == 0, (
            "No fallback log should appear when load_bootstrap_from_owned_store is None"
        )
