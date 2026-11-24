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
  default: ({ onTeamIdChange }: { onTeamIdChange?: (id: number | null, name: string | null) => void }) => {
    // Like the real panel with an invalid stored id: it reports "no team" synchronously on mount.
    React.useEffect(() => {
      if (localStorage.getItem('__panel_null_on_mount')) onTeamIdChange?.(null, null);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return (
    <div>
      <button onClick={() => onTeamIdChange?.(555, 'Synthetic FC')}>connect-team</button>
      <button onClick={() => onTeamIdChange?.(556, 'Other FC')}>connect-team-b</button>
      <button onClick={() => onTeamIdChange?.(null, null)}>disconnect-team</button>
    </div>
    );
  },
}));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/CommandPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/squad/SquadPitch', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: () => null }));

import ChatShell from '../components/chat/ChatShell';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import {
  MAIN_LEAGUE_LS_KEY,
  MAX_STORED_TEAMS,
  mainLeagueKey,
  migrateLegacyMainLeague,
  parseLeagueId,
  readMainLeagueFor,
  writeMainLeagueFor,
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

  test('write then read round-trips per team, and null (or junk) clears', () => {
    writeMainLeagueFor(555, 77);
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('77');
    expect(readMainLeagueFor(555)).toBe(77);
    expect(readMainLeagueFor(556)).toBeNull();
    writeMainLeagueFor(555, null);
    expect(localStorage.getItem(mainLeagueKey(555))).toBeNull();
    localStorage.setItem(mainLeagueKey(555), 'not-a-number');
    expect(readMainLeagueFor(555)).toBeNull();
    expect(readMainLeagueFor(null)).toBeNull();
  });

  test('only the last MAX_STORED_TEAMS teams are kept', () => {
    for (let t = 1; t <= MAX_STORED_TEAMS + 2; t++) writeMainLeagueFor(t, 1000 + t);
    expect(readMainLeagueFor(1)).toBeNull();
    expect(readMainLeagueFor(2)).toBeNull();
    expect(localStorage.getItem(mainLeagueKey(1))).toBeNull(); // evicted for real, not just hidden
    expect(readMainLeagueFor(3)).toBe(1003);
    expect(readMainLeagueFor(MAX_STORED_TEAMS + 2)).toBe(1000 + MAX_STORED_TEAMS + 2);
  });

  test('migration: the old value moves to the stored team only, then the old key is gone', () => {
    localStorage.setItem('fpl_team_id', '555');
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    migrateLegacyMainLeague();
    expect(readMainLeagueFor(555)).toBe(4242);
    expect(readMainLeagueFor(556)).toBeNull();
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull();
  });

  test('migration: no valid stored team drops the old value; an existing keyed value wins', () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    migrateLegacyMainLeague();
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull();
    expect(readMainLeagueFor(555)).toBeNull();
    localStorage.setItem('fpl_team_id', 'junk');
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    migrateLegacyMainLeague();
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull();
    localStorage.setItem('fpl_team_id', '555');
    writeMainLeagueFor(555, 9);
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    migrateLegacyMainLeague();
    expect(readMainLeagueFor(555)).toBe(9);
  });

  test('unavailable storage never throws', () => {
    const boom = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const boomSet = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readMainLeagueFor(555)).toBeNull();
    expect(() => writeMainLeagueFor(555, 5)).not.toThrow();
    expect(() => migrateLegacyMainLeague()).not.toThrow();
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
    localStorage.setItem(mainLeagueKey(555), '4242');
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
    localStorage.setItem(mainLeagueKey(555), '4242');
    const user = userEvent.setup();
    renderShell();
    await send(user, 'hola');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: null, main_league_id: null });
  });

  test('it survives a reload: a fresh mount reads it back and sends it once the team reconnects', async () => {
    localStorage.setItem(mainLeagueKey(555), '4242');
    const first = renderShell();
    first.unmount(); // the "reload"
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team')); // the real panel auto-reconnects on mount
    await send(user, 'despues del reload');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: 555, main_league_id: 4242 });
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('4242');
  });

  async function lastAsk(user: ReturnType<typeof userEvent.setup>, text: string) {
    const before = ask.mock.calls.length;
    await send(user, text);
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(before + 1));
    return ask.mock.calls[before][0];
  }

  test('pick -> refresh: the stored team and its league ride the first question, before the panel reconnects', async () => {
    localStorage.setItem('fpl_team_id', '555');
    localStorage.setItem(mainLeagueKey(555), '4242');
    const user = userEvent.setup();
    renderShell(); // the mocked panel never reports a team: this is a refresh with a slow or failing FPL fetch
    expect(await lastAsk(user, 'tras refresh')).toMatchObject({ team_id: 555, main_league_id: 4242 });
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('4242');
  });

  test('pick -> disconnect -> reconnect the same team: the league is back', async () => {
    localStorage.setItem(mainLeagueKey(555), '4242');
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await user.click(screen.getByText('disconnect-team'));
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('4242'); // disconnect empties memory only
    expect(await lastAsk(user, 'sin equipo')).toMatchObject({ team_id: null, main_league_id: null });
    await user.click(screen.getByText('connect-team'));
    expect(await lastAsk(user, 'otra vez')).toMatchObject({ team_id: 555, main_league_id: 4242 });
  });

  test('pick -> connect another team: that team has none; A -> B -> A finds A again; never a mixed pair', async () => {
    localStorage.setItem(mainLeagueKey(555), '4242');
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team'));
    expect(await lastAsk(user, 'en A')).toMatchObject({ team_id: 555, main_league_id: 4242 });
    await user.click(screen.getByText('connect-team-b')); // switch without a disconnect in between
    expect(await lastAsk(user, 'en B')).toMatchObject({ team_id: 556, main_league_id: null });
    await user.click(screen.getByText('connect-team'));
    expect(await lastAsk(user, 'de vuelta en A')).toMatchObject({ team_id: 555, main_league_id: 4242 });
    for (const [body] of ask.mock.calls) {
      expect(body.team_id === 556 ? body.main_league_id : 'n/a').not.toBe(4242);
    }
    expect(localStorage.getItem(mainLeagueKey(556))).toBeNull();
  });

  test('the old unkeyed value is migrated once to the stored team, then the old key is gone', async () => {
    localStorage.setItem('fpl_team_id', '555');
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '4242');
    const user = userEvent.setup();
    renderShell();
    expect(await lastAsk(user, 'migrada')).toMatchObject({ team_id: 555, main_league_id: 4242 });
    expect(localStorage.getItem(MAIN_LEAGUE_LS_KEY)).toBeNull();
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('4242');
  });

  test('a corrupt stored team id (the panel reports no team on mount) erases no league', async () => {
    localStorage.setItem('fpl_team_id', 'junk');
    localStorage.setItem('__panel_null_on_mount', '1');
    localStorage.setItem(mainLeagueKey(555), '4242');
    localStorage.setItem(mainLeagueKey(556), '77');
    const user = userEvent.setup();
    renderShell();
    expect(localStorage.getItem(mainLeagueKey(555))).toBe('4242');
    expect(localStorage.getItem(mainLeagueKey(556))).toBe('77');
    await user.click(screen.getByText('connect-team'));
    expect(await lastAsk(user, 'hola')).toMatchObject({ team_id: 555, main_league_id: 4242 });
  });

  test('a junk stored value is ignored', async () => {
    localStorage.setItem(mainLeagueKey(555), '{"x":1}');
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await send(user, 'hola');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatchObject({ team_id: 555, main_league_id: null });
  });
});
