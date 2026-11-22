/**
 * @jest-environment jsdom
 *
 * plan_to_sign chips (move count, other options): titled "Plan", never "which of these players", and a tap
 * sends the chip's question verbatim as a plain turn. Renders the real ChatShell with a mocked API.
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

const planReply = {
  ...reply,
  intent: 'plan_to_sign',
  final_text: 'Para fichar a N.Jackson...',
  suggestions: [
    { label: '1 traspaso', send_text: 'Plan: 1 traspaso', kind: 'plan_option' },
    { label: 'Usar hits (−4 cada uno)', send_text: 'Plan: Usar hits', kind: 'plan_option' },
  ],
};

describe('plan chips', () => {
  test('are titled Plan, not the player-pick question', async () => {
    ask.mockResolvedValueOnce(planReply);
    const user = userEvent.setup();
    renderShell('es');
    await send(user, 'como ficho a jackson');
    expect(await screen.findByRole('button', { name: '1 traspaso' })).toBeInTheDocument();
    expect(screen.getByText('Plan')).toBeInTheDocument();
    expect(screen.queryByText('¿Cuál de estos jugadores buscabas?')).toBeNull();
  });

  test('the same in English', async () => {
    ask.mockResolvedValueOnce(planReply);
    const user = userEvent.setup();
    renderShell('en');
    await send(user, 'how do i get jackson');
    expect(await screen.findByText('Plan')).toBeInTheDocument();
    expect(screen.queryByText('Which of these players did you mean?')).toBeNull();
  });

  test('a tap sends the chip text as a plain question with no player id', async () => {
    ask.mockResolvedValueOnce(planReply);
    const user = userEvent.setup();
    renderShell('es');
    await send(user, 'como ficho a jackson');
    await user.click(await screen.findByRole('button', { name: '1 traspaso' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: 'Plan: 1 traspaso' });
    expect(ask.mock.calls[1][0].selected_player_id).toBeUndefined();
  });
});
