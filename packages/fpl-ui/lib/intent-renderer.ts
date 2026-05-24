/**
 * Intent renderer selection (V2 Phase 2c — stateless).
 *
 * Pure function — no React, no side effects. Returns which structured
 * component should render under final_text, or null for text-only.
 *
 * Rendering invariants (from FINAL_RESPONSE_CONTRACT.md):
 *   - Always render final_text first; structured components are additive.
 *   - Only render when outcome === 'ok' AND the matching conditional field
 *     is non-null. The non-null check is required: the field CAN be null
 *     on ok turns if the intent was resolved by a sub-path.
 *   - Do not gate any rendering logic on debug-only fields.
 *
 * RENDERED (Phase 2c):
 *   captain_score      → 'captain'            (captain field non-null)
 *   compare_players    → 'comparison'         (comparison field non-null)
 *   rank_candidates    → 'ranking'            (captain_ranking non-null, length > 0)
 *   transfer_advice    → 'transfer'           (transfer field non-null)
 *   chip_advice        → 'chip'               (chip field non-null)
 *   player_fixture_run → 'fixture_run'        (fixture_run non-null, fixtures.length > 0)
 *   differential_picks → 'differential'       (differential non-null, picks.length > 0)
 *   @top_form/xg/etc.  → 'resource_ranking'  (resource_rows non-null, resource != 'injuries')
 *   @injuries          → 'resource_injuries'  (resource_rows non-null, resource === 'injuries')
 *
 * TEXT-ONLY (Phase 2c, structured rendering deferred):
 *   multi_intent, current_gameweek, player_summary, player_resolve
 */
import type { AskResponse } from './types';

export type IntentView =
  | 'captain'
  | 'comparison'
  | 'ranking'
  | 'transfer'
  | 'chip'
  | 'fixture_run'
  | 'differential'
  | 'multi_intent'
  | 'resource_ranking'
  | 'resource_injuries';

/**
 * Given a backend response, returns which structured intent component to
 * render below final_text, or null if the turn should be text-only.
 *
 * Called once per assistant message bubble.
 */
export function selectIntentView(response: AskResponse): IntentView | null {
  if (response.outcome !== 'ok') return null;

  // Resource rows — most specific signal: if present, render the resource view
  // regardless of intent. (A2 post-graduation)
  if (response.resource_rows != null) {
    return response.resource_rows.resource === 'injuries'
      ? 'resource_injuries'
      : 'resource_ranking';
  }

  if (response.intent === 'captain_score' && response.captain != null) {
    return 'captain';
  }
  if (response.intent === 'compare_players' && response.comparison != null) {
    return 'comparison';
  }
  if (
    response.intent === 'rank_candidates' &&
    response.captain_ranking != null &&
    response.captain_ranking.length > 0
  ) {
    return 'ranking';
  }
  if (response.intent === 'transfer_advice' && response.transfer != null) {
    return 'transfer';
  }
  if (response.intent === 'chip_advice' && response.chip != null) {
    return 'chip';
  }
  if (
    response.intent === 'player_fixture_run' &&
    response.fixture_run != null &&
    response.fixture_run.fixtures.length > 0
  ) {
    return 'fixture_run';
  }
  if (
    response.intent === 'differential_picks' &&
    response.differential != null &&
    response.differential.picks.length > 0
  ) {
    return 'differential';
  }
  if (
    response.intent === 'multi_intent' &&
    response.sub_responses != null &&
    response.sub_responses.length > 0
  ) {
    return 'multi_intent';
  }

  return null;
}
