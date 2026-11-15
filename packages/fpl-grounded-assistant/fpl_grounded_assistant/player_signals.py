"""
fpl_grounded_assistant.player_signals
=====================================
The player card's way past the first question (Leo, 2026-11-12): the verdict
says the fact, a pill under «EXPLORAR» opens the card that explains it.

Two pieces, both deterministic (no LLM; the model is only paid for on tap):

``position_fact``
    The data for the verdict's position line («Juega de extremo · 8 de 10»):
    in his latest ``POSITION_RECENT_STARTS`` starts with a stored lineup, at
    least ``POSITION_MIN_OFF_LINE_SHARE`` were off his FPL line (with at least
    ``POSITION_MIN_STARTS`` starts). Named by the role word when those
    off-line starts agree on a role, else by the line word when they agree on
    a line, else no line at all. Read from the per-build lineup index the
    fixture strip already keeps (player_strip_axis), so the card waits for
    nothing; while that index is being built the line is simply absent.

``signals_from_conclusions``
    The pills, named by their destination (`Posición ›` / `Zonas ›`). A pill
    shows iff its verdict line was emitted -- after the verdict's cap of 3 --
    so the two can never disagree. Tap -> the pill's question:

    * position -> «¿En qué posición juega X?» (get_position_changes: pitch);
    * zone     -> «¿Qué jugadores del {club} pueden explotar las zonas débiles
      del {rival}?» for the nearest favourable rival of the zonal line
      (get_zonal_opportunity, scoped to his club).

    No fixtures pill: the strip already is that.

Every threshold lives in the block below: proposals for Leo to tune.

Wire shape (``signals`` at the top level of the snapshot output, hidden from
the model): ``[{"kind": "position"|"zone", "label": str, "send_text": str}]``.
Never raises: a failure drops one item, never the snapshot.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from .catalogue import t
from .locale_types import Locale, bootstrap_locale

_LOG = logging.getLogger("fpl_grounded_assistant.player_signals")

# ---------------------------------------------------------------------------
# Thresholds (proposals -- tune here and only here)
# ---------------------------------------------------------------------------

#: Position line: how many of his latest starts with a stored lineup are read ("N de 10").
POSITION_RECENT_STARTS: int = 10
#: Position line: fewer starts than this and the line never shows.
POSITION_MIN_STARTS: int = 3
#: Position line: share of those starts that must be off his FPL line (0.5 = half or more).
POSITION_MIN_OFF_LINE_SHARE: float = 0.5

KIND_POSITION = "position"
KIND_ZONE = "zone"
#: Verdict key -> pill kind. Order of the pills = order of the verdict lines.
_PILL_FOR_CONCLUSION = {"position": KIND_POSITION, "zonal": KIND_ZONE}

_FPL_LINES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_WIDE_MIDFIELD = ("Left Midfield", "Right Midfield")

#: Provider ``detailed_position`` -> the role word of the line (worded by the UI).
_ROLE_WORD = {
    "Left Midfield": "winger", "Right Midfield": "winger",
    "Attacker": "forward", "Centre Forward": "forward",
    "Attacking Midfield": "attacking_mid", "Central Midfield": "central_mid",
    "Defensive Midfield": "holding_mid",
    "Centre Back": "centre_back", "Left Back": "full_back", "Right Back": "full_back",
}


# ---------------------------------------------------------------------------
# Position line data
# ---------------------------------------------------------------------------

def _role_word(slot: dict[str, Any]) -> str | None:
    role = slot.get("detailed_position")
    if role in _WIDE_MIDFIELD and str(slot.get("formation") or "").startswith("3"):
        return "wing_back"
    return _ROLE_WORD.get(str(role)) if role else None


def position_from_starts(element: dict[str, Any], starts: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """``{"role": word}`` or ``{"line": FPL line}``, plus ``starts`` (off-line) and ``games`` (read), or None.

    *starts* are his starting slots, oldest first (``detailed_position``, ``side``, ``formation``).
    """
    from football_intelligence.position_changes import played_line  # noqa: PLC0415

    fpl = _FPL_LINES.get(element.get("element_type"))  # type: ignore[arg-type]
    if fpl is None or fpl == "GKP" or not isinstance(starts, list):
        return None
    recent = [s for s in starts if isinstance(s, dict)][-POSITION_RECENT_STARTS:]
    if len(recent) < POSITION_MIN_STARTS:
        return None
    off_line = [s for s in recent if (line := played_line(s)) is not None and line not in (fpl, "GKP")]
    if not off_line or len(off_line) < POSITION_MIN_OFF_LINE_SHARE * len(recent):
        return None
    words = Counter(_role_word(s) for s in off_line)
    lines = Counter(played_line(s) for s in off_line)
    if len(words) == 1 and None not in words:
        named: dict[str, Any] = {"role": next(iter(words))}
    elif len(lines) == 1:
        named = {"line": next(iter(lines))}  # several roles, one line: the line is true, a role would not be
    else:
        return None
    return {**named, "starts": len(off_line), "games": len(recent)}


def position_fact(element: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any] | None:
    """The verdict's position line data from the per-build lineup index, or None. Never raises."""
    try:
        from .player_strip_axis import recent_starts_for  # noqa: PLC0415

        return position_from_starts(element, recent_starts_for(int(element["id"]), bootstrap))
    except Exception as exc:  # noqa: BLE001
        _LOG.info("player_signals: position line dropped (%s)", type(exc).__name__)
        return None


# ---------------------------------------------------------------------------
# Pills
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


def _zone_question(element: dict[str, Any], conclusion: dict[str, Any], bootstrap: dict[str, Any], locale: Locale) -> str | None:
    """The zonal card question for the line's FIRST rival (the zonal line lists them nearest first)."""
    opponents = (conclusion.get("params") or {}).get("opponents") or []
    if not opponents:
        return None
    teams = [tm for tm in bootstrap.get("teams") or [] if isinstance(tm, dict)]
    own = next((tm for tm in teams if tm.get("id") == element.get("team")), None)
    opp = next((tm for tm in teams if tm.get("short_name") == opponents[0]), None)
    if not own or not opp or not own.get("name") or not opp.get("name"):
        return None
    return t("signals.zone.ask", locale, team=own["name"], opp=opp["name"])


def signals_from_conclusions(
    element: dict[str, Any],
    conclusions: list[dict[str, Any]],
    bootstrap: dict[str, Any],
) -> list[dict[str, str]]:
    """One pill per EMITTED verdict line that has a deeper card, in the verdict's order. Never raises."""
    locale = bootstrap_locale(bootstrap)
    out: list[dict[str, str]] = []
    try:
        wanted = [(c, _PILL_FOR_CONCLUSION[c.get("key")]) for c in conclusions or []
                  if isinstance(c, dict) and c.get("key") in _PILL_FOR_CONCLUSION]
        if not wanted:
            return []
        name = _question_name(element, bootstrap)
        for conclusion, kind in wanted:
            if kind == KIND_POSITION:
                # A question that would not find him again is worse than no pill.
                ask = t("signals.position.ask", locale, player=name) if name else None
            else:
                ask = _zone_question(element, conclusion, bootstrap, locale)
            if ask:
                out.append({"kind": kind, "label": t(f"signals.pill.{kind}", locale), "send_text": ask})
    except Exception as exc:  # noqa: BLE001
        _LOG.info("player_signals: pills dropped (%s)", type(exc).__name__)
    return out
