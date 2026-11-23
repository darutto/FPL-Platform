/**
 * @jest-environment jsdom
 *
 * EO warm-up: once a team (and main league) is known the chat asks the backend to start the EO jobs, debounced so
 * team + the league restored from storage make ONE call; a league change calls again; no team, no call; failures
 * are swallowed. Renders the real ChatShell with a mocked API and fake timers.
 */
import React from 'react';
import { act, render, screen } from '@testing-library/react';
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
const eoWarm = jest.fn();
class FplApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
jest.mock('@/lib/api', () => ({
  ask: (...a: unknown[]) => ask(...a),
  eoWarm: (...a: unknown[]) => eoWarm(...a),
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

function renderShell() {
  return render(
    <LocaleProvider initialLocale="es" canSwitch={false}>
      <ChatShell />
    </LocaleProvider>,
  );
}

const tick = (ms: number) =>
  act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });

beforeEach(() => {
  jest.useFakeTimers();
  eoWarm.mockReset().mockResolvedValue(undefined);
  localStorage.clear();
  document.cookie = 'bf_locale=; path=/; max-age=0';
});
afterEach(() => {
  jest.useRealTimers();
});

describe('EO warm-up', () => {
  test('no team connected: no call', async () => {
    renderShell();
    await tick(5000);
    expect(eoWarm).not.toHaveBeenCalled();
  });

  test('connecting a team calls once, after the debounce, without a league when none is stored', async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await tick(1000);
    expect(eoWarm).not.toHaveBeenCalled();
    await tick(600);
    expect(eoWarm).toHaveBeenCalledTimes(1);
    expect(eoWarm).toHaveBeenLastCalledWith({ team_id: 555, league_id: null });
  });

  test('a stored main league goes in the same single call', async () => {
    localStorage.setItem(MAIN_LEAGUE_LS_KEY, '77');
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await tick(2000);
    expect(eoWarm).toHaveBeenCalledTimes(1);
    expect(eoWarm).toHaveBeenLastCalledWith({ team_id: 555, league_id: 77 });
  });

  test('disconnecting before the debounce ends cancels the call', async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await user.click(screen.getByText('disconnect-team'));
    await tick(5000);
    expect(eoWarm).not.toHaveBeenCalled();
  });

  test('a failing warm-up is swallowed', async () => {
    eoWarm.mockRejectedValue(new Error('429'));
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderShell();
    await user.click(screen.getByText('connect-team'));
    await tick(2000);
    expect(eoWarm).toHaveBeenCalledTimes(1);
    expect(screen.getByText('connect-team')).toBeInTheDocument(); // the chat is still up
  });
});
