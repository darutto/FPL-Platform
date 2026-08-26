import {
  clampFixtureWindowStart,
  fixtureOutlookWindow,
  restoreFixtureWindow,
} from '../lib/fixture-gameweek-navigation';
import type { FixtureOutlookMeta } from '../lib/types';

const data: FixtureOutlookMeta = {
  axis: 'attack', horizon: 5, current_gameweek: 1,
  teams: [{
    team_short: 'ARS', team_name: 'Arsenal', axis: 'attack', avg_band: 3,
    verdict: 'Calendario sin rachas claras.',
    series: [1, 2, 3, 4, 5, 6].map((gameweek) => ({
      gameweek, band: gameweek === 4 ? null : 3, klass: gameweek === 4 ? 'blank' as const : 'neutral' as const,
      is_dgw: false, is_bgw: gameweek === 4, fixtures: gameweek === 4 ? [] : [{ opponent_short: 'BRE', is_home: true, band: 3 }],
    })),
    runs: [{ type: 'good', start_gw: 2, end_gw: 4, length: 3, intensity: 'mild' }],
  }],
};

describe('fixture gameweek navigation', () => {
  test('clamps arrow navigation to the exported schedule', () => {
    expect(clampFixtureWindowStart(0, [1, 2, 3, 4, 5, 6], 3)).toBe(1);
    expect(clampFixtureWindowStart(9, [1, 2, 3, 4, 5, 6], 3)).toBe(6);
  });

  test('keeps a manual window only while next_gw has not changed', () => {
    const saved = JSON.stringify({ baseGameweek: 1, startGameweek: 3 });
    expect(restoreFixtureWindow(saved, 1, [1, 2, 3, 4, 5, 6], 3)).toBe(3);
    // The J1 -> J2 rollover resets to the new live anchor.
    expect(restoreFixtureWindow(saved, 2, [1, 2, 3, 4, 5, 6], 3)).toBe(2);
  });

  test('windows series, average, and visible runs without changing fixture cells', () => {
    const window = fixtureOutlookWindow(data, 3, 3);
    expect(window.teams[0].series.map((cell) => cell.gameweek)).toEqual([3, 4, 5]);
    expect(window.teams[0].avg_band).toBe(3);
    expect(window.teams[0].runs).toEqual([
      { type: 'good', start_gw: 3, end_gw: 4, length: 2, intensity: 'mild' },
    ]);
  });
});
