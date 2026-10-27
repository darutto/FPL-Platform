"""Text for a starting slot, shared by the get_position_changes text renderer and its card (B4)."""
from __future__ import annotations

from typing import Any

try:
    from .locale_types import Locale
except ImportError:  # standalone load of renderer.py (test_renderer_zonal bypasses the package)
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
