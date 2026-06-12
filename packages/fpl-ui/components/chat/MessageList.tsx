'use client';

/**
 * MessageList — renders the conversation history.
 *
 * Rendering rules (FINAL_RESPONSE_CONTRACT.md + U2 design update):
 *   - Structured turns (outcome=ok with a matching conditional field) render
 *     the intent card ALONE — no text bubble. The backend's final_text
 *     duplicates the card content, and bubble-wrapping the card produced a
 *     double box (user feedback 2026-06-12: "it should be only the table").
 *   - Text-only turns render final_text in a bubble as before.
 *   - Show a visible origin badge for assistant turns in both shapes.
 */
import { useEffect, useRef } from 'react';
import type { AskResponse, Outcome } from '@/lib/types';
import { selectIntentView } from '@/lib/intent-renderer';
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
  // Structured turn → render the card alone, like /preview (no text bubble,
  // no bubble-around-card double box).
  const hasCard =
    !isUser &&
    !message.isError &&
    message.response != null &&
    selectIntentView(message.response) != null;

  if (hasCard) {
    return (
      <div className="flex justify-start">
        <div className="max-w-prose w-full [&>:first-child]:mt-0">
          <IntentRenderer response={message.response!} />
          {showOriginBadge && <OriginBadges message={message} />}
        </div>
      </div>
    );
  }

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

        {showOriginBadge && <OriginBadges message={message} />}
      </div>
    </div>
  );
}

function OriginBadges({ message }: { message: Message }) {
  const originBadgeLabel = message.llmUsed ? 'IA activa' : 'Determinístico';
  const originBadgeClassName = message.llmUsed
    ? 'border-bf-turquoise/40 bg-bf-turquoise/10 text-bf-turquoise'
    : 'border-bf-gold/40 bg-bf-gold/10 text-bf-gold';

  return (
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
  );
}
