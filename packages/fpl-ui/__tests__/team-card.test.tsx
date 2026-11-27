/**
 * @jest-environment jsdom
 *
 * The team card and the club chip. All figures and names here are made up.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import type { AskResponse, TeamCardBody, TeamCardMetric } from '@/lib/types';
import TeamCard from '@/components/intents/TeamCard';
import MessageList, { type Message } from '@/components/chat/MessageList';
import { selectIntentView } from '@/lib/intent-renderer';
import { fetchTeamCard, isLatestTeamCard, teamCardResponse } from '@/lib/team-card';

// The outlook module is replaced below; pin the bundle too so nothing here can read the weekly one.
jest.mock('@/lib/data/fixture-outlook-2026-27.json', () => jest.requireActual('./fixtures/fixture-outlook-2026-27.pinned.json'));
jest.mock('@/lib/fixture-outlook-real', () => ({
  buildRealSeasonOutlook: () => ({ teams: [] }),
}));

const metric = (total: number, perMatch: number, extra: Partial<TeamCardMetric> = {}): TeamCardMetric => ({
  total, per_match: perMatch, range: null, per_match_range: null, matches: 4, reason: null, missing_gameweeks: [],
  ...extra,
});

const unmeasured: TeamCardMetric = {
  total: null, per_match: null, range: null, per_match_range: null, matches: null,
  reason: 'fetch_failed', missing_gameweeks: [2],
};

const BODY: TeamCardBody = {
  v: 1,
  kind: 'team',
  data_stamp: 'abc',
  card: {
    team: { id: 7, name: 'Alder Town', short_name: 'ALD' },
    table: {
      position: 3, teams: 6, played: 4, won: 2, drawn: 1, lost: 1, gf: 9, ga: 4, gd: 5, points: 7,
      form: [{ gameweek: 4, opponent_short: 'BIR', is_home: true, goals_for: 2, goals_against: 0, result: 'W' }],
    },
    stats: {
      recent_gameweeks: 5,
      season: {
        goals_for: metric(9, 2.25),
        goals_against: metric(4, 1),
        xg_for: unmeasured,
        xg_against: metric(3.5, 0.88, { range: [3.4, 3.6], per_match_range: [0.85, 0.9] }),
      },
      recent: {
        goals_for: metric(8, 2), goals_against: metric(3, 0.75), xg_for: metric(6.1, 1.53),
        xg_against: metric(2.75, 0.69),
      },
    },
    fixtures: {
      next: [{ gameweek: 5, opponent_short: 'CED', is_home: false, difficulty: 2 }],
      blank_gameweeks: [6],
      double_gameweeks: [],
    },
    players: [{ id: 1, web_name: 'Testman', position: 'MID', total_points: 31, price: 7 }],
    last_finished_gameweek: 4,
    data_provenance: { label: 'Datos: temporada de prueba' },
  },
};

const message = (response: AskResponse, text = response.final_text): Message => ({
  id: 'a1', role: 'assistant', text, outcome: 'ok', llmUsed: false, response,
});

const originalFetch = (globalThis as { fetch?: unknown }).fetch;
afterEach(() => {
  (globalThis as { fetch?: unknown }).fetch = originalFetch;
});

describe('TeamCard', () => {
  test('shows the computed table, with its label, and the footer', () => {
    render(<TeamCard data={BODY} />);
    expect(screen.getByText('3/6')).toBeInTheDocument();
    expect(screen.getByText('2-1-1')).toBeInTheDocument();
    expect(screen.getByText('Tabla calculada con los resultados')).toBeInTheDocument();
    expect(screen.getByText('Datos: temporada de prueba · Hasta J4')).toBeInTheDocument();
  });

  test('an unmeasured figure is a dash with its gameweek, and a range stays a range with dot decimals', () => {
    render(<TeamCard data={BODY} />);
    const stats = within(screen.getByTestId('team-card-stats'));
    expect(stats.getByText('Sin datos: J2')).toBeInTheDocument();
    expect(stats.getByText('3.40–3.60')).toBeInTheDocument();
    expect(stats.getByText('0.85–0.90 por partido')).toBeInTheDocument();
  });

  test('one missing section leaves the others', () => {
    render(<TeamCard data={{ ...BODY, card: { ...BODY.card, stats: null } }} />);
    expect(screen.getByText('Goles y xG: no disponible')).toBeInTheDocument();
    expect(screen.getByTestId('team-card-players')).toHaveTextContent('Testman');
  });

  test('fixtures use the player strip, name the blank gameweek, and the axis starts on attack', () => {
    render(<TeamCard data={BODY} />);
    expect(screen.getByTestId('player-fixture-strip')).toBeInTheDocument();
    expect(screen.getByTestId('team-card-blanks')).toHaveTextContent('Sin partido: J6');
    const buttons = within(screen.getByRole('group', { name: 'Dificultad por' })).getAllByRole('button');
    expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['true', 'false']);
    fireEvent.click(buttons[1]);
    expect(buttons[1]).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('the team card in the chat', () => {
  const response = teamCardResponse(BODY);

  test('selects the team card view', () => {
    expect(selectIntentView(response)).toBe('team_card');
  });

  test('has no verdict band and no follow-up button', () => {
    render(<MessageList messages={[message(response)]} loading={false} onFollowUp={() => {}} />);
    expect(screen.getByTestId('team-card')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Veredicto' })).not.toBeInTheDocument();
    expect(screen.queryByText('Seguir conversación')).not.toBeInTheDocument();
  });

  test('a second tap is recognised only while that club card is the latest message', () => {
    expect(isLatestTeamCard(message(response), 7)).toBe(true);
    expect(isLatestTeamCard(message(response), 8)).toBe(false);
    expect(isLatestTeamCard(undefined, 7)).toBe(false);
  });

  const playerAmbiguous = {
    final_text: 'Which player?', outcome: 'ambiguous', supported: true, intent: 'player_snapshot',
    review_passed: true, llm_used: false, team_chip: { team_id: 7, name: 'Alder Town' },
  } as AskResponse;

  test('the chip under a player answer opens the club through the handler', async () => {
    const open = jest.fn(async () => {});
    render(<MessageList messages={[message(playerAmbiguous)]} loading={false} onOpenTeam={open} />);
    fireEvent.click(screen.getByRole('button', { name: 'Ver equipo: Alder Town' }));
    await waitFor(() => expect(open).toHaveBeenCalledWith({ team_id: 7, name: 'Alder Town' }));
  });

  test('a failed chip tap says so on the chip', async () => {
    const open = jest.fn(async () => {
      throw new Error('down');
    });
    render(<MessageList messages={[message(playerAmbiguous)]} loading={false} onOpenTeam={open} />);
    fireEvent.click(screen.getByRole('button', { name: 'Ver equipo: Alder Town' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo abrir. Toca de nuevo.');
  });

  test('fetchTeamCard posts the ids only, to the card proxy', async () => {
    const calls: [string, { body: string }][] = [];
    (globalThis as { fetch?: unknown }).fetch = jest.fn(async (url: string, init: { body: string }) => {
      calls.push([url, init]);
      return { ok: true, json: async () => BODY };
    });
    await expect(fetchTeamCard(7, 'es')).resolves.toBe(BODY);
    expect(calls[0][0]).toBe('/api/fpl-card');
    expect(JSON.parse(calls[0][1].body)).toEqual({ v: 1, kind: 'team', team_id: 7, locale: 'es' });
  });

  test('fetchTeamCard rejects a failed answer', async () => {
    (globalThis as { fetch?: unknown }).fetch = jest.fn(async () => ({ ok: false, status: 429 }));
    await expect(fetchTeamCard(7, 'es')).rejects.toMatchObject({ status: 429 });
  });
});
