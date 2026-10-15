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
  },
};
const FREE = { available: true, tier: 'free', teams: { ARS: { extra_by_gameweek: { [String(START + 1)]: 2 } } } };

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

    // No sentence in any cell: the detail line is empty until something is picked.
    const detail = within(lane).getByTestId('competition-detail');
    expect(detail).toBeEmptyDOMElement();

    // Tap a tile: the full phrase. Keyboard focus does the same; Escape closes it.
    fireEvent.click(tile);
    expect(detail).toHaveTextContent('Champions League ante FC Bayern München (visitante)');
    fireEvent.keyDown(lane, { key: 'Escape' });
    expect(detail).toBeEmptyDOMElement();
    act(() => within(lane).getByTestId('rotation-gap').focus());
    expect(detail).toHaveTextContent('2 días de descanso antes de Everton: posible rotación');
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

  test('free: a grey ghost tile with a lock, dropped like the premium ones; never a rival or a competition', async () => {
    mockBackend(FREE);
    const { container } = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    const lane = await within(arsenal()).findByTestId('fixture-timeline');
    const ghost = within(lane).getByTestId('competition-tease');
    expect(ghost).toHaveTextContent('+2');
    expect(ghost).toHaveAttribute('href', '/subscribe');
    expect(ghost).toHaveAccessibleName('2 partidos más esta semana · Ver con Premium');
    expect(screen.getByTestId('competitions-upsell')).toHaveTextContent('Ver con Premium');
    const text = container.textContent ?? '';
    for (const leaked of ['UCL', 'UEL', 'UECL', 'Bayern', 'BAY', 'Champions', 'rotación', 'descanso']) {
      expect(text).not.toContain(leaked);
    }
    expect(within(lane).queryByTestId('competition-tile')).toBeNull();
    expect(within(lane).queryByTestId('rotation-notice')).toBeNull();
    expect(within(lane).queryByTestId('rest-days')).toBeNull();
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
});
