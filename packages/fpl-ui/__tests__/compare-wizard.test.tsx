/**
 * @jest-environment jsdom
 *
 * Guided Comparison chip-wizard tests — Track D.
 *
 * Renders the real ChatShell + MessageList + SuggestionChips + InputBar and
 * exercises the two-step wizard end to end:
 *   1. A `/comparar` clarification turn returns backend `suggestions` → the
 *      wizard arms and step-1 chips render under the latest assistant bubble.
 *   2. Tapping the first chip stores player A client-side and swaps the
 *      question to step 2 (no extra network round trip).
 *   3. Tapping the second chip sends the canonical `comparar {A} vs {B}`
 *      question through the normal send path (asserted on the api.ask mock).
 *   4. A manual send exits the wizard.
 *   5. Chips render only under the LATEST assistant turn, never historical ones.
 *
 * The visual-only / network-y children of ChatShell are stubbed so the test is
 * hermetic; MessageList, SuggestionChips and InputBar are the real components.
 */
import React from 'react';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

// jsdom implements neither of these; MessageList/ChatShell use both.
if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = () => {};
}
// jsdom's crypto has no randomUUID; ChatShell uses it for message ids.
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

// --- Clerk: no signed-in user -----------------------------------------------
jest.mock('@clerk/nextjs', () => ({
  useUser: () => ({ user: undefined }),
}));

// --- dev tier: always production (undefined) ---------------------------------
jest.mock('@/lib/dev-tier', () => ({ readDevTier: () => undefined }));

// --- API layer: controllable mocks ------------------------------------------
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

// --- Stub visual / network-y children (keep MessageList, InputBar real) ------
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

function clarificationResponse() {
  return {
    final_text: '¿A quién quieres comparar?',
    outcome: 'needs_clarification',
    supported: true,
    intent: null,
    review_passed: true,
    llm_used: false,
    orch_outcome: null,
    degraded: false,
    suggestions: [
      { label: 'Palmer', send_text: 'Palmer' },
      { label: 'Salah', send_text: 'Salah' },
      { label: 'Saka', send_text: 'Saka' },
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
  return screen.queryByTestId('compare-wizard');
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

describe('Guided Comparison chip wizard', () => {
  test('two-step flow sends canonical "comparar A vs B"', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar ');

    // Step 1: wizard armed, first-player question + all chips.
    const wizard = await screen.findByTestId('compare-wizard');
    expect(within(wizard).getByText('¿Cuál es el primer jugador?')).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Palmer' })).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Salah' })).toBeInTheDocument();

    // First tap → step 2 question swap, chosen player recorded, no new send.
    await user.click(within(wizard).getByRole('button', { name: 'Palmer' }));
    const wizard2 = screen.getByTestId('compare-wizard');
    expect(within(wizard2).getByText('¿Contra quién lo comparamos?')).toBeInTheDocument();
    expect(within(wizard2).getByText('Palmer')).toBeInTheDocument();
    // Chosen player is filtered out of the remaining options.
    expect(within(wizard2).queryByRole('button', { name: 'Palmer' })).toBeNull();
    expect(within(wizard2).getByRole('button', { name: 'Salah' })).toBeInTheDocument();
    expect(ask).toHaveBeenCalledTimes(1); // no round trip on the first tap

    // Second tap → canonical send through the normal path.
    ask.mockResolvedValueOnce(plainResponse('Comparación lista'));
    await user.click(within(wizard2).getByRole('button', { name: 'Salah' }));

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/comparar Palmer vs Salah' });
    // Wizard cleared after the send.
    await waitFor(() => expect(getWizard()).toBeNull());

    // Regression: the ORIGINAL clarification turn's raw backend text
    // (final_text, e.g. English "Are you comparing two players?...") must
    // stay hidden forever, not just while the wizard was still active.
    // `compareWizard` clearing back to null on completion must not make it
    // reappear on the now-historical message.
    expect(screen.queryByText(clarificationResponse().final_text)).toBeNull();
  });

  test('a single name already typed seeds player A and jumps to step 2', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar Palmer');

    // Backend only returns needs_clarification here because the SECOND name
    // is missing (two valid names would resolve to outcome=ok) — so "Palmer"
    // is safe to seed as player A directly, skipping the redundant step-1
    // question the user already answered by typing.
    const wizard = await screen.findByTestId('compare-wizard');
    expect(within(wizard).getByText('¿Contra quién lo comparamos?')).toBeInTheDocument();
    expect(within(wizard).getByText('Palmer')).toBeInTheDocument();
    // Palmer is excluded from the remaining chip options (can't compare to self).
    expect(within(wizard).queryByRole('button', { name: 'Palmer' })).toBeNull();
    expect(within(wizard).getByRole('button', { name: 'Salah' })).toBeInTheDocument();

    ask.mockResolvedValueOnce(plainResponse('Comparación lista'));
    await user.click(within(wizard).getByRole('button', { name: 'Salah' }));

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/comparar Palmer vs Salah' });
  });

  test('a two-name attempt with an unresolved second name does not seed player A', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    // Contains a connector ("vs") — a comparison was attempted and failed for
    // another reason, so seeding the whole phrase as one name would be wrong.
    await sendText(user, '/comparar Palmer vs Zzzznotaplayer');

    const wizard = await screen.findByTestId('compare-wizard');
    expect(within(wizard).getByText('¿Cuál es el primer jugador?')).toBeInTheDocument();
  });

  test('typing the second player composes the canonical compare text, same as a chip tap', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar ');
    const wizard = await screen.findByTestId('compare-wizard');
    await user.click(within(wizard).getByRole('button', { name: 'Palmer' }));
    expect(ask).toHaveBeenCalledTimes(1); // still no round trip after the first pick

    // Typed reply, not a chip tap — must converge on the same canonical text
    // a second chip tap would have sent.
    ask.mockResolvedValueOnce(plainResponse('Comparación lista'));
    await sendText(user, 'Salah');

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/comparar Palmer vs Salah' });
    await waitFor(() => expect(getWizard()).toBeNull());
  });

  test('typing the first player in step 1 (no chip tapped) attempts a fresh /comparar', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar ');
    expect(await screen.findByTestId('compare-wizard')).toBeInTheDocument();

    ask.mockResolvedValueOnce(plainResponse('Comparación lista'));
    await sendText(user, 'Palmer');

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/comparar Palmer' });
  });

  test('an explicit slash command escapes the wizard instead of being composed into it', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar ');
    const wizard = await screen.findByTestId('compare-wizard');
    await user.click(within(wizard).getByRole('button', { name: 'Palmer' }));

    // A deliberate new command (leading "/") is sent as-is, not folded into
    // "/comparar Palmer vs /capitan Haaland".
    ask.mockResolvedValueOnce(plainResponse('capitan: Haaland'));
    await sendText(user, '/capitan Haaland');

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/capitan Haaland' });
    await waitFor(() => expect(getWizard()).toBeNull());
  });

  test('chips render only under the latest assistant turn', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar ');
    expect(await screen.findByTestId('compare-wizard')).toBeInTheDocument();

    // A newer turn with NO suggestions arrives → the wizard is gone entirely,
    // proving chips never linger on the now-historical clarification turn.
    ask.mockResolvedValueOnce(plainResponse('respuesta normal'));
    await sendText(user, 'quien es el mejor delantero');

    await waitFor(() => expect(getWizard()).toBeNull());
    expect(screen.getByText('respuesta normal')).toBeInTheDocument();
  });

  test('the wizard hints that a player outside the chips can still be typed', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(clarificationResponse());
    render(<ChatShell />);

    await sendText(user, '/comparar ');

    const wizard = await screen.findByTestId('compare-wizard');
    expect(within(wizard).getByText('¿No está tu jugador? Escribilo abajo.')).toBeInTheDocument();
  });
});
