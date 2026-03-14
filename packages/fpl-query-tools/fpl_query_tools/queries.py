"""
fpl_query_tools.queries
========================
Read-only query helpers that compose the owned platform packages.

Dependencies (all Tier A, parity-validated):
    fpl_player_registry   — PlayerRecord, build_registry  (Phase 1d)
    fpl_data_core.schemas — POSITION_MAP                  (Phase 1b)
    fpl_api_client        — get_current_gameweek           (Phase 1c)

Design rules for this layer
----------------------------
- All inputs are explicit and in-memory (no network calls, no file I/O)
- Each public function accepts raw bootstrap dicts; it builds internal
  structures on demand (no shared mutable state)
- Resolution order for player queries:
    1. Numeric id  (cast query → int → lookup_by_id)
    2. Exact web_name (case-insensitive)
    3. Exact name  (web_name > second_name > first_name)
    4. Alias / nickname (KNOWN_NICKNAMES table)
- get_player_summary records which strategy resolved the query in the
  returned dict under "query_resolved_via" — useful for chat interface logs
- No LLM integration, no fuzzy matching, no consumer-project wiring

Phase 1e excludes:
    - fpl_captain_engine integration (Phase 2+)
    - Fuzzy / phonetic name matching  (Phase 2+)
    - Any live data fetching
"""

from __future__ import annotations

from typing import Any

from fpl_api_client.fpl_client import get_current_gameweek as _api_get_gw
from fpl_data_core.schemas import POSITION_MAP
from fpl_player_registry import PlayerRecord, build_registry

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATUS_LABELS: dict[str, str] = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
}


def _build_and_resolve(
    query: str | int,
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
) -> tuple[PlayerRecord | None, str | None]:
    """Build a registry and resolve *query*, returning (record, strategy).

    Strategy is one of: "id" | "web_name" | "exact_name" | "alias" | None.
    This is the single authoritative resolution path used by both public
    functions so they stay consistent.
    """
    reg = build_registry(players, teams)
    q = str(query).strip()

    # 1. Numeric id
    try:
        rec = reg.lookup_by_id(int(q))
        if rec is not None:
            return rec, "id"
    except (ValueError, TypeError):
        pass

    # 2. Exact web_name
    rec = reg.lookup_by_web_name(q)
    if rec is not None:
        return rec, "web_name"

    # 3. Exact name (web > second > first; handled inside lookup_by_exact_name)
    rec = reg.lookup_by_exact_name(q)
    if rec is not None:
        return rec, "exact_name"

    # 4. Alias / nickname table
    rec = reg.lookup_by_alias(q)
    if rec is not None:
        return rec, "alias"

    return None, None


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def resolve_player_query(
    query: str | int,
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
) -> PlayerRecord | None:
    """Resolve a player query to a :class:`~fpl_player_registry.PlayerRecord`.

    Parameters
    ----------
    query:
        Any of: FPL element id (int or numeric string), web_name,
        first/second name, or a known nickname alias (e.g. "KDB", "Mo").
    players:
        Player list from ``fpl_api_client.get_players(bootstrap)``.
    teams:
        Team list from ``fpl_api_client.get_teams(bootstrap)``.

    Returns
    -------
    PlayerRecord | None
        The resolved player, or ``None`` if no unambiguous match is found.

    Resolution order
    ----------------
    1. Numeric id  → ``registry.lookup_by_id``
    2. web_name    → ``registry.lookup_by_web_name``  (exact, unambiguous only)
    3. Exact name  → ``registry.lookup_by_exact_name`` (web > second > first)
    4. Alias       → ``registry.lookup_by_alias`` (KNOWN_NICKNAMES table)
    """
    rec, _ = _build_and_resolve(query, players, teams)
    return rec


def get_player_summary(
    query: str | int,
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a human-readable summary dict for a resolved player.

    Resolves *query* identically to :func:`resolve_player_query`, then
    enriches the result with position label, cost in £m, and status text.

    Returns
    -------
    dict | None
        ``None`` if the player cannot be resolved.

    Returned dict keys
    ------------------
    id                   FPL element id (int)
    name                 "{first_name} {second_name}" (falls back to web_name)
    web_name             FPL display name
    team                 Full team name
    team_short           Three-letter abbreviation
    position             "GKP" / "DEF" / "MID" / "FWD"
    cost_m               Cost in £m as float (e.g. 14.5), or None if unknown
    status               Human-readable availability string
    selected_by_percent  Ownership string (e.g. "52.3"), or None
    query_resolved_via   Resolution strategy used: "id" / "web_name" /
                         "exact_name" / "alias"
    """
    rec, via = _build_and_resolve(query, players, teams)
    if rec is None:
        return None

    full_name = f"{rec.first_name} {rec.second_name}".strip() or rec.web_name
    cost_m: float | None = (
        round(rec.now_cost / 10, 1) if rec.now_cost is not None else None
    )

    return {
        "id":                  rec.id,
        "name":                full_name,
        "web_name":            rec.web_name,
        "team":                rec.team_name,
        "team_short":          rec.team_short_name,
        "position":            POSITION_MAP.get(rec.element_type, "Unknown"),
        "cost_m":              cost_m,
        "status":              _STATUS_LABELS.get(rec.status, rec.status),
        "selected_by_percent": rec.selected_by_percent,
        "query_resolved_via":  via,
    }


def get_current_gameweek_from_bootstrap(
    bootstrap: dict[str, Any],
) -> int | None:
    """Return the current (or next) gameweek number from a bootstrap dict.

    A thin wrapper around ``fpl_api_client.get_current_gameweek`` that
    enforces the explicit-input contract: *bootstrap* must be supplied;
    a missing or ``None`` argument will return ``None`` rather than
    triggering a live network call.

    Parameters
    ----------
    bootstrap:
        Full bootstrap dict from ``fpl_api_client.get_bootstrap()``.

    Returns
    -------
    int | None
        Current gameweek id, or ``None`` if the season has not started /
        has finished, or if the bootstrap dict is empty / malformed.
    """
    if not bootstrap:
        return None
    return _api_get_gw(bootstrap)


