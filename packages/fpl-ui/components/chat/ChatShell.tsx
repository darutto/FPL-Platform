'use client';

/**
 * ChatShell — three-screen swipe shell (V2 Phase 2g + U2 pager).
 *
 * Screens (SwipePager): Calendario · Squad pitch · Chat (home) · Quick commands.
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
import { useState, useCallback, useEffect } from 'react';
import { useUser } from '@clerk/nextjs';
import { ask, sessionAsk, createSession, clearSession, FplApiError } from '@/lib/api';
import { generateId } from '@/lib/id';
import { buildSessionSeed } from '@/lib/session-seed';
import type { AskResponse, SquadContext, Suggestion } from '@/lib/types';
import { QUOTA_BUCKETS, type QuotaBucket } from '@/lib/tiers';
import { readDevTier } from '@/lib/dev-tier';
import MessageList, { type Message } from './MessageList';
import { type CompareWizardState, type PlayerPickWizardState } from './SuggestionChips';
import InputBar, { type InsertRequest } from './InputBar';
import StarterPrompts from './StarterPrompts';
import SquadContextPanel from './SquadContextPanel';
import QuotaIndicator from './QuotaIndicator';
import SwipePager, { PagerScreen } from './SwipePager';
import CommandPanel from './CommandPanel';
import TopBar from './TopBar';
import SquadPitch from '@/components/squad/SquadPitch';
import { FixturesBoard } from '@/components/intents/FixturesBoard';

// Pager screen order: 0 Calendario · 1 Squad · 2 Chat (home) · 3 Commands.
const PAGER_LABELS = ['Calendario', 'Squad', 'Chat', 'Commands'] as const;
const CHAT_SCREEN = 2;

export default function ChatShell() {
  const { user } = useUser();
  const clerkTier = (user?.publicMetadata?.tier as QuotaBucket | undefined) ?? 'free';
  // Dev-only impersonation, mirrors WcChatShell — read after mount to avoid a
  // hydration mismatch on the cookie. Always undefined in production.
  const [devTier, setDevTier] = useState<QuotaBucket | undefined>(undefined);
  useEffect(() => {
    setDevTier(readDevTier());
  }, []);
  const tier = devTier ?? clerkTier;
  // Premium web-search opt-in (sticky globe toggle). Mirrors WcChatShell: the
  // backend (WEB_SEARCH_TIERS) is still the source of truth for the gate —
  // this only governs the toggle's UI affordance.
  const webSearchAvailable = QUOTA_BUCKETS[tier]?.webSearch ?? false;
  const [webSearchOn, setWebSearchOn] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // Message id whose "Seguir conversación" button was tapped — arms the
  // NEXT send to use the session path. Reset after every send.
  const [followUpArmedFor, setFollowUpArmedFor] = useState<string | null>(null);
  // Guided Comparison flow: armed when a compare `/comparar` clarification turn
  // arrives with backend suggestions. Tied to the LATEST assistant turn only.
  // A manual send while armed is composed into the wizard's answer (see
  // sendMessage) unless it's an explicit "/" or "@" escape hatch.
  const [compareWizard, setCompareWizard] = useState<CompareWizardState | null>(null);
  // Single-tap disambiguation wizard for an ambiguous single-player lookup
  // (e.g. "Joao Pedro" matching two players). Sibling to compareWizard, not
  // a variant of it — one tap fully resolves the turn, no A/B composition.
  const [playerPickWizard, setPlayerPickWizard] = useState<PlayerPickWizardState | null>(null);
  const [squadContext, setSquadContext] = useState<SquadContext | null>(null);
  // Incremented after each completed turn so QuotaIndicator re-fetches quota
  const [quotaRefreshTrigger, setQuotaRefreshTrigger] = useState(0);
  // U2 pager state — see PAGER_LABELS (Calendario · Squad · Chat · Commands)
  const [screen, setScreen] = useState(CHAT_SCREEN);
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
    setScreen(CHAT_SCREEN);
  }, []);

  // Deep-link seed: /chat?q=... (e.g. from the /fixtures page) prefills the
  // composer (no auto-send, matching command-panel/pitch inserts). Cleared from
  // the URL so a refresh doesn't re-seed.
  useEffect(() => {
    const seed = new URLSearchParams(window.location.search).get('q');
    if (seed) {
      handleInsert(seed);
      window.history.replaceState(null, '', window.location.pathname);
    }
  }, [handleInsert]);

  // Arm follow-up mode for the next message, anchored to this reply.
  const handleFollowUp = useCallback((messageId: string) => {
    setFollowUpArmedFor(messageId);
  }, []);

  const cancelFollowUp = useCallback(() => {
    setFollowUpArmedFor(null);
  }, []);

  const sendMessage = useCallback(async (
    rawInput: string,
    selectedPlayerId?: number,
    selectedPlayerSessionId?: string | null,
  ) => {
    const trimmed = rawInput.trim();
    if (!trimmed || loading) return;

    // If a compare wizard is armed, a plain typed reply (not another slash
    // command, not an @resource query) answers the wizard's outstanding
    // question rather than firing an unrelated query — composed into the
    // same canonical "/comparar A vs B" text a chip tap already sends
    // (handleSuggestionPick), so typed and tapped answers converge on the
    // identical ComparisonCard. An explicit "/..." or "@..." send is the
    // escape hatch out of the wizard into something else.
    const isEscapeHatch = /^[/@]/.test(trimmed);
    const input =
      selectedPlayerId == null && compareWizard != null && !isEscapeHatch
        ? compareWizard.playerA == null
          ? `/comparar ${trimmed}`
          : `/comparar ${compareWizard.playerA} vs ${trimmed}`
        : trimmed;

    // Recognized slash commands (/capitan, /comparar, /transferencia, ...) are
    // sent to the backend RAW, with the leading command intact and no
    // intent_hint. The backend's prompt-registry decision_router parses the
    // literal "/command args" text natively — including bare commands with no
    // argument (correctly triggering needs_clarification) — for every
    // registered prompt. Stripping the prefix and attaching the legacy
    // intent_hint bias here actively breaks routing for some intents (e.g.
    // captain_score, player_fixture_run): _try_route_with_hint's canonical
    // templates were designed for a bare argument, not the leading-slash form,
    // and for commands with no argument the previous `parsed.question || input`
    // fallback (question is "" and falsy) re-introduced the raw slash text
    // anyway while still attaching the hint, hitting the same bug from the
    // other direction. Only non-slash free text gets no hint at all (unchanged).
    const effectiveQuestion = input;
    const intentHint = null;

    const userMessage: Message = {
      id: generateId(),
      role: 'user',
      text: input,
    };

    // @resource queries (@puntos, @lesionados, ...) are stateless lookups
    // only supported on the /ask (ask_v2) path — /session/{id}/ask still
    // runs the legacy respond() pipeline, which doesn't recognize them.
    const isResourceQuery = effectiveQuestion.trim().startsWith('@');
    const isFollowUp =
      !isResourceQuery &&
      (followUpArmedFor != null || (selectedPlayerId != null && selectedPlayerSessionId != null));
    // Named for readability, not because the value would otherwise be lost:
    // followUpArmedFor is closure-captured at this point in the running
    // call, so setFollowUpArmedFor(null) below only affects future renders.
    const armedForId = followUpArmedFor;

    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);
    setFollowUpArmedFor(null);
    // Every send clears the (now-resolved-or-abandoned) wizard state; if the
    // response below carries fresh suggestions, it gets re-armed at line ~250.
    setCompareWizard(null);
    setPlayerPickWizard(null);

    try {
      let response: AskResponse;
      let responseSessionId: string | null = null;

      const requestBody = {
        question: effectiveQuestion,
        ...(selectedPlayerId != null ? { selected_player_id: selectedPlayerId } : {}),
        intent_hint: intentHint,
        // squad_context is passed on every turn; null when no team connected
        squad_context: squadContext ?? null,
        // Explicit opt-in only — never silent. Gated by tier eligibility so
        // an ineligible user can't spend a request on a feature the backend
        // would reject anyway (defense-in-depth; the UI already locks the
        // toggle).
        web_search_requested: webSearchOn && webSearchAvailable,
      };

      if (isFollowUp) {
        let activeId = selectedPlayerSessionId ?? sessionId;
        if (activeId === null) {
          // Brand-new session — seed it from the prior turn's already-in-
          // memory response, so follow-up resolvers (comparison, transfer,
          // etc.) have context on the very first follow-up instead of
          // starting blank. Seeding only happens here, at creation time:
          // the existing non-follow-up branch below already clears
          // sessionId back to null on every ordinary send, so there is no
          // stale-session path where a later follow-up would reuse this
          // session without a chance to reseed.
          const priorMessage = armedForId
            ? messages.find((m) => m.id === armedForId)
            : undefined;
          const seed = buildSessionSeed(priorMessage?.response) ?? undefined;
          const created = await createSession(seed);
          activeId = created.session_id;
          setSessionId(activeId);
        }
        try {
          response = await sessionAsk(activeId, requestBody);
          responseSessionId = activeId;
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
        id: generateId(),
        role: 'assistant',
        text: response.final_text,
        outcome: response.outcome,
        llmUsed: response.llm_used,
        degraded: response.degraded,
        response,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      // Guided Comparison: a compare clarification turn arrives with tappable
      // suggestions. The backend guarantees `suggestions` is populated ONLY on a
      // compare_players needs_clarification turn, so its presence is the
      // authoritative compare signal. Arm the two-step chip wizard for THIS
      // latest turn.
      //
      // If the user already typed a single name ("/comparar Gabriel"), needs_
      // clarification only fires because the SECOND name is missing (two valid
      // names would have resolved to outcome=ok, not clarification) — so any
      // leftover text after the command prefix is safe to seed as playerA and
      // jump straight to step 2. Skip seeding when a two-name connector is
      // present (e.g. "Gabriel vs Bogus") since that means a comparison was
      // attempted and failed for another reason (unknown second player) —
      // seeding the whole phrase as one name would be nonsensical.
      // Intent-gated so the two wizards can never collide -- response.suggestions
      // is a generic {label, send_text}[] shared by both suppliers; without this
      // check a player_snapshot disambiguation turn would incorrectly arm the
      // two-slot compare flow (or vice versa).
      if (
        response.intent === 'compare_players' &&
        response.suggestions != null &&
        response.suggestions.length > 0
      ) {
        const afterCommand = input.replace(/^\/(comparar|compare)\s*/i, '').trim();
        const hasConnector = /\b(por|for|vs|y|and)\b|,/i.test(afterCommand);
        const seededA = afterCommand.length > 0 && !hasConnector ? afterCommand : null;
        setCompareWizard({ playerA: seededA, options: response.suggestions });
      }
      if (
        response.intent === 'player_snapshot' &&
        response.suggestions != null &&
        response.suggestions.length > 0
      ) {
        const stableIdOptions = response.suggestions.filter(
          (suggestion): suggestion is Suggestion & { player_id: number } =>
            suggestion.player_id != null,
        );
        if (stableIdOptions.length === response.suggestions.length) {
          setPlayerPickWizard({ options: stableIdOptions, sessionId: responseSessionId });
        }
      }
      // Refresh quota indicator after every completed turn
      setQuotaRefreshTrigger((n) => n + 1);
    } catch (err) {
      const errorText =
        err instanceof FplApiError
          ? err.message
          : 'Error inesperado. Por favor, inténtalo de nuevo.';

      const errorMessage: Message = {
        id: generateId(),
        role: 'assistant',
        text: errorText,
        isError: true,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  }, [loading, followUpArmedFor, sessionId, squadContext, webSearchOn, webSearchAvailable, messages, compareWizard]);

  // Guided Comparison: a chip tap. First tap stores player A client-side (no
  // round trip) and swaps the question to step 2. Second tap sends the canonical
  // `comparar {A} vs {B}` question through the normal send path — sendMessage
  // clears the wizard — so the wizard and free-text "A vs B" converge on the
  // identical ComparisonCard by construction.
  const handleSuggestionPick = useCallback((sendText: string) => {
    if (!compareWizard) return;
    if (compareWizard.playerA == null) {
      // First pick: store player A, swap to step 2 (no round trip).
      setCompareWizard({ playerA: sendText, options: compareWizard.options });
    } else {
      // Second pick: send canonical compare text; sendMessage clears the wizard.
      sendMessage(`/comparar ${compareWizard.playerA} vs ${sendText}`);
    }
  }, [compareWizard, sendMessage]);

  // Single-tap player disambiguation: show the friendly label in the user
  // bubble, but submit the stable FPL element id as authoritative data. If the
  // ambiguity came from a session turn, keep the selection in that session.
  const handlePlayerPick = useCallback((suggestion: Suggestion) => {
    if (suggestion.player_id == null) return;
    sendMessage(suggestion.label, suggestion.player_id, playerPickWizard?.sessionId ?? null);
  }, [playerPickWizard, sendMessage]);

  // Quick commands ("Vistas rápidas") are complete queries — send immediately
  // and jump to the chat screen, skipping the edit step.
  const handleSend = useCallback((text: string) => {
    setScreen(CHAT_SCREEN);
    sendMessage(text);
  }, [sendMessage]);

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-screen">
      <TopBar teamName={teamName} gw={gw} />

      <SwipePager screen={screen} onScreenChange={setScreen} labels={PAGER_LABELS}>
        {/* SCREEN 0 — Calendario (fixture ticker, deep-links into chat) */}
        <PagerScreen maxWidth={720}>
          <div className="h-full overflow-y-auto rounded-card border border-white/10 bg-bf-surface p-3">
            <FixturesBoard onAsk={handleInsert} />
          </div>
        </PagerScreen>

        {/* SCREEN 1 — Squad pitch */}
        <PagerScreen maxWidth={460}>
          <SquadPitch teamId={teamId} onAskPlayer={handleInsert} onGw={setGw} />
        </PagerScreen>

        {/* SCREEN 2 — Chat (home) */}
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
                  compareWizard={compareWizard}
                  onSuggestionPick={handleSuggestionPick}
                  playerPickWizard={playerPickWizard}
                  onPlayerPick={handlePlayerPick}
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
              <InputBar
                onSubmit={sendMessage}
                disabled={loading}
                insert={insert}
                webSearch={{
                  enabled: webSearchOn,
                  onToggle: () => setWebSearchOn((v) => !v),
                  available: webSearchAvailable,
                  upgradeUrl: '/subscribe',
                }}
              />
              <div className="flex justify-end">
                <QuotaIndicator userId={user?.id} tier={tier} refreshTrigger={quotaRefreshTrigger} />
              </div>
            </div>
          </div>
        </PagerScreen>

        {/* SCREEN 3 — Quick commands */}
        <PagerScreen maxWidth={520}>
          <div className="h-full rounded-card border border-white/10 bg-bf-surface overflow-hidden">
            <CommandPanel onInsert={handleInsert} onSend={handleSend} />
          </div>
        </PagerScreen>
      </SwipePager>
    </div>
  );
}
