/**
 * Player-disambiguation wizard arming — the UI's single source for "does this
 * turn's `suggestions` field carry pick-one chips, and of which shape".
 *
 * Mirrors the backend (fpl_grounded_assistant/harness.py):
 *   - WIZARD_ARMING_TOOLS = {get_player_snapshot, get_player_form} → intents
 *     `player_snapshot` / `player_form`. Their candidates come from the live
 *     bootstrap, so chips carry a stable `player_id` and the tap re-sends it.
 *   - get_player_season_points (past seasons) → chips of kind
 *     `historical_player_rewrite`, NO id: those ids belong to another season's
 *     store and would resolve against the wrong bootstrap. The tap re-sends
 *     `send_text` verbatim, exactly like `prompt_rewrite`.
 *
 * Both sides pin these sets in tests; change one, change the other.
 */
import type { Suggestion } from '@/lib/types';
import {
  SUGGESTION_KIND_HISTORICAL_PLAYER_REWRITE,
  SUGGESTION_KIND_PROMPT_REWRITE,
} from '@/lib/types';

/** Intents whose ambiguous turn arms the stable-id pick-one wizard. */
export const WIZARD_ARMING_INTENTS: ReadonlySet<string> = new Set(['player_snapshot', 'player_form']);

/** Chip kinds whose `send_text` is a complete question to send verbatim, without an id. */
export const REWRITE_SUGGESTION_KINDS: ReadonlySet<string> = new Set([
  SUGGESTION_KIND_PROMPT_REWRITE,
  SUGGESTION_KIND_HISTORICAL_PLAYER_REWRITE,
]);

export function isRewriteSuggestion(suggestion: Suggestion): boolean {
  return suggestion.kind != null && REWRITE_SUGGESTION_KINDS.has(suggestion.kind);
}

export function isStableIdSuggestion(
  suggestion: Suggestion,
): suggestion is Suggestion & { player_id: number } {
  return suggestion.player_id != null && !isRewriteSuggestion(suggestion);
}
