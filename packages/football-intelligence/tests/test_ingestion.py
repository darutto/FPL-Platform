from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from football_data_contract import canonical_fixture_id
from football_intelligence.ingestion.authority import select_player_authority
from football_intelligence.ingestion.builder import (DEFAULT_TEAM_SEED, build_from_fixture,
    replay_manifest, validate_active)
from football_intelligence.ingestion.keys import validate_edition_key, validate_fixture_key
from football_intelligence.ingestion.normalizers import NormalizationError, normalize_fixture
from football_intelligence.ingestion.schemas import SCHEMAS
from football_intelligence.ingestion.team_registry import (TeamCrosswalk, TeamRegistry,
    TeamSeed, load_team_registry)

FIXTURE = Path(__file__).parent / "fixtures" / "sportmonks_replay_v1.json"
GOLDEN = Path(__file__).parent / "golden" / "canonical_summary_v1.json"


def test_team_seed_is_valid_sorted_and_resolves_exact_aliases():
    registry = load_team_registry(DEFAULT_TEAM_SEED)
    assert [row.registry_key for row in registry.teams] == sorted(row.registry_key for row in registry.teams)
    assert registry.resolve("sportmonks", "1", "2026-01-01") == "team_40aacfa0c00a94eb11e47626"
    assert registry.resolve("sportmonks", "Arsenal", "2026-01-01") is None
    assert all("mock-only" in row.provenance for row in registry.crosswalks if row.provider == "sportmonks")


def test_duplicate_or_overlapping_team_mapping_fails():
    registry = load_team_registry(DEFAULT_TEAM_SEED); team = registry.teams[0]
    rows = (TeamCrosswalk("sportmonks", "x", team.canonical_team_id, "2025-01-01", None, "mock"),
            TeamCrosswalk("sportmonks", "x", team.canonical_team_id, "2026-01-01", None, "mock"))
    with pytest.raises(ValueError, match="overlapping"):
        TeamRegistry((team,), rows)


@pytest.mark.parametrize("valid", ["2025-2026", "2026", "special-centenary"])
def test_season_key_valid(valid): assert validate_edition_key(valid) == valid


@pytest.mark.parametrize("invalid", ["2025-2027", "25-26", "", "2025/26"])
def test_season_key_invalid(invalid):
    with pytest.raises(ValueError): validate_edition_key(invalid)


@pytest.mark.parametrize("valid", ["league-home-meeting-1", "league-away-meeting-2", "cup-semi-final-leg-1", "cup-third-round-replay-2", "cup-final-single", "replacement-1", "neutral-community-shield"])
def test_fixture_key_valid(valid): assert validate_fixture_key(valid) == valid


def test_fixture_identity_semantics_ignore_kickoff_and_provider_id():
    result = normalize_fixture(FIXTURE, load_team_registry(DEFAULT_TEAM_SEED), "build")
    fixture = result.tables["fixtures"][0]
    same = canonical_fixture_id(fixture["competition_id"], fixture["season_id"], fixture["home_team_id"], fixture["away_team_id"], fixture["fixture_key"])
    reverse = canonical_fixture_id(fixture["competition_id"], fixture["season_id"], fixture["away_team_id"], fixture["home_team_id"], fixture["fixture_key"])
    other_meeting = canonical_fixture_id(fixture["competition_id"], fixture["season_id"], fixture["home_team_id"], fixture["away_team_id"], "league-home-meeting-2")
    assert same == fixture["fixture_id"]
    assert len({same, reverse, other_meeting}) == 3


def test_player_authority_precedence_and_conflict():
    current = {"full_name": "Current", "birth_date": "2000-01-01"}
    historical = {"full_name": "Historical", "birth_date": "2000-01-01"}
    assert select_player_authority(current, None, None) == current
    assert select_player_authority(None, historical, None) == historical
    existing = {"canonical_player_id": "player_existing"}
    assert select_player_authority(current, None, existing) == existing
    with pytest.raises(ValueError, match="conflict"): select_player_authority(current, historical, None)


def test_normalizers_cover_every_family_and_quarantine_unmatched_player():
    result = normalize_fixture(FIXTURE, load_team_registry(DEFAULT_TEAM_SEED), "build")
    assert set(result.tables) == set(SCHEMAS)
    assert all(result.tables[name] for name in SCHEMAS)
    assert result.quarantine == ({"reason": "unmatched_player", "family": "players", "provider_ref": "sportmonks/999"},)
    assert result.assumption_status == "unverified_against_live"
    assert all("sportmonks_id" not in column and "league_id" not in column for schema in SCHEMAS.values() for column, _, _ in schema)


def test_malformed_snapshot_fails_typed(tmp_path):
    malformed = tmp_path / "malformed.json"; malformed.write_text('{"_fixture": {}}')
    with pytest.raises(NormalizationError, match="missing required families"):
        normalize_fixture(malformed, load_team_registry(DEFAULT_TEAM_SEED), "build")


def test_unknown_enum_warns_and_unknown_field_is_ignored(tmp_path):
    payload = json.loads(FIXTURE.read_text()); payload["fixtures"][0]["status"] = "provider-new"
    payload["fixtures"][0]["unexpected_provider_field"] = "ignored"
    changed = tmp_path / "unknown.json"; changed.write_text(json.dumps(payload))
    result = normalize_fixture(changed, load_team_registry(DEFAULT_TEAM_SEED), "build")
    assert result.tables["fixtures"][0]["status"] == "unknown"
    assert result.warnings[0]["reason"] == "unknown_provider_fixture_status"
    assert "unexpected_provider_field" not in result.tables["fixtures"][0]


def test_ambiguous_player_crosswalk_is_quarantined(tmp_path):
    payload = json.loads(FIXTURE.read_text())
    payload["player_crosswalks"].append({"sportmonks_id": "101", "fpl_id": "102"})
    changed = tmp_path / "ambiguous.json"; changed.write_text(json.dumps(payload))
    result = normalize_fixture(changed, load_team_registry(DEFAULT_TEAM_SEED), "build")
    assert any(row["reason"] == "ambiguous_player" for row in result.quarantine)
    assert all(row["source_provider_id"] != "101" for row in result.tables["players"])


def test_build_validate_roundtrip_and_explicit_dtypes(tmp_path):
    manifest = build_from_fixture(FIXTURE, tmp_path, build_id="golden-build")
    assert manifest == validate_active(tmp_path)
    build = tmp_path / "builds" / "golden-build"
    for name, schema in SCHEMAS.items():
        frame = pd.read_parquet(build / "canonical" / f"{name}.parquet")
        assert tuple(frame.columns) == tuple(column for column, _, _ in schema)
        assert len(frame) == manifest["row_counts"][name]
    assert manifest["quarantine_counts"] == {"unmatched_player": 1, "total": 1}
    assert (build / "reports" / "build_report.json").is_file()


def test_canonical_output_matches_reviewable_golden(tmp_path):
    manifest = build_from_fixture(FIXTURE, tmp_path, build_id="golden", built_at="2026-07-01T00:00:00Z")
    expected = json.loads(GOLDEN.read_text())
    assert {key: manifest[key] for key in expected} == expected


def test_deterministic_two_build_replay(tmp_path):
    first = build_from_fixture(FIXTURE, tmp_path / "one", build_id="same", built_at="2026-07-01T00:00:00Z")
    second = build_from_fixture(FIXTURE, tmp_path / "two", build_id="same", built_at="2026-07-01T00:00:00Z")
    assert first["content_hashes"] == second["content_hashes"]
    assert first["parquet_byte_hashes"] == second["parquet_byte_hashes"]
    assert json.loads(((tmp_path / "one/builds/same/reports/quarantine.json").read_text())) == json.loads(((tmp_path / "two/builds/same/reports/quarantine.json").read_text()))


def test_replay_manifest_proves_semantic_equivalence(tmp_path):
    build_from_fixture(FIXTURE, tmp_path / "source", build_id="replay")
    original = tmp_path / "source/builds/replay/manifest.json"
    replay = replay_manifest(original, tmp_path / "replayed")
    assert replay["content_hashes"] == json.loads(original.read_text())["content_hashes"]


def test_failed_publication_preserves_previous_active_build(tmp_path):
    build_from_fixture(FIXTURE, tmp_path, build_id="good")
    pointer = (tmp_path / "_football_latest.json").read_bytes()
    with pytest.raises(RuntimeError, match="seeded publication failure"):
        build_from_fixture(FIXTURE, tmp_path, build_id="bad", fail_after_write=True)
    assert (tmp_path / "_football_latest.json").read_bytes() == pointer
    assert not (tmp_path / "builds/bad").exists()


def test_runtime_and_canonical_contract_are_not_contaminated():
    root = Path(__file__).resolve().parents[2]
    canonical = root.parent / "football-data-contract" / "football_data_contract"
    canonical_source = "\n".join(path.read_text().casefold() for path in canonical.glob("*.py"))
    assert "import sportmonks_client" not in canonical_source and "from sportmonks_client" not in canonical_source
    runtime = root.parent / "fpl-grounded-assistant" / "fpl_grounded_assistant"
    assert "football_intelligence.ingestion" not in "\n".join(path.read_text(errors="ignore") for path in runtime.glob("*.py"))
    source = "\n".join(path.read_text() for path in (root / "football_intelligence/ingestion").glob("*.py"))
    assert "requests" not in source and "SPORTMONKS_API_TOKEN" not in source
