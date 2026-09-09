/**
 * Tests for buildRealSeasonOutlook — the /fixtures data seam sourced from the
 * 2026-27 season (exported by export_real_season_fixture_outlook.py, which
 * runs the actual backend fixture_outlook.py engine — no algorithm duplicated
 * here).
 *
 * Includes the axis-separation guard. The equivalent invariant already existed
 * for the SYNTHETIC generator (fixture-outlook-mock.test.ts: "the two axes
 * differ") but was never applied to the real bundle, so a shipped bundle with
 * both axes collapsed onto one signal passed every test for six weeks.
 */
import {
  buildRealSeasonOutlook,
  REAL_SEASON_GENERATION,
  REAL_SEASON_HORIZONS,
} from '@/lib/fixture-outlook-real';

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

/**
 * Measure axis separation the way the diagnosis did: how many of the 20 teams
 * come out with a different avg_band on the two axes. Deliberately computed
 * here from the rendered buckets rather than read from the bundle's metadata —
 * a guard that trusts the file's own self-description checks nothing.
 */
function teamsWithDifferentBand(horizon: number): number {
  const attack = new Map(
    buildRealSeasonOutlook('attack', horizon).teams.map((t) => [t.team_short, t.avg_band]),
  );
  const defence = new Map(
    buildRealSeasonOutlook('defence', horizon).teams.map((t) => [t.team_short, t.avg_band]),
  );
  let differing = 0;
  for (const [short, band] of attack) {
    if (defence.get(short) !== band) differing += 1;
  }
  return differing;
}

describe('the shipped bundle declares how it was built', () => {
  test('carries a generation block', () => {
    expect(REAL_SEASON_GENERATION).not.toBeNull();
    const gen = REAL_SEASON_GENERATION!;
    expect(gen.season).toMatch(/^\d{4}-\d{4}$/);
    expect(gen.generated_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(gen.gameweeks_played).toBeGreaterThanOrEqual(0);
    expect(gen.teams).toBe(20);
  });

  test('its axes_separated claim matches what the buckets actually contain', () => {
    const gen = REAL_SEASON_GENERATION!;
    const measured = REAL_SEASON_HORIZONS.some((h) => teamsWithDifferentBand(h) > 0);
    expect(gen.axes_separated).toBe(measured);
    for (const horizon of REAL_SEASON_HORIZONS) {
      expect(gen.axis_separation_by_horizon[String(horizon)]).toBe(
        teamsWithDifferentBand(horizon),
      );
    }
  });

  /**
   * THE GUARD. Identical axes are correct at kickoff — no results exist, so the
   * defence recipe has no form to refine FDR with — and stale the moment a
   * gameweek has been played. The bundle's own gameweeks_played tells the two
   * apart, so this fails on the obsolete case without failing a legitimate
   * season-start export.
   */
  test('once gameweeks have been played, the two axes must be different signals', () => {
    const gen = REAL_SEASON_GENERATION!;
    if (gen.gameweeks_played === 0) {
      expect(gen.source).toBe('season_start');
      return;
    }
    const perHorizon = REAL_SEASON_HORIZONS.map((h) => `J${h}=${teamsWithDifferentBand(h)}`);
    expect(
      `${gen.gameweeks_played} gameweeks played, teams differing per horizon: ` +
        `${perHorizon.join(', ')}`,
    ).not.toContain('J5=0, J8=0, J10=0');
    expect(REAL_SEASON_HORIZONS.some((h) => teamsWithDifferentBand(h) > 0)).toBe(true);
  });
});
