"""Lineup grid semantics shared by the trial checks and the licensed matchday store (CONTRACT.md "Lineup grid semantics")."""
from __future__ import annotations


def grid_row(grid_slot: str | None) -> int | None:
    """The row of a ``row:col`` cell, or None when it does not parse."""
    if not grid_slot or ":" not in grid_slot:
        return None
    try:
        return int(grid_slot.split(":")[0])
    except ValueError:
        return None


def line_depth(grid_slot: str | None, formation: str | None) -> float | None:
    """How far up the pitch a cell sits, 0.0 (the back line) to 1.0 (the front line), relative to the formation.

    Row 1 is the goalkeeper, so a formation with N outfield lines (``4-2-3-1`` has four) uses rows 2..N+1 and the
    depth is ``(row - 2) / (N - 1)``. Rows are numbered per formation, so the same raw row means different places in
    ``4-2-3-1`` and ``4-3-3``; only this normalised depth is comparable across formations, and only roughly (a line
    of 3 and a line of 5 are both "one line"). None when the formation or the cell does not parse, the cell is the
    goalkeeper's, or the row lies outside the formation's lines.
    """
    row = grid_row(grid_slot)
    try:
        lines = [int(x) for x in str(formation).split("-")] if formation else []
    except ValueError:
        return None
    if row is None or len(lines) < 2 or any(n < 1 for n in lines) or not 2 <= row <= len(lines) + 1:
        return None
    return (row - 2) / (len(lines) - 1)


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
