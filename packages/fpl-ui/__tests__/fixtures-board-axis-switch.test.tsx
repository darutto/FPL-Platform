/**
 * @jest-environment jsdom
 *
 * The Ataque / Portería a cero switcher, pressed the way a reader presses it.
 *
 * This is the test that would have caught the shipped bug, and it is worth
 * being precise about why nothing else did. The switcher was never broken:
 * `axis` and `horizon` are sibling useState values feeding one useMemo, and
 * `buildRealSeasonOutlook` really does index REAL_SEASON_DATA[axis][horizon].
 * The bundle behind it had both axes banded from the same signal, so the
 * component re-rendered identical rows, correctly.
 *
 * Every existing test passed throughout. fixture-outlook-real.test.ts loops
 * over both axes and asserts invariants WITHIN each one — 20 teams, bands in
 * 1..5, real opponent codes — and never compares one axis to the other. An
 * invariant that holds separately on two identical things cannot notice that
 * they are identical.
 *
 * So: render, click, and compare the output to itself.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import { FixturesBoard } from '@/components/intents/FixturesBoard';
import { REAL_SEASON_GENERATION } from '@/lib/fixture-outlook-real';
import { REAL_SEASON_HORIZONS } from '@/lib/fixture-outlook-real';

// Rendering the full board is 20 teams x up to 10 cells in jsdom, so these are
// slower than the 5s default. Raising the budget changes nothing about what is
// checked.
jest.setTimeout(30_000);

/**
 * fireEvent, not userEvent, and deliberately.
 *
 * userEvent simulates a full pointer sequence (hover, down, up, focus) against
 * every element under the cursor. Over a 200-cell grid that took ~120s for this
 * file and starved unrelated suites of CPU until they timed out -- a test file
 * that breaks its neighbours is a broken test file. These assertions are about
 * a click flipping state and the board re-rendering different data, which
 * fireEvent exercises exactly.
 */
const click = (el: HTMLElement) => act(() => { fireEvent.click(el); });

function mockFixtureStatus(payload: {
  next_gw: number | null;
  finished_gw: number | null;
}) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => payload,
  }) as unknown as typeof fetch;
}

/**
 * The DIFFICULTY the board is showing — not its prose.
 *
 * Worth spelling out, because the first version of this test compared the
 * rows' textContent and passed at horizons 5 and 8 against the known-collapsed
 * bundle. It was picking up two teams (FUL, BRE) whose verdict SENTENCE
 * differs while every band is identical. A green test that proves nothing is
 * worse than no test, so this reads the numbers that paint the grid:
 * each cell's FDR band, via the title text the cell already exposes for
 * accessibility, plus each team's average pill.
 */
function bandGrid(): string {
  const rows = screen.getByTestId('fixture-board-rows');
  const cells = Array.from(rows.querySelectorAll('[title]'))
    .map((el) => el.getAttribute('title') ?? '')
    .filter((title) => title.includes('FDR '));
  if (cells.length === 0) throw new Error('no FDR cells rendered — selector is stale');
  return cells.join('|');
}

/** Every team's "Prom X.X" average — the exact figure the diagnosis counted. */
function averages(): string {
  const rows = screen.getByTestId('fixture-board-rows');
  return Array.from(rows.querySelectorAll('*'))
    .map((el) => el.textContent ?? '')
    .filter((text) => /^Prom \d/.test(text))
    .join('|');
}

const attackButton = () => screen.getByRole('button', { name: 'Ataque' });
const defenceButton = () => screen.getByRole('button', { name: /Porter/ });

/** The gameweek the board should settle on once the live lookup lands. */
const expectedStart = (REAL_SEASON_GENERATION?.gameweeks_played ?? 0) + 1;

/**
 * Wait for the live-gameweek fetch to land before measuring anything.
 *
 * Without this the first bandGrid() is captured while the board is still
 * showing its offline fallback window, and the async setState then shifts it
 * underneath the test — which looks exactly like the axis having changed the
 * grid. Waiting on the window pill also asserts the board honours the live
 * `next_gw` rather than the bundle's first gameweek.
 */
async function settled() {
  await waitFor(() =>
    expect(screen.getByText(/^J\d+–J\d+$/).textContent).toMatch(
      new RegExp(`^J${expectedStart}–`),
    ),
  );
}

describe('the axis switcher changes what is on screen', () => {
  beforeEach(() => {
    // Pin the live yardstick to the bundle so the staleness branch stays out
    // of the way; these tests are about the rows, not the stamp.
    mockFixtureStatus({
      next_gw: expectedStart,
      finished_gw: REAL_SEASON_GENERATION?.gameweeks_played ?? 0,
    });
    window.sessionStorage.clear();
  });

  afterEach(() => jest.restoreAllMocks());

  /**
   * One render, one horizon.
   *
   * Mounting the full 20-team board is by far the most expensive thing in this
   * package's suite: an earlier version of this file walked all three horizons
   * through the DOM, took ~126s, and starved unrelated suites of CPU until they
   * timed out. A test file that breaks its neighbours is a broken test file.
   *
   * It was also redundant. Whether the two axes differ AT EACH HORIZON is
   * asserted directly on the data in fixture-outlook-real.test.ts, against all
   * three, by the same measurement the diagnosis used. What only the DOM can
   * tell us is whether pressing the button actually reaches the grid — and one
   * horizon proves that.
   *
   * Horizon 5 is the one worth spending the render on: on the collapsed bundle
   * it was where the switcher changed nothing whatsoever, not even a verdict
   * string.
   */
  test('pressing the switcher changes the grid the reader sees', async () => {
    render(<FixturesBoard onAsk={() => {}} />);
    // Settle the live-gameweek lookup FIRST. If it lands mid-test it shifts
    // the visible window, and two grids would differ because the gameweeks
    // moved rather than because the axis did.
    await settled();

    click(screen.getByRole('button', { name: '5' }));

    click(attackButton());
    const attackBands = bandGrid();
    const attackAverages = averages();
    expect(attackBands.length).toBeGreaterThan(0);
    expect(attackAverages.length).toBeGreaterThan(0);

    click(defenceButton());
    expect(defenceButton()).toHaveAttribute('aria-pressed', 'true');

    if (REAL_SEASON_GENERATION?.gameweeks_played === 0) {
      // A launch-day bundle has both axes on FDR by construction, so identical
      // grids are CORRECT here and must not fail. What the reader is owed in
      // that state is being told, which is the stamp's job -- so assert that
      // instead of asserting a difference that should not exist yet.
      expect(bandGrid()).toBe(attackBands);
      expect(screen.getByTestId('fixture-provenance')).toHaveAttribute(
        'data-status',
        'season_start',
      );
      expect(screen.getByTestId('fixture-provenance-warning')).toBeInTheDocument();
    } else {
      expect(bandGrid()).not.toBe(attackBands);
      expect(averages()).not.toBe(attackAverages);
    }

    // And back: the switch is a view over data, not a one-way mutation of it.
    // True in both states above.
    click(attackButton());
    expect(bandGrid()).toBe(attackBands);
    expect(attackButton()).toHaveAttribute('aria-pressed', 'true');
    expect(defenceButton()).toHaveAttribute('aria-pressed', 'false');
  });
});

describe('the provenance stamp', () => {
  afterEach(() => jest.restoreAllMocks());

  test('names the season and how much of it stands behind the difficulty', () => {
    mockFixtureStatus({ next_gw: null, finished_gw: null });
    render(<FixturesBoard onAsk={() => {}} />);

    const stamp = screen.getByTestId('fixture-provenance');
    const gen = REAL_SEASON_GENERATION;
    expect(gen).not.toBeNull();
    expect(stamp).toHaveTextContent(gen!.season_label);
    if (gen!.gameweeks_played > 0) {
      expect(stamp).toHaveTextContent(String(gen!.gameweeks_played));
    }
  });

  test('feeds the LIVE gameweek count into the stamp, not the bundle\'s own', async () => {
    // The comparison that makes the stamp more than a restatement of itself:
    // the number comes from the live FPL bootstrap, not from the file. This
    // test owns the WIRING; which caveat wins is the provenance module's own
    // unit test (collapsed axes deliberately outrank staleness, because that
    // is the one the reader can see on screen).
    mockFixtureStatus({ next_gw: 38, finished_gw: 37 });
    render(<FixturesBoard onAsk={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTestId('fixture-provenance-warning')).toBeInTheDocument();
    });
    const stamp = screen.getByTestId('fixture-provenance');
    expect(stamp).not.toHaveAttribute('data-status', 'current');

    if (REAL_SEASON_GENERATION?.axes_separated) {
      expect(stamp).toHaveAttribute('data-status', 'stale_gameweeks');
      // 37 appears nowhere in the bundle -- it can only have come from the
      // mocked live lookup.
      expect(screen.getByTestId('fixture-provenance-warning')).toHaveTextContent('37');
    } else {
      // Collapsed axes outrank staleness by design.
      expect(['season_start', 'axes_collapsed']).toContain(
        stamp.getAttribute('data-status'),
      );
    }
  });

  test('a failed live lookup degrades quietly instead of crying stale', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    render(<FixturesBoard onAsk={() => {}} />);

    // Not knowing how far the league has got is not evidence of staleness.
    expect(screen.getByTestId('fixture-provenance')).not.toHaveAttribute(
      'data-status',
      'stale_gameweeks',
    );
  });
});

describe('the FDR caption follows the window', () => {
  afterEach(() => jest.restoreAllMocks());

  test('it tracks the visible gameweeks rather than a hardcoded J1', async () => {
    mockFixtureStatus({ next_gw: 1, finished_gw: 0 });
    render(<FixturesBoard onAsk={() => {}} />);

    const caption = () => screen.getByText(/FDR promedio/).textContent ?? '';
    const before = caption();

    click(screen.getByRole('button', { name: 'Jornada siguiente' }));

    expect(caption()).not.toBe(before);
    // The navigation pill was always right; the caption must now agree with it.
    const pill = screen.getByText(/^J\d+–J\d+$/).textContent ?? '';
    expect(caption()).toContain(pill);
  });
});
