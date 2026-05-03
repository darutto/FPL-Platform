'use client';

/**
 * MessageList — renders the conversation history.
 *
 * Rendering rules (from FINAL_RESPONSE_CONTRACT.md):
 *   - Always render final_text — it is always non-empty.
 *   - Show a visible origin badge for assistant turns.
 *   - Render structured intent component beneath final_text when
 *     outcome=ok and the matching conditional field is non-null.
 *   - Non-ok outcomes and text-only intents render final_text only.
 */
import { useEffect, useRef } from 'react';
import type { AskResponse, Outcome } from '@/lib/types';
import IntentRenderer from './IntentRenderer';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  outcome?: Outcome;
  llmUsed?: boolean;
  degraded?: boolean;
  isError?: boolean;
  /** Full backend response — populated on successful assistant turns.
   *  Used by IntentRenderer to select and supply the structured component. */
  response?: AskResponse;
}

interface Props {
  messages: Message[];
  loading: boolean;
}

export default function MessageList({ messages, loading }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  return (
    <div className="flex-1 overflow-y-auto py-4 space-y-4">
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
      {loading && (
        <div className="flex justify-start">
          <div className="bg-gray-800 rounded-2xl px-4 py-3 max-w-prose">
            <span className="text-gray-400 text-sm animate-pulse">
              Pensando…
            </span>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  const showOriginBadge = !isUser && !message.isError && message.response;
  const originBadgeLabel = message.llmUsed
    ? 'IA activa'
    : 'Determinístico';
  const originBadgeClassName = message.llmUsed
    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
    : 'border-amber-500/40 bg-amber-500/10 text-amber-300';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-prose rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-indigo-600 text-white'
            : message.isError
              ? 'bg-red-900/60 text-red-200'
              : 'bg-gray-800 text-gray-100'
        }`}
      >
        <p className="text-sm whitespace-pre-wrap">{message.text}</p>

        {/* Structured intent component — additive beneath final_text */}
        {!isUser && !message.isError && message.response && (
          <IntentRenderer response={message.response} />
        )}

        {showOriginBadge && (
          <div className="mt-3 flex items-center gap-2">
            <span
              className={`inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-medium uppercase tracking-[0.12em] ${originBadgeClassName}`}
            >
              {originBadgeLabel}
            </span>
            {/* Degraded notice — shown when LLM was attempted but provider failed (Phase 2.6b) */}
            {message.degraded && (
              <span className="inline-flex items-center rounded-full border border-orange-500/40 bg-orange-500/10 px-2 py-1 text-[11px] font-medium text-orange-300">
                proveedor no disponible
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
