'use client';

/**
 * ChatShell — three-screen swipe shell (V2 Phase 2g + U2 pager).
 *
 * Screens (SwipePager): Squad pitch · Chat (home) · Quick commands.
 *
 * Chat supports:
 *   - Stateless mode (default): every question goes through POST /ask on its
 *     own, with no memory of prior turns.
 *   - Follow-up mode: tapping "Seguir conversación" on the last reply arms
 *     the NEXT message to go through POST /session/{id}/ask (creating a
 *     session on first use), so it can use pronoun resolution against that
 *     reply. Sending without arming follow-up clears any active session —
 *     each unarmed question is treated as a brand-new conversation.
 *   - Squad context: optional FPL team ID attached to every ask (Phase 2f)
 *   - SlashMenu dropdown via InputBar + SlashMenu (Phase 2g)
 *
 * squad_context passes through both ask paths unchanged.
 * The renderer path (IntentRenderer) is identical in all modes.
 *
 * Command-panel clicks and pitch "Ask AI" insert text into the InputBar
 * (no auto-send) and snap back to the chat screen.
 *
 * Auth gating deferred to Phase 3.
 */
import { useState, useCallback } from 'react';
import { ask, sessionAsk, createSession, clearSession, FplApiError } from '@/lib/api';
import { parseSlashCommand } from '@/lib/slash-commands';
import type { AskResponse, SquadContext } from '@/lib/types';
import MessageList, { type Message } from './MessageList';
import InputBar, { type InsertRequest } from './InputBar';
import StarterPrompts from './StarterPrompts';
import SquadContextPanel from './SquadContextPanel';
import QuotaIndicator from './QuotaIndicator';
import SwipePager, { PagerScreen } from './SwipePager';
import CommandPanel from './CommandPanel';
import TopBar from './TopBar';
import SquadPitch from '@/components/squad/SquadPitch';

export default function ChatShell() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // Message id whose "Seguir conversación" button was tapped — arms the
  // NEXT send to use the session path. Reset after every send.
  const [followUpArmedFor, setFollowUpArmedFor] = useState<string | null>(null);
  const [squadContext, setSquadContext] = useState<SquadContext | null>(null);
  // Incremented after each completed turn so QuotaIndicator re-fetches quota
  const [quotaRefreshTrigger, setQuotaRefreshTrigger] = useState(0);
  // U2 pager state: 0 = squad, 1 = chat (home), 2 = commands
  const [screen, setScreen] = useState(1);
  const [insert, setInsert] = useState<InsertRequest | null>(null);
  const [teamId, setTeamId] = useState<number | null>(null);
  const [teamName, setTeamName] = useState<string | null>(null);
  const [gw, setGw] = useState<number | null>(null);

  const handleTeamIdChange = useCallback((id: number | null, name: string | null) => {
    setTeamId(id);
    setTeamName(name);
    if (id == null) setGw(null);
  }, []);

  // Drop text into the chat input and snap back to the chat screen.
  // `placeholder` (e.g. "p.ej. Haaland") hints the required argument when
  // inserting a bare slash command from the command panel.
  const handleInsert = useCallback((text: string, placeholder?: string) => {
    setInsert({ text, nonce: Date.now(), placeholder });
    setScreen(1);
  }, []);

  // Arm follow-up mode for the next message, anchored to this reply.
  const handleFollowUp = useCallback((messageId: string) => {
    setFollowUpArmedFor(messageId);
  }, []);

  const cancelFollowUp = useCallback(() => {
    setFollowUpArmedFor(null);
  }, []);

  const sendMessage = useCallback(async (rawInput: string) => {
    const input = rawInput.trim();
    if (!input || loading) return;

    const parsed = parseSlashCommand(input);
    const effectiveQuestion = parsed?.question || input;
    const intentHint = parsed?.intent_hint ?? null;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      text: input,
    };

    // @resource queries (@puntos, @lesionados, ...) are stateless lookups
    // only supported on the /ask (ask_v2) path — /session/{id}/ask still
    // runs the legacy respond() pipeline, which doesn't recognize them.
    const isResourceQuery = effectiveQuestion.trim().startsWith('@');
    const isFollowUp = followUpArmedFor != null && !isResourceQuery;

    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);
    setFollowUpArmedFor(null);

    try {
      let response: AskResponse;

      const requestBody = {
        question: effectiveQuestion,
        intent_hint: intentHint,
        // squad_context is passed on every turn; null when no team connected
        squad_context: squadContext ?? null,
      };

      if (isFollowUp) {
        let activeId = sessionId;
        if (activeId === null) {
          const created = await createSession();
          activeId = created.session_id;
          setSessionId(activeId);
        }
        try {
          response = await sessionAsk(activeId, requestBody);
        } catch (err) {
          if (err instanceof FplApiError && err.status === 404) {
            setSessionId(null);
          }
          throw err;
        }
      } else {
        // Not a follow-up: this is a brand-new conversation. Drop any
        // active session so prior context doesn't leak into resolution.
        if (sessionId) {
          clearSession(sessionId).catch(() => { /* ignore — may already be expired */ });
          setSessionId(null);
        }
        response = await ask(requestBody);
      }

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: response.final_text,
        outcome: response.outcome,
        llmUsed: response.llm_used,
        degraded: response.degraded,
        response,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      // Refresh quota indicator after every completed turn
      setQuotaRefreshTrigger((n) => n + 1);
    } catch (err) {
      const errorText =
        err instanceof FplApiError
          ? err.message
          : 'Error inesperado. Por favor, inténtalo de nuevo.';

      const errorMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: errorText,
        isError: true,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  }, [loading, followUpArmedFor, sessionId, squadContext]);

  // Quick commands ("Vistas rápidas") are complete queries — send immediately
  // and jump to the chat screen, skipping the edit step.
  const handleSend = useCallback((text: string) => {
    setScreen(1);
    sendMessage(text);
  }, [sendMessage]);

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-screen">
      <TopBar teamName={teamName} gw={gw} />

      <SwipePager screen={screen} onScreenChange={setScreen}>
        {/* SCREEN 0 — Squad pitch */}
        <PagerScreen maxWidth={460}>
          <SquadPitch teamId={teamId} onAskPlayer={handleInsert} onGw={setGw} />
        </PagerScreen>

        {/* SCREEN 1 — Chat (home) */}
        <PagerScreen maxWidth={672}>
          <div className="h-full flex flex-col rounded-card border border-white/10 bg-bf-surface overflow-hidden">
            <header className="px-4 py-3 border-b border-white/10 flex-shrink-0 space-y-2 bg-black/25">
              <div className="flex items-center gap-2">
                <h1 className="text-[10px] font-bold uppercase tracking-widest text-bf-text/50 leading-none">Chat</h1>
                <span className="w-1.5 h-1.5 rounded-full bg-bf-turquoise" />
              </div>

              {/* Squad context row */}
              <SquadContextPanel onContextChange={setSquadContext} onTeamIdChange={handleTeamIdChange} />
            </header>

            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
              {isEmpty ? (
                <div className="flex-1 flex flex-col items-center justify-center gap-6 px-4">
                  <p className="text-bf-gray text-sm">
                    Haz una pregunta sobre tu equipo de Fantasy Premier League.
                  </p>
                  <StarterPrompts onSelect={sendMessage} />
                </div>
              ) : (
                <MessageList
                  messages={messages}
                  loading={loading}
                  onFollowUp={handleFollowUp}
                  followUpArmedFor={followUpArmedFor}
                />
              )}
            </div>

            <div className="flex-shrink-0 px-3 pb-3 pt-2 space-y-2 border-t border-white/5">
              {followUpArmedFor && (
                <button
                  onClick={cancelFollowUp}
                  className="flex items-center gap-1.5 text-[11px] font-medium text-bf-turquoise bg-bf-turquoise/10 border border-bf-turquoise/40 rounded-full px-2.5 py-1"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-bf-turquoise" />
                  Respondiendo a esto · toca para cancelar
                </button>
              )}
              <InputBar onSubmit={sendMessage} disabled={loading} insert={insert} />
              <div className="flex justify-end">
                <QuotaIndicator refreshTrigger={quotaRefreshTrigger} />
              </div>
            </div>
          </div>
        </PagerScreen>

        {/* SCREEN 2 — Quick commands */}
        <PagerScreen maxWidth={520}>
          <div className="h-full rounded-card border border-white/10 bg-bf-surface overflow-hidden">
            <CommandPanel onInsert={handleInsert} onSend={handleSend} />
          </div>
        </PagerScreen>
      </SwipePager>
    </div>
  );
}
