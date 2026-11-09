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

export type ChatAsk = (question: string) => void;

const ChatAskContext = createContext<ChatAsk | null>(null);

export function ChatAskProvider({ ask, children }: { ask: ChatAsk; children: ReactNode }) {
  return <ChatAskContext.Provider value={ask}>{children}</ChatAskContext.Provider>;
}

export function useChatAsk(): ChatAsk | null {
  return useContext(ChatAskContext);
}
