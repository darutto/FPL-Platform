/**
 * @jest-environment jsdom
 *
 * Prompt-turn disambiguation wizard, English (the Spanish twin is prompt-rewrite-wizard.test.tsx).
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
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';

const SAKA_LINE = 'Adam Johnson beats Saka';

/** What the backend returns for `/compare Johnson vs Saka`: the user's own (English) command, rewritten per chip. */
function ambiguousCompareResponse() {
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
      { label: 'Adam Johnson (CHE)', send_text: '/compare Adam Johnson vs Saka', player_id: 6, kind: 'prompt_rewrite' },
      { label: 'Glen Johnson (MUN)', send_text: '/compare Glen Johnson vs Saka', player_id: 7, kind: 'prompt_rewrite' },
    ],
  };
}

function okResponse(text: string) {
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

function renderEn() {
  return render(
    <LocaleProvider initialLocale="en" canSwitch={false}>
      <ChatShell />
    </LocaleProvider>,
  );
}

async function sendText(user: ReturnType<typeof userEvent.setup>, text: string) {
  const textbox = screen.getByRole('textbox', { name: /ask the fpl assistant/i });
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

describe('Prompt-rewrite disambiguation chips in English', () => {
  test('an ambiguous /compare turn arms the pick-one wizard in English', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousCompareResponse());
    renderEn();

    await sendText(user, '/compare Johnson vs Saka');

    const wizard = await screen.findByTestId('player-pick-wizard');
    expect(within(wizard).getByText('Which of these players did you mean?')).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Adam Johnson (CHE)' })).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Glen Johnson (MUN)' })).toBeInTheDocument();
    expect(screen.queryByTestId('compare-wizard')).toBeNull();
    // no Spanish and no raw backend instruction beside the chips
    expect(screen.queryByText(/ask the user to clarify/i)).toBeNull();
    expect(screen.queryByText(/cu[aá]l de estos/i)).toBeNull();
  });

  test('tapping a chip re-sends the English command with no selected_player_id', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(ambiguousCompareResponse());
    renderEn();

    await sendText(user, '/compare Johnson vs Saka');
    const wizard = await screen.findByTestId('player-pick-wizard');

    ask.mockResolvedValueOnce(okResponse(SAKA_LINE));
    await user.click(within(wizard).getByRole('button', { name: 'Adam Johnson (CHE)' }));

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/compare Adam Johnson vs Saka' });
    expect(ask.mock.calls[1][0]).not.toHaveProperty('selected_player_id');
    await screen.findByText(SAKA_LINE);
    expect(screen.queryByTestId('player-pick-wizard')).toBeNull();
  });
});
