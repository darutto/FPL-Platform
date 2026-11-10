/**
 * The player card's fixture strip. Pure, no I/O. Same rules as the /fixtures calendar
 * (Leo, 2026-11-09: the calendar leads).
 *
 * - Every plan: our fixture-outlook band on each Premier League cell, on the player's axis
 *   (FWD/MID attack, DEF/GKP defence). With no band, the cell keeps FPL's FDR.
 * - Premium only: Europe and cup matches as their own cells, before the gameweek they
 *   precede, and the short-rest notice on the Premier League match that follows them.
 *
 * The BACKEND decides the tier (via /fixtures/competitions). This file never gates: the
 * caller passes the team's extras only when the answer was premium.
 */
import type { FixtureAxis, FixtureEntry, FixtureOutlookGW } from './types';
import type { Band } from './fixture-outlook-format';
import type { TeamExtras } from './fixture-competitions';

/**
 * Which outlook axis a player reads. Goes by FPL position for now: DEF/GKP read the
 * clean-sheet axis, everyone else attack. Leo decided a defensive MID reads defence and
 * an attacking wing-back reads attack; that rule needs the observed role and is not built yet.
 */
export function stripAxis(position: string): FixtureAxis {
  const code = position.trim().toUpperCase();
  return code === 'DEF' || code === 'GKP' || code === 'GK' ? 'defence' : 'attack';
}

export interface StripRest {
  /** Whole days since the previous match. */
  days: number;
  /** The competition played before it (e.g. 'UEL'). */
  competition: string;
}

export interface StripPlCell {
  kind: 'pl';
  key: string;
  gameweek: number;
  opponent: string;
  isHome: boolean;
  /** FPL's FDR, always present: the fallback when there is no band. */
  fdr: 1 | 2 | 3 | 4 | 5;
  /** Our band on the player's axis, or null (the cell then shows the FDR). */
  band: Band | null;
  /** Short rest after a European or cup match (server-decided), or null. */
  rest: StripRest | null;
}

export interface StripExtraCell {
  kind: 'extra';
  key: string;
  /** The Premier League gameweek this match precedes. */
  gameweek: number;
  competition: string;
  opponentCode: string;
  opponent: string;
  venue: 'H' | 'A';
  kickoff: string;
}

export type StripCell = StripPlCell | StripExtraCell;

const asBand = (v: number | null | undefined): Band | null =>
  typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= 5 ? (v as Band) : null;

/** The band of one fixture: its own cell's band in a double gameweek, the gameweek's band otherwise. */
export function bandFor(entry: FixtureEntry, series: FixtureOutlookGW[] | null): Band | null {
  if (!series) return null;
  const gw = series.find((g) => g.gameweek === entry.gameweek);
  if (!gw || gw.band === null) return null;
  const cell = gw.fixtures.find((f) => f.opponent_short === entry.opponent_short && f.is_home === entry.is_home);
  if (cell) return asBand(cell.band);
  // The bundle and FPL disagree on this fixture: no band rather than someone else's.
  return null;
}

function restFor(entry: FixtureEntry, extras: TeamExtras | null): StripRest | null {
  if (!extras) return null;
  const sameGw = extras.plMatches.filter((m) => m.gameweek === entry.gameweek);
  const venue = entry.is_home ? 'H' : 'A';
  const match =
    sameGw.find((m) => m.opponentCode === entry.opponent_short && m.venue === venue) ??
    (sameGw.length === 1 ? sameGw[0] : undefined);
  if (!match || !match.rotation || match.restWholeDays === null || !match.previousCompetition) return null;
  return { days: match.restWholeDays, competition: match.previousCompetition };
}

/**
 * The strip: Premier League cells with their band, plus (when `extras` is given, i.e. Premium)
 * other competitions in date order between them and the short-rest notice.
 */
export function buildStrip(
  fixtures: FixtureEntry[],
  extras: TeamExtras | null,
  series: FixtureOutlookGW[] | null,
): StripCell[] {
  const cells: StripCell[] = [];
  const placed = new Set<number>();
  for (const f of fixtures) {
    if (!placed.has(f.gameweek)) {
      placed.add(f.gameweek);
      const before = (extras?.extras ?? [])
        .filter((m) => m.gameweek === f.gameweek)
        .sort((a, b) => Date.parse(a.kickoff) - Date.parse(b.kickoff));
      for (const m of before) {
        cells.push({
          kind: 'extra',
          key: `x-${m.kickoff}-${m.competition}`,
          gameweek: f.gameweek,
          competition: m.competition,
          opponentCode: m.opponentCode,
          opponent: m.opponent,
          venue: m.venue,
          kickoff: m.kickoff,
        });
      }
    }
    cells.push({
      kind: 'pl',
      key: `${f.gameweek}-${f.opponent_short}-${f.is_home ? 'H' : 'A'}`,
      gameweek: f.gameweek,
      opponent: f.opponent_short,
      isHome: f.is_home,
      fdr: f.difficulty,
      band: bandFor(f, series),
      rest: restFor(f, extras),
    });
  }
  return cells;
}
