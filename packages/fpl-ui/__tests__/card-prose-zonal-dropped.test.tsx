/**
 * @jest-environment jsdom
 *
 * Card-prose rule on the player zonal card: when the model's text only listed the card's matches again, the turn
 * arrives with final_text "" next to the card, which carries its own verdict. The bubble must show the card once,
 * with no verdict band and no empty text bubble, on /ask and /session alike. The bodies are the backend's own
 * serialized responses (written and checked by fpl-grounded-assistant/tests/test_card_prose_zonal.py).
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
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
  eoPoll: jest.fn(),
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
jest.mock('../components/chat/SquadContextPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/CommandPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/squad/SquadPitch', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: () => null }));

import ChatShell from '../components/chat/ChatShell';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';


import askBody from './fixtures/player-zonal/prose-dropped-ask.json';
import sessionBody from './fixtures/player-zonal/prose-dropped-session.json';

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
  ask.mockReset();
  localStorage.clear();
});

const STRUCTURED = 'Respuesta estructurada';

describe('a player zonal turn whose prose was dropped (final_text empty)', () => {
  test.each([['/ask', askBody], ['/session', sessionBody]])('%s: the card once, no verdict band, no empty bubble', async (_route, body) => {
    expect(body.final_text).toBe('');
    ask.mockResolvedValueOnce(body);
    const user = userEvent.setup();
    const { container } = renderShell();
    await send(user, 'oportunidades zonales de Palmer');
    // The chat answer itself (the share image renders its own copy of the card elsewhere).
    const answer = await screen.findByRole('region', { name: STRUCTURED });
    expect(within(answer).getAllByTestId('player-zonal-card')).toHaveLength(1);
    expect(within(answer).getByTestId('player-zonas-verdict')).toHaveTextContent(body.player_zonal.zonal.verdict);
    expect(screen.queryByRole('region', { name: 'Veredicto' })).not.toBeInTheDocument();
    expect(container.querySelector('.chat-prose')).toBeNull();
    const paragraphs = Array.from(container.querySelectorAll('p'));
    expect(paragraphs.every((p) => (p.textContent ?? '').trim().length > 0)).toBe(true);
    expect(within(answer).getAllByTestId('player-zonas-row')).toHaveLength(body.player_zonal.zonal.fixtures.length);
  });

  test('with prose left over, the same selectors do find it', async () => {
    ask.mockResolvedValueOnce({ ...askBody, final_text: 'La ventana llega al final del tramo.' });
    const user = userEvent.setup();
    const { container } = renderShell();
    await send(user, 'oportunidades zonales de Palmer');
    await screen.findByRole('region', { name: STRUCTURED });
    expect(screen.getByRole('region', { name: 'Veredicto' })).toBeInTheDocument();
    expect(container.querySelector('.chat-prose')).not.toBeNull();
  });
});
