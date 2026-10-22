"""B3 step 2b: the licensed matchday build and its distribution family. Synthetic data only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from football_intelligence.distribution.family import CANONICAL_V1, FamilyPrefixError
from football_intelligence.distribution.keys import manifest_key, pointer_key
from football_intelligence.distribution.service import encode_pointer, publish_build, sync_build
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.ingestion.licensed.derive import DeriveReport, DerivedTables
from football_intelligence.ingestion.licensed.store import (
    LICENSED_V1, POINTER_NAME, REPORT_PATH, TABLES, LicensedStoreError, validate_build, write_build,
)
from football_intelligence.provenance import LiveTrialProvenanceRefused
from football_intelligence.public_calendar import convert_matches, SourceMatch

PREFIX = "football-licensed"


def _tables(observed="2026-10-24T12:00:00Z", confirmed=False, element=501):
    cup = convert_matches([SourceMatch("EFL", "Arsenal", "Invented Town", "2026-10-29T19:45:00Z", home_code="ARS",
                                       away_code="IVT")], competition="EFL", season="2026-27",
                          source="sportmonks-starter", fetched_at=observed)
    return DerivedTables(
        lineup_snapshots=({"fixture_id": 301, "team": "ARS", "observed_at": observed, "state": "scheduled",
                           "confirmed": confirmed, "formation": "4-3-3", "n_starters": 11, "n_bench": 0},),
        lineup_slots=({"fixture_id": 301, "team": "ARS", "observed_at": observed, "element": element, "starter": True,
                       "detailed_position": "Right Back", "grid_slot": "2:1", "side": "right"},),
        sidelined=({"element": 502, "team": "ARS", "category": "injury", "start_date": "2026-10-01", "end_date": None,
                    "games_missed": 2, "completed": False, "observed_at": observed},),
        squad_membership=({"team": "ARS", "element": element, "jersey_number": 2, "observed_at": observed},),
        cup_snapshots=(cup,), report=DeriveReport(fixtures_seen=1, rows={"lineup_slots": 1}),
    )


def _build(root, build_id="pass-one", **kw):
    return write_build(_tables(**kw), {700001: 501}, root, build_id=build_id, built_at="2026-10-24T12:01:00Z")


def test_a_build_is_stamped_licensed_and_validates(tmp_path):
    manifest = validate_build(_build(tmp_path))
    assert manifest["assumption_status"] == "licensed_starter"
    assert manifest["normalizer_versions"] == {"licensed_adapter": "licensed-starter-v1"}
    assert manifest["source"] == {"source_kind": "licensed-sportmonks-starter"}
    assert set(manifest["files"]) == {REPORT_PATH, *(f"datasets/{n}.parquet" for n in TABLES)}
    assert manifest["row_counts"]["cup_records"] == 1 and manifest["row_counts"]["crosswalk"] == 1


def test_history_tables_accumulate_and_state_tables_are_replaced(tmp_path):
    first = _build(tmp_path, "pass-one")
    second = write_build(_tables(observed="2026-10-24T13:00:00Z", confirmed=True), {700002: 502}, tmp_path,
                         build_id="pass-two", built_at="2026-10-24T13:01:00Z", previous=first)
    snapshots = pd.read_parquet(second / "datasets/lineup_snapshots.parquet")
    assert list(snapshots.confirmed) == [False, True]          # predicted, then confirmed: both kept
    assert list(pd.read_parquet(second / "datasets/crosswalk.parquet").sportmonks_player_id) == [700002]
    again = write_build(_tables(observed="2026-10-24T13:00:00Z", confirmed=True), {700002: 502}, tmp_path,
                        build_id="pass-three", built_at="2026-10-24T13:02:00Z", previous=second)
    assert len(pd.read_parquet(again / "datasets/lineup_snapshots.parquet")) == 2   # same observation: no duplicate


def test_a_build_id_is_immutable(tmp_path):
    _build(tmp_path)
    with pytest.raises(FileExistsError):
        _build(tmp_path)


@pytest.mark.parametrize("change", [
    lambda m: m.update(assumption_status="mock_validated"),
    lambda m: m.update(normalizer_versions={"live_trial_adapter": "live-trial-v1"}),
    lambda m: m.update(source={"source_kind": "local-live-trial"}),
    lambda m: m.update(build_family="canonical-v1"),
    lambda m: m["files"].pop(REPORT_PATH),
    lambda m: m.update(extra=1),
])
def test_the_validator_refuses_any_other_shape_or_binding(tmp_path, change):
    build = _build(tmp_path)
    manifest = json.loads((build / "manifest.json").read_text())
    change(manifest)
    (build / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(LicensedStoreError):
        validate_build(build)


def test_a_tampered_table_is_refused(tmp_path):
    build = _build(tmp_path)
    (build / "datasets/sidelined.parquet").write_bytes(b"not parquet")
    with pytest.raises(LicensedStoreError, match="hash"):
        validate_build(build)


# ------------------------------------------------------------ distribution family

def test_the_family_has_its_own_pointer_and_governs_only_its_files():
    assert LICENSED_V1.pointer_name == POINTER_NAME != CANONICAL_V1.pointer_name
    licensed = [REPORT_PATH, *(f"datasets/{n}.parquet" for n in TABLES)]
    canonical = ["canonical/fixtures.parquet", "reports/build_report.json", "reports/quarantine.json"]
    assert all(LICENSED_V1.governed_path(p) for p in licensed)
    assert not any(LICENSED_V1.governed_path(p) for p in canonical)
    assert not any(CANONICAL_V1.governed_path(p) for p in licensed)
    assert not LICENSED_V1.governed_path("datasets/raw_payload.json")


def test_a_licensed_build_round_trips_through_publish_and_sync(tmp_path):
    store = InMemoryArtifactStore()
    publish_build(store, PREFIX, _build(tmp_path / "author"), family=LICENSED_V1)
    assert pointer_key(PREFIX, POINTER_NAME) in store.objects
    assert all(key.startswith(f"{PREFIX}/") for key in store.objects)
    cache = tmp_path / "cache"
    assert sync_build(store, PREFIX, cache, family=LICENSED_V1).build_id == "pass-one"
    validate_build(cache / "builds/pass-one")


def test_the_licensed_family_cannot_use_the_canonical_prefix_and_vice_versa(tmp_path):
    with pytest.raises(FamilyPrefixError):
        publish_build(InMemoryArtifactStore(), "football", _build(tmp_path), family=LICENSED_V1)
    with pytest.raises(FamilyPrefixError):
        sync_build(InMemoryArtifactStore(), PREFIX, tmp_path / "cache")  # canonical default under the licensed prefix


def test_a_relabelled_trial_manifest_is_refused_at_publish_and_sync(tmp_path):
    """The shared refusal runs before the licensed validator, whatever the manifest claims."""
    build = _build(tmp_path / "author")
    manifest = json.loads((build / "manifest.json").read_text())
    manifest["source"] = {"source_kind": "local-live-trial"}
    data = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (build / "manifest.json").write_bytes(data)
    with pytest.raises(LiveTrialProvenanceRefused, match="publish_build"):
        publish_build(InMemoryArtifactStore(), PREFIX, build, family=LICENSED_V1)
    store = InMemoryArtifactStore()
    store.put_immutable(manifest_key(PREFIX, "pass-one"), data, hashlib.sha256(data).hexdigest())
    store.put_pointer(pointer_key(PREFIX, POINTER_NAME),
                      encode_pointer("pass-one", hashlib.sha256(data).hexdigest(), "2026-01-01T00:00:00Z"), None)
    with pytest.raises(LiveTrialProvenanceRefused, match="sync_build"):
        sync_build(store, PREFIX, tmp_path / "cache", family=LICENSED_V1)
