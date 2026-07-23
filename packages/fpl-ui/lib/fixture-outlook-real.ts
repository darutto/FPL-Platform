/**
 * fixture-outlook-real — the /fixtures data seam (Track D).
 *
 * Real 2026–27 season fixtures + FDR, pulled from the LIVE FPL API the day the
 * season launched and run through the SAME run-detection / verdict engine the
 * live tool uses (see
 * packages/fpl-grounded-assistant/scripts/export_real_season_fixture_outlook.py
 * --season-start — it loads fixture_outlook.py directly, no reimplementation).
 * Real opponents, real venues, real gameweek order.
 *
 * Season-start difficulty: both axes band from FPL's own FDR. Zero games have
 * been played, so the defence-axis FDR+form recipe (the ML0-validated signal)
 * has no rolling form to refine with yet — the defence axis therefore mirrors
 * the attack axis until real results exist, at which point re-running the
 * default (non-`--season-start`) export re-separates the axes.
 *
 * Refresh cadence: re-run `export_real_season_fixture_outlook.py --season-start`
 * to pick up newly-scheduled tail gameweeks (the launch schedule is partial),
 * then switch to the form-refined recipe export once GWs have been played.
 * Same FixtureOutlookMeta shape throughout, so nothing else changes.
 */
import type { FixtureAxis, FixtureOutlookMeta } from './types';
import real from './data/fixture-outlook-2026-27.json';

type RealBundle = Record<FixtureAxis, Record<string, FixtureOutlookMeta>>;

const REAL_SEASON_DATA = real as unknown as RealBundle;

/** Available horizons — matches what the export script precomputed. */
export const REAL_SEASON_HORIZONS = [5, 8, 10] as const;

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
