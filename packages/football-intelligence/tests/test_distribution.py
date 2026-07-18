from __future__ import annotations
import json
from pathlib import Path

import pytest

from football_intelligence.distribution.config import DownloadLimits, RemoteStoreConfig
from football_intelligence.distribution.errors import ArtifactSizeError, DistributionConfigError, ImmutableConflictError, PointerRaceError, RemoteValidationError
from football_intelligence.distribution.keys import artifact_key, manifest_key, pointer_key
from football_intelligence.distribution.runtime import RuntimeBuildHandle, startup_status
from football_intelligence.distribution.service import encode_pointer, parse_pointer, publish_build, read_bounded, sync_build
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.ingestion.builder import build_from_fixture, replay_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "sportmonks_replay_v1.json"


def built(tmp_path, build_id="portable"):
    build_from_fixture(FIXTURE, tmp_path, build_id=build_id)
    return tmp_path / "builds" / build_id


def test_portable_manifest_and_replay_hash(tmp_path):
    build = built(tmp_path / "one")
    manifest = json.loads((build / "manifest.json").read_text())
    assert "source_fixture" not in manifest
    assert not Path(manifest["source"]["source_relative_path"]).is_absolute()
    replay_manifest(build / "manifest.json", tmp_path / "two")
    manifest["source"]["source_content_hash"] = "0" * 64
    changed = tmp_path / "changed.json"; changed.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash mismatch"): replay_manifest(changed, tmp_path / "bad")


def test_old_manifest_fails_explicitly(tmp_path):
    old = tmp_path / "old.json"; old.write_text('{"schema_version":1}')
    with pytest.raises(ValueError, match="schema-v1"): replay_manifest(old, tmp_path / "out")


def test_config_disabled_validated_and_secret_safe():
    assert RemoteStoreConfig.from_env({}) is None
    secret = "do-not-leak"
    with pytest.raises(DistributionConfigError) as caught:
        RemoteStoreConfig.from_env({"FPL_FOOTBALL_REMOTE_ENDPOINT": "ftp://bad", "FPL_FOOTBALL_REMOTE_BUCKET": "b", "FPL_FOOTBALL_REMOTE_ACCESS_KEY_ID": "x", "FPL_FOOTBALL_REMOTE_SECRET_ACCESS_KEY": secret})
    assert secret not in str(caught.value)


@pytest.mark.parametrize("relative", ["../x", r"canonical\x.parquet", "/x", "canonical//x.parquet", "reports/other.json"])
def test_key_grammar_rejects_escape(relative):
    with pytest.raises(ValueError): artifact_key("football", "build-1", relative)


def test_key_layout_is_deterministic():
    assert pointer_key("football") == "football/_football_latest.json"
    assert manifest_key("football", "build-1") == "football/builds/build-1/manifest.json"
    assert artifact_key("football", "build-1", "canonical/teams.parquet") == "football/builds/build-1/canonical/teams.parquet"


def test_pointer_is_strict_and_versioned():
    pointer = parse_pointer(encode_pointer("build-1", "a" * 64, "2026-07-01T00:00:00Z"))
    assert pointer["build_id"] == "build-1"
    pointer["extra"] = True
    with pytest.raises(RemoteValidationError): parse_pointer(json.dumps(pointer).encode())


def test_publish_pointer_last_idempotent_and_conflict(tmp_path):
    store = InMemoryArtifactStore(); report = publish_build(store, "football", built(tmp_path), dry_run=False)
    assert store.operations[-1] == ("pointer", pointer_key("football"))
    assert report.files_uploaded > 1
    publish_build(store, "football", tmp_path / "builds/portable")
    first_key = next(k for k in store.objects if "/canonical/" in k)
    store.objects[first_key] = b"conflict"
    with pytest.raises(ImmutableConflictError): publish_build(store, "football", tmp_path / "builds/portable")


def test_pointer_race_preserves_prior_pointer(tmp_path):
    store = InMemoryArtifactStore(); build = built(tmp_path)
    original = encode_pointer("old", "b" * 64); store.put_pointer(pointer_key("football"), original, None)
    store.fail_on.add(("pointer", pointer_key("football")))
    with pytest.raises(Exception): publish_build(store, "football", build)
    assert store.objects[pointer_key("football")] == original


def test_bounded_read_declared_and_streamed_size():
    store = InMemoryArtifactStore(); store.put_immutable("x", b"12345", __import__("hashlib").sha256(b"12345").hexdigest())
    assert read_bounded(store, "x", 5) == b"12345"
    with pytest.raises(ArtifactSizeError): read_bounded(store, "x", 4)
    store.declared_sizes["x"] = 1
    with pytest.raises(ArtifactSizeError): read_bounded(store, "x", 4)


def test_sync_initial_noop_upgrade_and_runtime_handle(tmp_path):
    author = tmp_path / "author"; cache = tmp_path / "cache"; store = InMemoryArtifactStore()
    publish_build(store, "football", built(author, "one")); first = sync_build(store, "football", cache)
    assert first.changed and RuntimeBuildHandle(cache).manifest()["build_id"] == "one"
    assert not sync_build(store, "football", cache).changed
    publish_build(store, "football", built(author, "two")); assert sync_build(store, "football", cache).build_id == "two"


def test_sync_hash_failure_retains_previous_active(tmp_path):
    author = tmp_path / "author"; cache = tmp_path / "cache"; store = InMemoryArtifactStore()
    publish_build(store, "football", built(author, "one")); sync_build(store, "football", cache)
    prior = (cache / "_football_latest.json").read_bytes()
    publish_build(store, "football", built(author, "two"))
    key = next(k for k in store.objects if "/builds/two/canonical/" in k); store.objects[key] = b"tampered"
    with pytest.raises(RemoteValidationError): sync_build(store, "football", cache)
    assert (cache / "_football_latest.json").read_bytes() == prior


def test_runtime_disabled_and_unavailable_are_fail_soft():
    assert startup_status({}).state == "disabled"
    status = startup_status({"FPL_FOOTBALL_REMOTE_ENDPOINT":"https://example.invalid", "FPL_FOOTBALL_REMOTE_BUCKET":"bucket-ok", "FPL_FOOTBALL_REMOTE_ACCESS_KEY_ID":"x", "FPL_FOOTBALL_REMOTE_SECRET_ACCESS_KEY":"y"})
    assert status.state == "unavailable"
