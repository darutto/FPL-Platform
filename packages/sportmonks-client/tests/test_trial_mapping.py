"""FI-8 S6: identity mapping and provider-id stability.

The only slice whose output is itself a §14.1 gate, so the arithmetic is pinned
against a number that was published before this script existed
(`football-identity-registry/corpus/report.json`, 0.813449) rather than against
a hand-built pool alone. A rate instrument that agrees with a hand-built case
and disagrees with the registry would be wrong in exactly the way FI-9 could not
detect.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_mapping  # noqa: E402
from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, EXIT_UNMET, MODE_MOCK, OBSERVED,
    UNMET, make_client, response,
)
from football_identity_registry.models import CandidatePlayer, SourcePlayer  # noqa: E402
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import SportmonksRequestError  # noqa: E402

SCRIPT = trial_mapping.SCRIPT
#: Both objectives this script owns, in emitted order.
OBJECTIVE_IDS = (19, 18)

#: The rate the FI-2 corpus report publishes for the current-season corpus, and
#: the figure §14.1 quotes as the baseline this gate has to close.
PUBLISHED_FI2_RATE = 0.813449
PUBLISHED_FI2_MATCHED = 375
PUBLISHED_FI2_TOTAL = 461


def _collect(**overrides):
    transport = trial_mapping.mock_transport(**overrides)
    return trial_mapping.collect(make_client(MODE_MOCK, transport=transport), MODE_MOCK)[0]


def _shapes(report):
    return {shape.name: shape.shape for shape in report.observed_shapes}


def _statuses(report):
    return {objective.id: objective.status for objective in report.objectives}


def _evidence(report, objective_id):
    return next(o.evidence for o in report.objectives if o.id == objective_id)


def _record(provider_id, name, **fields):
    return {"id": provider_id, "name": name, **fields}


def _pool(*records):
    return {"data": list(records)}


# --- End to end ----------------------------------------------------------------

def test_a_mock_run_exits_zero_and_writes_both_artifacts(tmp_path):
    assert trial_mapping.main(["--out", str(tmp_path)]) == EXIT_OK
    assert sorted(p.name for p in (tmp_path / "reports").iterdir()) == [
        f"{SCRIPT}.json", f"{SCRIPT}.md", f"{SCRIPT}_unresolved_queue.json",
    ]


def test_mock_is_the_default_mode(tmp_path):
    trial_mapping.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert payload["mode"] == MODE_MOCK


def test_live_without_the_acknowledgement_refuses(tmp_path, capsys):
    assert trial_mapping.main(["--live", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("REFUSED:")


def test_a_mock_run_is_byte_stable_across_repeats(tmp_path):
    trial_mapping.main(["--out", str(tmp_path / "a")])
    trial_mapping.main(["--out", str(tmp_path / "b")])
    for name in (f"{SCRIPT}.json", f"{SCRIPT}.md", f"{SCRIPT}_unresolved_queue.json"):
        assert (tmp_path / "a" / "reports" / name).read_bytes() == \
               (tmp_path / "b" / "reports" / name).read_bytes()


def test_the_committed_example_matches_a_fresh_mock_run(tmp_path):
    from _trial_common import EXAMPLES_DIR
    trial_mapping.main(["--out", str(tmp_path)])
    for suffix in ("json", "md"):
        name = f"{SCRIPT}.{suffix}"
        assert (EXAMPLES_DIR / name).read_bytes() == \
               (tmp_path / "reports" / name).read_bytes()


def test_the_objective_titles_match_the_trial_dashboard():
    from _trial_common import PACKAGE_ROOT
    dashboard = (PACKAGE_ROOT / "TRIAL_STATUS.md").read_text(encoding="utf-8")
    rows = {
        int(cells[1]): cells[2].strip()
        for line in dashboard.splitlines()
        if (cells := line.split("|")) and len(cells) > 3 and cells[1].strip().isdigit()
    }
    assert rows[18] == trial_mapping.OBJECTIVE_18
    assert rows[19] == trial_mapping.OBJECTIVE_19


# --- DoD 5: the registry is read, never written ---------------------------------

def _registry_digest():
    """Hash of every file under the registry package, path included.

    Content alone would not notice a file being renamed or a new one appearing,
    and "the script wrote a new override file" is exactly the failure this
    guards against.
    """
    digest = hashlib.sha256()
    root = trial_mapping.REGISTRY_ROOT
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_a_run_leaves_the_identity_registry_byte_identical(tmp_path):
    """DoD 5. The registry is FI-2's output and FI-9's input; a trial script that
    edited it would make the ≥95% measurement a measurement of itself."""
    before = _registry_digest()
    trial_mapping.main(["--out", str(tmp_path)])
    assert _registry_digest() == before


def test_the_registry_digest_notices_a_change(tmp_path, monkeypatch):
    """The guard above is a comparison of two hashes, and a hash function that
    ignored its input would pass it forever. Measured on a real edit rather than
    assumed — and reverted, because the subject is the repository."""
    root = trial_mapping.REGISTRY_ROOT
    probe = root / "corpus" / "_digest_probe.tmp"
    before = _registry_digest()
    probe.write_text("x", encoding="utf-8")
    try:
        assert _registry_digest() != before
    finally:
        probe.unlink()
    assert _registry_digest() == before


def test_the_unresolved_queue_is_written_under_the_trial_output_not_the_registry(tmp_path):
    trial_mapping.main(["--out", str(tmp_path)])
    queue = tmp_path / "reports" / f"{SCRIPT}_unresolved_queue.json"
    payload = json.loads(queue.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert isinstance(payload["items"], list)
    assert not queue.is_relative_to(trial_mapping.REGISTRY_ROOT)


def test_the_queue_carries_the_unresolved_sources_in_the_registry_format():
    """Same item shape `football-identity-registry`'s store already writes, so an
    FI-9 queue is reviewable with the tooling that exists."""
    outcome = trial_mapping.map_pool(
        (SourcePlayer(provider="sportmonks", provider_id="1", full_name="Nobody Here"),),
        (CandidatePlayer("cp-1", "Someone Else"),),
        set(),
    )
    assert [item["reason"] for item in outcome.queue] == ["no_candidate"]
    assert outcome.queue[0]["source"]["provider_id"] == "1"


# --- DoD 2 and the published number ----------------------------------------------

def test_the_rate_arithmetic_is_pinned_on_a_known_answer():
    """DoD 2, verbatim: a hand-built pool with a known answer, 8/10 → exactly
    80.0. Asserted by `==` on the float, not by a range."""
    outcome = trial_mapping.MappingOutcome(10, 8, {}, {}, ())
    assert outcome.rate_percent == 80.0
    assert trial_mapping.MappingOutcome(10, 10, {}, {}, ()).rate_percent == 100.0
    assert trial_mapping.MappingOutcome(0, 0, {}, {}, ()).rate_percent == 0.0


def test_the_rate_reproduces_the_published_fi2_number():
    """The instrument measured against an answer published before it existed.

    `corpus/report.json` reports 375/461 = 0.813449 for the current-season
    corpus, and §14.1 quotes that figure as the gap this gate has to close. This
    script assembles its own candidate set — the registry's own assembly lives
    in a module that imports pandas, which this package's dependency allowlist
    excludes — so the mirroring is measured here rather than asserted in a
    comment. A candidate rule that drifted would land on a different number.
    """
    corpus = trial_mapping.load_corpus()
    candidates, conflicts = trial_mapping.registry_candidates(corpus)
    sources = tuple(SourcePlayer(**item) for item in corpus["sources"])
    outcome = trial_mapping.map_pool(sources, candidates, conflicts)

    published = json.loads(
        (trial_mapping.REGISTRY_ROOT / "corpus" / "report.json").read_text(encoding="utf-8")
    )["results"][trial_mapping.CORPUS_NAME]
    assert (outcome.matched, outcome.total) == (PUBLISHED_FI2_MATCHED, PUBLISHED_FI2_TOTAL)
    assert round(outcome.matched / outcome.total, 6) == PUBLISHED_FI2_RATE
    assert published["automatic_match_rate"] == PUBLISHED_FI2_RATE
    assert published["unresolved_reasons"] == outcome.reasons


def test_the_real_corpus_is_below_the_gate_and_would_exit_one(tmp_path, monkeypatch):
    """DoD 6: below-threshold is `unmet` and exits 1 — never rounded up, never
    waived. Driven with the real 81.3449% rather than a synthetic low number,
    because that is the value FI-9 starts from."""
    corpus = trial_mapping.load_corpus()
    pool = {"data": [
        {"id": 700000 + offset, "name": item["full_name"],
         "team": item.get("team_provider_id")}
        for offset, item in enumerate(corpus["sources"])
    ]}
    build = trial_mapping.mock_transport
    monkeypatch.setattr(trial_mapping, "mock_transport", lambda **_: build(players=pool))
    assert trial_mapping.main(["--out", str(tmp_path)]) == EXIT_UNMET
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    objective = next(o for o in payload["objectives"] if o["id"] == 19)
    assert objective["status"] == UNMET
    assert "81.3449% is below the 95.0% gate" in objective["evidence"]


def test_a_rate_that_only_reaches_the_gate_by_rounding_does_not_pass():
    """94.99996% rounds to 95.0 at six decimals. The gate is compared against the
    four-decimal value precisely so it cannot be reached by rounding."""
    just_under = trial_mapping.MappingOutcome(1000000, 949999, {}, {}, ())
    assert just_under.rate_percent == 94.9999
    assert not just_under.meets_gate
    assert trial_mapping.MappingOutcome(1000000, 950000, {}, {}, ()).meets_gate


# --- DoD 4: no new matching tier ---------------------------------------------------

def test_the_script_calls_the_registry_matcher_and_adds_no_tier():
    """§14.1 prohibits fuzzy matching, speculative aliases, and unsafe
    fall-through. The check is on what the tier table *is* at runtime, not on
    what the source says: a shadowed or extended table is the shape a new tier
    would actually take."""
    from football_identity_registry import matcher as registry_matcher
    from football_identity_registry.matcher import MATCH_TIERS
    assert trial_mapping.match_player is registry_matcher.match_player
    assert MATCH_TIERS == (
        ("manual_override", 1.00),
        ("full_name_birth_date", 0.99),
        ("full_name_team", 0.95),
        ("full_name_unique", 0.90),
        ("known_name_team", 0.85),
        ("surname_birth_date", 0.80),
    )
    assert not hasattr(trial_mapping, "MATCH_TIERS")


def test_an_unmatched_identity_is_queued_rather_than_guessed():
    """The failure mode the prohibition exists for: a near-miss name must land in
    the queue, never in the matched count."""
    report = _collect(players=_pool(_record(1, "Aaron Hicky", team="Brentford")))
    assert _statuses(report)[19] == UNMET
    assert "no_candidate" in _shapes(report)["unresolved_reasons"]


# --- Standing DoD item 12: failure paths asserted whole ------------------------

def test_live_without_a_token_exits_three_and_says_so_in_the_report(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_mapping.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "configuration incomplete; no request was issued")
        for objective_id in OBJECTIVE_IDS
    ]


def test_a_rejected_token_exits_three_and_says_something_different(tmp_path, monkeypatch):
    build = trial_mapping.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_mapping, "mock_transport", lambda **_: _with_401(build()))
    code = trial_mapping.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "authentication rejected by the provider")
        for objective_id in OBJECTIVE_IDS
    ]


def test_the_two_exit_three_reasons_are_not_interchangeable(tmp_path, monkeypatch):
    build = trial_mapping.mock_transport
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    trial_mapping.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "cfg")])
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_mapping, "mock_transport", lambda **_: _with_401(build()))
    trial_mapping.main(["--out", str(tmp_path / "auth")])

    def _reason(where):
        payload = json.loads(
            (tmp_path / where / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
        return payload["objectives"][0]["evidence"]

    assert _reason("cfg") == "configuration incomplete; no request was issued"
    assert _reason("auth") == "authentication rejected by the provider"
    assert _reason("cfg") != _reason("auth")


# --- Standing DoD item 13: the taxonomy -----------------------------------------

def _with_401(transport):
    transport._by_endpoint[ENDPOINTS["players"][0]] = [response({}, status=401)] * 2
    return transport


def test_a_rejected_token_is_never_reported_as_a_zero_match_rate(tmp_path, monkeypatch):
    """A 401 is a credential fact. Swallowed by a broad catch it becomes an empty
    provider pool, and an empty pool through this script is a 0% match rate —
    read on trial day 2 as "Sportmonks names do not map to ours", the exact
    question the ≥95% gate exists to answer."""
    build = trial_mapping.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_mapping, "mock_transport", lambda **_: _with_401(build()))
    code = trial_mapping.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert payload["observed_shapes"] == []
    assert "0.0%" not in json.dumps(payload)


def test_a_refusing_provider_is_reported_as_a_failure_not_as_emptiness():
    report = _collect(
        players=SportmonksRequestError("gone", endpoint="players", status_code=404))
    assert _statuses(report) == {18: UNMET, 19: UNMET}
    assert "players request failed: SportmonksRequestError" in _evidence(report, 19)


# --- The pool entry ----------------------------------------------------------------

def test_the_pool_entry_reports_the_fields_that_arrived():
    """Two pools carrying different keys, two different entries, asserted by
    `==` and by distinctness."""
    lean = _collect(players=_pool(_record(1, "Karl Hein")))
    rich = _collect(players=_pool(
        _record(1, "Karl Hein", date_of_birth="2002-04-13", team="Arsenal")))
    assert _shapes(lean)["provider_player_pool"] == "1 record(s); record{id,name}"
    assert _shapes(rich)["provider_player_pool"] == \
        "1 record(s); record{id,name,date_of_birth,team}"
    assert _shapes(lean)["provider_player_pool"] != _shapes(rich)["provider_player_pool"]


def test_an_empty_pool_drops_its_entry_and_leaves_both_objectives_unmet():
    report = _collect(players={"data": []})
    assert _shapes(report) == {}
    assert _statuses(report) == {18: UNMET, 19: UNMET}
    assert "no player record returned" in _evidence(report, 19)


# --- Tiers and reasons ---------------------------------------------------------------

def test_the_tier_entry_names_the_tiers_that_actually_fired():
    """Two pools that match through different tiers. The tier a rate rests on is
    the difference between a match on name-and-birth-date and one on a known
    name plus a team, and a report that only carried the rate would hide it."""
    by_birth_date = _collect(players=_pool(
        _record(1, "Karl Hein", date_of_birth="2002-04-13")))
    by_team = _collect(players=_pool(_record(1, "Karl Hein", team="Arsenal")))
    assert _shapes(by_birth_date)["match_tiers"] == "full_name_birth_date 1"
    assert _shapes(by_team)["match_tiers"] == "full_name_team 1"


def test_the_tier_entry_is_emitted_when_no_tier_fired():
    """Second branch of standing DoD item 10: the entry's existence is the
    observation. A 0% rate has no tier to name, and an entry that vanished would
    report the worst outcome by saying nothing."""
    report = _collect(players=_pool(_record(1, "Nobody At All")))
    assert _shapes(report)["match_tiers"] == "no tier fired"


def test_the_unresolved_entry_names_the_reasons_the_matcher_gave():
    """Two pools producing two different reasons, so the entry cannot be a
    literal naming the common one."""
    absent = _collect(players=_pool(_record(1, "Nobody At All")))
    assert _shapes(absent)["unresolved_reasons"] == "no_candidate 1"
    two = _collect(players=_pool(_record(1, "Nobody At All"), _record(2, "Also Nobody")))
    assert _shapes(two)["unresolved_reasons"] == "no_candidate 2"


def test_the_unresolved_entry_is_emitted_when_nothing_is_unresolved():
    """Second branch: an empty reason set is the gate's success condition, and
    the entry is how the report states it rather than implying it."""
    report = _collect(players=_pool(_record(1, "Karl Hein", team="Arsenal")))
    assert _shapes(report)["unresolved_reasons"] == "none unresolved"


# --- Objective 18: provider-id stability ---------------------------------------------

def test_a_changed_provider_id_is_named_and_makes_objective_eighteen_unmet():
    first = _pool(_record(1, "Karl Hein", team="Arsenal"))
    second = _pool(_record(2, "Karl Hein", team="Arsenal"))
    report = _collect(players=first, second_fetch=second)
    assert _shapes(report)["provider_id_stability"] == \
        "1 compared; 1 changed; 0 appeared; 0 disappeared"
    assert _statuses(report)[18] == UNMET
    assert "1 provider_id(s) changed between snapshots: karl hein" in _evidence(report, 18)


def test_the_stability_entry_is_emitted_when_nothing_changed():
    """Second branch: "no id changed" is objective 18's entire positive result."""
    report = _collect(players=_pool(_record(1, "Karl Hein", team="Arsenal")))
    assert _shapes(report)["provider_id_stability"] == \
        "1 compared; 0 changed; 0 appeared; 0 disappeared"
    assert _statuses(report)[18] == OBSERVED


def test_a_moved_entity_set_degrades_where_a_changed_id_is_unmet():
    """Two different facts. A provider that renumbers its players and one that
    registered a new signing between two fetches are not the same finding, and
    only the first is objective 18 failing."""
    moved = _collect(
        players=_pool(_record(1, "Karl Hein", team="Arsenal")),
        second_fetch=_pool(
            _record(1, "Karl Hein", team="Arsenal"), _record(3, "Kepa Arrizabalaga Revuelta")),
    )
    renumbered = _collect(
        players=_pool(_record(1, "Karl Hein", team="Arsenal")),
        second_fetch=_pool(_record(2, "Karl Hein", team="Arsenal")),
    )
    assert (_statuses(moved)[18], _statuses(renumbered)[18]) == (DEGRADED, UNMET)
    assert _shapes(moved)["provider_id_stability"] == \
        "1 compared; 0 changed; 1 appeared; 0 disappeared"


def test_two_disjoint_snapshots_leave_nothing_to_compare():
    report = _collect(
        players=_pool(_record(1, "Karl Hein", team="Arsenal")),
        second_fetch=_pool(_record(2, "Kepa Arrizabalaga Revuelta")),
    )
    assert _statuses(report)[18] == UNMET
    assert "no entity appeared in both snapshots" in _evidence(report, 18)


# --- The synthesized rehearsal --------------------------------------------------------

def test_the_synthesis_is_declared_in_the_report(tmp_path):
    trial_mapping.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert trial_mapping.SYNTHETIC_WARNING in payload["warnings"]


def test_the_mock_pool_is_drawn_from_the_registry_and_says_so():
    """A rehearsal that matched by construction and did not say so would read as
    a 100% match rate against Sportmonks."""
    corpus = trial_mapping.load_corpus()
    pool = trial_mapping.mock_pool_payload(corpus)
    candidates, _ = trial_mapping.registry_candidates(corpus)
    assert len(pool["data"]) == trial_mapping.MOCK_POOL_SIZE
    assert [row["name"] for row in pool["data"]] == \
        [candidate.full_name for candidate in candidates[:trial_mapping.MOCK_POOL_SIZE]]


# --- The declaration -------------------------------------------------------------

def test_every_entry_is_declared_and_names_a_test_that_exists():
    report = _collect()
    assert set(trial_mapping.DECLARED_SHAPES) == set(_shapes(report))
    for names in trial_mapping.DECLARED_SHAPES.values():
        for name in names:
            assert name in globals(), name
