/**
 * @jest-environment jsdom
 *
 * i110 — the in-chat calendar card paints ONE header per team, and no
 * tendency "ladder" for a single gameweek.
 *
 * Seen in prod (Bournemouth vs CHE, J6, 2026-09-20): the card mounted both
 * sub-views for the same team and each painted its own header ("BOU · Prom
 * 4.0 · verdict"), so the block appeared twice, and the 1-5 ladder with a
 * single point said nothing the cell's "4" did not.
 *
 * Every assertion counts what is in the rendered DOM (data-testid on the
 * header and on the chart), never what the props asked for. The two-team
 * case is the one that captures the bug as seen: two teams used to yield
 * four headers.
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import FixtureOutlookCard from '@/components/intents/FixtureOutlookCard';
import { FixturesBoard } from '@/components/intents/FixturesBoard';
import { FixtureTickerRow } from '@/components/intents/FixtureTickerRow';
import { FixtureTendencyChart } from '@/components/intents/FixtureTendencyChart';
import type { FixtureOutlookGW, FixtureOutlookMeta, TeamOutlook } from '@/lib/types';

function gw(gameweek: number, opp: string, band: number, isHome = true): FixtureOutlookGW {
  return {
    gameweek,
    band,
    klass: band <= 2 ? 'good' : band >= 4 ? 'bad' : 'neutral',
    is_dgw: false,
    is_bgw: false,
    fixtures: [{ opponent_short: opp, is_home: isHome, band }],
  };
}

function team(short: string, name: string, series: FixtureOutlookGW[]): TeamOutlook {
  const bands = series.map((s) => s.band as number);
  return {
    team_short: short,
    team_name: name,
    axis: 'attack',
    avg_band: bands.reduce((a, b) => a + b, 0) / bands.length,
    verdict: `${name}: calendario de prueba`,
    series,
    runs: [],
  };
}

const ONE_GW = team('BOU', 'Bournemouth', [gw(6, 'CHE', 4, false)]);
const FIVE_GW = team('ARS', 'Arsenal', [
  gw(6, 'CHE', 4),
  gw(7, 'HUL', 2, false),
  gw(8, 'COV', 2),
  gw(9, 'LIV', 5, false),
  gw(10, 'BRE', 3),
]);
const OTHER_FIVE = team('NEW', 'Newcastle', [
  gw(6, 'HUL', 2),
  gw(7, 'COV', 2, false),
  gw(8, 'MCI', 5),
  gw(9, 'AVL', 3, false),
  gw(10, 'EVE', 3),
]);

function meta(teams: TeamOutlook[]): FixtureOutlookMeta {
  return { axis: 'attack', horizon: 5, current_gameweek: 5, teams };
}

describe('i110 — FixtureOutlookCard', () => {
  it('series of 1: exactly one header, no tendency chart', () => {
    render(<FixtureOutlookCard data={meta([ONE_GW])} />);
    const headers = screen.getAllByTestId('team-header');
    expect(headers).toHaveLength(1);
    expect(within(headers[0]).getByText('BOU')).toBeInTheDocument();
    expect(within(headers[0]).getByText('Prom 4.0')).toBeInTheDocument();
    expect(screen.queryByTestId('fixture-tendency-chart')).not.toBeInTheDocument();
    // The ticker row (the cell that says "4") is still there.
    expect(screen.getByTestId('fixture-ticker-row')).toBeInTheDocument();
    expect(screen.getByText('CHE')).toBeInTheDocument();
  });

  it('series of 5: one header, chart present', () => {
    render(<FixtureOutlookCard data={meta([FIVE_GW])} />);
    expect(screen.getAllByTestId('team-header')).toHaveLength(1);
    expect(screen.getAllByTestId('fixture-tendency-chart')).toHaveLength(1);
    // The chart's x-axis names the opponents; the header is not repeated inside it.
    const chart = screen.getByTestId('fixture-tendency-chart');
    expect(within(chart).queryByTestId('team-header')).not.toBeInTheDocument();
  });

  it('two teams with series of 5: exactly two headers (one per team, not four)', () => {
    render(<FixtureOutlookCard data={meta([FIVE_GW, OTHER_FIVE])} />);
    const headers = screen.getAllByTestId('team-header');
    expect(headers).toHaveLength(2);
    expect(headers.map((h) => within(h).getByText(/^(ARS|NEW)$/).textContent)).toEqual(['ARS', 'NEW']);
    expect(screen.getAllByTestId('fixture-tendency-chart')).toHaveLength(2);
    // Each team block: header first, then the row, then the chart.
    const blocks = screen.getAllByTestId('fixture-outlook-team');
    expect(blocks).toHaveLength(2);
    for (const block of blocks) {
      const order = Array.from(block.querySelectorAll('[data-testid]')).map((el) =>
        el.getAttribute('data-testid'),
      );
      expect(order.indexOf('team-header')).toBeLessThan(order.indexOf('fixture-ticker-row'));
      expect(order.indexOf('fixture-ticker-row')).toBeLessThan(order.indexOf('fixture-tendency-chart'));
    }
  });

  it('mixed: a 1-GW team and a 5-GW team -> two headers, one chart', () => {
    render(<FixtureOutlookCard data={meta([ONE_GW, FIVE_GW])} />);
    expect(screen.getAllByTestId('team-header')).toHaveLength(2);
    expect(screen.getAllByTestId('fixture-tendency-chart')).toHaveLength(1);
  });
});

describe('i110 — the standalone views keep their own header by default', () => {
  it('FixtureTickerRow alone renders one header', () => {
    render(<FixtureTickerRow team={FIVE_GW} />);
    expect(screen.getAllByTestId('team-header')).toHaveLength(1);
  });

  it('FixtureTendencyChart alone renders one header', () => {
    render(<FixtureTendencyChart team={FIVE_GW} />);
    expect(screen.getAllByTestId('team-header')).toHaveLength(1);
  });

  it('showHeader={false} removes the header from either view', () => {
    render(
      <div>
        <FixtureTickerRow team={FIVE_GW} showHeader={false} />
        <FixtureTendencyChart team={FIVE_GW} showHeader={false} />
      </div>,
    );
    expect(screen.queryByTestId('team-header')).not.toBeInTheDocument();
  });

  it('the /fixtures board still shows one header per team in its detailed view', () => {
    render(<FixturesBoard onAsk={() => undefined} />);
    const rows = screen.getByTestId('fixture-board-rows');
    const headers = within(rows).getAllByTestId('team-header');
    const rowsRendered = within(rows).getAllByTestId('fixture-ticker-row');
    expect(headers.length).toBe(rowsRendered.length);
    expect(headers.length).toBeGreaterThan(0);
  });
});
