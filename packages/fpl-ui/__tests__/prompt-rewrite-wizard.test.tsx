/**
 * @jest-environment jsdom
 *
 * Prompt-turn disambiguation wizard tests.
 *
 * Regression context: `/comparar Palmer vs Saka` with an ambiguous "Palmer"
 * rendered a dead-end English clarification with nothing to tap. The backend
 * now returns pick-one chips whose `send_text` is the user's own command with
 * the ambiguous slot resolved, marked `kind: 'prompt_rewrite'`.
 *
 * These chips arrive on a `compare_players` turn, so the UI's three chip flows
 * all have a claim on the same `suggestions` field. What's pinned here:
 *   1. prompt_rewrite chips arm the pick-one wizard, NOT the two-step compare
 *      wizard, even though the intent is compare_players.
 *   2. Tapping one sends send_text verbatim with NO selected_player_id —
 *      attaching the id would drop the second half of the comparison.
 *   3. The existing compare and stable-id flows still behave as before.
 *
 * Mirrors __tests__/player-pick-wizard.test.tsx's structure/mocking approach.
 */
import React from 'react';
import { render, screen, within, waitFor } from '@testing-library/react';
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** What the backend now returns for `/comparar Johnson vs Saka`. */
function ambiguousComparePromptResponse() {
  return {
    final_text:
      "Multiple players share the name 'Johnson'. Ask the user to clarify — for example by providing a player id, full name, or team name.",
    outcome: 'ambiguous',
    supported: true,
    intent: 'compare_players',
    review_passed: true,
    llm_used: false,
    orch_outcome: null,
    degraded: false,
    suggestions: [
      {
        label: 'Adam Johnson (CHE)',
        send_text: '/comparar Adam Johnson vs Saka',
        player_id: 6,
        kind: 'prompt_rewrite',
      },
      {
        label: 'Glen Johnson (MUN)',
        send_text: '/comparar Glen Johnson vs Saka',
        player_id: 7,
        kind: 'prompt_rewrite',
      },
    ],
  };
}

/** A bare `/comparar` — the two-step wizard this must not be confused with. */
function compareClarificationResponse() {
  return {
    final_text: '¿A quién quieres comparar?',
    outcome: 'needs_clarification',
    supported: true,
    intent: 'compare_players',
    review_passed: true,
    llm_used: false,
    orch_outcome: null,
    degraded: false,
    suggestions: [
      { label: 'Palmer', send_text: 'Palmer' },
      { label: 'Salah', send_text: 'Salah' },
    ],
  };
}

function plainResponse(text: string) {
  return {
    final_text: text,
    outcome: 'ok',
    supported: true,
    intent: 'comparison',
    review_passed: true,
    llm_used: false,
    orch_outcome: null,
    degraded: false,
    suggestions: null,
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

beforeEach(() => {
  ask.mockReset();
  sessionAsk.mockReset();
  createSession.mockReset();
  clearSession.mockReset();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Prompt-rewrite disambiguation chips', () => {
  test('an ambiguous /comparar turn arms the pick-one wizard, not the compare wizard', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousComparePromptResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar Johnson vs Saka');

    const wizard = await screen.findByTestId('player-pick-wizard');
    expect(within(wizard).getByText('¿Cuál de estos jugadores buscabas?')).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Adam Johnson (CHE)' })).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Glen Johnson (MUN)' })).toBeInTheDocument();
    // The two-step A/B wizard must stay out of this turn entirely.
    expect(screen.queryByTestId('compare-wizard')).toBeNull();
  });

  test("the backend's raw English clarification is not shown alongside the chips", async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousComparePromptResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar Johnson vs Saka');

    await screen.findByTestId('player-pick-wizard');
    expect(screen.queryByText(/multiple players share the name/i)).toBeNull();
  });

  test('tapping a chip re-sends the whole command and never a bare player id', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousComparePromptResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar Johnson vs Saka');
    const wizard = await screen.findByTestId('player-pick-wizard');

    ask.mockResolvedValueOnce(plainResponse('Adam Johnson supera a Saka'));
    await user.click(within(wizard).getByRole('button', { name: 'Adam Johnson (CHE)' }));

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({
      question: '/comparar Adam Johnson vs Saka',
    });
    // The critical assertion: attaching the id would hand off to a
    // single-player lookup and silently drop "vs Saka".
    expect(ask.mock.calls[1][0]).not.toHaveProperty('selected_player_id');
  });

  test('the chips clear once the rewritten command resolves', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousComparePromptResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar Johnson vs Saka');
    const wizard = await screen.findByTestId('player-pick-wizard');

    ask.mockResolvedValueOnce(plainResponse('Adam Johnson supera a Saka'));
    await user.click(within(wizard).getByRole('button', { name: 'Adam Johnson (CHE)' }));

    await screen.findByText('Adam Johnson supera a Saka');
    expect(screen.queryByTestId('player-pick-wizard')).toBeNull();
  });

  test('a bare /comparar still arms the two-step compare wizard', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(compareClarificationResponse());
    render(<ChatShell />);

    // Trailing space closes the slash menu so Enter submits the text rather
    // than picking a command — same convention as compare-wizard.test.tsx.
    await sendText(user, '/comparar ');

    await screen.findByTestId('compare-wizard');
    expect(screen.queryByTestId('player-pick-wizard')).toBeNull();
  });
});
