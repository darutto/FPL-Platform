/**
 * @jest-environment jsdom
 *
 * Automatic retry of a "computing" EO answer: the reply carries `pending`, the chat shows a pending line and
 * polls POST /eo/poll by itself (fake timers here), swaps the card in on ready, stops after max_s with
 * «Reintentar», and never runs more than one poll. Renders the real ChatShell with a mocked API.
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

const reply = {
  final_text: 'Se esta calculando; pregunta de nuevo en unos segundos.',
  outcome: 'ok',
  supported: true,
  intent: 'unsupported',
  review_passed: true,
  llm_used: true,
  synthesis_turn: true,
  orch_outcome: null,
  degraded: false,
  suggestions: null,
};
const pending = { tool: 'get_league_eo', league_id: 77, eta_s: 20, poll_s: 4, max_s: 60 };
const card = {
  accent: 'turquoise', title: 'EO Work Mates', subtitle: 'exact', hero: null, pills: [], footer: null,
  columns: [{ header: '', align: 'left', kind: 'text' }], rows: [['Synthetic Player']],
};
const ready = { status: 'ready', text: 'Listo: EO Work Mates · GW 12', generic_card: card, suggestions: null };

function renderShell(locale: 'es' | 'en' = 'es') {
  return render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
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

async function startPending(locale: 'es' | 'en' = 'es') {
  const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
  renderShell(locale);
  await user.click(screen.getByText('connect-team'));
  await send(user, 'EO de mi liga');
  await screen.findByTestId('eo-pending');
  return user;
}

const tick = (ms: number) =>
  act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });

beforeEach(() => {
  jest.useFakeTimers();
  ask.mockReset().mockResolvedValue({ ...reply, pending });
  eoPoll.mockReset().mockResolvedValue({ status: 'computing', eta_s: 20, poll_s: 4 });
  localStorage.clear();
  document.cookie = 'bf_locale=; path=/; max-age=0';
});
afterEach(() => {
  jest.useRealTimers();
});

describe('EO auto-retry', () => {
  test('shows the pending line in the user language, with the eta', async () => {
    await startPending('es');
    expect(screen.getByText('Calculando el EO de tu liga… (~20 s)')).toBeInTheDocument();
    expect(screen.getByText(/pregunta de nuevo/)).toBeInTheDocument(); // the model text stays for the first reply
  });

  test('English wording, and the near-rank tool names its own line', async () => {
    ask.mockResolvedValue({ ...reply, pending: { tool: 'get_near_rank_eo', eta_s: 30, poll_s: 4, max_s: 60 } });
    await startPending('en');
    expect(screen.getByText('Calculating the EO near your rank… (~30 s)')).toBeInTheDocument();
  });

  test('polls every poll_s with the marker args and no model call; on ready the card and one line replace the bubble', async () => {
    await startPending();
    expect(eoPoll).not.toHaveBeenCalled();
    await tick(3999);
    expect(eoPoll).not.toHaveBeenCalled();
    await tick(1);
    expect(eoPoll).toHaveBeenCalledTimes(1);
    expect(eoPoll).toHaveBeenLastCalledWith({ tool: 'get_league_eo', team_id: 555, league_id: 77, locale: 'es' });
    await tick(4000);
    expect(eoPoll).toHaveBeenCalledTimes(2);
    eoPoll.mockResolvedValue(ready);
    await tick(4000);
    expect(await screen.findByText('Listo: EO Work Mates · GW 12')).toBeInTheDocument();
    expect(screen.getAllByText('Synthetic Player').length).toBeGreaterThan(0);
    expect(screen.queryByText(/pregunta de nuevo/)).toBeNull();
    expect(screen.queryByTestId('eo-pending')).toBeNull();
    expect(ask).toHaveBeenCalledTimes(1); // the whole thing was one /ask: the polls went to eoPoll
    await tick(20000);
    expect(eoPoll).toHaveBeenCalledTimes(3); // no polling after ready
  });

  test('after max_s it stops and offers «Reintentar»; the button polls again', async () => {
    await startPending();
    await tick(60000);
    const calls = eoPoll.mock.calls.length;
    expect(calls).toBeGreaterThanOrEqual(14);
    const retry = await screen.findByRole('button', { name: 'Reintentar' });
    expect(screen.queryByText(/Calculando/)).toBeNull();
    await tick(20000);
    expect(eoPoll).toHaveBeenCalledTimes(calls); // stopped
    eoPoll.mockResolvedValue(ready);
    await act(async () => {
      retry.click();
    });
    await tick(4000);
    expect(await screen.findByText('Listo: EO Work Mates · GW 12')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull();
  });

  test('unavailable ends the poll quietly and keeps the existing text', async () => {
    eoPoll.mockResolvedValue({ status: 'unavailable', reason: 'busy' });
    await startPending();
    await tick(4000);
    expect(screen.queryByTestId('eo-pending')).toBeNull();
    expect(screen.getByText(/pregunta de nuevo/)).toBeInTheDocument();
    await tick(20000);
    expect(eoPoll).toHaveBeenCalledTimes(1);
  });

  test('a 429 only waits: the next poll goes on', async () => {
    eoPoll.mockRejectedValueOnce(new FplApiError(429, 'x')).mockResolvedValue(ready);
    await startPending();
    await tick(4000);
    expect(screen.getByTestId('eo-pending')).toBeInTheDocument();
    await tick(4000);
    expect(await screen.findByText('Listo: EO Work Mates · GW 12')).toBeInTheDocument();
  });

  test('one pending bubble per conversation: a newer marker replaces the older; a new send cancels', async () => {
    const user = await startPending();
    ask.mockResolvedValue({ ...reply, final_text: 'Otra vez calculando.', pending: { ...pending, league_id: 42 } });
    await tick(1000);
    await send(user, 'otra vez');
    await waitFor(() => expect(screen.getByText('Otra vez calculando.')).toBeInTheDocument());
    expect(screen.getAllByTestId('eo-pending')).toHaveLength(1);
    await tick(4000);
    expect(eoPoll).toHaveBeenCalledTimes(1);
    expect(eoPoll).toHaveBeenLastCalledWith(expect.objectContaining({ league_id: 42 }));
    ask.mockResolvedValue({ ...reply, final_text: 'Sin marcador.' });
    await send(user, 'algo mas');
    await waitFor(() => expect(screen.getByText('Sin marcador.')).toBeInTheDocument());
    expect(screen.queryByTestId('eo-pending')).toBeNull();
    await tick(30000);
    expect(eoPoll).toHaveBeenCalledTimes(1); // the new question cancelled it
  });

  test('disconnecting the team stops the poll', async () => {
    const user = await startPending();
    await user.click(screen.getByText('disconnect-team'));
    expect(screen.queryByTestId('eo-pending')).toBeNull();
    await tick(10000);
    expect(eoPoll).not.toHaveBeenCalled();
  });
});
