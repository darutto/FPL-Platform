"""FI-8 trial acceptance script: identity mapping and provider-id stability.

Covers brief §11.3 objectives 18 (stable provider IDs) and 19 (FPL
identity-match rate).

THIS SCRIPT'S OUTPUT IS ITSELF A GATE
-------------------------------------
§14.1 requires ≥95% automatic matching and the FI-2 baseline stands at
**81.3449%** — the largest gap of any gate in the phase. Its FI-8 job is to be
*ready to measure*; the measurement is FI-9. So the number it produces has to be
trustworthy before it is produced, which is why the arithmetic is pinned against
a corpus whose answer is already published (`corpus/report.json`) rather than
against a hand-built pool alone.

NO NEW MATCHING TIER — THE REGISTRY'S MATCHER IS CALLED, NOT REIMPLEMENTED
--------------------------------------------------------------------------
§14.1 prohibits fuzzy matching, speculative aliases, and unsafe fall-through.
`match_player` from `football_identity_registry` is called directly and
`MATCH_TIERS` is never extended, added to, or shadowed here. What this script
does assemble is the *candidate set*, which is not a matching decision: it
mirrors the registry's own conflict rule — identities whose fingerprint is
carried by more than one distinguishable record are dropped, and their sources
are reported `identity_indistinguishable`. That mirroring is not asserted, it is
**measured**: `test_the_rate_reproduces_the_published_fi2_number` runs this
script's arithmetic over the checked-in FI-2 corpus and requires exactly
`0.813449` — the figure §14.1 quotes. A candidate assembly that drifted from the
registry's would produce a different number and fail.

WHY THE MOCK POOL CANNOT BE THE REAL CORPUS
-------------------------------------------
Standing DoD 2 requires every script to exit 0 under `--mock`; DoD 6 requires a
below-threshold rate to exit 1. The real corpus sits at 81.3%, so running mock
mode against it would satisfy the second by violating the first, and "the
rehearsal fails" would become the expected state — the condition under which a
genuine regression stops being visible.

Resolved the way S3 and S5a resolved their corpus gaps: mock mode **synthesizes**
a provider pool from the registry's own candidates and says so in a warning that
travels with the report. That pool matches by construction, which is precisely
why its rate is worthless as evidence and the warning says so in those terms.
The rate that means anything is the one FI-9 computes against a real Sportmonks
pool, and the instrument computing it is pinned by the published-number test
above rather than by the rehearsal.

READS OUTSIDE THE PACKAGE, WRITES NOTHING
-----------------------------------------
S6 is the only FI-8 slice permitted to read outside `packages/sportmonks-client`
and it reads two sibling packages: `football-identity-registry` (the FI-2
crosswalks and matcher) and `football-data-contract` (the provider enum the
matcher's models require). It **must not write** to either;
`test_a_run_leaves_the_identity_registry_byte_identical` hashes the whole
registry tree before and after.

Only `football_identity_registry` grows `EXPECTED_THIRD_PARTY` in
`tests/test_trial_harness.py`, which pins the live-call guard's completeness.
`football_data_contract` is on `sys.path` as the registry's own dependency but
is imported by none of our files, and that allowlist is a statement about what
*we* reach for.

That pin's own error message sanctions exactly two ways to grow: extend the
conftest guard to the new library's network entry points, **or record why the
library cannot reach the network at all**. The second applies, and it is
recorded as a test rather than a comment:
`test_the_registry_import_adds_no_network_capable_module` measures what
importing this script loads into a *fresh interpreter*, as a **difference**
against the harness alone — `requests` brings `http`, `socket`, and `ssl` with
it and always has, and those are the routes the conftest guard already covers.
The question the allowlist entry rests on is the narrow one: does the registry
path add any more.

Note *loads*, not *declares* — `football_identity_registry` does contain
`pandas` and `yaml` imports, in `corpus.py`, `store.py`, and `overrides.py`,
none of which are on the import path this script takes. A file scan would
report a dependency that never executes; the adjacent-question table in §15 is
about exactly that difference.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED, UNMET,
    EndpointReplayTransport, Objective, ObservedShape, PACKAGE_ROOT, TrialRefusal,
    TrialReport, build_parser, make_client, resolve_mode, response, write_report,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

#: The two sibling packages S6 reads. Resolved from this package's root rather
#: than from the current working directory, so the script behaves the same run
#: from anywhere -- the trial operator will not be standing in `packages/`.
REGISTRY_ROOT = PACKAGE_ROOT.parent / "football-identity-registry"
CONTRACT_ROOT = PACKAGE_ROOT.parent / "football-data-contract"
for _root in (CONTRACT_ROOT, REGISTRY_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from football_identity_registry.canonical_ids import (  # noqa: E402
    canonical_player_id, identity_fingerprint,
)
from football_identity_registry.matcher import match_player  # noqa: E402
from football_identity_registry.models import CandidatePlayer, SourcePlayer  # noqa: E402
from football_identity_registry.normalization import normalize_name  # noqa: E402

SCRIPT = "trial_mapping"
OBJECTIVE_18 = "Stable provider IDs"
OBJECTIVE_19 = "FPL identity-match rate"

#: The §14.1 gate, as a percentage. Never rounded up, never waived: a rate below
#: this is `unmet` and exits 1, which is the whole point of measuring it early
#: enough in the trial to still act on a bad number.
GATE_PERCENT = 95.0

#: The FI-2 corpus this script reads. Read-only; nothing here writes to the
#: registry tree.
CORPUS_PATH = REGISTRY_ROOT / "corpus" / "owned_names.json"

#: Which corpus inside that file supplies the candidate registry. The
#: current-season one, because that is the corpus §14.1's 81.3449% refers to.
CORPUS_NAME = "understat"

#: How many candidates the mock pool draws. Small enough to keep the rehearsal
#: fast, large enough that a rate is a rate rather than a coin flip.
MOCK_POOL_SIZE = 20

#: The provider id the synthesized mock pool starts numbering from. An
#: **input**, and deliberately far from any real Sportmonks id range so a
#: rehearsal artifact cannot be mistaken for a live one.
MOCK_PROVIDER_ID_BASE = 900001

SYNTHETIC_WARNING = (
    "the mock provider pool is synthesized from the identity registry's own "
    "candidates, so it matches by construction; its rate is a property of the "
    "rehearsal and is not evidence about Sportmonks. The rate that counts "
    "against the ≥95% gate is the one FI-9 computes on a real provider pool"
)

#: Standing DoD items 10 and 11, per entry.
#:
#: `provider_player_pool` is under item 10's **first** branch: it exists only
#: when the provider returned player records, so an empty pool is visible as a
#: missing entry *and* a non-`observed` objective 19.
#:
#: `match_tiers`, `unresolved_reasons` and `provider_id_stability` are under the
#: **second** branch — existence is the observation, and all three are emitted
#: whenever a pool arrived:
#:  - `match_tiers` because "no tier fired" is what a 0% rate looks like from
#:    the inside, and a vanishing entry could not say which tiers carried the
#:    matches that did happen — the difference between a rate resting on
#:    `full_name_birth_date` and one resting on `known_name_team`.
#:  - `unresolved_reasons` because an empty reason set is the observation that
#:    nothing was unresolved, which is the gate's success condition.
#:  - `provider_id_stability` because "no id changed" is objective 18's entire
#:    positive result; an entry that disappeared on stability would report the
#:    good outcome by saying nothing.
DECLARED_SHAPES = {
    "provider_player_pool": (
        "test_the_pool_entry_reports_the_fields_that_arrived",
        "test_an_empty_pool_drops_its_entry_and_leaves_both_objectives_unmet",
    ),
    "match_tiers": (
        "test_the_tier_entry_names_the_tiers_that_actually_fired",
        "test_the_tier_entry_is_emitted_when_no_tier_fired",
    ),
    "unresolved_reasons": (
        "test_the_unresolved_entry_names_the_reasons_the_matcher_gave",
        "test_the_unresolved_entry_is_emitted_when_nothing_is_unresolved",
    ),
    "provider_id_stability": (
        "test_a_changed_provider_id_is_named_and_makes_objective_eighteen_unmet",
        "test_the_stability_entry_is_emitted_when_nothing_changed",
    ),
}


@dataclass(frozen=True)
class MappingOutcome:
    """What the registry's matcher made of a provider pool."""

    total: int
    matched: int
    tiers: dict[str, int]
    reasons: dict[str, int]
    queue: tuple[dict[str, Any], ...]

    @property
    def rate_percent(self) -> float:
        """Automatic-match rate as a percentage.

        Rounded to four decimals so it prints the way §14.1 quotes the FI-2
        baseline (81.3449%), and never rounded *toward* the gate: the comparison
        below is `>=` against the rounded value, so a rate that only reaches
        95% by rounding cannot pass — 94.99996 rounds to 95.0 at six decimals
        and to 94.9999 here.
        """
        return round(self.matched / self.total * 100, 4) if self.total else 0.0

    @property
    def meets_gate(self) -> bool:
        return self.total > 0 and self.rate_percent >= GATE_PERCENT


@dataclass(frozen=True)
class StabilityOutcome:
    """How two snapshots of the same entity set compare."""

    changed: tuple[str, ...]
    appeared: tuple[str, ...]
    disappeared: tuple[str, ...]
    compared: int

    @property
    def stable(self) -> bool:
        return not self.changed

    @property
    def complete(self) -> bool:
        return not self.appeared and not self.disappeared


def registry_candidates(corpus: dict[str, Any]) -> tuple[list[CandidatePlayer], set[str]]:
    """The registry's candidate set, with indistinguishable identities dropped.

    Mirrors the rule `football_identity_registry.corpus` applies when it
    publishes its own rate. Imported from there directly would be cleaner and is
    not available: that module imports `pandas` at module scope, which this
    package's dependency allowlist excludes for good reason. The mirroring is
    held honest by `test_the_rate_reproduces_the_published_fi2_number` rather
    than by inspection.
    """
    signatures: dict[str, set[tuple[str, str, str]]] = {}
    for row in corpus["candidates"]:
        fingerprint = identity_fingerprint(row["full_name"], row.get("birth_date"))
        signatures.setdefault(fingerprint, set()).add((
            str(row.get("team_provider_id") or ""),
            normalize_name(str(row.get("known_name") or "")),
            str(row.get("birth_date") or ""),
        ))
    conflicts = {fp for fp, values in signatures.items() if len(values) > 1}
    candidates = {
        CandidatePlayer(
            canonical_player_id(row["full_name"], row.get("birth_date")),
            row["full_name"], row.get("team_provider_id"),
            row.get("birth_date"), row.get("known_name"),
        )
        for row in corpus["candidates"]
        if identity_fingerprint(row["full_name"], row.get("birth_date")) not in conflicts
    }
    return sorted(candidates, key=lambda item: item.canonical_player_id), conflicts


def map_pool(
    sources: Sequence[SourcePlayer],
    candidates: Sequence[CandidatePlayer],
    conflicts: set[str],
) -> MappingOutcome:
    """Run the registry's matcher over a provider pool. No tier is added here."""
    tiers: dict[str, int] = {}
    reasons: dict[str, int] = {}
    queue: list[dict[str, Any]] = []
    matched = 0
    for source in sources:
        if identity_fingerprint(source.full_name, source.birth_date) in conflicts:
            reasons["identity_indistinguishable"] = \
                reasons.get("identity_indistinguishable", 0) + 1
            queue.append({
                "source": asdict(source), "reason": "identity_indistinguishable",
                "candidates": [],
            })
            continue
        result = match_player(source, candidates)
        if result.matched:
            matched += 1
            method = result.match_method or "unknown"
            tiers[method] = tiers.get(method, 0) + 1
            continue
        reason = result.reason or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1
        queue.append({
            "source": asdict(source), "reason": reason,
            "candidates": [asdict(candidate) for candidate in result.candidates],
        })
    return MappingOutcome(
        len(sources), matched, dict(sorted(tiers.items())),
        dict(sorted(reasons.items())), tuple(queue),
    )


def source_players(records: Sequence[Any]) -> tuple[SourcePlayer, ...]:
    """Provider player records as matcher inputs.

    The field names are **inputs** — which key Sportmonks uses for a display
    name is unverified until FI-9 — and what gets observed is the pool entry
    reporting which keys actually arrived.
    """
    return tuple(
        SourcePlayer(
            provider="sportmonks",
            provider_id=str(record.provider_id),
            full_name=str(record.raw_fields.get("name") or ""),
            team_provider_id=record.raw_fields.get("team"),
            birth_date=record.raw_fields.get("date_of_birth"),
            known_name=record.raw_fields.get("display_name"),
        )
        for record in records
    )


def snapshot(records: Sequence[Any]) -> dict[str, str]:
    """Entity → provider id, keyed by something that is not the provider id.

    Objective 18 asks whether a provider id is stable for the same entity, so
    the key has to be independent of the thing under test. The normalized name
    is what the registry itself keys on.
    """
    return {
        normalize_name(str(record.raw_fields.get("name") or "")): str(record.provider_id)
        for record in records
    }


def compare_snapshots(first: dict[str, str], second: dict[str, str]) -> StabilityOutcome:
    """Which entities changed provider id between two fetches.

    Entities that appeared or disappeared are reported separately from ids that
    changed: a squad that gained a player between two fetches is an incomplete
    comparison, while an id that moved under a player who was in both is
    objective 18 failing.
    """
    shared = sorted(set(first) & set(second))
    return StabilityOutcome(
        tuple(key for key in shared if first[key] != second[key]),
        tuple(sorted(set(second) - set(first))),
        tuple(sorted(set(first) - set(second))),
        len(shared),
    )


def mock_pool_payload(corpus: dict[str, Any]) -> dict[str, Any]:
    """A Sportmonks-shaped player pool synthesized from registry candidates.

    Deterministic — the candidates are taken in canonical-id order — so mock
    output stays byte-stable across runs.
    """
    candidates, _ = registry_candidates(corpus)
    return {"data": [
        {
            "id": MOCK_PROVIDER_ID_BASE + offset,
            "name": candidate.full_name,
            "display_name": candidate.known_name,
            "date_of_birth": candidate.birth_date,
            "team": candidate.team_provider_id,
        }
        for offset, candidate in enumerate(candidates[:MOCK_POOL_SIZE])
    ]}


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    """Read the FI-2 corpus. Read-only, and the only registry file touched."""
    return json.loads(path.read_text(encoding="utf-8"))["corpora"][CORPUS_NAME]


def mock_transport(
    *,
    players: Any | None = None,
    second_fetch: Any | None = None,
) -> EndpointReplayTransport:
    """Serve the player pool twice — objective 18 needs two fetches of one set.

    `second_fetch` defaults to the first, which is what a stable provider looks
    like. A test supplying a different second payload is what proves the
    stability report is derived from the comparison rather than asserted.
    """
    first = mock_pool_payload(load_corpus()) if players is None else players
    second = first if second_fetch is None else second_fetch
    return EndpointReplayTransport({
        ENDPOINTS["players"][0]: [
            item if isinstance(item, Exception) else response(item)
            for item in (first, second)
        ],
    })


def _fetch(client) -> tuple[tuple[Any, ...], str]:
    try:
        return tuple(client.iter_entities("players")), ""
    except (SportmonksConfigurationError, SportmonksAuthenticationError):
        # Standing DoD item 13: both subclass SportmonksError, and a broad catch
        # here would report a rejected token as "the provider has no players" —
        # which on a gate this narrow reads as a 0% match rate.
        raise
    except SportmonksError as exc:
        return (), type(exc).__name__


def collect(client, mode: str) -> tuple[TrialReport, MappingOutcome]:
    report = TrialReport(script=SCRIPT, mode=mode)
    first, failure = _fetch(client)
    second, second_failure = _fetch(client) if not failure else ((), failure)

    corpus = load_corpus()
    candidates, conflicts = registry_candidates(corpus)
    outcome = map_pool(source_players(first), candidates, conflicts)
    stability = compare_snapshots(snapshot(first), snapshot(second))

    # --- Objective 19: automatic match rate against the §14.1 gate ------------
    shortfalls_19: list[str] = []
    if failure:
        shortfalls_19.append(f"players request failed: {failure}")
    elif not first:
        shortfalls_19.append("no player record returned")
    elif not outcome.meets_gate:
        shortfalls_19.append(
            f"{outcome.rate_percent}% is below the {GATE_PERCENT}% gate; "
            f"{outcome.total - outcome.matched} identit(ies) unresolved"
        )
    evidence_19 = (
        f"{outcome.matched}/{outcome.total} matched automatically "
        f"= {outcome.rate_percent}% against a {len(candidates)}-candidate registry "
        f"(gate ≥{GATE_PERCENT}%)"
    )
    report.objectives.append(Objective(
        19, OBJECTIVE_19,
        # Below the gate is `unmet`, never `degraded`: §14.1 makes it a GO
        # criterion, and a gate reported as a partial observation is a gate
        # someone will read as nearly passing.
        OBSERVED if not shortfalls_19 else UNMET,
        evidence_19 if not shortfalls_19 else f"{evidence_19} — {'; '.join(shortfalls_19)}",
    ))

    # --- Objective 18: provider-id stability ----------------------------------
    shortfalls_18: list[str] = []
    if failure or second_failure:
        shortfalls_18.append(
            f"players request failed: {failure or second_failure}")
    elif not stability.compared:
        shortfalls_18.append("no entity appeared in both snapshots")
    else:
        if not stability.stable:
            shortfalls_18.append(
                f"{len(stability.changed)} provider_id(s) changed between "
                f"snapshots: {','.join(stability.changed)}")
        if not stability.complete:
            shortfalls_18.append(
                f"the entity set moved between snapshots: "
                f"{len(stability.appeared)} appeared, "
                f"{len(stability.disappeared)} disappeared")
    evidence_18 = (
        f"{stability.compared} entit(ies) in both snapshots; "
        f"{len(stability.changed)} provider_id change(s)"
    )
    report.objectives.append(Objective(
        18, OBJECTIVE_18,
        # A changed id is the property failing; a moved entity set is an
        # incomplete comparison. Collapsing them would report a provider that
        # renumbers its players and one that signed someone as the same finding.
        OBSERVED if not shortfalls_18
        else (DEGRADED if stability.stable and stability.compared else UNMET),
        evidence_18 if not shortfalls_18 else f"{evidence_18} — {'; '.join(shortfalls_18)}",
    ))

    if first:
        keys = tuple(first[0].raw_fields)
        extra = sorted({key for r in first for key in r.raw_fields} - set(keys))
        rendered = ",".join(keys)
        report.observed_shapes.append(ObservedShape(
            "provider_player_pool",
            f"{len(first)} record(s); record{{{rendered}{'+' + ','.join(extra) if extra else ''}}}",
        ))
        # Second branch, all three: see DECLARED_SHAPES.
        report.observed_shapes.append(ObservedShape(
            "match_tiers",
            ",".join(f"{tier} {count}" for tier, count in outcome.tiers.items())
            or "no tier fired",
        ))
        report.observed_shapes.append(ObservedShape(
            "unresolved_reasons",
            ",".join(f"{reason} {count}" for reason, count in outcome.reasons.items())
            or "none unresolved",
        ))
        report.observed_shapes.append(ObservedShape(
            "provider_id_stability",
            f"{stability.compared} compared; {len(stability.changed)} changed; "
            f"{len(stability.appeared)} appeared; {len(stability.disappeared)} disappeared",
        ))

    if mode == MODE_MOCK:
        report.warnings.append(SYNTHETIC_WARNING)
    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    return report, outcome


def write_queue(outcome: MappingOutcome, out_dir: Path) -> Path:
    """Emit the unresolved queue in the shape the FI-2 store already writes.

    Same schema as `football-identity-registry`'s `ambiguity_queue.json`, so an
    FI-9 queue can be reviewed and burned down with the tooling that exists
    rather than a second format nobody has a reader for. Written under the
    gitignored trial output — **never** into the registry tree.
    """
    reports_dir = out_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{SCRIPT}_unresolved_queue.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "items": list(outcome.queue)},
            indent=2, ensure_ascii=False, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(19, OBJECTIVE_19, status, reason))
    report.objectives.append(Objective(18, OBJECTIVE_18, status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """Nothing was reached, so nothing was observed."""
    return _report_with(mode, UNMET, reason)


# No `_degraded_report`: `_fetch` turns every provider-scoped error into the
# pool's own observation and re-raises the two that are not, so no generic
# provider branch is enterable. Same reasoning as `trial_entities`,
# `trial_injuries`, and `trial_squads`.


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser(SCRIPT).parse_args(argv)
    try:
        mode = resolve_mode(args)
    except TrialRefusal as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED

    transport = mock_transport() if mode == MODE_MOCK else None
    failure: str | None = None
    config_failure = False
    outcome: MappingOutcome | None = None
    try:
        client = make_client(mode, transport=transport, out_dir=args.out)
        report, outcome = collect(client, mode)
    except SportmonksConfigurationError as exc:
        failure = f"CONFIG: {type(exc).__name__}"
        config_failure = True
        report = _unmet_report(mode, "configuration incomplete; no request was issued")
    except SportmonksAuthenticationError as exc:
        failure = f"AUTH: {type(exc).__name__}"
        config_failure = True
        report = _unmet_report(mode, "authentication rejected by the provider")

    json_path, md_path = write_report(report, args.out)
    queue_path = write_queue(
        outcome if outcome is not None else MappingOutcome(0, 0, {}, {}, ()), args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path} "
          f"queue={queue_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
