/**
 * Tests for the /fixtures provenance stamp.
 *
 * The bug this guards: a bundle exported on launch day has `attack` and
 * `defence` banded from the same signal, so the axis switcher re-renders
 * identical rows. That is CORRECT at kickoff and WRONG once gameweeks have
 * been played — the difference is a fact the bundle now carries, so the stamp
 * distinguishes the two rather than guessing.
 */
import {
  fixtureOutlookProvenance,
  formatGeneratedAt,
  THIN_GAMEWEEKS,
} from '@/lib/fixture-outlook-provenance';
import type { FixtureOutlookGeneration } from '@/lib/types';

function generation(overrides: Partial<FixtureOutlookGeneration> = {}): FixtureOutlookGeneration {
  return {
    generated_at: '2026-09-08T22:14:03Z',
    season: '2026-2027',
    season_label: '2026-27',
    source: 'recipe',
    gameweeks_played: 12,
    axes_separated: true,
    axis_separation_by_horizon: { '38': 15 },
    teams: 20,
    source_horizon: 38,
    covers_gameweeks: [1, 38],
    gameweek_columns: 38,
    ...overrides,
  };
}

describe('formatGeneratedAt', () => {
  test('renders the UTC date in Spanish', () => {
    expect(formatGeneratedAt('2026-09-08T22:14:03Z')).toBe('8 sep 2026');
    expect(formatGeneratedAt('2026-01-31T00:00:00Z')).toBe('31 ene 2026');
  });

  test('returns null rather than "Invalid Date" for missing or junk input', () => {
    expect(formatGeneratedAt(null)).toBeNull();
    expect(formatGeneratedAt('')).toBeNull();
    expect(formatGeneratedAt('not a date')).toBeNull();
  });
});

describe('fixtureOutlookProvenance', () => {
  test('healthy bundle: states the season and how much of it, no warning', () => {
    const p = fixtureOutlookProvenance(generation(), 12);
    expect(p.status).toBe('current');
    expect(p.warning).toBeNull();
    expect(p.label).toContain('2026-27');
    expect(p.label).toContain('jornada 12');
    expect(p.label).toContain('8 sep 2026');
  });

  test('collapsed axes with gameweeks played: warns that the switcher does nothing', () => {
    const p = fixtureOutlookProvenance(
      generation({ axes_separated: false, gameweeks_played: 3, source: 'season_start' }),
      3,
    );
    expect(p.status).toBe('axes_collapsed');
    expect(p.warning).toContain('mismos datos');
    expect(p.warning).toContain('3');
  });

  test('collapsed axes at kickoff is legitimate, and says so without crying bug', () => {
    const p = fixtureOutlookProvenance(
      generation({ axes_separated: false, gameweeks_played: 0, source: 'season_start' }),
      0,
    );
    expect(p.status).toBe('season_start');
    expect(p.warning).toContain('Arranque de temporada');
    expect(p.label).toContain('sin jornadas jugadas');
  });

  test('thin sample ships, declared — the owner chose publish-and-say-so', () => {
    const p = fixtureOutlookProvenance(generation({ gameweeks_played: 3 }), 3);
    expect(p.status).toBe('thin');
    expect(p.warning).toContain('3 de 38');
    expect(THIN_GAMEWEEKS).toBeGreaterThan(3);
  });

  test('staleness is measured against the LIVE league, not against the bundle', () => {
    const behind = fixtureOutlookProvenance(generation({ gameweeks_played: 6 }), 11);
    expect(behind.status).toBe('stale_gameweeks');
    expect(behind.warning).toContain('jornada 11');

    // Same bundle, live lookup unavailable: we must not invent staleness.
    expect(fixtureOutlookProvenance(generation({ gameweeks_played: 6 }), null).status)
      .toBe('current');
  });

  test('collapsed axes outrank staleness — it is what the user can see on screen', () => {
    const p = fixtureOutlookProvenance(
      generation({ axes_separated: false, gameweeks_played: 3 }),
      11,
    );
    expect(p.status).toBe('axes_collapsed');
  });

  test('a bundle with no generation block admits it rather than staying silent', () => {
    const p = fixtureOutlookProvenance(null, 5);
    expect(p.status).toBe('unknown');
    expect(p.warning).toBeTruthy();
  });
});
