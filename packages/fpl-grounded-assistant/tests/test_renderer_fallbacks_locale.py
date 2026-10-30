"""Fallback texts (used when a tool result has no message of its own): en unchanged, es Spanish."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.renderer import render

_CASES = [
    ("get_chip_advice", {"status": "error"}, "Error (error): An unexpected chip advice error occurred.", "Error (error): Ocurrió un error inesperado con el consejo de chips."),
    ("get_transfer_advice", {"status": "error"}, "Error (error): An unexpected transfer advice error occurred.", "Error (error): Ocurrió un error inesperado con el consejo de traspasos."),
    ("get_transfer_advice", {"status": "not_found", "error_player": "Foo"}, "Could not resolve player 'Foo'.", "No se pudo identificar al jugador 'Foo'."),
    ("get_player_form", {"status": "error"}, "Error (error): An unexpected player form error occurred.", "Error (error): Ocurrió un error inesperado con la forma del jugador."),
    ("get_player_form", {"status": "missing_context"}, "Player match history unavailable.", "El historial de partidos del jugador no está disponible."),
    ("get_price_changes", {"status": "empty"}, "No price-change data available.", "No hay datos de cambios de precio."),
    ("get_price_changes", {"status": "error"}, "Error (error): An unexpected price changes error occurred.", "Error (error): Ocurrió un error inesperado con los cambios de precio."),
]


@pytest.mark.parametrize("tool,output,en,es", _CASES)
def test_fallback_is_paired(tool, output, en, es):
    assert render(tool, output, locale="en") == en
    assert render(tool, output, locale="es") == es
