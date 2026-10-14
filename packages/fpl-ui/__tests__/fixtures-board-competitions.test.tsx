/**
 * @jest-environment jsdom
 *
 * The multi-competition layer of /fixtures, at both tiers.
 *
 * The backend decides the tier; these tests pin what the board does with each
 * answer: premium detail, the free tease (never a rival or a competition), and
 * nothing at all when the layer is unavailable (all production ever sees).
 * Each full-board render is expensive in jsdom, so there are few of them.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { FixturesBoard } from '@/components/intents/FixturesBoard';
import { REAL_SEASON_GENERATION } from '@/lib/fixture-outlook-real';
import { parseCompetitions, rotationText, extrasFor } from '@/lib/fixture-competitions';

jest.setTimeout(30_000);

const START = (REAL_SEASON_GENERATION?.gameweeks_played ?? 0) + 1;

const PREMIUM = {
  available: true,
  tier: 'premium',
  teams: {
    ARS: {
      matches: [
        { kickoff_utc: '2026-10-13T19:00:00Z', week: '2026-10-12', gameweek: START, competition: 'UCL',
          venue: 'H', opponent: 'LOSC Lille', rest_days_before: 3.3, rest_days_after: 4.9 },
      ],
      rotation_notices: [
        { kickoff_utc: '2026-10-18T15:30:00Z', week: '2026-10-12', gameweek: START, opponent: 'Chelsea',
          rest_whole_days: 3, previous_competition: 'UCL' },
      ],
    },
  },
};
const FREE = { available: true, tier: 'free', teams: { ARS: { extra_by_gameweek: { [String(START)]: 2 } } } };

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

describe('parseCompetitions', () => {
  test.each([
    [null], [undefined], ['x'], [{}], [{ available: false }], [{ available: true }],
    [{ available: true, tier: 'gold', teams: {} }], [{ next_gw: 5, finished_gw: 4 }],
  ])('unrecognised payload %j -> null (the board stays as it was)', (payload) => {
    expect(parseCompetitions(payload)).toBeNull();
  });

  test('premium: matches and notices land on their gameweek', () => {
    const slot = (extrasFor(parseCompetitions(PREMIUM), 'ARS') as { byGw: Map<number, any> }).byGw.get(START)!;
    expect(slot.matches[0]).toMatchObject({ competition: 'UCL', opponent: 'LOSC Lille', venue: 'H', restBefore: 3.3 });
    expect(slot.notice).toMatchObject({ restWholeDays: 3, previousCompetition: 'UCL' });
  });

  test('free: only counts per gameweek', () => {
    const view = parseCompetitions(FREE)!;
    expect(extrasFor(view, 'ARS')).toEqual({ kind: 'free', countByGw: new Map([[START, 2]]) });
  });

  test("rotation wording is Leo's", () => {
    expect(rotationText({ restWholeDays: 3, previousCompetition: 'UCL', opponent: '' }))
      .toBe('3 días de descanso tras la Champions · posible rotación');
    expect(rotationText({ restWholeDays: 1, previousCompetition: null, opponent: '' }))
      .toBe('1 día de descanso · posible rotación');
  });
});

describe('FixturesBoard multi-competition layer', () => {
  beforeEach(() => window.sessionStorage.clear());
  afterEach(() => jest.restoreAllMocks());

  test('premium: badge, rival, rest days and the rotation notice, in the detailed row and in presentation', async () => {
    mockBackend(PREMIUM);
    render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    const row = (await screen.findAllByTestId('competition-extras'))[0];
    expect(within(row).getByTestId('competition-badge')).toHaveTextContent('UCL');
    expect(row).toHaveTextContent('LOSC Lille');
    expect(row).toHaveTextContent('3d desde el anterior');
    // The presentation overlay is always mounted (hidden), so scope to the visible board.
    const board = screen.getByTestId('fixture-board-rows');
    const notice = within(board).getByTestId('rotation-notice');
    expect(notice).toHaveTextContent('3 días de descanso tras la Champions · posible rotación');
    expect(notice.getAttribute('title')).toMatch(/^Oportunidad:/);
    expect(screen.getByTestId('competitions-legend')).toBeInTheDocument();
    expect(screen.queryByTestId('competition-tease')).toBeNull();
    expect(within(board).queryAllByTestId('competition-badge')).toHaveLength(1);

    // Presentation mode shows the same facts and keeps the gesture guard of #435.
    act(() => { fireEvent.click(screen.getByRole('button', { name: 'Presentar' })); });
    const overlay = screen.getByLabelText('Calendario en modo presentación');
    expect(overlay).toHaveAttribute('data-no-swipe');
    const chip = within(overlay).getByTestId('competition-extras');
    expect(chip).toHaveTextContent('UCL');
    expect(within(overlay).getByTestId('rotation-notice')).toHaveTextContent('↻3d');
  });

  test('free: a lock mark and an upgrade link, never a rival or a competition', async () => {
    mockBackend(FREE);
    const { container } = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    const tease = (await screen.findAllByTestId('competition-tease'))[0];
    expect(tease).toHaveTextContent('🔒 +2');
    expect(tease.closest('a') ?? tease).toHaveAttribute('href', '/subscribe');
    expect(screen.getByTestId('competitions-upsell')).toHaveTextContent('Ver con Premium');
    const text = container.textContent ?? '';
    for (const leaked of ['UCL', 'UEL', 'UECL', 'Lille', 'Champions', 'rotación', 'descanso']) {
      expect(text).not.toContain(leaked);
    }
    expect(screen.queryByTestId('competition-badge')).toBeNull();
    expect(screen.queryAllByTestId('rotation-notice')).toHaveLength(0);
  });

  test('unavailable (production) or failing: the board is exactly what it was', async () => {
    mockBackend({ available: false });
    const first = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await act(async () => { await Promise.resolve(); });
    const unavailable = first.container.innerHTML;
    expect(screen.queryByTestId('competition-extras')).toBeNull();
    expect(screen.queryByTestId('competition-tease')).toBeNull();
    expect(screen.queryByTestId('competitions-legend')).toBeNull();
    expect(screen.queryByTestId('competitions-upsell')).toBeNull();
    first.unmount();

    mockBackend({ available: true, tier: 'premium', teams: {} }, false);
    const second = render(<FixturesBoard onAsk={() => {}} />);
    await settled();
    await act(async () => { await Promise.resolve(); });
    expect(second.container.innerHTML).toBe(unavailable);
  });
});
