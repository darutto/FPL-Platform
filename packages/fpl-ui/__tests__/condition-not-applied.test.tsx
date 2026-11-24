/**
 * @jest-environment jsdom
 *
 * Brief 0a: the season ranking refused a conditioned question ("puntos en las últimas 5 jornadas").
 * The backend answers outcome "condition_not_applied": supported false, review_passed false, no card, the
 * code-written line as final_text. The bubble must show that text and nothing else (no table, no empty card),
 * and the next turn's chips must behave as usual. The body below is the serialized /ask response of the real
 * backend path (synthetic bootstrap, fake model), debug stripped.
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

const LINE =
  'No puedo aplicar las últimas jornadas a este ranking: solo cubre la temporada completa. ' +
  'Puedes pedir el ranking de toda la temporada.';

/** Backend JSON for the refused ranking (every key the route serializes). */
const refused = {
  final_text: LINE, outcome: 'condition_not_applied', supported: false, intent: 'unsupported',
  review_passed: false, llm_used: false, comparison: null, captain: null, captain_ranking: null,
  pool_source: null, pool_size: null, synthesis_turn: false, presentation: null, squad_source: null,
  squad_excluded: null, sub_responses: null, transfer: null, chip: null, fixture_run: null,
  differential: null, plan_state: null, pending: null, orch_outcome: null, degraded: false,
  player_form: null, injury_list: null, price_changes: null, team_calendar: null, team_schedule: null,
  position_fixture_run: null, transfer_suggestion: null, zonal_opportunity: null, fixture_outlook: null,
  player_snapshot: null, generic_card: null, suggestions: null, resource_rows: null,
  table_conclusions: null, route_source: null, classifier_confidence: null, route_conflict: false,
  clarification_asked: false, web_search: null,
};
const nextReply = {
  ...refused, final_text: 'Aquí tienes.', outcome: 'ok', supported: true, review_passed: true, llm_used: true,
  synthesis_turn: true,
  suggestions: [{ label: 'Friends', send_text: 'EO en Friends', kind: 'league_pick', league_id: 42 }],
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
  ask.mockReset();
  localStorage.clear();
});

describe('a refused season ranking (outcome condition_not_applied)', () => {
  test('shows the honest line as plain text: no card, no table, no empty list', async () => {
    ask.mockResolvedValueOnce(refused);
    const user = userEvent.setup();
    renderShell();
    await send(user, 'puntos en las últimas 5 jornadas');
    expect(await screen.findByText(LINE)).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('list')).toBeNull();
    expect(screen.queryByTestId('eo-pending')).toBeNull();
    expect(screen.queryByTestId('compare-wizard')).toBeNull();
    expect(screen.queryByTestId('player-pick-wizard')).toBeNull();
  });

  test('the next turn renders as usual: its chips are armed, nothing from the refused turn lingers', async () => {
    ask.mockResolvedValueOnce(refused).mockResolvedValueOnce(nextReply);
    const user = userEvent.setup();
    renderShell();
    await send(user, 'puntos en las últimas 5 jornadas');
    await screen.findByText(LINE);
    await send(user, 'ranking de puntos de la temporada');
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('button', { name: 'Friends' })).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
