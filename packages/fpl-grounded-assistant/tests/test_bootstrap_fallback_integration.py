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


# ---------------------------------------------------------------------------
# H4c: team_fixtures reconstruction inside load_bootstrap_from_owned_store
# ---------------------------------------------------------------------------

class TestTeamFixturesReconstruction:
    """Unit tests for _build_team_fixtures_from_owned_store."""

    def _teams(self):
        return [
            {"id": 1, "strength": 4},
            {"id": 2, "strength": 2},
            {"id": 3, "strength": 5},
            {"id": 4},  # missing strength -> defaults to 3
        ]

    def test_a_shape_and_required_keys(self):
        import pandas as pd
        from fpl_grounded_assistant.owned_store_fallback import (
            _build_team_fixtures_from_owned_store,
        )

        fixtures_df = pd.DataFrame([
            {"event_id": 5, "team_h": 1, "team_a": 2,
             "team_h_difficulty": 3, "team_a_difficulty": 4},
            {"event_id": 5, "team_h": 3, "team_a": 4,
             "team_h_difficulty": 2, "team_a_difficulty": 5},
        ])
        out = _build_team_fixtures_from_owned_store(fixtures_df, self._teams())

        assert isinstance(out, dict) and len(out) > 0
        assert set(out.keys()) == {1, 2, 3, 4}
        for team_id, fixtures in out.items():
            for fx in fixtures:
                assert set(fx.keys()) == {
                    "gameweek", "opponent_team", "is_home", "difficulty"
                }
                assert isinstance(fx["gameweek"], int)
                assert isinstance(fx["opponent_team"], int)
                assert isinstance(fx["is_home"], bool)
                assert isinstance(fx["difficulty"], int)

    def test_b_sort_order(self):
        import pandas as pd
        from fpl_grounded_assistant.owned_store_fallback import (
            _build_team_fixtures_from_owned_store,
        )

        # Team 1 plays multiple gameweeks against different opponents, out of order
        fixtures_df = pd.DataFrame([
            {"event_id": 7, "team_h": 1, "team_a": 3,
             "team_h_difficulty": 2, "team_a_difficulty": 4},
            {"event_id": 6, "team_h": 1, "team_a": 4,
             "team_h_difficulty": 2, "team_a_difficulty": 4},
            {"event_id": 6, "team_h": 2, "team_a": 1,   # team 1 away vs 2 in GW6
             "team_h_difficulty": 3, "team_a_difficulty": 3},
        ])
        out = _build_team_fixtures_from_owned_store(fixtures_df, self._teams())
        team1 = out[1]
        keys = [(fx["gameweek"], fx["opponent_team"]) for fx in team1]
        assert keys == sorted(keys)

    def test_c_difficulty_fallback_chain(self):
        import pandas as pd
        from fpl_grounded_assistant.owned_store_fallback import (
            _build_team_fixtures_from_owned_store,
        )

        # Row 1: null team_h_difficulty -> should fall back to team_a strength (2)
        # Row 2: null both, opponent (team 4) has no strength -> default 3
        fixtures_df = pd.DataFrame([
            {"event_id": 1, "team_h": 1, "team_a": 2,
             "team_h_difficulty": None, "team_a_difficulty": None},
            {"event_id": 2, "team_h": 1, "team_a": 4,
             "team_h_difficulty": None, "team_a_difficulty": None},
        ])
        out = _build_team_fixtures_from_owned_store(fixtures_df, self._teams())

        # Team 1 home vs team 2: fallback to team_a strength = 2
        fx_gw1 = [fx for fx in out[1] if fx["gameweek"] == 1][0]
        assert fx_gw1["difficulty"] == 2

        # Team 1 home vs team 4 (no strength): default 3
        fx_gw2 = [fx for fx in out[1] if fx["gameweek"] == 2][0]
        assert fx_gw2["difficulty"] == 3

        # Team 2 away vs team 1 (null away_difficulty -> team 1 strength = 4)
        fx_team2 = [fx for fx in out[2] if fx["gameweek"] == 1][0]
        assert fx_team2["difficulty"] == 4

    def test_d_empty_fixtures_df(self):
        import pandas as pd
        from fpl_grounded_assistant.owned_store_fallback import (
            _build_team_fixtures_from_owned_store,
        )
        out = _build_team_fixtures_from_owned_store(
            pd.DataFrame(columns=["event_id", "team_h", "team_a",
                                  "team_h_difficulty", "team_a_difficulty"]),
            self._teams(),
        )
        assert out == {}

    def test_f_null_event_id_skipped(self):
        import pandas as pd
        from fpl_grounded_assistant.owned_store_fallback import (
            _build_team_fixtures_from_owned_store,
        )
        fixtures_df = pd.DataFrame([
            {"event_id": None, "team_h": 1, "team_a": 2,
             "team_h_difficulty": 3, "team_a_difficulty": 4},
            {"event_id": 5, "team_h": 1, "team_a": 2,
             "team_h_difficulty": 3, "team_a_difficulty": 4},
        ])
        out = _build_team_fixtures_from_owned_store(fixtures_df, self._teams())
        assert len(out[1]) == 1
        assert out[1][0]["gameweek"] == 5


class TestLoadBootstrapTeamFixturesIntegration:
    """Integration: load_bootstrap_from_owned_store wires team_fixtures
    and tolerates missing fixtures.parquet."""

    def _patch_preamble(self, monkeypatch, request, tmp_path):
        """Make _read_pointer_and_build_provenance return a tmp dir + minimal provenance.

        Patches via load_bootstrap_from_owned_store.__globals__ (the module dict
        actually consulted at runtime). test_fixtures_fallback.py uses a custom
        loader that can desync sys.modules vs the package attribute, so we
        target the function's own globals to be unambiguous.
        """
        from fpl_grounded_assistant.owned_store_fallback import (
            load_bootstrap_from_owned_store as _load,
        )
        osf_globals = _load.__globals__
        OwnedStoreProvenance = osf_globals["OwnedStoreProvenance"]

        prov = OwnedStoreProvenance(
            pointer_path=str(tmp_path / "_owned_latest.json"),
            merged_at="2026-05-27T10-00-00Z",
            baseline_captured_at="2026-05-27T08-00-00Z",
            incremental_count=1,
            staleness_hours=1.0,
            row_counts={"players": 700, "teams": 20, "events": 38},
        )

        sentinel = object()
        original = osf_globals.get("_read_pointer_and_build_provenance", sentinel)
        osf_globals["_read_pointer_and_build_provenance"] = (
            lambda season: (tmp_path, prov)
        )

        def _restore():
            if original is sentinel:
                osf_globals.pop("_read_pointer_and_build_provenance", None)
            else:
                osf_globals["_read_pointer_and_build_provenance"] = original

        request.addfinalizer(_restore)
        return prov

    def _write_core_parquets(self, tmp_path):
        import pandas as pd
        pd.DataFrame([
            {"player_id": 1, "team_id": 1, "web_name": "A"},
        ]).to_parquet(tmp_path / "players.parquet")
        pd.DataFrame([
            {"team_id": 1, "name": "Team1", "strength": 4},
            {"team_id": 2, "name": "Team2", "strength": 2},
        ]).to_parquet(tmp_path / "teams.parquet")
        pd.DataFrame([
            {"event_id": 1, "finished": False, "is_current": True},
        ]).to_parquet(tmp_path / "events.parquet")

    def test_a_team_fixtures_present_when_parquet_exists(self, monkeypatch, request, tmp_path):
        import sys
        import pandas as pd
        from fpl_grounded_assistant.owned_store_fallback import (
            load_bootstrap_from_owned_store as _load,
        )
        load_bootstrap_from_owned_store = sys.modules[_load.__module__].load_bootstrap_from_owned_store

        self._patch_preamble(monkeypatch, request, tmp_path)
        self._write_core_parquets(tmp_path)
        pd.DataFrame([
            {"event_id": 1, "team_h": 1, "team_a": 2,
             "team_h_difficulty": 3, "team_a_difficulty": 4},
        ]).to_parquet(tmp_path / "fixtures.parquet")

        bootstrap, prov = load_bootstrap_from_owned_store(season="2025-2026")
        assert "team_fixtures" in bootstrap
        assert 1 in bootstrap["team_fixtures"] and 2 in bootstrap["team_fixtures"]
        fx = bootstrap["team_fixtures"][1][0]
        assert fx == {"gameweek": 1, "opponent_team": 2,
                      "is_home": True, "difficulty": 3}
        assert prov.row_counts.get("fixtures") == 1
        # Existing keys preserved
        assert "players" in prov.row_counts

    def test_e_missing_fixtures_parquet_tolerated(self, monkeypatch, request, tmp_path, caplog):
        import sys
        from fpl_grounded_assistant.owned_store_fallback import (
            load_bootstrap_from_owned_store as _load,
        )
        load_bootstrap_from_owned_store = sys.modules[_load.__module__].load_bootstrap_from_owned_store

        self._patch_preamble(monkeypatch, request, tmp_path)
        self._write_core_parquets(tmp_path)
        # NOTE: no fixtures.parquet written

        with caplog.at_level(logging.DEBUG,
                             logger="fpl_grounded_assistant.owned_store_fallback"):
            bootstrap, prov = load_bootstrap_from_owned_store(season="2025-2026")

        assert bootstrap["team_fixtures"] == {}
        assert prov.row_counts.get("fixtures") == 0
        # DEBUG log emitted
        debug_msgs = [r.getMessage() for r in caplog.records
                      if "owned_store_team_fixtures_skipped" in r.getMessage()]
        assert len(debug_msgs) >= 1

    def test_d_empty_fixtures_parquet_tolerated(self, monkeypatch, request, tmp_path):
        import sys
        import pandas as pd
        from fpl_grounded_assistant.owned_store_fallback import (
            load_bootstrap_from_owned_store as _load,
        )
        load_bootstrap_from_owned_store = sys.modules[_load.__module__].load_bootstrap_from_owned_store

        self._patch_preamble(monkeypatch, request, tmp_path)
        self._write_core_parquets(tmp_path)
        pd.DataFrame(
            columns=["event_id", "team_h", "team_a",
                     "team_h_difficulty", "team_a_difficulty"]
        ).astype({
            "event_id": "Int64", "team_h": "Int64", "team_a": "Int64",
            "team_h_difficulty": "Int64", "team_a_difficulty": "Int64",
        }).to_parquet(tmp_path / "fixtures.parquet")

        bootstrap, prov = load_bootstrap_from_owned_store(season="2025-2026")
        assert bootstrap["team_fixtures"] == {}
        assert prov.row_counts.get("fixtures") == 0
