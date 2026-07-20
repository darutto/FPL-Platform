from __future__ import annotations

import copy
import hashlib
import json
import socket
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import football_intelligence.features.engine_v2 as engine_v2
from football_intelligence.features.engine_v2 import FeatureV2InputError, compute_features_v2
from football_intelligence.features.registry_v2 import (
    CUTOFF_POLICY_VERSION, ENGINE_VERSION, FEATURE_REGISTRY_VERSION, FEATURE_SPECS_V2,
    registry_hash_v2, validate_registry_v2,
)
from football_intelligence.features.store import validate_feature_build
from football_intelligence.features.store_v2 import (
    FeatureV2ValidationError, build_features_v2, replay_feature_build_v2,
    validate_active_features_v2, validate_feature_build_v2, _resolve,
)
from football_intelligence.ingestion.builder_v2 import build_context_v2


class FakeHandle:
    def __init__(self, root): self.cache_root = root
    def manifest(self): return json.loads((self.cache_root / "builds/base/manifest.json").read_text())
    def dataset_path(self, name): return self.cache_root / f"builds/base/canonical/{name}.parquet"


def _row(fixture_id, kickoff, home="team_a", away="team_b", status="completed"):
    return {"fixture_id": fixture_id, "season_id": "season_1", "competition_id": "comp_1",
        "home_team_id": home, "away_team_id": away, "kickoff_utc": kickoff, "status": status}


def sources(tmp_path, mutate=None):
    kickoffs = [f"2026-07-{day:02d}T15:00:00Z" for day in (1, 4, 7, 10, 13, 16)]
    base_rows = [_row(f"past_{index}", kickoff) for index, kickoff in enumerate(kickoffs, 1)]
    base_rows += [_row("same_time", "2026-08-01T15:00:00Z"),
        _row("same_time_scheduled", "2026-08-01T15:00:00Z", status="scheduled"),
        _row("target", "2026-08-01T15:00:00Z", status="scheduled"),
        _row("leading", "2026-08-08T15:00:00Z", status="scheduled"),
        _row("third_team", "2026-07-20T15:00:00Z", "team_c", "team_d")]
    lineups = []
    roles = ["central midfield", "left wing", "central midfield", "unknown", "right wing", "central midfield"]
    starts = [True, False, True, True, False, True]
    minutes = [90, 20, 80, 75, 15, 90]
    for index, role in enumerate(roles, 1):
        lineups.append({"fixture_id": f"past_{index}", "team_id": "team_a", "player_id": "player_1",
            "started": starts[index-1], "minutes": minutes[index-1], "formation": "4-3-3", "grid_slot": "2:2", "detailed_position": role})
    base = {"fixtures": pd.DataFrame(base_rows),
        "squads": pd.DataFrame([{"team_id":"team_a","player_id":"player_1","valid_from":"2026-01-01T00:00:00Z","valid_to":None}]),
        "lineups": pd.DataFrame(lineups)}
    trace = {"source_provider":"mock", "source_timestamp":"2026-01-01T00:00:00Z", "assumption_status":"mock_validated"}
    fixtures = [{"fixture_id": row["fixture_id"], "competition_id":"comp_1", "season_id":"season_1",
        "home_team_id":row["home_team_id"], "away_team_id":row["away_team_id"], "competition_stage":"league", **trace} for row in base_rows]
    schedules = [{"fixture_id":row["fixture_id"], "observed_at_utc":"2026-01-01T00:00:00Z",
        "scheduled_kickoff_utc":row["kickoff_utc"], "status":row["status"], "competition_tier":"league", **trace} for row in base_rows]
    memberships = [{"competition_id":"comp_1","season_id":"season_1","team_id":team,
        "effective_from_utc":"2026-01-01T00:00:00Z","effective_to_utc":None,**trace} for team in ("team_a","team_b","team_c","team_d")]
    standings = []
    for position, team in enumerate(("team_a","team_b","team_c","team_d"), 1):
        standings.append({"competition_id":"comp_1","season_id":"season_1","as_of_utc":"2026-07-25T00:00:00Z",
            "team_id":team,"observed_position":position,"played":10,"wins":5,"draws":3,"losses":2,
            "goals_for":20-position,"goals_against":10,"goal_difference":10-position,
            "points_before_deduction":18-position,"points_deduction":0,**trace})
    payload = {"version":"fi5bb-test-v1","captured_at":"2026-07-30T00:00:00Z","canonical":{
        "competitions":[{"competition_id":"comp_1",**trace}],
        "seasons":[{"season_id":"season_1","competition_id":"comp_1",**trace}],
        "teams":[{"team_id":team,**trace} for team in ("team_a","team_b","team_c","team_d")],
        "fixtures":fixtures,"competition_memberships":memberships,"fixture_schedule_snapshots":schedules,
        "team_standing_snapshots":standings}}
    if mutate: mutate(base, payload)
    base_root = tmp_path / "base"; canonical = base_root / "builds/base/canonical"; canonical.mkdir(parents=True)
    for name, frame in base.items(): frame.to_parquet(canonical / f"{name}.parquet", index=False)
    manifest = {"build_id":"base"}; (canonical.parent / "manifest.json").write_text(json.dumps(manifest) + "\n")
    source = tmp_path / "context.json"; source.write_text(json.dumps(payload, sort_keys=True) + "\n")
    context_root = tmp_path / "context"; build_context_v2(source, context_root, build_id="context", built_at="2026-07-30T00:00:00Z")
    return FakeHandle(base_root), context_root / "builds-v2/context"


def target(frames, name): return frames[name].query("fixture_id == 'target'").reset_index(drop=True)


def test_registry_and_versions_are_closed_and_do_not_contain_intelligence_outputs():
    assert (FEATURE_REGISTRY_VERSION, ENGINE_VERSION, CUTOFF_POLICY_VERSION) == ("fi5-registry-v2", "fi5-engine-v2", "strictly-before-kickoff-v2")
    names = {spec.name for spec in FEATURE_SPECS_V2}
    assert "expected_minutes" not in names and "start_probability" not in names and len(names) == len(FEATURE_SPECS_V2) == 30
    assert registry_hash_v2() == registry_hash_v2(tuple(FEATURE_SPECS_V2)) and len(registry_hash_v2()) == 64


@pytest.mark.parametrize(("change", "message"), [
    ({"dtype":"object"}, "unsupported v2 feature contract"),
    ({"source_datasets":("undeclared.table",)}, "undeclared v2 feature dependency"),
    ({"cutoff":"latest"}, "unsupported v2 cutoff"),
    ({"vocabulary":()}, "uncontrolled v2 vocabulary"),
])
def test_registry_rejects_invalid_contracts_and_hash_changes_causally(change, message):
    index = 8 if "vocabulary" in change else 0
    changed = list(FEATURE_SPECS_V2); changed[index] = replace(changed[index], **change)
    with pytest.raises(ValueError, match=message): validate_registry_v2(tuple(changed))
    if "vocabulary" not in change:
        with pytest.raises(ValueError): registry_hash_v2(tuple(changed))


def test_registry_duplicate_output_and_order_are_pinned():
    with pytest.raises(ValueError, match="duplicate v2 feature name"): validate_registry_v2((FEATURE_SPECS_V2[0], FEATURE_SPECS_V2[0]))
    reversed_specs = tuple(reversed(FEATURE_SPECS_V2))
    assert registry_hash_v2(reversed_specs) != registry_hash_v2()


def test_m1_exact_window_weights_nonappearance_and_conditional_minutes(tmp_path):
    base, context = sources(tmp_path); frames, _ = compute_features_v2(base, context); row = target(frames, "player_fixture_module_inputs").iloc[0]
    assert row.eligible_team_fixtures_last_6 == 6
    assert row.weighted_start_numerator_last_6 == 14.0 and row.weighted_start_denominator_last_6 == 21.0
    assert row.weighted_start_share_last_6 == pytest.approx(14/21)
    assert (row.starts_last_6, row.appearances_last_6, row.cameo_appearances_last_6) == (4, 6, 2)
    assert row.mean_minutes_when_started_last_6 == pytest.approx(83.75)
    assert row.mean_minutes_when_cameo_last_6 == pytest.approx(17.5)
    assert "expected_minutes" not in frames["player_fixture_module_inputs"].columns


def test_m1_low_and_missing_history_are_explicit(tmp_path):
    base, context = sources(tmp_path); frames, _ = compute_features_v2(base, context)
    row = frames["player_fixture_module_inputs"].query("fixture_id == 'past_1'").iloc[0]
    assert row.eligible_team_fixtures_last_6 == 0 and row.weighted_start_denominator_last_6 == 0
    assert pd.isna(row.weighted_start_share_last_6) and pd.isna(row.recency_weight_version)
    assert row.starts_last_6 == row.appearances_last_6 == row.cameo_appearances_last_6 == 0


def test_m2_normalized_windows_include_unmapped_in_denominator_and_no_conclusion(tmp_path):
    base, context = sources(tmp_path); frames, _ = compute_features_v2(base, context)
    summary = target(frames, "player_role_window_summary"); distribution = target(frames, "player_role_distribution")
    last = summary.query("window_segment == 'last_10'").iloc[0]
    assert (last.eligible_starts, last.mapped_starts, last.unmapped_starts) == (4, 3, 1)
    assert distribution.query("window_segment == 'last_10'").role_share.sum() == pytest.approx(3/4)
    assert "role_changed" not in summary.columns and set(summary.window_segment) == {"last_10", "last_3", "prior_7"}
    counts = summary.set_index("window_segment").eligible_starts
    assert counts["last_3"] + counts["prior_7"] == counts["last_10"]


def test_m3_as_known_context_strict_boundaries_and_third_team_isolation(tmp_path):
    base, context = sources(tmp_path); frames, _ = compute_features_v2(base, context); row = target(frames, "team_fixture_context_v2").query("team_id == 'team_a'").iloc[0]
    assert row.trailing_fixtures_considered == 2  # only Jul 13/16 are in the 21-day window; same-time is excluded
    assert row.leading_fixtures_considered == 1 and row.next_rest_days == 7
    assert row.weighted_trailing_congestion_21d == 2.0  # unrelated third-team fixture excluded
    assert row.target_competition_stage == "league" and row.league_position_band == "top"
    assert row.schedule_context_as_of_utc == "2026-01-01T00:00:00Z" and row.standing_context_as_of_utc == "2026-07-25T00:00:00Z"


def test_scheduled_same_kickoff_is_excluded_from_strict_next_anchor_and_future_window(tmp_path):
    base, context = sources(tmp_path); frames, _ = compute_features_v2(base, context)
    row = target(frames, "team_fixture_context_v2").query("team_id == 'team_a'").iloc[0]
    assert row.next_rest_days == 7.0  # same_time_scheduled cannot become a zero-day next anchor
    assert row.leading_fixtures_considered == 1  # only the fixture seven days later is strictly future


def test_rest_uses_nearest_fixture_outside_congestion_windows(tmp_path):
    def mutate(base_data, payload):
        for row in base_data["fixtures"].to_dict("records"):
            if row["fixture_id"].startswith("past_"):
                base_data["fixtures"].loc[base_data["fixtures"].fixture_id == row["fixture_id"], "kickoff_utc"] = "2026-06-01T15:00:00Z"
        for row in payload["canonical"]["fixture_schedule_snapshots"]:
            if row["fixture_id"].startswith("past_"): row["scheduled_kickoff_utc"] = "2026-06-01T15:00:00Z"
            if row["fixture_id"] == "past_6": row["scheduled_kickoff_utc"] = "2026-07-03T15:00:00Z"
            if row["fixture_id"] == "leading": row["scheduled_kickoff_utc"] = "2026-08-30T15:00:00Z"
        base_data["fixtures"].loc[base_data["fixtures"].fixture_id == "past_6", "kickoff_utc"] = "2026-07-03T15:00:00Z"
        base_data["fixtures"].loc[base_data["fixtures"].fixture_id == "leading", "kickoff_utc"] = "2026-08-30T15:00:00Z"
    base, context = sources(tmp_path, mutate); frames, _ = compute_features_v2(base, context)
    row = target(frames, "team_fixture_context_v2").query("team_id == 'team_a'").iloc[0]
    assert row.previous_rest_days == 29.0 and row.trailing_fixtures_considered == 0
    assert row.next_rest_days == 29.0 and row.leading_fixtures_considered == 0


def test_rest_nulls_without_eligible_anchors_and_ignores_same_kickoff(tmp_path):
    def no_previous(base_data, payload):
        for row in payload["canonical"]["fixture_schedule_snapshots"]:
            if row["fixture_id"].startswith("past_"): row["status"] = "scheduled"
    base, context = sources(tmp_path / "previous", no_previous); frames, _ = compute_features_v2(base, context)
    row = target(frames, "team_fixture_context_v2").query("team_id == 'team_a'").iloc[0]
    assert pd.isna(row.previous_rest_days)  # same_time is exactly at cutoff and cannot anchor rest

    def no_next(base_data, payload):
        for row in payload["canonical"]["fixture_schedule_snapshots"]:
            if row["fixture_id"] == "leading": row["status"] = "cancelled"
    base, context = sources(tmp_path / "next", no_next); frames, _ = compute_features_v2(base, context)
    row = target(frames, "team_fixture_context_v2").query("team_id == 'team_a'").iloc[0]
    assert pd.isna(row.next_rest_days)
    assert row.previous_rest_days == 16.0  # same_time did not become a zero-day previous anchor


def test_same_kickoff_schedule_candidates_are_total_ordered_and_replay_stable(tmp_path, monkeypatch):
    def mutate(base_data, payload):
        trace = {"source_provider":"mock","source_timestamp":"2026-01-01T00:00:00Z","assumption_status":"mock_validated"}
        for fixture_id, kickoff, status in (("leading_2","2026-08-08T15:00:00Z","scheduled"), ("trailing_2","2026-07-16T15:00:00Z","completed")):
            payload["canonical"]["fixtures"].append({"fixture_id":fixture_id,"competition_id":"comp_1","season_id":"season_1","home_team_id":"team_a","away_team_id":"team_b","competition_stage":"league",**trace})
            payload["canonical"]["fixture_schedule_snapshots"].append({"fixture_id":fixture_id,"observed_at_utc":"2026-01-01T00:00:00Z","scheduled_kickoff_utc":kickoff,"status":status,"competition_tier":"league",**trace})
    base, context = sources(tmp_path / "source", mutate)
    first, _ = compute_features_v2(base, context)
    row = target(first, "team_fixture_context_v2").query("team_id == 'team_a'").iloc[0]
    assert row.leading_fixtures_considered == 2 and row.trailing_fixtures_considered == 3

    original_base, original_context = engine_v2._base_frames, engine_v2._context_frames
    monkeypatch.setattr(engine_v2, "_base_frames", lambda handle: {k:v.iloc[::-1].reset_index(drop=True) for k,v in original_base(handle).items()})
    monkeypatch.setattr(engine_v2, "_context_frames", lambda build: {k:v.iloc[::-1].reset_index(drop=True) for k,v in original_context(build).items()})
    reversed_frames, _ = compute_features_v2(base, context)
    for name in first: pd.testing.assert_frame_equal(first[name], reversed_frames[name])
    one = build_features_v2(base, context, tmp_path/"one", feature_build_id="stable", built_at="2026-08-01T00:00:00Z")
    two = build_features_v2(base, context, tmp_path/"two", feature_build_id="stable", built_at="2026-08-01T00:00:00Z")
    assert one["content_hashes"] == two["content_hashes"] and one["parquet_byte_hashes"] == two["parquet_byte_hashes"]


@pytest.mark.parametrize(("field", "value"), [("home_team_id","team_c"), ("competition_id","other_competition"), ("season_id","other_season")])
def test_cross_family_fixture_contradictions_fail_typed_before_output(tmp_path, field, value):
    def mutate(base_data, payload): base_data["fixtures"].loc[base_data["fixtures"].fixture_id == "target", field] = value
    base, context = sources(tmp_path, mutate)
    with pytest.raises(FeatureV2InputError) as caught: compute_features_v2(base, context)
    assert str(caught.value) == f"cross-source fixture contradiction: fixture_id=target; fields={field}"


def test_cross_family_matching_and_one_family_only_fixtures_preserve_behavior(tmp_path):
    base, context = sources(tmp_path / "matching"); expected, _ = compute_features_v2(base, context)
    def mutate(base_data, payload):
        base_data["fixtures"] = pd.concat([base_data["fixtures"], pd.DataFrame([_row("base_only", "2026-07-25T15:00:00Z")])], ignore_index=True)
    changed_base, changed_context = sources(tmp_path / "base-only", mutate); actual, _ = compute_features_v2(changed_base, changed_context)
    for name in expected: pd.testing.assert_frame_equal(expected[name], actual[name])


def test_cross_family_error_is_deterministic_under_row_reversal(tmp_path):
    def conflict(base_data, payload): base_data["fixtures"].loc[base_data["fixtures"].fixture_id == "target", "away_team_id"] = "team_c"
    base, context = sources(tmp_path / "one", conflict)
    with pytest.raises(FeatureV2InputError) as first: compute_features_v2(base, context)
    def reversed_conflict(base_data, payload):
        conflict(base_data, payload)
        for name in base_data: base_data[name] = base_data[name].iloc[::-1].reset_index(drop=True)
        for name in payload["canonical"]: payload["canonical"][name].reverse()
    other_base, other_context = sources(tmp_path / "two", reversed_conflict)
    with pytest.raises(FeatureV2InputError) as second: compute_features_v2(other_base, other_context)
    assert str(first.value) == str(second.value) == "cross-source fixture contradiction: fixture_id=target; fields=away_team_id"


def test_target_future_and_later_observation_mutations_do_not_leak(tmp_path):
    base, context = sources(tmp_path / "one"); before, _ = compute_features_v2(base, context)
    def mutate(base_data, payload):
        base_data["lineups"] = pd.concat([base_data["lineups"], pd.DataFrame([{"fixture_id":"target","team_id":"team_a","player_id":"player_1","started":True,"minutes":120,"formation":"x","grid_slot":"x","detailed_position":"centre forward"}])], ignore_index=True)
        payload["canonical"]["fixture_schedule_snapshots"].append({"fixture_id":"leading","observed_at_utc":"2026-08-02T00:00:00Z","scheduled_kickoff_utc":"2026-08-20T15:00:00Z","status":"scheduled","competition_tier":"continental","source_provider":"mock","source_timestamp":"2026-08-02T00:00:00Z","assumption_status":"mock_validated"})
        later = [copy.deepcopy(row) for row in payload["canonical"]["team_standing_snapshots"]]
        for row in later: row["as_of_utc"] = "2026-08-02T00:00:00Z"
        payload["canonical"]["team_standing_snapshots"].extend(later)
    changed_base, changed_context = sources(tmp_path / "two", mutate); after, _ = compute_features_v2(changed_base, changed_context)
    provenance = {"canonical_manifest_hash", "context_manifest_hash"}
    for name in before:
        left, right = target(before, name), target(after, name)
        columns = [column for column in left.columns if column not in provenance]
        pd.testing.assert_frame_equal(left[columns], right[columns])


def test_missing_standings_stays_unknown_and_is_not_backfilled(tmp_path):
    def mutate(base_data, payload): payload["canonical"]["team_standing_snapshots"] = []
    base, context = sources(tmp_path, mutate); frames, _ = compute_features_v2(base, context)
    assert set(target(frames, "team_fixture_context_v2").league_position_band) == {"unknown"}
    assert target(frames, "team_fixture_context_v2").standing_context_as_of_utc.isna().all()


def test_missing_schedule_is_distinct_from_empty_leading_window(tmp_path):
    base, context = sources(tmp_path / "complete"); complete, _ = compute_features_v2(base, context)
    def mutate(base_data, payload):
        payload["canonical"]["fixture_schedule_snapshots"] = [row for row in payload["canonical"]["fixture_schedule_snapshots"] if row["fixture_id"] != "target"]
    missing_base, missing_context = sources(tmp_path / "missing", mutate); missing, _ = compute_features_v2(missing_base, missing_context)
    assert target(complete, "team_fixture_context_v2").target_competition_tier.notna().all()
    assert target(missing, "team_fixture_context_v2").target_competition_tier.isna().all()
    assert set(target(missing, "team_fixture_context_v2").leading_fixtures_considered) == {1}


def test_reversed_source_rows_preserve_order_values_and_primary_keys(tmp_path):
    base, context = sources(tmp_path / "one"); first, _ = compute_features_v2(base, context)
    def mutate(base_data, payload):
        for name in base_data: base_data[name] = base_data[name].iloc[::-1].reset_index(drop=True)
        for name in payload["canonical"]: payload["canonical"][name].reverse()
    other_base, other_context = sources(tmp_path / "two", mutate); second, _ = compute_features_v2(other_base, other_context)
    for name in first:
        columns = [column for column in first[name].columns if column != "context_manifest_hash"]
        pd.testing.assert_frame_equal(first[name][columns], second[name][columns])
    assert not first["player_fixture_module_inputs"].duplicated(["fixture_id","team_id","player_id"]).any()
    assert not first["team_fixture_context_v2"].duplicated(["fixture_id","team_id"]).any()


def test_input_order_replay_source_binding_atomic_pointer_and_no_network(tmp_path, monkeypatch):
    base, context = sources(tmp_path / "source"); root = tmp_path / "features"
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    first = build_features_v2(base, context, root, feature_build_id="v2-one", built_at="2026-08-01T00:00:00Z")
    assert validate_active_features_v2(root, base, context) == first
    replay = replay_feature_build_v2(root / "builds-v2/v2-one", base, context, tmp_path / "replay")
    assert replay["content_hashes"] == first["content_hashes"] and replay["parquet_byte_hashes"] == first["parquet_byte_hashes"]
    pointer = (root / "_features_v2_latest.json").read_bytes()
    with pytest.raises(RuntimeError): build_features_v2(base, context, root, feature_build_id="v2-fail", built_at="2026-08-01T00:00:00Z", fail_before_pointer=True)
    assert (root / "_features_v2_latest.json").read_bytes() == pointer
    manifest = json.loads((root / "builds-v2/v2-one/manifest.json").read_text()); manifest["context_source"]["build_id"] = "other"
    (root / "builds-v2/v2-one/manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FeatureV2ValidationError, match="source binding"): validate_feature_build_v2(root / "builds-v2/v2-one", base, context)


def test_v1_and_v2_validators_reject_the_other_contract(tmp_path):
    base, context = sources(tmp_path / "source"); root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="v2", built_at="2026-08-01T00:00:00Z")
    with pytest.raises(Exception, match="unsupported feature manifest"): validate_feature_build(root / "builds-v2/v2")
    v1 = tmp_path / "v1"; v1.mkdir(); (v1 / "manifest.json").write_text(json.dumps({"schema_version":1}))
    with pytest.raises(FeatureV2ValidationError, match="unsupported feature manifest schema"): validate_feature_build_v2(v1)


@pytest.mark.parametrize(("field", "value"), [("feature_engine_version","fi5-engine-v1"), ("feature_registry_version","fi5-registry-v1"), ("cutoff_policy_version","strictly-before-kickoff-v1")])
def test_v2_rejects_every_unsupported_feature_contract_binding(tmp_path, field, value):
    base, context = sources(tmp_path / "source"); root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="v2", built_at="2026-08-01T00:00:00Z")
    path = root / "builds-v2/v2/manifest.json"; manifest = json.loads(path.read_text()); manifest[field] = value; path.write_text(json.dumps(manifest))
    with pytest.raises(FeatureV2ValidationError, match="unsupported feature contract version"): validate_feature_build_v2(path.parent)


def test_canonical_v1_path_cannot_substitute_for_context_v2(tmp_path):
    base, _ = sources(tmp_path / "source")
    with pytest.raises(Exception): compute_features_v2(base, base.cache_root / "builds/base")


def test_manifest_is_closed(tmp_path):
    base, context = sources(tmp_path / "source"); root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="v2", built_at="2026-08-01T00:00:00Z")
    path = root / "builds-v2/v2/manifest.json"; manifest = json.loads(path.read_text()); manifest["unexpected"] = True; path.write_text(json.dumps(manifest))
    with pytest.raises(FeatureV2ValidationError, match="manifest schema"): validate_feature_build_v2(path.parent)


def test_manifest_registry_hash_is_bound(tmp_path):
    base, context = sources(tmp_path / "source"); root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="v2", built_at="2026-08-01T00:00:00Z")
    path = root / "builds-v2/v2/manifest.json"; manifest = json.loads(path.read_text()); manifest["feature_registry_hash"] = "0" * 64; path.write_text(json.dumps(manifest))
    with pytest.raises(FeatureV2ValidationError, match="registry hash"): validate_feature_build_v2(path.parent)


@pytest.mark.parametrize("relative", ["../escape.parquet", "C:/escape.parquet", "datasets/../escape.parquet", "other.parquet"])
def test_v2_dataset_paths_fail_closed(tmp_path, relative):
    with pytest.raises(FeatureV2ValidationError, match="dataset path"): _resolve(tmp_path, "player_fixture_module_inputs", relative)


def test_duplicate_feature_key_is_rejected_before_content_acceptance(tmp_path):
    base, context = sources(tmp_path / "source"); root = tmp_path / "features"
    build_features_v2(base, context, root, feature_build_id="v2", built_at="2026-08-01T00:00:00Z")
    build = root / "builds-v2/v2"; dataset = build / "datasets/player_fixture_module_inputs.parquet"
    frame = pd.read_parquet(dataset); pd.concat([frame, frame.iloc[[0]]], ignore_index=True).to_parquet(dataset, index=False, compression="zstd")
    manifest = json.loads((build / "manifest.json").read_text()); manifest["parquet_byte_hashes"]["player_fixture_module_inputs"] = hashlib.sha256(dataset.read_bytes()).hexdigest()
    (build / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FeatureV2ValidationError, match="schema/key mismatch"): validate_feature_build_v2(build)
