"""B2: the ``licensed_starter`` provenance of production Sportmonks builds.

The paid Starter plan allows storing, deriving and showing to subscribers, so a
licensed build passes every path that publishes, syncs or serves. Trial data
stays refused everywhere, including a trial build relabelled as licensed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from football_intelligence.distribution import service
from football_intelligence.distribution.keys import artifact_key, manifest_key, pointer_key
from football_intelligence.distribution.runtime import RuntimeBuildHandle
from football_intelligence.distribution.service import encode_pointer, publish_build, sync_build
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.features.registry_v2 import ROLE_MAPPING_VERSION_V3
from football_intelligence.features.store_v2 import build_features_v2, validate_feature_build_v2
from football_intelligence.ingestion.builder import build_from_fixture
from football_intelligence.ingestion.builder_v2 import build_context_v2, validate_context_build
from football_intelligence.provenance import (
    LICENSED_NORMALIZER, LICENSED_SOURCE_KIND, LICENSED_STARTER, LIVE_TRIAL_LOCAL, LiveTrialProvenanceRefused,
    is_live_trial, refuse_live_trial,
)
from test_features_v2 import sources

FIXTURE = Path(__file__).parent / "fixtures" / "sportmonks_replay_v1.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _licensed_context(tmp_path):
    base, _mock_context = sources(tmp_path)
    root = tmp_path / "licensed-context"
    build_context_v2(tmp_path / "context.json", root, build_id="licensed-context", built_at="2026-10-26T00:00:00Z",
                     provenance=LICENSED_STARTER)
    return base, root / "builds-v2/licensed-context"


def _v1_build(root, summary):
    build_from_fixture(FIXTURE, root, build_id="prod")
    path = root / "builds/prod/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["assumption_status_summary"] = summary
    path.write_text(json.dumps(manifest, sort_keys=True))
    return root / "builds/prod"


def _seed_remote(build, build_id):
    """Seed the remote store directly, so sync is tested on its own."""
    manifest_bytes = (build / "manifest.json").read_bytes()
    store = InMemoryArtifactStore()
    for relative in service._artifact_paths(json.loads(manifest_bytes)):
        data = (build / Path(*relative.split("/"))).read_bytes()
        store.put_immutable(artifact_key("football", build_id, relative), data, _sha(data))
    store.put_immutable(manifest_key("football", build_id), manifest_bytes, _sha(manifest_bytes))
    store.put_pointer(pointer_key("football"), encode_pointer(build_id, _sha(manifest_bytes), "2026-01-01T00:00:00Z"), None)
    return store


def _runtime_cache(tmp_path, build):
    cache = tmp_path / "cache"
    shutil.copytree(build.parent, cache / "builds")
    (cache / "_football_latest.json").write_text(json.dumps({
        "schema_version": 1, "build_id": "prod", "manifest_hash": "0" * 64,
        "published_at": "2026-01-01T00:00:00Z", "publisher_version": "fi4b-v1"}))
    return cache


# ------------------------------------------------------------- the binding

def test_a_licensed_context_is_stamped_and_validates(tmp_path):
    _base, context = _licensed_context(tmp_path)
    manifest = validate_context_build(context)
    assert manifest["assumption_status"] == LICENSED_STARTER
    assert manifest["normalizer_versions"] == {"licensed_adapter": LICENSED_NORMALIZER}
    assert manifest["source"]["source_kind"] == LICENSED_SOURCE_KIND
    assert not is_live_trial(manifest)


@pytest.mark.parametrize("field,value", [
    ("normalizer_versions", {"live_trial_adapter": "live-trial-v1"}),
    ("normalizer_versions", {"mock_adapter": "fi5ba-v1"}),
    ("source_kind", "local-live-trial"),
    ("source_kind", "checked-in-fixture"),
])
def test_a_licensed_status_with_another_binding_is_refused(tmp_path, field, value):
    _base, context = _licensed_context(tmp_path)
    manifest = json.loads((context / "manifest.json").read_text())
    if field == "source_kind":
        manifest["source"]["source_kind"] = value
    else:
        manifest[field] = value
    (context / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="binding"):
        validate_context_build(context)


def test_a_licensed_feature_build_carries_its_provenance(tmp_path):
    base, context = _licensed_context(tmp_path)
    root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="licensed-features", built_at="2026-10-27T00:00:00Z",
                      role_map_version=ROLE_MAPPING_VERSION_V3, assumption_status=LICENSED_STARTER)
    manifest = validate_feature_build_v2(root / "builds-v2/licensed-features", base, context)
    assert manifest["assumption_status"] == LICENSED_STARTER and not is_live_trial(manifest)


# ------------------------------------------------- accepted by the prod paths

def test_publication_accepts_a_licensed_build(tmp_path):
    store = InMemoryArtifactStore()
    report = publish_build(store, "football", _v1_build(tmp_path, {LICENSED_STARTER: 1}))
    assert report.build_id == "prod" and report.files_uploaded > 0


def test_synchronization_accepts_a_licensed_build(tmp_path):
    store = _seed_remote(_v1_build(tmp_path / "author", {LICENSED_STARTER: 1}), "prod")
    cache = tmp_path / "cache"
    assert sync_build(store, "football", cache).build_id == "prod"
    assert (cache / "_football_latest.json").exists()


def test_the_serving_runtime_handle_accepts_a_licensed_build(tmp_path):
    cache = _runtime_cache(tmp_path, _v1_build(tmp_path / "author", {LICENSED_STARTER: 1}))
    assert RuntimeBuildHandle(cache).manifest()["build_id"] == "prod"


# ------------------------------------------- trial data stays refused, everywhere

TRIAL_MARKERS = [
    {"assumption_status_summary": {LIVE_TRIAL_LOCAL: 1}},
    {"assumption_status_summary": {LICENSED_STARTER: 1, LIVE_TRIAL_LOCAL: 1}},
    {"assumption_status_summary": {LICENSED_STARTER: 1}, "source_kind": "local-live-trial"},
]


@pytest.mark.parametrize("marker", TRIAL_MARKERS)
def test_publication_refuses_trial_data_even_when_labelled_licensed(tmp_path, marker):
    build = _v1_build(tmp_path, marker["assumption_status_summary"])
    if "source_kind" in marker:
        path = build / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["source"]["source_kind"] = marker["source_kind"]
        path.write_text(json.dumps(manifest, sort_keys=True))
    store = InMemoryArtifactStore()
    with pytest.raises(LiveTrialProvenanceRefused, match="publish_build"):
        publish_build(store, "football", build)
    assert store.objects == {}


def test_synchronization_still_refuses_trial_data(tmp_path):
    store = _seed_remote(_v1_build(tmp_path / "author", {LIVE_TRIAL_LOCAL: 1}), "prod")
    with pytest.raises(LiveTrialProvenanceRefused, match="sync_build"):
        sync_build(store, "football", tmp_path / "cache")


def test_the_serving_runtime_handle_still_refuses_trial_data(tmp_path):
    cache = _runtime_cache(tmp_path, _v1_build(tmp_path / "author", {LIVE_TRIAL_LOCAL: 1}))
    with pytest.raises(LiveTrialProvenanceRefused, match="RuntimeBuildHandle"):
        RuntimeBuildHandle(cache).manifest()


def test_a_relabelled_trial_manifest_is_still_recognized():
    assert is_live_trial({"assumption_status": LICENSED_STARTER, "normalizer_versions": {"live_trial_adapter": "live-trial-v1"}})
    assert is_live_trial({"assumption_status": LICENSED_STARTER, "source": {"source_kind": "local-live-trial"}})
    refuse_live_trial({"assumption_status": LICENSED_STARTER, "normalizer_versions": {"licensed_adapter": LICENSED_NORMALIZER},
                       "source": {"source_kind": LICENSED_SOURCE_KIND}}, "x")
