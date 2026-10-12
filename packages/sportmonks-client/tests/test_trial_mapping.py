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
from sportmonks_client.models import Player, parse_entity  # noqa: E402
from _trial_common import MOCK_SCOPE  # noqa: E402

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


# --- The FPL side of the gate (live) -------------------------------------------

def _el(i, first, second, web, born, team=1, minutes=900):
    return {"id": i, "first_name": first, "second_name": second, "web_name": web,
            "birth_date": born, "team": team, "minutes": minutes}


def _bootstrap(*elements):
    return {"elements": list(elements)}


def _rec(i, name, born, display=None):
    """A Sportmonks player record the way the squads include delivers it."""
    return parse_entity(Player, {
        "id": i, "name": name, "display_name": display or name, "date_of_birth": born}, "squads")


def _side(records, *elements):
    return trial_mapping.fpl_side(records, trial_mapping.fpl_people(_bootstrap(*elements)))


def test_the_gate_denominator_is_fpl_elements_with_minutes():
    played = _el(1, "Ann", "Able", "Able", "2000-01-01")
    bench = _el(2, "Bob", "Baker", "Baker", "2001-02-02", minutes=0)
    side = _side([_rec(10, "Ann Able", "2000-01-01")], played, bench)
    assert (side.with_minutes, side.with_minutes_resolved) == (1, 1)
    assert (side.all_elements, side.all_resolved) == (2, 1)
    assert side.rate_percent == 100.0 and side.meets_gate


def test_an_element_nobody_played_does_not_count_against_the_gate():
    played = _el(1, "Ann", "Able", "Able", "2000-01-01")
    idle = _el(2, "Bob", "Baker", "Baker", "2001-02-02", minutes=0)
    side = _side([_rec(10, "Ann Able", "2000-01-01")], played, idle)
    assert side.all_resolved / side.all_elements == 0.5 and side.rate_percent == 100.0


def test_a_player_missing_from_the_sportmonks_pool_lowers_the_rate():
    a = _el(1, "Ann", "Able", "Able", "2000-01-01")
    b = _el(2, "Bob", "Baker", "Baker", "2001-02-02")
    side = _side([_rec(10, "Ann Able", "2000-01-01")], a, b)
    assert (side.with_minutes, side.with_minutes_resolved, side.rate_percent) == (2, 1, 50.0)
    assert not side.meets_gate and side.fpl_causes == {"absent_from_other_side": 1}


def test_the_academy_rows_of_the_pool_are_reported_apart_and_do_not_move_the_gate():
    a = _el(1, "Ann", "Able", "Able", "2000-01-01")
    pool = [_rec(10, "Ann Able", "2000-01-01"), _rec(11, "Kid Youth", "2009-05-05")]
    side = _side(pool, a)
    assert side.rate_percent == 100.0 and (side.pool, side.pool_resolved) == (2, 1)
    assert side.pool_causes == {"absent_from_other_side": 1}


def test_the_legal_name_with_extra_words_is_filed_as_a_compound_not_resolved():
    """The matcher is untouched: a longer legal name with the same birth date is a
    non-match, reported under its cause. Resolving it is a tier decision."""
    e = _el(1, "Piero", "Hincapié", "Hincapie", "2002-01-09")
    side = _side([_rec(10, "Piero Martín Hincapié Reyna", "2002-01-09", display="Piero Hincapié")], e)
    assert side.with_minutes_resolved == 0 and side.fpl_causes == {"nickname_or_abbreviation": 1} \
        or side.fpl_causes == {"compound_or_partial_name": 1}


def _person(name, born, known=None, alt=None, side="fpl"):
    return {"side": side, "full_name": name, "birth_date": born, "known_name": known, "alt_name": alt}


def test_every_cause_is_reachable_and_they_are_pairwise_different():
    other = lambda name, born, known=None, alt=None: _person(name, born, known, alt, "sportmonks")
    cases = {
        "fpl_birth_date_absent": explain(_person("Ann Able", None), []),
        "indistinguishable_in_fpl": explain(_person("Ann Able", "2000-01-01"), [], conflict=True),
        "nickname_or_abbreviation": explain(_person("Juanlu Sanchez", "2003-08-15", "Juanlu"),
                                            [other("Juan Luis Sanchez Velasco", "2003-08-15", "Juanlu")]),
        "spelling_or_hyphenation": explain(_person("Jaden Philogene Bidace", "2002-02-08"),
                                           [other("Jaden Philogene-Bidace", "2002-02-08")]),
        "compound_or_partial_name": explain(_person("Erling Haaland", "2000-07-21"),
                                            [other("Erling Braut Haaland", "2000-07-21")]),
        "same_birth_date_different_name": explain(_person("Ann Able", "2000-01-01"),
                                                  [other("Zed Zulu", "2000-01-01")]),
        "birth_date_differs": explain(_person("Ann Able", "2000-01-01"), [other("Ann Able", "1999-12-31")]),
        "other_side_birth_date_absent": explain(_person("Ann Able", "2000-01-01"), [other("Ann Able", None)]),
        "absent_from_other_side": explain(_person("Ann Able", "2000-01-01"), [other("Zed Zulu", "1990-01-01")]),
    }
    assert {k: v for k, v in cases.items()} == {k: k for k in cases}
    assert set(cases) == set(trial_mapping.CAUSES)


explain = trial_mapping.explain_non_match


def _live(tmp_path, records, *elements, state=None):
    transport = trial_mapping.mock_transport(players=_pool(*records))
    client = make_client(MODE_MOCK, transport=transport)
    return trial_mapping.collect(client, "live", bootstrap=_bootstrap(*elements),
                                 scope=MOCK_SCOPE, state_dir=state)[0]


def test_a_live_run_gates_on_the_fpl_side_and_says_so(tmp_path):
    a = _el(1, "Ann", "Able", "Able", "2000-01-01")
    b = _el(2, "Bob", "Baker", "Baker", "2001-02-02")
    report = _live(tmp_path, [_record(10, "Ann Able", date_of_birth="2000-01-01")], a, b)
    assert _statuses(report)[19] == UNMET
    text = _evidence(report, 19)
    assert "minutes>0 still in a PL club: 1/2" in text and "50.0%" in text and "Sportmonks pool 1/1" in text
    assert "fpl_unmatched_with_minutes_by_cause" in _shapes(report)
    assert _shapes(report)["fpl_unmatched_with_minutes_by_cause"] == "absent_from_other_side 1"


def test_a_live_run_at_the_gate_is_observed(tmp_path):
    a = _el(1, "Ann", "Able", "Able", "2000-01-01")
    report = _live(tmp_path, [_record(10, "Ann Able", date_of_birth="2000-01-01")], a)
    assert _statuses(report)[19] == OBSERVED and "100.0%" in _evidence(report, 19)


def test_the_second_live_run_compares_ids_with_the_first(tmp_path):
    a = _el(1, "Ann", "Able", "Able", "2000-01-01")
    state = tmp_path / "mapping"
    first = _live(tmp_path, [_record(10, "Ann Able", date_of_birth="2000-01-01")], a, state=state)
    assert "provider_id_stability_across_runs" not in _shapes(first)
    renumbered = _live(tmp_path, [_record(99, "Ann Able", date_of_birth="2000-01-01")], a, state=state)
    assert _shapes(renumbered)["provider_id_stability_across_runs"].startswith("1 compared against a read")
    assert "1 changed" in _shapes(renumbered)["provider_id_stability_across_runs"]


def test_a_mock_run_still_gates_on_the_published_corpus_not_on_fpl():
    report = _collect()
    assert "fpl_unmatched_with_minutes_by_cause" not in _shapes(report)
    assert "candidate registry" in _evidence(report, 19)


# --- The display-name second pass (approved 2026-10-11, one test per guard) ----

CLUB = 100       # a Sportmonks club id
TEAM = "7"       # the FPL team it maps to


def _sm(i, name, born, display=None, club=CLUB, position=26):
    return parse_entity(Player, {
        "id": i, "name": name, "display_name": display if display is not None else name,
        "date_of_birth": born, "squad_team_id": club, "position_id": position}, "squads")


def _fpl(i, first, second, web, born, team=7, minutes=900, etype=3):
    return {"id": i, "first_name": first, "second_name": second, "web_name": web, "birth_date": born,
            "team": team, "minutes": minutes, "element_type": etype}


def _anchors():
    """Three exact first-pass pairs for the club: enough for the crosswalk to trust it."""
    sm = [_sm(1, "Ann Able", "2000-01-01"), _sm(2, "Bob Baker", "2000-02-02"), _sm(3, "Cy Cook", "2000-03-03")]
    fpl = [_fpl(1, "Ann", "Able", "Able", "2000-01-01"), _fpl(2, "Bob", "Baker", "Baker", "2000-02-02"),
           _fpl(3, "Cy", "Cook", "Cook", "2000-03-03")]
    return sm, fpl


def _run(extra_sm, extra_fpl, **kwargs):
    sm, fpl = _anchors()
    return trial_mapping.fpl_side(sm + extra_sm, trial_mapping.fpl_people(_bootstrap(*(fpl + extra_fpl))), **kwargs)


LEGAL = _sm(9, "Piero Martin Hincapie Reyna", "2002-01-09", display="Piero Hincapie")
TARGET = _fpl(9, "Piero", "Hincapie", "Hincapie", "2002-01-09")


def test_the_display_name_pass_resolves_a_legal_name_and_reports_its_own_method():
    side = _run([LEGAL], [TARGET])
    assert side.with_minutes_resolved == 4 and side.second_pass["resolved"] == 1
    assert side.by_method[trial_mapping.DISPLAY_NAME_METHOD] == 1
    assert side.by_method["full_name_birth_date"] == 3, "the first-pass pairs keep their own method"


def test_without_the_pass_the_same_row_stays_unresolved():
    side = _run([LEGAL], [TARGET], second_pass=False)
    assert side.with_minutes_resolved == 3 and trial_mapping.DISPLAY_NAME_METHOD not in side.by_method


def test_the_pass_never_replaces_a_first_pass_pair():
    """Ann resolves to element 1 on the first pass. Her display name would point at
    element 4 (same birth date, different person); the pair must stay and the
    would-be change is only counted."""
    sm, fpl = _anchors()
    ann = _sm(1, "Ann Able", "2000-01-01", display="Ann Bea Able")
    other = _fpl(4, "Ann", "Bea Able", "Bea Able", "2000-01-01")
    side = trial_mapping.fpl_side([ann] + sm[1:], trial_mapping.fpl_people(_bootstrap(*(fpl + [other]))))
    assert side.second_pass["first_pass_pairs_changed"] == 1
    assert side.second_pass["resolved"] == 0 and trial_mapping.DISPLAY_NAME_METHOD not in side.by_method
    assert side.by_method["full_name_birth_date"] == 3
    assert side.all_resolved == 3, "element 4 stays unresolved: the display name did not take it"


def test_the_pass_only_looks_at_rows_the_first_pass_left_unresolved():
    side = _run([LEGAL], [TARGET])
    assert side.by_method["full_name_birth_date"] + side.by_method[trial_mapping.DISPLAY_NAME_METHOD] \
        + side.by_method.get("surname_birth_date", 0) + side.by_method.get("full_name_unique", 0) == 4


def test_a_second_row_cannot_take_an_element_a_first_pass_row_already_holds():
    twin = _sm(10, "Ann Alternate Legal", "2000-01-01", display="Ann Able")
    side = _run([twin], [])
    assert side.second_pass["resolved"] == 0 and side.second_pass["rejected_taken"] == 1


def test_a_missing_birth_date_on_the_provider_side_does_not_resolve():
    """Without the method restriction this row would resolve through
    `full_name_unique`, which needs no birth date."""
    undated = _sm(11, "Piero Martin Hincapie Reyna", None, display="Piero Hincapie")
    side = _run([undated], [TARGET])
    assert side.second_pass["resolved"] == 0 and side.with_minutes_resolved == 3


def test_a_missing_birth_date_on_the_fpl_side_does_not_resolve():
    undated = _fpl(9, "Piero", "Hincapie", "Hincapie", None)
    side = _run([LEGAL], [undated])
    assert side.second_pass["resolved"] == 0 and side.with_minutes_resolved == 3


def test_a_club_that_disagrees_with_the_crosswalk_does_not_resolve():
    elsewhere = _fpl(9, "Piero", "Hincapie", "Hincapie", "2002-01-09", team=8)
    side = _run([LEGAL], [elsewhere])
    assert side.second_pass["resolved"] == 0 and side.second_pass["rejected_club"] == 1
    assert side.with_minutes_resolved == 3


def test_a_club_the_first_pass_could_not_vouch_for_does_not_resolve():
    stranger = _sm(9, "Piero Martin Hincapie Reyna", "2002-01-09", display="Piero Hincapie", club=555)
    side = _run([stranger], [TARGET])
    assert side.second_pass["resolved"] == 0 and side.second_pass["rejected_club"] == 1


def test_the_crosswalk_trusts_a_club_only_with_enough_unanimous_pairs():
    assert trial_mapping.club_crosswalk([(1, "7"), (1, "7"), (1, "7")]) == {1: "7"}
    assert trial_mapping.club_crosswalk([(1, "7"), (1, "7")]) == {}
    assert trial_mapping.club_crosswalk([(1, "7"), (1, "7"), (1, "8")]) == {}
    assert trial_mapping.club_crosswalk([(1, "7")] * 3 + [(2, "9")] * 3) == {1: "7", 2: "9"}


def test_the_pass_audit_is_a_set_of_counts_and_nothing_else():
    sm, fpl = _anchors()
    side = trial_mapping.fpl_side(sm + [LEGAL], trial_mapping.fpl_people(_bootstrap(*(fpl + [TARGET]))))
    assert side.second_pass == {
        "resolved": 1, "rejected_taken": 0, "rejected_club": 0, "rejected_no_birth_date": 0,
        "first_pass_pairs_changed": 0, "position_mismatch_new": 0, "position_mismatch_first": 0}


def test_only_the_exact_name_and_birth_date_level_may_resolve_in_the_second_pass():
    """With the display name 'Zed Smith', the registry's surname level would pair this
    row with 'Bob Smith' (same last word, same birth date). The pass must not."""
    row = _sm(12, "Zed Quentin Smith Jones", "1999-09-09", display="Zed Smith")
    other = _fpl(12, "Bob", "Smith", "Smith", "1999-09-09")
    side = _run([row], [other])
    assert side.second_pass["resolved"] == 0 and side.with_minutes_resolved == 3
    assert trial_mapping.DISPLAY_NAME_METHOD not in side.by_method


# --- The official denominator: minutes > 0 and still in a Premier League club ----

PL = {1, 2, 3}
SEASON_START = "2026-08-21"
TODAY = "2026-10-11"


def _rule(person, teams, found=True):
    return trial_mapping.departed_from_pl(
        person, lambda p: {"id": 5} if found else None, lambda pid: teams, PL, SEASON_START, TODAY)


def _leaver(status="u", born="1998-08-08"):
    return {"status": status, "birth_date": born, "full_name": "Lee Ver", "known_name": "Ver"}


ABROAD = [{"team_id": 900, "start": "2026-09-01", "end": None}]


def test_unavailable_and_registered_outside_the_league_is_departed():
    assert _rule(_leaver(), ABROAD) is True


def test_an_available_player_is_never_departed_whatever_the_history():
    assert _rule(_leaver(status="a"), ABROAD) is False


def test_a_player_still_current_at_a_pl_club_is_not_departed():
    assert _rule(_leaver(), ABROAD + [{"team_id": 2, "start": "2024-07-01", "end": None}]) is False
    assert _rule(_leaver(), ABROAD + [{"team_id": 2, "start": "2024-07-01", "end": "2027-06-30"}]) is False


def test_an_old_pl_spell_that_ended_does_not_keep_a_departed_player_in():
    assert _rule(_leaver(), ABROAD + [{"team_id": 2, "start": "2020-07-01", "end": "2026-08-31"}]) is True


def test_a_registration_outside_the_league_from_before_the_season_does_not_count():
    assert _rule(_leaver(), [{"team_id": 900, "start": "2024-10-11", "end": None}]) is False


def test_a_player_the_provider_cannot_find_or_without_a_birth_date_is_not_excluded():
    assert _rule(_leaver(), ABROAD, found=False) is False
    assert _rule(_leaver(born=None), ABROAD) is False


def _gate(departed):
    stay = _el(1, "Ann", "Able", "Able", "2000-01-01")
    gone = _el(2, "Lee", "Ver", "Ver", "1998-08-08")
    missing = _el(3, "Mia", "Miss", "Miss", "2001-03-03")
    people = trial_mapping.fpl_people(_bootstrap(stay, gone, missing))
    return trial_mapping.fpl_side([_rec(10, "Ann Able", "2000-01-01")], people, departed=departed)


def test_the_official_denominator_leaves_out_the_departed_and_the_old_one_is_kept_beside_it():
    side = _gate({2})
    assert (side.with_minutes, side.in_pl, side.departed) == (3, 2, 1)
    assert side.rate_percent == 50.0 and side.rate_with_minutes_percent == 33.3333
    assert side.fpl_causes == {"absent_from_other_side": 1}, "the departed one is not filed as a failure"
    assert {i["group"] for i in side.unmatched if i["full_name"] == "Lee Ver"} == {"fpl_departed_from_pl"}


def test_without_departures_the_official_gate_is_the_old_one():
    side = _gate(set())
    assert side.in_pl == side.with_minutes == 3 and side.rate_percent == side.rate_with_minutes_percent


def test_a_resolved_element_is_never_excluded_as_departed():
    stay = _el(1, "Ann", "Able", "Able", "2000-01-01")
    people = trial_mapping.fpl_people(_bootstrap(stay))
    side = trial_mapping.fpl_side([_rec(10, "Ann Able", "2000-01-01")], people, departed={1})
    assert side.departed == 0 and side.in_pl == 1 and side.rate_percent == 100.0


def test_the_post_queue_ceiling_counts_only_what_no_squad_holds():
    side = _gate({2})
    assert side.unreachable == 1 and side.ceiling_percent == 50.0
    nothing_unreachable = trial_mapping.fpl_side(
        [_rec(10, "Ann Able", "2000-01-01"), _rec(11, "Mia Miss Extra", "2001-03-03", display="Mia Miss")],
        trial_mapping.fpl_people(_bootstrap(_el(1, "Ann", "Able", "Able", "2000-01-01"),
                                            _el(3, "Mia", "Miss", "Miss", "2001-03-03"))))
    assert nothing_unreachable.unreachable == 0 and nothing_unreachable.ceiling_percent == 100.0


def test_a_live_run_finds_the_departed_from_the_provider_data_alone(tmp_path):
    from _trial_common import EndpointReplayTransport
    stay = _el(1, "Ann", "Able", "Able", "2000-01-01")
    gone = {**_el(2, "Lee", "Ver", "Ver", "1998-08-08"), "status": "u"}
    pool = _pool(_record(10, "Ann Able", date_of_birth="2000-01-01"))
    transport = EndpointReplayTransport({
        ENDPOINTS["players"][0]: [response(trial_mapping._nest("players", list(pool["data"])))] * 2,
        "players/search/{term}": response({"data": [{"id": 77, "date_of_birth": "1998-08-08", "name": "Lee Ver"}]}),
        "players/{player_id}": response({"data": {"id": 77, "teams": [{"team_id": 900, "start": "2026-09-01", "end": None}]}}),
    })
    client = make_client(MODE_MOCK, transport=transport)
    report = trial_mapping.collect(client, "live", bootstrap=_bootstrap(stay, gone),
                                   scope=MOCK_SCOPE, state_dir=None)[0]
    assert _statuses(report)[19] == OBSERVED
    assert "still in a PL club: 1/1" in _evidence(report, 19)
    assert "departed from the league 1" in _shapes(report)["gate_denominators"]


def test_every_resolved_pair_is_exported_with_its_method_for_local_use():
    sm, fpl = _anchors()
    side = trial_mapping.fpl_side(sm + [LEGAL], trial_mapping.fpl_people(_bootstrap(*(fpl + [TARGET]))))
    pairs = {(a, b): m for a, b, m in side.pairs}
    assert pairs[("1", 1)] == "full_name_birth_date" and pairs[("9", 9)] == trial_mapping.DISPLAY_NAME_METHOD
    assert len(side.pairs) == 4 and len({a for a, _, _ in side.pairs}) == 4


def test_the_pairs_file_holds_ids_and_methods_and_no_names(tmp_path):
    sm, fpl = _anchors()
    side = trial_mapping.fpl_side(sm, trial_mapping.fpl_people(_bootstrap(*fpl)))
    trial_mapping.write_fpl_unmatched(side, tmp_path)
    items = json.loads((tmp_path / "reports/trial_mapping_pairs.json").read_text())["items"]
    assert {tuple(sorted(i)) for i in items} == {("fpl_id", "method", "sportmonks_id")}
    assert "Able" not in (tmp_path / "reports/trial_mapping_pairs.json").read_text()


# --- Manual confirmations: a human said "same player" (explicit, guarded, logged) ---------

import pytest  # noqa: E402

UNPAIRED_SM = _sm(20, "Totally Different Legal Name", "1999-09-09", display="Other Display")
UNPAIRED_FPL = _fpl(20, "Kip", "Quirk", "Quirk", "1999-09-09")


def _manual(sm_id="20", fpl_id=20, **over):
    return {"sportmonks_id": sm_id, "fpl_id": fpl_id, "confirmed_by": "Leo", "confirmed_on": "2026-10-12",
            "evidence": "Sofascore line-up", **over}


def _with_manual(entries, extra_sm=(UNPAIRED_SM,), extra_fpl=(UNPAIRED_FPL,), **kw):
    sm, fpl = _anchors()
    return trial_mapping.fpl_side(sm + list(extra_sm), trial_mapping.fpl_people(_bootstrap(*(fpl + list(extra_fpl)))),
                                  manual_pairs=entries, **kw)


def test_without_a_confirmation_the_unrelated_pair_stays_unresolved():
    side = _with_manual([])
    assert side.with_minutes_resolved == 3 and side.manual_results == ()


def test_a_confirmation_resolves_the_pair_with_its_own_method_and_moves_only_the_final_rate():
    side = _with_manual([_manual()])
    assert side.manual_accepted == 1 and side.by_method[trial_mapping.MANUAL_METHOD] == 1
    assert (side.with_minutes_resolved, side.in_pl) == (4, 4)
    assert side.rate_automatic_percent == 75.0 and side.rate_percent == 100.0
    assert ("20", 20, trial_mapping.MANUAL_METHOD) in side.pairs
    assert side.meets_post_queue_target


def test_a_rejected_confirmation_changes_nothing_and_says_why():
    side = _with_manual([_manual(sm_id="999")])
    assert side.manual_accepted == 0 and side.manual_results[0]["reason"] == "unknown_sportmonks_player"
    assert side.with_minutes_resolved == 3 and not side.meets_post_queue_target


@pytest.mark.parametrize("entry,reason", [
    (_manual(sm_id="999"), "unknown_sportmonks_player"),
    (_manual(fpl_id=999), "unknown_fpl_element"),
    (_manual(sm_id="1", fpl_id=20), "sportmonks_player_already_paired"),       # row 1 is paired automatically
    (_manual(sm_id="20", fpl_id=1), "fpl_element_already_resolved_or_ambiguous"),  # element 1 is resolved automatically
])
def test_each_guard_refuses_what_it_is_for(entry, reason):
    side = _with_manual([entry])
    assert side.manual_results[0]["accepted"] is False and side.manual_results[0]["reason"] == reason
    assert side.by_method.get(trial_mapping.MANUAL_METHOD) is None


def test_a_confirmation_never_overrules_an_automatic_pair():
    side = _with_manual([_manual(sm_id="1", fpl_id=20)])
    assert ("1", 1, "full_name_birth_date") in side.pairs and ("1", 20, trial_mapping.MANUAL_METHOD) not in side.pairs


def test_different_or_missing_birth_dates_are_not_overridden():
    other_day = _fpl(20, "Kip", "Quirk", "Quirk", "1999-09-10")
    assert _with_manual([_manual()], extra_fpl=(other_day,)).manual_results[0]["reason"] == "birth_date_absent_or_different"
    undated = _fpl(20, "Kip", "Quirk", "Quirk", None)
    assert _with_manual([_manual()], extra_fpl=(undated,)).manual_results[0]["reason"] == "birth_date_absent_or_different"


def test_an_element_marked_departed_that_a_human_confirms_is_resolved_and_back_in_the_denominator():
    """A resolved element is never excluded as departed (the rule of 2026-10-11), so a confirmation brings it back."""
    side = _with_manual([_manual()], departed={20})
    assert side.departed == 0 and side.in_pl == 4 and side.manual_in_pl == 1 and side.rate_percent == 100.0
    assert _with_manual([], departed={20}).in_pl == 3, "without the confirmation it stays excluded"


@pytest.mark.parametrize("payload,message", [
    ({"schema_version": 2, "pairs": []}, "schema_version"),
    ({"schema_version": 1}, "schema_version"),
    ({"schema_version": 1, "pairs": [{"sportmonks_id": "1"}]}, "exactly"),
    ({"schema_version": 1, "pairs": [_manual(evidence=" ")]}, "empty"),
    ({"schema_version": 1, "pairs": [_manual(confirmed_on="yesterday")]}, "date"),
    ({"schema_version": 1, "pairs": [_manual(fpl_id="x")]}, "integer"),
    ({"schema_version": 1, "pairs": [_manual(), _manual(fpl_id=21)]}, "twice"),
    ({"schema_version": 1, "pairs": [_manual(), _manual(sm_id="21")]}, "twice"),
])
def test_the_confirmation_file_must_be_complete_dated_attributed_and_without_repeats(tmp_path, payload, message):
    path = tmp_path / "manual_pairs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(trial_mapping.ManualPairsError, match=message):
        trial_mapping.load_manual_pairs(path)


def test_a_missing_file_is_no_confirmations_and_a_good_file_loads(tmp_path):
    path = tmp_path / "manual_pairs.json"
    assert trial_mapping.load_manual_pairs(path) == []
    path.write_text(json.dumps({"schema_version": 1, "pairs": [_manual(fpl_id="20")]}), encoding="utf-8")
    assert trial_mapping.load_manual_pairs(path) == [_manual()]


def test_every_run_appends_what_each_confirmation_did_and_never_rewrites(tmp_path):
    side = _with_manual([_manual(), _manual(sm_id="999", fpl_id=21)])
    first = trial_mapping.append_manual_log(side, tmp_path)
    trial_mapping.append_manual_log(side, tmp_path)
    lines = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4 and {line["accepted"] for line in lines} == {True, False}
    assert all(set(line) >= {"at", "sportmonks_id", "fpl_id", "accepted", "reason"} for line in lines)
    assert trial_mapping.append_manual_log(_with_manual([]), tmp_path) is None


def test_a_live_run_reports_the_confirmations_and_the_two_rates(tmp_path):
    from _trial_common import EndpointReplayTransport
    state = tmp_path / "mapping"
    state.mkdir()
    (state / "manual_pairs.json").write_text(json.dumps({"schema_version": 1, "pairs": [_manual()]}), encoding="utf-8")
    sm, fpl = _anchors()
    pool = [{"id": r.provider_id, **r.raw_fields} for r in sm + [UNPAIRED_SM]]
    transport = EndpointReplayTransport({ENDPOINTS["players"][0]: [response(trial_mapping._nest("players", pool))] * 2})
    client = make_client(MODE_MOCK, transport=transport)
    report = trial_mapping.collect(client, "live", bootstrap=_bootstrap(*(fpl + [UNPAIRED_FPL])), scope=MOCK_SCOPE, state_dir=state)[0]
    text = _shapes(report)["manual_confirmations"]
    assert "1 accepted, 0 rejected" in text and "75.0% automatic -> 100.0% with confirmations" in text and "met" in text
    assert _shapes(report)["match_by_method"].count("manual_confirmation 1") == 1

import pytest  # noqa: E402


# --- FPL's departure notice is evidence enough (approved by Leo, 2026-10-11, via review chat) -------------------

def _gone(news, status="u", **over):
    return {"status": status, "birth_date": "1998-08-08", "full_name": "Lee Ver", "known_name": "Ver", "news": news, **over}


def _no_lookup(person):  # a Sportmonks lookup that must not be needed
    raise AssertionError("the news rule needs no Sportmonks lookup")


@pytest.mark.parametrize("news", [
    "Has joined Como on loan for the rest of the season",
    "Has joined Fiorentina permanently",
    "  has joined juventus on loan for the rest of the season"])
def test_an_unavailable_player_whose_news_says_he_has_joined_another_club_is_departed(news):
    assert trial_mapping.departed_from_pl(_gone(news), _no_lookup, lambda pid: [], PL, SEASON_START, TODAY) is True


@pytest.mark.parametrize("news,status", [
    ("not included in squad.", "u"), ("", "u"), (None, "u"), ("Hamstring injury - Unknown return date", "i"),
    ("Has joined Como on loan for the rest of the season", "a"),       # not unavailable: the notice alone is not enough
    ("Has joined Como on loan for the rest of the season", "i"),
    ("Joined the national team camp", "u"), ("Rumoured to have joined", "u")])
def test_other_news_or_another_status_is_not_a_departure_notice(news, status):
    assert trial_mapping.departed_from_pl(_gone(news, status=status), lambda p: None, lambda pid: [], PL, SEASON_START, TODAY) is False


def test_the_notice_also_covers_a_player_sportmonks_cannot_find_or_without_a_birth_date():
    notice = "Has joined Como on loan for the rest of the season"
    assert trial_mapping.departed_from_pl(_gone(notice, birth_date=None), _no_lookup, lambda pid: [], PL, SEASON_START, TODAY) is True
    assert trial_mapping.departed_from_pl(_gone(None), lambda p: None, lambda pid: [], PL, SEASON_START, TODAY) is False


def test_the_sportmonks_history_still_decides_when_there_is_no_notice():
    assert _rule(_leaver(), ABROAD) is True


def test_a_resolved_element_with_the_notice_is_still_never_excluded():
    elements = [_el(1, "Ann", "Able", "Able", "2000-01-01")]
    people = trial_mapping.fpl_people(_bootstrap(*elements))
    people[0].update(status="u", news="Has joined Como on loan for the rest of the season")
    side = trial_mapping.fpl_side([_rec(10, "Ann Able", "2000-01-01")], people, departed={1})
    assert side.departed == 0 and side.in_pl == 1


def test_the_news_travels_from_the_bootstrap_into_the_people():
    people = trial_mapping.fpl_people(_bootstrap({**_el(1, "Ann", "Able", "Able", "2000-01-01"), "status": "u",
                                                  "news": "Has joined Como on loan for the rest of the season"}))
    assert people[0]["news"].startswith("Has joined") and people[0]["status"] == "u"


# --- Manual departures: a human said "left the league" (explicit, guarded, logged, counted apart) ---

def _left(fpl_id=20, **over):
    return {"fpl_id": fpl_id, "confirmed_by": "Leo", "confirmed_on": "2026-10-12", "evidence": "Leo: left at season start", **over}


def _with_left(entries, **kw):
    return _with_manual([], manual_departures=entries, **kw)


def test_a_manual_departure_leaves_the_denominator_and_is_counted_apart_from_the_rule():
    base = _with_left([])
    side = _with_left([_left()])
    assert side.manual_departed == 1 and side.departed == 0 and side.in_pl == base.in_pl - 1
    assert side.departure_results[0]["accepted"] is True


def test_manual_departure_takes_precedence_over_the_rule_so_it_is_never_counted_twice():
    side = _with_left([_left()], departed={20})
    assert side.manual_departed == 1 and side.departed == 0
    assert side.in_pl == _with_left([]).in_pl - 1
    assert _with_left([], departed={20}).departed == 1


@pytest.mark.parametrize("entry,reason", [
    (_left(fpl_id=999), "unknown_fpl_element"),
    (_left(fpl_id=1), "already_resolved"),            # element 1 is resolved: it cannot be excluded
])
def test_a_manual_departure_that_cannot_apply_is_rejected_with_a_reason(entry, reason):
    side = _with_left([entry])
    assert side.manual_departed == 0 and side.departure_results[0]["reason"] == reason
    assert side.in_pl == _with_left([]).in_pl


def test_a_manual_departure_of_an_element_without_minutes_is_rejected():
    sm, fpl = _anchors()
    idle = {**_fpl(20, "Kip", "Quirk", "Quirk", "1999-09-09"), "minutes": 0}
    side = trial_mapping.fpl_side(sm, trial_mapping.fpl_people(_bootstrap(*(fpl + [idle]))), manual_departures=[_left()])
    assert side.departure_results[0]["reason"] == "no_minutes" and side.manual_departed == 0


@pytest.mark.parametrize("payload,fragment", [
    ({"schema_version": 2, "departures": []}, "schema_version"),
    ({"schema_version": 1, "departures": [{**_left(), "extra": 1}]}, "exactly"),
    ({"schema_version": 1, "departures": [{k: v for k, v in _left().items() if k != "evidence"}]}, "exactly"),
    ({"schema_version": 1, "departures": [_left(evidence=" ")]}, "empty"),
    ({"schema_version": 1, "departures": [_left(confirmed_on="yesterday")]}, "date"),
    ({"schema_version": 1, "departures": [_left(fpl_id="x")]}, "integer"),
    ({"schema_version": 1, "departures": [_left(), _left()]}, "twice"),
])
def test_a_malformed_departures_file_stops_the_run(tmp_path, payload, fragment):
    path = tmp_path / "manual_departures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(trial_mapping.ManualPairsError, match=fragment):
        trial_mapping.load_manual_departures(path)


def test_the_departures_file_is_optional_and_loaded_as_is(tmp_path):
    path = tmp_path / "manual_departures.json"
    assert trial_mapping.load_manual_departures(path) == []
    path.write_text(json.dumps({"schema_version": 1, "departures": [_left(fpl_id="20")]}), encoding="utf-8")
    assert trial_mapping.load_manual_departures(path) == [_left()]


def test_departures_are_logged_on_every_run_and_never_rewritten(tmp_path):
    side = _with_left([_left(), _left(fpl_id=999)])
    trial_mapping.append_manual_log(side, tmp_path)
    trial_mapping.append_manual_log(side, tmp_path)
    lines = [json.loads(x) for x in (tmp_path / "manual_departures.log.ndjson").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4 and {x["accepted"] for x in lines} == {True, False}
    assert all(set(x) >= {"at", "fpl_id", "accepted", "reason"} for x in lines)


def test_a_live_run_reports_manual_departures_beside_the_rule_ones(tmp_path):
    from _trial_common import EndpointReplayTransport
    state = tmp_path / "mapping"
    state.mkdir()
    (state / "manual_departures.json").write_text(json.dumps({"schema_version": 1, "departures": [_left()]}), encoding="utf-8")
    sm, fpl = _anchors()
    pool = [{"id": r.provider_id, **r.raw_fields} for r in sm]
    transport = EndpointReplayTransport({ENDPOINTS["players"][0]: [response(trial_mapping._nest("players", pool))] * 2})
    client = make_client(MODE_MOCK, transport=transport)
    report = trial_mapping.collect(client, "live", bootstrap=_bootstrap(*(fpl + [UNPAIRED_FPL])), scope=MOCK_SCOPE, state_dir=state)[0]
    shapes = _shapes(report)
    assert "1 accepted (manual_departure)" in shapes["manual_departures"]
    assert "1 by manual departure" in shapes["gate_denominators"]


# --- A move inside the league is not a departure from it --------------------------------------

PL_NAMES = ["Man Utd", "Manchester United", "Spurs", "Tottenham Hotspur", "Aston Villa"]


@pytest.mark.parametrize("news", [
    "Has joined Aston Villa on loan for the rest of the season",
    "Has joined Man Utd permanently",
    "has joined tottenham hotspur permanently."])
def test_a_player_who_joined_another_league_club_is_not_departed_from_the_league(news):
    assert trial_mapping.departed_from_pl(_gone(news), lambda p: None, lambda i: [], {1}, "2026-08-01", "2026-10-12",
                                          PL_NAMES) is False


def test_the_same_news_for_a_club_outside_the_league_is_still_a_departure():
    assert trial_mapping.departed_from_pl(_gone("Has joined Como on loan for the rest of the season"), lambda p: None,
                                          lambda i: [], {1}, "2026-08-01", "2026-10-12", PL_NAMES) is True


def test_a_club_name_only_counts_as_a_whole_word():
    # "Villarreal" starts with "Villa" but is not Aston Villa
    assert trial_mapping.departed_from_pl(_gone("Has joined Villarreal on loan"), lambda p: None, lambda i: [], {1},
                                          "2026-08-01", "2026-10-12", ["Villa"]) is True


def test_a_live_run_reads_the_league_clubs_from_the_bootstrap(tmp_path):
    from _trial_common import EndpointReplayTransport
    sm, fpl = _anchors()
    mover = {**_fpl(30, "Moe", "Ver", "Ver", "1998-08-08"), "status": "u", "news": "Has joined Aston Villa permanently"}
    pool = [{"id": r.provider_id, **r.raw_fields} for r in sm]
    transport = EndpointReplayTransport({ENDPOINTS["players"][0]: [response(trial_mapping._nest("players", pool))] * 2})
    client = make_client(MODE_MOCK, transport=transport)
    boot = {**_bootstrap(*(fpl + [mover])), "teams": [{"name": "Aston Villa", "short_name": "AVL"}]}
    report = trial_mapping.collect(client, "live", bootstrap=boot, scope=MOCK_SCOPE, state_dir=None)[0]
    assert "departed from the league 0 by rule" in _shapes(report)["gate_denominators"]
