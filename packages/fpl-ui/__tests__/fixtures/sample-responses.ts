/**
 * Minimal AskResponse fixtures for UI unit tests.
 *
 * Derived from the backend contract artifacts:
 *   http_contract_fixtures.json (V2 Phase 1f)
 *   FINAL_RESPONSE_CONTRACT.md
 *
 * These are NOT exhaustive response copies — only the fields needed by the
 * intent renderer are populated. Null is explicit for all unused conditional
 * fields to match the backend's actual serialisation.
 */
import type { AskResponse } from '../../lib/types';

/** captain_score OK — CaptainCard should render */
export const captainOkResponse: AskResponse = {
  final_text: 'Deberías capitanear a Haaland esta semana.',
  outcome: 'ok',
  supported: true,
  intent: 'captain_score',
  review_passed: true,
  llm_used: false,
  captain: {
    web_name: 'Haaland',
    team_short: 'MCI',
    captain_score: 83.5,
    tier: 'safe',
    role_bonus: 5.0,
    set_piece_notes: ['penalty_taker_1'],
  },
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
};

/** captain_score OK — upside tier, no set piece notes */
export const captainUpsideResponse: AskResponse = {
  ...captainOkResponse,
  captain: {
    web_name: 'Salah',
    team_short: 'LIV',
    captain_score: 74.2,
    tier: 'upside',
    role_bonus: 0.0,
    set_piece_notes: [],
  },
};

/** compare_players OK — ComparisonCard should render */
export const comparisonOkResponse: AskResponse = {
  final_text: 'Haaland es mejor opción que Salah esta semana.',
  outcome: 'ok',
  supported: true,
  intent: 'compare_players',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: {
    winner: 'Haaland',
    margin: 6.8,
    label: 'moderate',
    reasons: ['Mejor forma (9.5 vs 8.0)', 'Mejor fixture (FDR 2 vs 4)'],
    player_a: {
      web_name: 'Haaland',
      position: 'FWD',
      captain_score: 83.5,
      position_score: 84.0,
      is_home: true,
      effective_fdr: 1.5,
      role_bonus: 5.0,
      set_piece_notes: ['penalty_taker_1'],
    },
    player_b: {
      web_name: 'Salah',
      position: 'MID',
      captain_score: 76.7,
      position_score: 77.0,
      is_home: false,
      effective_fdr: 2.5,
      role_bonus: 0.0,
      set_piece_notes: [],
    },
  },
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
};

/** compare_players OK — tied (winner=null) */
export const comparisonTiedResponse: AskResponse = {
  ...comparisonOkResponse,
  comparison: {
    winner: null,
    margin: 0.0,
    label: 'narrow',
    reasons: [],
    player_a: comparisonOkResponse.comparison!.player_a,
    player_b: comparisonOkResponse.comparison!.player_b,
  },
};

/** compare_players OK — player_a/b null (legacy construction path) */
export const comparisonNoContextResponse: AskResponse = {
  ...comparisonOkResponse,
  comparison: {
    winner: 'Haaland',
    margin: 6.8,
    label: 'moderate',
    reasons: ['Mejor forma'],
    player_a: null,
    player_b: null,
  },
};

/** unsupported_intent — text-only, no structured rendering */
export const unsupportedResponse: AskResponse = {
  final_text: 'Lo siento, no puedo responder esa pregunta.',
  outcome: 'unsupported_intent',
  supported: false,
  intent: null,
  review_passed: false,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
};

/** not_found — text-only, no structured rendering */
export const notFoundResponse: AskResponse = {
  final_text: 'No encontré al jugador en el sistema.',
  outcome: 'not_found',
  supported: true,
  intent: 'captain_score',
  review_passed: false,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
};

/** rank_candidates OK — RankingTable should render */
export const rankingOkResponse: AskResponse = {
  final_text: 'Los mejores candidatos a capitán esta semana son Haaland, Salah y Palmer.',
  outcome: 'ok',
  supported: true,
  intent: 'rank_candidates',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: [
    {
      rank: 1,
      web_name: 'Haaland',
      team_short: 'MCI',
      captain_score: 83.5,
      tier: 'safe',
      role_bonus: 5.0,
      set_piece_notes: ['penalty_taker_1'],
    },
    {
      rank: 2,
      web_name: 'Salah',
      team_short: 'LIV',
      captain_score: 76.7,
      tier: 'upside',
      role_bonus: 0.0,
      set_piece_notes: [],
    },
    {
      rank: 3,
      web_name: 'Palmer',
      team_short: 'CHE',
      captain_score: 71.2,
      tier: 'differential',
      role_bonus: 0.5,
      set_piece_notes: ['freekick_taker_1'],
    },
  ],
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
};

/** rank_candidates OK — empty list (edge case: should fall through to text-only) */
export const rankingEmptyResponse: AskResponse = {
  ...rankingOkResponse,
  captain_ranking: [],
};

/** transfer_advice OK — TransferCard should render (Phase 2b) */
export const transferOkResponse: AskResponse = {
  final_text: 'Considera fichar a Salah por Saka.',
  outcome: 'ok',
  supported: true,
  intent: 'transfer_advice',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: {
    player_out: 'Saka',
    player_in: 'Salah',
    recommendation: 'transfer_in',
    score_delta: 7.5,
    price_delta: 10,
    reasons: ['Mejor forma'],
    budget_constraint: false,
    hit_warning: false,
  },
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
};

/** transfer_advice OK — hold recommendation, with budget_constraint */
export const transferHoldResponse: AskResponse = {
  ...transferOkResponse,
  transfer: {
    player_out: 'Saka',
    player_in: 'Salah',
    recommendation: 'hold',
    score_delta: -1.2,
    price_delta: 15,
    reasons: [],
    budget_constraint: true,
    hit_warning: false,
  },
};

/** chip_advice OK — triple_captain, conditions_favorable — ChipCard should render */
export const chipOkResponse: AskResponse = {
  final_text: 'Las condiciones son favorables para usar el Triple Capitán esta semana.',
  outcome: 'ok',
  supported: true,
  intent: 'chip_advice',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: {
    chip: 'triple_captain',
    recommendation: 'conditions_favorable',
    gw: 28,
    signal_value: 83.5,
    signal_label: 'Puntuación de capitán',
    chip_unavailable: false,
  },
  fixture_run: null,
  differential: null,
  sub_responses: null,
};

/** chip_advice OK — wildcard, conditions_marginal */
export const chipWildcardResponse: AskResponse = {
  ...chipOkResponse,
  chip: {
    chip: 'wildcard',
    recommendation: 'conditions_marginal',
    gw: 28,
    signal_value: 28.0,
    signal_label: 'Jornada actual',
    chip_unavailable: false,
  },
};

/** chip_advice OK — free_hit, missing_context (no DGW/BGW data) */
export const chipMissingContextResponse: AskResponse = {
  ...chipOkResponse,
  chip: {
    chip: 'free_hit',
    recommendation: 'missing_context',
    gw: 28,
    signal_value: null,
    signal_label: null,
    chip_unavailable: false,
  },
};

/** chip_advice OK — chip unavailable in squad */
export const chipUnavailableResponse: AskResponse = {
  ...chipOkResponse,
  chip: {
    ...chipOkResponse.chip!,
    chip_unavailable: true,
  },
};

/** player_fixture_run OK — FixtureRunTable should render */
export const fixtureRunOkResponse: AskResponse = {
  final_text: 'Haaland tiene un buen calendario de partidos en las próximas semanas.',
  outcome: 'ok',
  supported: true,
  intent: 'player_fixture_run',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: {
    web_name: 'Haaland',
    team_short: 'MCI',
    position: 'FWD',
    horizon: 5,
    current_gameweek: 28,
    fixtures: [
      { gameweek: 28, opponent_short: 'ARS', is_home: true,  difficulty: 2 },
      { gameweek: 29, opponent_short: 'MUN', is_home: false, difficulty: 2 },
      { gameweek: 30, opponent_short: 'CHE', is_home: true,  difficulty: 3 },
      { gameweek: 31, opponent_short: 'LIV', is_home: false, difficulty: 4 },
      { gameweek: 32, opponent_short: 'TOT', is_home: true,  difficulty: 2 },
    ],
  },
  differential: null,
  sub_responses: null,
};

/**
 * player_fixture_run OK — double gameweek (DGW).
 *
 * GW29 contains TWO fixtures (ARS at home, MUN away). Used to verify that
 * the renderer does not assume gameweek values are unique across the fixtures
 * array and that both DGW fixtures are preserved independently.
 */
export const fixtureRunDgwResponse: AskResponse = {
  ...fixtureRunOkResponse,
  fixture_run: {
    web_name: 'Haaland',
    team_short: 'MCI',
    position: 'FWD',
    horizon: 5,
    current_gameweek: 28,
    fixtures: [
      { gameweek: 28, opponent_short: 'ARS', is_home: true,  difficulty: 2 },
      { gameweek: 29, opponent_short: 'ARS', is_home: true,  difficulty: 2 },
      { gameweek: 29, opponent_short: 'MUN', is_home: false, difficulty: 3 },
      { gameweek: 30, opponent_short: 'CHE', is_home: true,  difficulty: 3 },
      { gameweek: 31, opponent_short: 'LIV', is_home: false, difficulty: 4 },
    ],
  },
};

/** player_fixture_run OK — empty fixtures (edge case: should fall through to text-only) */
export const fixtureRunEmptyResponse: AskResponse = {
  ...fixtureRunOkResponse,
  fixture_run: {
    web_name: 'Haaland',
    team_short: 'MCI',
    position: 'FWD',
    horizon: 0,
    current_gameweek: 38,
    fixtures: [],
  },
};

/** differential_picks OK — DifferentialTable should render */
export const differentialOkResponse: AskResponse = {
  final_text: 'Los mejores diferenciales esta semana son Palmer, Mbeumo y Diaby.',
  outcome: 'ok',
  supported: true,
  intent: 'differential_picks',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: {
    ownership_threshold: 15.0,
    top_n: 3,
    picks: [
      {
        rank: 1,
        web_name: 'Palmer',
        team_short: 'CHE',
        position: 'MID',
        captain_score: 71.2,
        position_score: 72.0,
        ownership: 1.0,
        now_cost: 75,
        is_home: true,
      },
      {
        rank: 2,
        web_name: 'Mbeumo',
        team_short: 'BRE',
        position: 'FWD',
        captain_score: 68.5,
        position_score: 69.1,
        ownership: 8.2,
        now_cost: 70,
        is_home: false,
      },
      {
        rank: 3,
        web_name: 'Diaby',
        team_short: 'AVL',
        position: 'MID',
        captain_score: 65.1,
        position_score: 66.0,
        ownership: 12.3,
        now_cost: 65,
        is_home: null,
      },
    ],
  },
  sub_responses: null,
};

/** differential_picks OK — empty picks (edge case: should fall through to text-only) */
export const differentialEmptyResponse: AskResponse = {
  ...differentialOkResponse,
  differential: {
    ownership_threshold: 15.0,
    top_n: 0,
    picks: [],
  },
};

/**
 * multi_intent OK — two sub-responses (captain_score + transfer_advice).
 * MultiIntentView should render with two stacked sub-cards.
 */
export const multiIntentOkResponse: AskResponse = {
  final_text: 'Aquí tienes las respuestas a tus dos preguntas.',
  outcome: 'ok',
  supported: true,
  intent: 'multi_intent',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: [
    {
      ...captainOkResponse,
      final_text: 'Deberías capitanear a Haaland esta semana.',
    },
    {
      ...transferOkResponse,
      final_text: 'Considera fichar a Salah por Saka.',
    },
  ],
};

/** multi_intent OK — null sub_responses: should fall through to text-only */
export const multiIntentNullSubsResponse: AskResponse = {
  ...multiIntentOkResponse,
  sub_responses: null,
};

/** multi_intent OK — empty sub_responses: should fall through to text-only */
export const multiIntentEmptySubsResponse: AskResponse = {
  ...multiIntentOkResponse,
  sub_responses: [],
};
