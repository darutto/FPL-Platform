"""B4 PR 1: the read-only licensed runtime. Synthetic data and an in-memory store only: no network, no provider."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from football_intelligence.distribution.licensed_runtime import (
    LICENSED_CACHE_ROOT_ENV, LICENSED_SYNC_ENABLED_ENV, READABLE_TABLES, LicensedRuntimeHandle,
    LicensedTableRefused, licensed_startup_sync,
)
from football_intelligence.distribution.service import publish_build
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.ingestion.licensed.derive import DeriveReport, DerivedTables
from football_intelligence.ingestion.licensed.store import LICENSED_V1, PREFIX_SEGMENT, write_build
from football_intelligence.provenance import LIVE_TRIAL_LOCAL, LiveTrialProvenanceRefused


def _tables(observed="2026-10-24T12:00:00Z", element=501):
    return DerivedTables(
        lineup_snapshots=({"fixture_id": 301, "team": "ARS", "observed_at": observed, "state": "scheduled",
                           "confirmed": True, "formation": "4-3-3", "n_starters": 11, "n_bench": 0},),
        lineup_slots=({"fixture_id": 301, "team": "ARS", "observed_at": observed, "element": element, "starter": True,
                       "detailed_position": "Right Back", "grid_slot": "2:1", "side": "right"},),
        sidelined=(), squad_membership=(), cup_snapshots=(), report=DeriveReport(fixtures_seen=1),
    )


def _published(tmp_path: Path, build_id="pass-one") -> InMemoryArtifactStore:
    build = write_build(_tables(), {700001: 501}, tmp_path / "author", build_id=build_id, built_at="2026-10-24T12:01:00Z")
    store = InMemoryArtifactStore()
    publish_build(store, PREFIX_SEGMENT, build, family=LICENSED_V1)
    return store


def _env(tmp_path: Path, **extra) -> dict[str, str]:
    return {LICENSED_SYNC_ENABLED_ENV: "true", LICENSED_CACHE_ROOT_ENV: str(tmp_path / "cache"), **extra}


def test_it_is_off_unless_the_licensed_flag_is_set_even_with_credentials(tmp_path):
    env = {"FPL_FOOTBALL_REMOTE_ENDPOINT": "https://r2.example", "FPL_FOOTBALL_REMOTE_BUCKET": "private-bucket",
           "FPL_FOOTBALL_REMOTE_ACCESS_KEY_ID": "k", "FPL_FOOTBALL_REMOTE_SECRET_ACCESS_KEY": "s",
           LICENSED_CACHE_ROOT_ENV: str(tmp_path / "cache")}
    status = licensed_startup_sync(env)
    assert (status.state, status.reason_code) == ("disabled", "sync_not_enabled")
    assert not (tmp_path / "cache").exists()


def test_enabled_without_remote_configuration_is_disabled_not_an_error(tmp_path):
    status = licensed_startup_sync(_env(tmp_path))
    assert (status.state, status.reason_code) == ("disabled", "not_configured")


def test_a_published_licensed_build_syncs_and_its_tables_read(tmp_path):
    status = licensed_startup_sync(_env(tmp_path), store=_published(tmp_path))
    assert (status.state, status.reason_code, status.local_build_id) == ("ready", "synchronized", "pass-one")
    handle = LicensedRuntimeHandle(tmp_path / "cache")
    assert handle.manifest()["assumption_status"] == "licensed_starter"
    slots = handle.table("lineup_slots")
    assert list(slots.element) == [501] and list(slots.side) == ["right"]
    again = licensed_startup_sync(_env(tmp_path), store=_published(tmp_path / "second"))
    assert again.reason_code in {"already_current", "synchronized"}


def test_the_crosswalk_with_provider_ids_is_not_served(tmp_path):
    licensed_startup_sync(_env(tmp_path), store=_published(tmp_path))
    handle = LicensedRuntimeHandle(tmp_path / "cache")
    assert "crosswalk" not in READABLE_TABLES
    with pytest.raises(LicensedTableRefused):
        handle.table("crosswalk")
    with pytest.raises(LicensedTableRefused):
        handle.table("../manifest")


def test_a_trial_stamped_build_in_the_cache_is_refused_at_read(tmp_path):
    licensed_startup_sync(_env(tmp_path), store=_published(tmp_path))
    manifest_path = tmp_path / "cache" / "builds" / "pass-one" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["assumption_status"] = LIVE_TRIAL_LOCAL
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(Exception) as caught:  # the licensed validator and the shared trial refusal both stop it
        LicensedRuntimeHandle(tmp_path / "cache").table("lineup_slots")
    assert isinstance(caught.value, (LiveTrialProvenanceRefused, ValueError))


def test_a_failed_refresh_keeps_serving_the_last_good_build_as_degraded(tmp_path):
    licensed_startup_sync(_env(tmp_path), store=_published(tmp_path))
    status = licensed_startup_sync(_env(tmp_path), store=InMemoryArtifactStore())  # pointer missing remotely
    assert status.state == "degraded" and status.local_build_id == "pass-one"
    assert LicensedRuntimeHandle(tmp_path / "cache").build_id() == "pass-one"


def test_nothing_synced_and_a_failure_is_unavailable(tmp_path):
    status = licensed_startup_sync(_env(tmp_path), store=InMemoryArtifactStore())
    assert (status.state, status.local_build_id) == ("unavailable", None)


def test_the_status_carries_no_content(tmp_path):
    status = licensed_startup_sync(_env(tmp_path), store=_published(tmp_path))
    text = json.dumps(status.__dict__)
    assert "ARS" not in text and "501" not in text and "Right Back" not in text


def test_the_licensed_sync_cannot_read_the_canonical_prefix(tmp_path):
    from football_intelligence.distribution.family import FamilyPrefixError
    from football_intelligence.distribution.service import sync_build
    with pytest.raises(FamilyPrefixError):
        sync_build(InMemoryArtifactStore(), "football", tmp_path / "c", family=LICENSED_V1)
