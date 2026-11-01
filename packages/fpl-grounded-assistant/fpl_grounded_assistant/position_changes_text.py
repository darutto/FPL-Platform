"""Text for a starting slot, shared by the get_position_changes text renderer and its card (B4)."""
from __future__ import annotations

from typing import Any

try:
    from .catalogue import t
    from .locale_types import Locale
except ImportError:  # standalone load of renderer.py (test_renderer_zonal bypasses the package)
    from catalogue import t  # type: ignore[no-redef]
    from locale_types import Locale  # type: ignore[no-redef]

#: Provider position names -> Spanish. English shows the provider's own name; an unknown name passes through.
_DETAILED_POSITION_ES = {
    "Goalkeeper": "Portero", "Centre Back": "Central", "Right Back": "Lateral derecho", "Left Back": "Lateral izquierdo",
    "Defensive Midfield": "Pivote", "Central Midfield": "Mediocentro", "Attacking Midfield": "Mediapunta",
    "Right Midfield": "Banda derecha", "Left Midfield": "Banda izquierda", "Attacker": "Delantero",
    "Centre Forward": "Delantero centro",
}
_SIDE_WORDS = {"en": {"left": "left", "right": "right", "centre": "centre"},
               "es": {"left": "izquierda", "right": "derecha", "centre": "centro"}}


def role_text(role: dict[str, Any] | None, locale: Locale) -> str:
    """'Right Midfield' / 'Banda derecha'; the side is added only when the name does not already carry it."""
    if not role or not role.get("detailed_position"):
        return "?"
    position = str(role["detailed_position"])
    text = _DETAILED_POSITION_ES.get(position, position) if locale == "es" else position
    side = role.get("side")
    if side in ("left", "right") and side not in position.lower() and locale == "en":
        text += f" ({_SIDE_WORDS['en'][side]})"
    elif side in ("left", "right") and locale == "es" and position not in _DETAILED_POSITION_ES:
        text += f" ({_SIDE_WORDS['es'][side]})"
    return text


_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def out_date(since: str, locale: Locale) -> str:
    """'17 Oct' (en) / '17/10' (es) from an ISO date; the text unchanged when it is not one."""
    try:
        year, month, day = (int(p) for p in since[:10].split("-"))
        _ = _MONTHS_EN[month - 1], year
    except (ValueError, IndexError):
        return since
    return f"{day} {_MONTHS_EN[month - 1]}" if locale == "en" else f"{day:02d}/{month:02d}"


def out_text(fpl_out: dict[str, Any], locale: Locale) -> str:
    """'out: knee injury (FPL, 17 Oct)' / 'baja: lesión de rodilla (FPL, 17/10)'. Only ever from a dated FPL notice."""
    return t("renderer.position_changes.out", locale,
             reason=t(f"renderer.position_changes.reason_{fpl_out.get('reason')}", locale),
             date=out_date(str(fpl_out.get("since") or ""), locale))


def slot_row_text(occupants: list[dict[str, Any]] | None, locale: Locale) -> str:
    """'slot: Delap' / 'casilla: Delap'; the closest cell when the formation had no same-role slot. '' when nobody."""
    if not occupants:
        return ""
    names = ", ".join((o.get("player") or {}).get("web_name", "?") for o in occupants)
    closest = any(o.get("match") == "closest" for o in occupants)
    return t("renderer.position_changes.slot_row_closest" if closest else "renderer.position_changes.slot_row", locale, name=names)


def slot_summary_lines(cover: dict[str, Any] | None, player_name: str, locale: Locale) -> list[str]:
    """Summary of who held the usual slot in the matches without him (observed; no cause, no decision)."""
    if not cover:
        return []
    n = int(cover.get("matches_without") or 0)
    if cover.get("status") != "ok":
        return [t("renderer.position_changes.slot_none", locale, player=player_name, n=cover.get("starts_used", 0))]
    occupants = cover.get("occupants") or []
    if not occupants:
        return []
    slot = role_text(cover.get("usual_slot"), locale).lower()
    sep = " y " if locale == "es" else " and "
    parts = [(o.get("player") or {}).get("web_name", "?") + (f" ({o['count']})" if n > 1 else "") for o in occupants]
    names = ", ".join(parts[:-1]) + sep + parts[-1] if len(parts) > 1 else parts[0]
    lines = [t("renderer.position_changes.slot_summary" if n > 1 else "renderer.position_changes.slot_summary_one", locale,
               n=n, player=player_name, slot=slot, names=names)]
    if cover.get("closest_used"):
        lines.append(t("renderer.position_changes.slot_closest", locale))
    if cover.get("small_sample"):
        lines.append(t("renderer.position_changes.slot_small" if n > 1 else "renderer.position_changes.slot_small_one", locale,
                       n=n, player=player_name))
    return lines
