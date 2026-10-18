/**
 * @jest-environment jsdom
 *
 * The multi-competition layer of /fixtures (iteration 2: one timeline per team), at both tiers.
 *
 * The backend decides the tier; these tests pin what the board does with each
 * answer: the premium timeline, the free ghost tile (never a rival or a competition),
 * the "Otras competiciones" switch, and nothing at all when the layer is unavailable
 * (all production ever sees). Each full-board render is expensive in jsdom, so there are few.
 */
// The owner-only "Presentar" switch reads the Clerk session; these tests render the board without one.
jest.mock('@/lib/presentation-access', () => ({
  usePresentationAccess: () => (globalThis as { __owner?: boolean }).__owner !== false,
}));

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { FixturesBoard } from '@/components/intents/FixturesBoard';
import { REAL_SEASON_GENERATION } from '@/lib/fixture-outlook-real';

jest.setTimeout(40_000);

const START = (REAL_SEASON_GENERATION?.gameweeks_played ?? 0) + 1;

/** Arsenal's week: PL, then a Tuesday UCL (3 whole days later), then PL again (rotation notice). */
const PREMIUM = {
  available: true,
  tier: 'premium',
  teams: {
    ARS: {
      matches: [
        { kickoff_utc: '2026-10-21T19:00:00Z', week: '2026-10-19', gameweek: START + 1, competition: 'UCL',
          venue: 'A', opponent: 'FC Bayern München', opponent_code: 'BAY', rest_days_before: 3.1,
          rest_whole_days_before: 3, rest_days_after: 2.8, previous_competition: 'PL' },
      ],
      pl_matches: [
        { kickoff_utc: '2026-10-18T15:30:00Z', week: '2026-10-12', gameweek: START, venue: 'A', opponent: 'Nottingham Forest',
          opponent_code: 'NFO', rest_whole_days_before: 4, previous_competition: 'UCL', rotation: false },
        { kickoff_utc: '2026-10-24T14:00:00Z', week: '2026-10-19', gameweek: START + 1, venue: 'H', opponent: 'Everton',
          opponent_code: 'EVE', rest_whole_days_before: 2, previous_competition: 'UCL', rotation: true },
      ],
    },
    // Two matches before one gameweek, and no notice: two bars, no dot.
    MCI: {
      matches: [
        { kickoff_utc: '2026-10-27T20:00:00Z', week: 'w', gameweek: START + 2, competition: 'UEL', venue: 'H',
          opponent: 'Real Betis', opponent_code: 'BET', rest_days_before: 4, rest_whole_days_before: 4,
          rest_days_after: 3, previous_competition: 'PL' },
        { kickoff_utc: '2026-10-28T20:00:00Z', week: 'w', gameweek: START + 2, competition: 'EFL', venue: 'A',
          opponent: 'Fleetwood Town', opponent_code: 'FLT', rest_days_before: 1, rest_whole_days_before: 1,
          rest_days_after: 4, previous_competition: 'UEL' },
      ],
      pl_matches: [
        { kickoff_utc: '2026-11-01T16:30:00Z', week: 'w', gameweek: START + 2, venue: 'H', opponent: 'Chelsea',
          opponent_code: 'CHE', rest_whole_days_before: 4, previous_competition: 'EFL', rotation: false },
      ],
    },
  },
};
/** All the server tells Free/Tribuna: the layer exists and is locked. */
const FREE = { available: true, tier: 'free' };

function mockBackend(competitions: unknown, ok = true) {
  global.fetch = jest.fn(async (url: RequestInfo | URL) => {
    if (String(url).includes('fpl-fixture-competitions')) {
      return { ok, json: async () => competitions } as Response;
    }
    return {
      ok: true,
      json: async () => ({ next_gw: START, finished_gw: REAL_SEASON_GENERATION?.gameweeks_played ?? 0 }),
    } as Response;
  }) as unknown as typeof fetch;
}

const settled = () =>
  waitFor(() => expect(screen.getByText(/^J\d+–J\d+$/).textContent).toMatch(new RegExp(`^J${START}–`)));

const boardRows = () => screen.getByTestId('fixture-board-rows');

/** The team row (its timeline, or its plain tiles) of Arsenal inside the detailed view. */
const arsenal = () =>
  within(boardRows())
    .getAllByTestId('fixture-ticker-row')
    .find((row) => within(row).queryByText('ARS', { selector: 'button, span' }))!;

describe('FixturesBoard multi-competition layer (timeline)', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => jest.restoreAllMocks());

  test('premium: a tile of its own, the rest in the gap, the notice in gold, and the phrase only on demand', async () => {
    mockBackend(PREMIUM);
    render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    const lane = await within(arsenal()).findByTestId('fixture-timeline');

    // Order: PL (START) -> UCL -> PL (START+1), by real kickoff; the UCL tile carries sigla + 3-letter code + L/V.
    const tile = within(lane).getByTestId('competition-tile');
    expect(tile).toHaveTextContent('UCL');
    expect(tile).toHaveTextContent('BAY');
    expect(tile).toHaveTextContent('V');
    expect(tile).not.toHaveTextContent('Bayern');
    const first = within(lane).getByTitle(new RegExp(`^J${START} ·`));
    const second = within(lane).getByTitle(new RegExp(`^J${START + 1} ·`));
    const after = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(after(first, tile)).toBe(true);
    expect(after(tile, second)).toBe(true);
    // The Premier League tile itself says only gameweek, rival, venue (and colour): no competition text inside.
    expect(first).not.toHaveTextContent(/UCL|descanso|rotación/);

    // Rest between each consecutive pair: whole days, grey; the rotation one is gold and focusable.
    expect(within(lane).getAllByTestId('rest-days')[0]).toHaveTextContent('3d');
    const gold = within(lane).getByTestId('rotation-notice');
    expect(gold).toHaveTextContent('2d');
    expect(gold.className).toMatch(/text-bf-gold/);
    expect(within(lane).getByTestId('rotation-gap')).toBeInTheDocument();
    expect(within(lane).getByTestId('rotation-gap')).toHaveAccessibleName('2 días tras UCL');

    // No sentence in any cell: the detail line is empty until something is picked.
    const detail = within(lane).getByTestId('competition-detail');
    expect(detail).toBeEmptyDOMElement();

    // Tap a tile: the full phrase. Keyboard focus does the same; Escape closes it.
    fireEvent.click(tile);
    expect(detail).toHaveTextContent('Champions League ante FC Bayern München (visitante)');
    fireEvent.keyDown(lane, { key: 'Escape' });
    expect(detail).toBeEmptyDOMElement();
    act(() => within(lane).getByTestId('rotation-gap').focus());
    expect(detail).toHaveTextContent('Su equipo jugó UCL hace 2 días. Todavía no hay evidencia suficiente para cuantificar el riesgo de rotación.');
    expect(tile).toHaveAccessibleName('Champions League ante FC Bayern München (visitante)');

    // The legend: one line with the colours and what a gold number means.
    expect(screen.getByTestId('timeline-legend')).toHaveTextContent('3d dorado = descanso corto tras Europa o copa');

    // Presentation mode: the same timeline, sized from the viewport, with the #435 gesture guard.
    act(() => { fireEvent.click(screen.getByRole('button', { name: 'Presentar' })); });
    const overlay = screen.getByLabelText('Calendario en modo presentación');
    expect(overlay).toHaveAttribute('data-no-swipe');
    const presentation = within(overlay).getByTestId('presentation-timeline');
    expect(presentation.style.getPropertyValue('--r')).toContain('100dvh');
    expect(within(presentation).getByRole('img', { name: /Champions League ante FC Bayern/ })).toHaveTextContent('BAY');
    expect(within(presentation).getByTestId('rotation-notice')).toHaveTextContent('2d');
  });

  test('the switch: on by default, remembered, and off leaves exactly the Premier-only calendar', async () => {
    mockBackend({ available: false });
    const baseline = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await act(async () => { await Promise.resolve(); });
    const premierOnly = boardRows().innerHTML;
    expect(screen.queryByRole('switch', { name: 'Otras competiciones' })).toBeNull();
    baseline.unmount();

    mockBackend(PREMIUM);
    const first = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    const toggle = await screen.findByRole('switch', { name: 'Otras competiciones' });
    expect(toggle).toBeChecked();
    expect(boardRows().innerHTML).not.toBe(premierOnly);

    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(boardRows().innerHTML).toBe(premierOnly);
    expect(screen.queryByTestId('timeline-legend')).toBeNull();
    expect(window.localStorage.getItem('fpl-fixtures-other-competitions')).toBe('0');
    first.unmount();

    // A new visit remembers the choice.
    const second = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    const remembered = await screen.findByRole('switch', { name: 'Otras competiciones' });
    await waitFor(() => expect(remembered).not.toBeChecked());
    expect(boardRows().innerHTML).toBe(premierOnly);
    fireEvent.click(remembered);
    expect(remembered).toBeChecked();
    expect(window.localStorage.getItem('fpl-fixtures-other-competitions')).toBe('1');
    second.unmount();
  });

  test('Compacto: a 12 px strip before each column with one bar per extra match, a gold dot, the detail on tap or focus', async () => {
    mockBackend({ available: false });
    const baseline = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    fireEvent.click(screen.getByRole('button', { name: 'Compacto' }));
    await act(async () => { await Promise.resolve(); });
    const premierOnly = boardRows().innerHTML;
    baseline.unmount();

    mockBackend(PREMIUM);
    render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    fireEvent.click(screen.getByRole('button', { name: 'Compacto' }));
    const gutters = await screen.findAllByTestId('compact-gutter');
    expect(gutters).toHaveLength(2);                                   // Arsenal before gameweek 2, City before gameweek 3 (relative to START)

    // 1 match -> one 16 px bar and the gold dot; 2 matches -> two stacked bars, no dot; none -> an empty strip.
    const [arsenalGutter, cityGutter] = gutters;
    expect(within(arsenalGutter).getAllByTestId('compact-bar')).toHaveLength(1);
    expect(within(arsenalGutter).getAllByTestId('compact-bar')[0]).toHaveStyle({ height: '16px', backgroundColor: 'rgb(111, 147, 255)' });
    expect(within(arsenalGutter).getByTestId('compact-rotation-dot')).toBeInTheDocument();
    expect(within(cityGutter).getAllByTestId('compact-bar')).toHaveLength(2);
    expect(within(cityGutter).getAllByTestId('compact-bar')[0]).toHaveStyle({ height: '10px' });
    expect(within(cityGutter).queryByTestId('compact-rotation-dot')).toBeNull();

    // Every row carries the same strips, so the 20 teams' columns stay aligned: 8 gutters per row.
    const rows = boardRows().querySelectorAll('div.flex.items-center.gap-1.py-\\[2px\\]');
    expect(rows.length).toBe(20);
    rows.forEach((row) => expect(row.querySelectorAll(':scope > span.contents > .w-\\[12px\\], :scope > span.contents > button.w-\\[12px\\]').length).toBe(8));

    // The legend is one line with the colours and the gold dot.
    expect(screen.getByTestId('compact-legend')).toHaveTextContent('● descanso corto tras Europa o copa');

    // Nothing is said until a bar is picked; then the detail line names the team, the match and the notice.
    expect(screen.queryByTestId('compact-detail')).toBeNull();
    fireEvent.click(arsenalGutter);
    expect(screen.getByTestId('compact-detail')).toHaveTextContent(
      'ARS · Champions League ante FC Bayern München (visitante) · Su equipo jugó UCL hace 2 días. Todavía no hay evidencia suficiente para cuantificar el riesgo de rotación.',
    );
    fireEvent.keyDown(arsenalGutter, { key: 'Escape' });
    expect(screen.queryByTestId('compact-detail')).toBeNull();
    act(() => cityGutter.focus());
    expect(screen.getByTestId('compact-detail')).toHaveTextContent('MCI · Europa League ante Real Betis (local) · Carabao Cup ante Fleetwood Town (visitante)');
    expect(arsenalGutter).toHaveAccessibleName(/^ARS · Champions League ante FC Bayern/);

    // The bar is fixed to the viewport (the card clips overflow) and closes with its own button.
    expect(screen.getByTestId('compact-detail-bar').className).toMatch(/\bfixed\b/);
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar detalle' }));
    expect(screen.queryByTestId('compact-detail')).toBeNull();

    // The switch off: the grid is the Premier-only one, byte for byte.
    fireEvent.click(screen.getByRole('switch', { name: 'Otras competiciones' }));
    expect(boardRows().innerHTML).toBe(premierOnly);
    expect(screen.queryByTestId('compact-legend')).toBeNull();
  });

  test('Compacto, free: the Premier-only grid and the locked switch, nothing else', async () => {
    mockBackend({ available: false });
    const baseline = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    fireEvent.click(screen.getByRole('button', { name: 'Compacto' }));
    await act(async () => { await Promise.resolve(); });
    const premierOnly = boardRows().innerHTML;
    baseline.unmount();

    mockBackend(FREE);
    render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await screen.findByTestId('locked-competitions-toggle');
    fireEvent.click(screen.getByRole('button', { name: 'Compacto' }));
    expect(boardRows().innerHTML).toBe(premierOnly);
    expect(screen.queryAllByTestId('compact-gutter')).toHaveLength(0);
  });

  test('free: the Premier calendar as always, and one locked switch that opens a short line', async () => {
    mockBackend({ available: false });
    const baseline = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await act(async () => { await Promise.resolve(); });
    const premierOnly = boardRows().innerHTML;
    baseline.unmount();

    mockBackend(FREE);
    const { container } = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    const locked = await screen.findByTestId('locked-competitions-toggle');

    // No gaps, no marks, no tiles: the rows are byte for byte the Premier-only board.
    expect(boardRows().innerHTML).toBe(premierOnly);
    expect(screen.queryByTestId('fixture-timeline')).toBeNull();
    expect(screen.queryByTestId('competition-tease')).toBeNull();
    expect(screen.queryByTestId('competitions-upsell')).toBeNull();

    // The one difference: a switch that is off, locked, with a lock and «Premium».
    expect(locked).toHaveAttribute('role', 'switch');
    expect(locked).toHaveAttribute('aria-checked', 'false');
    expect(locked).toHaveTextContent('Otras competiciones');
    expect(locked).toHaveTextContent('Premium');
    expect(locked).toHaveTextContent('🔒');
    expect(screen.queryByRole('switch', { name: /Otras competiciones/ })).toBe(locked);
    expect(screen.queryByTestId('locked-competitions-line')).toBeNull();

    // Tapping opens the line with the link to /subscribe; tapping again closes it. It never turns on.
    fireEvent.click(locked);
    const line = screen.getByTestId('locked-competitions-line');
    expect(line).toHaveTextContent('Ve los partidos de Champions, Europa y copas, con los días de descanso.');
    expect(within(line).getByRole('link', { name: 'Ver con Premium' })).toHaveAttribute('href', '/subscribe');
    expect(locked).toHaveAttribute('aria-expanded', 'true');
    expect(locked).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(locked);
    expect(screen.queryByTestId('locked-competitions-line')).toBeNull();

    // Nothing about the calendar is on the page, and Presentar stays the plain compact grid.
    const text = container.textContent ?? '';
    for (const leaked of ['UCL', 'UEL', 'UECL', 'Bayern', 'BAY', 'Champions', 'rotación']) {
      expect(text).not.toContain(leaked);
    }
    act(() => { fireEvent.click(screen.getByRole('button', { name: 'Presentar' })); });
    const overlay = screen.getByLabelText('Calendario en modo presentación');
    expect(within(overlay).queryByTestId('presentation-timeline')).toBeNull();
    expect(within(overlay).queryByTestId('competition-extras')).toBeNull();
    expect(window.localStorage.getItem('fpl-fixtures-other-competitions')).toBeNull();
  });

  test('failing or unavailable: the board is exactly what it was', async () => {
    mockBackend({ available: false });
    const first = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await act(async () => { await Promise.resolve(); });
    const unavailable = first.container.innerHTML;
    expect(screen.queryByTestId('fixture-timeline')).toBeNull();
    first.unmount();

    mockBackend({ available: true, tier: 'premium', teams: {} }, false);
    const second = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await act(async () => { await Promise.resolve(); });
    expect(second.container.innerHTML).toBe(unavailable);
  });

  test('Presentar: one fixed grid. The gameweek only in the header, every row the same cells, the extras in the slot before their gameweek', async () => {
    mockBackend(PREMIUM);
    render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await within(arsenal()).findByTestId('fixture-timeline');
    act(() => { fireEvent.click(screen.getByRole('button', { name: 'Presentar' })); });
    const grid = within(screen.getByLabelText('Calendario en modo presentación')).getByTestId('presentation-timeline');

    // Six gameweeks by default, one header cell each; 8 on request.
    const headers = () => within(grid).getAllByTestId('gw-header').map((h) => h.textContent);
    expect(headers()).toEqual(Array.from({ length: 6 }, (_, i) => `J${START + i}`));

    const cellsOf = (row: Element) =>
      Array.from(row.children).flatMap((child) => (child.classList.contains('contents') ? Array.from(child.children) : [child]));
    const rows = () => within(grid).getAllByTestId('presentation-row');
    expect(rows()).toHaveLength(20);
    // Team + 6 gameweek columns + a slot between each pair: the same for all 20 teams.
    for (const row of rows()) {
      expect(cellsOf(row)).toHaveLength(1 + 6 + 5);
      expect(row.textContent).not.toMatch(/J\d+/);
    }

    // ARS: the UCL tile sits in the slot between its first two columns; MCI's two matches stack in the slot before its third.
    const row = (team: string) => rows().find((r) => r.textContent?.startsWith(team))!;
    expect(within(cellsOf(row('ARS'))[2] as HTMLElement).getByRole('img', { name: /Champions League ante FC Bayern/ })).toHaveTextContent('BAY');
    expect(within(cellsOf(row('MCI'))[4] as HTMLElement).getAllByRole('img')).toHaveLength(2);
    // A team with no other competition keeps its slots empty.
    expect(within(row('COV')).queryAllByRole('img').length).toBe(6);

    act(() => { fireEvent.click(screen.getByRole('button', { name: '8 jornadas' })); });
    expect(headers()).toHaveLength(8);
    for (const r of rows()) expect(cellsOf(r)).toHaveLength(1 + 8 + 7);
  });

  test('Presentar is only offered to the owner accounts', async () => {
    mockBackend(PREMIUM);
    (globalThis as { __owner?: boolean }).__owner = false;
    try {
      render(<FixturesBoard onAsk={() => {}} />);
      await settled();
      expect(screen.queryByRole('button', { name: 'Presentar' })).toBeNull();
    } finally {
      delete (globalThis as { __owner?: boolean }).__owner;
    }
  });
});
