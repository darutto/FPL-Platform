"""Build families in distribution (B3 PR 2a): one shared publish/sync path, per-family build shape.

The canonical family is the default and its behaviour is pinned by test_distribution.py, unchanged. Here a
toy second family proves the seam: it round-trips, trial data is refused for it in the shared path, and
its prefix and the canonical one cannot reach each other.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_intelligence.distribution.errors import RemoteValidationError
from football_intelligence.distribution.family import CANONICAL_V1, BuildFamily, FamilyPrefixError
from football_intelligence.distribution.keys import manifest_key, pointer_key
from football_intelligence.distribution.service import publish_build, sync_build
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.ingestion.builder import build_from_fixture
from football_intelligence.provenance import LIVE_TRIAL_LOCAL, LiveTrialProvenanceRefused

FIXTURE = Path(__file__).parent / "fixtures" / "sportmonks_replay_v1.json"
TOY_PREFIX = "football-licensed"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _toy_validate(build: Path) -> dict:
    """Schema only: file paths and hashes are checked by the shared path (artifact_key, expected_hash)."""
    manifest = json.loads((build / "manifest.json").read_text())
    if manifest.get("schema_version") != 7:
        raise RemoteValidationError("toy manifest version")
    return manifest


TOY = BuildFamily(
    name="toy", manifest_schema_version=7, pointer_name="_toy_latest.json", validate=_toy_validate,
    artifact_paths=lambda m: tuple(sorted(m["files"])), expected_hash=lambda m, rel: m["files"][rel],
    governed_path=lambda rel: rel.startswith("data/") and rel.endswith(".json") and rel.count("/") == 1,
    prefix_segment="football-licensed",
)


def _toy_build(root: Path, build_id="toy-one", **manifest_extra) -> Path:
    build = root / build_id
    (build / "data").mkdir(parents=True)
    payload = b'{"rows": 3}\n'
    (build / "data" / "a.json").write_bytes(payload)
    manifest = {"schema_version": 7, "build_id": build_id, "files": {"data/a.json": _sha(payload)}, **manifest_extra}
    (build / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    return build


def test_a_second_family_round_trips_through_publish_and_sync(tmp_path):
    store = InMemoryArtifactStore()
    report = publish_build(store, TOY_PREFIX, _toy_build(tmp_path / "author"), family=TOY)
    assert report.build_id == "toy-one"
    assert pointer_key(TOY_PREFIX, TOY.pointer_name) in store.objects
    cache = tmp_path / "cache"
    synced = sync_build(store, TOY_PREFIX, cache, family=TOY)
    assert synced.changed and synced.files_transferred == 1
    assert (cache / "builds/toy-one/data/a.json").read_bytes() == b'{"rows": 3}\n'
    assert (cache / "_toy_latest.json").exists() and not (cache / "_football_latest.json").exists()
    assert not sync_build(store, TOY_PREFIX, cache, family=TOY).changed


def test_a_family_only_publishes_its_governed_paths(tmp_path):
    """The shared path asks the family which paths are governed; an ungoverned one never reaches the store."""
    build = _toy_build(tmp_path)
    manifest = json.loads((build / "manifest.json").read_text())
    manifest["files"]["../escape.json"] = manifest["files"]["data/a.json"]
    (build / "manifest.json").write_text(json.dumps(manifest))
    store = InMemoryArtifactStore()
    with pytest.raises(ValueError, match="not governed"):
        publish_build(store, TOY_PREFIX, build, family=TOY)
    assert store.objects == {}


def test_a_changed_artifact_is_refused_by_the_shared_hash_check(tmp_path):
    build = _toy_build(tmp_path)
    (build / "data" / "a.json").write_bytes(b'{"rows": 4}\n')
    with pytest.raises(RemoteValidationError, match="hash"):
        publish_build(InMemoryArtifactStore(), TOY_PREFIX, build, family=TOY)


# ---------------------------------------------- trial refusal is shared, for every family

TRIAL_MARKERS = [
    {"assumption_status": LIVE_TRIAL_LOCAL},
    {"assumption_status": "licensed_starter", "assumption_status_summary": {LIVE_TRIAL_LOCAL: 1}},
    {"assumption_status": "licensed_starter", "normalizer_versions": {"live_trial_adapter": "live-trial-v1"}},
    {"assumption_status": "licensed_starter", "source": {"source_kind": "local-live-trial"}},
]


@pytest.mark.parametrize("marker", TRIAL_MARKERS)
def test_publication_refuses_trial_data_for_any_family(tmp_path, marker):
    store = InMemoryArtifactStore()
    with pytest.raises(LiveTrialProvenanceRefused, match="publish_build"):
        publish_build(store, TOY_PREFIX, _toy_build(tmp_path, **marker), family=TOY)
    assert store.objects == {}


@pytest.mark.parametrize("marker", TRIAL_MARKERS)
def test_synchronization_refuses_trial_data_for_any_family(tmp_path, marker):
    """Seed the remote directly (publication would refuse), then sync."""
    build = _toy_build(tmp_path / "author", **marker)
    store = InMemoryArtifactStore()
    store.put_immutable(f"{TOY_PREFIX}/builds/toy-one/data/a.json", (build / "data/a.json").read_bytes(),
                        _sha((build / "data/a.json").read_bytes()))
    manifest_bytes = (build / "manifest.json").read_bytes()
    store.put_immutable(manifest_key(TOY_PREFIX, "toy-one"), manifest_bytes, _sha(manifest_bytes))
    from football_intelligence.distribution.service import encode_pointer
    store.put_pointer(pointer_key(TOY_PREFIX, TOY.pointer_name),
                      encode_pointer("toy-one", _sha(manifest_bytes), "2026-01-01T00:00:00Z"), None)
    cache = tmp_path / "cache"
    with pytest.raises(LiveTrialProvenanceRefused, match="sync_build"):
        sync_build(store, TOY_PREFIX, cache, family=TOY)
    assert not (cache / "_toy_latest.json").exists() and not (cache / "builds").exists()


# ---------------------------------------------------------- prefixes keep families apart

@pytest.mark.parametrize("prefix", ["football", "prod/football", "football-licensed-x"])
def test_a_reserved_family_never_publishes_or_syncs_outside_its_prefix(tmp_path, prefix):
    store = InMemoryArtifactStore()
    with pytest.raises(FamilyPrefixError):
        publish_build(store, prefix, _toy_build(tmp_path), family=TOY)
    with pytest.raises(FamilyPrefixError):
        sync_build(store, prefix, tmp_path / "cache", family=TOY)
    assert store.objects == {}


@pytest.mark.parametrize("prefix", ["football-licensed", "prod/football-licensed"])
def test_the_canonical_family_never_publishes_or_syncs_under_a_reserved_prefix(tmp_path, prefix):
    store = InMemoryArtifactStore()
    build_from_fixture(FIXTURE, tmp_path, build_id="canon")
    with pytest.raises(FamilyPrefixError):
        publish_build(store, prefix, tmp_path / "builds/canon")
    with pytest.raises(FamilyPrefixError):
        sync_build(store, prefix, tmp_path / "cache")
    assert store.objects == {}


def test_both_families_in_one_store_do_not_share_a_single_key(tmp_path):
    store = InMemoryArtifactStore()
    build_from_fixture(FIXTURE, tmp_path, build_id="canon")
    publish_build(store, "football", tmp_path / "builds/canon")
    canonical_keys = set(store.objects)
    publish_build(store, TOY_PREFIX, _toy_build(tmp_path / "toy"), family=TOY)
    toy_keys = set(store.objects) - canonical_keys
    assert toy_keys and all(k.startswith(f"{TOY_PREFIX}/") for k in toy_keys)
    assert all(k.startswith("football/") for k in canonical_keys)
    # Each sync reads only its own family's pointer and builds.
    assert sync_build(store, "football", tmp_path / "c1").build_id == "canon"
    assert sync_build(store, TOY_PREFIX, tmp_path / "c2", family=TOY).build_id == "toy-one"


def test_a_family_can_only_own_a_reserved_segment():
    with pytest.raises(ValueError, match="reserved"):
        BuildFamily(name="x", manifest_schema_version=1, pointer_name="_x.json", validate=lambda p: {},
                    artifact_paths=lambda m: (), expected_hash=lambda m, r: "", governed_path=lambda r: False,
                    prefix_segment="football-anything")
    assert CANONICAL_V1.prefix_segment is None
