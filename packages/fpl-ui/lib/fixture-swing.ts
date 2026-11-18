/**
 * Fixture swings — where a team's run of fixtures turns easier or harder.
 *
 * Pure and deterministic: a team's full-season series plus the live gameweek in,
 * one swing (or none) out. No React, no I18N, no side effects, so the board, the
 * chart and any later consumer read the same answer.
 *
 * The idea. The reference is how hard the team's last SWING_TRAILING played
 * gameweeks were. Looking SWING_LOOKAHEAD gameweeks ahead, the swing point is the
 * first gameweek `g` where
 *   1. the run starting at `g` (the SWING_RUN gameweeks from `g`) differs from the
 *      reference by at least SWING_THRESHOLD, and
 *   2. gameweek `g` itself already moved at least one whole band the same way.
 * Condition 2 keeps the divider on the first genuinely good or bad fixture, rather
 * than a few gameweeks early where a rolling average first crosses the threshold.
 *
 * Fixtures, not gameweeks. Every fixture weighs the same in an average, so a
 * double gameweek contributes two fixtures and a blank contributes none. A blank
 * is never the swing point. A swing needs SWING_MIN_FIXTURES fixtures behind both
 * the reference and the new run, so nothing is called on thin evidence (the last
 * gameweeks of the data, or a window that is mostly blanks).
 *
 * Doubles and blanks are NOT swings: they are volume, not difficulty, and keep
 * their own markers. They only enter here through the fixture counts above.
 */
import type { FixtureOutlookGW, TeamOutlook } from './types';

/** Gameweeks of already-played fixtures that form the reference. */
export const SWING_TRAILING = 5;
/** Gameweeks ahead of now in which a swing point is searched. */
export const SWING_LOOKAHEAD = 10;
/** Gameweeks, counted from the swing point, that make up the new run. */
export const SWING_RUN = 5;
/** Smallest average change that counts as a swing (a multiple of 0.2 in practice, so 0.5 acts as 0.6). */
export const SWING_THRESHOLD = 0.5;
/** Fewest fixtures allowed behind the reference and behind the new run. */
export const SWING_MIN_FIXTURES = 3;

export type SwingDirection = 'easier' | 'harder';

export interface Swing {
  /** First gameweek of the new run. */
  gameweek: number;
  direction: SwingDirection;
  /** Average difficulty of the trailing played fixtures. */
  reference: number;
  /** Average difficulty of the new run. */
  lead: number;
  /** lead - reference: negative = easier, positive = harder. */
  change: number;
  /** Gameweeks from `now` to the swing point; 0 = starts now. */
  inGameweeks: number;
}

/** Round half up. Math.round and Python's round() disagree on halves; this pins one meaning. */
function roundHalfUp(n: number): number {
  return Math.floor(n + 0.5);
}

function fixtureBands(gw: FixtureOutlookGW): number[] {
  return gw.fixtures.map((f) => f.band);
}

function mean(values: number[]): number {
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

/** Every fixture band in the gameweeks [from, to], in order. Gameweeks missing from the series add nothing. */
function bandsBetween(byGameweek: Map<number, FixtureOutlookGW>, from: number, to: number): number[] {
  const out: number[] = [];
  for (let g = from; g <= to; g++) {
    const entry = byGameweek.get(g);
    if (entry) out.push(...fixtureBands(entry));
  }
  return out;
}

export interface SwingOptions {
  threshold: number;
  lookahead: number;
}

/**
 * The next swing in `series`, or null when there is none in the lookahead (or not
 * enough fixtures to call one). `now` is the live gameweek: the first one not yet
 * played. The series must be the full-season one, not a window. `options` exists so
 * the threshold can be tuned against real bundles; the board uses the defaults.
 */
export function findSwing(
  series: readonly FixtureOutlookGW[],
  now: number,
  options: Partial<SwingOptions> = {},
): Swing | null {
  const threshold = options.threshold ?? SWING_THRESHOLD;
  const lookahead = options.lookahead ?? SWING_LOOKAHEAD;
  const byGameweek = new Map(series.map((gw) => [gw.gameweek, gw]));

  const trailing = bandsBetween(byGameweek, now - SWING_TRAILING, now - 1);
  if (trailing.length < SWING_MIN_FIXTURES) return null;
  const reference = mean(trailing);
  const referenceBand = roundHalfUp(reference);

  for (let g = now; g < now + lookahead; g++) {
    const entry = byGameweek.get(g);
    const own = entry ? fixtureBands(entry) : [];
    if (own.length === 0) continue; // a blank is never the swing point

    const run = bandsBetween(byGameweek, g, g + SWING_RUN - 1);
    if (run.length < SWING_MIN_FIXTURES) continue;

    const lead = mean(run);
    const change = lead - reference;
    if (Math.abs(change) < threshold - 1e-9) continue;

    const ownBand = mean(own);
    const moved = change < 0 ? ownBand <= referenceBand - 1 : ownBand >= referenceBand + 1;
    if (!moved) continue;

    return {
      gameweek: g,
      direction: change < 0 ? 'easier' : 'harder',
      reference,
      lead,
      change,
      inGameweeks: g - now,
    };
  }
  return null;
}

export type SwingGroup = 'easier' | 'stable' | 'harder';

export interface SwingEntry {
  team: TeamOutlook;
  swing: Swing | null;
  group: SwingGroup;
}

/**
 * Teams grouped easier / stable / harder, in that order. Within a swing group the
 * sooner swing comes first, then the larger change; the stable group keeps the
 * order it came in (the board's best-run order), so the middle is never arbitrary.
 *
 * `teams` is the order to preserve for stable teams; `full` supplies the whole
 * season for each team, keyed by team_short, because the swing needs more than
 * the visible window.
 */
export function orderBySwing(
  teams: readonly TeamOutlook[],
  full: ReadonlyMap<string, readonly FixtureOutlookGW[]>,
  now: number,
): SwingEntry[] {
  const entries: SwingEntry[] = teams.map((team) => {
    const swing = findSwing(full.get(team.team_short) ?? team.series, now);
    const group: SwingGroup = swing ? (swing.direction === 'easier' ? 'easier' : 'harder') : 'stable';
    return { team, swing, group };
  });
  const rank = (e: SwingEntry): number => (e.group === 'easier' ? 0 : e.group === 'stable' ? 1 : 2);
  const original = new Map(entries.map((e, i) => [e, i]));
  return [...entries].sort((a, b) => {
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    if (a.swing && b.swing) {
      return (
        a.swing.gameweek - b.swing.gameweek ||
        Math.abs(b.swing.change) - Math.abs(a.swing.change) ||
        (original.get(a) as number) - (original.get(b) as number)
      );
    }
    return (original.get(a) as number) - (original.get(b) as number);
  });
}
