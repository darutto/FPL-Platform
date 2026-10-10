/**
 * @jest-environment jsdom
 *
 * i152 — mini-pitch in the «Zonas» section of PlayerCard.
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import PlayerCard from '../components/intents/PlayerCard';
import PlayerZonesPitch, { cellOpacity } from '../components/intents/PlayerZonesPitch';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import { pitchCell } from '../lib/defensive-zones';
import type {
  PlayerSnapshotMeta,
  PlayerZonalFixture,
  PlayerZonalOutlookMeta,
  PlayerZonalZone,
} from '../lib/types';

const SIX = [
  'in-box / left', 'in-box / central', 'in-box / right',
  'edge-of-box / left', 'edge-of-box / central', 'edge-of-box / right',
];

const zone = (z: string, share: number): PlayerZonalZone => ({ zone: z, share });
const fixture = (
  status: PlayerZonalFixture['status'],
  matches: PlayerZonalFixture['matches'] = [],
  gw = 6,
): PlayerZonalFixture => ({
  gameweek: gw, fixture_id: gw, opponent: 'Rival', opponent_short: 'RIV', is_home: true, status, matches,
});
const match = (z: string) => ({ zone: z, delta_vs_avg: 0.05, player_share: 0.5 });
const cellOf = (z: string) => screen.getByTestId(`pitch-cell-${z.replace(/[^a-z]+/g, '-')}`);

describe('pitchCell', () => {
  test('maps all six engine zones to distinct cells', () => {
    const cells = SIX.map((z) => JSON.stringify(pitchCell(z)));
    expect(new Set(cells).size).toBe(6);
    expect(pitchCell('in-box / left')).toEqual({ row: 0, col: 0 });
    expect(pitchCell('edge-of-box / right')).toEqual({ row: 1, col: 2 });
  });

  test('unknown keys map to null', () => {
    expect(pitchCell('somewhere')).toBeNull();
    expect(pitchCell('in-box / up')).toBeNull();
    expect(pitchCell('midfield / left')).toBeNull();
  });
});

describe('PlayerZonesPitch', () => {
  test('draws all six zones when the player has all six', () => {
    render(<PlayerZonesPitch zones={SIX.map((z) => zone(z, 0.4))} fixtures={[fixture('neutral')]} />);
    for (const z of SIX) expect(cellOf(z)).toBeInTheDocument();
    // distinct positions: six different (x, y) pairs
    const pos = SIX.map((z) => `${cellOf(z).getAttribute('x')},${cellOf(z).getAttribute('y')}`);
    expect(new Set(pos).size).toBe(6);
  });

  test('frontal zones sit below the box, box zones inside it', () => {
    render(<PlayerZonesPitch zones={SIX.map((z) => zone(z, 0.4))} fixtures={[]} />);
    expect(Number(cellOf('in-box / central').getAttribute('y'))).toBeLessThan(
      Number(cellOf('edge-of-box / central').getAttribute('y')),
    );
    expect(Number(cellOf('in-box / left').getAttribute('x'))).toBeLessThan(
      Number(cellOf('in-box / right').getAttribute('x')),
    );
  });

  test('only the player zones are drawn', () => {
    render(<PlayerZonesPitch zones={[zone('in-box / central', 0.6)]} fixtures={[]} />);
    expect(screen.getAllByTestId(/^pitch-cell-/)).toHaveLength(1);
  });

  test('with a favorable coincidence the matching zone is turquoise, the others neutral', () => {
    render(
      <PlayerZonesPitch
        zones={[zone('in-box / central', 0.6), zone('edge-of-box / right', 0.3)]}
        fixtures={[fixture('favorable', [match('in-box / central')])]}
      />,
    );
    const hit = cellOf('in-box / central');
    const miss = cellOf('edge-of-box / right');
    expect(hit).toHaveAttribute('data-match', 'true');
    expect(hit.getAttribute('fill')).toBe('#02EBAE');
    expect(miss).toHaveAttribute('data-match', 'false');
    expect(miss.getAttribute('fill')).toBe('#6b6975');
  });

  test('without favorable fixtures only the player zones are painted, all neutral', () => {
    render(
      <PlayerZonesPitch
        zones={[zone('in-box / central', 0.6), zone('in-box / left', 0.3)]}
        fixtures={[fixture('neutral'), fixture('no_data')]}
      />,
    );
    for (const c of screen.getAllByTestId(/^pitch-cell-/)) {
      expect(c).toHaveAttribute('data-match', 'false');
      expect(c.getAttribute('fill')).toBe('#6b6975');
    }
  });

  test('a match on a zone that is not the player zone paints nothing extra', () => {
    render(
      <PlayerZonesPitch
        zones={[zone('in-box / central', 0.6)]}
        fixtures={[fixture('favorable', [match('in-box / left')])]}
      />,
    );
    expect(screen.getAllByTestId(/^pitch-cell-/)).toHaveLength(1);
    expect(cellOf('in-box / central')).toHaveAttribute('data-match', 'false');
  });

  test('matches in a non-favorable fixture never highlight', () => {
    render(
      <PlayerZonesPitch
        zones={[zone('in-box / central', 0.6)]}
        fixtures={[fixture('neutral', [match('in-box / central')])]}
      />,
    );
    expect(cellOf('in-box / central')).toHaveAttribute('data-match', 'false');
  });

  test('no zones → no pitch', () => {
    const { container } = render(<PlayerZonesPitch zones={[]} fixtures={[fixture('favorable')]} />);
    expect(container.querySelector('svg')).toBeNull();
  });

  test('zones the pitch cannot place are skipped; if none can be placed, no pitch', () => {
    const { container } = render(
      <PlayerZonesPitch zones={[zone('somewhere', 0.5), zone('in-box / up', 0.5)]} fixtures={[]} />,
    );
    expect(container.querySelector('svg')).toBeNull();
  });

  test('aria-label lists the zones with percentages and the coincidence', () => {
    render(
      <PlayerZonesPitch
        zones={[zone('in-box / central', 0.5923), zone('edge-of-box / right', 0.2611)]}
        fixtures={[fixture('favorable', [match('in-box / central')])]}
      />,
    );
    const label = screen.getByRole('img').getAttribute('aria-label') ?? '';
    expect(label).toContain('Área centro: 59% de su xG (coincide con un cruce favorable)');
    expect(label).toContain('Frontal der: 26% de su xG');
    expect(label).not.toContain('Frontal der: 26% de su xG (coincide');
  });

  test('cells carry the percentage once, from the 0–1 share', () => {
    const { container } = render(
      <PlayerZonesPitch zones={[zone('in-box / central', 0.5923)]} fixtures={[]} />,
    );
    const texts = Array.from(container.querySelectorAll('text')).map((t) => t.textContent);
    expect(texts).toEqual(['59%']);
  });

  test('nothing red anywhere in the drawing', () => {
    const { container } = render(
      <PlayerZonesPitch
        zones={SIX.map((z) => zone(z, 0.5))}
        fixtures={[fixture('favorable', [match('in-box / left')])]}
      />,
    );
    const html = container.innerHTML.toLowerCase();
    for (const bad of ['#e74c3c', '#ff0000', 'red', 'coral']) expect(html).not.toContain(bad);
  });

  test('shade grows with share and a coincidence is stronger than a plain zone', () => {
    expect(cellOpacity(0.8, false)).toBeGreaterThan(cellOpacity(0.2, false));
    expect(cellOpacity(0.5, true)).toBeGreaterThan(cellOpacity(0.5, false));
    expect(cellOpacity(5, true)).toBeLessThanOrEqual(0.52);
    expect(cellOpacity(-1, false)).toBeCloseTo(0.1);
  });
});

describe('PlayerCard integration', () => {
  const zonal = (zones: PlayerZonalZone[], fixtures: PlayerZonalFixture[]): PlayerZonalOutlookMeta => ({
    zones, gw_from: 6, gw_to: 8, fixtures, verdict_kind: 'neutral', verdict: 'v', data_provenance: null,
  });
  const card = (z: PlayerZonalOutlookMeta | null): PlayerSnapshotMeta => ({
    ...playerSnapshotOkResponse.player_snapshot!, zonal: z,
  });

  test('the section shows the pitch, the legend only with a favorable cross', () => {
    const { unmount } = render(
      <PlayerCard
        data={card(zonal([zone('in-box / central', 0.59)], [fixture('favorable', [match('in-box / central')])]))}
      />,
    );
    expect(screen.getByTestId('player-zones-pitch')).toBeInTheDocument();
    expect(screen.getByTestId('player-zonas-legend')).toHaveTextContent('Turquesa');
    unmount();
    render(<PlayerCard data={card(zonal([zone('in-box / central', 0.59)], [fixture('neutral')]))} />);
    expect(screen.getByTestId('player-zones-pitch')).toBeInTheDocument();
    expect(screen.queryByTestId('player-zonas-legend')).not.toBeInTheDocument();
  });

  test('no placeable zones: no pitch wrapper, chips remain', () => {
    render(<PlayerCard data={card(zonal([zone('somewhere', 0.5)], [fixture('neutral')]))} />);
    expect(screen.queryByTestId('player-zonas-pitch-wrap')).not.toBeInTheDocument();
    expect(screen.getByTestId('player-zonas-chips')).toBeInTheDocument();
  });

  test('no zonal: no pitch at all', () => {
    render(<PlayerCard data={card(null)} />);
    expect(screen.queryByTestId('player-zones-pitch')).not.toBeInTheDocument();
  });
});
