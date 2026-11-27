/**
 * A team card opened by a tap: fetch it (POST /card) and shape it as the assistant message the chat draws.
 * No question was asked, so there is no user bubble and nothing for the model or the quota.
 */
import { FplApiError } from './api';
import type { AskResponse, TeamCardBody } from './types';
import type { Locale } from './i18n/locale';

export async function fetchTeamCard(teamId: number, locale: Locale): Promise<TeamCardBody> {
  const res = await fetch('/api/fpl-card', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ v: 1, kind: 'team', team_id: teamId, locale }),
  });
  if (!res.ok) throw new FplApiError(res.status, `Request failed (${res.status})`);
  return res.json() as Promise<TeamCardBody>;
}

export function teamCardResponse(body: TeamCardBody): AskResponse {
  return {
    final_text: body.card.team.name,
    outcome: 'ok',
    supported: true,
    intent: 'team_card',
    review_passed: true,
    llm_used: false,
    team_card: body,
  } as AskResponse;
}

/** True when the last thing said is already this club's card: a second tap scrolls to it instead. */
export function isLatestTeamCard(last: { response?: AskResponse } | undefined, teamId: number): boolean {
  return last?.response?.team_card?.card.team.id === teamId;
}
