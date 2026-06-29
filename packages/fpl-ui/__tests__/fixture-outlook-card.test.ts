/**
 * Track D / FI4 — FixtureOutlookCard helpers + intent selection.
 * Imports only pure .ts (no JSX) so the card's render path is irrelevant here.
 */
import { selectIntentView } from '../lib/intent-renderer';
import { bandColor, axisLabel } from '../lib/fixture-outlook-format';
import type { AskResponse, FixtureOutlookMeta } from '../lib/types';

function meta(teams: FixtureOutlookMeta['teams']): FixtureOutlookMeta {
  return { axis: 'attack', horizon: 10, current_gameweek: 1, teams };
}

const oneTeam: FixtureOutlookMeta['teams'] = [
  {
    team_short: 'ARS',
    team_name: 'Arsenal',
    axis: 'attack',
    avg_band: 1.7,
    verdict: 'Buen tramo ofensivo: 3 jornadas asequibles (J1–J3).',
    series: [
      { gameweek: 1, band: 2, klass: 'good', is_dgw: false, is_bgw: false,
        fixtures: [{ opponent_short: 'BRE', is_home: true, band: 2 }] },
    ],
    runs: [{ type: 'good', start_gw: 1, end_gw: 3, length: 3, intensity: 'mild' }],
  },
];

function response(over: Partial<AskResponse>): AskResponse {
  return {
    outcome: 'ok',
    intent: 'fixture_outlook',
    resource_rows: null,
    web_search: null,
    fixture_outlook: meta(oneTeam),
    ...over,
  } as unknown as AskResponse;
}

describe('bandColor / axisLabel', () => {
  test('band ramp: 1 green … 5 red', () => {
    expect(bandColor(1)).toBe('#2ecc71');
    expect(bandColor(5)).toBe('#e74c3c');
  });
  test('axis labels are Spanish', () => {
    expect(axisLabel('attack')).toBe('Ataque');
    expect(axisLabel('defence')).toBe('Portería a cero');
  });
});

describe('selectIntentView — fixture_outlook', () => {
  test('renders the card when intent + non-empty teams', () => {
    expect(selectIntentView(response({}))).toBe('fixture_outlook');
  });
  test('text-only when teams empty', () => {
    expect(selectIntentView(response({ fixture_outlook: meta([]) }))).toBeNull();
  });
  test('text-only when intent mismatches', () => {
    expect(selectIntentView(response({ intent: 'player_summary' }))).toBeNull();
  });
  test('text-only when not ok', () => {
    expect(selectIntentView(response({ outcome: 'not_found' }))).toBeNull();
  });
});
