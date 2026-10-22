"""Licensed matchday store: Sportmonks player id -> FPL element id. Pure: no I/O but the optional alias file.

The matching is the one the trial measured (413/430 = 96.0 % of FPL elements with minutes), run on the
licensed squad reads; the trial's own pairs are trial data and are never reused. It calls the registry's
``match_player`` and adds no tier:

* **First pass:** the provider's ``name`` as the full name, against every FPL element, with identities whose
  fingerprint several distinguishable FPL records share dropped first (the registry's conflict rule).
* **Second pass,** only over rows the first left unresolved: the provider's ``display_name`` as the full
  name, accepted only through ``full_name_birth_date`` (both birth dates present and equal), only to an
  element no earlier pair took, and only when the player's club agrees with the club crosswalk the first
  pass built (a club maps only when at least three first-pass pairs all name the same FPL team).
* **Manual aliases (optional):** a checked-in file of FPL element ids a human confirmed. It holds no provider
  id and no name: an entry resolves only when exactly one still-unresolved provider player of that element's
  club (by the club crosswalk) has the element's birth date. Applied last, never over an existing pair.
  A missing file is no aliases.

``trial_mapping.fpl_side`` (sportmonks-client/scripts) is the reference implementation of the first two
passes; ``test_licensed_crosswalk`` runs both on one pool and requires the same pairs, so the two cannot
drift while the trial script exists. The report holds counts only (the job's logs are public).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from football_identity_registry.canonical_ids import canonical_player_id, identity_fingerprint
from football_identity_registry.matcher import match_player
from football_identity_registry.models import CandidatePlayer, SourcePlayer
from football_identity_registry.normalization import normalize_name

SECOND_PASS_METHOD = "display_name_birth_date"
MANUAL_METHOD = "manual_birth_date_club"
CLUB_GUARD_MIN_PAIRS = 3
ALIAS_FIELDS = ("fpl_id", "confirmed_by", "confirmed_on", "evidence")


class AliasFileError(ValueError):
    """The manual alias file is not in the governed shape."""


@dataclass
class CrosswalkReport:
    """Counts only."""

    pool: int = 0
    pool_resolved: int = 0
    elements: int = 0
    elements_with_minutes: int = 0
    with_minutes_resolved: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    aliases_accepted: int = 0
    aliases_rejected: dict[str, int] = field(default_factory=dict)

    @property
    def rate_with_minutes_percent(self) -> float:
        return round(self.with_minutes_resolved / self.elements_with_minutes * 100, 4) if self.elements_with_minutes else 0.0


@dataclass(frozen=True)
class Crosswalk:
    pairs: Mapping[int, int]  # Sportmonks player id -> FPL element id
    report: CrosswalkReport


def load_aliases(path: Path) -> list[dict[str, Any]]:
    """``{"schema_version": 1, "aliases": [{fpl_id, confirmed_by, confirmed_on, evidence}]}``; missing = none.

    Every entry says who confirmed it, when and on what evidence; a missing field, a malformed date or a
    repeated FPL id stops the run."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise AliasFileError("alias file is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("aliases"), list):
        raise AliasFileError("alias file must be {schema_version: 1, aliases: [...]}")
    seen: set[int] = set()
    out = []
    for entry in payload["aliases"]:
        if not isinstance(entry, dict) or set(entry) != set(ALIAS_FIELDS):
            raise AliasFileError(f"each alias needs exactly {ALIAS_FIELDS}")
        if any(not str(entry[k]).strip() for k in ALIAS_FIELDS):
            raise AliasFileError("no alias field may be empty")
        try:
            date.fromisoformat(str(entry["confirmed_on"]))
            fpl_id = int(entry["fpl_id"])
        except ValueError as exc:
            raise AliasFileError("confirmed_on must be a date and fpl_id an integer") from exc
        if fpl_id in seen:
            raise AliasFileError("an FPL element appears twice")
        seen.add(fpl_id)
        out.append({**entry, "fpl_id": fpl_id})
    return out


def _person(element: Mapping[str, Any]) -> dict[str, Any]:
    birth = element.get("birth_date")
    return {"id": element.get("id"),
            "full_name": f"{element.get('first_name') or ''} {element.get('second_name') or ''}".strip(),
            "known_name": element.get("web_name"), "birth_date": (birth or "")[:10] or None,
            "team": str(element.get("team")), "minutes": int(element.get("minutes") or 0)}


def _candidates(people: Sequence[Mapping[str, Any]]) -> tuple[list[CandidatePlayer], set[str]]:
    """The registry's candidate set with indistinguishable identities dropped (its conflict rule)."""
    signatures: dict[str, set[tuple[str, str, str]]] = {}
    for p in people:
        signatures.setdefault(identity_fingerprint(p["full_name"], p["birth_date"]), set()).add(
            (p["team"] or "", normalize_name(str(p["known_name"] or "")), p["birth_date"] or ""))
    conflicts = {fp for fp, values in signatures.items() if len(values) > 1}
    candidates = {CandidatePlayer(canonical_player_id(p["full_name"], p["birth_date"]), p["full_name"], p["team"],
                                  p["birth_date"], p["known_name"])
                  for p in people if identity_fingerprint(p["full_name"], p["birth_date"]) not in conflicts}
    return sorted(candidates, key=lambda c: c.canonical_player_id), conflicts


def _club_crosswalk(pairs: Iterable[tuple[Any, str]]) -> dict[Any, str]:
    votes: dict[Any, Counter] = {}
    for club, team in pairs:
        votes.setdefault(club, Counter())[team] += 1
    return {club: next(iter(teams)) for club, teams in votes.items()
            if len(teams) == 1 and sum(teams.values()) >= CLUB_GUARD_MIN_PAIRS}


def build_crosswalk(players: Iterable[Mapping[str, Any]], elements: Iterable[Mapping[str, Any]],
                    aliases: Sequence[Mapping[str, Any]] = ()) -> Crosswalk:
    """``players``: provider player records (``id``, ``name``, ``display_name``, ``date_of_birth``,
    ``squad_team_id``); ``elements``: FPL ``bootstrap-static`` elements."""
    records = {int(r["id"]): r for r in players}
    people = [_person(e) for e in elements]
    candidates, conflicts = _candidates(people)
    by_canonical: dict[str, list[dict[str, Any]]] = {}
    for p in people:
        by_canonical.setdefault(canonical_player_id(p["full_name"], p["birth_date"]), []).append(p)
    report = CrosswalkReport(pool=len(records), elements=len(people))
    methods: Counter = Counter()

    def source(pid: int, full_name: str, team: Any) -> SourcePlayer:
        r = records[pid]
        return SourcePlayer(provider="sportmonks", provider_id=str(pid), full_name=full_name, team_provider_id=team,
                            birth_date=r.get("date_of_birth"), known_name=r.get("display_name"))

    taken: set[str] = set()
    canon_of: dict[int, str] = {}
    for pid, r in records.items():
        s = source(pid, str(r.get("name") or ""), r.get("team"))
        if identity_fingerprint(s.full_name, s.birth_date) in conflicts:
            continue
        result = match_player(s, candidates)
        if result.matched:
            taken.add(result.canonical_player_id)
            canon_of[pid] = result.canonical_player_id
            methods[result.match_method] += 1

    clubs = _club_crosswalk(
        (records[pid].get("squad_team_id"), by_canonical[canon][0]["team"]) for pid, canon in canon_of.items()
        if len(by_canonical.get(canon, [])) == 1 and records[pid].get("squad_team_id") is not None)
    for pid, r in records.items():
        if pid in canon_of:
            continue
        display = str(r.get("display_name") or "").strip()
        if not display:
            continue
        s = source(pid, display, None)
        if identity_fingerprint(s.full_name, s.birth_date) in conflicts:
            continue
        result = match_player(s, candidates)
        if not result.matched or result.match_method != "full_name_birth_date":
            continue
        matched = by_canonical.get(result.canonical_player_id, [])
        if (not s.birth_date or len(matched) != 1 or not matched[0]["birth_date"]
                or result.canonical_player_id in taken or clubs.get(r.get("squad_team_id")) != matched[0]["team"]):
            continue
        taken.add(result.canonical_player_id)
        canon_of[pid] = result.canonical_player_id
        methods[SECOND_PASS_METHOD] += 1

    people_by_id = {p["id"]: p for p in people}
    rejected: Counter = Counter()
    for entry in aliases:
        person = people_by_id.get(entry["fpl_id"])
        if person is None:
            rejected["unknown_fpl_element"] += 1
            continue
        canonical = canonical_player_id(person["full_name"], person["birth_date"])
        if canonical in taken or identity_fingerprint(person["full_name"], person["birth_date"]) in conflicts:
            rejected["already_resolved_or_ambiguous"] += 1
            continue
        if not person["birth_date"]:
            rejected["no_birth_date"] += 1
            continue
        found = [pid for pid, r in records.items() if pid not in canon_of
                 and clubs.get(r.get("squad_team_id")) == person["team"] and r.get("date_of_birth") == person["birth_date"]]
        if len(found) != 1:
            rejected["no_candidate" if not found else "ambiguous"] += 1
            continue
        taken.add(canonical)
        canon_of[found[0]] = canonical
        methods[MANUAL_METHOD] += 1
        report.aliases_accepted += 1

    pairs = {pid: by_canonical[canon][0]["id"] for pid, canon in canon_of.items() if len(by_canonical.get(canon, [])) == 1}
    resolved = set(pairs.values())
    active = [p for p in people if p["minutes"] > 0]
    report.pool_resolved = len(canon_of)
    report.elements_with_minutes = len(active)
    report.with_minutes_resolved = sum(1 for p in active if p["id"] in resolved)
    report.by_method = dict(sorted(methods.items()))
    report.aliases_rejected = dict(sorted(rejected.items()))
    return Crosswalk(pairs, report)
