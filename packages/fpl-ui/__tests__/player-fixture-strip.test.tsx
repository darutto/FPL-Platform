/**
 * @jest-environment jsdom
 *
 * The player card's fixture strip by plan. The backend decides the tier; these tests pin
 * what the strip does with each answer. All data here is synthetic.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import type { FixtureEntry, FixtureOutlookGW } from '@/lib/types';
import { buildStrip, stripAxis, bandFor } from '@/lib/player-fixture-strip';
import { parseCompetitions } from '@/lib/fixture-competitions';
import { PlayerFixtureStrip } from '@/components/intents/PlayerFixtureStrip';

const SERIES: Record<'attack' | 'defence', FixtureOutlookGW[]> = {
  attack: [
    { gameweek: 12, band: 2, klass: 'good', is_dgw: false, is_bgw: false, fixtures: [{ opponent_short: 'AAA', is_home: true, band: 2 }] },
    // A gameweek the bundle has no band for: the cell keeps FPL's FDR.
    { gameweek: 13, band: null, klass: 'blank', is_dgw: false, is_bgw: false, fixtures: [] },
  ],
  defence: [
    { gameweek: 12, band: 4, klass: 'bad', is_dgw: false, is_bgw: false, fixtures: [{ opponent_short: 'AAA', is_home: true, band: 4 }] },
    { gameweek: 13, band: null, klass: 'blank', is_dgw: false, is_bgw: false, fixtures: [] },
  ],
};

// The outlook module is replaced below; pin the bundle too so nothing here can read the weekly one.
jest.mock('@/lib/data/fixture-outlook-2026-27.json', () => jest.requireActual('./fixtures/fixture-outlook-2026-27.pinned.json'));
jest.mock('@/lib/fixture-outlook-real', () => ({
  buildRealSeasonOutlook: (axis: 'attack' | 'defence') => ({
    teams: [{ team_short: 'TST', team_name: 'Test', axis, avg_band: null, verdict: '', series: SERIES[axis], runs: [] }],
  }),
}));

const FIXTURES: FixtureEntry[] = [
  { gameweek: 12, opponent_short: 'AAA', is_home: true, difficulty: 3 },
  { gameweek: 13, opponent_short: 'BBB', is_home: false, difficulty: 4 },
];

const PREMIUM = {
  available: true,
  tier: 'premium',
  teams: {
    TST: {
      matches: [
        { kickoff_utc: '2026-11-26T20:00:00Z', week: 'w', gameweek: 13, competition: 'UEL', venue: 'A',
          opponent: 'Synthetic FC', opponent_code: 'SYN', rest_days_before: 4, rest_whole_days_before: 4,
          rest_days_after: 2.9, previous_competition: 'PL' },
      ],
      pl_matches: [
        { kickoff_utc: '2026-11-21T15:00:00Z', week: 'w', gameweek: 12, venue: 'H', opponent: 'Alpha', opponent_code: 'AAA',
          rest_whole_days_before: 6, previous_competition: 'PL', rotation: false },
        { kickoff_utc: '2026-11-29T14:00:00Z', week: 'w', gameweek: 13, venue: 'A', opponent: 'Beta', opponent_code: 'BBB',
          rest_whole_days_before: 2, previous_competition: 'UEL', rotation: true },
      ],
    },
  },
};

function answer(payload: unknown) {
  (globalThis as { fetch?: unknown }).fetch = jest.fn(async () => ({ ok: true, json: async () => payload }));
}

afterEach(() => {
  delete (globalThis as { fetch?: unknown }).fetch;
});

describe('player-fixture-strip lib', () => {
  test('axis goes by FPL position: DEF/GKP defence, the rest attack', () => {
    expect(['FWD', 'MID', 'DEF', 'GKP'].map(stripAxis)).toEqual(['attack', 'attack', 'defence', 'defence']);
  });

  test('band comes from the matching fixture; a mismatch or blank gives none', () => {
    expect(bandFor(FIXTURES[0], SERIES.attack)).toBe(2);
    expect(bandFor(FIXTURES[1], SERIES.attack)).toBeNull();
    expect(bandFor({ ...FIXTURES[0], opponent_short: 'ZZZ' }, SERIES.attack)).toBeNull();
    expect(bandFor(FIXTURES[0], null)).toBeNull();
  });

  test('premium strip puts a cup match before its gameweek and the rest notice on the next PL match', () => {
    const view = parseCompetitions(PREMIUM)!;
    const cells = buildStrip(FIXTURES, view.teams.get('TST')!, SERIES.attack);
    expect(cells.map((c) => (c.kind === 'pl' ? `${c.gameweek}:${c.opponent}` : c.competition))).toEqual([
      '12:AAA',
      'UEL',
      '13:BBB',
    ]);
    const last = cells[2];
    expect(last.kind === 'pl' && last.rest).toEqual({ days: 2, competition: 'UEL' });
    const first = cells[0];
    expect(first.kind === 'pl' && first.rest).toBeNull();
  });

  test('without extras (Free, or no answer) the strip keeps its band and drops cup cells and rest', () => {
    const cells = buildStrip(FIXTURES, null, SERIES.attack);
    expect(cells.map((c) => c.kind)).toEqual(['pl', 'pl']);
    expect(cells.map((c) => (c.kind === 'pl' ? [c.band, c.rest] : null))).toEqual([[2, null], [null, null]]);
  });
});

/** The band never depends on the tier: what every plan sees on the Premier League cells. */
async function expectBandCells() {
  await waitFor(() => expect(screen.getAllByTestId('player-strip-pl')[0]).toHaveAttribute('data-source', 'band'));
  const pl = screen.getAllByTestId('player-strip-pl');
  expect(pl[1]).toHaveAttribute('data-source', 'fdr');
  expect(pl[1]).toHaveTextContent('BBB (V) · 4');
  expect(screen.getByTestId('player-strip-legend')).toHaveTextContent('FácilMuy difícil');
}

describe('PlayerFixtureStrip by tier (calendar rules: band for all, Europe/cups Premium)', () => {
  test('no answer (unavailable): band cells, no lock line, no cup cells', async () => {
    answer({ available: false });
    render(<PlayerFixtureStrip fixtures={FIXTURES} teamShort="TST" position="FWD" />);
    expect(screen.getByText('J12')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/fpl-fixture-competitions?team=TST'));
    await expectBandCells();
    expect(screen.queryByTestId('player-strip-locked')).not.toBeInTheDocument();
    expect(screen.queryByTestId('player-strip-extra')).not.toBeInTheDocument();
    expect(screen.queryByTestId('player-strip-rest')).not.toBeInTheDocument();
  });

  test('free: the same band cells, plus the calendar lock without any axis word', async () => {
    answer({ available: true, tier: 'free' });
    render(<PlayerFixtureStrip fixtures={FIXTURES} teamShort="TST" position="DEF" />);
    const line = await screen.findByTestId('player-strip-locked');
    expect(line).toHaveTextContent(/^🔒 Europa y copas · Ver con Premium$/);
    expect(line).not.toHaveTextContent(/Ataque|Portería/);
    expect(within(line).getByRole('link')).toHaveAttribute('href', '/subscribe');
    await expectBandCells();
    expect(screen.getAllByTestId('player-strip-pl')[0].querySelector('[title]')).toHaveAttribute('title', 'Difícil');
    expect(screen.getByTestId('player-strip-footnote')).toHaveTextContent('Dificultad propia · Portería a cero');
    expect(screen.queryByTestId('player-strip-extra')).not.toBeInTheDocument();
    expect(screen.queryByTestId('player-strip-rest')).not.toBeInTheDocument();
  });

  test('premium: band cell, FDR fallback, cup cell, rest notice, legend and footnote', async () => {
    answer(PREMIUM);
    render(<PlayerFixtureStrip fixtures={FIXTURES} teamShort="TST" position="FWD" />);
    await waitFor(() => expect(screen.getAllByTestId('player-strip-pl')[0]).toHaveAttribute('data-source', 'band'));
    const pl = screen.getAllByTestId('player-strip-pl');
    expect(pl[1]).toHaveAttribute('data-source', 'fdr');
    expect(pl[1]).toHaveTextContent('BBB (V) · 4');
    expect(screen.getByTestId('player-strip-extra')).toHaveTextContent('UEL');
    expect(screen.getByTestId('player-strip-rest')).toHaveTextContent('2d · UEL');
    expect(screen.getByTestId('player-strip-legend')).toHaveTextContent('FácilMuy difícil');
    expect(screen.getByTestId('player-strip-footnote')).toHaveTextContent('Dificultad propia · Ataque · FDR de FPL donde falta');
    expect(screen.queryByTestId('player-strip-locked')).not.toBeInTheDocument();
  });

  test('premium defender reads the defence band', async () => {
    answer(PREMIUM);
    render(<PlayerFixtureStrip fixtures={FIXTURES} teamShort="TST" position="DEF" />);
    await waitFor(() => expect(screen.getAllByTestId('player-strip-pl')[0]).toHaveAttribute('data-source', 'band'));
    const first = screen.getAllByTestId('player-strip-pl')[0];
    // Colour only in the cell; the band word lives in the tooltip.
    expect(first).not.toHaveTextContent('Difícil');
    expect(first.querySelector('[title]')).toHaveAttribute('title', 'Difícil');
    expect(first).toHaveTextContent('AAA (L)');
    expect(screen.getByTestId('player-strip-footnote')).toHaveTextContent('Portería a cero');
  });
});
