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
import type { AskResponse, Outcome, Suggestion } from '@/lib/types';
import { SUGGESTION_KIND_PROMPT_REWRITE } from '@/lib/types';
import type { WcAskResponse } from '@/lib/wc-types';
import { selectIntentView } from '@/lib/intent-renderer';
import { selectWcIntentView } from '@/lib/wc-intent-renderer';
import IntentRenderer from './IntentRenderer';
import WcIntentRenderer from '@/components/wc/WcIntentRenderer';
import SuggestionChips, {
  PlayerPickChips,
  COMPARE_STEP1_QUESTION,
  PICK_ONE_QUESTION,
  type CompareWizardState,
  type PlayerPickWizardState,
} from './SuggestionChips';
import ShareActions from '@/components/share/ShareActions';
import EvidenceBoundary from '@/components/intelligence/EvidenceBoundary';
import EvidenceList from '@/components/intelligence/EvidenceList';
import MarkdownLite from '@/components/MarkdownLite';

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
  /** Guided Comparison wizard state — non-null while a compare wizard is armed.
   *  Chips render ONLY under the latest top-level assistant bubble. */
  compareWizard?: CompareWizardState | null;
  /** Called with the complete stable-id player suggestion. */
  onSuggestionPick?: (sendText: string) => void;
  /** Single-tap player disambiguation wizard state (player_snapshot intent). */
  playerPickWizard?: PlayerPickWizardState | null;
  /** Called with a tapped chip's send_text. */
  onPlayerPick?: (suggestion: Suggestion) => void;
}

export default function MessageList({
  messages,
  loading,
  onFollowUp,
  followUpArmedFor,
  compareWizard,
  onSuggestionPick,
  playerPickWizard,
  onPlayerPick,
}: Props) {
  const listRef = useRef<HTMLDivElement>(null);
  const shareQuestionByAssistantId = assistantShareQuestionMap(messages);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;

    // Keep autoscroll scoped to the conversation viewport. scrollIntoView()
    // also scrolls overflow-hidden ancestors, which can move the SwipePager
    // itself upward when a tall card arrives.
    if (typeof list.scrollTo === 'function') {
      list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' });
    } else {
      // jsdom and older browser shims may not expose scrollTo().
      list.scrollTop = list.scrollHeight;
    }
  }, [messages, loading]);

  const lastId = messages[messages.length - 1]?.id;

  return (
    <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          message={msg}
          shareQuestion={shareQuestionByAssistantId[msg.id] ?? null}
          isLast={msg.id === lastId}
          armed={followUpArmedFor === msg.id}
          onFollowUp={onFollowUp}
          compareWizard={compareWizard}
          onSuggestionPick={onSuggestionPick}
          playerPickWizard={playerPickWizard}
          onPlayerPick={onPlayerPick}
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
      <div />
    </div>
  );
}

interface MessageBubbleProps {
  message: Message;
  shareQuestion: string | null;
  isLast: boolean;
  armed: boolean;
  onFollowUp?: (messageId: string) => void;
  compareWizard?: CompareWizardState | null;
  onSuggestionPick?: (sendText: string) => void;
  playerPickWizard?: PlayerPickWizardState | null;
  onPlayerPick?: (suggestion: Suggestion) => void;
}

function MessageBubble({ message, shareQuestion, isLast, armed, onFollowUp, compareWizard, onSuggestionPick, playerPickWizard, onPlayerPick }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const showOriginBadge = !isUser && !message.isError && (message.response != null || message.wcResponse != null);
  const showFollowUp = !isUser && !message.isError && isLast && onFollowUp != null;
  // A compare-clarification turn is identified by ITS OWN response carrying
  // suggestions — a permanent property of this message, unlike `compareWizard`
  // (transient global state that clears once the user finishes the wizard).
  // The backend's raw clarification text (English, redundant with the wizard's
  // own Spanish copy) must stay hidden for this turn FOREVER, not just while
  // the wizard is still active — otherwise it reappears the moment the wizard
  // completes and `compareWizard` resets to null.
  const responseSuggestions = message.response?.suggestions;
  const hasSuggestions =
    !isUser &&
    !message.isError &&
    (responseSuggestions?.length ?? 0) > 0 &&
    (
      message.response?.intent !== 'player_snapshot' ||
      responseSuggestions!.every((suggestion) => suggestion.player_id != null)
    );
  // Which question this turn asked, for the superseded (non-interactive)
  // fallback copy below. A pick-one turn asks the user to identify ONE player
  // — either a snapshot disambiguation or a slash prompt whose player name was
  // ambiguous (prompt_rewrite chips); only the two-step compare wizard asks
  // for a first player. Keyed off the chips themselves rather than the intent,
  // because prompt_rewrite chips arrive on a compare_players turn.
  const isPickOneTurn =
    message.response?.intent === 'player_snapshot' ||
    (responseSuggestions ?? []).some(
      (suggestion) => suggestion.kind === SUGGESTION_KIND_PROMPT_REWRITE,
    );
  // Guided Comparison chips: only under the LATEST top-level assistant bubble
  // (never historical turns, never sub-responses) while a wizard is armed.
  const showWizard = hasSuggestions && isLast && compareWizard != null && onSuggestionPick != null;
  // Single-tap player disambiguation chips — mutually exclusive with
  // showWizard in practice (ChatShell only arms one wizard per intent), but
  // each derived independently here so the two chip sets never depend on
  // each other's state.
  const showPlayerPickWizard =
    hasSuggestions && isLast && playerPickWizard != null && onPlayerPick != null;
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
          {hasFplCard && message.response!.intent !== 'multi_intent' && (
            <EvidenceBoundary>
              <EvidenceList evidence={message.response!.evidence} />
            </EvidenceBoundary>
          )}
          {hasFplCard && shareQuestion && (
            <ShareActions question={shareQuestion} response={message.response!} />
          )}
          {hasWcCard && <WcIntentRenderer response={message.wcResponse!} />}
          {showOriginBadge && <OriginBadges message={message} />}
          {showWizard && <SuggestionChips wizard={compareWizard!} onPick={onSuggestionPick!} />}
          {showPlayerPickWizard && <PlayerPickChips wizard={playerPickWizard!} onPick={onPlayerPick!} />}
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
        {/* A compare-clarification turn's bubble content is owned by the
            wizard's own Spanish copy — not the backend's generic/English
            clarification text — for the LIFE of this message, not just while
            the wizard is still the active one. Live chips while active;
            once superseded (wizard finished or a newer turn arrived), fall
            back to a static, non-interactive line so the turn still reads
            sensibly in history without the English text reappearing. */}
        {!hasSuggestions &&
          (isUser || message.isError ? (
            // User prompts and error strings render verbatim (a user's literal
            // asterisks/dashes must not become bold/bullets).
            <p className="text-sm whitespace-pre-wrap">{message.text}</p>
          ) : (
            // Assistant prose (orchestrator synthesis, tool narration) renders
            // as minimal markdown so open-ended answers read with hierarchy
            // instead of a flat/raw text wall.
            <MarkdownLite text={message.text} className="text-sm" />
          ))}
        {hasSuggestions && !showWizard && !showPlayerPickWizard && (
          <p className="text-sm font-semibold text-bf-text/90">
            {isPickOneTurn ? PICK_ONE_QUESTION : COMPARE_STEP1_QUESTION}
          </p>
        )}

        {!isUser && !message.isError && message.response?.intent !== 'multi_intent' && (
          <EvidenceBoundary>
            <EvidenceList evidence={message.response?.evidence} />
          </EvidenceBoundary>
        )}

        {showOriginBadge && <OriginBadges message={message} />}
        {showWizard && <SuggestionChips wizard={compareWizard!} onPick={onSuggestionPick!} />}
        {showPlayerPickWizard && <PlayerPickChips wizard={playerPickWizard!} onPick={onPlayerPick!} />}
        {showFollowUp && <FollowUpButton armed={armed} onClick={() => onFollowUp!(message.id)} />}
      </div>
    </div>
  );
}

function assistantShareQuestionMap(messages: Message[]): Record<string, string> {
  const map: Record<string, string> = {};
  let latestUserQuestion = '';

  for (const msg of messages) {
    if (msg.role === 'user') {
      latestUserQuestion = msg.text.trim();
      continue;
    }
    if (latestUserQuestion) {
      map[msg.id] = latestUserQuestion;
    }
  }

  return map;
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
  } else if (message.response?.web_search != null) {
    // Unverified external synthesis — same cyan accent as WebSearchCard.
    originBadgeLabel = 'Búsqueda web + IA';
    originBadgeClassName = 'border-bf-cyan/40 bg-bf-cyan/10 text-bf-cyan';
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
