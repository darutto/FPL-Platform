"""
fpl_grounded_assistant.formatting
=================================
Shared, dependency-free display formatters.

Extracted so the text renderer (``renderer.py``) and the structured-card
composers (``atomic_tool_cards.py``) format the *same* raw numeric values
*identically* — a card and its prose fallback can never disagree numerically
because they call one function, not two mirrored copies.

This module must import nothing from the rest of the package (keep it a leaf
so any module can use it without an import cycle).
"""
from __future__ import annotations

from typing import Any


def format_metric_value(value: Any) -> str:
    """Format a numeric metric value for display.

    A whole-valued float renders as an integer (``17.0 -> "17"``); a fractional
    float keeps two decimals (``0.573 -> "0.57"``). Non-float values (ints,
    strings) are stringified as-is. Behaviour is byte-identical to the logic
    previously inlined in ``renderer._render_rank_players_by_metric``.

    >>> format_metric_value(239.0)
    '239'
    >>> format_metric_value(0.86)
    '0.86'
    >>> format_metric_value(17)
    '17'
    """
    if isinstance(value, float) and value == int(value) and abs(value) < 1e6:
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
