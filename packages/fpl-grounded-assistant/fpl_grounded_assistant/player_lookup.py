"""Deterministic pre-orchestration classification for general player lookups."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fpl_player_registry import PlayerResolution, normalize_player_name, resolve_player_candidates

from .find_players import _build_match_dict
from .get_player_snapshot import get_player_snapshot
from .router import (
    _RESOLVE_PREFIXES,
    _SUMMARY_PREFIXES,
    _extract_player_query,
    _normalise,
    _strip_summary_trailing_noise,
    route,
)


_GENERAL_LOOKUP_TOOLS = frozenset({"get_player_summary", "resolve_player"})
_BARE_PREFIX_STOPWORDS = frozenset({
    "about", "best", "como", "cual", "cuando", "donde", "esta", "este",
    "find", "give", "hello", "hola", "para", "please", "quien", "search",
    "show", "tell", "that", "this", "vamos", "what", "when", "where", "which",
    "who", "with", "your",
})
_MAX_CANDIDATES = 5


@dataclass(frozen=True)
class PlayerLookupDecision:
    """Result of probing one complete user input for general player intent."""

    status: str
    query: str | None
    explicit: bool
    resolution: PlayerResolution | None
    resolution_strategy: str | None
    candidate_count: int
    deterministic_branch: str

    @property
    def terminal(self) -> bool:
        return self.status in {"ok", "ambiguous"}


def _strategy(resolution: PlayerResolution) -> str | None:
    strategies = {match.matched_via for match in resolution.best_matches}
    if not strategies:
        return None
    return next(iter(strategies)) if len(strategies) == 1 else "mixed"


def _split_team_hint(
    query: str,
    teams: list[dict[str, Any]],
) -> tuple[str, str | None]:
    tokens = query.strip().split()
    if len(tokens) < 2:
        return query.strip(), None
    known_codes = {
        normalize_player_name(team.get("short_name"))
        for team in teams
        if normalize_player_name(team.get("short_name"))
    }
    if normalize_player_name(tokens[-1]) not in known_codes:
        return query.strip(), None
    return " ".join(tokens[:-1]), tokens[-1]


def _explicit_subject(question: str) -> tuple[str | None, bool]:
    original = question.strip().rstrip("?!.")
    normalized = _normalise(question)
    prefixes = sorted(
        tuple((prefix, True) for prefix in _SUMMARY_PREFIXES)
        + tuple((prefix, False) for prefix in _RESOLVE_PREFIXES),
        key=lambda item: -len(item[0]),
    )
    for prefix, is_summary in prefixes:
        start = normalized.find(prefix)
        if start < 0:
            continue
        end = start + len(prefix)
        if start > 0 and normalized[start - 1].isalnum():
            continue
        if end < len(normalized) and normalized[end].isalnum():
            continue
        subject = _extract_player_query(original, normalized, (prefix,))
        if is_summary:
            subject = _strip_summary_trailing_noise(subject)
        return subject or None, True
    return None, False


def classify_player_lookup(
    question: str,
    bootstrap: dict[str, Any],
) -> PlayerLookupDecision:
    """Classify a complete input without scanning embedded name substrings."""
    routed = route(question)
    if routed is not None and routed.tool_name not in _GENERAL_LOOKUP_TOOLS:
        return PlayerLookupDecision(
            status="not_applicable",
            query=None,
            explicit=False,
            resolution=None,
            resolution_strategy=None,
            candidate_count=0,
            deterministic_branch="specialized_fallthrough",
        )

    subject, explicit = _explicit_subject(question)
    query = subject if explicit else question.strip().rstrip("?!.")
    if not query:
        return PlayerLookupDecision(
            status="not_applicable",
            query=None,
            explicit=explicit,
            resolution=None,
            resolution_strategy=None,
            candidate_count=0,
            deterministic_branch="empty_fallthrough",
        )

    players = bootstrap.get("elements", []) or []
    teams = bootstrap.get("teams", []) or []
    name_query, team_hint = _split_team_hint(query, teams)
    normalized_query = normalize_player_name(name_query)
    non_space_chars = sum(char.isalnum() for char in normalized_query)
    allow_prefix = explicit or (
        non_space_chars >= 4 and normalized_query not in _BARE_PREFIX_STOPWORDS
    )
    resolution = resolve_player_candidates(
        name_query,
        players,
        teams,
        allow_prefix=allow_prefix,
        allow_substring=explicit,
        team_hint=team_hint,
    )
    count = len(resolution.best_matches)
    status = resolution.status
    branch_prefix = "explicit" if explicit else "bare"
    branch_suffix = status if status != "not_found" else "not_found_fallthrough"
    return PlayerLookupDecision(
        status=status,
        query=query,
        explicit=explicit,
        resolution=resolution,
        resolution_strategy=_strategy(resolution),
        candidate_count=count,
        deterministic_branch=f"{branch_prefix}_{branch_suffix}",
    )


def execute_player_lookup(
    decision: PlayerLookupDecision,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Execute a terminal lookup decision as the existing snapshot contract."""
    if not decision.terminal or decision.resolution is None:
        raise ValueError("player lookup decision is not terminal")

    if decision.status == "ok":
        match = decision.resolution.player
        if match is None:
            raise ValueError("ok player lookup has no unique match")
        # Resolve the already-selected candidate by authoritative element ID so
        # substring discovery and team-code narrowing cannot diverge in the
        # snapshot tool's second resolution pass.
        return get_player_snapshot(str(match.record.id), bootstrap=bootstrap)

    teams = bootstrap.get("teams", []) or []
    element_types = bootstrap.get("element_types", []) or []
    elements_by_id = {
        element.get("id"): element
        for element in bootstrap.get("elements", []) or []
        if element.get("id") is not None
    }
    candidates = [
        _build_match_dict(
            elements_by_id[match.record.id], teams, element_types, match.rank
        )
        for match in decision.resolution.best_matches[:_MAX_CANDIDATES]
        if match.record.id in elements_by_id
    ]
    normalized_query = normalize_player_name(decision.query or "")
    return {
        "status": "ambiguous",
        "query": normalized_query,
        "candidates": candidates,
        "message": f"Multiple players match '{normalized_query}'. Please specify.",
    }


__all__ = [
    "PlayerLookupDecision",
    "classify_player_lookup",
    "execute_player_lookup",
]
