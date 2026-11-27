'use client';

/**
 * chat-ask — lets a card deep inside a chat message send a question to the
 * chat without threading a callback through MessageList → IntentRenderer →
 * every card. ChatShell provides its send function; a card reads it with
 * `useChatAsk()`.
 *
 * Outside the chat (a shared answer, a test render) there is no provider and
 * `useChatAsk()` returns null: a card must then render nothing tappable.
 */
import { createContext, useContext, type ReactNode } from 'react';
import type { QuerySpecDict } from './types';

export type ChatAsk = (question: string) => void;

const ChatAskContext = createContext<ChatAsk | null>(null);

export function ChatAskProvider({ ask, children }: { ask: ChatAsk; children: ReactNode }) {
  return <ChatAskContext.Provider value={ask}>{children}</ChatAskContext.Provider>;
}

export function useChatAsk(): ChatAsk | null {
  return useContext(ChatAskContext);
}

/** What a query card can do in the chat. Same rule as above: no provider, nothing tappable. */
export interface QueryActions {
  /** Re-run a typed spec. `label` fills the user's bubble; it is never read as a question. */
  pick: (spec: QuerySpecDict, label: string) => void;
  /** "Not this": put the cursor in the composer for the correction. */
  correct: () => void;
}

const SharedImageContext = createContext(false);

/** True inside the picture a user shares, which may leave out small print meant for the app. */
export const SharedImageProvider = SharedImageContext.Provider;

export function useSharedImage(): boolean {
  return useContext(SharedImageContext);
}

const QueryActionsContext = createContext<QueryActions | null>(null);

export const QueryActionsProvider = QueryActionsContext.Provider;

export function useQueryActions(): QueryActions | null {
  return useContext(QueryActionsContext);
}
