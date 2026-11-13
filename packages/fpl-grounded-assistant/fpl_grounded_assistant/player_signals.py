"""
fpl_grounded_assistant.player_signals
=====================================
The player card's way past the first question (Leo, 2026-11-12): the verdict
says the fact, a pill under «EXPLORAR» opens the card that explains it.

Two pieces, both deterministic (no LLM; the model is only paid for on tap):

``position_fact``
    The data for the verdict's position line («Juega de extremo · 6 de 6»,
    evidence «J5–J10»). The SAME count as the position card the pill opens
    (get_position_changes, Leo 2026-11-13): his club's latest
    ``position_changes.DEFAULT_LIMIT`` matches, and
    ``position_changes.fpl_position_gap`` over them (the line he started on
    most, more than half of his starts, is not his FPL line). Named by the
    role word when his starts on that line agree on a role, else by the line
    word. Read from the per-build lineup index the fixture strip already
    keeps (player_strip_axis), so the card waits for nothing; while that
    index is being built the line is simply absent.

``signals_from_conclusions``
    The «Explorar» pills, named by their destination (`Posición ›`). A pill
    shows iff its verdict line was emitted -- after the verdict's cap of 3 --
    so the two can never disagree. Tap -> «¿En qué posición juega X?»
    (get_position_changes: pitch). No fixtures pill: the strip already is
    that; no zones pill: the card's own «Zonas» section already shows the pitch.

``zone_signal`` / ``team_zone_link``
    The team-level zonal question, reached from where the matchup is shown
    (Leo 2026-11-13): «Quién del {club} explota al {rival} ›» -> «¿Qué
    jugadores del {club} pueden explotar las zonas débiles del {rival}?»
    (get_zonal_opportunity, scoped to the club by naming it). On the player
    card it closes the «Zonas» section, only when a row there is a favourable
    matchup (the nearest one); the fixture-cell answer reuses
    ``team_zone_link`` (fixture_cell_zonal.py).

Every threshold lives in the block below: proposals for Leo to tune.

Wire shape (``signals`` at the top level of the snapshot output, hidden from
the model): ``[{"kind": "position"|"zone", "label": str, "send_text": str}]``;
the UI draws ``position`` under «Explorar» and ``zone`` at the end of «Zonas».
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

#: Position line: fewer starts in the window than this and the line never shows (the card itself needs 2).
POSITION_MIN_STARTS: int = 3

KIND_POSITION = "position"
KIND_ZONE = "zone"
#: Verdict key -> pill kind. Order of the pills = order of the verdict lines.
_PILL_FOR_CONCLUSION = {"position": KIND_POSITION}
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


def position_from_window(element: dict[str, Any], window: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """``{"role": word}`` or ``{"line": FPL line}``, plus ``starts`` / ``games`` (the card's «6/6») and
    ``gw_from`` / ``gw_to`` (the gameweeks of his starts, the card's «J5–J10»), or None.

    *window* is his position-card window (``position_changes.recent_windows_by_element``): records with
    ``gameweek``, ``player_status`` and ``slot``, oldest first.
    """
    from football_intelligence.position_changes import fpl_position_gap, played_line  # noqa: PLC0415

    if not isinstance(window, list):
        return None
    records = [m for m in window if isinstance(m, dict)]
    gap = fpl_position_gap(element.get("element_type"), records)
    if gap is None or gap["of"] < POSITION_MIN_STARTS:
        return None
    started = [m for m in records if m.get("player_status") == "started" and m.get("slot")]
    words = Counter(_role_word(m["slot"]) for m in started if played_line(m["slot"]) == gap["played_line"])
    named: dict[str, Any] = (
        {"role": next(iter(words))} if len(words) == 1 and None not in words else {"line": gap["played_line"]}
    )
    out = {**named, "starts": gap["starts"], "games": gap["of"]}
    gws = [m["gameweek"] for m in started if isinstance(m.get("gameweek"), int)]
    if gws:
        out.update(gw_from=min(gws), gw_to=max(gws))
    return out


def position_fact(element: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any] | None:
    """The verdict's position line data from the per-build lineup index, or None. Never raises."""
    try:
        from .player_strip_axis import position_window_for  # noqa: PLC0415

        return position_from_window(element, position_window_for(int(element["id"]), bootstrap))
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


def team_zone_link(own: dict[str, Any], opp: dict[str, Any], locale: Locale) -> dict[str, str] | None:
    """``{"label", "send_text"}`` for the team zonal question: *own*'s players against *opp*'s weak zones.

    *own* / *opp* are bootstrap team rows. The label names the destination with the short codes («Quién del BHA
    explota al HUL»); the question names the full clubs, as get_zonal_opportunity's scope inference reads them.
    """
    if not own.get("name") or not opp.get("name") or not own.get("short_name") or not opp.get("short_name"):
        return None
    if own.get("id") == opp.get("id"):
        return None
    return {
        "label": t("signals.zone.link", locale, team=own["short_name"], opp=opp["short_name"]),
        "send_text": t("signals.zone.ask", locale, team=own["name"], opp=opp["name"]),
    }


def zone_signal(element: dict[str, Any], zonal: Any, bootstrap: dict[str, Any]) -> dict[str, str] | None:
    """The «Zonas» section's closing link: the nearest FAVOURABLE row of the card's own ``zonal`` block, or None
    (no block, no favourable row, unknown club). Never raises."""
    try:
        if not isinstance(zonal, dict):
            return None
        rival = next(
            (str(fx.get("opponent_short") or "") for fx in zonal.get("fixtures") or []
             if isinstance(fx, dict) and fx.get("status") == "favorable" and fx.get("opponent_short")),
            None,
        )
        if not rival:
            return None
        teams = [tm for tm in bootstrap.get("teams") or [] if isinstance(tm, dict)]
        own = next((tm for tm in teams if tm.get("id") == element.get("team")), None)
        opp = next((tm for tm in teams if tm.get("short_name") == rival), None)
        if own is None or opp is None:
            return None
        link = team_zone_link(own, opp, bootstrap_locale(bootstrap))
        return {"kind": KIND_ZONE, **link} if link else None
    except Exception as exc:  # noqa: BLE001
        _LOG.info("player_signals: zone link dropped (%s)", type(exc).__name__)
        return None


def signals_from_conclusions(
    element: dict[str, Any],
    conclusions: list[dict[str, Any]],
    bootstrap: dict[str, Any],
) -> list[dict[str, str]]:
    """One «Explorar» pill per EMITTED verdict line that has a deeper card, in the verdict's order. Never raises."""
    locale = bootstrap_locale(bootstrap)
    out: list[dict[str, str]] = []
    try:
        wanted = [(c, _PILL_FOR_CONCLUSION[c.get("key")]) for c in conclusions or []
                  if isinstance(c, dict) and c.get("key") in _PILL_FOR_CONCLUSION]
        if not wanted:
            return []
        name = _question_name(element, bootstrap)
        for _conclusion, kind in wanted:
            # A question that would not find him again is worse than no pill.
            ask = t("signals.position.ask", locale, player=name) if name else None
            if ask:
                out.append({"kind": kind, "label": t(f"signals.pill.{kind}", locale), "send_text": ask})
    except Exception as exc:  # noqa: BLE001
        _LOG.info("player_signals: pills dropped (%s)", type(exc).__name__)
    return out
