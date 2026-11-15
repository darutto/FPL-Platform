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


# ---- B4: periodic re-sync (a new build is picked up without a restart) ---------------------------------------------

import time  # noqa: E402

from football_intelligence.distribution.licensed_runtime import (  # noqa: E402
    DEFAULT_RESYNC_SECONDS, KEEP_BUILDS, MIN_RESYNC_SECONDS, LicensedResync, prune_old_builds, resync_interval,
)


def _publish(store, tmp_path, build_id, element=501, previous=None):
    build = write_build(_tables(element=element), {700001: element}, tmp_path / "author", build_id=build_id,
                        built_at="2026-10-24T12:01:00Z", previous=previous)
    publish_build(store, PREFIX_SEGMENT, build, family=LICENSED_V1)
    return build


def _handle(tmp_path):
    return LicensedRuntimeHandle(tmp_path / "cache")


def test_a_new_build_is_picked_up_without_a_restart(tmp_path):
    store = InMemoryArtifactStore()
    first = _publish(store, tmp_path, "pass-one")
    resync = LicensedResync(_env(tmp_path), store=store, interval_seconds=1)
    assert resync.run_once().reason_code == "synchronized" and _handle(tmp_path).build_id() == "pass-one"
    _publish(store, tmp_path, "pass-two", element=502, previous=first)     # the ingestion publishes while we run
    status = resync.run_once()
    assert (status.state, status.reason_code, status.local_build_id) == ("ready", "synchronized", "pass-two")
    assert _handle(tmp_path).build_id() == "pass-two" and list(_handle(tmp_path).table("lineup_slots").element) == [501, 502]


def test_an_unchanged_pointer_downloads_nothing(tmp_path):
    store = InMemoryArtifactStore()
    _publish(store, tmp_path, "pass-one")
    resync = LicensedResync(_env(tmp_path), store=store, interval_seconds=1)
    resync.run_once()
    again = resync.run_once()
    assert again.reason_code == "already_current" and resync.runs == 2


def test_a_failed_refresh_keeps_the_build_in_use(tmp_path):
    store = InMemoryArtifactStore()
    first = _publish(store, tmp_path, "pass-one")
    resync = LicensedResync(_env(tmp_path), store=store, interval_seconds=1)
    resync.run_once()
    _publish(store, tmp_path, "pass-two", element=502, previous=first)

    store.fail_on.add(("read", f"{PREFIX_SEGMENT}/{LICENSED_V1.pointer_name}"))   # the bucket stops answering
    status = resync.run_once()
    assert status.state == "degraded" and status.local_build_id == "pass-one"
    assert _handle(tmp_path).build_id() == "pass-one"            # the old build still serves
    assert list(_handle(tmp_path).table("lineup_slots").element) == [501]


def test_a_corrupted_remote_artifact_leaves_no_half_synced_build(tmp_path):
    store = InMemoryArtifactStore()
    first = _publish(store, tmp_path, "pass-one")
    resync = LicensedResync(_env(tmp_path), store=store, interval_seconds=1)
    resync.run_once()
    _publish(store, tmp_path, "pass-two", element=502, previous=first)
    store.objects[f"{PREFIX_SEGMENT}/builds/pass-two/datasets/lineup_slots.parquet"] = b"tampered"
    status = resync.run_once()
    assert status.state == "degraded" and _handle(tmp_path).build_id() == "pass-one"
    assert sorted(p.name for p in (tmp_path / "cache" / "builds").iterdir()) == ["pass-one"]


def test_the_loop_never_raises_even_if_the_sync_itself_does(tmp_path, monkeypatch):
    resync = LicensedResync(_env(tmp_path), store=InMemoryArtifactStore(), interval_seconds=1)
    monkeypatch.setattr("football_intelligence.distribution.licensed_runtime.licensed_startup_sync",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    status = resync.run_once()
    assert (status.state, status.reason_code) == ("unavailable", "resync_failed")


def test_it_does_not_start_unless_the_sync_flag_is_on(tmp_path):
    off = LicensedResync({LICENSED_CACHE_ROOT_ENV: str(tmp_path / "cache")}, store=InMemoryArtifactStore(), interval_seconds=1)
    assert off.start() is False and off._thread is None
    zero = LicensedResync(_env(tmp_path), store=InMemoryArtifactStore(), interval_seconds=0)
    assert zero.start() is False and zero._thread is None


def test_the_background_thread_picks_up_a_build_published_while_it_runs(tmp_path):
    store = InMemoryArtifactStore()
    first = _publish(store, tmp_path, "pass-one")
    assert licensed_startup_sync(_env(tmp_path), store=store).reason_code == "synchronized"
    resync = LicensedResync(_env(tmp_path), store=store, interval_seconds=0.05)
    assert resync.start() is True and resync.start() is False          # one thread only
    try:
        _publish(store, tmp_path, "pass-two", element=502, previous=first)
        deadline = time.time() + 10
        while time.time() < deadline and _handle(tmp_path).build_id() != "pass-two":
            time.sleep(0.05)
        assert _handle(tmp_path).build_id() == "pass-two"
    finally:
        resync.stop()
    assert resync._thread is None


def test_the_interval_has_a_default_a_floor_and_an_off_switch():
    assert resync_interval({}) == DEFAULT_RESYNC_SECONDS == 600.0
    assert resync_interval({"FPL_FOOTBALL_LICENSED_RESYNC_SECONDS": "5"}) == MIN_RESYNC_SECONDS
    assert resync_interval({"FPL_FOOTBALL_LICENSED_RESYNC_SECONDS": "900"}) == 900
    assert resync_interval({"FPL_FOOTBALL_LICENSED_RESYNC_SECONDS": "0"}) == 0
    assert resync_interval({"FPL_FOOTBALL_LICENSED_RESYNC_SECONDS": "soon"}) == DEFAULT_RESYNC_SECONDS


def test_old_builds_are_pruned_but_never_the_one_in_use(tmp_path):
    store = InMemoryArtifactStore()
    previous = None
    resync = LicensedResync(_env(tmp_path), store=store, interval_seconds=1)
    for n in range(1, 7):
        previous = _publish(store, tmp_path, f"pass-{n}", element=500 + n, previous=previous)
        resync.run_once()
        time.sleep(0.02)
    names = sorted(p.name for p in (tmp_path / "cache" / "builds").iterdir())
    assert len(names) == KEEP_BUILDS and "pass-6" in names
    assert _handle(tmp_path).build_id() == "pass-6"
    assert prune_old_builds(tmp_path / "nowhere") == 0


def test_the_status_and_the_log_line_carry_no_content(tmp_path, caplog):
    import logging
    store = InMemoryArtifactStore()
    _publish(store, tmp_path, "pass-one")
    resync = LicensedResync(_env(tmp_path), store=store, interval_seconds=1)
    with caplog.at_level(logging.INFO):
        resync.run_once()
        resync.run_once()                                              # unchanged: no second line
    lines = [r.getMessage() for r in caplog.records if "licensed resync" in r.getMessage()]
    assert lines == ["football licensed resync: state=ready reason=synchronized"]
