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
 * Refresh cadence: re-run the export's default (recipe) path over the season's
 * owned-store parquet — the `Regenerate /fixtures outlook bundle` workflow does
 * exactly that, since the parquet lives in R2 rather than on anyone's laptop.
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

/** Available horizons — matches what the export script precomputed. */
export const REAL_SEASON_HORIZONS = [5, 8, 10] as const;

/**
 * The bundle's own account of how it was built, or null on a bundle exported
 * before the block existed. Null is not "fine" — the board says so on screen.
 */
export const REAL_SEASON_GENERATION: FixtureOutlookGeneration | null =
  REAL_SEASON_DATA.generation ?? null;

export function buildRealSeasonOutlook(axis: FixtureAxis, horizon: number): FixtureOutlookMeta {
  const bucket = REAL_SEASON_DATA[axis]?.[String(horizon)];
  if (!bucket) {
    throw new Error(
      `No real-season fixture outlook for axis="${axis}" horizon=${horizon}. ` +
        `Available horizons: ${REAL_SEASON_HORIZONS.join(', ')}.`,
    );
  }
  return bucket;
}
