/**
 * @jest-environment jsdom
 *
 * Card-prose rule: when the model's text only reprinted the ranking card's rows, the backend drops it and the turn
 * arrives with final_text "" next to the card and the table's conclusions (#648). The bubble must then show the
 * card and the conclusions ONCE, with no empty text bubble and no duplicate, on /ask and on /session alike. The two
 * bodies below are the serialized responses of the real backend path (synthetic bootstrap, fake model), debug stripped.
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


const askBody = {
 "final_text": "",
 "outcome": "ok",
 "supported": true,
 "intent": "unsupported",
 "review_passed": true,
 "llm_used": true,
 "comparison": null,
 "captain": null,
 "captain_ranking": null,
 "pool_source": null,
 "pool_size": null,
 "synthesis_turn": true,
 "presentation": null,
 "squad_source": null,
 "squad_excluded": null,
 "sub_responses": null,
 "transfer": null,
 "chip": null,
 "fixture_run": null,
 "differential": null,
 "plan_state": null,
 "pending": null,
 "orch_outcome": "ok",
 "degraded": false,
 "player_form": null,
 "injury_list": null,
 "price_changes": null,
 "team_calendar": null,
 "team_schedule": null,
 "position_fixture_run": null,
 "transfer_suggestion": null,
 "zonal_opportunity": null,
 "fixture_outlook": null,
 "player_snapshot": null,
 "generic_card": {
  "accent": "turquoise",
  "title": "TOP 5 · Puntos",
  "subtitle": null,
  "hero": {
   "value": "0",
   "label": "Puntos",
   "tone": null
  },
  "pills": [],
  "columns": [
   {
    "header": "#",
    "align": "right",
    "kind": "mono"
   },
   {
    "header": "Jugador",
    "align": "left",
    "kind": "text"
   },
   {
    "header": "Equipo",
    "align": "left",
    "kind": "text"
   },
   {
    "header": "Pos",
    "align": "left",
    "kind": "text"
   },
   {
    "header": "Puntos",
    "align": "right",
    "kind": "mono"
   }
  ],
  "rows": [
   [
    "1",
    "Haaland",
    "MCI",
    "FWD",
    "0"
   ],
   [
    "2",
    "Salah",
    "LIV",
    "MID",
    "0"
   ],
   [
    "3",
    "Saka",
    "ARS",
    "MID",
    "0"
   ],
   [
    "4",
    "De Bruyne",
    "MCI",
    "MID",
    "0"
   ],
   [
    "5",
    "Raya",
    "ARS",
    "GKP",
    "0"
   ]
  ],
  "footer": null,
  "involvement_compare": null,
  "position_pitch": null,
  "badge_tones": null
 },
 "suggestions": null,
 "resource_rows": null,
 "table_conclusions": [
  {
   "key": "gap",
   "params": {
    "leaders": [
     "Alder"
    ],
    "metric": "total_points"
   },
   "evidence": {
    "lead_values": [
     76
    ],
    "next_value": 70,
    "next_rank": 2
   }
  }
 ],
 "route_source": null,
 "classifier_confidence": null,
 "route_conflict": false,
 "clarification_asked": false,
 "web_search": null
};
const sessionBody = {
 "session_id": "032af9d6-780c-47e8-9c94-880270562031",
 "final_text": "",
 "outcome": "ok",
 "supported": true,
 "intent": "unsupported",
 "review_passed": true,
 "llm_used": true,
 "rewritten_question": null,
 "comparison": null,
 "captain": null,
 "captain_ranking": null,
 "pool_source": null,
 "pool_size": null,
 "synthesis_turn": true,
 "presentation": null,
 "squad_source": null,
 "squad_excluded": null,
 "sub_responses": null,
 "transfer": null,
 "chip": null,
 "fixture_run": null,
 "differential": null,
 "orch_outcome": "ok",
 "degraded": false,
 "player_form": null,
 "injury_list": null,
 "price_changes": null,
 "team_calendar": null,
 "team_schedule": null,
 "position_fixture_run": null,
 "transfer_suggestion": null,
 "zonal_opportunity": null,
 "fixture_outlook": null,
 "player_snapshot": null,
 "generic_card": {
  "accent": "turquoise",
  "title": "TOP 5 · Puntos",
  "subtitle": null,
  "hero": {
   "value": "0",
   "label": "Puntos",
   "tone": null
  },
  "pills": [],
  "columns": [
   {
    "header": "#",
    "align": "right",
    "kind": "mono"
   },
   {
    "header": "Jugador",
    "align": "left",
    "kind": "text"
   },
   {
    "header": "Equipo",
    "align": "left",
    "kind": "text"
   },
   {
    "header": "Pos",
    "align": "left",
    "kind": "text"
   },
   {
    "header": "Puntos",
    "align": "right",
    "kind": "mono"
   }
  ],
  "rows": [
   [
    "1",
    "Haaland",
    "MCI",
    "FWD",
    "0"
   ],
   [
    "2",
    "Salah",
    "LIV",
    "MID",
    "0"
   ],
   [
    "3",
    "Saka",
    "ARS",
    "MID",
    "0"
   ],
   [
    "4",
    "De Bruyne",
    "MCI",
    "MID",
    "0"
   ],
   [
    "5",
    "Raya",
    "ARS",
    "GKP",
    "0"
   ]
  ],
  "footer": null,
  "involvement_compare": null,
  "position_pitch": null,
  "badge_tones": null
 },
 "suggestions": null,
 "resource_rows": null,
 "table_conclusions": [
  {
   "key": "gap",
   "params": {
    "leaders": [
     "Alder"
    ],
    "metric": "total_points"
   },
   "evidence": {
    "lead_values": [
     76
    ],
    "next_value": 70,
    "next_rank": 2
   }
  }
 ],
 "route_source": null,
 "classifier_confidence": null,
 "route_conflict": false,
 "clarification_asked": false
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

describe('a ranking turn whose prose was dropped (final_text empty, conclusions + card)', () => {
  test.each([['/ask', askBody], ['/session', sessionBody]])('%s: card and conclusions once, no empty bubble', async (_route, body) => {
    ask.mockResolvedValueOnce(body);
    const user = userEvent.setup();
    const { container } = renderShell();
    await send(user, 'mejores defensas por puntos');
    expect(await screen.findAllByTestId('table-conclusions')).toHaveLength(1);
    expect(screen.getByText(/Alder/)).toBeInTheDocument();                       // the conclusion names the leader
    expect(screen.getAllByText(/TOP 5/).length).toBeGreaterThan(0);              // the ranking card is on screen
    // no empty text bubble: every paragraph under the assistant message has text
    const paragraphs = Array.from(container.querySelectorAll('p'));
    expect(paragraphs.every((p) => (p.textContent ?? '').trim().length > 0)).toBe(true);
    // the rows are not printed twice: the card is the only place a player's row appears
    expect(screen.queryAllByText(/^1\.\s/)).toHaveLength(0);
  });

  test('the two routes render the same assistant surface', async () => {
    const html: string[] = [];
    for (const body of [askBody, sessionBody]) {
      ask.mockReset().mockResolvedValueOnce(body);
      const user = userEvent.setup();
      const { container, unmount } = renderShell();
      await send(user, 'mejores defensas por puntos');
      await screen.findAllByTestId('table-conclusions');
      html.push(container.querySelector('[data-testid="conversation-scroll"]')?.innerHTML ?? '');
      unmount();
      localStorage.clear();
    }
    expect(html[0]).toBe(html[1]);
  });
});
