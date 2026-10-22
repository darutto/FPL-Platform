"""Lineup grid semantics shared by the trial checks and the licensed matchday store (CONTRACT.md "Lineup grid semantics")."""
from __future__ import annotations


def grid_side(grid_slot: str | None, row_width: int, is_home: bool) -> str | None:
    """left / right of a grid cell, or None when the cell is not on a touchline edge.

    ``row:col`` is absolute along the touchline: col 1 is the home team's right and the highest col its
    left; the away team is mirrored. Only the first and last column of a row of at least three say a side;
    the goalkeeper's row says none.
    """
    if not grid_slot or ":" not in grid_slot or row_width < 3:
        return None
    try:
        row, col = (int(x) for x in grid_slot.split(":"))
    except ValueError:
        return None
    if row == 1 or col not in (1, row_width):
        return None
    at_col_one = "right" if is_home else "left"
    at_last = "left" if is_home else "right"
    return at_col_one if col == 1 else at_last
