/**
 * planStateForNextTurn — the plan_to_sign follow-up state that rides on the
 * NEXT request only.
 *
 * Why client-carried: the chat posts every plain turn to the stateless /ask and
 * drops any session (ChatShell), so state kept server-side would not survive to
 * the next turn. The backend returns `plan_state` on the plan answer; sending it
 * back here lets "who else can I sell to get the money?" keep its target.
 *
 * Only the IMMEDIATELY preceding assistant message counts: a plan answer that is
 * not the last thing said must not hijack a later, unrelated question.
 */
import type { AskResponse } from './types';

interface MessageLike {
  role: 'user' | 'assistant';
  response?: Pick<AskResponse, 'plan_state'>;
}

export function planStateForNextTurn(
  messages: readonly MessageLike[],
): Record<string, unknown> | undefined {
  const last = messages[messages.length - 1];
  if (!last || last.role !== 'assistant') return undefined;
  return last.response?.plan_state ?? undefined;
}
