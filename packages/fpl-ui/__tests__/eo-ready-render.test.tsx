/**
 * @jest-environment jsdom
 *
 * What the bubble looks like AFTER a polled EO answer arrives. The JSON is the backend's real output
 * (__tests__/fixtures/eo/*.json, generated and drift-checked by tests/test_eo_wire_fixtures.py): the original
 * turn is outcome "unsupported_intent" (a computing result is not ok), the poll answers ready / needs_league.
 * The full bubble is rendered (card, one-line text, chips, outline), not just the state.
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


/* eslint-disable @typescript-eslint/no-require-imports */
const computingLeague = require('./fixtures/eo/computing-league.json');
const computingNear = require('./fixtures/eo/computing-near.json');
const readyLeague = require('./fixtures/eo/ready-league.json');
const readyNear = require('./fixtures/eo/ready-near.json');
const needsLeague = require('./fixtures/eo/needs-league.json');

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

async function startFrom(computing: unknown) {
  ask.mockReset().mockResolvedValue(computing);
  const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
  renderShell();
  await user.click(screen.getByText('connect-team'));
  await send(user, 'EO');
  await screen.findByTestId('eo-pending');
  return user;
}

beforeEach(() => {
  jest.useFakeTimers();
  eoPoll.mockReset();
  localStorage.clear();
  document.cookie = 'bf_locale=; path=/; max-age=0';
});
afterEach(() => {
  jest.useRealTimers();
});

describe('the bubble after a polled EO answer (real backend JSON)', () => {
  test('the fixture is the shape a real computing turn has: not ok, model text, pending', () => {
    for (const c of [computingLeague, computingNear]) {
      expect(c.outcome).not.toBe('ok');
      expect(c.pending).toBeTruthy();
      expect(c.generic_card).toBeNull();
    }
  });

  test.each([
    ['get_league_eo', computingLeague, readyLeague, 'EO en Friends', 'EO cerca de tu puesto'],
    ['get_near_rank_eo', computingNear, readyNear, 'EO cerca de tu puesto', 'EO en Friends'],
  ])('%s: card, one-line text and a tappable switch chip; nothing of the model text; not claimed by the model', async (_tool, computing, ready, title, chip) => {
    const user = await startFrom(computing);
    expect(screen.getByText(/pregunta de nuevo/)).toBeInTheDocument();
    eoPoll.mockResolvedValue(ready);
    await tick(4000);
    await waitFor(() => expect(screen.queryByTestId('eo-pending')).toBeNull());
    expect(screen.queryByText(/pregunta de nuevo/)).toBeNull();
    expect(screen.getAllByText(title).length).toBeGreaterThan(0); // the card header
    expect(screen.getByText(ready.text)).toBeInTheDocument(); // the one line, in the verdict band
    const region = screen.getByRole('region', { name: /respuesta estructurada|structured/i });
    expect(region.className).toContain('border-bf-gold/25'); // deterministic outline, not the model's turquoise
    expect(region.className).not.toContain('border-bf-turquoise/25');
    const askedBefore = ask.mock.calls.length;
    await user.click(screen.getByRole('button', { name: chip }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(askedBefore + 1));
    expect(ask.mock.calls[askedBefore][0]).toMatchObject({ question: chip });
    expect(ask.mock.calls[askedBefore][0].selected_player_id).toBeUndefined();
  });

  test('needs_league: the question and the pick chips show, and a tap stores and re-asks', async () => {
    const user = await startFrom(computingNear);
    eoPoll.mockResolvedValue(needsLeague);
    await tick(4000);
    await waitFor(() => expect(screen.queryByTestId('eo-pending')).toBeNull());
    expect(screen.queryByText(/pregunta de nuevo/)).toBeNull();
    await user.click(await screen.findByRole('button', { name: 'Work Mates' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: 'EO en Work Mates', team_id: 555, main_league_id: 77 });
  });

  test('a poll answering after a newer question changes nothing in that newer turn', async () => {
    const user = await startFrom(computingLeague);
    let resolvePoll: (v: unknown) => void = () => {};
    eoPoll.mockReturnValue(new Promise((r) => { resolvePoll = r; }));
    await tick(4000); // the poll is now in flight
    ask.mockResolvedValue({ ...computingLeague, pending: null, final_text: 'Otra respuesta.', outcome: 'ok', supported: true });
    await send(user, 'otra cosa');
    await waitFor(() => expect(screen.getByText('Otra respuesta.')).toBeInTheDocument());
    await act(async () => { resolvePoll(readyLeague); });
    expect(screen.getByText('Otra respuesta.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'EO cerca de tu puesto' })).toBeNull(); // no chips armed over the newer turn
  });
});
