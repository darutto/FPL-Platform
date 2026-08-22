"""Shared temporal provenance for bootstrap-backed player rankings."""
from __future__ import annotations

from typing import Any

from .get_gameweek_context import get_gameweek_context


def get_ranking_basis(bootstrap: dict[str, Any] | None) -> str:
    """Map the canonical gameweek state to a stable ranking provenance label.

    Empty fixture overrides keep this temporal-only lookup offline; gameweek
    state itself is still resolved exclusively by ``get_gameweek_context``.
    """
    if not bootstrap:
        return "unknown"

    events = bootstrap.get("events", []) or []
    fixture_overrides = {
        int(event["id"]): []
        for event in events
        if isinstance(event, dict) and "id" in event
    }
    context = get_gameweek_context(
        bootstrap=bootstrap,
        fixtures=fixture_overrides or None,
    )
    if context.get("status") != "ok":
        return "unknown"
    if context.get("is_pre_season"):
        return "prior_season_carryover"
    if context.get("current_gw_status") == "in_progress":
        return "current_season_partial"
    return "current_season"
