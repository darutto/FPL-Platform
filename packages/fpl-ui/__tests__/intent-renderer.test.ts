/**
 * Intent renderer selection tests — V2 Phase 2c
 *
 * Tests lib/intent-renderer.ts selectIntentView() in isolation.
 * No React, no DOM, no jsdom required — pure function tests.
 *
 * Coverage:
 *   - Correct component selection for all rendered intents
 *   - null returned for non-ok outcomes
 *   - null returned for ok turns where the conditional field is null
 *     (null-safety guard: the field CAN be null even on ok turns)
 *   - null returned for ok turns with empty lists (ranking/fixture/differential)
 *   - null returned for intents not yet rendered (text-only Phase 2c)
 *   - final_text is present on all sample responses (data contract)
 */
import { selectIntentView } from '../lib/intent-renderer';
import type { AskResponse } from '../lib/types';
import {
  captainOkResponse,
  captainUpsideResponse,
  comparisonOkResponse,
  comparisonTiedResponse,
  comparisonNoContextResponse,
  rankingOkResponse,
  rankingEmptyResponse,
  transferOkResponse,
  transferHoldResponse,
  chipOkResponse,
  chipWildcardResponse,
  chipMissingContextResponse,
  chipUnavailableResponse,
  fixtureRunOkResponse,
  fixtureRunEmptyResponse,
  differentialOkResponse,
  differentialEmptyResponse,
  multiIntentOkResponse,
  multiIntentNullSubsResponse,
  multiIntentEmptySubsResponse,
  unsupportedResponse,
  notFoundResponse,
} from './fixtures/sample-responses';

// ---------------------------------------------------------------------------
// Component selection — should render structured view
// ---------------------------------------------------------------------------

describe('selectIntentView — returns structured view', () => {
  test('captain_score OK → "captain"', () => {
    expect(selectIntentView(captainOkResponse)).toBe('captain');
  });

  test('captain_score OK upside tier → "captain"', () => {
    expect(selectIntentView(captainUpsideResponse)).toBe('captain');
  });

  test('compare_players OK → "comparison"', () => {
    expect(selectIntentView(comparisonOkResponse)).toBe('comparison');
  });

  test('compare_players OK tied → "comparison"', () => {
    expect(selectIntentView(comparisonTiedResponse)).toBe('comparison');
  });

  test('compare_players OK no player context → "comparison"', () => {
    expect(selectIntentView(comparisonNoContextResponse)).toBe('comparison');
  });

  test('rank_candidates OK non-empty → "ranking"', () => {
    expect(selectIntentView(rankingOkResponse)).toBe('ranking');
  });

  test('transfer_advice OK (transfer_in) → "transfer"', () => {
    expect(selectIntentView(transferOkResponse)).toBe('transfer');
  });

  test('transfer_advice OK (hold) → "transfer"', () => {
    expect(selectIntentView(transferHoldResponse)).toBe('transfer');
  });

  test('chip_advice OK (conditions_favorable) → "chip"', () => {
    expect(selectIntentView(chipOkResponse)).toBe('chip');
  });

  test('chip_advice OK (wildcard) → "chip"', () => {
    expect(selectIntentView(chipWildcardResponse)).toBe('chip');
  });

  test('chip_advice OK (missing_context) → "chip"', () => {
    expect(selectIntentView(chipMissingContextResponse)).toBe('chip');
  });

  test('chip_advice OK (chip_unavailable) → "chip"', () => {
    expect(selectIntentView(chipUnavailableResponse)).toBe('chip');
  });

  test('player_fixture_run OK non-empty fixtures → "fixture_run"', () => {
    expect(selectIntentView(fixtureRunOkResponse)).toBe('fixture_run');
  });

  test('differential_picks OK non-empty picks → "differential"', () => {
    expect(selectIntentView(differentialOkResponse)).toBe('differential');
  });

  test('multi_intent OK non-empty sub_responses → "multi_intent"', () => {
    expect(selectIntentView(multiIntentOkResponse)).toBe('multi_intent');
  });
});

// ---------------------------------------------------------------------------
// Text-only — non-ok outcomes
// ---------------------------------------------------------------------------

describe('selectIntentView — text-only (non-ok outcomes)', () => {
  test('unsupported_intent → null', () => {
    expect(selectIntentView(unsupportedResponse)).toBeNull();
  });

  test('not_found → null', () => {
    expect(selectIntentView(notFoundResponse)).toBeNull();
  });

  test('ambiguous → null', () => {
    expect(
      selectIntentView({ ...captainOkResponse, outcome: 'ambiguous', captain: null }),
    ).toBeNull();
  });

  test('error → null', () => {
    expect(
      selectIntentView({ ...captainOkResponse, outcome: 'error', captain: null }),
    ).toBeNull();
  });

  test('missing_arguments → null', () => {
    expect(
      selectIntentView({ ...captainOkResponse, outcome: 'missing_arguments', captain: null }),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Null-safety guard — ok outcome but conditional field is null
// ---------------------------------------------------------------------------

describe('selectIntentView — null-safety on conditional fields', () => {
  test('captain_score OK, captain null → null', () => {
    expect(selectIntentView({ ...captainOkResponse, captain: null })).toBeNull();
  });

  test('compare_players OK, comparison null → null', () => {
    expect(selectIntentView({ ...comparisonOkResponse, comparison: null })).toBeNull();
  });

  test('rank_candidates OK, captain_ranking null → null', () => {
    expect(selectIntentView({ ...rankingOkResponse, captain_ranking: null })).toBeNull();
  });

  test('rank_candidates OK, captain_ranking empty → null', () => {
    expect(selectIntentView(rankingEmptyResponse)).toBeNull();
  });

  test('transfer_advice OK, transfer null → null', () => {
    expect(selectIntentView({ ...transferOkResponse, transfer: null })).toBeNull();
  });

  test('chip_advice OK, chip null → null', () => {
    expect(selectIntentView({ ...chipOkResponse, chip: null })).toBeNull();
  });

  test('player_fixture_run OK, fixture_run null → null', () => {
    expect(
      selectIntentView({ ...fixtureRunOkResponse, fixture_run: null }),
    ).toBeNull();
  });

  test('player_fixture_run OK, fixtures empty array → null', () => {
    expect(selectIntentView(fixtureRunEmptyResponse)).toBeNull();
  });

  test('differential_picks OK, differential null → null', () => {
    expect(
      selectIntentView({ ...differentialOkResponse, differential: null }),
    ).toBeNull();
  });

  test('differential_picks OK, picks empty array → null', () => {
    expect(selectIntentView(differentialEmptyResponse)).toBeNull();
  });

  test('multi_intent OK, sub_responses null → null', () => {
    expect(selectIntentView(multiIntentNullSubsResponse)).toBeNull();
  });

  test('multi_intent OK, sub_responses empty → null', () => {
    expect(selectIntentView(multiIntentEmptySubsResponse)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Text-only intents (Phase 2d — structured rendering deferred)
// ---------------------------------------------------------------------------

describe('selectIntentView — text-only intents (Phase 2d)', () => {
  test('current_gameweek OK → null', () => {
    expect(
      selectIntentView({ ...unsupportedResponse, outcome: 'ok', supported: true, intent: 'current_gameweek' }),
    ).toBeNull();
  });

  test('player_summary OK → null', () => {
    expect(
      selectIntentView({ ...unsupportedResponse, outcome: 'ok', supported: true, intent: 'player_summary' }),
    ).toBeNull();
  });

  test('player_resolve OK → null', () => {
    expect(
      selectIntentView({ ...unsupportedResponse, outcome: 'ok', supported: true, intent: 'player_resolve' }),
    ).toBeNull();
  });

  test('multi_intent OK with null sub_responses → null (no sub-cards to show)', () => {
    expect(selectIntentView(multiIntentNullSubsResponse)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Data contract — final_text always present on all fixtures
// ---------------------------------------------------------------------------

describe('sample responses — data contract', () => {
  const allSamples: AskResponse[] = [
    captainOkResponse,
    captainUpsideResponse,
    comparisonOkResponse,
    comparisonTiedResponse,
    comparisonNoContextResponse,
    rankingOkResponse,
    rankingEmptyResponse,
    transferOkResponse,
    transferHoldResponse,
    chipOkResponse,
    chipWildcardResponse,
    chipMissingContextResponse,
    chipUnavailableResponse,
    fixtureRunOkResponse,
    fixtureRunEmptyResponse,
    differentialOkResponse,
    differentialEmptyResponse,
    multiIntentOkResponse,
    multiIntentNullSubsResponse,
    multiIntentEmptySubsResponse,
    unsupportedResponse,
    notFoundResponse,
  ];

  test('final_text non-empty on every sample response', () => {
    for (const r of allSamples) {
      expect(r.final_text).toBeTruthy();
    }
  });

  test('fixture_run field is non-null on fixtureRunOkResponse', () => {
    expect(fixtureRunOkResponse.fixture_run).not.toBeNull();
    expect(fixtureRunOkResponse.fixture_run!.fixtures).toHaveLength(5);
  });

  test('differential field is non-null on differentialOkResponse', () => {
    expect(differentialOkResponse.differential).not.toBeNull();
    expect(differentialOkResponse.differential!.picks).toHaveLength(3);
  });

  test('only fixture_run field non-null on fixtureRunOkResponse', () => {
    const r = fixtureRunOkResponse;
    expect(r.captain).toBeNull();
    expect(r.comparison).toBeNull();
    expect(r.transfer).toBeNull();
    expect(r.chip).toBeNull();
    expect(r.differential).toBeNull();
  });

  test('only differential field non-null on differentialOkResponse', () => {
    const r = differentialOkResponse;
    expect(r.captain).toBeNull();
    expect(r.comparison).toBeNull();
    expect(r.fixture_run).toBeNull();
    expect(r.chip).toBeNull();
    expect(r.transfer).toBeNull();
  });

  test('multiIntentOkResponse has two sub_responses', () => {
    expect(multiIntentOkResponse.sub_responses).not.toBeNull();
    expect(multiIntentOkResponse.sub_responses!).toHaveLength(2);
  });

  test('multiIntentOkResponse sub_responses each have final_text', () => {
    for (const sub of multiIntentOkResponse.sub_responses!) {
      expect(sub.final_text).toBeTruthy();
    }
  });

  test('multiIntentOkResponse sub_responses are captain + transfer intents', () => {
    const intents = multiIntentOkResponse.sub_responses!.map((s) => s.intent);
    expect(intents).toEqual(['captain_score', 'transfer_advice']);
  });

  test('sub_responses of multiIntentOkResponse are individually selectable', () => {
    const [captain, transfer] = multiIntentOkResponse.sub_responses!;
    expect(selectIntentView(captain)).toBe('captain');
    expect(selectIntentView(transfer)).toBe('transfer');
  });
});
