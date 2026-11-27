"""A bare club name -> its team card. Deterministic, no model.

The WHOLE input must be a club's name, short code or listed alias: no prefix, no substring, no extra words
(«manchester» keeps asking; «Bournemouth fixtures» routes as before). A player who also matches exactly wins,
as typed player names always have, and the card then offers the club as a chip.
"""
from __future__ import annotations

from typing import Any, Mapping

from fpl_player_registry.resolution import RANK_EXACT

from .player_lookup import PlayerLookupDecision
from .team_fixture_calendar import _TEAM_RESOLVE_ALIASES

TEAM_CARD_TOOL = "get_team_card"
_EDGES = " \t\r\n¿?¡!.,"


def _key(text: str) -> str:
    return " ".join(str(text).strip(_EDGES).casefold().replace("’", "'").split())


def bare_team(text: str, bootstrap: Mapping[str, Any]) -> dict[str, Any] | None:
    """The bootstrap club *text* names in full, or ``None``."""
    query = _key(text)
    if not query:
        return None
    teams = bootstrap.get("teams") or []
    for wanted in (query, _TEAM_RESOLVE_ALIASES.get(query)):
        if wanted is None:
            continue
        for field in ("short_name", "name"):
            for team in teams:
                if _key(team.get(field) or "") == wanted:
                    return team
    return None


def player_matches_exactly(decision: PlayerLookupDecision) -> bool:
    return bool(
        decision.terminal
        and decision.resolution is not None
        and any(match.rank == RANK_EXACT for match in decision.resolution.best_matches)
    )


def team_chip(team: Mapping[str, Any]) -> dict[str, Any]:
    return {"team_id": int(team["id"]), "name": str(team.get("name") or "")}


def team_card_output(team: Mapping[str, Any], bootstrap: Mapping[str, Any], locale: str) -> dict[str, Any] | None:
    """The tool-shaped result: ``status`` plus the same body ``POST /card`` serves."""
    from .card_route import card_body  # noqa: PLC0415  (keeps the builder's imports off this module)

    body = card_body(int(team["id"]), dict(bootstrap), locale)  # type: ignore[arg-type]
    if body is None:
        return None
    return {"status": "ok", "team_name": str(team.get("name") or ""), "team_card": body}
