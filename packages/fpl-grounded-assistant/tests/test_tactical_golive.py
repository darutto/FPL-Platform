"""
tests/test_tactical_golive.py
=============================
Go-live wiring tests for the tactical-store startup sync (T-zonal).

Covers:
(i)   Default-off gate: TACTICAL_STORE_SYNC_ENABLED parsing.
(ii)  Flag off → /healthz payload has NO tactical_store_sync key (byte-for-
      byte unchanged vs pre-go-live) and lifespan never calls the sync.
(iii) Flag on → lifespan calls the sync; a mocked-R2 sync with a local
      fixture store yields /healthz tactical_store_sync.ok == true.
(iv)  Team-map completeness: all 20 current PL teams resolve through the
      FPL-short-name → Understat-name bridge (season rollover fails loudly).

No network anywhere: R2 is mocked at the boto3-client seam.
"""
from __future__ import annotations

import asyncio
import shutil
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_tactical import publish as tactical_publish
from fpl_tactical.publish import TacticalSyncResult


client = TestClient(fpl_server.app)


@pytest.fixture(autouse=True)
def _reset_tactical_state(monkeypatch):
    """Isolate each test: flag unset, last-result cache cleared."""
    monkeypatch.delenv("TACTICAL_STORE_SYNC_ENABLED", raising=False)
    monkeypatch.setattr(tactical_publish, "_LAST_TACTICAL_SYNC_RESULT", None)
    yield


def _run_lifespan():
    """Drive fpl_server.lifespan() once (bootstrap/classifier pre-seeded)."""
    async def go():
        async with fpl_server.lifespan(fpl_server.app):
            pass
    asyncio.run(go())


# ---------------------------------------------------------------------------
# (i) gate parsing
# ---------------------------------------------------------------------------

class TestGate:
    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", " yes "])
    def test_truthy_values_enable(self, monkeypatch, raw):
        monkeypatch.setenv("TACTICAL_STORE_SYNC_ENABLED", raw)
        assert tactical_publish.tactical_sync_enabled() is True

    @pytest.mark.parametrize("raw", ["", "0", "false", "no", "on"])
    def test_everything_else_is_off(self, monkeypatch, raw):
        monkeypatch.setenv("TACTICAL_STORE_SYNC_ENABLED", raw)
        assert tactical_publish.tactical_sync_enabled() is False

    def test_default_is_off(self):
        assert tactical_publish.tactical_sync_enabled() is False


# ---------------------------------------------------------------------------
# (ii) flag off → no behavior change
# ---------------------------------------------------------------------------

class TestFlagOff:
    def test_healthz_has_no_tactical_key(self):
        payload = client.get("/healthz").json()
        assert "tactical_store_sync" not in payload
        # pre-existing keys untouched
        assert "routing_counters" in payload
        assert "owned_store_sync" in payload

    def test_lifespan_does_not_sync(self, monkeypatch):
        monkeypatch.setattr(fpl_server, "_bootstrap", {"elements": []})
        monkeypatch.setattr(fpl_server, "_classifier_client", object())
        mock_sync = MagicMock()
        monkeypatch.setattr(fpl_server, "sync_tactical_store_from_r2", mock_sync)
        _run_lifespan()
        mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# (iii) flag on → sync runs; healthz reports ok
# ---------------------------------------------------------------------------

class TestFlagOn:
    def test_lifespan_calls_sync_when_enabled(self, monkeypatch):
        monkeypatch.setenv("TACTICAL_STORE_SYNC_ENABLED", "1")
        monkeypatch.setattr(fpl_server, "_bootstrap", {"elements": []})
        monkeypatch.setattr(fpl_server, "_classifier_client", object())
        mock_sync = MagicMock(
            return_value=TacticalSyncResult(ok=True, season="2025-2026",
                                            files_synced=2, error=None)
        )
        monkeypatch.setattr(fpl_server, "sync_tactical_store_from_r2", mock_sync)
        _run_lifespan()
        mock_sync.assert_called_once_with()

    def test_mocked_r2_sync_then_healthz_ok(self, tmp_path, monkeypatch):
        """Full seam test: fake R2 client delivers a real parquet + pointer;
        /healthz then reports tactical_store_sync.ok == true."""
        monkeypatch.setenv("TACTICAL_STORE_SYNC_ENABLED", "1")
        monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path / "store"))

        # Source objects the fake bucket serves.
        src = tmp_path / "bucket"
        src.mkdir()
        pd.DataFrame([{
            "season": "2025-2026", "match_id": 1, "date": "2025-09-01T15:00:00",
            "shooting_team": "Burnley", "conceding_team": "Crystal Palace",
            "player": "Someone", "is_home_shot": True, "minute": 10,
            "x": 0.9, "y": 0.2, "xg": 0.1, "situation": "Open Play",
            "shot_type": "Right Foot", "result": "Saved Shot",
        }]).to_parquet(src / "understat_shots.parquet", index=False)
        (src / "_tactical_latest.json").write_text('{"season": "2025-2026"}')

        class FakeR2Client:
            def download_file(self, bucket, key, dest):
                shutil.copy(src / key.rsplit("/", 1)[-1], dest)

        monkeypatch.setenv("OWNED_STORE_R2_ENDPOINT", "https://fake")
        monkeypatch.setenv("OWNED_STORE_R2_BUCKET", "fake-bucket")
        monkeypatch.setenv("OWNED_STORE_R2_ACCESS_KEY_ID", "k")
        monkeypatch.setenv("OWNED_STORE_R2_SECRET_ACCESS_KEY", "s")
        monkeypatch.setattr(tactical_publish, "_make_r2_client", lambda: FakeR2Client())

        result = tactical_publish.sync_tactical_store_from_r2("2025-2026")
        assert result.ok is True
        assert result.files_synced == 2
        # the synced parquet is really on disk where the engine will look
        assert (tmp_path / "store" / "seasons" / "2025-2026" / "understat_shots.parquet").exists()

        payload = client.get("/healthz").json()
        tac = payload["tactical_store_sync"]
        assert tac["ok"] is True
        assert tac["season"] == "2025-2026"
        assert tac["files_synced"] == 2
        assert tac["error"] is None

    def test_failed_sync_reports_not_ok(self, monkeypatch):
        """No R2 env vars → fail-soft result; /healthz shows ok=false."""
        monkeypatch.setenv("TACTICAL_STORE_SYNC_ENABLED", "1")
        result = tactical_publish.sync_tactical_store_from_r2("2025-2026")
        assert result.ok is False
        payload = client.get("/healthz").json()
        assert payload["tactical_store_sync"]["ok"] is False
        assert payload["tactical_store_sync"]["error"]


# ---------------------------------------------------------------------------
# (iv) team-map completeness — season rollover must fail loudly
# ---------------------------------------------------------------------------

# The 20 Premier League teams of 2025/26 as they appear in the FPL bootstrap.
_PL_2025_26 = [
    ("ARS", "Arsenal"), ("AVL", "Aston Villa"), ("BOU", "Bournemouth"),
    ("BRE", "Brentford"), ("BHA", "Brighton"), ("BUR", "Burnley"),
    ("CHE", "Chelsea"), ("CRY", "Crystal Palace"), ("EVE", "Everton"),
    ("FUL", "Fulham"), ("LEE", "Leeds"), ("LIV", "Liverpool"),
    ("MCI", "Man City"), ("MUN", "Man Utd"), ("NEW", "Newcastle"),
    ("NFO", "Nott'm Forest"), ("SUN", "Sunderland"), ("TOT", "Spurs"),
    ("WHU", "West Ham"), ("WOL", "Wolves"),
]


class TestTeamMapCompleteness:
    def test_all_20_teams_resolve_to_store_names(self):
        from fpl_grounded_assistant.zonal_weakness_tool import (
            _SHORT_TO_UNDERSTAT,
            _to_store_team,
        )
        bootstrap = {
            "teams": [
                {"id": i + 1, "short_name": short, "name": name}
                for i, (short, name) in enumerate(_PL_2025_26)
            ]
        }
        assert len(_PL_2025_26) == 20
        for short, name in _PL_2025_26:
            assert short in _SHORT_TO_UNDERSTAT, (
                f"{short} missing from _SHORT_TO_UNDERSTAT — update the map "
                f"for the new season (rollover must fail loudly, not as "
                f"silent not_found)"
            )
            # Resolve through the bridge by short code (the map's contract).
            # NOTE: some FPL *display* names ("Man City", "Spurs", "Wolves")
            # dead-end in team_fixture_calendar._resolve_team because its
            # alias map rewrites them to strings that match nothing in the
            # bootstrap — a pre-existing resolver quirk shared by all team
            # tools, out of scope for this go-live slice.
            resolved = _to_store_team(short, bootstrap)
            assert resolved == _SHORT_TO_UNDERSTAT[short]
        # bridge targets must be 20 distinct Understat titles
        assert len(set(_SHORT_TO_UNDERSTAT.values())) == len(_SHORT_TO_UNDERSTAT) == 20
