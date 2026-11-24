/**
 * @jest-environment jsdom
 *
 * A real team change (A -> B, A -> none) drops what was built for team A: the armed league picker, the EO poll
 * (and an in-flight reply of it) and the plan_to_sign state. The same team reconnecting (A -> A) keeps them.
 * Real localStorage is asserted for both teams. Renders the real ChatShell with a mocked API.
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
      <button onClick={() => onTeamIdChange?.(556, 'Other FC')}>connect-team-b</button>
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


const base = {
  final_text: 'ok', outcome: 'ok', supported: true, intent: 'unsupported', review_passed: true, llm_used: true,
  synthesis_turn: true, orch_outcome: null, degraded: false, suggestions: null,
};
const pickerReply = {
  ...base,
  final_text: 'Tienes varias ligas.',
  suggestions: [
    { label: 'Friends', send_text: 'EO en Friends', kind: 'league_pick', league_id: 42 },
    { label: 'Work Mates', send_text: 'EO en Work Mates', kind: 'league_pick', league_id: 77 },
  ],
};
const computing = {
  ...base, final_text: 'Se esta calculando; pregunta de nuevo.', outcome: 'unsupported_intent', supported: false,
  pending: { tool: 'get_league_eo', league_id: 77, eta_s: 20, poll_s: 4, max_s: 60 },
};
const planReply = { ...base, final_text: 'Plan.', plan_state: { target: 'synthetic', sold: [1, 2] } };
const readyCard = {
  status: 'ready', text: 'Listo: EO', suggestions: null,
  generic_card: { accent: 'turquoise', title: 'EO Work Mates', subtitle: 'x', hero: null, pills: [], footer: null,
    columns: [{ header: '', align: 'left', kind: 'text' }], rows: [['Synthetic Player']] },
};

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

const keyA = mainLeagueKey(555);
const keyB = mainLeagueKey(556);

async function armPickerOnA() {
  ask.mockReset().mockResolvedValueOnce(pickerReply);
  const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
  renderShell();
  await user.click(screen.getByText('connect-team'));
  await send(user, 'EO en mi liga');
  await screen.findByRole('button', { name: 'Friends' });
  return user;
}

beforeEach(() => {
  jest.useFakeTimers();
  ask.mockReset();
  eoPoll.mockReset().mockResolvedValue({ status: 'computing', eta_s: 20, poll_s: 4 });
  localStorage.clear();
  document.cookie = 'bf_locale=; path=/; max-age=0';
});
afterEach(() => {
  jest.useRealTimers();
});

describe('a real team change drops what was built for the old team', () => {
  test("A -> B: the armed league picker is gone, so a tap cannot store A's league under B; storage of both teams untouched", async () => {
    localStorage.setItem(keyA, '42');
    const user = await armPickerOnA();
    await user.click(screen.getByText('connect-team-b'));
    expect(screen.queryByRole('button', { name: 'Friends' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Work Mates' })).toBeNull();
    expect(localStorage.getItem(keyA)).toBe('42');
    expect(localStorage.getItem(keyB)).toBeNull();
  });

  test('A -> none: the picker is gone too', async () => {
    const user = await armPickerOnA();
    await user.click(screen.getByText('disconnect-team'));
    expect(screen.queryByRole('button', { name: 'Friends' })).toBeNull();
    expect(localStorage.getItem(keyA)).toBeNull();
    expect(localStorage.getItem(keyB)).toBeNull();
  });

  test('A -> A (reconnect or refresh of the same team) keeps the picker, and a tap stores under A', async () => {
    const user = await armPickerOnA();
    await user.click(screen.getByText('connect-team')); // the panel reporting the same team again
    const chip = await screen.findByRole('button', { name: 'Work Mates' });
    ask.mockResolvedValueOnce(base);
    await user.click(chip);
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(localStorage.getItem(keyA)).toBe('77');
    expect(localStorage.getItem(keyB)).toBeNull();
  });

  test('none -> A on mount does not clear what was armed for A', async () => {
    localStorage.setItem('fpl_team_id', '555');
    ask.mockReset().mockResolvedValueOnce(pickerReply);
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell(); // team hydrated from storage (none -> A), no panel callback yet
    await send(user, 'EO en mi liga');
    await screen.findByRole('button', { name: 'Friends' });
    await user.click(screen.getByText('connect-team')); // the panel then confirms the same team
    expect(screen.getByRole('button', { name: 'Friends' })).toBeInTheDocument();
  });

  test("A -> B cancels the EO poll: no poll runs with B's team id and A's league", async () => {
    ask.mockResolvedValue(computing);
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO');
    await screen.findByTestId('eo-pending');
    await user.click(screen.getByText('connect-team-b'));
    expect(screen.queryByTestId('eo-pending')).toBeNull();
    await tick(20000);
    expect(eoPoll).not.toHaveBeenCalled();
  });

  test('A -> B drops a poll reply already in flight: the old bubble is not replaced', async () => {
    ask.mockResolvedValue(computing);
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO');
    await screen.findByTestId('eo-pending');
    let resolvePoll: (v: unknown) => void = () => {};
    eoPoll.mockReturnValue(new Promise((r) => { resolvePoll = r; }));
    await tick(4000);
    expect(eoPoll).toHaveBeenCalledTimes(1);
    expect(eoPoll).toHaveBeenLastCalledWith(expect.objectContaining({ team_id: 555, league_id: 77 }));
    await user.click(screen.getByText('connect-team-b'));
    await act(async () => { resolvePoll(readyCard); });
    expect(screen.queryByText('EO Work Mates')).toBeNull();
    expect(screen.getByText(/pregunta de nuevo/)).toBeInTheDocument();
    await tick(20000);
    expect(eoPoll).toHaveBeenCalledTimes(1);
  });

  test('plan state: carried to the next turn of the same team, dropped after a switch to B', async () => {
    ask.mockResolvedValue(planReply);
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'como ficho a X');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    await tick(100);
    await user.click(screen.getByText('connect-team')); // same team: control, the state still rides
    ask.mockResolvedValue(base);
    await send(user, 'a quien mas vendo');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    await tick(100); // the turn finishes (loading off) before the next send
    expect(ask.mock.calls[1][0].plan_state).toEqual({ target: 'synthetic', sold: [1, 2] });

    ask.mockResolvedValue(planReply);
    await send(user, 'como ficho a Y');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(3));
    await tick(100);
    await user.click(screen.getByText('connect-team-b'));
    ask.mockResolvedValue(base);
    await send(user, 'a quien mas vendo');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(4));
    expect(ask.mock.calls[3][0].plan_state).toBeUndefined();
    expect(ask.mock.calls[3][0]).toMatchObject({ team_id: 556 });
  });
});

describe('an answer that arrives after the team changed', () => {
  const late = {
    ...pickerReply,
    final_text: 'Respuesta lenta.',
    pending: { tool: 'get_league_eo', league_id: 77, eta_s: 20, poll_s: 4, max_s: 60 },
    plan_state: { target: 'synthetic', sold: [1, 2] },
  };

  async function sendSlow(user: ReturnType<typeof userEvent.setup>) {
    let resolveAsk: (v: unknown) => void = () => {};
    ask.mockReset().mockReturnValueOnce(new Promise((r) => { resolveAsk = r; }));
    await send(user, 'EO en mi liga');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    return resolveAsk;
  }

  async function expectOldTeamStuffDropped(user: ReturnType<typeof userEvent.setup>) {
    expect(screen.getByText('Respuesta lenta.')).toBeInTheDocument(); // the text stays
    expect(screen.queryByRole('button', { name: 'Friends' })).toBeNull(); // no picker armed for the old team
    expect(screen.queryByTestId('eo-pending')).toBeNull(); // no poll for it
    await tick(20000);
    expect(eoPoll).not.toHaveBeenCalled();
    ask.mockResolvedValue(base);
    await send(user, 'a quien mas vendo');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0].plan_state).toBeUndefined(); // its plan state does not ride the next question
  }

  test('A -> B while the answer is in flight: text kept, picker / poll / plan state dropped', async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    const resolveAsk = await sendSlow(user);
    await user.click(screen.getByText('connect-team-b'));
    await act(async () => { resolveAsk(late); });
    await expectOldTeamStuffDropped(user);
    expect(localStorage.getItem(keyA)).toBeNull();
    expect(localStorage.getItem(keyB)).toBeNull();
  });

  test('A -> none -> B while the answer is in flight: the same', async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    const resolveAsk = await sendSlow(user);
    await user.click(screen.getByText('disconnect-team'));
    await user.click(screen.getByText('connect-team-b'));
    await act(async () => { resolveAsk(late); });
    await expectOldTeamStuffDropped(user);
  });

  test('none -> A hydration: sent with the stored id, the panel then confirms the same id: nothing is dropped', async () => {
    localStorage.setItem('fpl_team_id', '555');
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell(); // the stored team is in use at once
    const resolveAsk = await sendSlow(user);
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: 555 });
    await user.click(screen.getByText('connect-team')); // the panel confirms the same team
    await act(async () => { resolveAsk(late); });
    expect(await screen.findByRole('button', { name: 'Friends' })).toBeInTheDocument(); // picker armed
    expect(screen.getByTestId('eo-pending')).toBeInTheDocument(); // poll started
  });
});
