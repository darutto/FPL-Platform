/**
 * The player card's fixture strip. Pure, no I/O. Same rules as the /fixtures calendar
 * (Leo, 2026-11-09: the calendar leads).
 *
 * - Every plan: our fixture-outlook band on each Premier League cell, on the player's axis
 *   (his observed role when the backend has it, else FWD/MID attack, DEF/GKP defence).
 *   With no band, the cell keeps FPL's FDR.
 * - Premium only: Europe and cup matches as their own cells, before the gameweek they
 *   precede, the short-rest notice on the Premier League match that follows them, and the
 *   rest days before every cell (the /fixtures timeline's gaps; Leo, 2026-11-13).
 *
 * The BACKEND decides the tier (via /fixtures/competitions). This file never gates: the
 * caller passes the team's extras only when the answer was premium.
 */
import type { FixtureAxis, FixtureEntry, FixtureOutlookGW } from './types';
import type { Band } from './fixture-outlook-format';
import { extraSentence, gapFor, type ExtraMatch, type GapInfo, type PlMatch, type TeamExtras } from './fixture-competitions';
import { DEFAULT_LOCALE, type Locale } from './i18n/locale';

/**
 * Which outlook axis a player reads. The backend decides it from the role he was listed to
 * start in (`strip_axis` on the snapshot: a defensive MID reads defence, a pushed-up wing-back
 * attack; Leo, 2026-11-08). Without that answer (too few starts, no lineup data) it goes by FPL
 * position: DEF/GKP read the clean-sheet axis, everyone else attack.
 */
export function stripAxis(position: string, observed?: FixtureAxis | null): FixtureAxis {
  if (observed === 'attack' || observed === 'defence') return observed;
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
  /** The rest before this match, drawn between tiles (Premium only; null for the first cell). */
  gap: GapInfo | null;
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
  /** The match as the /fixtures timeline draws it, and its full sentence (tooltip / screen readers). */
  match: ExtraMatch;
  sentence: string;
  /** The rest before this match (null for the first cell). */
  gap: GapInfo | null;
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

/** The payload's Premier League match for a fixture: same gameweek, opponent and venue (or the only one that GW). */
function plMatchFor(entry: FixtureEntry, extras: TeamExtras | null): PlMatch | null {
  if (!extras) return null;
  const sameGw = extras.plMatches.filter((m) => m.gameweek === entry.gameweek);
  const venue = entry.is_home ? 'H' : 'A';
  return (
    sameGw.find((m) => m.opponentCode === entry.opponent_short && m.venue === venue) ??
    (sameGw.length === 1 ? sameGw[0] : null)
  );
}

function restFor(match: PlMatch | null): StripRest | null {
  if (!match || !match.rotation || match.restWholeDays === null || !match.previousCompetition) return null;
  return { days: match.restWholeDays, competition: match.previousCompetition };
}

/**
 * The strip: Premier League cells with their band, plus (when `extras` is given, i.e. Premium)
 * other competitions in date order between them, the short-rest notice and the rest days
 * before each cell (none before the first: it has no visible predecessor).
 */
export function buildStrip(
  fixtures: FixtureEntry[],
  extras: TeamExtras | null,
  series: FixtureOutlookGW[] | null,
  locale: Locale = DEFAULT_LOCALE,
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
          match: m,
          sentence: extraSentence(m, locale),
          gap: gapFor(m.restWholeDays, false, m.opponent, null, locale),
        });
      }
    }
    const match = plMatchFor(f, extras);
    cells.push({
      kind: 'pl',
      key: `${f.gameweek}-${f.opponent_short}-${f.is_home ? 'H' : 'A'}`,
      gameweek: f.gameweek,
      opponent: f.opponent_short,
      isHome: f.is_home,
      fdr: f.difficulty,
      band: bandFor(f, series),
      rest: restFor(match),
      gap: match
        ? gapFor(match.restWholeDays, match.rotation, match.opponent, match.previousCompetition, locale, match.restHours)
        : null,
    });
  }
  return cells.length > 0 ? [{ ...cells[0], gap: null }, ...cells.slice(1)] : cells;
}
