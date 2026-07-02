/**
 * Tests for buildLeagueOutlook — the /fixtures (FI7) off-season data seam.
 * Guards the shape, ordering, and run-detection invariants so the page always
 * receives well-formed FixtureOutlookMeta.
 */
import { buildLeagueOutlook } from '@/lib/fixture-outlook-mock';

describe('buildLeagueOutlook', () => {
  test('returns all 20 teams with series of the requested horizon', () => {
    const meta = buildLeagueOutlook('attack', 8);
    expect(meta.axis).toBe('attack');
    expect(meta.horizon).toBe(8);
    expect(meta.teams).toHaveLength(20);
    for (const t of meta.teams) {
      expect(t.series).toHaveLength(8);
      expect(t.avg_band).not.toBeNull();
      for (const gw of t.series) {
        expect(gw.band).toBeGreaterThanOrEqual(1);
        expect(gw.band).toBeLessThanOrEqual(5);
        expect(gw.fixtures[0].opponent_short).not.toBe(t.team_short); // no self-fixture
      }
    }
  });

  test('teams are ordered easiest-first (ascending avg_band)', () => {
    const meta = buildLeagueOutlook('attack', 10);
    const avgs = meta.teams.map((t) => t.avg_band ?? 99);
    expect(avgs).toEqual([...avgs].sort((a, b) => a - b));
  });

  test('run invariants: length >= 3, strong iff length >= 5, within range', () => {
    const meta = buildLeagueOutlook('defence', 10);
    for (const t of meta.teams) {
      for (const r of t.runs) {
        expect(r.length).toBeGreaterThanOrEqual(3);
        expect(r.end_gw - r.start_gw + 1).toBe(r.length);
        expect(r.intensity).toBe(r.length >= 5 ? 'strong' : 'mild');
        expect(['good', 'bad']).toContain(r.type);
        expect(r.start_gw).toBeGreaterThanOrEqual(1);
        expect(r.end_gw).toBeLessThanOrEqual(10);
      }
    }
  });

  test('deterministic, and the two axes differ', () => {
    const a1 = buildLeagueOutlook('attack', 8);
    const a2 = buildLeagueOutlook('attack', 8);
    expect(JSON.stringify(a1)).toBe(JSON.stringify(a2)); // deterministic
    const d1 = buildLeagueOutlook('defence', 8);
    expect(JSON.stringify(a1)).not.toBe(JSON.stringify(d1)); // axis changes seed
  });
});
