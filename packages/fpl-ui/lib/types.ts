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
  // A prompt (e.g. bare `/comparar`) needs more info before it can run. Carries
  // `suggestions` for the Guided Comparison chip wizard.
  | 'needs_clarification'
  | 'error'
  | 'quota_exceeded'
  // A premium feature (web search) was requested by an ineligible tier.
  | 'feature_gated';

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
  | 'multi_intent'
  | 'player_form'
  | 'injury_list'
  | 'price_changes'
  | 'team_fixture_calendar'
  | 'team_schedule'
  | 'position_fixture_run'
  | 'transfer_suggestion'
  // Track D / FI4: renderable orchestrator-routed intent (the ticker card).
  // Intentionally NOT in the deterministic classifier (keeps backend parity).
  | 'fixture_outlook'
  // T4b: orchestrator-only renderable intent (in dispatcher._TOOL_TO_INTENT
  // but deliberately NOT in SUPPORTED_INTENTS/the classifier).
  | 'zonal_opportunity';

/**
 * Runtime-accessible list of every intent value that can appear in
 * `response.intent`. Used by contract tests to guard against intent drift.
 * Tracks the dispatcher.py INTENT_* constants (minus the "unsupported"
 * sentinel) — this is a superset of the backend SUPPORTED_INTENTS frozenset:
 * `multi_intent` (synthesised by the orchestration layer), `fixture_outlook`
 * (Track D/FI4), and `zonal_opportunity` (T4b) are renderable
 * orchestrator-routed intents that appear in responses but are not
 * deterministic classifier targets.
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
  'player_form',
  'injury_list',
  'price_changes',
  'team_fixture_calendar',
  'team_schedule',
  'position_fixture_run',
  'transfer_suggestion',
  'fixture_outlook',   // Track D/FI4 — renderable orchestrator-routed intent
  'zonal_opportunity', // T4b — renderable orchestrator-routed intent
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
  'fixture_outlook', // Track D/FI4-3 — /calendario ticker
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
  /**
   * Explicit per-turn opt-in for the premium web-search tool (globe toggle).
   * Only takes effect when the caller's tier is in the backend's
   * WEB_SEARCH_TIERS allowlist — see lib/tiers.ts QUOTA_BUCKETS.webSearch.
   */
  web_search_requested?: boolean;
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
  /**
   * transfer_suggestion field — non-null when intent=transfer_suggestion AND
   * outcome=ok (Phase 2.6h). Optional because pre-2.6h fixtures/serialisers
   * omit it (same convention as zonal_opportunity / fixture_outlook).
   */
  transfer_suggestion?: TransferSuggestionMeta | null;
  /**
   * fixture_outlook field — non-null when intent=fixture_outlook AND
   * outcome=ok (Track D/FI4). Optional because pre-FI4 fixtures/serialisers
   * omit it (same convention as zonal_opportunity).
   */
  fixture_outlook?: FixtureOutlookMeta | null;
  sub_responses: AskResponse[] | null;
  /**
   * Defensive zones payload (T4b) — non-null when intent=zonal_opportunity
   * AND outcome=ok. Optional because pre-T4b fixtures/serialisers omit it.
   */
  zonal_opportunity?: DefensiveZonesMeta | null;

  /**
   * Provider degradation flag (Phase 2.6b).
   * true  — LLM call was attempted, failed (provider error), response fell
   *         back to deterministic text silently. Show a muted notice.
   * false — deterministic-only by design, successful LLM, or review failure.
   */
  degraded: boolean;

  /** Resource payload — non-null for @resource turns, null otherwise. (A1 post-graduation) */
  resource_rows: ResourceRows | null;

  /**
   * Generic card payload (Track B) — non-null when outcome='ok' and the
   * intent has no bespoke structured component. Renders via GenericCard,
   * the fallback that closes the "plain text block" gap. Optional because
   * pre-generic-card fixtures/serialisers omit it (same convention as
   * zonal_opportunity/web_search). Can also appear on entries inside
   * `sub_responses` (multi_intent nests full AskResponse objects).
   */
  generic_card?: GenericCardMeta | null;

  /**
   * Web search payload — non-null when the premium search_web tool ran
   * end-to-end (outcome='ok'). Unverified AI synthesis over live web
   * sources — never implies "grounded" data. Parity with the WC chat's
   * web_search field. Optional because pre-web-search fixtures/serialisers
   * omit it (same convention as zonal_opportunity).
   */
  web_search?: WebSearchPayload | null;

  /**
   * Guided Comparison suggestions — non-null only on a compare_players
   * needs_clarification turn (bare or partial `/comparar`). Each item is a
   * tappable chip {label, send_text} sourced deterministically from the
   * most transferred-in players this gameweek. The UI turns these into a
   * two-step chip wizard whose final send is a normal `comparar A vs B`
   * question. Optional because pre-guided-comparison fixtures/serialisers omit
   * it (same convention as generic_card/web_search).
   */
  suggestions?: Suggestion[] | null;

  // debug_only — null unless request included debug=true.
  // Do not gate production logic on this field.
  debug?: DebugBundle | null;
}

/** A single tappable suggestion chip (Guided Comparison). */
export interface Suggestion {
  /** Chip label — short player web_name. */
  label: string;
  /** Text sent through the normal send path when the chip is tapped. */
  send_text: string;
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

/**
 * One pick in a transfer_suggestion result (Phase 2.6h).
 * Source: fpl_grounded_assistant/final_response.py → TransferSuggestionEntry.
 */
export interface TransferSuggestionEntry {
  rank: number;
  web_name: string;
  team_short: string;
  position: string;
  /** now_cost in tenths of £ (e.g. 75 → £7.5m). */
  now_cost: number;
  /** now_cost pre-divided to £m (e.g. 7.5). */
  now_cost_m: number;
  form: number;
  avg_fdr: number;
  difficulty_label: string;
  composite_score: number;
  ownership: number;
}

/** transfer_suggestion field — non-null when intent=transfer_suggestion AND outcome=ok */
export interface TransferSuggestionMeta {
  /** Canonical FPL position code or "ALL". */
  position: string;
  position_label: string;
  /** null when no club filter was applied (Phase 2.6i). */
  team_short: string | null;
  team_name: string | null;
  max_price: number | null;
  horizon: number;
  top_n: number;
  picks: TransferSuggestionEntry[];
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
// Fixture outlook types (Track D / FI4 — two-axis ticker + run detection)
// ---------------------------------------------------------------------------

export type FixtureAxis = 'attack' | 'defence';
export type OutlookClass = 'good' | 'bad' | 'neutral' | 'blank';

/** One fixture within a gameweek (two in a DGW). */
export interface FixtureOutlookCell {
  opponent_short: string;
  is_home: boolean;
  /** 1=easiest … 5=hardest, on the meta's axis. */
  band: number;
}

/** One gameweek column for a team in the ticker. */
export interface FixtureOutlookGW {
  gameweek: number;
  /** null = blank GW. */
  band: number | null;
  klass: OutlookClass;
  is_dgw: boolean;
  is_bgw: boolean;
  fixtures: FixtureOutlookCell[];
}

/** A detected good/bad run (≥3 consecutive GWs). */
export interface FixtureOutlookRun {
  type: 'good' | 'bad';
  start_gw: number;
  end_gw: number;
  length: number;
  intensity: 'strong' | 'mild';
}

/** One team's row in the ticker. */
export interface TeamOutlook {
  team_short: string;
  team_name: string;
  axis: FixtureAxis;
  avg_band: number | null;
  verdict: string;
  series: FixtureOutlookGW[];
  runs: FixtureOutlookRun[];
}

/** fixture_outlook field — non-null when intent=fixture_outlook AND outcome=ok */
export interface FixtureOutlookMeta {
  axis: FixtureAxis;
  horizon: number;
  current_gameweek: number | null;
  teams: TeamOutlook[];
}

// ---------------------------------------------------------------------------
// Web search types (premium, opt-in — parity with WcWebSearchPayload)
// ---------------------------------------------------------------------------

/** One cited source in a web_search turn. */
export interface WebSearchResult {
  title: string;
  snippet: string;
  url: string;
  source: string;
  published: string | null;
}

/** web_search field — non-null when the search_web tool ran end-to-end. */
export interface WebSearchPayload {
  topic: string | null;
  summary: string;
  results: WebSearchResult[];
  timestamp: string;
}

// ---------------------------------------------------------------------------
// Defensive zones types (T4b — zonal_opportunity card)
// Source: fpl_grounded_assistant/final_response.py → DefensiveZonesMeta
// ---------------------------------------------------------------------------

/**
 * Lateral band of the penalty box in the attacker/opportunity frame — "the
 * flank you attack down" (flank-mirror fix 2026-07-09: verdict, zones and
 * pitch all speak this one frame; no defender flip anywhere). The pitch view
 * renders left→'Izquierda' etc. as the attacker faces the goal (goal at the
 * top, attacker's left = viewer's left).
 */
export type ZoneLateral = 'left' | 'central' | 'right';

/**
 * Opportunity coding for a zone — encodes YOUR attacking advantage:
 * 'opp' = clearly above league average (turquoise), 'warm' = slightly above
 * (amber/gold), 'cool' = at/below (grey). Never coral/red for a strong zone.
 */
export type OpportunityLevel = 'opp' | 'warm' | 'cool';

/** One in-box lateral cell of the pitch view (always exactly 3, in order). */
export interface DefensiveZoneCell {
  lateral: ZoneLateral;
  /** (xGA/game ÷ league avg − 1) × 100 — deviation from an average team. */
  pct_over_avg: number;
  opportunity_level: OpportunityLevel;
}

/** One row of the "Quién lo explota" zone-fit table. */
export interface ZonalExploiter {
  rank: number;
  web_name: string;
  team_short: string;
  /** '' when the backend's best-effort FPL name join missed. */
  position: string;
  /** Engine zone key, e.g. 'in-box / left' (attacker frame). */
  zone: string;
  /** 0–10 zone-fit heuristic — relative within this answer only. */
  fit_score: number;
}

/** zonal_opportunity field — non-null when intent=zonal_opportunity AND outcome=ok */
export interface DefensiveZonesMeta {
  opponent: string;
  weakness_label: string;
  verdict: string;
  zones: DefensiveZoneCell[];
  exploiters: ZonalExploiter[];
  penalty_xga_per_game: number;
  ai_active: boolean;
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
// Generic card types (Track B — generic_card payload)
// Fallback structured card for intents without a bespoke component.
// ---------------------------------------------------------------------------

/** Semantic tone used by generic_card pills/hero — maps to Bendito Fantasy
 *  turquoise/gold/coral/gray via lib/theme GENERIC_TONE_CLASSES. */
export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

/** Accent palette the backend can select for a generic_card. */
export type GenericCardAccent =
  | 'turquoise'
  | 'cyan'
  | 'coral'
  | 'gold'
  | 'purple'
  | 'gray';

/** Big Archivo Black hero stat — optional single headline number. */
export interface GenericCardHero {
  value: string;
  label: string;
  tone: Tone | null;
}

/** One tinted pill in the title row. */
export interface GenericCardPill {
  label: string;
  tone: Tone;
}

/** One CardTable column descriptor. */
export interface GenericCardColumn {
  header: string;
  align: 'left' | 'right';
  kind: 'text' | 'mono' | 'badge';
}

/**
 * generic_card field — non-null when outcome='ok' and the intent has no
 * bespoke structured component (see AskResponse.generic_card).
 *
 * rows: each entry's length MUST equal columns.length (backend-enforced;
 * the UI does not validate this at runtime — CardTable renders defensively
 * by index and drops cells past columns.length).
 */
export interface GenericCardMeta {
  accent: GenericCardAccent;
  title: string;
  subtitle: string | null;
  hero: GenericCardHero | null;
  pills: GenericCardPill[];
  columns: GenericCardColumn[];
  rows: string[][];
  footer: string | null;
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

// ---------------------------------------------------------------------------
// Quota types (P3 — visual quota indicator)
// Mirrors fpl_grounded_assistant.quota.QuotaCheck dataclass.
// ---------------------------------------------------------------------------

/**
 * Response shape for GET /quota (forwarded via GET /api/quota).
 * Used by QuotaIndicator to display daily/monthly remaining counts.
 */
export interface QuotaStatus {
  allowed: boolean;
  tier: string;
  daily_tokens_used: number;
  daily_message_count: number;
  monthly_tokens_used: number;
  monthly_message_count: number;
  daily_token_cap: number;
  monthly_token_cap: number;
  daily_message_cap: number;
  monthly_message_cap: number;
  /** Non-null when allowed=false — machine-readable reason code. */
  reason: string | null;
  /** Spanish upgrade prompt — non-null when allowed=false. */
  upgrade_prompt_es: string | null;
  /** English upgrade prompt — non-null when allowed=false. */
  upgrade_prompt_en: string | null;
}
