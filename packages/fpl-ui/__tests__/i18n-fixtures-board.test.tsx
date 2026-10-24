/**
 * @jest-environment jsdom
 *
 * S4b, the rendered half: the /fixtures board and the in-chat fixture card in both languages.
 *
 *   - "Spanish" tests snapshot the distinct texts and tooltips the surface shows. Those snapshots were
 *     recorded against the code as it was BEFORE the dictionary (origin/main), so a pass means the Spanish
 *     screen did not change by one character.
 *   - "English" tests assert that no Spanish UI word is left anywhere on screen (text, titles, aria-labels),
 *     that the questions a tap hands to the chat are English, and snapshot the English texts.
 *
 * Numbers and club codes are folded in the snapshots (digits -> N, ARS -> XXX) so they hold still as the
 * season moves. Text that comes from the payload itself (club names, opponents) is not translated.
 */
// The owner-only "Presentar" switch reads the Clerk session; these tests render the board without one.
jest.mock('@/lib/presentation-access', () => ({
  usePresentationAccess: () => true,
}));

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import FixtureOutlookCard from '@/components/intents/FixtureOutlookCard';
import { FixturesBoard } from '@/components/intents/FixturesBoard';
import { fixtureOutlookWindow } from '@/lib/fixture-gameweek-navigation';
import { buildRealSeasonOutlook, REAL_SEASON_GENERATION } from '@/lib/fixture-outlook-real';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';

jest.setTimeout(90_000);

const START = (REAL_SEASON_GENERATION?.gameweeks_played ?? 0) + 1;

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
const FREE = { available: true, tier: 'free' };

function mockBackend(competitions: unknown) {
  global.fetch = jest.fn(async (url: RequestInfo | URL) => {
    if (String(url).includes('fpl-fixture-competitions')) return { ok: true, json: async () => competitions } as Response;
    return {
      ok: true,
      json: async () => ({ next_gw: START, finished_gw: REAL_SEASON_GENERATION?.gameweeks_played ?? 0 }),
    } as Response;
  }) as unknown as typeof fetch;
}

/**
 * Every distinct text, plus every title and aria-label, of what is on screen. The text of an element is its own
 * text nodes joined, so how JSX happens to split a sentence into nodes ("J" + "7" or "J7") does not show.
 */
function onScreen(root: HTMLElement): string[] {
  const out = new Set<string>();
  const elements = [root, ...Array.from(root.querySelectorAll('*'))];
  for (const el of elements) {
    const own = Array.from(el.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent ?? '')
      .join('')
      .replace(/\s+/g, ' ')
      .trim();
    if (own) out.add(own);
    for (const attr of ['title', 'aria-label']) {
      const v = el.getAttribute(attr);
      if (v) out.add(`[${attr}] ${v}`);
    }
  }
  return [...out];
}

/** The same, with numbers and club codes folded, sorted: the shape of the screen, stable across the season. */
const shape = (root: HTMLElement): string[] =>
  [...new Set(onScreen(root).map((s) => s.replace(/\b(?!FDR\b)[A-Z]{3}\b/g, 'XXX').replace(/\d+(\.\d+)?/g, 'N')))].sort();

/** Spanish interface words that must not survive in the English screen. */
const SPANISH_UI =
  /\b(jornadas?|ataque|porter[ií]a|detallado|compacto|tendencia|visitante|local|racha|calendario|promedio|f[aá]cil|dif[ií]cil|presentar|nota|puesto|partido|doble|equipo|salir|cerrar|preguntar|dificultad|mejor|orden|competiciones|temporada|dorado|descanso|tras|muestra|copas|ve los)\b/i;

function board(locale: Locale, onAsk = jest.fn()) {
  const view = render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
      <FixturesBoard onAsk={onAsk} />
    </LocaleProvider>,
  );
  return { ...view, onAsk };
}

const settled = (pattern: RegExp) => waitFor(() => expect(screen.getByText(pattern)).toBeInTheDocument());

describe('the /fixtures board', () => {
  test('Spanish: the screen is what it was before the dictionary', async () => {
    mockBackend({ available: false });
    const { container } = board('es');
    await settled(/^J\d+–J\d+$/);
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: nothing Spanish is left, and the controls speak English', async () => {
    mockBackend({ available: false });
    const { container } = board('en');
    await settled(/^GW\d+–GW\d+$/);
    const strings = onScreen(container);
    expect(strings.filter((s) => SPANISH_UI.test(s))).toEqual([]);
    for (const expected of [
      'Attack', 'Clean sheet', 'Gameweeks', 'Detailed', 'Compact', 'Trend', 'Present', 'League · ordered by fixtures',
      '[aria-label] Browse gameweeks', '[aria-label] Previous gameweek', '[aria-label] Next gameweek',
      '1 · Easy', '5 · Very hard', 'Home', 'Away', 'Favourable run', 'Hard run (3+)',
      '[aria-label] Fixtures in presentation mode', 'FDR fixtures', 'Gameweeks to show', '6 gameweeks', '8 gameweeks', 'Exit',
    ]) {
      expect(strings.some((s) => s.includes(expected))).toBe(true);
    }
    expect(strings.some((s) => /^Best fixtures first · average FDR GW\d+–GW\d+$/.test(s))).toBe(true);
    expect(strings.some((s) => /^⚠ /.test(s))).toBe(true); // the data warning is there, in English (checked above)
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: a tapped team or cell hands an English question to the chat', async () => {
    mockBackend({ available: false });
    const { container, onAsk } = board('en');
    await settled(/^GW\d+–GW\d+$/);
    const rows = within(screen.getByTestId('fixture-board-rows'));

    fireEvent.click(container.querySelector('[data-testid="team-header"] button') as HTMLElement);
    expect(onAsk).toHaveBeenLastCalledWith(expect.stringMatching(/^How does .+'s attacking fixture run look over the next gameweeks\?$/));

    fireEvent.click(rows.getAllByTitle(/^GW\d+ · .+ · FDR \d/)[0]);
    expect(onAsk).toHaveBeenLastCalledWith(
      expect.stringMatching(/^.+ vs [A-Z]{3} \((at home|away)\)(?: and .+ vs [A-Z]{3} \((at home|away)\))?, GW\d+(?: \(double gameweek\))?: how do they look attacking and defensively for .+\?$/),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Clean sheet' }));
    fireEvent.click(container.querySelector('[data-testid="team-header"] button') as HTMLElement);
    expect(onAsk).toHaveBeenLastCalledWith(expect.stringMatching(/^How good is .+'s fixture run for clean sheets coming up\?$/));
  });

  test('English: the compact grid and the tendency chart', async () => {
    mockBackend({ available: false });
    const { container, onAsk } = board('en');
    await settled(/^GW\d+–GW\d+$/);

    fireEvent.click(screen.getByRole('button', { name: 'Compact' }));
    await waitFor(() => expect(container.querySelector('.fx-compact')).not.toBeNull());
    const compact = onScreen(container);
    expect(compact.filter((s) => SPANISH_UI.test(s))).toEqual([]);
    expect(compact).toContain('TEAM');
    expect(compact.some((s) => /^\[aria-label\] rank \d+$/.test(s))).toBe(true);
    expect(compact.some((s) => /^\[title\] .+ - ask in chat$/.test(s))).toBe(true);
    expect(compact.some((s) => /^\[title\] .+ · difficulty \d - ask in chat$/.test(s))).toBe(true);
    fireEvent.click(container.querySelector('.fx-cell') as HTMLElement);
    expect(onAsk).toHaveBeenLastCalledWith(expect.stringMatching(/how do they look attacking and defensively/));

    fireEvent.click(screen.getByRole('button', { name: 'Trend' }));
    await waitFor(() => expect(container.querySelector('[data-testid="fixture-tendency-chart"]')).not.toBeNull());
    const trend = onScreen(container);
    expect(trend.filter((s) => SPANISH_UI.test(s))).toEqual([]);
    expect(trend.some((s) => /^GW\d+ · [HA]$/.test(s) || /^GW\d+$/.test(s))).toBe(true);
    expect(trend.some((s) => /^\[title\] .+ · ask in chat$/.test(s))).toBe(true);
  });

  test('English: the premium competitions layer reads in English', async () => {
    mockBackend(PREMIUM);
    const { container } = board('en');
    await settled(/^GW\d+–GW\d+$/);
    await settled(/^Other competitions$/);
    const strings = onScreen(container);
    expect(strings.filter((s) => SPANISH_UI.test(s))).toEqual([]);
    expect(strings).toContain('[aria-label] Champions League vs FC Bayern München (away)');
    expect(strings.some((s) => /^[0-9]+ days? after UCL$/.test(s.replace('[aria-label] ', '')))).toBe(true);
    expect(strings.some((s) => /^The team played UCL \d+ days? ago\. There is not yet enough evidence to size the rotation risk\.$/.test(s))).toBe(true);
    for (const expected of ['3d gold = short rest after Europe or a cup', 'Cups', '3d gold = short rest', 'favourable run']) {
      expect(strings.some((s) => s.includes(expected))).toBe(true);
    }
  });

  test('Spanish: the premium competitions layer is what it was', async () => {
    mockBackend(PREMIUM);
    const { container } = board('es');
    await settled(/^J\d+–J\d+$/);
    await settled(/^Otras competiciones$/);
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: the locked switch for Free and Tribuna', async () => {
    mockBackend(FREE);
    board('en');
    await settled(/^GW\d+–GW\d+$/);
    const toggle = await screen.findByTestId('locked-competitions-toggle');
    expect(toggle).toHaveTextContent('Other competitions');
    expect(toggle).toHaveTextContent('Premium');
    fireEvent.click(toggle);
    const line = screen.getByTestId('locked-competitions-line');
    expect(line).toHaveTextContent('See the Champions League, Europa League and cup fixtures, with the days of rest.');
    expect(within(line).getByRole('link')).toHaveTextContent('See with Premium');
  });

  test('Spanish: the locked switch is what it was', async () => {
    mockBackend(FREE);
    board('es');
    await settled(/^J\d+–J\d+$/);
    const toggle = await screen.findByTestId('locked-competitions-toggle');
    expect(toggle).toHaveTextContent('Otras competiciones');
    fireEvent.click(toggle);
    const line = screen.getByTestId('locked-competitions-line');
    expect(line).toHaveTextContent('Ve los partidos de Champions, Europa y copas, con los días de descanso.');
    expect(within(line).getByRole('link')).toHaveTextContent('Ver con Premium');
  });
});

describe('the in-chat fixture card', () => {
  const data = () => {
    const window = fixtureOutlookWindow(buildRealSeasonOutlook('attack'), START, 5);
    return { ...window, teams: window.teams.slice(0, 2) };
  };
  const card = (locale: Locale) =>
    render(
      <LocaleProvider initialLocale={locale} canSwitch={false}>
        <FixtureOutlookCard data={data()} />
      </LocaleProvider>,
    );

  test('Spanish: the card is what it was', () => {
    const { container } = card('es');
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: the card reads in English, verdicts included', () => {
    const { container } = card('en');
    const strings = onScreen(container);
    expect(strings.filter((s) => SPANISH_UI.test(s))).toEqual([]);
    expect(strings).toContain('Fixtures');
    expect(strings).toContain('Attack');
    expect(strings.some((s) => /^Avg \d\.\d$/.test(s))).toBe(true);
    expect(strings.some((s) => /GW\d+/.test(s))).toBe(true);
    expect(shape(container)).toMatchSnapshot();
  });
});
