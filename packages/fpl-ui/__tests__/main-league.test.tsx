/**
 * @jest-environment jsdom
 *
 * The user's main mini-league: stored next to the team id, sent on every turn as
 * `main_league_id`, surviving a reload, and gone when the team is disconnected.
 * Renders the real ChatShell; the team panel is replaced by two buttons that report a
 * connect / disconnect exactly as the real panel does (onTeamIdChange).
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
import {
  MAIN_LEAGUE_LS_KEY,
  parseLeagueId,
  readMainLeagueId,
  writeMainLeagueId,
} from '@/lib/main-league';

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

beforeEach(() => {
  ask.mockReset().mockResolvedValue(reply);
  localStorage.clear();
  document.cookie = 'bf_locale=; path=/; max-age=0';
});

// -- the storage helpers ---------------------------------------------------------------------

describe('lib/main-league', () => {
  test.each([
    ['42', 42],
    [' 42 ', 42],
    [42, 42],
    ['0', null],
    ['-3', null],
    ['4.2', null],
    ['abc', null],
    ['', null],
    [null, null],
    [undefined, null],
    [NaN, null],
    [2 ** 60, null],
  ])('parseLeagueId(%p) = %p', (raw, expected) => {
    expect(parseLeagueId(raw)).toBe(expected);
  });

  test('write then read round-trips, and null (or junk) clears', () => {
    writeMainLeagueId(77);
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBe('77');
    expect(readMainLeagueId()).toBe(77);
    writeMainLeagueId(null);
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull();
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, 'not-a-number');
    expect(readMainLeagueId()).toBeNull();
  });

  test('unavailable storage never throws', () => {
    const boom = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const boomSet = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readMainLeagueId()).toBeNull();
    expect(() => writeMainLeagueId(5)).not.toThrow();
    boom.mockRestore();
    boomSet.mockRestore();
  });
});

// -- the request ---------------------------------------------------------------------------------

describe('ChatShell and main_league_id', () => {
  test('no team and nothing stored: main_league_id is null', async () => {
    const user = userEvent.setup();
    renderShell();
    await send(user, 'hola');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: null, main_league_id: null });
  });

  test('a stored league is sent with the team id on every turn', async () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'primera');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: 555, main_league_id: 4242 });
    await send(user, 'segunda');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ team_id: 555, main_league_id: 4242 });
  });

  test('a stored league without a connected team is not sent', async () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    const user = userEvent.setup();
    renderShell();
    await send(user, 'hola');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: null, main_league_id: null });
  });

  test('it survives a reload: a fresh mount reads it back and sends it once the team reconnects', async () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    const first = renderShell();
    first.unmount(); // the "reload"
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team')); // the real panel auto-reconnects on mount
    await send(user, 'despues del reload');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: 555, main_league_id: 4242 });
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBe('4242');
  });

  test('disconnecting the team clears the league, in the request and in storage', async () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await user.click(screen.getByText('disconnect-team'));
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull();
    await send(user, 'sin equipo');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: null, main_league_id: null });
    await user.click(screen.getByText('connect-team'));
    await send(user, 'otra vez');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ team_id: 555, main_league_id: null }); // gone for good
  });

  test('a junk stored value is ignored', async () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '{"x":1}');
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'hola');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: 555, main_league_id: null });
  });
});
