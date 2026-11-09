"""
fpl_grounded_assistant.player_signals
=====================================
«Señales» for the player card: up to ``MAX_SIGNALS`` tappable pills at the foot
of the ``player_snapshot`` card. Each one says, in two or three words, that
another card has something to say about THIS player, and carries the question
that opens that card. Deterministic, no LLM: the model's text is only paid for
when the user taps.

Two signals in this version, in this order:

``position``
    He started in a role off his FPL line in at least half of his latest
    stored starts. Reuses ``get_position_changes`` (the licensed lineup store,
    ``played_line`` and the FPL line, PRs #604-#607); offered only when that
    tool is (``FOOTBALL_INTELLIGENCE_ENABLED``). Label «Extremo 2 de 4» /
    "Winger 2 of 4". Tap -> the position-changes card.

``zone``
    A rival inside the zonal window (pending matches of the next
    ``WINDOW_GWS`` gameweeks) concedes above average in a zone where this
    player concentrates his own xG. Reuses the snapshot's ``zonal`` section
    (Bloque 10), so the existing rules hold unchanged: the zone-share
    threshold and the minimum-shots rule of ``zonal_weakness``. Only the
    nearest such rival is shown. Label «Banda débil BRE» / "BRE weak flank".
    Tap -> the zonal card (``get_zonal_opportunity``), scoped to his club.

There is no fixtures signal: it repeated the card's fixture strip.

Every threshold lives in the block of constants below. They are proposals
for Leo to tune, not measured values.

Wire shape (``signals`` at the top level of the snapshot output, hidden from
the model): ``[{"kind": "position"|"zone", "label": str, "send_text": str}]``.
An empty result leaves the key out, and the card exactly as it was.
Never raises: a failure drops one signal, never the snapshot.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any, Callable

from .catalogue import t
from .locale_types import Locale, bootstrap_locale
from .player_snapshot_zonal import WINDOW_GWS

_LOG = logging.getLogger("fpl_grounded_assistant.player_signals")

# ---------------------------------------------------------------------------
# Thresholds (proposals -- tune here and only here)
# ---------------------------------------------------------------------------

#: At most this many pills on one card.
MAX_SIGNALS: int = 3
#: Position: how many of his latest starts with a stored lineup are read.
POSITION_RECENT_STARTS: int = 5
#: Position: fewer starts than this and the signal never shows.
POSITION_MIN_STARTS: int = 3
#: Position: share of those starts that must be off his FPL line (0.5 = half or more).
POSITION_MIN_OFF_LINE_SHARE: float = 0.5
#: Zone: gameweeks ahead a rival may be in. Pinned to the zonal section's own
#: window, which is what the signal reads; the zone-share threshold and the
#: minimum shots come from ``zonal_weakness`` unchanged.
ZONE_WINDOW_GWS: int = WINDOW_GWS

KIND_POSITION = "position"
KIND_ZONE = "zone"

_FPL_LINES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_WIDE_MIDFIELD = ("Left Midfield", "Right Midfield")

#: Provider ``detailed_position`` -> the short role word of the pill.
_ROLE_WORD = {
    "Left Midfield": "winger", "Right Midfield": "winger",
    "Attacker": "forward", "Centre Forward": "forward",
    "Attacking Midfield": "attacking_mid", "Central Midfield": "central_mid",
    "Defensive Midfield": "holding_mid",
    "Centre Back": "centre_back", "Left Back": "full_back", "Right Back": "full_back",
}


# ---------------------------------------------------------------------------
# Name used in the questions
# ---------------------------------------------------------------------------

def _question_name(element: dict[str, Any], bootstrap: dict[str, Any]) -> str | None:
    """The shortest name that resolves back to THIS player: web_name, else the full name, else None."""
    from fpl_tool_contract import tool_resolve_player  # noqa: PLC0415

    full = f"{element.get('first_name') or ''} {element.get('second_name') or ''}".strip()
    for name in (str(element.get("web_name") or "").strip(), full):
        if not name:
            continue
        try:
            resolved = tool_resolve_player(name, bootstrap)
        except Exception:  # noqa: BLE001
            continue
        if resolved.get("status") == "ok" and resolved.get("player_id") == element.get("id"):
            return name
    return None


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

def _role_word(slot: dict[str, Any]) -> str | None:
    role = slot.get("detailed_position")
    if role in _WIDE_MIDFIELD and str(slot.get("formation") or "").startswith("3"):
        return "wing_back"
    return _ROLE_WORD.get(str(role)) if role else None


def position_signal(
    element: dict[str, Any],
    changes: dict[str, Any] | None,
    name: str,
    locale: Locale,
) -> dict[str, str] | None:
    """The position pill from a ``get_position_changes`` result, or None."""
    from football_intelligence.position_changes import played_line  # noqa: PLC0415

    fpl = _FPL_LINES.get(element.get("element_type"))  # type: ignore[arg-type]
    if fpl is None or fpl == "GKP" or not isinstance(changes, dict) or changes.get("status") != "ok":
        return None
    starts = [
        m["slot"] for m in changes.get("matches") or []
        if isinstance(m, dict) and m.get("player_status") == "started" and isinstance(m.get("slot"), dict)
    ][-POSITION_RECENT_STARTS:]
    if len(starts) < POSITION_MIN_STARTS:
        return None
    off_line = [s for s in starts if (line := played_line(s)) is not None and line not in (fpl, "GKP")]
    if not off_line or len(off_line) < POSITION_MIN_OFF_LINE_SHARE * len(starts):
        return None
    words = Counter(_role_word(s) for s in off_line)
    lines = Counter(played_line(s) for s in off_line)
    if len(words) == 1 and None not in words:
        key = f"signals.role.{next(iter(words))}"
    elif len(lines) == 1:
        # Several roles, one line («medio»): the line is still true, the role would not be.
        key = f"signals.line.{next(iter(lines))}"
    else:
        return None
    return {
        "kind": KIND_POSITION,
        "label": t("signals.position.label", locale, role=t(key, locale), n=len(off_line), m=len(starts)),
        "send_text": t("signals.position.ask", locale, player=name),
    }


#: The lineup read costs ~0.5-1 s (it parses the whole licensed lineup table),
#: and lineups change once per matchday: keep each player's result this long.
#: Same lifetime as position_changes_tool's fixture-list cache.
POSITION_CACHE_TTL_S: float = 600.0
_position_cache: dict[int, tuple[float, dict[str, Any] | None]] = {}


def _position_changes(element: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any] | None:
    from .orch_config import is_football_intelligence_enabled  # noqa: PLC0415

    if not is_football_intelligence_enabled():  # the pill would ask for a tool that is not offered
        return None
    from football_intelligence.position_changes import MAX_LIMIT  # noqa: PLC0415

    from .position_changes_tool import run_position_changes  # noqa: PLC0415

    key, now = int(element["id"]), time.monotonic()
    hit = _position_cache.get(key)
    if hit is not None and now - hit[0] < POSITION_CACHE_TTL_S:
        return hit[1]
    result = run_position_changes({"player": key, "matches": MAX_LIMIT}, bootstrap)
    if isinstance(result, dict) and result.get("status") == "ok":  # a store hiccup is not remembered
        _position_cache[key] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------

def zone_signal(
    element: dict[str, Any],
    zonal: dict[str, Any] | None,
    bootstrap: dict[str, Any],
    locale: Locale,
) -> dict[str, str] | None:
    """The zone pill from the snapshot's ``zonal`` section, or None."""
    if not isinstance(zonal, dict):
        return None
    window = zonal.get("window") or {}
    gw_from = window.get("gw_from")
    if not isinstance(gw_from, int):
        return None
    favourable = [
        f for f in zonal.get("fixtures") or []
        if isinstance(f, dict) and f.get("status") == "favorable" and f.get("matches")
        and isinstance(f.get("gameweek"), int) and f["gameweek"] < gw_from + ZONE_WINDOW_GWS
    ]
    if not favourable:
        return None
    nearest = min(favourable, key=lambda f: f["gameweek"])  # stable: first listed wins a tie
    best = max(nearest["matches"], key=lambda m: m.get("delta_vs_avg", 0.0))
    lateral = str(best.get("zone") or "").split(" / ")[-1]
    if lateral not in ("left", "right", "central"):
        return None
    opp_short = str(nearest.get("opponent_short") or "")
    teams = {tm.get("id"): tm for tm in bootstrap.get("teams") or [] if isinstance(tm, dict)}
    team = teams.get(element.get("team")) or {}
    opp = next((tm for tm in teams.values() if tm.get("short_name") == opp_short), None) or {}
    team_name, opp_name = str(team.get("name") or ""), str(opp.get("name") or nearest.get("opponent") or "")
    if not opp_short or not team_name or not opp_name:
        return None
    area = "flank" if lateral in ("left", "right") else "centre"
    return {
        "kind": KIND_ZONE,
        "label": t(f"signals.zone.label_{area}", locale, opp=opp_short),
        "send_text": t("signals.zone.ask", locale, team=team_name, opp=opp_name),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_player_signals(
    element: dict[str, Any],
    player: dict[str, Any],
    bootstrap: dict[str, Any],
    *,
    position_changes: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None = None,
) -> list[dict[str, str]]:
    """Signals for one resolved player, in display order. Never raises.

    ``player`` is the snapshot's player payload (its ``zonal`` section is
    read); ``position_changes`` is the test seam for the licensed lookup.
    """
    locale = bootstrap_locale(bootstrap)
    try:
        name = _question_name(element, bootstrap)
    except Exception:  # noqa: BLE001
        name = None
    if name is None:  # a question that would not find him again is worse than no pill
        return []
    out: list[dict[str, str]] = []
    try:
        changes = (position_changes or _position_changes)(element, bootstrap)
        sig = position_signal(element, changes, name, locale)
        if sig is not None:
            out.append(sig)
    except Exception as exc:  # noqa: BLE001
        _LOG.info("player_signals: position dropped (%s)", type(exc).__name__)
    try:
        sig = zone_signal(element, player.get("zonal"), bootstrap, locale)
        if sig is not None:
            out.append(sig)
    except Exception as exc:  # noqa: BLE001
        _LOG.info("player_signals: zone dropped (%s)", type(exc).__name__)
    return out[:MAX_SIGNALS]
