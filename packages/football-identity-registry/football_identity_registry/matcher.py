"""Exact, ordered, never-guess cross-provider player matcher."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import CandidateEvidence, CandidatePlayer, MatchResult, SourcePlayer
from .normalization import normalize_name, surname

MATCH_TIERS = (
    ("manual_override", 1.00),
    ("full_name_birth_date", 0.99),
    ("full_name_team", 0.95),
    ("full_name_unique", 0.90),
    ("known_name_team", 0.85),
    ("surname_birth_date", 0.80),
)


def _evidence(candidate: CandidatePlayer, fields: tuple[str, ...]) -> CandidateEvidence:
    return CandidateEvidence(candidate.canonical_player_id, candidate.full_name, fields)


def match_player(
    source: SourcePlayer,
    candidates: Sequence[CandidatePlayer],
    overrides: Mapping[tuple[str, str], str] | None = None,
    *,
    threshold: float = 0.80,
) -> MatchResult:
    ordered = sorted(candidates, key=lambda c: c.canonical_player_id)
    override_id = (overrides or {}).get((source.provider, source.provider_id))
    if override_id is not None:
        found = [c for c in ordered if c.canonical_player_id == override_id]
        if len(found) != 1:
            return MatchResult(source, None, None, None, reason="invalid_manual_override")
        return MatchResult(source, override_id, "manual_override", 1.0)

    full = normalize_name(source.full_name)
    known = normalize_name(source.known_name or source.full_name)
    tier_filters = (
        ("full_name_birth_date", 0.99, ("full_name", "birth_date"), lambda c: bool(source.birth_date) and normalize_name(c.full_name) == full and c.birth_date == source.birth_date),
        ("full_name_team", 0.95, ("full_name", "team_provider_id"), lambda c: bool(source.team_provider_id) and normalize_name(c.full_name) == full and c.team_provider_id == source.team_provider_id),
        ("full_name_unique", 0.90, ("full_name",), lambda c: normalize_name(c.full_name) == full),
        ("known_name_team", 0.85, ("known_name", "team_provider_id"), lambda c: bool(source.team_provider_id) and normalize_name(c.known_name or c.full_name) == known and c.team_provider_id == source.team_provider_id),
        ("surname_birth_date", 0.80, ("surname", "birth_date"), lambda c: bool(source.birth_date) and surname(c.full_name) == surname(source.full_name) and c.birth_date == source.birth_date),
    )
    for method, confidence, fields, predicate in tier_filters:
        matches = [c for c in ordered if predicate(c)]
        if len(matches) > 1:
            return MatchResult(source, None, None, None, tuple(_evidence(c, fields) for c in matches), "ambiguous")
        if len(matches) == 1:
            if confidence < threshold:
                return MatchResult(source, None, None, None, (_evidence(matches[0], fields),), "below_threshold")
            return MatchResult(source, matches[0].canonical_player_id, method, confidence)
    return MatchResult(source, None, None, None, reason="no_candidate")
