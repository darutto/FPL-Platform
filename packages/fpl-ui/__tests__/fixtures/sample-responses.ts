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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
    stat_comparison: {
      rows: [
        { key: 'form', label: 'Forma', kind: 'performance',
          value_a: { value: 9.5, display: '9.5' }, value_b: { value: 8.0, display: '8.0' }, better: 'a' },
        { key: 'total_points', label: 'Puntos totales', kind: 'performance',
          value_a: { value: 210, display: '210' }, value_b: { value: 195, display: '195' }, better: 'a' },
        { key: 'price_m', label: 'Precio', kind: 'context',
          value_a: { value: 14.5, display: '£14.5m' }, value_b: { value: 13.5, display: '£13.5m' }, better: null },
        { key: 'ownership_percent', label: 'Propiedad %', kind: 'context',
          value_a: { value: 52.3, display: '52.3%' }, value_b: { value: 64.1, display: '64.1%' }, better: null },
        { key: 'goals', label: 'Goles', kind: 'performance',
          value_a: { value: 22, display: '22' }, value_b: { value: 18, display: '18' }, better: 'a' },
        { key: 'assists', label: 'Asistencias', kind: 'performance',
          value_a: { value: 5, display: '5' }, value_b: { value: 9, display: '9' }, better: 'b' },
      ],
    },
  },
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
    stat_comparison: null,
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
    stat_comparison: null,
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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
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

/** transfer_suggestion OK — TransferSuggestionCard should render (Phase 2.6h) */
export const transferSuggestionOkResponse: AskResponse = {
  final_text: 'Los mejores objetivos de transferencia para medio son Palmer, Saka y Gordon.',
  outcome: 'ok',
  supported: true,
  intent: 'transfer_suggestion',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  fixture_outlook: null,
  transfer_suggestion: {
    position: 'MID',
    position_label: 'Mediocampistas',
    team_short: null,
    team_name: null,
    max_price: 9.5,
    horizon: 5,
    top_n: 3,
    picks: [
      {
        rank: 1,
        web_name: 'Palmer',
        team_short: 'CHE',
        position: 'MID',
        now_cost: 85,
        now_cost_m: 8.5,
        form: 7.4,
        avg_fdr: 2.4,
        difficulty_label: 'fácil',
        composite_score: 82.1,
        ownership: 42.3,
      },
      {
        rank: 2,
        web_name: 'Saka',
        team_short: 'ARS',
        position: 'MID',
        now_cost: 90,
        now_cost_m: 9.0,
        form: 6.8,
        avg_fdr: 2.8,
        difficulty_label: 'moderado',
        composite_score: 78.5,
        ownership: 35.1,
      },
      {
        rank: 3,
        web_name: 'Gordon',
        team_short: 'NEW',
        position: 'MID',
        now_cost: 75,
        now_cost_m: 7.5,
        form: 6.1,
        avg_fdr: 3.0,
        difficulty_label: 'moderado',
        composite_score: 71.9,
        ownership: 18.7,
      },
    ],
  },
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
};

/** transfer_suggestion OK — empty picks (edge case: should fall through to text-only) */
export const transferSuggestionEmptyResponse: AskResponse = {
  ...transferSuggestionOkResponse,
  transfer_suggestion: {
    position: 'MID',
    position_label: 'Mediocampistas',
    team_short: null,
    team_name: null,
    max_price: null,
    horizon: 5,
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
  fixture_outlook: null,
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
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
};

/** multi_intent OK — null sub_responses: should fall through to text-only */
export const multiIntentNullSubsResponse: AskResponse = {
  ...multiIntentOkResponse,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
};

/** multi_intent OK — empty sub_responses: should fall through to text-only */
export const multiIntentEmptySubsResponse: AskResponse = {
  ...multiIntentOkResponse,
  sub_responses: [],
};

// ---------------------------------------------------------------------------
// generic_card fixtures (Track B) — price_changes-style fallback card
// ---------------------------------------------------------------------------

/** price_changes OK — full generic_card: hero + pills + table + footer */
export const genericCardOkResponse: AskResponse = {
  final_text: 'Estos son los mayores cambios de precio hoy.',
  outcome: 'ok',
  supported: true,
  intent: 'price_changes',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
  generic_card: {
    accent: 'gold',
    title: 'Cambios de precio',
    subtitle: 'Actualizado hoy a las 02:00',
    hero: { value: '12', label: 'Jugadores subieron de precio', tone: 'good' },
    pills: [
      { label: '8 suben', tone: 'good' },
      { label: '4 bajan', tone: 'bad' },
    ],
    columns: [
      { header: 'Jugador', align: 'left', kind: 'text' },
      { header: 'Equipo', align: 'left', kind: 'text' },
      { header: 'Cambio', align: 'right', kind: 'mono' },
    ],
    rows: [
      ['Haaland', 'MCI', '+0.1'],
      ['Salah', 'LIV', '+0.1'],
      ['Rashford', 'MUN', '-0.1'],
    ],
    footer: 'Los precios pueden cambiar hasta la medianoche.',
  },
};

/** generic_card OK — minimal: title only, no hero/pills/table/footer */
export const genericCardMinimalResponse: AskResponse = {
  ...genericCardOkResponse,
  generic_card: {
    accent: 'gray',
    title: 'Sin datos adicionales',
    subtitle: null,
    hero: null,
    pills: [],
    columns: [],
    rows: [],
    footer: null,
  },
};

/** generic_card OK — hero with no tone (defaults to neutral/white text) */
export const genericCardNoHeroToneResponse: AskResponse = {
  ...genericCardOkResponse,
  generic_card: {
    ...genericCardOkResponse.generic_card!,
    hero: { value: '5', label: 'Jornada actual', tone: null },
  },
};

/**
 * Orchestrator atomic-tool ranking card — the open-ended "top players" case.
 * The tool (rank_players_by_metric) has no _TOOL_TO_INTENT entry, so intent is
 * null here (the frontend's representation of an unmapped/unsupported turn — the
 * backend's raw "unsupported" string maps to null in the Intent union), yet
 * outcome is 'ok' and generic_card is populated by the orchestrator overlay.
 * final_text is the raw ASCII table the card replaces.
 */
export const orchestratorRankCardResponse: AskResponse = {
  final_text:
    'Top 3 jugadores por total_points:\n  #  | Jugador | Equipo | Pos | Valor métrica\n  ---|---------|--------|-----|---------------\n    1 | Haaland | MCI    | FWD | 239',
  outcome: 'ok',
  supported: true,
  intent: null,
  review_passed: true,
  llm_used: true,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: 'ok',
  degraded: false,
  resource_rows: null,
  generic_card: {
    accent: 'turquoise',
    title: 'TOP 3 · Puntos',
    subtitle: null,
    hero: { value: '239', label: 'Puntos', tone: null },
    pills: [],
    columns: [
      { header: '#', align: 'right', kind: 'mono' },
      { header: 'Jugador', align: 'left', kind: 'text' },
      { header: 'Equipo', align: 'left', kind: 'text' },
      { header: 'Pos', align: 'left', kind: 'text' },
      { header: 'Puntos', align: 'right', kind: 'mono' },
    ],
    rows: [
      ['1', 'Haaland', 'MCI', 'FWD', '239'],
      ['2', 'B.Fernandes', 'MUN', 'MID', '180'],
      ['3', 'Palmer', 'CHE', 'MID', '175'],
    ],
    footer: null,
  },
};

/** injury_list OK — routes to InjuryListTable (generic_card adapter) */
export const injuryListGenericResponse: AskResponse = {
  final_text: 'Estas son las lesiones más recientes.',
  outcome: 'ok',
  supported: true,
  intent: 'injury_list',
  review_passed: true,
  llm_used: false,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: null,
  degraded: false,
  resource_rows: null,
  generic_card: {
    accent: 'coral',
    title: 'Lesiones',
    subtitle: null,
    hero: null,
    pills: [],
    columns: [
      { header: 'Jugador', align: 'left', kind: 'text' },
      { header: 'Equipo', align: 'left', kind: 'text' },
      { header: 'Pos', align: 'left', kind: 'text' },
      { header: 'Estado', align: 'left', kind: 'badge' },
      { header: '%', align: 'right', kind: 'text' },
      { header: 'Noticia', align: 'left', kind: 'text' },
      { header: 'Fecha', align: 'left', kind: 'text' },
    ],
    rows: [
      ['Saka', 'ARS', 'MID', 'Duda', '75', 'Molestia en el tobillo', '2026-07-15T00:00:00Z'],
      ['Isak', 'NEW', 'FWD', 'Lesionado', '0', 'Rotura muscular, baja varias semanas', '2026-07-10T00:00:00Z'],
    ],
    footer: null,
  },
};

/**
 * injury_list OK — generic_card present but empty rows: the injury_list
 * special-case requires non-empty rows, so this falls through to the plain
 * 'generic' view (generic_card is still non-null) rather than 'generic_injuries'.
 */
export const injuryListGenericEmptyResponse: AskResponse = {
  ...injuryListGenericResponse,
  generic_card: {
    ...injuryListGenericResponse.generic_card!,
    rows: [],
  },
};

/** player_snapshot OK — available player, PlayerCard should render */
export const playerSnapshotOkResponse: AskResponse = {
  final_text: 'Haaland: 239 puntos esta temporada.',
  outcome: 'ok',
  supported: true,
  intent: 'player_snapshot',
  review_passed: true,
  llm_used: true,
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  fixture_outlook: null,
  sub_responses: null,
  orch_outcome: 'ok',
  degraded: false,
  resource_rows: null,
  player_snapshot: {
    id: 351,
    web_name: 'Haaland',
    team_short: 'MCI',
    position: 'FWD',
    minutes_played_season: 2953,
    status: 'Available',
    news: '',
    news_added: null,
    chance_of_playing_this_round: null,
    form: 6.8,
    total_points: 239,
    points_per_game: 6.8,
    expected_goals: 25.5,
    expected_assists: 2.67,
    expected_goal_involvements: 28.17,
    ict_index: 302.3,
    expected_goals_per_90: 0.78,
    expected_assists_per_90: 0.08,
    expected_goal_involvements_per_90: 0.86,
    ict_index_per_90: 9.21,
    defensive_contribution: 116,
    defensive_contribution_per_90: 3.54,
    now_cost: 155,
    selected_by_percent: 74.2,
    transfers_in_event: 12345,
    transfers_out_event: 6789,
    fixtures: [
      { gameweek: 29, opponent_short: 'LIV', is_home: true, difficulty: 4 },
      { gameweek: 30, opponent_short: 'ARS', is_home: false, difficulty: 5 },
    ],
  },
};

/** player_snapshot OK — no team_fixtures coverage, fixture strip omitted */
export const playerSnapshotNoFixturesResponse: AskResponse = {
  ...playerSnapshotOkResponse,
  player_snapshot: {
    ...playerSnapshotOkResponse.player_snapshot!,
    fixtures: [],
  },
};

/** player_snapshot OK — doubtful player with news, exercises the warn-tone status badge */
export const playerSnapshotDoubtfulResponse: AskResponse = {
  ...playerSnapshotOkResponse,
  final_text: 'Saka: duda para la próxima jornada.',
  player_snapshot: {
    ...playerSnapshotOkResponse.player_snapshot!,
    web_name: 'Saka',
    team_short: 'ARS',
    status: 'Doubtful',
    news: 'Molestia en el tobillo, duda para la próxima jornada',
    chance_of_playing_this_round: 75,
  },
};
