/**
 * FPL Grounded Assistant — TypeScript contract types (V2 Phase 1 UI)
 *
 * Derived from:
 *   packages/fpl-grounded-assistant/http_contract_fixtures.json  (V2 Phase 1f)
 *   packages/fpl-grounded-assistant/FINAL_RESPONSE_CONTRACT.md
 *   packages/fpl-grounded-assistant/fpl_grounded_assistant/final_response.py
 *
 * STABILITY GUIDE:
 *   - Stable fields: safe for production logic and rendering decisions.
 *   - Conditional fields: non-null only when intent+outcome=ok matches.
 *     Treat as null for any other outcome.
 *   - DebugBundle: NEVER gate production logic on these fields.
 *     Only present when the request includes debug=true.
 *     Do not set debug=true in production.
 *
 * DEFERRED (Phase 2+):
 *   - Session mode (SessionAskResponse.session_id)
 *   - Squad context auto-fetch
 *   - Structured intent component rendering
 */

// ---------------------------------------------------------------------------
// Outcome + Intent enums
// ---------------------------------------------------------------------------

/** HTTP-200 domain outcome — use for routing decisions in the UI. */
export type Outcome =
  | 'ok'
  | 'unsupported_intent'
  | 'not_found'
  | 'ambiguous'
  | 'missing_arguments'
  | 'error';

/**
 * Intent resolved by the backend. null on unsupported_intent turns.
 *
 * Source: packages/fpl-grounded-assistant/fpl_grounded_assistant/dispatcher.py
 * → SUPPORTED_INTENTS frozenset (excludes INTENT_UNSUPPORTED which is the
 *   internal no-match sentinel and never appears in a response body).
 *
 * current_gameweek / player_summary / player_resolve: simpler intents with no
 * structured conditional metadata field. final_text is the full response for
 * these turns. Phase 2 intent components are not needed for them.
 */
export type Intent =
  | 'captain_score'
  | 'rank_candidates'
  | 'current_gameweek'
  | 'player_summary'
  | 'player_resolve'
  | 'compare_players'
  | 'transfer_advice'
  | 'chip_advice'
  | 'player_fixture_run'
  | 'differential_picks'
  | 'multi_intent';

/**
 * Runtime-accessible list of all backend-supported intent values.
 * Used by contract tests to guard against future intent drift.
 * Must stay in sync with dispatcher.py → SUPPORTED_INTENTS frozenset.
 */
export const SUPPORTED_INTENT_VALUES = [
  'captain_score',
  'rank_candidates',
  'current_gameweek',
  'player_summary',
  'player_resolve',
  'compare_players',
  'transfer_advice',
  'chip_advice',
  'player_fixture_run',
  'differential_picks',
  'multi_intent',
] as const satisfies readonly Intent[];

export type FplPosition = 'FWD' | 'MID' | 'DEF' | 'GKP';

export type CaptainTier =
  | 'safe'
  | 'upside'
  | 'differential'
  | 'avoid'
  | 'low_confidence';

// ---------------------------------------------------------------------------
// intent_hint (V2 Phase 1c)
// ---------------------------------------------------------------------------

/**
 * Allowlisted intent_hint values.
 * Source: http_contract_fixtures.json → _meta.intent_hint_contract.allowlist
 *
 * Invariants (all enforced backend-side):
 *   - deterministic router wins: if the question routes deterministically,
 *     intent_hint is completely ignored.
 *   - allowlisted only: values outside this list are silently ignored.
 *   - safe ignore: invalid hints never raise, never block.
 *   - pre-classifier: fires before LLM, no LLM call needed for routing.
 *   - per-turn in sessions: hint is NOT stored in session state.
 */
export const INTENT_HINT_ALLOWLIST = [
  'captain_score',
  'rank_candidates',
  'compare_players',
  'transfer_advice',
  'chip_advice',
  'player_fixture_run',
  'differential_picks',
] as const;

export type IntentHint = (typeof INTENT_HINT_ALLOWLIST)[number];

// ---------------------------------------------------------------------------
// Request types
// ---------------------------------------------------------------------------

/** Request body for POST /ask (stateless). */
export interface AskRequest {
  /** Required. FPL question in natural language or slash command text. */
  question: string;
  /**
   * Optional pre-classifier routing bias (V2 Phase 1c).
   * Must be in INTENT_HINT_ALLOWLIST. Values outside the list are silently
   * ignored by the backend. Set by slash command selection in the UI.
   */
  intent_hint?: IntentHint | null;
  /**
   * Optional per-turn squad state.
   * Enables budget_constraint and hit_warning signals on transfer advice,
   * and chip_unavailable on chip advice.
   */
  squad_context?: SquadContext | null;
  /**
   * Explicit candidate list for rank_candidates intent.
   * Each entry: { query: string }
   */
  candidates_list?: Array<{ query: string }> | null;
  /**
   * DO NOT set to true in production.
   * Populates the debug bundle — a diagnostic field excluded from
   * the stable production contract.
   */
  debug?: boolean;
}

/** Optional squad state included on every /ask request once the user
 *  connects their FPL team. Deferred to Phase 2 (SquadContextPanel). */
export interface SquadContext {
  itb?: number | null;
  free_transfers?: number | null;
  chips_remaining?: string[] | null;
}

// ---------------------------------------------------------------------------
// Response types — stable fields
// Source: http_contract_fixtures.json → _meta.response_stable_fields
// ---------------------------------------------------------------------------

/**
 * Stable response shape for POST /ask.
 *
 * HTTP 200 does NOT imply outcome='ok'.
 * Always check `supported` and `outcome` before rendering structured metadata.
 *
 * Rendering rule:
 *   - Always render `final_text` — it is always non-empty.
 *   - Show "Respuesta mejorada por IA" label when llm_used=true.
 *   - Structured metadata fields are only relevant when outcome='ok'.
 *   - Phase 2 will render structured metadata components per intent.
 */
export interface AskResponse {
  // Stable fields — always present
  final_text: string;
  outcome: Outcome;
  supported: boolean;
  intent: Intent | null;
  review_passed: boolean;
  llm_used: boolean;
  /**
   * Orchestration outcome — always present in JSON; null when orchestration
   * was not attempted (orch disabled, no API client, or sub-intent call).
   * Independence invariant: a non-OK orch_outcome never changes `outcome`.
   * Safe to ignore; `outcome` is always the authoritative routing field.
   */
  orch_outcome: string | null;

  // Conditional fields — non-null only for matching intent + outcome='ok'
  // Source: http_contract_fixtures.json → _meta.response_conditional_fields
  captain: CaptainScoreMeta | null;
  captain_ranking: RankedCaptainEntry[] | null;
  comparison: ComparisonMeta | null;
  transfer: TransferMeta | null;
  chip: ChipAdviceMeta | null;
  fixture_run: FixtureRunMeta | null;
  differential: DifferentialPicksMeta | null;
  sub_responses: AskResponse[] | null;

  /**
   * Provider degradation flag (Phase 2.6b).
   * true  — LLM call was attempted, failed (provider error), response fell
   *         back to deterministic text silently. Show a muted notice.
   * false — deterministic-only by design, successful LLM, or review failure.
   */
  degraded: boolean;

  /** Resource payload — non-null for @resource turns, null otherwise. (A1 post-graduation) */
  resource_rows: ResourceRows | null;

  // debug_only — null unless request included debug=true.
  // Do not gate production logic on this field.
  debug?: DebugBundle | null;
}

/** Session turn response — same as AskResponse plus session_id. */
export interface SessionAskResponse extends AskResponse {
  session_id: string;
}

// ---------------------------------------------------------------------------
// Structured metadata types (conditional fields)
// Source: fpl_grounded_assistant/final_response.py
// All values are deterministic backend output — nothing computed in the UI.
// ---------------------------------------------------------------------------

/** captain field — non-null when intent=captain_score AND outcome=ok */
export interface CaptainScoreMeta {
  web_name: string;
  team_short: string;
  captain_score: number;
  tier: CaptainTier;
  role_bonus: number;
  set_piece_notes: string[];
}

/** One entry in captain_ranking — non-null when intent=rank_candidates AND outcome=ok */
export interface RankedCaptainEntry {
  rank: number;
  web_name: string;
  team_short: string;
  captain_score: number;
  tier: CaptainTier;
  role_bonus: number;
  set_piece_notes: string[];
}

/** Per-player context within a comparison turn */
export interface ComparisonPlayerContext {
  web_name: string;
  position: FplPosition;
  captain_score: number;
  position_score: number;
  is_home: boolean | null;
  effective_fdr: number;
  role_bonus: number;
  set_piece_notes: string[];
}

/** comparison field — non-null when intent=compare_players AND outcome=ok */
export interface ComparisonMeta {
  winner: string | null;
  margin: number;
  label: 'narrow' | 'moderate' | 'clear';
  reasons: string[];
  player_a: ComparisonPlayerContext | null;
  player_b: ComparisonPlayerContext | null;
}

export type TransferRecommendation =
  | 'transfer_in'
  | 'marginal_transfer_in'
  | 'hold';

/** transfer field — non-null when intent=transfer_advice AND outcome=ok */
export interface TransferMeta {
  player_out: string;
  player_in: string;
  recommendation: TransferRecommendation;
  /** Captain score delta: player_in − player_out. */
  score_delta: number;
  /** Price delta in tenths of £: now_cost_in − now_cost_out. Informational only. */
  price_delta: number;
  reasons: string[];
  budget_constraint: boolean;
  hit_warning: boolean;
}

export type ChipRecommendation =
  | 'conditions_favorable'
  | 'conditions_marginal'
  | 'conditions_unfavorable'
  | 'missing_context';

/** chip field — non-null when intent=chip_advice AND outcome=ok */
export interface ChipAdviceMeta {
  chip: 'triple_captain' | 'wildcard' | 'bench_boost' | 'free_hit';
  recommendation: ChipRecommendation;
  gw: number | null;
  signal_value: number | null;
  signal_label: string | null;
  chip_unavailable: boolean;
}

/** One fixture in a player's upcoming run */
export interface FixtureEntry {
  gameweek: number;
  opponent_short: string;
  is_home: boolean;
  difficulty: 1 | 2 | 3 | 4 | 5;
}

/** fixture_run field — non-null when intent=player_fixture_run AND outcome=ok */
export interface FixtureRunMeta {
  web_name: string;
  team_short: string;
  position: FplPosition;
  horizon: number;
  current_gameweek: number | null;
  fixtures: FixtureEntry[];
}

/** One player in a differential picks result */
export interface DifferentialEntry {
  rank: number;
  web_name: string;
  team_short: string;
  position: FplPosition;
  captain_score: number;
  position_score?: number | null;
  ownership: number;
  now_cost: number;
  is_home: boolean | null;
}

/** differential field — non-null when intent=differential_picks AND outcome=ok */
export interface DifferentialPicksMeta {
  ownership_threshold: number;
  top_n: number;
  picks: DifferentialEntry[];
}

// ---------------------------------------------------------------------------
// Resource rows types (A2 post-graduation — @resource rendering)
// ---------------------------------------------------------------------------

/** One row in a metric-ranked resource (top_form/top_xg/top_points/top_minutes/popular). */
export interface ResourceRankingRow {
  web_name: string;
  team_short: string;
  position: FplPosition;
  value: number;
}

/** One row in @injuries. */
export interface InjuryRow {
  web_name: string;
  team_short: string;
  position: FplPosition;
  status_label: string;
  chance_of_playing: number | null;
  news: string;
  news_added: string | null;
}

/** Identifier for the 6 supported resources. */
export type ResourceKind =
  | 'top_form'
  | 'top_xg'
  | 'top_points'
  | 'top_minutes'
  | 'popular'
  | 'injuries';

/** Full resource_rows payload, populated for @resource turns. */
export interface ResourceRows {
  resource: ResourceKind;
  title: string;
  columns: string[];
  rows: ResourceRankingRow[] | InjuryRow[];
  data_age?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Debug bundle — debug_only, never in production
// Source: http_contract_fixtures.json → _meta.response_debug_only_fields
// ---------------------------------------------------------------------------

/** Present only when request debug=true. Excluded from stable contract. */
export interface DebugBundle {
  response_text: string;
  llm_text: string;
  violations: string[];
  prompt_used: string;
  model: string;
  /** null=deterministic routing, 'intent_hint'=hint fired, 'llm_classifier'=LLM used */
  classification_source: 'intent_hint' | 'llm_classifier' | null;
}
