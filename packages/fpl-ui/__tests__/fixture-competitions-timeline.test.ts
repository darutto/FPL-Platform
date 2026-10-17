/**
 * The timeline model (lib/fixture-competitions): date order, the rest shown in each gap,
 * the gold notice, and the free ghost tile. Pure data, no rendering.
 */
import {
  buildTimeline,
  compactGutter,
  extraSentence,
  gutterSentence,
  parseCompetitions,
} from '@/lib/fixture-competitions';
import type { FixtureOutlookGW } from '@/lib/types';

const gw = (gameweek: number, opponent = 'XXX', band: number | null = 3): FixtureOutlookGW => ({
  gameweek,
  band,
  klass: 'neutral',
  is_dgw: false,
  is_bgw: band === null,
  fixtures: band === null ? [] : [{ opponent_short: opponent, is_home: true, band }],
});

const pl = (gameweek: number, kickoff: string, rest: number | null, rotation = false, prev: string | null = null) => ({
  kickoff_utc: kickoff, week: 'w', gameweek, venue: 'H', opponent: `Rival ${gameweek}`, opponent_code: 'RIV',
  rest_whole_days_before: rest, previous_competition: prev, rotation,
});
const extra = (gameweek: number | null, kickoff: string, rest: number | null, competition = 'UCL') => ({
  kickoff_utc: kickoff, week: 'w', gameweek, competition, venue: 'A', opponent: 'Sturm Graz', opponent_code: 'STU',
  rest_whole_days_before: rest, rest_days_before: rest, rest_days_after: null, previous_competition: 'PL',
});

function premium(matches: unknown[], plMatches: unknown[]) {
  const view = parseCompetitions({ available: true, tier: 'premium', teams: { ARS: { matches, pl_matches: plMatches } } });
  return view!.teams.get('ARS')!;
}

const keys = (items: ReturnType<typeof buildTimeline>) => items.map((i) => i.key.replace(/^extra-\d+-/, 'x-'));

describe('buildTimeline (premium)', () => {
  const series = [gw(7), gw(8), gw(9)];

  test('real date order: an extra match lands between the Premier League tiles by its kickoff', () => {
    const team = premium(
      [extra(8, '2026-10-21T19:00:00Z', 3), extra(9, '2026-10-27T20:00:00Z', 3, 'EFL')],
      [pl(7, '2026-10-18T15:30:00Z', 4), pl(8, '2026-10-24T14:00:00Z', 2, true, 'UCL'), pl(9, '2026-11-01T16:30:00Z', 4)],
    );
    expect(keys(buildTimeline(series, team))).toEqual([
      'pl-7', 'x-2026-10-21T19:00:00Z', 'pl-8', 'x-2026-10-27T20:00:00Z', 'pl-9',
    ]);
  });

  test('a midweek match of the same gameweek that comes AFTER its Premier League match stays after it', () => {
    const team = premium(
      [extra(7, '2026-10-20T19:00:00Z', 2)],
      [pl(7, '2026-10-18T15:30:00Z', 4), pl(8, '2026-10-24T14:00:00Z', 4)],
    );
    expect(keys(buildTimeline([gw(7), gw(8)], team))).toEqual(['pl-7', 'x-2026-10-20T19:00:00Z', 'pl-8']);
  });

  test('the number in each gap is the whole rest days of the match that follows it; the first tile has none', () => {
    const team = premium(
      [extra(8, '2026-10-21T19:00:00Z', 3)],
      [pl(7, '2026-10-18T15:30:00Z', 6), pl(8, '2026-10-24T14:00:00Z', 2, true, 'UCL')],
    );
    const items = buildTimeline([gw(7), gw(8)], team);
    expect(items.map((i) => i.gap?.days ?? null)).toEqual([null, 3, 2]);
  });

  test('only the Premier League match flagged by the server gets the gold number', () => {
    const team = premium(
      [extra(8, '2026-10-21T19:00:00Z', 1)],     // 1 day after a PL match: grey, never gold (it is not a PL match)
      [pl(7, '2026-10-18T15:30:00Z', 6), pl(8, '2026-10-24T14:00:00Z', 2, true, 'UCL'), pl(9, '2026-10-31T14:00:00Z', 2, false, 'PL')],
    );
    const gold = buildTimeline([gw(7), gw(8), gw(9)], team).flatMap((i) => (i.gap ? [i.gap.rotation] : []));
    expect(gold).toEqual([false, true, false]);
  });

  test('the phrases: tile -> "competition ante rival (local/visitante)", gold -> rest before the Premier League rival', () => {
    const team = premium(
      [extra(8, '2026-10-21T19:00:00Z', 3, 'UEL')],
      [pl(7, '2026-10-18T15:30:00Z', 6), pl(8, '2026-10-24T14:00:00Z', 2, true, 'UEL')],
    );
    const items = buildTimeline([gw(7), gw(8)], team);
    const tile = items.find((i) => i.kind === 'extra');
    if (tile?.kind !== 'extra') throw new Error('no extra tile');
    expect(tile.sentence).toBe('Europa League ante Sturm Graz (visitante)');
    expect(extraSentence(tile.match)).toBe(tile.sentence);
    const goldGap = items.flatMap((i) => (i.kind === 'pl' && i.gap?.rotation ? [i.gap] : []))[0];
    expect(goldGap.sentence).toBe('2 días de descanso antes de Rival 8: posible rotación');
  });

  test('matches outside the visible window, or with no gameweek, do not appear', () => {
    const team = premium(
      [extra(12, '2026-11-24T20:00:00Z', 3), extra(null, '2027-06-01T20:00:00Z', 3)],
      [pl(7, '2026-10-18T15:30:00Z', 4)],
    );
    expect(keys(buildTimeline([gw(7)], team))).toEqual(['pl-7']);
  });

  test('a blank gameweek keeps its place after the previous tile', () => {
    const team = premium([], [pl(7, '2026-10-18T15:30:00Z', 4), pl(9, '2026-11-01T16:30:00Z', 14)]);
    expect(keys(buildTimeline([gw(7), gw(8, 'XXX', null), gw(9)], team))).toEqual(['pl-7', 'pl-8', 'pl-9']);
  });
});

describe('parseCompetitions (free)', () => {
  test('free is only "locked": a view with no teams, whatever else the answer carried', () => {
    for (const payload of [
      { available: true, tier: 'free' },
      { available: true, tier: 'free', teams: { ARS: { extra_by_gameweek: { '8': 2 }, matches: [{ opponent: 'X' }] } } },
    ]) {
      const view = parseCompetitions(payload)!;
      expect(view.tier).toBe('free');
      expect(view.teams.size).toBe(0);
    }
  });

  test('premium without a teams object is not a layer', () => {
    expect(parseCompetitions({ available: true, tier: 'premium' })).toBeNull();
  });
});

describe('compactGutter (the strip before a gameweek column in Compacto)', () => {
  const team = premium(
    [
      extra(8, '2026-10-21T19:00:00Z', 3),                 // one match before gameweek 8
      extra(9, '2026-10-27T20:00:00Z', 3, 'EFL'),           // two before gameweek 9, given out of order
      extra(9, '2026-10-26T20:00:00Z', 3, 'UEL'),
    ],
    [
      pl(7, '2026-10-18T15:30:00Z', 4),
      pl(8, '2026-10-24T14:00:00Z', 2, true, 'UCL'),
      pl(9, '2026-11-01T16:30:00Z', 4, false, 'EFL'),
      pl(10, '2026-11-07T15:00:00Z', 6),
    ],
  );

  test('0, 1 and 2 matches: the bars are the matches of that gameweek, in kickoff order', () => {
    expect(compactGutter(team, 7).matches).toEqual([]);
    expect(compactGutter(team, 8).matches.map((m) => m.competition)).toEqual(['UCL']);
    expect(compactGutter(team, 9).matches.map((m) => m.competition)).toEqual(['UEL', 'EFL']);
    expect(compactGutter(team, 10).matches).toEqual([]);
    expect(compactGutter(null, 8)).toEqual({ matches: [], rotation: null });
  });

  test('the gold dot is the server-flagged Premier League match of that gameweek, and only under a bar', () => {
    expect(compactGutter(team, 8).rotation?.opponent).toBe('Rival 8');
    expect(compactGutter(team, 9).rotation).toBeNull();     // matches but no notice
    expect(compactGutter(team, 7).rotation).toBeNull();     // no matches: nothing to hang a dot on
  });

  test('the detail line names the team, each match, and the rotation clause when there is one', () => {
    expect(gutterSentence('ARS', compactGutter(team, 8))).toBe(
      'ARS · Champions League ante Sturm Graz (visitante) · 2 días de descanso antes de Rival 8: posible rotación',
    );
    expect(gutterSentence('ARS', compactGutter(team, 9))).toBe(
      'ARS · Europa League ante Sturm Graz (visitante) · Carabao Cup ante Sturm Graz (visitante)',
    );
  });
});

test.each([
  [null], [undefined], ['x'], [{}], [{ available: false }], [{ available: true }],
  [{ available: true, tier: 'gold', teams: {} }], [{ next_gw: 5, finished_gw: 4 }],
])('unrecognised payload %j -> null (the board stays as it was)', (payload) => {
  expect(parseCompetitions(payload)).toBeNull();
});
