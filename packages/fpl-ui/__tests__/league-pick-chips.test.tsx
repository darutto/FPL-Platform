/**
 * @jest-environment jsdom
 *
 * The "which league?" chips (get_league_eo): one chip per private league, in the user's language; a tap
 * stores that league as the main one, sends the question naming it WITH that league on the request, and
 * the next turns keep sending it. Renders the real ChatShell with a mocked API.
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
  UserButton: () => null,
}));
jest.mock('@/lib/dev-tier', () => ({ readDevTier: () => undefined }));

const ask = jest.fn();
class FplApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
jest.mock('@/lib/api', () => ({
  ask: (...a: unknown[]) => ask(...a),
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
import { MAIN_LEAGUE_LS_KEY } from '@/lib/main-league';

const reply = {
  final_text: 'ok',
  outcome: 'ok',
  supported: true,
  intent: 'player_form',
  review_passed: true,
  llm_used: false,
  orch_outcome: null,
  degraded: false,
  suggestions: null,
};

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

beforeEach(() => {
  ask.mockReset().mockResolvedValue(reply);
  localStorage.clear();
  document.cookie = 'bf_locale=; path=/; max-age=0';
});

const pickerReply = {
  ...reply,
  intent: 'plan_to_sign',
  final_text: 'Tienes varias ligas.',
  suggestions: [
    { label: 'Friends', send_text: 'EO en Friends', kind: 'league_pick', league_id: 42 },
    { label: 'Work Mates', send_text: 'EO en Work Mates', kind: 'league_pick', league_id: 77 },
  ],
};

describe('league chips', () => {
  test('a picker turn shows one chip per league, asking which league (not which player)', async () => {
    ask.mockResolvedValueOnce(pickerReply);
    const user = userEvent.setup();
    renderShell('es');
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO en mi liga');
    expect(await screen.findByRole('button', { name: 'Friends' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Work Mates' })).toBeInTheDocument();
    expect(screen.getByText('¿De cuál de tus ligas?')).toBeInTheDocument();
    expect(screen.queryByText('¿Cuál de estos jugadores buscabas?')).toBeNull();
  });

  test('the same question in English', async () => {
    ask.mockResolvedValueOnce(pickerReply);
    const user = userEvent.setup();
    renderShell('en');
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO in my league');
    expect(await screen.findByText('Which of your leagues?')).toBeInTheDocument();
  });

  test('tapping a chip stores the league, sends its question with that league on the request, and keeps sending it', async () => {
    ask.mockResolvedValueOnce(pickerReply);
    const user = userEvent.setup();
    renderShell('es');
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO en mi liga');
    await user.click(await screen.findByRole('button', { name: 'Work Mates' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: 555, main_league_id: null });
    expect(ask.mock.calls[1][0]).toMatchObject({ question: 'EO en Work Mates', team_id: 555, main_league_id: 77 });
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBe('77');
    await send(user, 'otra vez');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(3));
    expect(ask.mock.calls[2][0]).toMatchObject({ main_league_id: 77 });
    expect(screen.queryByRole('button', { name: 'Friends' })).toBeNull(); // the chips are gone once answered
  });

  test('the chip answer is a plain question: no selected_player_id, no player wizard', async () => {
    ask.mockResolvedValueOnce(pickerReply);
    const user = userEvent.setup();
    renderShell('es');
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO en mi liga');
    await user.click(await screen.findByRole('button', { name: 'Friends' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0].selected_player_id).toBeUndefined();
  });

  test('a stored league is replaced by the one picked, and disconnecting still clears it', async () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '42');
    ask.mockResolvedValueOnce(pickerReply);
    const user = userEvent.setup();
    renderShell('es');
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO en mi liga');
    await user.click(await screen.findByRole('button', { name: 'Work Mates' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBe('77');
    await user.click(screen.getByText('disconnect-team'));
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull();
  });
});


const switchReply = {
  ...reply,
  intent: 'plan_to_sign',
  final_text: 'Haaland es la cobertura mas importante.',
  suggestions: [{ label: 'EO cerca de tu puesto', send_text: 'EO cerca de tu puesto', kind: 'eo_switch' }],
};

describe('EO switch chip', () => {
  test('is titled "another view", sends its text verbatim and is a plain question', async () => {
    ask.mockResolvedValueOnce(switchReply);
    const user = userEvent.setup();
    renderShell('es');
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO en mi liga');
    expect(await screen.findByText('Otra vista')).toBeInTheDocument();
    expect(screen.queryByText('¿Cuál de estos jugadores buscabas?')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'EO cerca de tu puesto' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: 'EO cerca de tu puesto', team_id: 555 });
    expect(ask.mock.calls[1][0].selected_player_id).toBeUndefined();
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull(); // not a league pick: nothing is stored
  });

  test('the title in English', async () => {
    ask.mockResolvedValueOnce({ ...switchReply, suggestions: [{ label: 'EO near your rank', send_text: 'EO near your rank', kind: 'eo_switch' }] });
    const user = userEvent.setup();
    renderShell('en');
    await user.click(screen.getByText('connect-team'));
    await send(user, 'EO in my league');
    expect(await screen.findByText('Another view')).toBeInTheDocument();
  });
});
