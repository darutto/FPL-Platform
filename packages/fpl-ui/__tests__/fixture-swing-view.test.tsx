/**
 * @jest-environment jsdom
 *
 * The swing in the trend view: the divider, the greyed run before it, the markers for
 * doubles and blanks, and the order switch with its three groups.
 *
 * Every assertion counts what is in the rendered DOM. The swing LOGIC is pinned in
 * fixture-swing.test.ts; this file is about what the reader is shown.
 */
jest.mock('@/lib/presentation-access', () => ({
  usePresentationAccess: () => false,
}));
jest.mock('@/lib/data/fixture-outlook-2026-27.json', () => jest.requireActual('./fixtures/fixture-outlook-2026-27.pinned.json'));

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { FixturesBoard } from '@/components/intents/FixturesBoard';
import { FixtureTendencyChart } from '@/components/intents/FixtureTendencyChart';
import type { Swing } from '@/lib/fixture-swing';
import type { FixtureOutlookGW, TeamOutlook } from '@/lib/types';

jest.setTimeout(60_000);

type Cell = number | number[];

function window_(from: number, cells: Cell[]): FixtureOutlookGW[] {
  return cells.map((cell, i) => {
    const bands = Array.isArray(cell) ? cell : [cell];
    const band = bands.length ? Math.round(bands.reduce((a, b) => a + b, 0) / bands.length) : null;
    return {
      gameweek: from + i,
      band,
      klass: band === null ? ('blank' as const) : band <= 2 ? ('good' as const) : band >= 4 ? ('bad' as const) : ('neutral' as const),
      is_dgw: bands.length >= 2,
      is_bgw: bands.length === 0,
      fixtures: bands.map((b, j) => ({ opponent_short: `O${i}${j}`, is_home: j === 0, band: b })),
    };
  });
}

function team(series: FixtureOutlookGW[]): TeamOutlook {
  return { team_short: 'TST', team_name: 'Test', axis: 'attack', avg_band: 3, verdict: '', series, runs: [] };
}

const swingAt = (gameweek: number, direction: Swing['direction'] = 'easier'): Swing => ({
  gameweek, direction, reference: 3.0, lead: direction === 'easier' ? 1.8 : 4.2, change: direction === 'easier' ? -1.2 : 1.2, inGameweeks: gameweek - 11,
});

const flat = window_(11, [3, 3, 3, 3, 3]); // GW11-15

describe('FixtureTendencyChart swing markers', () => {
  test('without a swing the chart carries no swing furniture', () => {
    render(<FixtureTendencyChart team={team(flat)} />);
    for (const id of ['fixture-swing-divider', 'fixture-swing-grey', 'fixture-swing-since', 'fixture-swing-pin', 'fixture-swing-pill']) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
  });

  test('a swing inside the window draws the divider, greys what is before it and shows the pill', () => {
    render(<FixtureTendencyChart team={team(flat)} swing={swingAt(13)} />);
    expect(screen.getByTestId('fixture-swing-divider')).toBeInTheDocument();
    expect(screen.getByTestId('fixture-swing-grey')).toBeInTheDocument();
    expect(screen.queryByTestId('fixture-swing-since')).toBeNull();
    expect(screen.queryByTestId('fixture-swing-pin')).toBeNull();
    const pill = screen.getByTestId('fixture-swing-pill');
    expect(pill).toHaveAttribute('data-direction', 'easier');
    expect(pill).toHaveTextContent('Más fácil desde J13');
    expect(pill).toHaveTextContent('3.0 → 1.8');
    expect(pill).toHaveTextContent('en 2 J');
  });

  test('a harder swing says so', () => {
    render(<FixtureTendencyChart team={team(flat)} swing={swingAt(14, 'harder')} />);
    expect(screen.getByTestId('fixture-swing-pill')).toHaveTextContent('Más difícil desde J14');
  });

  test('a swing beyond the window is a pin, with the whole visible run greyed and no divider', () => {
    render(<FixtureTendencyChart team={team(flat)} swing={swingAt(18)} />);
    expect(screen.getByTestId('fixture-swing-pin')).toHaveTextContent('J18');
    expect(screen.getByTestId('fixture-swing-grey')).toBeInTheDocument();
    expect(screen.queryByTestId('fixture-swing-divider')).toBeNull();
  });

  test('a window paged past the swing says "since", with nothing greyed', () => {
    render(<FixtureTendencyChart team={team(flat)} swing={swingAt(9)} />);
    expect(screen.getByTestId('fixture-swing-since')).toHaveTextContent('desde J9');
    expect(screen.queryByTestId('fixture-swing-grey')).toBeNull();
    expect(screen.queryByTestId('fixture-swing-divider')).toBeNull();
  });

  test('a swing that starts on the first visible gameweek says "from", not "since"', () => {
    render(<FixtureTendencyChart team={team(flat)} swing={swingAt(11)} />);
    expect(screen.getByTestId('fixture-swing-since')).toHaveTextContent('desde J11');
    expect(screen.getByTestId('fixture-swing-pill')).toHaveTextContent('empieza ya');
  });

  test('a double is two dots on one column and a blank is a hollow marker, not a dot', () => {
    render(<FixtureTendencyChart team={team(window_(11, [3, [1, 4], 3, [], 3]))} />);
    const double = screen.getByTestId('fixture-double-marker');
    expect(double.querySelectorAll('circle')).toHaveLength(2);
    expect(screen.getAllByTestId('fixture-blank-marker')).toHaveLength(1);
  });

  test('a double with the same band twice still shows two dots', () => {
    render(<FixtureTendencyChart team={team(window_(11, [3, [2, 2], 3, 3, 3]))} />);
    expect(screen.getByTestId('fixture-double-marker').querySelectorAll('circle')).toHaveLength(2);
  });
});

describe('FixturesBoard order switch (trend view)', () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ next_gw: 9, finished_gw: 8 }),
    }) as unknown as typeof fetch;
    window.sessionStorage.clear();
  });
  afterEach(() => jest.restoreAllMocks());

  test('the order control is only offered in the trend view, and swing order groups all 20 teams', async () => {
    render(<FixturesBoard onAsk={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Cambio de racha' })).toBeNull();

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Tendencia' })); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mejor calendario' })).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.queryByTestId('fixture-swing-groups')).toBeNull();

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Cambio de racha' })); });
    const groups = screen.getByTestId('fixture-swing-groups');
    const sections = Array.from(groups.querySelectorAll('section')).map((s) => s.getAttribute('data-testid'));
    // Whatever the data holds, the groups that appear keep this order.
    const order = ['fixture-swing-group-easier', 'fixture-swing-group-stable', 'fixture-swing-group-harder'];
    expect(sections).toEqual(order.filter((id) => sections.includes(id)));
    expect(sections.length).toBeGreaterThanOrEqual(2);
    // Every team appears once.
    expect(within(groups).getAllByTestId('fixture-tendency-chart')).toHaveLength(20);
    // Swing teams carry a pill, stable ones do not.
    const easier = screen.queryByTestId('fixture-swing-group-easier');
    if (easier) {
      expect(within(easier).getAllByTestId('fixture-swing-pill').length).toBe(within(easier).getAllByTestId('fixture-tendency-chart').length);
    }
    const stable = screen.queryByTestId('fixture-swing-group-stable');
    if (stable) expect(within(stable).queryAllByTestId('fixture-swing-pill')).toHaveLength(0);
  });

  test('switching back restores the best-run order without groups', async () => {
    render(<FixturesBoard onAsk={() => {}} initialView="tendency" />);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Cambio de racha' })); });
    expect(screen.getByTestId('fixture-swing-groups')).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Mejor calendario' })); });
    expect(screen.queryByTestId('fixture-swing-groups')).toBeNull();
    expect(screen.getAllByTestId('fixture-tendency-chart')).toHaveLength(20);
  });
});
