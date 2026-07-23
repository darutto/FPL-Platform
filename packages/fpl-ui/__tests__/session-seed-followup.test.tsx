/**
 * @jest-environment jsdom
 *
 * Follow-up session seeding — integration tests.
 *
 * Verifies ChatShell actually wires buildSessionSeed() into createSession()
 * at the moment a brand-new follow-up session is created, and — the
 * critical case an independent review pushed on — that this composes
 * correctly with the EXISTING non-follow-up branch's session-clearing
 * behavior so an intervening ordinary turn can never leave a stale session
 * to be silently reused by a later follow-up.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = () => {};
}
let __uuid = 0;
if (!globalThis.crypto) {
  (globalThis as unknown as { crypto: Crypto }).crypto = {} as Crypto;
}
if (typeof globalThis.crypto.randomUUID !== 'function') {
  Object.defineProperty(globalThis.crypto, 'randomUUID', {
    configurable: true,
    value: () => `test-uuid-${++__uuid}` as `${string}-${string}-${string}-${string}-${string}`,
  });
}

jest.mock('@clerk/nextjs', () => ({
  useUser: () => ({ user: undefined }),
}));
jest.mock('@/lib/dev-tier', () => ({ readDevTier: () => undefined }));

const ask = jest.fn();
const sessionAsk = jest.fn();
const createSession = jest.fn();
const clearSession = jest.fn();
class FplApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
jest.mock('@/lib/api', () => ({
  ask: (...a: unknown[]) => ask(...a),
  sessionAsk: (...a: unknown[]) => sessionAsk(...a),
  createSession: (...a: unknown[]) => createSession(...a),
  clearSession: (...a: unknown[]) => clearSession(...a),
  FplApiError,
}));

jest.mock('../components/chat/SwipePager', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PagerScreen: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
jest.mock('../components/chat/TopBar', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/StarterPrompts', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/SquadContextPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/CommandPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/squad/SquadPitch', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: () => null }));

import ChatShell from '../components/chat/ChatShell';
import { comparisonOkResponse } from './fixtures/sample-responses';
import type { AskResponse } from '@/lib/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ordinaryResponse(text: string): AskResponse {
  return {
    final_text: text,
    outcome: 'ok',
    supported: true,
    intent: 'player_summary',
    review_passed: true,
    llm_used: false,
    captain: null,
    captain_ranking: null,
    comparison: null,
    transfer: null,
    chip: null,
    fixture_run: null,
    differential: null,
    fixture_outlook: null,
    sub_responses: null,
    orch_outcome: null,
    degraded: false,
    resource_rows: null,
  } as AskResponse;
}

function comparisonWith(playerA: string, playerB: string): AskResponse {
  return {
    ...comparisonOkResponse,
    comparison: {
      ...comparisonOkResponse.comparison!,
      winner: playerA, // player A is always the "winner" in these fixtures
      player_a: { ...comparisonOkResponse.comparison!.player_a!, web_name: playerA },
      player_b: { ...comparisonOkResponse.comparison!.player_b!, web_name: playerB },
    },
  };
}

function getTextbox() {
  return screen.getByRole('textbox', { name: /pregunta/i });
}

async function sendText(user: ReturnType<typeof userEvent.setup>, text: string) {
  const textbox = getTextbox();
  await user.click(textbox);
  await user.type(textbox, text);
  await user.type(textbox, '{Enter}');
}

async function tapFollowUp(user: ReturnType<typeof userEvent.setup>) {
  const btn = await screen.findByRole('button', { name: /seguir conversaci[oó]n/i });
  await user.click(btn);
}

beforeEach(() => {
  ask.mockReset();
  sessionAsk.mockReset();
  createSession.mockReset();
  clearSession.mockReset();
  // clearSession's real return value is always a Promise; the app code
  // chains .catch() on it directly (fire-and-forget). A bare jest.fn()
  // resolves to undefined by default, which breaks that chain.
  clearSession.mockResolvedValue(undefined);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Follow-up session seeding', () => {
  test('tapping follow-up on a comparison reply seeds the new session with both player names', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(comparisonWith('Haaland', 'Salah'));
    createSession.mockResolvedValueOnce({
      session_id: 's1',
      created_at: 0,
      expires_after_seconds: 900,
    });
    sessionAsk.mockResolvedValueOnce(ordinaryResponse('ok'));

    render(<ChatShell />);
    await sendText(user, 'compare Haaland vs Salah');
    // ComparisonCard renders standalone (no separate text bubble) — the
    // follow-up button appearing is the reliable "turn completed" signal.
    await tapFollowUp(user);
    await sendText(user, 'y con Semenyo?');

    await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
    expect(createSession).toHaveBeenCalledWith({ last_comparison: ['Haaland', 'Salah'] });
    expect(sessionAsk).toHaveBeenCalledWith('s1', expect.objectContaining({ question: 'y con Semenyo?' }));
  });

  test(
    'the traced stale-session scenario: an intervening ordinary turn clears the ' +
      'session, so a later follow-up creates a NEW session seeded from the new reply, not the stale one',
    async () => {
      const user = userEvent.setup();

      // Turn 1: comparison A vs B, stateless.
      ask.mockResolvedValueOnce(comparisonWith('Haaland', 'Salah'));
      createSession.mockResolvedValueOnce({
        session_id: 's-A',
        created_at: 0,
        expires_after_seconds: 900,
      });
      sessionAsk.mockResolvedValueOnce(ordinaryResponse('follow-up on A answered'));

      render(<ChatShell />);
      await sendText(user, 'compare Haaland vs Salah');

      // Follow up on A → session s-A created, seeded from A.
      await tapFollowUp(user);
      await sendText(user, 'y con Semenyo?');
      await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
      expect(createSession).toHaveBeenNthCalledWith(1, { last_comparison: ['Haaland', 'Salah'] });
      // Wait for the follow-up turn to fully settle (loading reset to false)
      // before sending the next message — otherwise sendMessage's own
      // `if (!input || loading) return;` guard silently no-ops the next send.
      await screen.findByText('follow-up on A answered');

      // An ORDINARY, unarmed message — goes through stateless ask(), and per
      // the existing (pre-existing, not part of this change) non-follow-up
      // branch, must clear session s-A.
      ask.mockResolvedValueOnce(comparisonWith('Palmer', 'Foden'));
      await sendText(user, 'compare Palmer vs Foden');
      await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
      expect(clearSession).toHaveBeenCalledWith('s-A');
      await waitFor(() => {
        expect(screen.getAllByText(/Palmer|Foden/).length).toBeGreaterThan(0);
      });

      // Now follow up on THIS new reply (B = Palmer/Foden comparison).
      createSession.mockResolvedValueOnce({
        session_id: 's-B',
        created_at: 0,
        expires_after_seconds: 900,
      });
      sessionAsk.mockResolvedValueOnce(ordinaryResponse('follow-up on B answered'));

      await tapFollowUp(user);
      await sendText(user, 'y con Watkins?');

      // A SECOND, genuinely new session — seeded from B (Palmer/Foden), not
      // from the stale A (Haaland/Salah).
      await waitFor(() => expect(createSession).toHaveBeenCalledTimes(2));
      expect(createSession).toHaveBeenNthCalledWith(2, { last_comparison: ['Palmer', 'Foden'] });
      expect(sessionAsk).toHaveBeenLastCalledWith(
        's-B',
        expect.objectContaining({ question: 'y con Watkins?' }),
      );
    },
  );

  test('consecutive follow-ups within the same chain reuse the session — no reseed', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(comparisonWith('Haaland', 'Salah'));
    createSession.mockResolvedValueOnce({
      session_id: 's1',
      created_at: 0,
      expires_after_seconds: 900,
    });
    sessionAsk.mockResolvedValueOnce(comparisonWith('Haaland', 'Semenyo'));

    render(<ChatShell />);
    await sendText(user, 'compare Haaland vs Salah');

    await tapFollowUp(user);
    await sendText(user, 'y con Semenyo?');
    await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));

    // Tap follow-up AGAIN on the session-routed reply, send again — must
    // reuse s1 directly via sessionAsk, no second createSession call.
    sessionAsk.mockResolvedValueOnce(ordinaryResponse('second follow-up answered'));
    await tapFollowUp(user);
    await sendText(user, 'y con Watkins?');

    await waitFor(() => expect(sessionAsk).toHaveBeenCalledTimes(2));
    expect(createSession).toHaveBeenCalledTimes(1); // still just once
    expect(sessionAsk).toHaveBeenLastCalledWith(
      's1',
      expect.objectContaining({ question: 'y con Watkins?' }),
    );
  });

  test('follow-up armed for a non-ok response creates a session with no seed, not a crash', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce({
      final_text: 'No encontré una herramienta para responder a esto.',
      outcome: 'unsupported_intent',
      supported: false,
      intent: null,
      review_passed: false,
      llm_used: false,
      captain: null,
      captain_ranking: null,
      comparison: null,
      transfer: null,
      chip: null,
      fixture_run: null,
      differential: null,
      fixture_outlook: null,
      sub_responses: null,
      orch_outcome: null,
      degraded: false,
      resource_rows: null,
    } as AskResponse);
    createSession.mockResolvedValueOnce({
      session_id: 's1',
      created_at: 0,
      expires_after_seconds: 900,
    });
    sessionAsk.mockResolvedValueOnce(ordinaryResponse('ok'));

    render(<ChatShell />);
    await sendText(user, 'asdlkjasdlkj nonsense');
    await screen.findByText(/No encontré una herramienta/);

    await tapFollowUp(user);
    await sendText(user, 'y ahora?');

    await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
    expect(createSession).toHaveBeenCalledWith(undefined);
  });
});
