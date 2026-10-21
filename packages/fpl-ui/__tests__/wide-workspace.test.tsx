/** @jest-environment jsdom */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import ChatShell from '../components/chat/ChatShell';

jest.mock('@clerk/nextjs', () => ({ useUser: () => ({ user: undefined }) }));
jest.mock('@/lib/dev-tier', () => ({ readDevTier: () => undefined }));
jest.mock('../components/chat/TopBar', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/QuotaIndicator', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/chat/SquadContextPanel', () => ({ __esModule: true, default: ({ onTeamIdChange }: { onTeamIdChange: (id: number) => void }) => <button onClick={() => onTeamIdChange(123)}>Connect test team</button> }));
jest.mock('../components/chat/StarterPrompts', () => ({ __esModule: true, default: () => null }));
jest.mock('../components/intents/FixturesBoard', () => ({ FixturesBoard: ({ onAsk }: { onAsk: (text: string) => void }) => <button onClick={() => onAsk('Arsenal next fixtures')}>Ask about fixture</button> }));
const mockAsk = jest.fn();
jest.mock('@/lib/api', () => ({ ask: (...args: unknown[]) => mockAsk(...args), sessionAsk: jest.fn(), createSession: jest.fn(), clearSession: jest.fn(), FplApiError: class extends Error {} }));
jest.mock('@/lib/id', () => { let id = 0; return { generateId: () => `workspace-${++id}` }; });

let width = 1920;
let listeners: Array<() => void> = [];
beforeEach(() => {
  width = 1920; listeners = []; localStorage.clear();
  window.matchMedia = jest.fn((query: string) => ({
    get matches() { return width >= (query.includes('1440') ? 1440 : 1280); },
    media: query, onchange: null, addEventListener: (_: string, fn: () => void) => listeners.push(fn),
    removeEventListener: (_: string, fn: () => void) => { listeners = listeners.filter(f => f !== fn); },
    addListener: jest.fn(), removeListener: jest.fn(), dispatchEvent: jest.fn(),
  } as unknown as MediaQueryList));
  mockAsk.mockReset().mockImplementation(async ({ question }) => ({ final_text: `Answer: ${question}`, outcome: 'ok', supported: true, llm_used: false, intent: 'player_summary' }));
});
const nav = () => screen.getByLabelText('Workspace navigation');
const center = (name: string) => fireEvent.click(within(nav()).getByRole('button', { name }));

test('Chat/Calendar preserve the same messages, draft and scroll node across tab changes and resizing', async () => {
  const { container } = render(<ChatShell />);
  const input = screen.getByRole('textbox', { name: /pregunta/i });
  fireEvent.change(input, { target: { value: 'Captain options' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  await screen.findByText('Answer: Captain options');
  const list = screen.getByTestId('conversation-scroll');
  list.scrollTop = 137;
  fireEvent.change(input, { target: { value: 'My unfinished question' } });
  center('Calendar');
  expect(container.querySelector('[data-panel="chat"]')).toHaveAttribute('aria-hidden', 'true');
  center('Chat');
  expect(screen.getByTestId('conversation-scroll')).toBe(list);
  expect(list.scrollTop).toBe(137);
  expect(screen.getByRole('textbox', { name: /pregunta/i })).toBe(input);
  expect(input).toHaveValue('My unfinished question');
  expect(screen.getByText('Answer: Captain options')).toBeVisible();
  act(() => { width = 390; listeners.forEach(fn => fn()); });
  act(() => { width = 1920; listeners.forEach(fn => fn()); });
  expect(screen.getByTestId('conversation-scroll')).toBe(list);
  expect(input).toHaveValue('My unfinished question');
  expect(mockAsk).toHaveBeenCalledTimes(1);
});

test('a Calendar question and a complete Commands query open Chat and display their answers', async () => {
  render(<ChatShell />);
  center('Calendar');
  fireEvent.click(screen.getByRole('button', { name: 'Ask about fixture' }));
  await screen.findByText('Answer: Arsenal next fixtures');
  expect(within(nav()).getByRole('button', { name: 'Chat' })).toHaveAttribute('aria-pressed', 'true');
  center('Calendar');
  fireEvent.click(screen.getByRole('button', { name: /Lesionados/ }));
  await screen.findByText('Answer: @lesionados');
  expect(within(nav()).getByRole('button', { name: 'Chat' })).toHaveAttribute('aria-pressed', 'true');
  expect(mockAsk).toHaveBeenCalledTimes(2);
});

test('a command requiring arguments opens Chat and inserts the draft without sending an incomplete query', () => {
  render(<ChatShell />); center('Calendar');
  fireEvent.click(screen.getByRole('button', { name: /Comparar 2 jugadores/ }));
  expect(within(nav()).getByRole('button', { name: 'Chat' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('textbox', { name: /pregunta/i })).toHaveValue('/comparar ');
  expect(mockAsk).not.toHaveBeenCalled();
});

test('breakpoint defaults, saved collapse choices, and disconnected Squad are usable', async () => {
  width = 1280;
  const { container, unmount } = render(<ChatShell />);
  expect(container.querySelector('[data-panel="squad"]')).toHaveAttribute('aria-hidden', 'true');
  expect(container.querySelector('[data-panel="commands"]')).not.toHaveAttribute('aria-hidden');
  act(() => { width = 1440; listeners.forEach(fn => fn()); });
  expect(screen.getByText(/Conecta tu equipo FPL en la pestaña Chat/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Collapse squad' }));
  expect(screen.getByRole('button', { name: 'Show squad' })).toBeVisible();
  unmount();
  render(<ChatShell />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Show squad' })).toBeVisible());
  fireEvent.click(screen.getByRole('button', { name: 'Show squad' }));
  expect(screen.getByText(/Conecta tu equipo FPL en la pestaña Chat/)).toBeVisible();
});

test('selecting a Squad player only selects; Ask AI opens Chat and sends exactly once', async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({
    gw: 8, summary: { gw_points: 61, total_points: 432, bank: 14 },
    players: [{ id: 4, web_name: 'Haaland', team_short: 'MCI', position: 'FWD', price: 150, sel: '62.1', form: '7.0', gw_points: 10, pick_position: 10, is_starter: true, is_captain: false }],
  }) });
  try {
    render(<ChatShell />);
    fireEvent.click(screen.getByRole('button', { name: 'Connect test team' }));
    const player = await screen.findByRole('button', { name: 'Haaland, MCI' });
    center('Calendar');
    fireEvent.click(player);
    expect(player).toHaveAttribute('aria-pressed', 'true');
    expect(within(nav()).getByRole('button', { name: 'Calendar' })).toHaveAttribute('aria-pressed', 'true');
    expect(mockAsk).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Ask AI/ }));
    await screen.findByText(/^Answer:.*Haaland/);
    expect(within(nav()).getByRole('button', { name: 'Chat' })).toHaveAttribute('aria-pressed', 'true');
    expect(mockAsk).toHaveBeenCalledTimes(1);
    expect(mockAsk).toHaveBeenCalledWith(expect.objectContaining({ question: expect.stringContaining('Haaland') }));
  } finally { global.fetch = originalFetch; }
});
