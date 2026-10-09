/**
 * @jest-environment jsdom
 *
 * Bloque 10 — «Zonas» section of PlayerCard.
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import PlayerCard from '../components/intents/PlayerCard';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import { sharePercent, zoneChipLabel } from '../lib/defensive-zones';
import type { PlayerZonalOutlookMeta, PlayerSnapshotMeta } from '../lib/types';

const ZONES = [
  'in-box / left', 'in-box / central', 'in-box / right',
  'edge-of-box / left', 'edge-of-box / central', 'edge-of-box / right',
];

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
  data_provenance: {
    season: '2026-2027', season_label: '2026-27', live_season: '2026-2027', is_current: true,
    status: 'thin', label: '⚠ Datos de 2026-27, sólo 5 jornadas de liga — muestra corta para una lectura de liga',
    ingested_at: '2026-10-05T07:12:42Z', n_matches: 50, n_shots: 1398,
  },
};

const withZonal = (z: PlayerZonalOutlookMeta | null | undefined): PlayerSnapshotMeta => ({
  ...playerSnapshotOkResponse.player_snapshot!,
  zonal: z,
});

describe('zone helpers', () => {
  test('sharePercent is the single 0–1 → % conversion', () => {
    expect(sharePercent(0.5923)).toBe(59);
    expect(sharePercent(1)).toBe(100);
    expect(sharePercent(0.255)).toBe(26);
  });

  test('zoneChipLabel covers all six engine zones, distinctly', () => {
    const labels = ZONES.map(zoneChipLabel);
    expect(new Set(labels).size).toBe(6);
    expect(labels).toEqual([
      'Área izq', 'Área centro', 'Área der', 'Frontal izq', 'Frontal centro', 'Frontal der',
    ]);
    for (const l of labels) expect(l).not.toContain('/');
  });

  test('an unknown zone key passes through', () => {
    expect(zoneChipLabel('somewhere')).toBe('somewhere');
  });
});

describe('PlayerCard — Zonas section', () => {
  test('absent or null zonal leaves the card without the section', () => {
    const { rerender } = render(<PlayerCard data={withZonal(undefined)} />);
    expect(screen.queryByTestId('player-zonas')).not.toBeInTheDocument();
    rerender(<PlayerCard data={withZonal(null)} />);
    expect(screen.queryByTestId('player-zonas')).not.toBeInTheDocument();
    expect(screen.getByText('Haaland')).toBeInTheDocument();
  });

  test('renders heading, window, verdict and one section inside the same card', () => {
    const { container } = render(<PlayerCard data={withZonal(zonal)} />);
    const section = screen.getByTestId('player-zonas');
    expect(within(section).getByText('Zonas')).toBeInTheDocument();
    expect(within(section).getByText(/próximas 3 jornadas · J6–J8/)).toBeInTheDocument();
    expect(screen.getByTestId('player-zonas-verdict')).toHaveTextContent('cruce favorable en J7 (Everton)');
    expect(container.querySelectorAll('[data-testid="player-zonas"]')).toHaveLength(1);
    expect(screen.getByText('Haaland')).toBeInTheDocument();
  });

  test('chips show the percentage once, converted from the 0–1 fraction', () => {
    render(<PlayerCard data={withZonal(zonal)} />);
    const chips = screen.getByTestId('player-zonas-chips');
    expect(chips).toHaveTextContent('Área centro · 59% de su xG sin penalti');
    expect(chips).toHaveTextContent('Frontal der · 26% de su xG sin penalti');
    expect(chips).not.toHaveTextContent('0.59');
    expect(chips).not.toHaveTextContent('5923');
  });

  test('chips are not renormalised: two zones need not sum to 100', () => {
    render(<PlayerCard data={withZonal(zonal)} />);
    const total = zonal.zones.reduce((a, z) => a + sharePercent(z.share), 0);
    expect(total).toBeLessThan(100);
    expect(screen.getByTestId('player-zonas-chips').children).toHaveLength(2);
  });

  test('one row per pending match with gameweek and L/V', () => {
    render(<PlayerCard data={withZonal(zonal)} />);
    const rows = screen.getAllByTestId('player-zonas-row');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('J6');
    expect(rows[0]).toHaveTextContent('Bournemouth');
    expect(rows[0]).toHaveTextContent('(L)');
    expect(rows[1]).toHaveTextContent('Everton');
    expect(rows[1]).toHaveTextContent('(V)');
  });

  test('favorable is turquoise and names the zone; neutral is grey', () => {
    render(<PlayerCard data={withZonal(zonal)} />);
    const [neutral, favorable] = screen.getAllByTestId('player-zonas-row');
    const fav = within(favorable).getByText(/Cruce favorable/);
    expect(fav).toHaveTextContent('Área centro');
    expect(fav.className).toContain('turquoise');
    const neu = within(neutral).getByText('Sin cruce destacado');
    expect(neu.className).toContain('bf-gray');
    expect(neu.className).not.toContain('turquoise');
  });

  test('no_data says so in text and is not worded as neutral', () => {
    render(<PlayerCard data={withZonal(zonal)} />);
    const row = screen.getAllByTestId('player-zonas-row')[2];
    expect(row).toHaveAttribute('data-status', 'no_data');
    expect(row).toHaveTextContent('Sin datos del rival');
    expect(row).not.toHaveTextContent('Sin cruce destacado');
  });

  test('all no_data: availability verdict, no neutral wording anywhere', () => {
    const allNoData: PlayerZonalOutlookMeta = {
      ...zonal,
      fixtures: zonal.fixtures.map((f) => ({ ...f, status: 'no_data' as const, matches: [] })),
      verdict_kind: 'no_data',
      verdict: 'Sin datos zonales de los rivales de estos partidos, no se puede valorar el cruce.',
    };
    render(<PlayerCard data={withZonal(allNoData)} />);
    const section = screen.getByTestId('player-zonas');
    expect(section).toHaveAttribute('data-verdict-kind', 'no_data');
    expect(within(section).getAllByText('Sin datos del rival')).toHaveLength(3);
    expect(section).not.toHaveTextContent('Sin cruce destacado');
  });

  test('provenance is visible, verbatim, and flagged when not current', () => {
    const { unmount } = render(<PlayerCard data={withZonal(zonal)} />);
    const stamp = screen.getByTestId('zonal-provenance');
    expect(stamp).toHaveTextContent('muestra corta');
    expect(stamp).toHaveAttribute('data-status', 'thin');
    unmount();
    const old: PlayerZonalOutlookMeta = {
      ...zonal,
      data_provenance: {
        ...zonal.data_provenance!,
        status: 'stale_season',
        label: '⚠ Datos de 2025-26, no de la temporada en curso (2026-27)',
      },
    };
    render(<PlayerCard data={withZonal(old)} />);
    expect(screen.getByTestId('zonal-provenance')).toHaveTextContent('2025-26');
    expect(screen.getByTestId('zonal-provenance')).toHaveAttribute('data-status', 'stale_season');
  });

  test('a double gameweek renders both matches', () => {
    const dgw: PlayerZonalOutlookMeta = {
      ...zonal,
      fixtures: [zonal.fixtures[0], { ...zonal.fixtures[1], gameweek: 6, fixture_id: 99 }],
    };
    render(<PlayerCard data={withZonal(dgw)} />);
    expect(screen.getAllByTestId('player-zonas-row')).toHaveLength(2);
  });

  test('empty fixtures render nothing (defensive)', () => {
    render(<PlayerCard data={withZonal({ ...zonal, fixtures: [] })} />);
    expect(screen.queryByTestId('player-zonas')).not.toBeInTheDocument();
  });

  test('framing is opportunity only: no transaction words', () => {
    render(<PlayerCard data={withZonal(zonal)} />);
    const text = screen.getByTestId('player-zonas').textContent ?? '';
    expect(text).not.toMatch(/comprar|vender|fichar|traspas|urgente|peligro/i);
  });
});
