'use client';

/**
 * ChatShell — chat UI container (V2 Phase 2g).
 *
 * Supports:
 *   - Stateless mode (default): POST /ask
 *   - Session mode: POST /session/{id}/ask with pronoun resolution
 *   - Squad context: optional FPL team ID attached to every ask (Phase 2f)
 *   - SlashMenu dropdown via InputBar + SlashMenu (Phase 2g)
 *
 * squad_context passes through both ask paths unchanged.
 * The renderer path (IntentRenderer) is identical in all modes.
 *
 * Auth gating deferred to Phase 3.
 */
import { useState, useCallback } from 'react';
import { ask, sessionAsk, createSession, clearSession, FplApiError } from '@/lib/api';
import { parseSlashCommand } from '@/lib/slash-commands';
import type { AskResponse, SquadContext } from '@/lib/types';
import MessageList, { type Message } from './MessageList';
import InputBar from './InputBar';
import StarterPrompts from './StarterPrompts';
import SquadContextPanel from './SquadContextPanel';
import QuotaIndicator from './QuotaIndicator';

export default function ChatShell() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionMode, setSessionMode] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [squadContext, setSquadContext] = useState<SquadContext | null>(null);
  // Incremented after each completed turn so QuotaIndicator re-fetches quota
  const [quotaRefreshTrigger, setQuotaRefreshTrigger] = useState(0);

  const handleClearSession = useCallback(async () => {
    if (sessionId) {
      try { await clearSession(sessionId); } catch { /* ignore — may already be expired */ }
      setSessionId(null);
    }
    setMessages([]);
  }, [sessionId]);

  const toggleSessionMode = useCallback(async () => {
    if (sessionMode && sessionId) {
      try { await clearSession(sessionId); } catch { /* ignore */ }
      setSessionId(null);
    }
    setSessionMode((prev) => !prev);
    setMessages([]);
  }, [sessionMode, sessionId]);

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

    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);

    try {
      let response: AskResponse;

      const requestBody = {
        question: effectiveQuestion,
        intent_hint: intentHint,
        // squad_context is passed on every turn; null when no team connected
        squad_context: squadContext ?? null,
      };

      if (!sessionMode) {
        response = await ask(requestBody);
      } else {
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
  }, [loading, sessionMode, sessionId, squadContext]);

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto px-4 py-3">
      {/* Contained panel — DS surface card framing the whole chat */}
      <div className="flex flex-col flex-1 min-h-0 rounded-card border border-white/10 bg-bf-surface overflow-hidden">
        <header className="px-4 py-3 border-b border-white/10 flex-shrink-0 space-y-2 bg-black/25">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h1 className="text-base font-extrabold text-white leading-none">FPL Asistente</h1>
              <span className="w-1.5 h-1.5 rounded-full bg-bf-turquoise" />
            </div>

            <div className="flex items-center gap-3">
              {sessionMode && sessionId && (
                <button
                  onClick={handleClearSession}
                  disabled={loading}
                  className="text-xs text-bf-gray hover:text-bf-text transition-colors disabled:opacity-40"
                >
                  Limpiar sesión
                </button>
              )}

              <button
                onClick={toggleSessionMode}
                disabled={loading}
                className={`flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full border transition-colors disabled:opacity-40 ${
                  sessionMode
                    ? 'border-bf-turquoise/60 text-bf-turquoise bg-bf-turquoise/10'
                    : 'border-white/10 text-bf-gray hover:text-bf-text hover:border-white/20'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${sessionMode ? 'bg-bf-turquoise' : 'bg-bf-gray/60'}`} />
                {sessionMode ? 'Conversación' : 'Directo'}
              </button>
            </div>
          </div>

          {/* Squad context row */}
          <SquadContextPanel onContextChange={setSquadContext} />
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
            <MessageList messages={messages} loading={loading} />
          )}
        </div>

        <div className="flex-shrink-0 px-3 pb-3 pt-2 space-y-2 border-t border-white/5">
          <InputBar onSubmit={sendMessage} disabled={loading} />
          <div className="flex justify-end">
            <QuotaIndicator refreshTrigger={quotaRefreshTrigger} />
          </div>
        </div>
      </div>
    </div>
  );
}
