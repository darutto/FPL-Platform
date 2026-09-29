"""Jev (TypeSafe System One) tool router -- i115. Not wired to any serving path.

See :mod:`.router` for the contract and :mod:`.criteria` for the ported,
measured option texts.
"""
from .router import (
    CATALOG_EXCEPTIONS,
    MENU_EXCLUDED,
    PATH_CHIP,
    PATH_ESCALATE,
    JevDecision,
    build_menu,
    build_request,
    decide,
    route,
)

__all__ = [
    "CATALOG_EXCEPTIONS",
    "MENU_EXCLUDED",
    "PATH_CHIP",
    "PATH_ESCALATE",
    "JevDecision",
    "build_menu",
    "build_request",
    "decide",
    "route",
]
