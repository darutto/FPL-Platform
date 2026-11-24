/**
 * @jest-environment jsdom
 *
 * EO chip taps answered without a model, and «Cambiar de liga». The JSON is the backend's real output
 * (__tests__/fixtures/eo/*.json, generated and drift-checked by tests/test_eo_wire_fixtures.py): the tap's /ask
 * answer (card, one line with content, switch + change-league chips), the calculating answer with its pending
 * marker, and the league picker. The full bubble is rendered and the chips are tapped.
 */
import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
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
  UserButton: () => null,
}));
jest.mock('@/lib/dev-tier', () => ({ readDevTier: () => undefined }));

const ask = jest.fn();
const eoPoll = jest.fn();
class FplApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
jest.mock('@/lib/api', () => ({
  ask: (...a: unknown[]) => ask(...a),
  eoPoll: (...a: unknown[]) => eoPoll(...a),
  sessionAsk: jest.fn(),
  createSession: jest.fn(),
  clearSession: jest.fn(() => Promise.resolve()),
  FplApiError,
}));

jest.mock('../components/chat/SwipePager', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PagerScreen: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
jest.mock('../components/chat/StarterPrompts', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/SquadContextPanel', () => ({
  __esModule: true,
  default: ({ onTeamIdChange }: { onTeamIdChange?: (id: number | null, name: string | null) => void }) => (
    <div>
      <button onClick={() => onTeamIdChange?.(555, 'Synthetic FC')}>connect-team</button>
      <button onClick={() => onTeamIdChange?.(null, null)}>disconnect-team</button>
    </div>
  ),
}));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/CommandPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/squad/SquadPitch', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: () => null }));

import ChatShell from '../components/chat/ChatShell';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import { mainLeagueKey } from '@/lib/main-league';


/* eslint-disable @typescript-eslint/no-require-imports */
const tapReady = require('./fixtures/eo/tap-ready-league.json');
const tapComputing = require('./fixtures/eo/tap-computing-league.json');
const tapChange = require('./fixtures/eo/tap-change-league.json');
const readyLeague = require('./fixtures/eo/ready-league.json');

function renderShell() {
  return render(
    <LocaleProvider initialLocale="es" canSwitch={false}>
      <ChatShell />
    </LocaleProvider>,
  );
}

async function send(user: ReturnType<typeof userEvent.setup>, text: string) {
  const box = screen.getByRole('textbox');
  await user.click(box);
  await user.type(box, text);
  await user.type(box, '{Enter}');
}

const tick = (ms: number) =>
  act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });

beforeEach(() => {
  jest.useFakeTimers();
  ask.mockReset();
  eoPoll.mockReset();
  localStorage.clear();
  document.cookie = 'bf_locale=; path=/; max-age=0';
});
afterEach(() => {
  jest.useRealTimers();
});

describe('EO chip taps (real backend JSON)', () => {
  test('a tap answer shows the card, a line with content and both chips; «Cambiar de liga» opens the picker; a pick stores and asks', async () => {
    ask.mockResolvedValueOnce(tapReady);
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO en Friends');
    expect(await screen.findByText(tapReady.final_text)).toBeInTheDocument(); // the line names players, not just "Listo"
    expect(tapReady.final_text).toMatch(/^Cúbrete con .+; tu diferencial: .+\.$/);
    expect(screen.getAllByText(tapReady.generic_card.title).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'EO cerca de tu puesto' })).toBeInTheDocument();

    ask.mockResolvedValueOnce(tapChange);
    await user.click(screen.getByRole('button', { name: 'Cambiar de liga' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: 'Cambiar de liga', team_id: 555 });
    expect(ask.mock.calls[1][0].selected_player_id).toBeUndefined();
    const pick = await screen.findByRole('button', { name: 'Work Mates' }); // the current league is not offered
    expect(screen.queryByRole('button', { name: 'Friends' })).toBeNull();

    ask.mockResolvedValueOnce(tapReady);
    await user.click(pick);
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(3));
    expect(ask.mock.calls[2][0]).toMatchObject({ question: 'EO en Work Mates', team_id: 555, main_league_id: 77 });
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('77');
    // stored when the chip was tapped (before the answer): the next plain question already uses the new league
    await tick(100); // the pick's turn finishes before the next question
    ask.mockResolvedValueOnce(tapReady);
    await send(user, '¿Qué EO hay en mi liga?');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(4));
    expect(ask.mock.calls[3][0]).toMatchObject({ team_id: 555, main_league_id: 77 });
  });

  test('a pick whose answer is still computing already counts as the main league', async () => {
    ask.mockResolvedValueOnce(tapChange);
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'Cambiar de liga');
    const pick = await screen.findByRole('button', { name: 'Work Mates' });
    ask.mockResolvedValueOnce(tapComputing);
    await user.click(pick);
    await screen.findByTestId('eo-pending');
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('77'); // not waiting for the answer
    await tick(100);
    ask.mockResolvedValueOnce(tapReady);
    eoPoll.mockResolvedValue(readyLeague);
    await send(user, '¿Qué EO hay en mi liga?');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(3));
    expect(ask.mock.calls[2][0]).toMatchObject({ team_id: 555, main_league_id: 77 });
  });

  test('the calculating answer shows its line and the pending line, then the poll swaps in the card and the content line', async () => {
    ask.mockResolvedValueOnce(tapComputing);
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO en Friends');
    await screen.findByTestId('eo-pending');
    expect(screen.getAllByText(tapComputing.final_text).length).toBeGreaterThan(0); // the view's title: EO en Friends
    expect(tapComputing.final_text).toBe('EO en Friends');
    eoPoll.mockResolvedValue(readyLeague);
    await tick(4000);
    await waitFor(() => expect(screen.queryByTestId('eo-pending')).toBeNull());
    expect(screen.getByText(readyLeague.text)).toBeInTheDocument();
    expect(screen.getAllByText(readyLeague.generic_card.title).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Cambiar de liga' })).toBeInTheDocument();
  });
});
