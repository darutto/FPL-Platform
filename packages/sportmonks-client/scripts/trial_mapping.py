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
from typing import Any, Collection, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED, UNMET,
    EndpointReplayTransport, Objective, ObservedShape, PACKAGE_ROOT, TrialRefusal,
    TrialReport, build_parser, make_client, resolve_mode, response, write_report,
    _nest, fetch_family, scope_for,
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
            item if isinstance(item, Exception) else response(_nest("players", list(item["data"])))
            for item in (first, second)
        ],
    })


# --- The FPL side of the gate (live) -----------------------------------------
#
# Decided by the review chat on 2026-10-11. The §14.1 gate is measured over the
# players the product has to resolve: FPL 2026/27 elements with minutes > 0 this
# season. All FPL elements and the whole Sportmonks pool (academy players FPL
# never lists) are reported alongside and do not count towards the gate. The
# candidates are the *current* FPL bootstrap, not the 2025-26 corpus, which stays
# in the repository as history and still drives the mock rehearsal. The matcher
# and its tiers are untouched.

FPL_API_ROOT = PACKAGE_ROOT.parent / "fpl-api-client"

#: Causes a non-match is filed under. Diagnostics only: nothing below resolves
#: anything, so none of it is fuzzy matching. Evaluated in this order; the first
#: that holds wins, and `other` is what is left.
CAUSES = (
    "fpl_birth_date_absent",        # the FPL element carries no birth date
    "indistinguishable_in_fpl",     # two FPL elements share name and birth date
    "nickname_or_abbreviation",     # same birth date; known name equals the other side's display name
    "spelling_or_hyphenation",      # same birth date; names equal once spaces, hyphens, apostrophes go
    "compound_or_partial_name",     # same birth date; the names share a word but are not equal
    "same_birth_date_different_name",
    "birth_date_differs",           # same full name, other birth date
    "other_side_birth_date_absent", # same full name, the other side has no birth date
    "absent_from_other_side",       # no one with that birth date or that name on the other side
)


def _compact(value: str) -> str:
    return "".join(ch for ch in normalize_name(value) if ch.isalnum())


def _words(value: str) -> set[str]:
    return {w for w in normalize_name(value).split() if len(w) > 1}


def explain_non_match(person: dict[str, Any], others: Sequence[dict[str, Any]], *,
                      conflict: bool = False) -> str:
    """Why this person found no counterpart on the other side. Diagnostic only."""
    if not person.get("birth_date"):
        return "fpl_birth_date_absent" if person.get("side") == "fpl" else "other_side_birth_date_absent"
    if conflict:
        return "indistinguishable_in_fpl"
    same_dob = [o for o in others if o.get("birth_date") == person["birth_date"]]
    known = normalize_name(person.get("known_name") or "")
    for o in same_dob:
        if known and known in {normalize_name(o.get("known_name") or ""), normalize_name(o.get("alt_name") or "")}:
            return "nickname_or_abbreviation"
    for o in same_dob:
        if _compact(person["full_name"]) == _compact(o["full_name"]):
            return "spelling_or_hyphenation"
    for o in same_dob:
        if _words(person["full_name"]) & _words(o["full_name"]):
            return "compound_or_partial_name"
    if same_dob:
        return "same_birth_date_different_name"
    full = normalize_name(person["full_name"])
    same_name = [o for o in others if normalize_name(o["full_name"]) == full]
    if any(o.get("birth_date") for o in same_name):
        return "birth_date_differs"
    if same_name:
        return "other_side_birth_date_absent"
    return "absent_from_other_side"


def fpl_people(bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
    """FPL elements as plain people. ``minutes`` is the season total."""
    people = []
    for element in bootstrap.get("elements", []):
        birth = element.get("birth_date")
        people.append({
            "side": "fpl", "id": element.get("id"),
            "full_name": f"{element.get('first_name') or ''} {element.get('second_name') or ''}".strip(),
            "known_name": element.get("web_name"), "birth_date": (birth or "")[:10] or None,
            "team": str(element.get("team")), "minutes": int(element.get("minutes") or 0),
            "element_type": element.get("element_type"), "status": element.get("status"),
        })
    return people


def departed_from_pl(person: dict[str, Any], find_player, teams_of,
                     pl_club_ids: Collection[Any], season_start: str, today: str) -> bool:
    """Has this FPL element left the Premier League? Decided from data, never by hand.

    True only when FPL marks the element unavailable (status ``u``) **and** the
    Sportmonks team history shows it registered with a club outside the league
    since the season started **and** with no Premier League club still current.
    ``find_player(person)`` returns the Sportmonks player (a dict with ``id``) or
    None; ``teams_of(player_id)`` returns its team history rows
    (``team_id``, ``start``, ``end``). Both are injected so the rule is testable
    without the provider.
    """
    if person.get("status") != "u" or not person.get("birth_date"):
        return False
    found = find_player(person)
    if not found:
        return False
    entries = list(teams_of(found["id"]) or [])
    if any(e.get("team_id") in pl_club_ids and (not e.get("end") or e["end"] >= today) for e in entries):
        return False
    return any(e.get("team_id") not in pl_club_ids and (e.get("start") or "") >= season_start for e in entries)


#: The method name the second pass reports under, so the gate shows how many
#: resolutions come from it. Distinct from every tier of the registry.
DISPLAY_NAME_METHOD = "display_name_birth_date"
#: A Sportmonks club is trusted to stand for one FPL team only when the first
#: pass produced at least this many pairs for it and every one agreed.
CLUB_GUARD_MIN_PAIRS = 3
#: Sportmonks `position_id` -> FPL `element_type`, used only to report (position
#: is not a guard: the two sources classify wide players differently).
_POSITION = {24: 1, 25: 2, 26: 3, 27: 4}


@dataclass(frozen=True)
class FplSide:
    """The FPL-side measurement. Aggregates only; names stay in ``unmatched``."""

    with_minutes: int
    with_minutes_resolved: int
    all_elements: int
    all_resolved: int
    pool: int
    pool_resolved: int
    fpl_causes: dict[str, int]
    pool_causes: dict[str, int]
    unmatched: tuple[dict[str, Any], ...]
    by_method: dict[str, int]
    second_pass: dict[str, int]
    departed: int = 0

    @property
    def in_pl(self) -> int:
        """Elements with minutes that are still in a Premier League club: the official denominator."""
        return self.with_minutes - self.departed

    @property
    def rate_percent(self) -> float:
        """The official gate: resolved / (minutes > 0 and still in a PL club). A
        departed element is only ever excluded while unresolved, so the
        numerator is unchanged by the exclusion."""
        return round(self.with_minutes_resolved / self.in_pl * 100, 4) if self.in_pl > 0 else 0.0

    @property
    def rate_with_minutes_percent(self) -> float:
        """The previous gate (all elements with minutes), reported beside the official one."""
        return round(self.with_minutes_resolved / self.with_minutes * 100, 4) if self.with_minutes else 0.0

    @property
    def unreachable(self) -> int:
        """Unresolved in-league elements the squads do not hold at all: no matcher can resolve them."""
        return self.fpl_causes.get("absent_from_other_side", 0)

    @property
    def ceiling_percent(self) -> float:
        """Best the manual queue can reach: everything except what no squad holds."""
        return round((self.in_pl - self.unreachable) / self.in_pl * 100, 4) if self.in_pl > 0 else 0.0

    @property
    def meets_gate(self) -> bool:
        return self.in_pl > 0 and self.rate_percent >= GATE_PERCENT


def club_crosswalk(pairs: Sequence[tuple[Any, str]]) -> dict[Any, str]:
    """Sportmonks club -> FPL team, from first-pass pairs only.

    A club is mapped only when it has at least ``CLUB_GUARD_MIN_PAIRS`` pairs and
    all of them name the same FPL team; any dissent leaves it unmapped, and an
    unmapped club cannot vouch for a second-pass resolution.
    """
    votes: dict[Any, dict[str, int]] = {}
    for club, team in pairs:
        votes.setdefault(club, {})[team] = votes.get(club, {}).get(team, 0) + 1
    return {club: next(iter(teams)) for club, teams in votes.items()
            if len(teams) == 1 and sum(teams.values()) >= CLUB_GUARD_MIN_PAIRS}


def fpl_side(records: Sequence[Any], people: Sequence[dict[str, Any]], *,
             second_pass: bool = True, departed: Collection[Any] = ()) -> FplSide:
    """Run the registry's matcher from the Sportmonks pool to the FPL elements.

    First pass: the provider's `name` as the full name. Second pass (approved
    2026-10-11), only over the rows the first left unresolved: the provider's
    `display_name` as the full name, resolving only through
    ``full_name_birth_date`` (both birth dates present and equal), only to an
    FPL element no first-pass row already took, and only when the club agrees
    with the crosswalk the first pass built. A second-pass row never replaces a
    first-pass pair.
    """
    rows = [{"full_name": p["full_name"], "known_name": p["known_name"],
             "birth_date": p["birth_date"], "team_provider_id": p["team"]} for p in people]
    candidates, conflicts = registry_candidates({"candidates": rows})
    by_canonical: dict[str, list[dict[str, Any]]] = {}
    for person in people:
        by_canonical.setdefault(canonical_player_id(person["full_name"], person["birth_date"]), []).append(person)
    sources = source_players(records)
    by_id = {str(r.provider_id): r for r in records}

    hit: set[str] = set()
    pool_matched: set[str] = set()
    pairs: dict[str, str] = {}          # provider id -> canonical id, first pass
    by_method: dict[str, int] = {}
    for source in sources:
        if identity_fingerprint(source.full_name, source.birth_date) in conflicts:
            continue
        result = match_player(source, candidates)
        if result.matched:
            hit.add(result.canonical_player_id)
            pool_matched.add(source.provider_id)
            pairs[source.provider_id] = result.canonical_player_id
            by_method[result.match_method] = by_method.get(result.match_method, 0) + 1

    audit = {"resolved": 0, "rejected_taken": 0, "rejected_club": 0, "rejected_no_birth_date": 0,
             "first_pass_pairs_changed": 0, "position_mismatch_new": 0, "position_mismatch_first": 0}
    for pid, canon in pairs.items():
        people_for = by_canonical.get(canon, [])
        if len(people_for) == 1 and _POSITION.get(by_id[pid].raw_fields.get("position_id")) != people_for[0].get("element_type"):
            audit["position_mismatch_first"] += 1

    if second_pass:
        crosswalk = club_crosswalk([
            (by_id[pid].raw_fields.get("squad_team_id"), by_canonical[canon][0]["team"])
            for pid, canon in pairs.items()
            if len(by_canonical.get(canon, [])) == 1 and by_id[pid].raw_fields.get("squad_team_id") is not None])
        for source in sources:
            record = by_id[source.provider_id]
            display = str(record.raw_fields.get("display_name") or "").strip()
            alt = SourcePlayer(provider="sportmonks", provider_id=source.provider_id,
                               full_name=display or source.full_name, team_provider_id=None,
                               birth_date=source.birth_date, known_name=source.known_name)
            if identity_fingerprint(alt.full_name, alt.birth_date) in conflicts:
                continue
            result = match_player(alt, candidates) if display else None
            if source.provider_id in pairs:
                # Measured, never applied: would the display name have moved a first-pass pair?
                if result is not None and result.matched and result.canonical_player_id != pairs[source.provider_id]:
                    audit["first_pass_pairs_changed"] += 1
                continue
            if result is None or not result.matched or result.match_method != "full_name_birth_date":
                continue
            matched = by_canonical.get(result.canonical_player_id, [])
            if not source.birth_date or len(matched) != 1 or not matched[0]["birth_date"]:
                audit["rejected_no_birth_date"] += 1
                continue
            if result.canonical_player_id in hit:
                audit["rejected_taken"] += 1
                continue
            if crosswalk.get(record.raw_fields.get("squad_team_id")) != matched[0]["team"]:
                audit["rejected_club"] += 1
                continue
            hit.add(result.canonical_player_id)
            pool_matched.add(source.provider_id)
            audit["resolved"] += 1
            by_method[DISPLAY_NAME_METHOD] = by_method.get(DISPLAY_NAME_METHOD, 0) + 1
            if _POSITION.get(record.raw_fields.get("position_id")) != matched[0].get("element_type"):
                audit["position_mismatch_new"] += 1

    def resolved(person: dict[str, Any]) -> bool:
        if identity_fingerprint(person["full_name"], person["birth_date"]) in conflicts:
            return False
        return canonical_player_id(person["full_name"], person["birth_date"]) in hit

    pool_people = [{
        "side": "sportmonks", "id": r.provider_id, "full_name": str(r.raw_fields.get("name") or ""),
        "known_name": r.raw_fields.get("display_name"), "alt_name": r.raw_fields.get("common_name"),
        "birth_date": r.raw_fields.get("date_of_birth"),
    } for r in records]
    for p in pool_people:
        if p["known_name"] is None:
            p["known_name"] = p["alt_name"]
    fpl_causes: dict[str, int] = {}
    pool_causes: dict[str, int] = {}
    unmatched: list[dict[str, Any]] = []
    for person in people:
        if resolved(person):
            continue
        cause = explain_non_match(
            person, pool_people,
            conflict=identity_fingerprint(person["full_name"], person["birth_date"]) in conflicts)
        gone = person["id"] in departed and person["minutes"] > 0
        if person["minutes"] > 0 and not gone:
            fpl_causes[cause] = fpl_causes.get(cause, 0) + 1
        group = ("fpl_departed_from_pl" if gone else
                 "fpl_with_minutes" if person["minutes"] > 0 else "fpl_without_minutes")
        unmatched.append({"group": group, "id": person["id"],
                          "cause": cause, "full_name": person["full_name"],
                          "known_name": person["known_name"], "birth_date": person["birth_date"]})
    for person in pool_people:
        if str(person["id"]) in pool_matched:
            continue
        cause = explain_non_match(person, [{**p, "alt_name": None} for p in people])
        pool_causes[cause] = pool_causes.get(cause, 0) + 1
        unmatched.append({"group": "sportmonks_without_fpl", "cause": cause,
                          "full_name": person["full_name"], "known_name": person["known_name"],
                          "birth_date": person["birth_date"]})
    active = [p for p in people if p["minutes"] > 0]
    return FplSide(
        len(active), sum(1 for p in active if resolved(p)),
        len(people), sum(1 for p in people if resolved(p)),
        len(records), len(pool_matched), dict(sorted(fpl_causes.items())),
        dict(sorted(pool_causes.items())), tuple(unmatched),
        dict(sorted(by_method.items())), audit,
        sum(1 for p in active if p["id"] in departed and not resolved(p)),
    )


def _causes_text(causes: dict[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in sorted(causes.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"


def _departed_ids(client, scope, side: "FplSide", people: Sequence[dict[str, Any]],
                  records: Sequence[Any]) -> set[Any]:
    """FPL elements with minutes, unresolved and marked unavailable, that the rule
    in ``departed_from_pl`` finds registered outside the league. A few requests:
    one search and one team history per candidate."""
    import datetime as _dt

    unresolved = {i["id"] for i in side.unmatched if i["group"] == "fpl_with_minutes"}
    pending = [p for p in people if p["id"] in unresolved and p.get("status") == "u"]
    if not pending:
        return set()
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()

    def find_player(person: dict[str, Any]) -> dict[str, Any] | None:
        words = person["full_name"].split()
        for term in dict.fromkeys([person["known_name"] or "", words[-1] if words else "", words[0] if words else ""]):
            if not term:
                continue
            try:
                hits = list(client.iter_entities("player_search", scope={"term": term}, max_pages=1))
            except SportmonksError:
                continue
            for hit in hits:
                if hit.raw_fields.get("date_of_birth") == person["birth_date"]:
                    return {"id": hit.provider_id}
        return None

    def teams_of(player_id: Any) -> list[dict[str, Any]]:
        try:
            rows = list(client.iter_entities("player_teams", scope={"player_id": player_id}, max_pages=1))
        except SportmonksError:
            return []
        return [dict(t) for r in rows for t in (r.raw_fields.get("teams") or []) if isinstance(t, dict)]

    pl_ids = set(scope.team_ids)
    return {p["id"] for p in pending
            if departed_from_pl(p, find_player, teams_of, pl_ids, scope.season_start or "0000-00-00", today)}


def load_fpl_bootstrap() -> dict[str, Any]:
    """The current FPL bootstrap through the platform's own client.

    Read-only, no token, imported lazily so the mock rehearsal and the import
    audit never load it. Only aggregates are ever versioned.
    """
    if str(FPL_API_ROOT) not in sys.path:
        sys.path.insert(0, str(FPL_API_ROOT))
    from fpl_api_client.fpl_client import get_bootstrap  # noqa: PLC0415
    return get_bootstrap()


def write_fpl_unmatched(side: FplSide, out_dir: Path) -> Path:
    """Names of every unmatched person, grouped. Local and gitignored."""
    reports_dir = out_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{SCRIPT}_fpl_side_unmatched.json"
    path.write_text(json.dumps({"schema_version": 1, "items": list(side.unmatched)},
                               indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    # What the gate leaves for a human: FPL elements with minutes nobody resolved.
    queue = reports_dir / f"{SCRIPT}_manual_queue.json"
    queue.write_text(json.dumps({"schema_version": 1, "items": [
        i for i in side.unmatched if i["group"] == "fpl_with_minutes"]},
        indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path



def _fetch(client, scope) -> tuple[tuple[Any, ...], str]:
    try:
        return fetch_family(client, "players", scope)[0], ""
    except (SportmonksConfigurationError, SportmonksAuthenticationError):
        # Standing DoD item 13: both subclass SportmonksError, and a broad catch
        # here would report a rejected token as "the provider has no players" —
        # which on a gate this narrow reads as a 0% match rate.
        raise
    except SportmonksError as exc:
        return (), type(exc).__name__


def collect(client, mode: str, *, bootstrap: dict[str, Any] | None = None,
            scope=None, state_dir: Path | None = None) -> tuple[TrialReport, MappingOutcome]:
    report = TrialReport(script=SCRIPT, mode=mode)
    live = mode != MODE_MOCK
    scope = scope if scope is not None else scope_for(client, mode)
    first, failure = _fetch(client, scope)
    second, second_failure = _fetch(client, scope) if not failure else ((), failure)

    people = fpl_people(bootstrap if bootstrap is not None else load_fpl_bootstrap()) if (live and first) else None
    if people is not None:
        candidates, conflicts = registry_candidates({"candidates": [
            {"full_name": p["full_name"], "known_name": p["known_name"],
             "birth_date": p["birth_date"], "team_provider_id": p["team"]} for p in people]})
    else:
        corpus = load_corpus()
        candidates, conflicts = registry_candidates(corpus)
    outcome = map_pool(source_players(first), candidates, conflicts)
    stability = compare_snapshots(snapshot(first), snapshot(second))

    side: FplSide | None = None
    if people is not None:
        side = fpl_side(first, people)
        gone = _departed_ids(client, scope, side, people, first)
        if gone:
            side = fpl_side(first, people, departed=gone)
    if side is not None:
        # --- Objective 19, live: the FPL side, minutes > 0 and still in a PL club
        shortfalls_19 = []
        if not side.in_pl:
            shortfalls_19.append("no FPL element with minutes > 0 in a Premier League club to resolve")
        elif not side.meets_gate:
            shortfalls_19.append(
                f"{side.rate_percent}% is below the {GATE_PERCENT}% gate; "
                f"{side.in_pl - side.with_minutes_resolved} element(s) unresolved")
        evidence_19 = (
            f"FPL 2026/27 elements with minutes>0 still in a PL club: {side.with_minutes_resolved}/{side.in_pl} "
            f"resolved automatically = {side.rate_percent}% (gate ≥{GATE_PERCENT}%); "
            f"aside, not counted: previous gate (minutes>0, {side.departed} departed included) "
            f"{side.with_minutes_resolved}/{side.with_minutes} = {side.rate_with_minutes_percent}%, "
            f"all FPL elements {side.all_resolved}/{side.all_elements}, "
            f"Sportmonks pool {side.pool_resolved}/{side.pool}; "
            f"post-queue ceiling {side.in_pl - side.unreachable}/{side.in_pl} = {side.ceiling_percent}%"
        )
    elif failure:
        shortfalls_19 = [f"players request failed: {failure}"]
        evidence_19 = "no pool"
    elif not first:
        shortfalls_19 = ["no player record returned"]
        evidence_19 = "no pool"
    else:
        shortfalls_19 = []
        if not outcome.meets_gate:
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

    if side is not None:
        report.observed_shapes.append(ObservedShape(
            "fpl_unmatched_with_minutes_by_cause", _causes_text(side.fpl_causes)))
        report.observed_shapes.append(ObservedShape(
            "sportmonks_unmatched_by_cause", _causes_text(side.pool_causes)))
        report.observed_shapes.append(ObservedShape(
            "gate_denominators",
            f"official {side.with_minutes_resolved}/{side.in_pl}; previous (minutes>0) "
            f"{side.with_minutes_resolved}/{side.with_minutes}; departed from the league {side.departed}; "
            f"unreachable through squads {side.unreachable}; post-queue ceiling {side.ceiling_percent}%"))
        report.observed_shapes.append(ObservedShape(
            "match_by_method", ", ".join(f"{k} {v}" for k, v in side.by_method.items()) or "none"))
        audit = side.second_pass
        report.observed_shapes.append(ObservedShape(
            "display_name_pass_audit",
            f"resolved {audit['resolved']}; first-pass pairs it would change {audit['first_pass_pairs_changed']}; "
            f"rejected: club {audit['rejected_club']}, element already taken {audit['rejected_taken']}, "
            f"birth date missing {audit['rejected_no_birth_date']}; "
            f"position differs: new {audit['position_mismatch_new']}/{audit['resolved']}, "
            f"first pass {audit['position_mismatch_first']}/{side.pool_resolved - audit['resolved']}"))
        report.warnings.append(
            "gate denominator: FPL elements with minutes > 0 that are still in a Premier League club "
            "(review decision 2026-10-11, refined: unavailable in FPL and registered outside the league "
            "per the Sportmonks team history are excluded, by rule, not by list)"
        )
    if live and first and state_dir is not None:
        across = _stability_across_runs(snapshot(first), state_dir)
        if across:
            report.observed_shapes.append(ObservedShape("provider_id_stability_across_runs", across))

    if mode == MODE_MOCK:
        report.warnings.append(SYNTHETIC_WARNING)
    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    report.fpl_side = side  # type: ignore[attr-defined]
    return report, outcome


def _stability_across_runs(current: dict[str, str], state_dir: Path) -> str:
    """Compare this read with the one saved by the previous run (objective 18, days apart).

    The saved snapshot is replaced by this one. Returns '' on the first run.
    """
    import datetime as _dt
    path = state_dir / "snapshot.json"
    now = _dt.datetime.now(_dt.timezone.utc)
    previous = None
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "players": current},
                               sort_keys=True), encoding="utf-8", newline="\n")
    if not previous:
        return ""
    age = (now - _dt.datetime.strptime(previous["at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=_dt.timezone.utc)).total_seconds() / 3600
    result = compare_snapshots(previous["players"], current)
    return (f"{result.compared} compared against a read {age:.0f} h earlier; "
            f"{len(result.changed)} changed; {len(result.appeared)} appeared; "
            f"{len(result.disappeared)} disappeared")


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
        report, outcome = collect(client, mode, state_dir=args.out / "mapping")
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
    side = getattr(report, "fpl_side", None)
    if side is not None:
        write_fpl_unmatched(side, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path} "
          f"queue={queue_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
