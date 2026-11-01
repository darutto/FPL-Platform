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
