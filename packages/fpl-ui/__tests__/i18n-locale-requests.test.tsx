/**
 * @jest-environment jsdom
 *
 * The language the user is looking at is the language every request asks for.
 * Renders the real ChatShell + TopBar + InputBar inside the real LocaleProvider and checks
 * what reaches the API layer: the locale in the body of /ask, the toggle that is only there
 * when the rollout allows it, and that switching mid-session changes the NEXT request.
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
const sessionAsk = jest.fn();
const createSession = jest.fn();
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
  clearSession: jest.fn(() => Promise.resolve()),
  FplApiError,
}));

jest.mock('../components/chat/SwipePager', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PagerScreen: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
jest.mock('../components/chat/StarterPrompts', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/SquadContextPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/CommandPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/squad/SquadPitch', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: () => null }));

import ChatShell from '../components/chat/ChatShell';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';

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

function renderShell(initialLocale: Locale, canSwitch: boolean) {
  return render(
    <LocaleProvider initialLocale={initialLocale} canSwitch={canSwitch}>
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
  sessionAsk.mockReset().mockResolvedValue(reply);
  createSession.mockReset();
  document.cookie = 'bf_locale=; path=/; max-age=0';
  document.documentElement.lang = 'es';
});

test('Spanish is what a plain render asks for, and there is no toggle', async () => {
  const user = userEvent.setup();
  renderShell('es', false);
  expect(screen.queryByRole('group', { name: 'Idioma' })).toBeNull();
  await send(user, 'hola');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
  expect(ask.mock.calls[0][0]).toMatchObject({ question: 'hola', locale: 'es' });
});

test('an English visitor allowed by the rollout asks for English, in the body and in the page language', async () => {
  const user = userEvent.setup();
  renderShell('en', true);
  expect(document.documentElement.lang).toBe('en');
  await send(user, 'captain pick');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
  expect(ask.mock.calls[0][0]).toMatchObject({ question: 'captain pick', locale: 'en' });
});

test('switching the toggle mid-session changes the NEXT request, and is remembered in the cookie', async () => {
  const user = userEvent.setup();
  renderShell('es', true);
  await send(user, 'primera');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
  expect(ask.mock.calls[0][0]).toMatchObject({ locale: 'es' });

  const group = screen.getByRole('group', { name: 'Idioma' });
  await user.click(group.querySelector('button[aria-pressed="false"]') as HTMLElement);
  expect(document.cookie).toContain('bf_locale=en');
  expect(document.documentElement.lang).toBe('en');
  expect(screen.getByRole('group', { name: 'Language' })).toBeInTheDocument();

  await send(user, 'second');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
  expect(ask.mock.calls[1][0]).toMatchObject({ question: 'second', locale: 'en' });
  // The earlier turn keeps the language it was asked in.
  expect(ask.mock.calls[0][0]).toMatchObject({ locale: 'es' });
});

test('when the rollout does not allow choosing there is nothing to set: no cookie, still Spanish', async () => {
  const user = userEvent.setup();
  renderShell('es', false);
  await send(user, 'hola');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
  expect(document.cookie).not.toContain('bf_locale');
  expect(ask.mock.calls[0][0]).toMatchObject({ locale: 'es' });
});
