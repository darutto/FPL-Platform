/**
 * @jest-environment jsdom
 *
 * Query answers in the chat: the request a typed message, a tapped pill and "Not this" really send.
 */
import fs from 'node:fs';
import path from 'node:path';

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
}));
jest.mock('@/lib/dev-tier', () => ({ readDevTier: () => undefined }));

const ask = jest.fn();
const sessionAsk = jest.fn();
const createSession = jest.fn();
const clearSession = jest.fn();
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
  clearSession: (...a: unknown[]) => clearSession(...a),
  FplApiError,
}));

jest.mock('../components/chat/SwipePager', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PagerScreen: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
jest.mock('../components/chat/TopBar', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/StarterPrompts', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/SquadContextPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/CommandPanel', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/squad/SquadPitch', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: () => null }));

// The share copy of each answer is a second, static render of the card (query-card.test.tsx covers it).
jest.mock('../components/share/ShareActions', () => ({ __esModule: true, default: () => null }));

import ChatShell from '../components/chat/ChatShell';
import type { AskResponse } from '@/lib/types';

// The backend's own serialized /ask body, with one chip added so there is something to tap.
const BODY: AskResponse = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../fpl-grounded-assistant/tests/fixtures/query_response_bodies.json'),
    'utf8',
  ),
).complete_list_es;

const SPEC = BODY.query!.spec;
const NEXT = { ...SPEC, top_n: 5 };
const queryAnswer: AskResponse = { ...BODY, query: { ...BODY.query!, chips: [{ label: 'Server chip', spec: NEXT }] } };

function getTextbox() {
  return screen.getByRole('textbox', { name: /pregunta/i });
}

async function sendText(user: ReturnType<typeof userEvent.setup>, text: string) {
  const textbox = getTextbox();
  await user.click(textbox);
  await user.type(textbox, text);
  await user.type(textbox, '{Enter}');
}

const sent = (call: number) => ask.mock.calls[call][0] as Record<string, unknown>;

async function openQueryAnswer() {
  const user = userEvent.setup();
  ask.mockResolvedValue(queryAnswer);
  render(<ChatShell />);
  await sendText(user, 'first question');
  await screen.findByTestId('query-card');
  return user;
}

beforeEach(() => {
  ask.mockReset();
  clearSession.mockReset();
  clearSession.mockResolvedValue(undefined);
});

test('the card replaces the text copy of the answer', async () => {
  await openQueryAnswer();
  expect(screen.queryByText(/Muestro:/)).toBeNull();
  expect(sent(0)).not.toHaveProperty('query_context');
  expect(sent(0)).not.toHaveProperty('query_spec');
});

test('a typed follow-up carries the last spec, without "Not this"', async () => {
  const user = await openQueryAnswer();
  await sendText(user, 'second question');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
  expect(sent(1).query_context).toEqual({ spec: SPEC, not_this: false });
});

test('"Not this" focuses the composer, and only the next typed message says so', async () => {
  const user = await openQueryAnswer();
  await user.click(screen.getByRole('button', { name: 'No es esto' }));
  expect(getTextbox()).toHaveFocus();
  expect(ask).toHaveBeenCalledTimes(1);
  await sendText(user, 'a correction');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
  expect(sent(1).query_context).toEqual({ spec: SPEC, not_this: true });
  await waitFor(() => expect(screen.getAllByTestId('query-card')).toHaveLength(2));
  await sendText(user, 'another');
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(3));
  expect(sent(2).query_context).toEqual({ spec: SPEC, not_this: false });
});

test('a tap sends the typed spec verbatim, its label as the bubble, and no context', async () => {
  const user = await openQueryAnswer();
  await user.click(screen.getByRole('button', { name: 'Server chip' }));
  await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
  expect(sent(1)).toMatchObject({ question: 'Server chip', query_spec: NEXT, web_search_requested: false });
  expect(sent(1)).not.toHaveProperty('query_context');
});
