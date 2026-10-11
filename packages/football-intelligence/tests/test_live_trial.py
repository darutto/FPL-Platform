"""FI-9 live-trial additions: role-map-v3 and the live_trial_local provenance with its refusals.

The role map and the provenance vocabulary are the two places the live Sportmonks
reads do not fit the FI-4/FI-5 mock-era contracts. Both are explicit, versioned
and fixed here; neither rewrites v2 behavior.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from football_intelligence.distribution import service
from football_intelligence.distribution.keys import artifact_key, manifest_key, pointer_key
from football_intelligence.distribution.runtime import RuntimeBuildHandle
from football_intelligence.distribution.service import encode_pointer, publish_build, sync_build
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.features.engine_v2 import (
    FeatureV2InputError, ROLE_MAP, ROLE_MAP_V2, ROLE_MAP_V3, ROLE_MAPS, compute_features_v2,
)
from football_intelligence.features.registry_v2 import (
    ROLE_MAPPING_VERSION, ROLE_MAPPING_VERSION_V3, ROLE_MAPPING_VERSIONS, ROLE_VOCABULARY,
)
from football_intelligence.features.store_v2 import (
    FeatureV2ValidationError, build_features_v2, validate_feature_build_v2,
)
from football_intelligence.ingestion.builder import build_from_fixture
from football_intelligence.ingestion.builder_v2 import build_context_v2, validate_context_build
from football_intelligence.provenance import (
    ASSUMPTION_STATUSES, LIVE_TRIAL_LOCAL, LiveTrialProvenanceRefused, is_live_trial, refuse_live_trial,
)
from test_features_v2 import sources

FIXTURE = Path(__file__).parent / "fixtures" / "sportmonks_replay_v1.json"

#: The nine detailed positions the live lineups carry (FI-9 day 1), lower-cased as the engine keys them.
LIVE_POSITIONS = {
    "goalkeeper": ("goalkeeper", "center", "goalkeeper"),
    "centre back": ("center_back", "center", "defense"),
    "right back": ("full_back", "right", "defense"),
    "left back": ("full_back", "left", "defense"),
    "central midfield": ("central_midfield", "center", "midfield"),
    "attacking midfield": ("attacking_midfield", "center", "midfield"),
    "right midfield": ("winger", "right", "attack"),
    "left midfield": ("winger", "left", "attack"),
    "attacker": ("forward", "center", "attack"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- role-map-v3

def test_every_live_position_has_the_decided_role_in_v3():
    assert {k: ROLE_MAP_V3[k] for k in LIVE_POSITIONS} == LIVE_POSITIONS


def test_v2_is_unchanged_and_does_not_know_the_live_spellings():
    assert ROLE_MAP is ROLE_MAP_V2 and ROLE_MAPS[ROLE_MAPPING_VERSION] is ROLE_MAP_V2
    for name in ("centre back", "attacker", "left midfield", "right midfield", "attacking midfield"):
        assert name not in ROLE_MAP_V2
    assert set(ROLE_MAP_V2) == {"goalkeeper", "central defender", "left back", "right back", "left wing",
                                "right wing", "central midfield", "centre forward"}


def test_v3_keeps_every_v2_entry_and_adds_only_the_five_live_spellings():
    assert all(ROLE_MAP_V3[k] == v for k, v in ROLE_MAP_V2.items())
    assert set(ROLE_MAP_V3) - set(ROLE_MAP_V2) == {"centre back", "left midfield", "right midfield",
                                                   "attacking midfield", "attacker"}


def test_attacking_midfield_is_a_governed_role_and_both_versions_are_listed():
    assert "attacking_midfield" in ROLE_VOCABULARY
    assert ROLE_MAPPING_VERSIONS == ("role-map-v2", "role-map-v3") and ROLE_MAPPING_VERSION_V3 == "role-map-v3"
    assert {role for role, _, _ in ROLE_MAP_V3.values()} <= ROLE_VOCABULARY


def _live_positions(base, payload):
    live = ["Centre Back", "Attacking Midfield", "Left Midfield", "Right Midfield", "Attacker", "Right Back"]
    base["lineups"]["detailed_position"] = live
    base["lineups"]["started"] = True


def test_v3_maps_live_spellings_that_v2_leaves_unmapped(tmp_path):
    base, context = sources(tmp_path, _live_positions)
    v2, _ = compute_features_v2(base, context)
    v3, _ = compute_features_v2(base, context, role_map_version=ROLE_MAPPING_VERSION_V3)
    key = "fixture_id == 'target' and window_segment == 'last_10'"
    assert v2["player_role_window_summary"].query(key).iloc[0].mapped_starts == 1  # only "right back" is a v2 key
    summary = v3["player_role_window_summary"].query(key).iloc[0]
    assert (summary.mapped_starts, summary.unmapped_starts) == (6, 0)
    assert set(v3["player_role_window_summary"].role_mapping_version) == {ROLE_MAPPING_VERSION_V3}
    assert {"center_back", "attacking_midfield", "winger", "forward", "full_back"} <= set(v3["player_role_distribution"].role)
    assert "attacking_midfield" not in set(v2["player_role_distribution"].role)


def test_an_unknown_role_map_version_is_refused(tmp_path):
    base, context = sources(tmp_path)
    with pytest.raises(FeatureV2InputError, match="role map version"):
        compute_features_v2(base, context, role_map_version="role-map-v9")


# ------------------------------------------------------------ provenance vocabulary

def _live_context(tmp_path):
    base, _mock_context = sources(tmp_path)
    live_root = tmp_path / "live-context"
    build_context_v2(tmp_path / "context.json", live_root, build_id="live-context", built_at="2026-07-30T00:00:00Z",
                     provenance=LIVE_TRIAL_LOCAL)
    return base, live_root / "builds-v2/live-context"


def test_a_live_trial_context_is_stamped_and_validates(tmp_path):
    _base, context = _live_context(tmp_path)
    manifest = validate_context_build(context)
    assert manifest["assumption_status"] == LIVE_TRIAL_LOCAL
    assert manifest["normalizer_versions"] == {"live_trial_adapter": "live-trial-v1"}
    assert manifest["source"]["source_kind"] == "local-live-trial"
    assert is_live_trial(manifest)


def test_a_mock_context_is_still_the_mock_contract(tmp_path):
    _base, context = sources(tmp_path)
    manifest = validate_context_build(context)
    assert manifest["assumption_status"] == "mock_validated" and not is_live_trial(manifest)
    assert manifest["normalizer_versions"] == {"mock_adapter": "fi5ba-v1"}


def test_the_status_and_the_normalizer_must_agree(tmp_path):
    _base, context = _live_context(tmp_path)
    manifest = json.loads((context / "manifest.json").read_text())
    manifest["normalizer_versions"] = {"mock_adapter": "fi5ba-v1"}
    (context / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="binding"):
        validate_context_build(context)


def test_an_unknown_provenance_is_refused_when_building(tmp_path):
    sources(tmp_path)
    with pytest.raises(ValueError, match="provenance"):
        build_context_v2(tmp_path / "context.json", tmp_path / "x", build_id="x", provenance="live")


def test_a_live_feature_build_carries_its_provenance_and_the_v3_map(tmp_path):
    base, context = _live_context(tmp_path)
    root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="live-features", built_at="2026-07-31T00:00:00Z",
                      role_map_version=ROLE_MAPPING_VERSION_V3, assumption_status=LIVE_TRIAL_LOCAL)
    build = root / "builds-v2/live-features"
    manifest = validate_feature_build_v2(build, base, context)
    assert manifest["assumption_status"] == LIVE_TRIAL_LOCAL and is_live_trial(manifest)
    frame = pd.read_parquet(build / "datasets/player_role_window_summary.parquet")
    assert set(frame.role_mapping_version) == {ROLE_MAPPING_VERSION_V3}
    assert set(frame.assumption_status) == {LIVE_TRIAL_LOCAL}


def test_a_feature_build_with_an_unknown_assumption_status_is_refused(tmp_path):
    base, context = sources(tmp_path)
    with pytest.raises(FeatureV2ValidationError, match="assumption"):
        build_features_v2(base, context, tmp_path / "f", feature_build_id="f", built_at="2026-07-31T00:00:00Z",
                          assumption_status="live")


def test_the_vocabulary_is_closed():
    assert ASSUMPTION_STATUSES == {"mock_validated", "live_trial_local"}


# -------------------------------------------------------------- refusals (one per path)

def _live_v1_build(root):
    """A canonical v1 build whose provenance summary says live_trial_local."""
    build_from_fixture(FIXTURE, root, build_id="live")
    path = root / "builds/live/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["assumption_status_summary"] = {LIVE_TRIAL_LOCAL: 1}
    path.write_text(json.dumps(manifest, sort_keys=True))
    return root / "builds/live"


def test_publication_refuses_a_live_trial_build_before_uploading_anything(tmp_path):
    store = InMemoryArtifactStore()
    with pytest.raises(LiveTrialProvenanceRefused, match="publish_build"):
        publish_build(store, "football", _live_v1_build(tmp_path))
    assert store.objects == {} and store.operations == []


def test_a_dry_run_publication_refuses_too(tmp_path):
    with pytest.raises(LiveTrialProvenanceRefused):
        publish_build(InMemoryArtifactStore(), "football", _live_v1_build(tmp_path), dry_run=True)


def test_synchronization_refuses_a_remote_build_that_is_live_trial(tmp_path):
    """Seed the remote store directly (publication itself would refuse), then sync."""
    build = _live_v1_build(tmp_path / "author")
    manifest_bytes = (build / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    store = InMemoryArtifactStore()
    for relative in service._artifact_paths(manifest):
        data = (build / Path(*relative.split("/"))).read_bytes()
        store.put_immutable(artifact_key("football", "live", relative), data, _sha(data))
    store.put_immutable(manifest_key("football", "live"), manifest_bytes, _sha(manifest_bytes))
    store.put_pointer(pointer_key("football"), encode_pointer("live", _sha(manifest_bytes), "2026-01-01T00:00:00Z"), None)
    cache = tmp_path / "cache"
    with pytest.raises(LiveTrialProvenanceRefused, match="sync_build"):
        sync_build(store, "football", cache)
    assert not (cache / "_football_latest.json").exists() and not (cache / "builds").exists()


def test_the_serving_runtime_handle_refuses_a_live_trial_build(tmp_path):
    cache = tmp_path / "cache"
    shutil.copytree(_live_v1_build(tmp_path / "author").parent, cache / "builds")
    (cache / "_football_latest.json").write_text(json.dumps({
        "schema_version": 1, "build_id": "live", "manifest_hash": "0" * 64,
        "published_at": "2026-01-01T00:00:00Z", "publisher_version": "fi4b-v1"}))
    with pytest.raises(LiveTrialProvenanceRefused, match="RuntimeBuildHandle"):
        RuntimeBuildHandle(cache).manifest()
    assert RuntimeBuildHandle(cache, allow_live_trial_local=True).manifest()["build_id"] == "live"


def test_a_mock_manifest_is_never_refused():
    refuse_live_trial({"assumption_status": "mock_validated", "normalizer_versions": {"mock_adapter": "fi5ba-v1"}}, "x")
    refuse_live_trial({"assumption_status_summary": {"unverified_against_live": 1}}, "x")


def test_every_manifest_shape_that_declares_live_trial_is_recognized():
    assert is_live_trial({"assumption_status": LIVE_TRIAL_LOCAL})
    assert is_live_trial({"assumption_status_summary": {LIVE_TRIAL_LOCAL: 3}})
    assert is_live_trial({"normalizer_versions": {"live_trial_adapter": "live-trial-v1"}})
    assert not is_live_trial({})
