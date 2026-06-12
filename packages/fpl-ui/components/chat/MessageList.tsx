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
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
      {loading && (
        <div className="flex justify-start">
          <div className="bg-white/5 border border-white/10 rounded-[14px] rounded-tl px-4 py-3 max-w-prose">
            <span className="text-bf-turquoise text-sm animate-pulse">
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
    ? 'border-bf-turquoise/40 bg-bf-turquoise/10 text-bf-turquoise'
    : 'border-bf-gold/40 bg-bf-gold/10 text-bf-gold';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-prose px-4 py-3 ${
          isUser
            ? 'bg-bf-coral text-white hc:text-bf-ink rounded-[14px] rounded-br'
            : message.isError
              ? 'bg-bf-coral/10 border border-bf-coral/40 text-bf-coral rounded-[14px] rounded-tl'
              : 'bg-white/5 border border-white/10 text-bf-text rounded-[14px] rounded-tl'
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
              <span className="inline-flex items-center rounded-full border border-bf-coral-soft/40 bg-bf-coral-soft/10 px-2 py-1 text-[11px] font-medium text-bf-coral-soft">
                proveedor no disponible
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
