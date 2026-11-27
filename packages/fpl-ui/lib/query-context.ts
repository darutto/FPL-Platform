/**
 * queryContextForNextTurn — what the NEXT typed message carries so the server can read it as a correction.
 *
 * The chat posts plain turns to the stateless /ask, so the last query's spec travels with the client. Only
 * the immediately preceding assistant message counts: any other answer in between clears it. A tapped pill or
 * chip sends none, because its `query_spec` is already the whole question.
 */
import type { AskResponse, QueryContext } from './types';

interface MessageLike {
  role: 'user' | 'assistant';
  response?: Pick<AskResponse, 'query'>;
}

export function queryContextForNextTurn(
  messages: readonly MessageLike[],
  notThis: boolean,
): QueryContext | undefined {
  const last = messages[messages.length - 1];
  if (!last || last.role !== 'assistant') return undefined;
  const spec = last.response?.query?.spec;
  return spec != null ? { spec, not_this: notThis } : undefined;
}
