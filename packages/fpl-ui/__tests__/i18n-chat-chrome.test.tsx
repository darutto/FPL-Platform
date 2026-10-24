/**
 * @jest-environment jsdom
 *
 * The chat chrome in English: what an English visitor reads around the answers. Spanish is
 * what every other test already pins (their assertions are unchanged); here the same
 * components are rendered under an English LocaleProvider, and a Spanish render is compared
 * for the strings the glossary says must not move.
 */
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
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
  apiErrorText: (err: { message: string }) => err.message,
  FplApiError,
}));

jest.mock('../components/chat/SwipePager', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PagerScreen: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/squad/SquadPitch', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: () => null }));

import ChatShell from '../components/chat/ChatShell';
import CommandPanel from '../components/chat/CommandPanel';
import StarterPrompts, { buildDynamicPrompts, staticPrompts } from '../components/chat/StarterPrompts';
import SquadContextPanel from '../components/chat/SquadContextPanel';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';

const reply = (text: string, extra: object = {}) => ({
  final_text: text,
  outcome: 'ok',
  supported: true,
  intent: 'player_form',
  review_passed: true,
  llm_used: false,
  orch_outcome: null,
  degraded: false,
  suggestions: null,
  ...extra,
});

const inLocale = (locale: Locale, ui: React.ReactElement) =>
  render(<LocaleProvider initialLocale={locale} canSwitch={false}>{ui}</LocaleProvider>);

beforeEach(() => {
  ask.mockReset().mockResolvedValue(reply('ok'));
  sessionAsk.mockReset().mockResolvedValue(reply('ok'));
  createSession.mockReset().mockResolvedValue({ session_id: 's1', created_at: 0, expires_after_seconds: 60 });
  global.fetch = jest.fn(async () => ({ ok: false, json: async () => ({}) }) as Response) as unknown as typeof fetch;
});

describe('the chat screen', () => {
  test('English: empty state, input, send button and the follow-up wording', async () => {
    const user = userEvent.setup();
    inLocale('en', <ChatShell />);
    expect(screen.getByText('Ask a question about your Fantasy Premier League team.')).toBeInTheDocument();
    const box = screen.getByRole('textbox', { name: 'Ask the FPL assistant' });
    expect(box).toHaveAttribute('placeholder', 'Ask a question or use /captain, /compare…');
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();

    await user.type(box, 'form check{Enter}');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('button', { name: 'Follow up →' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Follow up →' }));
    expect(screen.getByRole('button', { name: 'Follow-up on ✓' })).toBeInTheDocument();
    expect(screen.getByText('Replying to this · tap to cancel')).toBeInTheDocument();
  });

  test('Spanish keeps every string it had', async () => {
    const user = userEvent.setup();
    inLocale('es', <ChatShell />);
    expect(screen.getByText('Haz una pregunta sobre tu equipo de Fantasy Premier League.')).toBeInTheDocument();
    const box = screen.getByRole('textbox', { name: 'Pregunta al asistente FPL' });
    expect(box).toHaveAttribute('placeholder', 'Escribe tu pregunta o usa /capitan, /comparar…');
    await user.type(box, 'forma{Enter}');
    expect(await screen.findByRole('button', { name: 'Seguir conversación →' })).toBeInTheDocument();
  });

  test('an unexpected failure is worded in the language showing', async () => {
    const user = userEvent.setup();
    ask.mockReset().mockRejectedValue(new Error('boom'));
    inLocale('en', <ChatShell />);
    await user.type(screen.getByRole('textbox', { name: 'Ask the FPL assistant' }), 'anything{Enter}');
    expect(await screen.findByText('Unexpected error. Please try again.')).toBeInTheDocument();
  });

  test('the compare wizard composes the English command in English, the Spanish one in Spanish', async () => {
    const user = userEvent.setup();
    const clarification = reply('?', {
      outcome: 'needs_clarification',
      intent: 'compare_players',
      suggestions: [{ label: 'Palmer', send_text: 'Palmer' }, { label: 'Saka', send_text: 'Saka' }],
    });
    ask.mockReset().mockResolvedValueOnce(clarification).mockResolvedValue(reply('compared'));
    const { unmount } = inLocale('en', <ChatShell />);
    await user.type(screen.getByRole('textbox', { name: 'Ask the FPL assistant' }), '/compare{Enter}{Enter}');
    expect(await screen.findByText('Who is the first player?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Palmer' }));
    expect(await screen.findByText('Who are we comparing him with?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Saka' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/compare Palmer vs Saka', locale: 'en' });
    unmount();

    ask.mockReset().mockResolvedValueOnce(clarification).mockResolvedValue(reply('comparado'));
    inLocale('es', <ChatShell />);
    await user.type(screen.getByRole('textbox', { name: 'Pregunta al asistente FPL' }), '/comparar{Enter}{Enter}');
    expect(await screen.findByText('¿Cuál es el primer jugador?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Palmer' }));
    await user.click(await screen.findByRole('button', { name: 'Saka' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0]).toMatchObject({ question: '/comparar Palmer vs Saka', locale: 'es' });
    // Two full chat renders and a dozen typed keys: about 2 s alone, over the 5 s default inside the whole suite.
  }, 30_000);
});

describe('the command panel', () => {
  test('English headings, English command names inserted, English @views sent', async () => {
    const user = userEvent.setup();
    const onInsert = jest.fn();
    const onSend = jest.fn();
    inLocale('en', <CommandPanel onInsert={onInsert} onSend={onSend} />);
    expect(screen.getByText('Quick commands')).toBeInTheDocument();
    expect(screen.getByText('Quick views')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();

    // The labels follow the glossary: @form is form, @popular is ownership (Most selected), not transfers in.
    expect(screen.getByRole('button', { name: /In form/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Most selected/ })).toBeInTheDocument();
    expect(screen.queryByText(/brought in/i)).toBeNull();
    await user.click(screen.getByRole('button', { name: /Injuries/ }));
    expect(onSend).toHaveBeenCalledWith('@injuries');
    await user.click(screen.getByRole('button', { name: /Who gets the armband\?/ }));
    expect(onInsert).toHaveBeenCalledWith('/captain ', 'e.g. Haaland');
    await user.click(screen.getByRole('button', { name: /Use a chip\?/ }));
    expect(onInsert).toHaveBeenCalledWith('/chips ', 'e.g. Triple Captain');
  });

  test('Spanish is what the panel always showed', async () => {
    const user = userEvent.setup();
    const onInsert = jest.fn();
    const onSend = jest.fn();
    inLocale('es', <CommandPanel onInsert={onInsert} onSend={onSend} />);
    expect(screen.getByText('Comandos rápidos')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Lesionados/ }));
    expect(onSend).toHaveBeenCalledWith('@lesionados');
    await user.click(screen.getByRole('button', { name: /¿A quién le doy la cinta\?/ }));
    expect(onInsert).toHaveBeenCalledWith('/capitan ', 'p.ej. Haaland');
  });
});

describe('starter prompts', () => {
  test('Spanish starters are exactly the ones the app always had, with live names woven in', () => {
    expect(staticPrompts('es')).toEqual([
      '¿A quién debería dar el brazalete?',
      '/comparar Haaland vs Bruno Fernandes',
      '¿Debería usar el triple capitán?',
      '/diferenciales menos del 10%',
      '/transferencia Cole Palmer por Saka',
      '/calendarios Haaland',
    ]);
    expect(buildDynamicPrompts(['Palmer', 'Saka'], ['Gordon'])).toEqual([
      '¿A quién debería dar el brazalete?',
      '/comparar Palmer vs Saka',
      '¿Debería usar el triple capitán?',
      '/diferenciales menos del 10%',
      '/transferencia Gordon por Palmer',
      '/calendarios Palmer',
    ]);
  });

  test('English starters use the English commands and the chip name unchanged', () => {
    expect(buildDynamicPrompts(['Palmer', 'Saka'], ['Gordon'], 'en')).toEqual([
      'Who should I captain?',
      '/compare Palmer vs Saka',
      'Should I use the Triple Captain?',
      '/differentials under 10%',
      '/transfer Gordon for Palmer',
      '/fixtures Palmer',
    ]);
  });

  test('the rendered chips follow the locale', () => {
    inLocale('en', <StarterPrompts onSelect={() => {}} />);
    expect(screen.getByRole('button', { name: 'Should I use the Triple Captain?' })).toBeInTheDocument();
  });
});

describe('squad connection', () => {
  test('English labels and error wording', async () => {
    const user = userEvent.setup();
    inLocale('en', <SquadContextPanel onContextChange={() => {}} />);
    const input = screen.getByPlaceholderText('FPL team ID');
    await user.type(input, 'abc');
    await user.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText('Invalid team ID — it must be a positive number.')).toBeInTheDocument();
  });

  test('Spanish error wording is unchanged', async () => {
    const user = userEvent.setup();
    inLocale('es', <SquadContextPanel onContextChange={() => {}} />);
    await user.type(screen.getByPlaceholderText('ID de equipo FPL'), 'abc');
    await user.click(screen.getByRole('button', { name: 'Conectar' }));
    expect(await screen.findByText('ID de equipo no válido — debe ser un número positivo.')).toBeInTheDocument();
    expect(within(document.body).queryByText('Invalid team ID')).toBeNull();
  });
});
