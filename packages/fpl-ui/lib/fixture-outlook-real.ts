/**
 * fixture-outlook-real — the interim /fixtures data seam (Track D).
 *
 * Real 2025–26 season fixtures + results (via fpl-historical), run through
 * the SAME band/run-detection engine the live tool uses (see
 * packages/fpl-grounded-assistant/scripts/export_real_season_fixture_outlook.py
 * — it loads fixture_outlook.py directly, no reimplementation). Real
 * opponents, real venues, real gameweek order; only the *strength inputs*
 * are a single end-of-capture snapshot rather than week-by-week evolving
 * values, so treat the season as if strength were constant throughout —
 * a known simplification, not fabricated data.
 *
 * Manual backtesting: since the season is finished, real results (scores)
 * exist in fpl-historical's fixtures.parquet — ask directly ("how did
 * Arsenal's GW10 home game actually go?") and the answer comes from that
 * real data, not from anything rendered here.
 *
 * Swap point for when the new season's live fixtures exist: replace this
 * module's import in FixturesBoard with a live get_fixture_outlook fetch —
 * same FixtureOutlookMeta shape, so nothing else changes.
 */
import type { FixtureAxis, FixtureOutlookMeta } from './types';
import real from './data/fixture-outlook-2025-26.json';

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
