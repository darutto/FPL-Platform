/**
 * buildSessionSeed — extracts a small, typed seed payload from the prior
 * turn's already-in-memory AskResponse, so a newly-created follow-up
 * session doesn't start with no memory of a turn that happened over the
 * stateless /ask endpoint before the session existed.
 *
 * Only a clean, single-intent, successful turn is eligible — multi_intent
 * responses are deliberately excluded in v1 (the intent checks below never
 * match 'multi_intent'), not because deriving a seed from a sub_response
 * would be impossible, but because it's an unnecessary complication for a
 * first pass; revisit if follow-up-after-multi-intent turns out to matter.
 */
import type { AskResponse } from './types';

export interface SessionSeed {
  last_comparison?: [string, string] | null;
  last_transfer?: [string, string] | null;
  last_fixture_run_player?: string | null;
  last_differential?: boolean;
  last_player_query?: string | null;
}

export function buildSessionSeed(response: AskResponse | undefined): SessionSeed | null {
  if (!response) return null;
  if (response.outcome !== 'ok' || !response.supported || !response.intent) {
    return null;
  }

  if (
    response.intent === 'compare_players' &&
    response.comparison?.player_a &&
    response.comparison?.player_b
  ) {
    return {
      last_comparison: [response.comparison.player_a.web_name, response.comparison.player_b.web_name],
    };
  }
  if (response.intent === 'transfer_advice' && response.transfer) {
    return { last_transfer: [response.transfer.player_out, response.transfer.player_in] };
  }
  if (response.intent === 'player_fixture_run' && response.fixture_run) {
    return { last_fixture_run_player: response.fixture_run.web_name };
  }
  if (response.intent === 'differential_picks' && response.differential) {
    return { last_differential: true };
  }
  if (response.intent === 'captain_score' && response.captain) {
    return { last_player_query: response.captain.web_name };
  }

  return null;
}
