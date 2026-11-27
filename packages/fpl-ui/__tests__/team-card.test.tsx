/**
 * @jest-environment jsdom
 *
 * The team card and the club chip. All figures and names here are made up.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import type { AskResponse, TeamCardBody, TeamCardMetric } from '@/lib/types';
import TeamCard from '@/components/intents/TeamCard';
import MessageList, { assistantShareQuestionMap, type Message } from '@/components/chat/MessageList';
import { selectIntentView } from '@/lib/intent-renderer';
import { fetchTeamCard, isLatestTeamCard, teamCardResponse, visibleTeamCards } from '@/lib/team-card';
import ShareCard from '@/components/share/ShareCard';
import { buildShareText } from '@/lib/share';

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
    data_provenance: {
      season: '2000-2001', season_label: '2000-01', live_season: '2000-2001', is_current: true, status: 'current',
      label: 'Datos: temporada de prueba', ingested_at: null, n_matches: null, n_shots: null,
    },
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
  test('points are the hero, with the position in words, and the table is labelled as computed', () => {
    render(<TeamCard data={BODY} />);
    expect(screen.getByTestId('team-card-hero')).toHaveTextContent('7pts');
    expect(screen.getByTestId('team-card-hero')).toHaveTextContent('Puesto 3 de 6');
    expect(screen.getByText('Tabla calculada con los resultados')).toBeInTheDocument();
    expect(screen.getByText('ALD · datos hasta J4')).toBeInTheDocument();
    expect(screen.getByTestId('zonal-provenance')).toHaveTextContent('Datos: temporada de prueba');
  });

  test('every group of numbers says what it is', () => {
    render(<TeamCard data={BODY} />);
    for (const label of ['Jugados', 'G-E-P', 'Dif. de goles', 'Últimos resultados', 'Goles a favor', 'xG a favor',
      'Próximos partidos', 'Jugadores con más puntos']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    const players = within(screen.getByTestId('team-card-players'));
    expect(players.getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Jugador', 'Pos', 'Precio', 'Puntos']);
    expect(players.getByText('£7.0m')).toBeInTheDocument();
    expect(screen.getByTestId('team-card-form')).toHaveTextContent('G 2-0');
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
    const { container } = render(<MessageList messages={[message(response)]} loading={false} onFollowUp={() => {}} />);
    expect(visibleTeamCards(container)).toHaveLength(1);
    expect(screen.queryByRole('region', { name: 'Veredicto' })).not.toBeInTheDocument();
    expect(screen.queryByText('Seguir conversación')).not.toBeInTheDocument();
  });

  const asked: Message = { id: 'u1', role: 'user', text: 'alder town' };

  test('a typed club is shared with its question', () => {
    render(<MessageList messages={[asked, message(response)]} loading={false} />);
    expect(screen.getByRole('button', { name: 'Compartir tarjeta' })).toBeInTheDocument();
    expect(assistantShareQuestionMap([asked, message(response)])).toEqual({ a1: 'alder town' });
  });

  test('a card opened by a tap is shared with no question, never the earlier one', () => {
    const player = { ...message({ ...response, intent: 'player_snapshot', team_card: null } as AskResponse), id: 'p1' };
    expect(assistantShareQuestionMap([asked, player, message(response)])).toEqual({ p1: 'alder town', a1: '' });
    render(<MessageList messages={[message(response)]} loading={false} />);
    expect(screen.getByRole('button', { name: 'Compartir tarjeta' })).toBeInTheDocument();
  });

  test('the share image has header, card and footer, and a question block only when there was one', () => {
    const { rerender } = render(<ShareCard question="" response={response} appUrl="https://example.test" cta="cta" />);
    expect(screen.getByText('Club Bendito Fantasy')).toBeInTheDocument();
    expect(screen.getByTestId('team-card')).toBeInTheDocument();
    expect(screen.getByText('https://example.test')).toBeInTheDocument();
    expect(screen.queryByText('Pregunta')).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Dificultad por' })).not.toBeInTheDocument();
    rerender(<ShareCard question="alder town" response={response} appUrl="https://example.test" cta="cta" />);
    expect(screen.getByText('Pregunta')).toBeInTheDocument();
  });

  test('the share copy shows the side chosen on the card, and is not counted as a card on screen', () => {
    const { container } = render(<MessageList messages={[asked, message(response)]} loading={false} />);
    const onScreen = within(visibleTeamCards(container)[0] as HTMLElement);
    const chosen = () => screen.getByTestId('team-card-axis').textContent;
    const attack = chosen();
    fireEvent.click(within(onScreen.getByRole('group', { name: 'Dificultad por' })).getAllByRole('button')[1]);
    expect(chosen()).not.toBe(attack);
    expect(screen.getAllByTestId('team-card')).toHaveLength(2);
    expect(visibleTeamCards(container)).toHaveLength(1);
  });

  test('the invite text without a question quotes none', () => {
    const text = buildShareText({ question: '', locale: 'es' });
    expect(text.split('\n')[0]).toBe('Una tarjeta de Club Bendito Fantasy');
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
