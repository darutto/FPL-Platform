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
import {
  clampFixtureWindowStart,
  fixtureGameweeks,
  fixtureOutlookWindow,
} from '@/lib/fixture-gameweek-navigation';

describe('buildRealSeasonOutlook', () => {
  test('returns all 20 teams on both axes', () => {
    for (const axis of ['attack', 'defence'] as const) {
      const meta = buildRealSeasonOutlook(axis);
      expect(meta.axis).toBe(axis);
      expect(meta.teams).toHaveLength(20);
    }
  });

  test('every team starts at gameweek 1 with real opponent codes', () => {
    const meta = buildRealSeasonOutlook('attack');
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
    const meta = buildRealSeasonOutlook('attack');
    const mci = meta.teams.find((t) => t.team_short === 'MCI');
    expect(mci).toBeDefined();
    const gw1 = mci!.series.find((s) => s.gameweek === 1);
    expect(gw1?.fixtures[0]).toMatchObject({ opponent_short: 'BOU', is_home: true });
  });

  test('names the fix when the bundle is not the single-bucket shape', () => {
    // The old three-bucket bundle (5/8/10) still parses as JSON and still has
    // 20 teams. It fails here, with the workflow to run, rather than silently
    // serving whichever bucket Object.keys happened to yield first.
    jest.isolateModules(() => {
      jest.doMock('@/lib/data/fixture-outlook-2026-27.json', () => ({
        attack: { 5: { teams: [] }, 10: { teams: [] } },
        defence: { 5: { teams: [] }, 10: { teams: [] } },
      }));
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const stale = require('@/lib/fixture-outlook-real');
      expect(() => stale.buildRealSeasonOutlook('attack')).toThrow(/Regenerate/);
    });
  });
});

/**
 * Measure axis separation the way the diagnosis did: how many of the 20 teams
 * come out with a different avg_band on the two axes. Deliberately computed
 * here from the rendered buckets rather than read from the bundle's metadata —
 * a guard that trusts the file's own self-description checks nothing.
 */
function teamsWithDifferentBand(horizon: number): number {
  const windowed = (axis: 'attack' | 'defence') => {
    const full = buildRealSeasonOutlook(axis);
    const first = fixtureGameweeks(full)[0];
    return fixtureOutlookWindow(full, first, horizon).teams;
  };
  const attack = new Map(windowed('attack').map((t) => [t.team_short, t.avg_band]));
  const defence = new Map(windowed('defence').map((t) => [t.team_short, t.avg_band]));
  let differing = 0;
  for (const [short, band] of attack) {
    if (defence.get(short) !== band) differing += 1;
  }
  return differing;
}

/**
 * A bundle with no `generation` block at all is the pre-fix 2026-27 file: it
 * cannot say which season it describes, how many gameweeks it used, or whether
 * its axes are distinct. Fail with that sentence rather than a null deref, so
 * whoever hits it is told what to do about it.
 */
function requireGeneration() {
  if (!REAL_SEASON_GENERATION) {
    throw new Error(
      'The shipped bundle carries no `generation` block, so nothing about its ' +
        'provenance can be checked. Regenerate it with the "Regenerate /fixtures ' +
        'outlook bundle" workflow (packages/fpl-grounded-assistant/scripts/' +
        'export_real_season_fixture_outlook.py --season <key>).',
    );
  }
  return REAL_SEASON_GENERATION;
}

describe('the shipped bundle declares how it was built', () => {
  test('carries a generation block', () => {
    expect(REAL_SEASON_GENERATION).not.toBeNull();
    const gen = requireGeneration();
    expect(gen.season).toMatch(/^\d{4}-\d{4}$/);
    expect(gen.generated_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(gen.gameweeks_played).toBeGreaterThanOrEqual(0);
    expect(gen.teams).toBe(20);
  });

  test('its axes_separated claim matches what the bucket actually contains', () => {
    const gen = requireGeneration();
    const measured = REAL_SEASON_HORIZONS.some((h) => teamsWithDifferentBand(h) > 0);
    expect(gen.axes_separated).toBe(measured);
    // The bundle reports separation over its own full-season bucket; that key
    // is whatever horizon it shipped, so read it rather than assume 5/8/10.
    expect(gen.axis_separation_by_horizon[String(gen.source_horizon)]).toBeGreaterThanOrEqual(0);
  });

  /**
   * THE GUARD. Identical axes are correct at kickoff — no results exist, so the
   * defence recipe has no form to refine FDR with — and stale the moment a
   * gameweek has been played. The bundle's own gameweeks_played tells the two
   * apart, so this fails on the obsolete case without failing a legitimate
   * season-start export.
   */
  test('once gameweeks have been played, the two axes must be different signals', () => {
    const gen = requireGeneration();
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

// ---------------------------------------------------------------------------
// THE COVERAGE GUARD
//
// Same shape as the axis guard above, and for the same reason: the failure it
// catches is silent, gradual, and looks like working software the whole way
// down.
//
// The bundle's window started at gameweek 1 and ran for `horizon`. The screen's
// window starts at the LIVE gameweek. So every week that passed cost one column
// off the right-hand side: at GW4 the "10" selector showed 7, at GW8 it showed
// 3, and from GW10 the board froze on one column of GW10 -- a match already
// played -- and stayed there. Not empty. Worse: a stale number that looks like
// a forecast.
//
// What would make this guard pass while the fix is wrong? Two things, and both
// are closed below. Measuring coverage against the bundle's FIRST gameweek
// rather than the live one (the old bundle covers J1-J10 and would sail
// through). And trusting `generation.covers_gameweeks` instead of the series
// (metadata can claim a span the data does not have).
// ---------------------------------------------------------------------------

/** Columns actually rendered for `selector`, if the live gameweek were `liveGw`. */
function renderedColumns(liveGw: number, selector: number): number {
  const full = buildRealSeasonOutlook('attack');
  const gws = fixtureGameweeks(full);
  const start = clampFixtureWindowStart(liveGw, gws, selector) ?? gws[0];
  return fixtureOutlookWindow(full, start, selector).teams[0].series.length;
}

describe('the bundle covers enough gameweeks AHEAD of the live one', () => {
  const LARGEST_SELECTOR = Math.max(...REAL_SEASON_HORIZONS);

  test('the series itself spans the season, not a window sized at build time', () => {
    const gen = requireGeneration();
    const series = buildRealSeasonOutlook('attack').teams[0].series;
    const last = series.at(-1)!.gameweek;

    // Read off the DATA, then cross-check the metadata against it. Trusting
    // covers_gameweeks alone would let a bundle claim a span it does not hold.
    expect(gen.covers_gameweeks[1]).toBe(last);
    expect(last).toBeGreaterThanOrEqual(30);
  });

  test('every selector still fills at the gameweeks where it used to collapse', () => {
    const gen = requireGeneration();
    const lastCovered = buildRealSeasonOutlook('attack').teams[0].series.at(-1)!.gameweek;

    // Anchored on the LIVE gameweek, which is the thing that moves. Checking
    // from the bundle's own first gameweek is what made the old bundle look
    // healthy: J1 + 10 fits inside J1-J10 perfectly well.
    for (const liveGw of [gen.gameweeks_played + 1, 4, 8, 10, 15, 20]) {
      if (liveGw > lastCovered - LARGEST_SELECTOR) continue; // genuinely near the end
      for (const selector of REAL_SEASON_HORIZONS) {
        expect(`J${liveGw} sel ${selector}: ${renderedColumns(liveGw, selector)} columns`)
          .toBe(`J${liveGw} sel ${selector}: ${selector} columns`);
      }
    }
  });

  test('near the end of the season a short window is correct, not a failure', () => {
    // The guard must not demand 10 columns at gameweek 37. Shrinking is only a
    // bug when there is season left that the bundle failed to carry.
    const series = buildRealSeasonOutlook('attack').teams[0].series;
    const last = series.at(-1)!.gameweek;
    expect(renderedColumns(last, LARGEST_SELECTOR)).toBeGreaterThan(0);
    expect(renderedColumns(last, LARGEST_SELECTOR)).toBeLessThan(LARGEST_SELECTOR);
  });
});
