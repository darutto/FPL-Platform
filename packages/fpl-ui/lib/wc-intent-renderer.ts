/**
 * WC intent renderer selection (Iteration 3 — stateless).
 *
 * Pure function — no React, no side effects. Sibling of
 * lib/intent-renderer.ts for the World Cup domain: returns which structured
 * card should render under final_text, or null for text-only.
 *
 * Rendering invariants (same as FPL):
 *   - Always render final_text first; structured components are additive.
 *   - Only render when outcome === 'ok' AND the matching field is non-null
 *     (and, for list fields, non-empty).
 *
 * Precedence matters when multiple fields are non-null in the same turn
 * (e.g. a multi-tool answer) — standings and scorer/fantasy rankings are
 * the most specific signals, fixtures the most general.
 */
import type { WcAskResponse } from './wc-types';

export type WcIntentView =
  | 'bracket'
  | 'standings'
  | 'top_scorers'
  | 'top_assists'
  | 'fantasy_top_players'
  | 'players_info'
  | 'squad'
  | 'head_to_head'
  | 'wc2022_results'
  | 'fixtures'
  | 'web_search';

/**
 * Given a WC backend response, returns which structured card to render
 * below final_text, or null if the turn should be text-only.
 */
export function selectWcIntentView(response: WcAskResponse): WcIntentView | null {
  if (response.outcome !== 'ok') return null;

  if (response.bracket != null && response.bracket.ties.length > 0) {
    return 'bracket';
  }
  if (response.standings != null && Object.keys(response.standings).length > 0) {
    return 'standings';
  }
  if (response.top_scorers != null && response.top_scorers.length > 0) {
    return 'top_scorers';
  }
  if (response.top_assists != null && response.top_assists.length > 0) {
    return 'top_assists';
  }
  if (response.fantasy_top_players != null && response.fantasy_top_players.length > 0) {
    return 'fantasy_top_players';
  }
  if (response.players_info != null && response.players_info.length > 0) {
    return 'players_info';
  }
  if (response.squad != null && response.squad.players.length > 0) {
    return 'squad';
  }
  if (response.head_to_head != null) {
    return 'head_to_head';
  }
  if (response.wc2022_results != null && response.wc2022_results.length > 0) {
    return 'wc2022_results';
  }
  if (response.fixtures != null && response.fixtures.length > 0) {
    return 'fixtures';
  }
  // Lowest precedence: a deterministic tool answer always wins over web search.
  // Rendering this view makes MessageList show the card alone (no duplicate
  // text bubble) — the card's `summary` already carries the Spanish synthesis.
  if (response.web_search != null) {
    return 'web_search';
  }

  return null;
}
