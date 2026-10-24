/**
 * @jest-environment jsdom
 *
 * S4c: the zones card, the player's «Zonas» section and the squad pitch, in both languages.
 *
 *   - "Spanish" tests snapshot the shape of what is on screen. Those snapshots were recorded against the code as it
 *     was BEFORE the dictionary (origin/main), so a pass means the Spanish screen did not change.
 *   - "English" tests assert that no Spanish UI word is left (text, titles, aria-labels), name the English wording,
 *     and check the question the squad pitch hands to the chat.
 *
 * Text that arrives inside the payload (the zones verdict and pill, the season stamp, a club note, the Zonas
 * verdict) is written by the backend and is its to localise (S5); the English checks set it aside.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import DefensiveZonesCard from '../components/intents/DefensiveZonesCard';
import PlayerCard from '../components/intents/PlayerCard';
import SquadPitch from '../components/squad/SquadPitch';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import type { Locale } from '../lib/i18n/locale';
import type { DefensiveZonesMeta, PlayerZonalOutlookMeta } from '../lib/types';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import { onScreen, shape, SPANISH_UI_WORDS } from './support/screen-text';

jest.setTimeout(30_000);

const inLocale = (locale: Locale, ui: React.ReactElement) => (
  <LocaleProvider initialLocale={locale} canSwitch={false}>
    {ui}
  </LocaleProvider>
);

// ---------------------------------------------------------------------------------------------------------------
// The zones card
// ---------------------------------------------------------------------------------------------------------------

const PAYLOAD_TEXT = [
  'Ataca la frontal del área',
  'Ataca a Tottenham por el centro en la frontal del área — concede un +44% sobre un equipo medio ahí.',
  '⚠ Datos de 2026-27, sólo 5 jornadas de liga — muestra corta para una lectura de liga',
  'antes en BUR',
];

const zonesCard: DefensiveZonesMeta = {
  opponent: 'Tottenham',
  weakness_label: 'Ataca la frontal del área',
  weakness_strength: 'marginal',
  verdict: 'Ataca a Tottenham por el centro en la frontal del área — concede un +44% sobre un equipo medio ahí.',
  zones: [
    { lateral: 'left', pct_over_avg: 30.8, opportunity_level: 'opp' },
    { lateral: 'central', pct_over_avg: 0.2, opportunity_level: 'cool' },
    { lateral: 'right', pct_over_avg: 12, opportunity_level: 'warm' },
  ],
  frontal_zones: [
    { lateral: 'left', pct_over_avg: 3, opportunity_level: 'warm' },
    { lateral: 'central', pct_over_avg: 44, opportunity_level: 'opp' },
    { lateral: 'right', pct_over_avg: -2, opportunity_level: 'cool' },
  ],
  exploiters: [
    { rank: 1, web_name: 'Right Poacher', team_short: 'BUR', position: 'FWD', zone: 'in-box / right', fit_score: 10,
      gameweek: 5, is_home: false, zone_share: 0.898, zone_shots: 8, origin: 'open_play', sample: 'ok' },
    { rank: 2, web_name: 'Anthony', team_short: 'BRE', position: 'MID', zone: 'edge-of-box / central', fit_score: 9,
      gameweek: 5, is_home: false, zone_share: 0.534, zone_shots: 1, origin: 'set_piece', sample: 'thin',
      club_note: 'antes en BUR' },
    { rank: 3, web_name: 'Heavy Hitter', team_short: 'AVL', position: 'GKP', zone: 'in-box / left', fit_score: 4,
      gameweek: 6, is_home: true, zone_share: 0.4, zone_shots: 3, origin: 'mixed', sample: 'ok' },
  ],
  team_filter: {
    requested: null,
    matched: 'Burnley, Aston Villa',
    source: 'fixtures',
    requested_teams: [],
    matched_teams: ['Burnley', 'Aston Villa'],
    unmatched_teams: [],
    fixture_window: { from_gw: 5, to_gw: 6, horizon: 2 },
    fixtures: [
      { gameweek: 5, team: 'Burnley', is_home: false },
      { gameweek: 6, team: 'Aston Villa', is_home: true },
    ],
    scheduled_opponents: ['Burnley', 'Aston Villa'],
  },
  data_provenance: {
    season: '2026-2027', season_label: '2026-27', live_season: '2026-2027', is_current: true, status: 'thin',
    label: '⚠ Datos de 2026-27, sólo 5 jornadas de liga — muestra corta para una lectura de liga',
    ingested_at: '2026-10-05T07:12:42Z', n_matches: 50, n_shots: 1398,
  },
  penalty_xga_per_game: 0.1402,
  ai_active: true,
};

const fromPayload = (s: string) => PAYLOAD_TEXT.some((p) => p.includes(s) || s.includes(p));

describe('the zones card', () => {
  test('Spanish: the card is what it was before the dictionary', () => {
    const { container } = render(inLocale('es', <DefensiveZonesCard data={zonesCard} />));
    expect(shape(container)).toMatchSnapshot();
  });

  test('Spanish: without a frontal band, a clear read and a league-wide table', () => {
    const { container } = render(
      inLocale('es', <DefensiveZonesCard data={{ ...zonesCard, frontal_zones: undefined, weakness_strength: 'clear', team_filter: null, exploiters: [{ ...zonesCard.exploiters[0], gameweek: null }] }} />),
    );
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: nothing of the interface is left in Spanish', () => {
    const { container } = render(inLocale('en', <DefensiveZonesCard data={zonesCard} />));
    const strings = onScreen(container);
    expect(strings.filter((s) => SPANISH_UI_WORDS.test(s) && !fromPayload(s))).toEqual([]);
    for (const expected of [
      'Where to attack', 'The greener, the bigger your edge.', 'Inside the box', 'Edge of the box',
      'Left', 'Centre', 'Right', 'your best zone', 'slight edge', 'no edge', '≈ average',
      'expected goals above an average league side', 'Player', 'Zone', 'Fit',
      'Penalties (excluded):', 'AI on', 'small sample',
    ]) {
      expect(strings.some((s) => s.includes(expected))).toBe(true);
    }
    expect(strings.some((s) => s.startsWith('Who takes advantage'))).toBe(true);
    expect(strings).toContain("· Tottenham's opponents up to GW6");
    expect(strings).toContain('GW5 · BUR visit Tottenham');
    expect(strings).toContain('GW6 · AVL host Tottenham');
    expect(strings.some((s) => /marginal reading/.test(s))).toBe(true);
    expect(strings.some((s) => /^0\.140 xGA\/match$/.test(s))).toBe(true);
    expect(strings.some((s) => /^90% of their xG here · 8 shots · open play$/.test(s))).toBe(true);
    expect(strings.some((s) => /^53% of their xG here · 1 shot · set piece$/.test(s))).toBe(true);
    expect(strings.some((s) => /^40% of their xG here · 3 shots · open play \+ set piece$/.test(s))).toBe(true);
    // positions and zone pills in English
    expect(strings).toContain('BRE (antes en BUR) · MID');
    expect(strings).toContain('AVL · GKP');
    expect(strings).toContain('Edge centre');
    expect(strings.some((s) => s.startsWith('[aria-label] Box Left: +31%') && s.includes('Edge Centre: +44%'))).toBe(true);
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: "Where to attack" stays positive, no weakness wording', () => {
    const { container } = render(inLocale('en', <DefensiveZonesCard data={zonesCard} />));
    const text = onScreen(container).filter((s) => !fromPayload(s)).join(' ');
    expect(text).not.toMatch(/weak|vulnerab|struggl|poor|bad|worst/i);
  });
});

// ---------------------------------------------------------------------------------------------------------------
// The player's Zonas section
// ---------------------------------------------------------------------------------------------------------------

const zonal: PlayerZonalOutlookMeta = {
  zones: [
    { zone: 'in-box / central', share: 0.5923 },
    { zone: 'edge-of-box / right', share: 0.2611 },
  ],
  gw_from: 6,
  gw_to: 8,
  fixtures: [
    { gameweek: 6, fixture_id: 53, opponent: 'Bournemouth', opponent_short: 'BOU', is_home: true, status: 'neutral', matches: [] },
    {
      gameweek: 7, fixture_id: 64, opponent: 'Everton', opponent_short: 'EVE', is_home: false, status: 'favorable',
      matches: [{ zone: 'in-box / central', delta_vs_avg: 0.0477, player_share: 0.5923 }],
    },
    { gameweek: 8, fixture_id: 73, opponent: 'Ipswich', opponent_short: 'IPS', is_home: true, status: 'no_data', matches: [] },
  ],
  verdict_kind: 'favorable',
  verdict: 'Palmer genera su xG justo en zonas donde el rival concede por encima de la media — cruce favorable en J7 (Everton).',
  data_provenance: zonesCard.data_provenance ?? null,
};

const playerWithZonal = () => ({ ...playerSnapshotOkResponse.player_snapshot!, zonal });
const ZONAS_PAYLOAD = [zonal.verdict, zonesCard.data_provenance!.label];

describe("the player's Zonas section", () => {
  const section = (locale: Locale) => {
    const { container } = render(inLocale(locale, <PlayerCard data={playerWithZonal()} />));
    return { container, zonas: within(screen.getByTestId('player-zonas')) };
  };

  test('Spanish: the section is what it was', () => {
    section('es');
    expect(shape(screen.getByTestId('player-zonas'))).toMatchSnapshot();
  });

  test('English: the section reads in English', () => {
    section('en');
    const strings = onScreen(screen.getByTestId('player-zonas'));
    expect(strings.filter((s) => SPANISH_UI_WORDS.test(s) && !ZONAS_PAYLOAD.some((p) => p.includes(s) || s.includes(p)))).toEqual([]);
    for (const expected of [
      'Zones', 'Fixtures in the next 3 gameweeks · GW6–GW8', 'Box centre · 59% of their non-penalty xG',
      'Edge right · 26% of their non-penalty xG', 'Turquoise: matches the zone with an edge against a favourable opponent.',
      'Favourable matchup · Box centre', 'No data on the opponent', 'No standout matchup',
    ]) {
      expect(strings.some((s) => s.includes(expected))).toBe(true);
    }
    expect(strings).toContain('(H)');
    expect(strings).toContain('(A)');
    expect(strings).toContain('GW7');
    expect(strings).toContain('[aria-label] Box centre: 59% of their xG (matches a favourable matchup) · Edge right: 26% of their xG');
    expect(shape(screen.getByTestId('player-zonas'))).toMatchSnapshot();
  });
});

// ---------------------------------------------------------------------------------------------------------------
// The squad pitch
// ---------------------------------------------------------------------------------------------------------------

const squad = {
  gw: 8,
  summary: { gw_points: 61, total_points: 432, bank: 14 },
  players: [
    { id: 1, web_name: 'Pickford', team_short: 'EVE', position: 'GK', price: 55, sel: '18.0', form: '4.5', gw_points: 6, pick_position: 1, is_starter: true, is_captain: false },
    { id: 2, web_name: 'Gabriel', team_short: 'ARS', position: 'DEF', price: 60, sel: '22.0', form: '6.2', gw_points: 8, pick_position: 2, is_starter: true, is_captain: false },
    { id: 3, web_name: 'Cole Palmer', team_short: 'CHE', position: 'MID', price: 105, sel: '45.3', form: '8.4', gw_points: 12, pick_position: 6, is_starter: true, is_captain: true },
    { id: 4, web_name: 'Haaland', team_short: 'MCI', position: 'FWD', price: 150, sel: '62.1', form: '7.0', gw_points: 10, pick_position: 10, is_starter: true, is_captain: false },
    { id: 5, web_name: 'Calvert-Lewin', team_short: 'LEE', position: 'FWD', price: 55, sel: '2.1', form: '3.0', gw_points: 2, pick_position: 15, is_starter: false, is_captain: false },
  ],
};

const originalFetch = global.fetch;
afterEach(() => {
  global.fetch = originalFetch;
});
const mockFetch = (impl: () => Promise<unknown>) => {
  global.fetch = jest.fn(impl as never) as unknown as typeof fetch;
};
const ready = () => mockFetch(async () => ({ ok: true, json: async () => squad }));
const preseason = () =>
  mockFetch(async () => ({ ok: false, status: 404, json: async () => ({ code: 'preseason', next_gw: 1, next_deadline: '2026-08-21T17:30:00Z' }) }));
const failing = () => mockFetch(async () => ({ ok: false, status: 500, json: async () => ({}) }));
const offline = () => mockFetch(async () => { throw new Error('offline'); });

function pitch(locale: Locale, teamId: number | null = 123, onAskPlayer = jest.fn()) {
  const view = render(inLocale(locale, <SquadPitch teamId={teamId} onAskPlayer={onAskPlayer} />));
  return { ...view, onAskPlayer };
}

describe('the squad pitch', () => {
  test('Spanish: the pitch, with a player selected, is what it was', async () => {
    ready();
    const { container } = pitch('es');
    fireEvent.click(await screen.findByRole('button', { name: 'Cole Palmer, CHE, capitán' }));
    expect(shape(container)).toMatchSnapshot();
  });

  test('Spanish: every empty and failure state is what it was', async () => {
    const states: Array<[string, () => void, number | null, RegExp]> = [
      ['idle', ready, null, /Conecta tu equipo FPL/],
      ['preseason', preseason, 123, /La temporada aún no ha comenzado/],
      ['http error', failing, 123, /No se pudo cargar la plantilla \(500\)/],
      ['offline', offline, 123, /No se pudo conectar con la API de FPL/],
    ];
    const seen: Record<string, string[]> = {};
    for (const [name, arrange, teamId, expected] of states) {
      arrange();
      const { container, unmount } = pitch('es', teamId);
      await waitFor(() => expect(container).toHaveTextContent(expected));
      seen[name] = shape(container);
      unmount();
    }
    expect(seen).toMatchSnapshot();
  });

  test('English: the pitch, the detail and the question to the chat', async () => {
    ready();
    const { container, onAskPlayer } = pitch('en');
    const captain = await screen.findByRole('button', { name: 'Cole Palmer, CHE, captain' });
    expect(container).toHaveTextContent('GW8');
    expect(container).toHaveTextContent('Bank');
    expect(container).toHaveTextContent('Bench');
    expect(container).toHaveTextContent('Tap a playerto see details');
    fireEvent.click(captain);
    const detail = screen.getByRole('region', { name: 'Details for Cole Palmer' });
    expect(within(detail).getByText('MID')).toBeInTheDocument();
    for (const label of ['GW pts', 'Sel.', 'Form']) expect(within(detail).getByText(label)).toBeInTheDocument();
    fireEvent.click(within(detail).getByRole('button', { name: /Ask AI/ }));
    expect(onAskPlayer).toHaveBeenCalledWith('Tell me about Cole Palmer — should I start this player this week?');
    const strings = onScreen(container);
    expect(strings.filter((s) => SPANISH_UI_WORDS.test(s))).toEqual([]);
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: every empty and failure state reads in English', async () => {
    const states: Array<[string, () => void, number | null, RegExp]> = [
      ['idle', ready, null, /Connect your FPL team in the Chat tab.*to see your squad here\./],
      ['preseason', preseason, 123, /The season has not started yet.*Gameweek 1 \(21 Aug\).*check Fixtures and ask in Chat\./],
      ['http error', failing, 123, /Could not load the squad \(500\)\..*Retry/],
      ['offline', offline, 123, /Could not connect to the FPL API\..*Retry/],
    ];
    for (const [, arrange, teamId, expected] of states) {
      arrange();
      const { container, unmount } = pitch('en', teamId);
      await waitFor(() => expect(container).toHaveTextContent(expected));
      expect(onScreen(container).filter((s) => SPANISH_UI_WORDS.test(s))).toEqual([]);
      unmount();
    }
  });
});
