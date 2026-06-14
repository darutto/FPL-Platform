/**
 * World Cup assistant — TypeScript contract types (Iteration 2/3 UI).
 *
 * Mirrors packages/worldcup-assistant/worldcup_assistant/wc_server.py
 * AskRequest/AskResponse. final_text + the stable status fields are always
 * populated; the structured card fields (standings/top_scorers/
 * fantasy_top_players/fixtures, added in Iteration 3) are additive and
 * non-null only when the matching tool was the most recent of its kind in
 * the backend's tool loop on an ok turn.
 *
 * Deliberately NOT reusing lib/types.ts's AskResponse — the WC backend has
 * no deterministic intent router (intent is always "wc_info") and no FPL
 * conditional fields, so a separate minimal contract avoids widening the
 * FPL Intent/Outcome unions for a domain that doesn't use them.
 */
import type { Outcome } from './types';

/** One row of a group standings table (already locale_es-localized). */
export interface WcStandingsRow {
  team: string;
  group: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  points: number;
  goal_difference: number;
}

/** One row of the tournament top-scorers ranking. */
export interface WcScorerRow {
  player: string;
  team: string | null;
  goals: number;
  assists: number;
}

/** One row of the tournament top-assists ranking (sibling of WcScorerRow,
 *  same shape, sorted by assists first). */
export type WcAssistRow = WcScorerRow;

/** One row of the FIFA Fantasy points leaderboard. */
export interface WcFantasyPlayerRow {
  player: string;
  team: string | null;
  position: string;
  total_points: number;
  avg_points: number;
  form: number;
  price: number;
}

/** One player in a national team's full tournament roster. */
export interface WcSquadPlayerRow {
  name: string;
  position: string;
  price: number;
}

/** Full tournament squad for one national team (get_squad). */
export interface WcSquadPayload {
  team: string;
  group: string;
  players: WcSquadPlayerRow[];
}

/** Single-player profile (get_player_info) — '/jugador' and '/comparar'. */
export interface WcPlayerInfoRow {
  player: string;
  team: string | null;
  position: string;
  price: number;
  total_points: number;
  avg_points: number;
  form: number;
  goals: number;
  assists: number;
}

/** WC2022 (Qatar) tournament aggregate for a player who also played in 2022 (get_player_wc2022_stats). */
export interface WcPlayer2022Stats {
  name: string;
  team: string;
  appearances: number;
  minutes: number;
  goals: number;
  assists: number;
  yellow_cards: number;
  red_cards: number;
  saves: number;
  key_passes: number;
  avg_rating: number | null;
  position: string | null;
  season: number;
}

/** One match (fixture, result, or live game) — already locale_es-localized. */
export interface WcMatchRow {
  match_id: string | number;
  round: number | null;
  date: string | null;
  venue: string | null;
  venue_city: string | null;
  home_team: string;
  away_team: string;
  home_score: number | null;
  away_score: number | null;
  /** Penalty shootout score (WC2022 results only); null for non-shootout matches. */
  penalty_home?: number | null;
  penalty_away?: number | null;
  status: string;
  minute: number | string | null;
  stage: string;
}

/** Head-to-head record between two national teams (get_head_to_head). */
export interface WcHeadToHeadPayload {
  matches: WcMatchRow[];
  note: string;
}

/** Request body for POST /ask (WC backend, via /api/wc-proxy). */
export interface WcAskRequest {
  /** Required. World Cup question in natural language or slash command text. */
  question: string;
  /** Optional wc:-namespaced session id for multi-turn history. */
  session_id?: string | null;
  /** DO NOT set to true in production — populates the debug bundle. */
  debug?: boolean;
}

/** Response shape for POST /ask (WC backend). */
export interface WcAskResponse {
  final_text: string;
  outcome: Outcome;
  supported: boolean;
  /** Always "wc_info" — the orchestrator IS the router for this domain. */
  intent: string;
  review_passed: boolean;
  llm_used: boolean;
  debug?: Record<string, unknown> | null;
  sub_responses?: Record<string, unknown>[] | null;
  orch_outcome?: string | null;
  degraded: boolean;
  session_id?: string | null;
  /** Group standings keyed by group letter (e.g. "A"), non-null when get_standings was the last matching tool call. */
  standings?: Record<string, WcStandingsRow[]> | null;
  /** Tournament top-scorers ranking, non-null when get_top_scorers was the last matching tool call. */
  top_scorers?: WcScorerRow[] | null;
  /** Tournament top-assists ranking, non-null when get_top_assists was the last matching tool call. */
  top_assists?: WcAssistRow[] | null;
  /** FIFA Fantasy points leaderboard, non-null when get_fantasy_top_players was the last matching tool call. */
  fantasy_top_players?: WcFantasyPlayerRow[] | null;
  /** Fixtures/results/live matches, non-null when get_fixtures or get_live_scores was the last matching tool call. */
  fixtures?: WcMatchRow[] | null;
  /** Full tournament squad, non-null when get_squad was the last matching tool call. */
  squad?: WcSquadPayload | null;
  /** Head-to-head record, non-null when get_head_to_head was the last matching tool call. */
  head_to_head?: WcHeadToHeadPayload | null;
  /** One entry per distinct get_player_info call (1 = '/jugador', 2+ = '/comparar'). */
  players_info?: WcPlayerInfoRow[] | null;
  /** WC2022 supplementary stats, one entry per players_info player who also played in Qatar 2022 (not all will have one). */
  wc2022_stats?: WcPlayer2022Stats[] | null;
  /** WC2022 (Qatar) match results, non-null when get_wc2022_results was the last matching tool call. */
  wc2022_results?: WcMatchRow[] | null;
  /** True iff at least one tool call this turn returned grounded data (status "ok").
   *  Drives the UI origin badge ("Datos verificados" vs "Sin datos del torneo") —
   *  llm_used is true on nearly every WC turn so it isn't a useful signal here. */
  grounded?: boolean;
}

/** Response shape for POST /session (WC backend — mints a wc:-namespaced id). */
export interface WcCreateSessionResult {
  session_id: string;
  created_at: number;
  expires_after_seconds: number;
}

export class WcApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'WcApiError';
  }
}
