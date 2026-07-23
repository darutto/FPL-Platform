/**
 * buildSessionSeed() pure-function tests — one case per mapping row, plus
 * the contract guards (outcome/supported/intent-match) that stop a
 * malformed or unexpectedly-retained field from silently producing a seed.
 */
import { buildSessionSeed } from '@/lib/session-seed';
import {
  captainOkResponse,
  comparisonOkResponse,
  comparisonNoContextResponse,
  transferOkResponse,
  fixtureRunOkResponse,
  differentialOkResponse,
  unsupportedResponse,
  multiIntentOkResponse,
} from './fixtures/sample-responses';

describe('buildSessionSeed', () => {
  test('no response → null', () => {
    expect(buildSessionSeed(undefined)).toBeNull();
  });

  test('compare_players → last_comparison with both web_names', () => {
    expect(buildSessionSeed(comparisonOkResponse)).toEqual({
      last_comparison: ['Haaland', 'Salah'],
    });
  });

  test('compare_players with null player_a/player_b (legacy) → null, not a partial seed', () => {
    expect(buildSessionSeed(comparisonNoContextResponse)).toBeNull();
  });

  test('transfer_advice → last_transfer with player_out/player_in', () => {
    expect(buildSessionSeed(transferOkResponse)).toEqual({
      last_transfer: ['Saka', 'Salah'],
    });
  });

  test('player_fixture_run → last_fixture_run_player', () => {
    expect(buildSessionSeed(fixtureRunOkResponse)).toEqual({
      last_fixture_run_player: 'Haaland',
    });
  });

  test('differential_picks → last_differential: true', () => {
    expect(buildSessionSeed(differentialOkResponse)).toEqual({
      last_differential: true,
    });
  });

  test('captain_score → last_player_query', () => {
    expect(buildSessionSeed(captainOkResponse)).toEqual({
      last_player_query: 'Haaland',
    });
  });

  test('outcome !== "ok" → null even if a meta field is populated', () => {
    expect(buildSessionSeed(unsupportedResponse)).toBeNull();
  });

  test('supported === false → null', () => {
    expect(buildSessionSeed({ ...captainOkResponse, supported: false })).toBeNull();
  });

  test('intent/field mismatch (comparison populated, intent says something else) → null', () => {
    expect(
      buildSessionSeed({ ...comparisonOkResponse, intent: 'captain_score' }),
    ).toBeNull();
  });

  test('multi_intent → null (explicit v1 scope boundary, not incidental)', () => {
    expect(buildSessionSeed(multiIntentOkResponse)).toBeNull();
  });
});
