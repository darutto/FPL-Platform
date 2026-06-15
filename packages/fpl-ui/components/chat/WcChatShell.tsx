'use client';

/**
 * WcChatShell — World Cup 2026 chat shell (Iteration 2 UI).
 *
 * Sibling of ChatShell (FPL) for the isolated World Cup domain — same
 * presentational building blocks (MessageList, InputBar, SlashMenu,
 * TopBar, theme) but talks to the WC backend via /api/wc-proxy and uses
 * the WC slash-command registry. No squad context, no quota indicator
 * (the WC backend has neither), and only 2 screens (Chat / Comandos)
 * via WcPager instead of FPL's 3-screen SwipePager.
 *
 * Renders final_text plus, when present, a structured WC card
 * (standings/top-scorers/fantasy/fixtures — Iteration 3) via
 * MessageList/WcIntentRenderer driven by message.wcResponse.
 *
 * Session isolation: WC session ids are minted by the WC backend
 * (wc:-prefixed) and live only in this component's React state — never
 * shared with FPL's ChatShell, which has its own independent state tree.
 */
import { useState, useCallback } from 'react';
import { wcAsk, wcCreateSession } from '@/lib/wc-api';
import { WcApiError } from '@/lib/wc-types';
import { parseWcSlashCommand, WC_SLASH_COMMANDS } from '@/lib/wc-slash-commands';
import MessageList, { type Message } from './MessageList';
import InputBar, { type InsertRequest } from './InputBar';
import WcPager, { WcPagerScreen } from './WcPager';
import WcCommandPanel from './WcCommandPanel';
import TopBar from './TopBar';

const WC_STARTER_PROMPTS = [
  '¿Cómo va el grupo A?',
  '/comparar Mbappé vs Haaland',
  '¿Quiénes son los máximos goleadores?',
  '/clasificacion grupo B',
  '¿Qué partidos hay hoy?',
  '/fantasy delanteros',
] as const;

function WcStarterPrompts({ onSelect }: { onSelect: (prompt: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2 justify-center max-w-lg">
      {WC_STARTER_PROMPTS.map((prompt) => (
        <button
          key={prompt}
          onClick={() => onSelect(prompt)}
          className="text-xs font-bold bg-bf-turquoise/10 hover:bg-bf-turquoise/20 border border-bf-turquoise/40 text-bf-turquoise rounded-full px-3 py-1.5 transition-colors"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}

export default function WcChatShell() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionMode, setSessionMode] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // 0 = chat (home), 1 = quick commands
  const [screen, setScreen] = useState(0);
  const [insert, setInsert] = useState<InsertRequest | null>(null);
  // Premium web-search opt-in (sticky globe toggle). The backend enforces the
  // tier gate; `webSearchAvailable` only governs the toggle's UI affordance.
  // TODO(clerk): derive availability from the live Patreon tier once Clerk
  // supplies X-User-Tier. Until then the backend returns feature_gated for
  // ineligible users, which renders as a Spanish upgrade prompt.
  const [webSearchOn, setWebSearchOn] = useState(false);
  const webSearchAvailable = true;
  const [lastQuery, setLastQuery] = useState('');

  const handleInsert = useCallback((text: string, placeholder?: string) => {
    setInsert({ text, nonce: Date.now(), placeholder });
    setScreen(0);
  }, []);

  const toggleSessionMode = useCallback(() => {
    setSessionMode((prev) => !prev);
    setSessionId(null);
    setMessages([]);
  }, []);

  const handleClearSession = useCallback(() => {
    // WC backend has no session-delete endpoint; idle sessions expire via
    // TTL. Resetting local state is enough to start a fresh conversation.
    setSessionId(null);
    setMessages([]);
  }, []);

  const sendMessage = useCallback(async (
    rawInput: string,
    opts?: { forceWebSearch?: boolean },
  ) => {
    const input = rawInput.trim();
    if (!input || loading) return;

    const parsed = parseWcSlashCommand(input);
    const effectiveQuestion = parsed?.question ?? input;
    // Explicit opt-in only: the sticky globe toggle, or the one-tap "Buscar en
    // la web" escalation chip (forceWebSearch). Never silent.
    const webSearchRequested = opts?.forceWebSearch ?? webSearchOn;
    setLastQuery(input);

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      text: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);

    try {
      let activeSessionId = sessionId;
      if (sessionMode && activeSessionId === null) {
        const created = await wcCreateSession();
        activeSessionId = created.session_id;
        setSessionId(activeSessionId);
      }

      const response = await wcAsk({
        question: effectiveQuestion,
        session_id: sessionMode ? activeSessionId : null,
        web_search_requested: webSearchRequested,
      });

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: response.final_text,
        outcome: response.outcome,
        llmUsed: response.llm_used,
        degraded: response.degraded,
        wcResponse: response,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      const errorText =
        err instanceof WcApiError
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
  }, [loading, sessionMode, sessionId, webSearchOn]);

  // One-tap "Buscar en la web" escalation: re-run the last query with web
  // search forced on (shown when an answer had no tournament data).
  const handleWebSearchEscalation = useCallback(() => {
    if (!lastQuery || loading) return;
    setWebSearchOn(true);
    sendMessage(lastQuery, { forceWebSearch: true });
  }, [lastQuery, loading, sendMessage]);

  // Offer the escalation chip when the most recent assistant turn produced no
  // grounded tournament data and wasn't itself a web-search answer.
  const lastMessage = messages[messages.length - 1];
  const showWebSearchChip =
    webSearchAvailable &&
    !loading &&
    lastMessage?.role === 'assistant' &&
    !lastMessage.isError &&
    lastMessage.wcResponse != null &&
    lastMessage.wcResponse.source !== 'web_search' &&
    !(lastMessage.wcResponse.grounded ?? false);

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-screen">
      <TopBar title="Mundial 2026" subtitle="Bendito Fantasy" />

      <WcPager screen={screen} onScreenChange={setScreen}>
        {/* SCREEN 0 — Chat (home) */}
        <WcPagerScreen maxWidth={672}>
          <div className="h-full flex flex-col rounded-card border border-white/10 bg-bf-surface overflow-hidden">
            <header className="px-4 py-3 border-b border-white/10 flex-shrink-0 space-y-2 bg-black/25">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h1 className="text-[10px] font-bold uppercase tracking-widest text-bf-text/50 leading-none">Chat</h1>
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
            </header>

            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
              {isEmpty ? (
                <div className="flex-1 flex flex-col items-center justify-center gap-6 px-4">
                  <p className="text-bf-gray text-sm">
                    Haz una pregunta sobre el Mundial 2026: partidos, clasificaciones, plantillas…
                  </p>
                  <WcStarterPrompts onSelect={sendMessage} />
                </div>
              ) : (
                <MessageList messages={messages} loading={loading} />
              )}
            </div>

            <div className="flex-shrink-0 px-3 pb-3 pt-2 space-y-2 border-t border-white/5">
              {showWebSearchChip && (
                <div className="flex justify-center">
                  <button
                    onClick={handleWebSearchEscalation}
                    disabled={loading}
                    className="inline-flex items-center gap-1.5 text-xs font-bold bg-bf-cyan/10 hover:bg-bf-cyan/20 border border-bf-cyan/40 text-bf-cyan rounded-full px-3 py-1.5 transition-colors disabled:opacity-40"
                  >
                    🌐 Buscar en la web
                  </button>
                </div>
              )}
              <InputBar
                onSubmit={sendMessage}
                disabled={loading}
                insert={insert}
                commands={WC_SLASH_COMMANDS}
                defaultPlaceholder="Escribe tu pregunta o usa /partidos, /clasificacion…"
                webSearch={{
                  enabled: webSearchOn,
                  onToggle: () => setWebSearchOn((v) => !v),
                  available: webSearchAvailable,
                }}
              />
            </div>
          </div>
        </WcPagerScreen>

        {/* SCREEN 1 — Quick commands */}
        <WcPagerScreen maxWidth={520}>
          <div className="h-full rounded-card border border-white/10 bg-bf-surface overflow-hidden">
            <WcCommandPanel onInsert={handleInsert} />
          </div>
        </WcPagerScreen>
      </WcPager>
    </div>
  );
}
