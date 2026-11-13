"""
fpl_grounded_assistant.fixture_cell_zonal
=========================================
The team zonal question under the answer to a /fixtures cell tap (Leo,
2026-11-13): «Quién del BHA explota al HUL ›» -> «¿Qué jugadores del Brighton
pueden explotar las zonas débiles del Hull City?» (get_zonal_opportunity).
Nobody thought to ask it; the cell answer is where the matchup is on screen.

Deterministic, no LLM; the model is only paid for on tap. A link is offered
for the outlook's team against each Premier League opponent of the ONE
gameweek the outlook covers, and only when the tap would be worth it:

* the outlook covers exactly one gameweek (a cell), with at least one match
  (a blank gameweek has no rival); a double gameweek gives one link per
  rival, at most :data:`MAX_LINKS`;
* the zonal (Understat shots) store is readable, the outlook's team has shots
  of its own in it, and the rival has a defensive profile there whose top
  weak zone is at least ``marginal`` (``zonal_weakness.weakness_strength``) --
  "no weak zone" would open a card with no opportunity to show.

Europe/cup matches never reach this list: the outlook series holds Premier
League fixtures only. A shared answer has no chat to send to; the UI hides
the link there, as it does the player card's pills.

Wire: ``zonal_links`` on the get_fixture_outlook output,
``[{"label": str, "send_text": str}]``, hidden from the model. Never raises:
any failure means no link.
"""
from __future__ import annotations

import logging
from typing import Any

from .locale_types import Locale, bootstrap_locale
from .player_signals import team_zone_link

_LOG = logging.getLogger("fpl_grounded_assistant.fixture_cell_zonal")

#: A double gameweek offers one link per rival, never more than this.
MAX_LINKS: int = 2


def _has_shots(shots: Any, store_team: str) -> bool:
    teams = {str(t).lower() for t in shots["shooting_team"].unique()}
    return store_team.strip().lower() in teams


def _rival_has_weak_zone(shots: Any, store_team: str, locale: Locale) -> bool:
    from .zonal_weakness import get_zonal_weakness, weakness_strength  # noqa: PLC0415

    weakness = get_zonal_weakness(store_team, store=shots, locale=locale)
    return weakness.get("status") == "ok" and weakness_strength(weakness.get("weakest_zones") or []) != "none"


def match_zonal_links(
    outlook: dict[str, Any],
    team: dict[str, Any],
    bootstrap: dict[str, Any],
    *,
    store: Any = None,
) -> list[dict[str, str]]:
    """The links for a one-gameweek *outlook* of *team* (a bootstrap team row); ``[]`` when none applies.

    *store* is the zonal shots store seam (``zonal_weakness._load_shots``: None = the owned store). Never raises.
    """
    try:
        series = outlook.get("series") or []
        if len(series) != 1:
            return []
        rivals: list[str] = []
        for fx in series[0].get("fixtures") or []:
            short = str((fx or {}).get("opponent_short") or "")
            if short and short not in rivals:
                rivals.append(short)
        if not rivals:
            return []

        from .zonal_weakness import _load_shots  # noqa: PLC0415
        from .zonal_weakness_tool import _to_store_team  # noqa: PLC0415

        shots = _load_shots(store)
        if shots is None or not _has_shots(shots, _to_store_team(str(team.get("short_name") or ""), bootstrap)):
            return []
        locale = bootstrap_locale(bootstrap)
        teams = {str(tm.get("short_name")): tm for tm in bootstrap.get("teams") or [] if isinstance(tm, dict)}
        out: list[dict[str, str]] = []
        for short in rivals[:MAX_LINKS]:
            opp = teams.get(short)
            if opp is None or not _rival_has_weak_zone(shots, _to_store_team(short, bootstrap), locale):
                continue
            link = team_zone_link(team, opp, locale)
            if link:
                out.append(link)
        return out
    except Exception as exc:  # noqa: BLE001
        _LOG.info("fixture_cell_zonal: links dropped (%s)", type(exc).__name__)
        return []
