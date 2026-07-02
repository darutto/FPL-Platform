/**
 * Tests for lib/fixture-tendency — FI5's reversed-axis chart geometry +
 * qualitative labelling (no fabricated probabilities; see FixtureTendencyChart).
 */
import { bandY, buildTendencyPoints, qualitativeBandLabel } from '@/lib/fixture-tendency';
import type { FixtureOutlookGW } from '@/lib/types';

describe('bandY — reversed axis, good=up', () => {
  test('band 1 (best) sits at the top (y=0)', () => {
    expect(bandY(1, 100)).toBe(0);
  });
  test('band 5 (worst) sits at the bottom (y=height)', () => {
    expect(bandY(5, 100)).toBe(100);
  });
  test('band 3 sits at the midpoint', () => {
    expect(bandY(3, 100)).toBe(50);
  });
  test('clamps out-of-range bands', () => {
    expect(bandY(0, 100)).toBe(0);
    expect(bandY(9, 100)).toBe(100);
  });
});

function gw(overrides: Partial<FixtureOutlookGW> & { gameweek: number }): FixtureOutlookGW {
  return {
    band: 3,
    klass: 'neutral',
    is_dgw: false,
    is_bgw: false,
    fixtures: [{ opponent_short: 'XXX', is_home: true, band: 3 }],
    ...overrides,
  };
}

describe('buildTendencyPoints', () => {
  test('one point per gameweek, spread across the width', () => {
    const series = [gw({ gameweek: 1 }), gw({ gameweek: 2 }), gw({ gameweek: 3 })];
    const points = buildTendencyPoints(series, 100, 50);
    expect(points).toHaveLength(3);
    expect(points[0].x).toBe(0);
    expect(points[2].x).toBe(100);
  });

  test('blank GW (band=null) is flagged but still positioned (neutral y)', () => {
    const series = [gw({ gameweek: 1, band: null, klass: 'blank' })];
    const [p] = buildTendencyPoints(series, 100, 100);
    expect(p.blank).toBe(true);
    expect(p.band).toBeNull();
    expect(p.y).toBe(bandY(3, 100)); // neutral fallback so the line stays continuous
  });

  test('single-GW series does not divide by zero', () => {
    const points = buildTendencyPoints([gw({ gameweek: 1 })], 100, 50);
    expect(points[0].x).toBe(0);
  });
});

describe('qualitativeBandLabel — no fabricated probabilities', () => {
  test('blank GW', () => {
    expect(qualitativeBandLabel(null, 'attack')).toMatch(/sin partido/i);
  });
  test('attack axis mentions goal opportunity, not a percentage', () => {
    const label = qualitativeBandLabel(1, 'attack');
    expect(label).toMatch(/gol/i);
    expect(label).not.toMatch(/%/);
  });
  test('defence axis mentions clean sheet, not a percentage', () => {
    const label = qualitativeBandLabel(5, 'defence');
    expect(label).toMatch(/portería/i);
    expect(label).not.toMatch(/%/);
  });
  test('band 3 is neutral for both axes', () => {
    expect(qualitativeBandLabel(3, 'attack')).toMatch(/media/i);
    expect(qualitativeBandLabel(3, 'defence')).toMatch(/media/i);
  });
});
