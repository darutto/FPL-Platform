/**
 * Multi-competition layer of /fixtures: parsing the backend's tier-gated payload
 * and the wording shown on the board. Pure, no I/O.
 *
 * The BACKEND decides what a caller may see. This file never gates anything: it
 * renders whichever of the two shapes arrived, and a payload it does not
 * recognise (or `available: false`, which is all production ever returns)
 * yields `null` so the board looks exactly as it did before this layer existed.
 */

export interface ExtraMatch {
  competition: string;
  venue: 'H' | 'A';
  opponent: string;
  restBefore: number | null;
  restAfter: number | null;
}

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
  | { kind: 'premium'; byGw: Map<number, PremiumGw> }
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
    const byGw = new Map<number, PremiumGw>();
    const slot = (gw: number) => {
      const existing = byGw.get(gw);
      if (existing) return existing;
      const created: PremiumGw = { matches: [], notice: null };
      byGw.set(gw, created);
      return created;
    };
    for (const m of Array.isArray(raw.matches) ? raw.matches : []) {
      if (!isRecord(m)) continue;
      const gw = num(m.gameweek);
      if (gw === null || typeof m.competition !== 'string' || typeof m.opponent !== 'string') continue;
      slot(gw).matches.push({
        competition: m.competition,
        venue: m.venue === 'A' ? 'A' : 'H',
        opponent: m.opponent,
        restBefore: num(m.rest_days_before),
        restAfter: num(m.rest_days_after),
      });
    }
    for (const n of Array.isArray(raw.rotation_notices) ? raw.rotation_notices : []) {
      if (!isRecord(n)) continue;
      const gw = num(n.gameweek);
      const days = num(n.rest_whole_days);
      if (gw === null || days === null) continue;
      slot(gw).notice = {
        restWholeDays: days,
        previousCompetition: typeof n.previous_competition === 'string' ? n.previous_competition : null,
        opponent: typeof n.opponent === 'string' ? n.opponent : '',
      };
    }
    teams.set(code, { kind: 'premium', byGw });
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

/** «3 días de descanso tras la Champions · posible rotación» (Leo's wording, 2026-10-14). */
export function rotationText(notice: RotationNotice): string {
  const days = `${notice.restWholeDays} ${notice.restWholeDays === 1 ? 'día' : 'días'} de descanso`;
  const after = notice.previousCompetition ? AFTER[notice.previousCompetition] : undefined;
  return `${days}${after ? ` tras ${after}` : ''} · posible rotación`;
}

/** Opportunity framing for the tooltip: what the reader can DO with the notice. */
export const ROTATION_OPPORTUNITY =
  'Oportunidad: revisa quién entra y qué alternativas tienes antes del cierre de la jornada.';

export const freeTeaseText = (n: number): string => `🔒 +${n}`;
export const freeTeaseTitle = (n: number): string =>
  `${n === 1 ? '1 partido más' : `${n} partidos más`} esta semana · Ver con Premium`;

export function restLabel(days: number | null): string | null {
  return days === null ? null : `${Math.floor(days)}d`;
}
