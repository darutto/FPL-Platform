/**
 * How many gameweeks, and how many team columns, the Calendar shows for the
 * width it has. Pure so the rule can be tested without a browser.
 *
 * Cells never stretch: a gameweek always costs GW_CELL_PX, so a wider board
 * gets a longer window and/or more team columns, never bigger cells.
 */

/** Space one gameweek cell needs in a ticker row (cell + gap), measured from the rendered row. */
export const GW_CELL_PX = 78;
/** Gap between team columns. */
export const ROW_GAP_PX = 40;
/** Window widths the selector offers; 12 exists only in the wide workspace. */
export const WINDOW_OPTIONS = [5, 8, 10, 12] as const;
/** Window sizes worth splitting into columns, largest first. */
const TWO_COLUMN_WINDOWS = [12, 10, 8] as const;

/** Team columns of `horizon` gameweeks that fit in `width` (at least one). */
export function rowColumns(width: number, horizon: number): number {
  return Math.max(1, Math.floor((width + ROW_GAP_PX) / (horizon * GW_CELL_PX + ROW_GAP_PX)));
}

/**
 * Largest window that gives two team columns (12, then 10, then 8 gameweeks);
 * when even 2 x 8 does not fit, one column with the largest window that fits.
 */
export function fitFixtureWindow(width: number): { horizon: number; columns: number } {
  for (const horizon of TWO_COLUMN_WINDOWS) {
    const columns = rowColumns(width, horizon);
    if (columns >= 2) return { horizon, columns };
  }
  const room = Math.floor(width / GW_CELL_PX);
  const horizon = WINDOW_OPTIONS.filter((h) => h <= room).at(-1) ?? WINDOW_OPTIONS[0];
  return { horizon, columns: 1 };
}
