/**
 * Multi-competition layer of /fixtures: parsing the backend's tier-gated payload,
 * the single-timeline model of one team's season, and the wording shown on the board.
 * Pure, no I/O.
 *
 * The BACKEND decides what a caller may see. This file never gates anything: it
 * renders whichever of the two shapes arrived, and a payload it does not
 * recognise (or `available: false`, which is all production ever returns)
 * yields `null` so the board looks exactly as it did before this layer existed.
 */
import type { FixtureOutlookGW } from './types';
import { translate } from './i18n/dictionary';
import { DEFAULT_LOCALE, type Locale } from './i18n/locale';

export interface ExtraMatch {
  kickoff: string;
  gameweek: number | null;
  competition: string;
  venue: 'H' | 'A';
  opponent: string;
  /** Three-letter code (Sportmonks short_code; FPL's for Premier League clubs). */
  opponentCode: string;
  /** Whole days (floor of hours / 24) since the club's previous match, any competition. */
  restWholeDays: number | null;
}

export interface PlMatch {
  kickoff: string;
  gameweek: number | null;
  opponent: string;
  venue: 'H' | 'A';
  restWholeDays: number | null;
  /** Server-decided: <= 3 whole days after a European or cup match (Leo, 2026-10-14). */
  rotation: boolean;
  previousCompetition: string | null;
}

export interface TeamExtras {
  /** Every other-competition match. */
  extras: ExtraMatch[];
  /** Premier League kickoffs with their rest days. */
  plMatches: PlMatch[];
}

/**
 * What the backend answered. `free` (Free and Tribuna) carries NO teams: the server tells
 * them only that the layer exists and is locked, so there is nothing to draw but the locked switch.
 */
export interface CompetitionsView {
  tier: 'premium' | 'free';
  teams: Map<string, TeamExtras>;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function parseCompetitions(payload: unknown): CompetitionsView | null {
  if (!isRecord(payload) || payload.available !== true) return null;
  const tier = payload.tier;
  if (tier !== 'premium' && tier !== 'free') return null;
  const teams = new Map<string, TeamExtras>();
  // Whatever else a free answer carried is ignored: the locked layer draws nothing per team.
  if (tier === 'free') return { tier, teams };
  if (!isRecord(payload.teams)) return null;
  for (const [code, raw] of Object.entries(payload.teams)) {
    if (!isRecord(raw)) continue;
    const extras: ExtraMatch[] = [];
    for (const m of Array.isArray(raw.matches) ? raw.matches : []) {
      if (!isRecord(m) || typeof m.kickoff_utc !== 'string') continue;
      if (typeof m.competition !== 'string' || typeof m.opponent !== 'string') continue;
      extras.push({
        kickoff: m.kickoff_utc,
        gameweek: num(m.gameweek),
        competition: m.competition,
        venue: m.venue === 'A' ? 'A' : 'H',
        opponent: m.opponent,
        opponentCode:
          typeof m.opponent_code === 'string' && m.opponent_code
            ? m.opponent_code
            : m.opponent.slice(0, 3).toUpperCase(),
        restWholeDays: num(m.rest_whole_days_before),
      });
    }
    const plMatches: PlMatch[] = [];
    for (const m of Array.isArray(raw.pl_matches) ? raw.pl_matches : []) {
      if (!isRecord(m) || typeof m.kickoff_utc !== 'string' || typeof m.opponent !== 'string') continue;
      plMatches.push({
        kickoff: m.kickoff_utc,
        gameweek: num(m.gameweek),
        opponent: m.opponent,
        venue: m.venue === 'A' ? 'A' : 'H',
        restWholeDays: num(m.rest_whole_days_before),
        rotation: m.rotation === true,
        previousCompetition: typeof m.previous_competition === 'string' ? m.previous_competition : null,
      });
    }
    teams.set(code, { extras, plMatches });
  }
  return { tier, teams };
}

export function extrasFor(view: CompetitionsView | null, team: string): TeamExtras | null {
  return view?.teams.get(team) ?? null;
}

// ---------------------------------------------------------------------------
// Names and colours
// ---------------------------------------------------------------------------

const NAMES: Record<string, string> = {
  UCL: 'Champions League',
  UEL: 'Europa League',
  UECL: 'Conference League',
  FA: 'FA Cup',
  EFL: 'Carabao Cup',
  PL: 'Premier League',
};
export const competitionName = (badge: string, locale: Locale = DEFAULT_LOCALE): string =>
  badge === 'UEFA-SC' ? translate(locale, 'fx.comp.superCup') : NAMES[badge] ?? badge;

/** The shortest label the calendar shows for a competition: the code on its tile (the Super Cup shows «SC»). */
export const competitionTileLabel = (badge: string): string => (badge === 'UEFA-SC' ? 'SC' : badge);

/**
 * Outline colour of a competition's tile (iteration-2 design). The app's `bf-*` tokens
 * carry no competition hues, so they live here, next to the only code that uses them.
 */
export const COMPETITION_COLORS: Record<string, string> = {
  UCL: '#6F93FF',
  'UEFA-SC': '#6F93FF',
  UEL: '#FF9F43',
  UECL: '#35C79A',
  FA: '#D77AD0',
  EFL: '#D77AD0',
};
export const competitionColor = (badge: string): string => COMPETITION_COLORS[badge] ?? '#ABA9AC';

/** One legend entry: its label, its hue and (when the label is long) the shorter word the presentation header uses. */
export interface LegendEntry {
  label: string;
  color: string;
  short?: string;
}

/** The legend's entries: one swatch per hue, in the design's order. Only «Copas» / «Cups» changes with the language. */
export function competitionLegend(locale: Locale = DEFAULT_LOCALE): LegendEntry[] {
  return [
    { label: 'Champions', color: COMPETITION_COLORS.UCL },
    { label: 'Europa League', color: COMPETITION_COLORS.UEL, short: 'Europa' },
    { label: 'Conference', color: COMPETITION_COLORS.UECL },
    { label: translate(locale, 'fx.comp.cups'), color: COMPETITION_COLORS.FA },
  ];
}
export const COMPETITION_LEGEND: LegendEntry[] = competitionLegend();

/** The locked switch (Free/Tribuna): what it says and what opens when it is tapped. */
export const LOCKED_BADGE = 'Premium';
export const lockedLine = (locale: Locale = DEFAULT_LOCALE): string => translate(locale, 'fx.comp.lockedLine');
export const lockedLink = (locale: Locale = DEFAULT_LOCALE): string => translate(locale, 'fx.comp.lockedLink');
export const LOCKED_LINE = lockedLine();
export const LOCKED_LINK = lockedLink();

// ---------------------------------------------------------------------------
// The timeline: one team's matches in real date order, every competition
// ---------------------------------------------------------------------------

/** The rest between a match and the one before it, as a number in the gap. */
export interface GapInfo {
  /** Whole days (floor of hours / 24). */
  days: number;
  /** Gold: a Premier League match <= 3 days after a European or cup match. */
  rotation: boolean;
  /** Full phrase for the detail and for assistive technology. */
  sentence: string;
  /** Short label of the cell, e.g. «3 días tras Champions League» (rotation notice only). */
  cell?: string;
}

export type TimelineItem =
  | { kind: 'pl'; key: string; gw: FixtureOutlookGW; gap: GapInfo | null }
  | { kind: 'extra'; key: string; match: ExtraMatch; sentence: string; gap: GapInfo | null };

const daysWord = (n: number, locale: Locale) => translate(locale, n === 1 ? 'fx.days.one' : 'fx.days.many', { n });

export const venueWord = (venue: 'H' | 'A', locale: Locale = DEFAULT_LOCALE) =>
  translate(locale, venue === 'H' ? 'fx.venue.homeLower' : 'fx.venue.awayLower');

export function extraSentence(match: ExtraMatch, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, 'fx.extra.sentence', {
    comp: competitionName(match.competition, locale),
    opponent: match.opponent,
    venue: venueWord(match.venue, locale),
  });
}

/**
 * Rotation notice copy (descriptive, no claim about the risk): the cell says how many days after which
 * competition; the detail says what happened and that there is not yet evidence to size the risk.
 * Only the wording lives here: the days, the flag and the competition come from the server unchanged.
 */
function gapFor(
  restWholeDays: number | null,
  rotation: boolean,
  _opponent: string,
  previousCompetition: string | null = null,
  locale: Locale = DEFAULT_LOCALE,
): GapInfo | null {
  if (restWholeDays === null) return null;
  const days = daysWord(restWholeDays, locale);
  if (!rotation) return { days: restWholeDays, rotation, sentence: translate(locale, 'fx.rest', { days }) };
  const comp = previousCompetition ? competitionTileLabel(previousCompetition) : translate(locale, 'fx.comp.another');
  return {
    days: restWholeDays,
    rotation,
    cell: translate(locale, 'fx.rest.cell', { days, comp }),
    sentence: translate(locale, 'fx.rest.sentence', { comp, days }),
  };
}

/**
 * The visible window as one line of tiles.
 *
 * Premier League tiles come from the bundle's gameweeks (their kickoffs from the payload);
 * other-competition matches are placed between them by their real kickoff. A gameweek
 * with no Premier League match (blank) keeps its place right after the previous one.
 */
export function buildTimeline(
  series: FixtureOutlookGW[],
  extras: TeamExtras,
  locale: Locale = DEFAULT_LOCALE,
): TimelineItem[] {
  const visible = new Set(series.map((gw) => gw.gameweek));
  type Slot = { at: number; item: TimelineItem };
  const slots: Slot[] = [];
  let lastPlAt = Number.MIN_SAFE_INTEGER;

  for (const gw of series) {
    const first = extras.plMatches
      .filter((m) => m.gameweek === gw.gameweek)
      .sort((a, b) => Date.parse(a.kickoff) - Date.parse(b.kickoff))[0];
    const at = first ? Date.parse(first.kickoff) : lastPlAt + 1;
    lastPlAt = at;
    slots.push({
      at,
      item: {
        kind: 'pl',
        key: `pl-${gw.gameweek}`,
        gw,
        gap: first
          ? gapFor(first.restWholeDays, first.rotation, first.opponent, first.previousCompetition, locale)
          : null,
      },
    });
  }
  extras.extras.forEach((match, i) => {
    if (match.gameweek === null || !visible.has(match.gameweek)) return;
    slots.push({
      at: Date.parse(match.kickoff),
      item: {
        kind: 'extra',
        key: `extra-${i}-${match.kickoff}`,
        match,
        sentence: extraSentence(match, locale),
        gap: gapFor(match.restWholeDays, false, match.opponent, null, locale),
      },
    });
  });

  const ordered = slots.sort((a, b) => a.at - b.at).map((s) => s.item);
  // The first tile of the window has no visible predecessor: no number before it.
  const [head, ...rest] = ordered;
  return head ? [{ ...head, gap: null }, ...rest] : ordered;
}

// ---------------------------------------------------------------------------
// Compact grid: the gutter before each gameweek column
// ---------------------------------------------------------------------------

/** What sits in the narrow strip just before a gameweek's column. */
export interface CompactGutter {
  /** The other-competition matches that precede that gameweek's Premier League match, in kickoff order. */
  matches: ExtraMatch[];
  /** That Premier League match, when it carries the rotation notice (the gold dot). */
  rotation: PlMatch | null;
}

export function compactGutter(extras: TeamExtras | null, gameweek: number): CompactGutter {
  if (!extras) return { matches: [], rotation: null };
  const matches = extras.extras
    .filter((m) => m.gameweek === gameweek)
    .sort((a, b) => Date.parse(a.kickoff) - Date.parse(b.kickoff));
  const rotation = matches.length ? extras.plMatches.find((m) => m.gameweek === gameweek && m.rotation) ?? null : null;
  return { matches, rotation };
}

/** The line a tapped bar opens, e.g. «ARS · Champions League ante Lille (local) · Su equipo jugó UCL hace 3 días. Todavía no hay evidencia suficiente para cuantificar el riesgo de rotación.». */
export function gutterSentence(team: string, gutter: CompactGutter, locale: Locale = DEFAULT_LOCALE): string {
  const parts = gutter.matches.map((match) => extraSentence(match, locale));
  if (gutter.rotation && gutter.rotation.restWholeDays !== null) {
    parts.push(
      gapFor(
        gutter.rotation.restWholeDays,
        true,
        gutter.rotation.opponent,
        gutter.rotation.previousCompetition,
        locale,
      )?.sentence ?? '',
    );
  }
  return `${team} · ${parts.join(' · ')}`;
}

// ---------------------------------------------------------------------------
// Presentation: one fixed column per gameweek, a reserved slot before each
// ---------------------------------------------------------------------------

/** An other-competition match that sits in a slot, with the rest before it. */
export interface SlotMatch {
  key: string;
  match: ExtraMatch;
  sentence: string;
  /** Rest since the previous match of any competition (null when unknown or first of the window). */
  gap: GapInfo | null;
}

/** One gameweek column and the slot that precedes it. */
export interface PresentationColumn {
  gw: FixtureOutlookGW;
  /** Other-competition matches between the previous Premier League match and this one, in kickoff order. */
  slot: SlotMatch[];
  /** Rest into this Premier League match (gold when it carries the rotation notice); null for the first column. */
  gap: GapInfo | null;
}

/**
 * The timeline folded onto a fixed grid: every team gets exactly one column per
 * gameweek of the window, so the rows of the whole league align. A match of another
 * competition belongs to the slot before the Premier League match it precedes; any
 * after the last Premier League match of the window belongs to a gameweek the window
 * does not show and is left out. A team the layer knows nothing about still gets its columns.
 */
export function buildPresentationColumns(
  series: FixtureOutlookGW[],
  extras: TeamExtras | null,
  locale: Locale = DEFAULT_LOCALE,
): PresentationColumn[] {
  const items = buildTimeline(series, extras ?? { extras: [], plMatches: [] }, locale);
  const columns: PresentationColumn[] = [];
  let pending: SlotMatch[] = [];
  for (const item of items) {
    if (item.kind === 'extra') {
      pending.push({ key: item.key, match: item.match, sentence: item.sentence, gap: item.gap });
    } else {
      columns.push({ gw: item.gw, slot: pending, gap: item.gap });
      pending = [];
    }
  }
  return columns;
}
