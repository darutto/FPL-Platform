from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from football_identity_registry.builder import build
from football_identity_registry import canonical_ids
from football_identity_registry.canonical_ids import CanonicalIdCollisionError, IdentityIndistinguishableError, canonical_player_id
from football_identity_registry.matcher import MATCH_TIERS, match_player
from football_identity_registry.models import CandidatePlayer, SourcePlayer
from football_identity_registry.normalization import normalize_name
from football_identity_registry.overrides import OverrideSchemaError, load_overrides
from football_identity_registry.store import IdentityStore, PlayerIdentityRow, _atomic_json, reconcile_player_rows, verify_player_rows


def candidate(identifier="p1", name="José O'Neil", team="A", dob="2000-01-02", known="Jose"):
    return CandidatePlayer(identifier, name, team, dob, known)


@pytest.mark.parametrize(("raw", "expected"), [
    ("  JOSÉ  O'Neil ", "jose o neil"), ("Ødegaard", "odegaard"), ("Straße", "strasse"),
])
def test_normalization(raw, expected):
    assert normalize_name(raw) == expected


def test_models_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        SourcePlayer("x", "1", "A").full_name = "B"


def test_tiers_are_closed_and_ordered():
    assert MATCH_TIERS == (("manual_override", 1.0), ("full_name_birth_date", .99), ("full_name_team", .95), ("full_name_unique", .9), ("known_name_team", .85), ("surname_birth_date", .8))


def test_manual_override_wins():
    source = SourcePlayer("understat", "u1", "Different")
    result = match_player(source, [candidate()], {("understat", "u1"): "p1"})
    assert (result.canonical_player_id, result.match_method, result.match_confidence) == ("p1", "manual_override", 1)


@pytest.mark.parametrize(("source", "expected"), [
    (SourcePlayer("x", "1", "Jose O Neil", "Z", "2000-01-02"), "full_name_birth_date"),
    (SourcePlayer("x", "1", "Jose O Neil", "A"), "full_name_team"),
    (SourcePlayer("x", "1", "Jose O Neil"), "full_name_unique"),
    (SourcePlayer("x", "1", "Unrelated", "A", known_name="Jose"), "known_name_team"),
    (SourcePlayer("x", "1", "M. O'Neil", "Z", "2000-01-02"), "surname_birth_date"),
])
def test_each_automatic_tier(source, expected):
    assert match_player(source, [candidate()]).match_method == expected


def test_ambiguity_never_guesses_and_is_sorted():
    source = SourcePlayer("x", "1", "Same Name")
    result = match_player(source, [candidate("z", "Same Name"), candidate("a", "Same Name")])
    assert not result.matched and result.reason == "ambiguous"
    assert [c.canonical_player_id for c in result.candidates] == ["a", "z"]


def test_below_threshold_queues():
    result = match_player(SourcePlayer("x", "1", "Same Name"), [candidate(name="Same Name")], threshold=.95)
    assert not result.matched and result.reason == "below_threshold"


def test_no_fuzzy_matching():
    assert match_player(SourcePlayer("x", "1", "Jsoe O Neil"), [candidate()]).reason == "no_candidate"


def test_id_is_stable_and_provider_free():
    value = canonical_player_id("José O'Neil", "2000-01-02")
    assert value == canonical_player_id("Jose O Neil", "2000-01-02")
    assert "understat" not in value and "123" not in value


def test_canonical_id_collision_stops_build(monkeypatch):
    class Digest:
        def hexdigest(self):
            return "0" * 64
    monkeypatch.setattr(canonical_ids.hashlib, "sha256", lambda value: Digest())
    with pytest.raises(CanonicalIdCollisionError):
        canonical_ids.assert_no_id_collisions([("One Player", None), ("Other Player", None)])


def _build_payload(candidates, sources=None):
    return {"candidates": candidates, "sources": sources or []}


@pytest.mark.parametrize("reverse", [False, True])
def test_distinct_no_dob_same_name_fails_closed_independent_of_order(tmp_path, reverse):
    candidates = [
        {"full_name": "John Smith", "team_provider_id": "TEAM_A", "known_name": "John"},
        {"full_name": "John Smith", "team_provider_id": "TEAM_B", "known_name": "J. Smith"},
    ]
    if reverse:
        candidates.reverse()
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_build_payload(candidates)), encoding="utf-8")
    overrides = tmp_path / "overrides.yaml"
    overrides.write_text("version: 1\noverrides: []\n", encoding="utf-8")
    with pytest.raises(IdentityIndistinguishableError, match="distinct candidates"):
        build(input_path, IdentityStore(tmp_path / "store"), overrides, valid_from="2025-08-01", run_id="r", generated_at="2025-08-01T00:00:00Z")
    assert not (tmp_path / "store" / "player_identity.parquet").exists()


def test_identical_duplicate_candidate_rows_do_not_false_collide(tmp_path):
    candidate_row = {"full_name": "John Smith", "team_provider_id": "TEAM_A", "known_name": "John"}
    source = dataclasses.asdict(SourcePlayer("understat", "u1", "John Smith", "TEAM_A"))
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_build_payload([candidate_row, candidate_row], [source])), encoding="utf-8")
    overrides = tmp_path / "overrides.yaml"
    overrides.write_text("version: 1\noverrides: []\n", encoding="utf-8")
    store = IdentityStore(tmp_path / "store")
    assert build(input_path, store, overrides, valid_from="2025-08-01", run_id="r", generated_at="2025-08-01T00:00:00Z")["matched"] == 1
    assert len(store.read_players()) == 1


def test_same_name_distinct_dobs_have_distinct_stable_ids():
    first = canonical_player_id("John Smith", "1990-01-01")
    second = canonical_player_id("John Smith", "1991-01-01")
    assert first != second
    assert first == canonical_player_id("John Smith", "1990-01-01")


def test_manual_override_cannot_bypass_indistinguishable_candidates(tmp_path):
    candidates = [
        {"full_name": "John Smith", "team_provider_id": "TEAM_A"},
        {"full_name": "John Smith", "team_provider_id": "TEAM_B"},
    ]
    source = dataclasses.asdict(SourcePlayer("understat", "u1", "John Smith", "TEAM_A"))
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_build_payload(candidates, [source])), encoding="utf-8")
    overrides = tmp_path / "overrides.yaml"
    overrides.write_text(f"version: 1\noverrides:\n  - provider: understat\n    provider_id: u1\n    canonical_player_id: {canonical_player_id('John Smith', None)}\n    reason: reviewed\n", encoding="utf-8")
    with pytest.raises(IdentityIndistinguishableError):
        build(input_path, IdentityStore(tmp_path / "store"), overrides, valid_from="2025-08-01", run_id="r", generated_at="2025-08-01T00:00:00Z")


def test_manual_override_cannot_bypass_active_mapping_uniqueness():
    first = dataclasses.replace(row(), match_method="manual_override", match_confidence=1.0, manual_override=True)
    second = dataclasses.replace(first, team_provider_id="TEAM_B")
    assert verify_player_rows([first, second]) == ["conflicting active mapping: understat/u1"]


def row(team="A", start="2025-08-01", end=None):
    return PlayerIdentityRow("p1", "understat", "u1", "jose", "Jose", team, None, start, end, "full_name_team", .95, False)


def test_transfer_closes_old_row_and_preserves_history():
    rows = reconcile_player_rows([row()], [row("B", "2026-08-01")])
    assert [(r.team_provider_id, r.valid_from, r.valid_to) for r in rows] == [("A", "2025-08-01", "2026-07-31"), ("B", "2026-08-01", None)]


def test_reconcile_is_idempotent():
    assert reconcile_player_rows([row()], [row()]) == [row()]


def test_override_schema(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("version: 1\noverrides:\n  - provider: x\n", encoding="utf-8")
    with pytest.raises(OverrideSchemaError):
        load_overrides(path)


def test_build_store_queue_verify_and_idempotency(tmp_path):
    input_path = tmp_path / "input.json"
    candidate_input = dataclasses.asdict(candidate())
    candidate_input.pop("canonical_player_id")
    input_path.write_text(json.dumps({"candidates": [candidate_input], "sources": [dataclasses.asdict(SourcePlayer("understat", "u1", "Jose O Neil", "A")), dataclasses.asdict(SourcePlayer("understat", "u2", "Nobody"))]}), encoding="utf-8")
    overrides = tmp_path / "overrides.yaml"
    overrides.write_text("version: 1\noverrides: []\n", encoding="utf-8")
    store = IdentityStore(tmp_path / "store")
    kwargs = dict(valid_from="2025-08-01", run_id="run-1", generated_at="2026-01-01T00:00:00Z")
    assert build(input_path, store, overrides, **kwargs) == {"matched": 1, "unresolved": 1, "total": 2}
    first = store.read_players()
    assert first[0].canonical_player_id == canonical_player_id("José O'Neil", "2000-01-02")
    build(input_path, store, overrides, **kwargs)
    assert store.read_players() == first
    assert store.verify() == []
    queue = json.loads((store.root / "ambiguity_queue.json").read_text())
    assert queue["items"][0]["reason"] == "no_candidate"
    assert json.loads((store.root / "_identity_latest.json").read_text())["run_id"] == "run-1"


def test_all_crosswalk_files_written(tmp_path):
    store = IdentityStore(tmp_path)
    store.write([], run_id="r", generated_at="2026-01-01T00:00:00Z", queue=[])
    assert {p.name for p in tmp_path.glob("*.parquet")} == {"player_identity.parquet", "team_identity.parquet", "fixture_identity.parquet", "competition_identity.parquet"}


def test_atomic_json_replace_failure_preserves_published_file(tmp_path, monkeypatch):
    path = tmp_path / "pointer.json"
    path.write_text('{"old": true}\n', encoding="utf-8")
    monkeypatch.setattr("football_identity_registry.store.os.replace", lambda source, destination: (_ for _ in ()).throw(OSError("seeded failure")))
    with pytest.raises(OSError, match="seeded failure"):
        _atomic_json(path, {"old": False})
    assert json.loads(path.read_text()) == {"old": True}
