/**
 * @jest-environment jsdom
 *
 * i60 -- ambiguous players on player_form and past-season turns reach the UI
 * as tappable chips, and the tap resolves the RIGHT player.
 *
 *   player_form (current season): intent is in WIZARD_ARMING_INTENTS, chips
 *     carry stable ids -> tap sends selected_player_id.
 *   player_season_points (past season): chips are kind
 *     'historical_player_rewrite' with NO id -> tap sends send_text verbatim
 *     and NO selected_player_id (those ids belong to another season's store).
 *
 * Mutations that kill this file: drop 'player_form' from WIZARD_ARMING_INTENTS
 * (test 1: no wizard); drop the rewrite branch from handlePlayerPick (test 3:
 * the tap sends nothing).
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


function playerFormAmbiguousResponse() {
  return {
    final_text: 'Multiple players match "gabriel".',
    outcome: 'ambiguous',
    supported: true,
    intent: 'player_form',
    review_passed: true,
    llm_used: true,
    orch_outcome: 'ok',
    degraded: false,
    suggestions: [
      { label: 'Gabriel (ARS)', send_text: 'Gabriel ARS', player_id: 11 },
      { label: 'Gabriel (MCI)', send_text: 'Gabriel MCI', player_id: 22 },
    ],
  };
}

function seasonPointsAmbiguousResponse() {
  return {
    final_text: "Multiple players share the name 'salah'.",
    outcome: 'ambiguous',
    supported: true,
    intent: 'player_season_points',
    review_passed: true,
    llm_used: true,
    orch_outcome: 'ok',
    degraded: false,
    suggestions: [
      {
        label: 'Salah (LIV)',
        send_text: 'puntos de Mohamed Salah (LIV) en la temporada 2025-2026',
        kind: 'historical_player_rewrite',
      },
      {
        label: 'Salah (BOU)',
        send_text: 'puntos de Mohamed Salah (BOU) en la temporada 2025-2026',
        kind: 'historical_player_rewrite',
      },
    ],
  };
}

function plainResponse(text: string, intent = 'player_form') {
  return {
    final_text: text,
    outcome: 'ok',
    supported: true,
    intent,
    review_passed: true,
    llm_used: true,
    orch_outcome: 'ok',
    degraded: false,
    suggestions: null,
  };
}

async function sendText(user: ReturnType<typeof userEvent.setup>, text: string) {
  const textbox = screen.getByRole('textbox', { name: /pregunta/i });
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

describe('i60 — player_form ambiguity (stable-id chips)', () => {
  test('an ambiguous player_form turn arms the pick-one wizard', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(playerFormAmbiguousResponse());
    render(<ChatShell />);

    await sendText(user, 'forma de gabriel');

    const wizard = await screen.findByTestId('player-pick-wizard');
    expect(within(wizard).getByRole('button', { name: 'Gabriel (ARS)' })).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Gabriel (MCI)' })).toBeInTheDocument();
    expect(screen.queryByTestId('compare-wizard')).toBeNull();
  });

  test('tapping a chip sends the stable id as selected_player_id', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(playerFormAmbiguousResponse());
    render(<ChatShell />);

    await sendText(user, 'forma de gabriel');
    const wizard = await screen.findByTestId('player-pick-wizard');

    ask.mockResolvedValueOnce(plainResponse('Gabriel (MCI): 3 goles en 5 jornadas'));
    await user.click(within(wizard).getByRole('button', { name: 'Gabriel (MCI)' }));

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ selected_player_id: 22 });
  });
});

describe('i60 — past-season ambiguity (historical rewrite chips)', () => {
  test('historical chips are visible even though they carry no player_id', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(seasonPointsAmbiguousResponse());
    render(<ChatShell />);

    await sendText(user, 'puntos de salah la temporada pasada');

    const wizard = await screen.findByTestId('player-pick-wizard');
    expect(within(wizard).getByRole('button', { name: 'Salah (LIV)' })).toBeInTheDocument();
    expect(within(wizard).getByRole('button', { name: 'Salah (BOU)' })).toBeInTheDocument();
    // the raw English clarification stays hidden behind the chips
    expect(screen.queryByText(/multiple players share the name/i)).toBeNull();
  });

  test('tapping a historical chip sends its canonical question and NO selected_player_id', async () => {
    const user = userEvent.setup();
    ask.mockResolvedValueOnce(seasonPointsAmbiguousResponse());
    render(<ChatShell />);

    await sendText(user, 'puntos de salah la temporada pasada');
    const wizard = await screen.findByTestId('player-pick-wizard');

    ask.mockResolvedValueOnce(plainResponse('Salah (BOU, FWD) — 2025-2026: 40 points', 'player_season_points'));
    await user.click(within(wizard).getByRole('button', { name: 'Salah (BOU)' }));

    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({
      question: 'puntos de Mohamed Salah (BOU) en la temporada 2025-2026',
    });
    expect(ask.mock.calls[1][0]).not.toHaveProperty('selected_player_id');
    await screen.findByText(/40 points/);
    expect(screen.queryByTestId('player-pick-wizard')).toBeNull();
  });
});
