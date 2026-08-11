/**
 * @jest-environment jsdom
 *
 * Single-tap player disambiguation wizard tests.
 *
 * Renders the real ChatShell + MessageList + SuggestionChips (PlayerPickChips)
 * + InputBar and exercises the one-tap flow end to end:
 *   1. An ambiguous player_snapshot turn returns backend `suggestions` → the
 *      wizard arms and chips render under the latest assistant bubble.
 *   2. Tapping a chip sends its send_text verbatim through the normal send
 *      path (single round trip, unlike the two-step compare wizard).
 *   3. Chips render only under the LATEST assistant turn.
 *   4. The compare wizard and this wizard never collide -- each only arms
 *      for its own intent, even though both share the generic
 *      `response.suggestions` field.
 *
 * Mirrors __tests__/compare-wizard.test.tsx's structure/mocking approach.
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

function ambiguousPlayerResponse() {
  return {
    final_text: "Multiple players match 'johnson'. Please specify.",
    outcome: 'ambiguous',
    supported: true,
    intent: 'player_snapshot',
    review_passed: true,
    llm_used: false,
    orch_outcome: 'ambiguous',
    degraded: false,
    suggestions: [
      { label: 'Johnson (CHE)', send_text: 'Johnson CHE' },
      { label: 'Johnson (MUN)', send_text: 'Johnson MUN' },
    ],
  };
}

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
    intent: 'player_form',
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

function getWizard() {
  return screen.queryByTestId('player-pick-wizard');
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

describe('Player disambiguation chip wizard', () => {
  test('an ambiguous player_snapshot turn arms the wizard with both candidates', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousPlayerResponse());
    render(<ChatShell />);

    await sendText(user, 'johnson');

    const wizard = await screen.findByTestId('player-pick-wizard');
    expect(within(wizard).getByText('¿Cuál de estos jugadores buscabas?')).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Johnson (CHE)' })).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Johnson (MUN)' })).toBeInTheDocument();
  });

  test('tapping a chip sends its send_text verbatim in a single round trip', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousPlayerResponse());
    render(<ChatShell />);

    await sendText(user, 'johnson');
    const wizard = await screen.findByTestId('player-pick-wizard');

    ask.mockResolvedValueOnce(plainResponse('Johnson (CHE): 45 puntos'));
    await user.click(within(wizard).getByRole('button', { name: 'Johnson (CHE)' }));

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: 'Johnson CHE' });
    await waitFor(() => expect(getWizard()).toBeNull());
  });

  test('chips render only under the latest assistant turn', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousPlayerResponse());
    render(<ChatShell />);

    await sendText(user, 'johnson');
    expect(await screen.findByTestId('player-pick-wizard')).toBeInTheDocument();

    ask.mockResolvedValueOnce(plainResponse('respuesta normal'));
    await sendText(user, 'quien es el mejor delantero');

    await waitFor(() => expect(getWizard()).toBeNull());
    expect(screen.getByText('respuesta normal')).toBeInTheDocument();
  });

  test('a compare_players clarification does not arm the player-pick wizard', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(compareClarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar ');

    expect(await screen.findByTestId('compare-wizard')).toBeInTheDocument();
    expect(getWizard()).toBeNull();
  });

  test('an ambiguous player_snapshot turn does not arm the compare wizard', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousPlayerResponse());
    render(<ChatShell />);

    await sendText(user, 'johnson');

    expect(await screen.findByTestId('player-pick-wizard')).toBeInTheDocument();
    expect(screen.queryByTestId('compare-wizard')).toBeNull();
  });
});
