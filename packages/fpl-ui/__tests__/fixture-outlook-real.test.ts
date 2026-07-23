/**
 * Tests for buildRealSeasonOutlook — the /fixtures data seam sourced from the
 * live 2026-27 season schedule (exported by
 * export_real_season_fixture_outlook.py --season-start, which runs the actual
 * backend fixture_outlook.py engine — no algorithm duplicated here).
 */
import { buildRealSeasonOutlook, REAL_SEASON_HORIZONS } from '@/lib/fixture-outlook-real';

describe('buildRealSeasonOutlook', () => {
  test('returns all 20 teams for every supported (axis, horizon) combo', () => {
    for (const axis of ['attack', 'defence'] as const) {
      for (const horizon of REAL_SEASON_HORIZONS) {
        const meta = buildRealSeasonOutlook(axis, horizon);
        expect(meta.axis).toBe(axis);
        expect(meta.horizon).toBe(horizon);
        expect(meta.teams).toHaveLength(20);
      }
    }
  });

  test('every team starts at gameweek 1 with real opponent codes', () => {
    const meta = buildRealSeasonOutlook('attack', 8);
    for (const t of meta.teams) {
      expect(t.series).toHaveLength(8);
      expect(t.series[0].gameweek).toBe(1);
      for (const gw of t.series) {
        expect(gw.band).toBeGreaterThanOrEqual(1);
        expect(gw.band).toBeLessThanOrEqual(5);
        expect(gw.fixtures.length).toBeGreaterThan(0);
        expect(gw.fixtures[0].opponent_short).not.toBe(t.team_short);
        // Real team codes are 3 uppercase letters (ARS, AVL, ...), not
        // synthetic placeholders.
        expect(gw.fixtures[0].opponent_short).toMatch(/^[A-Z]{3}$/);
      }
    }
  });

  test('a known real fixture is present: Man City host Bournemouth in GW1', () => {
    const meta = buildRealSeasonOutlook('attack', 5);
    const mci = meta.teams.find((t) => t.team_short === 'MCI');
    expect(mci).toBeDefined();
    const gw1 = mci!.series.find((s) => s.gameweek === 1);
    expect(gw1?.fixtures[0]).toMatchObject({ opponent_short: 'BOU', is_home: true });
  });

  test('throws on an unsupported horizon rather than silently returning nothing', () => {
    expect(() => buildRealSeasonOutlook('attack', 7)).toThrow();
  });
});
