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

/** Compact view only: the rotation notice of a gameweek, as the marks need it. */
export interface RotationNotice {
  restWholeDays: number;
  previousCompetition: string | null;
  opponent: string;
}

export interface PremiumGw {
  matches: ExtraMatch[];
  notice: RotationNotice | null;
}

export type TeamExtras =
  | {
      kind: 'premium';
      /** By gameweek, for the compact grid's marks. */
      byGw: Map<number, PremiumGw>;
      /** Every other-competition match, for the timeline. */
      extras: ExtraMatch[];
      /** Premier League kickoffs with their rest days, for the timeline. */
      plMatches: PlMatch[];
    }
  | { kind: 'free'; countByGw: Map<number, number> };

export interface CompetitionsView {
  tier: 'premium' | 'free';
  teams: Map<string, TeamExtras>;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function parseCompetitions(payload: unknown): CompetitionsView | null {
  if (!isRecord(payload) || payload.available !== true || !isRecord(payload.teams)) return null;
  const tier = payload.tier;
  if (tier !== 'premium' && tier !== 'free') return null;
  const teams = new Map<string, TeamExtras>();
  for (const [code, raw] of Object.entries(payload.teams)) {
    if (!isRecord(raw)) continue;
    if (tier === 'free') {
      const countByGw = new Map<number, number>();
      if (isRecord(raw.extra_by_gameweek)) {
        for (const [gw, n] of Object.entries(raw.extra_by_gameweek)) {
          if (typeof n === 'number' && n > 0 && Number.isInteger(Number(gw))) countByGw.set(Number(gw), n);
        }
      }
      teams.set(code, { kind: 'free', countByGw });
      continue;
    }
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
    const byGw = new Map<number, PremiumGw>();
    const slot = (gw: number) => {
      const existing = byGw.get(gw);
      if (existing) return existing;
      const created: PremiumGw = { matches: [], notice: null };
      byGw.set(gw, created);
      return created;
    };
    for (const m of extras) if (m.gameweek !== null) slot(m.gameweek).matches.push(m);
    for (const m of plMatches) {
      if (m.gameweek === null || !m.rotation || m.restWholeDays === null) continue;
      slot(m.gameweek).notice = {
        restWholeDays: m.restWholeDays,
        previousCompetition: m.previousCompetition,
        opponent: m.opponent,
      };
    }
    teams.set(code, { kind: 'premium', byGw, extras, plMatches });
  }
  return { tier, teams };
}

export function extrasFor(view: CompetitionsView | null, team: string): TeamExtras | null {
  return view?.teams.get(team) ?? null;
}

/** Whole-league: does the free view have anything to tease inside these gameweeks? */
export function hasFreeTease(view: CompetitionsView | null, gameweeks: number[]): boolean {
  if (view?.tier !== 'free') return false;
  const shown = new Set(gameweeks);
  for (const extras of view.teams.values()) {
    if (extras.kind !== 'free') continue;
    for (const gw of extras.countByGw.keys()) if (shown.has(gw)) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Names and colours
// ---------------------------------------------------------------------------

const NAMES: Record<string, string> = {
  UCL: 'Champions League',
  UEL: 'Europa League',
  UECL: 'Conference League',
  'UEFA-SC': 'Supercopa de Europa',
  FA: 'FA Cup',
  EFL: 'Carabao Cup',
  PL: 'Premier League',
};
const AFTER: Record<string, string> = {
  UCL: 'la Champions',
  UEL: 'la Europa League',
  UECL: 'la Conference',
  'UEFA-SC': 'la Supercopa de Europa',
  FA: 'la FA Cup',
  EFL: 'la Carabao',
  PL: 'la Premier',
};

export const competitionName = (badge: string): string => NAMES[badge] ?? badge;

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

/** The legend's entries: one swatch per hue, in the design's order. */
export const COMPETITION_LEGEND: Array<{ label: string; color: string }> = [
  { label: 'Champions', color: COMPETITION_COLORS.UCL },
  { label: 'Europa League', color: COMPETITION_COLORS.UEL },
  { label: 'Conference', color: COMPETITION_COLORS.UECL },
  { label: 'Copas', color: COMPETITION_COLORS.FA },
];

/** «3 días de descanso tras la Champions · posible rotación» (compact view's tooltip). */
export function rotationText(notice: RotationNotice): string {
  const days = `${notice.restWholeDays} ${notice.restWholeDays === 1 ? 'día' : 'días'} de descanso`;
  const after = notice.previousCompetition ? AFTER[notice.previousCompetition] : undefined;
  return `${days}${after ? ` tras ${after}` : ''} · posible rotación`;
}

export const freeTeaseText = (n: number): string => `🔒 +${n}`;
export const freeTeaseTitle = (n: number): string =>
  `${n === 1 ? '1 partido más' : `${n} partidos más`} esta semana · Ver con Premium`;

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
}

export type TimelineItem =
  | { kind: 'pl'; key: string; gw: FixtureOutlookGW; gap: GapInfo | null }
  | { kind: 'extra'; key: string; match: ExtraMatch; sentence: string; gap: GapInfo | null }
  | { kind: 'ghost'; key: string; gameweek: number; count: number };

const daysWord = (n: number) => `${n} ${n === 1 ? 'día' : 'días'}`;

export const venueWord = (venue: 'H' | 'A') => (venue === 'H' ? 'local' : 'visitante');

export function extraSentence(match: ExtraMatch): string {
  return `${competitionName(match.competition)} ante ${match.opponent} (${venueWord(match.venue)})`;
}

function gapFor(restWholeDays: number | null, rotation: boolean, opponent: string): GapInfo | null {
  if (restWholeDays === null) return null;
  return {
    days: restWholeDays,
    rotation,
    sentence: rotation
      ? `${daysWord(restWholeDays)} de descanso antes de ${opponent}: posible rotación`
      : `${daysWord(restWholeDays)} de descanso`,
  };
}

/**
 * The visible window as one line of tiles.
 *
 * Premier League tiles come from the bundle's gameweeks (their kickoffs from the payload);
 * other-competition matches are placed between them by their real kickoff. A gameweek
 * with no Premier League match (blank) keeps its place right after the previous one.
 * The free view has no dates, only counts: a ghost tile sits before its gameweek's tile.
 */
export function buildTimeline(series: FixtureOutlookGW[], extras: TeamExtras): TimelineItem[] {
  if (extras.kind === 'free') {
    return series.flatMap((gw): TimelineItem[] => {
      const count = extras.countByGw.get(gw.gameweek);
      const tile: TimelineItem = { kind: 'pl', key: `pl-${gw.gameweek}`, gw, gap: null };
      return count ? [{ kind: 'ghost', key: `ghost-${gw.gameweek}`, gameweek: gw.gameweek, count }, tile] : [tile];
    });
  }

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
        gap: first ? gapFor(first.restWholeDays, first.rotation, first.opponent) : null,
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
        sentence: extraSentence(match),
        gap: gapFor(match.restWholeDays, false, match.opponent),
      },
    });
  });

  const ordered = slots.sort((a, b) => a.at - b.at).map((s) => s.item);
  // The first tile of the window has no visible predecessor: no number before it.
  const [head, ...rest] = ordered;
  return head && head.kind !== 'ghost' ? [{ ...head, gap: null }, ...rest] : ordered;
}
