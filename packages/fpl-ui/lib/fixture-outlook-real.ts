/**
 * fixture-outlook-real — the /fixtures data seam (Track D).
 *
 * Real 2026–27 season fixtures + FDR run through the SAME run-detection /
 * verdict engine the live tool uses (see
 * packages/fpl-grounded-assistant/scripts/export_real_season_fixture_outlook.py
 * — it loads fixture_outlook.py directly, no reimplementation). Real
 * opponents, real venues, real gameweek order.
 *
 * Difficulty signal — the asymmetric recipe: the attack axis bands from FPL's
 * own FDR, the defence axis from FDR refined by the opponent's walk-forward
 * attacking form. That refinement needs played gameweeks, so a bundle exported
 * on launch day (`--season-start`) has both axes on FDR and the axis switcher
 * does nothing. That is a real state the bundle now DECLARES rather than
 * hides: `generation.axes_separated`, measured from the output itself.
 *
 * Coverage: the bundle spans EVERY scheduled gameweek, not a window sized off
 * the day it was built. `generation.covers_gameweeks` states the span, read
 * back off the emitted series rather than copied from the requested horizon.
 *
 * Refresh cadence: the `Regenerate /fixtures outlook bundle` workflow runs
 * weekly after the gameweek closes (the parquet lives in R2, not on anyone's
 * laptop). Regeneration now buys fresher FORM and a truthful
 * `gameweeks_played`; it is no longer what keeps the table from emptying.
 * Same FixtureOutlookMeta shape throughout, so nothing else changes.
 */
import type {
  FixtureAxis,
  FixtureOutlookGeneration,
  FixtureOutlookMeta,
} from './types';
import real from './data/fixture-outlook-2026-27.json';

type RealBundle = Record<FixtureAxis, Record<string, FixtureOutlookMeta>> & {
  generation?: FixtureOutlookGeneration;
};

const REAL_SEASON_DATA = real as unknown as RealBundle;

/**
 * The horizons the SELECTOR offers. Not a property of the data any more.
 *
 * The bundle used to ship one precomputed bucket per entry here, and the board
 * read only the largest. That coupled how far the file reached to which button
 * was pressed, and both were measured from gameweek 1 while the screen's window
 * follows the live gameweek — so coverage shrank by one column a week. The
 * bundle now carries the whole season and these are purely window widths.
 */
export const REAL_SEASON_HORIZONS = [5, 8, 10] as const;

/**
 * The bundle's own account of how it was built, or null on a bundle exported
 * before the block existed. Null is not "fine" — the board says so on screen.
 */
export const REAL_SEASON_GENERATION: FixtureOutlookGeneration | null =
  REAL_SEASON_DATA.generation ?? null;

/**
 * The full-season outlook for one axis — every scheduled gameweek, from which
 * the board slices whatever window the reader asked for.
 */
export function buildRealSeasonOutlook(axis: FixtureAxis): FixtureOutlookMeta {
  const buckets = REAL_SEASON_DATA[axis];
  const keys = buckets ? Object.keys(buckets) : [];
  if (keys.length !== 1) {
    throw new Error(
      `Expected exactly one full-season bucket for axis="${axis}", found ` +
        `[${keys.join(', ')}]. Regenerate the bundle with the "Regenerate ` +
        `/fixtures outlook bundle" workflow.`,
    );
  }
  return buckets[keys[0]];
}
