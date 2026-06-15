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
import type { WcAskResponse } from '@/lib/wc-types';
import { selectIntentView } from '@/lib/intent-renderer';
import { selectWcIntentView } from '@/lib/wc-intent-renderer';
import IntentRenderer from './IntentRenderer';
import WcIntentRenderer from '@/components/wc/WcIntentRenderer';

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
  /** World Cup backend response — populated on successful WcChatShell turns.
   *  Used by WcIntentRenderer to select and supply the structured card. */
  wcResponse?: WcAskResponse;
}

interface Props {
  messages: Message[];
  loading: boolean;
  /** Called with a message id when its "Seguir conversación" button is tapped. */
  onFollowUp?: (messageId: string) => void;
  /** Id of the message currently armed for follow-up, if any. */
  followUpArmedFor?: string | null;
}

export default function MessageList({ messages, loading, onFollowUp, followUpArmedFor }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const lastId = messages[messages.length - 1]?.id;

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          message={msg}
          isLast={msg.id === lastId}
          armed={followUpArmedFor === msg.id}
          onFollowUp={onFollowUp}
        />
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

interface MessageBubbleProps {
  message: Message;
  isLast: boolean;
  armed: boolean;
  onFollowUp?: (messageId: string) => void;
}

function MessageBubble({ message, isLast, armed, onFollowUp }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const showOriginBadge = !isUser && !message.isError && (message.response != null || message.wcResponse != null);
  const showFollowUp = !isUser && !message.isError && isLast && onFollowUp != null;
  // Structured turn → render the card alone, like /preview (no text bubble,
  // no bubble-around-card double box).
  const hasFplCard =
    !isUser &&
    !message.isError &&
    message.response != null &&
    selectIntentView(message.response) != null;
  const hasWcCard =
    !isUser &&
    !message.isError &&
    message.wcResponse != null &&
    selectWcIntentView(message.wcResponse) != null;

  if (hasFplCard || hasWcCard) {
    return (
      <div className="flex justify-start">
        <div className="max-w-prose w-full [&>:first-child]:mt-0">
          {hasFplCard && <IntentRenderer response={message.response!} />}
          {hasWcCard && <WcIntentRenderer response={message.wcResponse!} />}
          {showOriginBadge && <OriginBadges message={message} />}
          {showFollowUp && <FollowUpButton armed={armed} onClick={() => onFollowUp!(message.id)} />}
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
        {showFollowUp && <FollowUpButton armed={armed} onClick={() => onFollowUp!(message.id)} />}
      </div>
    </div>
  );
}

function FollowUpButton({ armed, onClick }: { armed: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`mt-3 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
        armed
          ? 'border-bf-turquoise/60 bg-bf-turquoise/10 text-bf-turquoise'
          : 'border-white/10 text-bf-gray hover:text-bf-text hover:border-white/20'
      }`}
    >
      {armed ? 'Seguimiento activado ✓' : 'Seguir conversación →'}
    </button>
  );
}

function OriginBadges({ message }: { message: Message }) {
  // World Cup turns: llm_used is true on nearly every turn (the LLM always
  // phrases final_text, even when 100% tool-grounded), so it isn't a useful
  // origin signal here. Use `grounded` instead — whether a real tool call
  // backed this answer ("Datos verificados") vs an ungrounded LLM reply
  // ("Sin datos del torneo", e.g. a "no tengo datos" refusal).
  let originBadgeLabel: string;
  let originBadgeClassName: string;
  if (message.wcResponse?.source === 'web_search') {
    // Unverified external synthesis — NEVER "Datos verificados". Cyan matches
    // the WcWebSearchCard accent (the system's web/search color).
    originBadgeLabel = 'Búsqueda web + IA';
    originBadgeClassName = 'border-bf-cyan/40 bg-bf-cyan/10 text-bf-cyan';
  } else if (message.wcResponse != null) {
    const grounded = message.wcResponse.grounded ?? false;
    originBadgeLabel = grounded ? 'Datos verificados' : 'Sin datos del torneo';
    originBadgeClassName = grounded
      ? 'border-bf-turquoise/40 bg-bf-turquoise/10 text-bf-turquoise'
      : 'border-bf-gold/40 bg-bf-gold/10 text-bf-gold';
  } else {
    originBadgeLabel = message.llmUsed ? 'IA activa' : 'Determinístico';
    originBadgeClassName = message.llmUsed
      ? 'border-bf-turquoise/40 bg-bf-turquoise/10 text-bf-turquoise'
      : 'border-bf-gold/40 bg-bf-gold/10 text-bf-gold';
  }

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
