// Pinned like every suite that reads the bundle: the live file is regenerated weekly (see bundle-pinning-guard).
jest.mock('@/lib/data/fixture-outlook-2026-27.json', () => jest.requireActual('./fixtures/fixture-outlook-2026-27.pinned.json'));

import { buildRealSeasonOutlook } from '../lib/fixture-outlook-real';
import { findSwing, orderBySwing, SWING_THRESHOLDS } from '../lib/fixture-swing';
import type { FixtureOutlookGW, TeamOutlook } from '../lib/types';

/**
 * A season built from per-gameweek band lists: a number is one fixture, an array
 * is a double ([a, b]) or a blank ([]). Gameweeks are numbered from `from`.
 */
type Cell = number | number[];

function season(from: number, cells: Cell[]): FixtureOutlookGW[] {
  return cells.map((cell, i) => {
    const bands = Array.isArray(cell) ? cell : [cell];
    const mean = bands.length ? Math.round(bands.reduce((a, b) => a + b, 0) / bands.length) : null;
    return {
      gameweek: from + i,
      band: mean,
      klass: mean === null ? ('blank' as const) : mean <= 2 ? ('good' as const) : mean >= 4 ? ('bad' as const) : ('neutral' as const),
      is_dgw: bands.length >= 2,
      is_bgw: bands.length === 0,
      fixtures: bands.map((band, j) => ({ opponent_short: `O${i}${j}`, is_home: j === 0, band })),
    };
  });
}

const NOW = 11;
/** The worked examples below are written against a 0.5 threshold; the per-axis defaults are tested on their own. */
const T05 = { threshold: 0.5 };
/** Five played gameweeks (6-10) at the given difficulty, then the upcoming ones from GW11. */
const withPast = (past: number | Cell[], upcoming: Cell[]): FixtureOutlookGW[] =>
  season(6, [...(Array.isArray(past) ? past : [past, past, past, past, past]), ...upcoming]);

describe('findSwing', () => {
  test('finds the first gameweek where the run turns easier and anchors on it', () => {
    // Reference 3.0. From GW14 the run is 1,1,2,2,3 (1.8) and GW14 itself is band 1.
    const swing = findSwing(withPast(3, [3, 3, 3, 1, 1, 2, 2, 3, 3, 2]), NOW, T05);
    expect(swing).toMatchObject({ gameweek: 14, direction: 'easier', inGameweeks: 3 });
    expect(swing?.reference).toBeCloseTo(3.0);
    expect(swing?.lead).toBeCloseTo(1.8);
    expect(swing?.change).toBeCloseTo(-1.2);
  });

  test('finds a harder swing', () => {
    // Reference 2.4. GW13 is a 5 and the run 5,3,3,3,3 averages 3.4.
    const swing = findSwing(withPast([2, 2, 3, 3, 2], [2, 2, 5, 3, 3, 3, 3, 3, 3, 3]), NOW, T05);
    expect(swing).toMatchObject({ gameweek: 13, direction: 'harder', inGameweeks: 2 });
    expect(swing?.change).toBeCloseTo(1.0);
  });

  test('does not call the swing early, where only the rolling average has crossed the threshold', () => {
    // Reference 3.4. From GW13 the run already averages 2.8 or better (Δ -0.6) but GW13 itself is still a 4
    // (no band lower than 3 yet), so no swing there. GW16 is the first gameweek that has genuinely moved.
    const swing = findSwing(withPast([4, 3, 3, 4, 3], [3, 3, 4, 3, 3, 2, 2, 2, 3, 3]), NOW, T05);
    expect(swing?.gameweek).toBe(16);
  });

  test('a change under the threshold is not a swing', () => {
    // Reference 3.2, run from GW15 averages 2.8: Δ -0.4.
    expect(findSwing(withPast([4, 3, 3, 3, 3], [4, 3, 3, 3, 2, 3, 3, 3, 3, 3]), NOW, T05)).toBeNull();
  });

  test('0.5 behaves as 0.6: whole-band averages over five fixtures move in steps of 0.2', () => {
    // Reference 3.0, and GW11 has itself moved a band, so only the size of the change decides.
    // Run 4,4,3,3,3 = 3.4: Δ +0.4 is below the threshold.
    expect(findSwing(withPast(3, [4, 4, 3, 3, 3, 3, 3, 3, 3, 3]), NOW, T05)).toBeNull();
    // Run 4,4,4,3,3 = 3.6: Δ +0.6 is above it, and there is no step between 0.4 and 0.6 to land on.
    expect(findSwing(withPast(3, [4, 4, 4, 3, 3, 3, 3, 3, 3, 3]), NOW, T05)).toMatchObject({ gameweek: 11, direction: 'harder' });
  });

  test('a double adds two fixtures to the run and a blank adds none', () => {
    // Reference 3.0. GW14 is a double (1, 2), so the new run has six fixtures: 1,2,1,2,2,3 = 1.83.
    const doubled = findSwing(withPast(3, [3, 3, 3, [1, 2], 1, 2, 2, 3, 3, 2]), NOW, T05);
    expect(doubled?.gameweek).toBe(14);
    expect(doubled?.lead).toBeCloseTo(11 / 6);
    // Reference 2.8. GW15 is a blank. The run from GW14 is 4,(blank),4,3,3 = four fixtures at 3.5.
    const blanked = findSwing(withPast([3, 3, 3, 2, 3], [3, 3, 3, 4, [], 4, 3, 3, 3, 3]), NOW, T05);
    expect(blanked?.gameweek).toBe(14);
    expect(blanked?.lead).toBeCloseTo(3.5);
  });

  test('a blank is never the swing point', () => {
    // The new run begins at GW13, but GW13 is a blank, so the swing lands on GW14.
    const swing = findSwing(withPast(3, [3, 3, [], 1, 1, 1, 1, 3, 3, 3]), NOW, T05);
    expect(swing?.gameweek).toBe(14);
  });

  test('a double with a mixed-difficulty pair is judged on its mean', () => {
    // Reference 3.0. GW13 is a double 2 and 4 (mean 3), which has not moved a band, so it is skipped;
    // the swing is GW14.
    const swing = findSwing(withPast(3, [3, 3, [2, 4], 1, 1, 1, 3, 3, 3, 3]), NOW, T05);
    expect(swing?.gameweek).toBe(14);
  });

  test('needs enough fixtures behind the new run', () => {
    // Two fixtures left in the data: not enough evidence at the very end.
    const tail = withPast(3, [3, 3, 3, 3, 3, 3, 3, 3, 1, 1]);
    expect(findSwing(tail, NOW, T05)).toBeNull();
    // Three fixtures left is enough.
    const longer = withPast(3, [3, 3, 3, 3, 3, 3, 3, 1, 1, 1]);
    expect(findSwing(longer, NOW, T05)?.gameweek).toBe(18);
  });

  test('needs enough played fixtures for a reference', () => {
    // Season start: nothing has been played, so there is no trailing run to compare with.
    expect(findSwing(season(1, [3, 3, 3, 1, 1, 1, 1, 1, 1, 1]), 1)).toBeNull();
    // Two played fixtures are still too few.
    expect(findSwing(season(9, [3, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]), 11)).toBeNull();
  });

  test('the lookahead stops ten gameweeks out', () => {
    // The change starts at GW21, the first gameweek past GW11 + 10.
    const late = withPast(3, [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 1, 1, 1, 1, 1]);
    expect(findSwing(late, NOW, T05)).toBeNull();
  });

  test('a series with gaps (blank gameweeks dropped by the exporter) is read by gameweek number', () => {
    // GW8 and GW14 are missing entirely, as the exporter may emit them.
    const gappy = withPast(3, [3, 3, 3, 1, 1, 2, 2, 3, 3, 2]).filter((gw) => gw.gameweek !== 8 && gw.gameweek !== 16);
    expect(findSwing(gappy, NOW, T05)?.gameweek).toBe(14);
  });
});

// Real data, pinned: swing has to stay the exception or the Stable group disappears.
describe('swing frequency on the pinned 2026-27 bundle', () => {
  const nows = [9, 12, 15, 18, 21, 24, 27];

  test.each(['attack', 'defence'] as const)('%s: a swing is called for a minority of teams', (axis) => {
    const meta = buildRealSeasonOutlook(axis);
    const counts = nows.map((now) => meta.teams.filter((t) => findSwing(t.series, now, { axis })).length);
    const mean = counts.reduce((a, b) => a + b, 0) / counts.length;
    // 0.5 flagged 12 (attack) and 19 (defence) of 20. The tuned thresholds must stay well under half.
    expect(mean).toBeGreaterThan(1);
    expect(mean).toBeLessThan(9);
    for (const c of counts) expect(c).toBeLessThan(14);
  });
});

describe('per-axis thresholds', () => {
  test('the defaults are 0.8 for attack and 1.6 for defence', () => {
    expect(SWING_THRESHOLDS).toEqual({ attack: 0.8, defence: 1.6 });
  });

  test('a change big enough for attack is not big enough for defence', () => {
    // Reference 3.0, run from GW14 is 1,1,2,2,3 = 1.8: Δ -1.2.
    const series = withPast(3, [3, 3, 3, 1, 1, 2, 2, 3, 3, 2]);
    expect(findSwing(series, NOW)?.gameweek).toBe(14); // attack by default
    expect(findSwing(series, NOW, { axis: 'attack' })?.gameweek).toBe(14);
    expect(findSwing(series, NOW, { axis: 'defence' })).toBeNull();
  });

  test('defence calls the swing once the change reaches 1.6', () => {
    // Run from GW14 is 1,1,1,2,2 = 1.4: Δ -1.6.
    const series = withPast(3, [3, 3, 3, 1, 1, 1, 2, 2, 3, 3]);
    expect(findSwing(series, NOW, { axis: 'defence' })).toMatchObject({ gameweek: 14, direction: 'easier' });
  });

  test('an explicit threshold wins over the axis', () => {
    const series = withPast(3, [3, 3, 3, 1, 1, 2, 2, 3, 3, 2]);
    expect(findSwing(series, NOW, { axis: 'defence', threshold: 1.0 })?.gameweek).toBe(14);
  });
});

describe('orderBySwing', () => {
  const team = (short: string, avg: number | null = 3): TeamOutlook => ({
    team_short: short, team_name: short, axis: 'attack', avg_band: avg, verdict: '', series: [], runs: [],
  });
  const full = new Map<string, FixtureOutlookGW[]>([
    ['EAR', withPast(3, [3, 3, 2, 1, 1, 1, 3, 3, 3, 3])],      // easier at GW13
    ['EA2', withPast(3, [3, 3, 3, 1, 1, 2, 2, 3, 3, 2])],      // easier at GW14, bigger change
    ['EA3', withPast([4, 3, 4, 4, 3], [4, 3, 3, 3, 2, 3, 3, 3, 3, 3])], // easier at GW15
    ['STA', withPast(3, [3, 3, 3, 3, 3, 3, 3, 3, 3, 3])],
    ['STB', withPast(3, [3, 3, 3, 3, 3, 3, 3, 3, 3, 3])],
    ['HAR', withPast([2, 2, 3, 3, 2], [2, 2, 5, 3, 3, 3, 3, 3, 3, 3])], // harder at GW13
    ['HA2', withPast([3, 3, 3, 2, 3], [3, 3, 3, 4, 4, 4, 3, 3, 3, 3])], // harder at GW14
  ]);

  test('groups easier, stable, harder; sooner first, then larger change', () => {
    const teams = ['STA', 'HA2', 'EA2', 'STB', 'HAR', 'EAR'].map((s) => team(s));
    const ordered = orderBySwing(teams, full, NOW);
    expect(ordered.map((e) => e.team.team_short)).toEqual(['EAR', 'EA2', 'STA', 'STB', 'HAR', 'HA2']);
    expect(ordered.map((e) => e.group)).toEqual(['easier', 'easier', 'stable', 'stable', 'harder', 'harder']);
  });

  test('stable teams keep the order they arrived in', () => {
    const ordered = orderBySwing([team('STB'), team('STA')], full, NOW);
    expect(ordered.map((e) => e.team.team_short)).toEqual(['STB', 'STA']);
  });

  test('a team with no full-season series falls back to its own series and does not throw', () => {
    expect(() => orderBySwing([team('ZZZ')], full, NOW)).not.toThrow();
    expect(orderBySwing([team('ZZZ')], full, NOW)[0].group).toBe('stable');
  });
});
