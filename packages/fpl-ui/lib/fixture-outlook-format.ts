/**
 * Pure formatting helpers for the fixture outlook ticker (Track D / FI4).
 * Kept in a .ts (no JSX) so they're trivially unit-testable.
 *
 * Palette + labels follow the "Calendario FDR" readability design
 * (Bendito Fantasy design system) — see
 * .design-import/design_handoff_calendario_fdr/.
 */
import type { FixtureAxis, FixtureOutlookGW } from './types';
import { translate, type DictKey } from './i18n/dictionary';
import { DEFAULT_LOCALE, type Locale } from './i18n/locale';

export type Band = 1 | 2 | 3 | 4 | 5;

/** Difficulty band (1=easiest … 5=hardest) → hex colour (FDR ramp). */
export function bandColor(band: Band): string {
  const COLORS: Record<Band, string> = {
    1: '#02EBAE', // Fácil
    2: '#04C4D9', // Favorable
    3: '#F2C572', // Medio
    4: '#F27A5E', // Difícil
    5: '#FF6A4D', // Muy difícil
  };
  return COLORS[band];
}

const BAND_KEYS: Record<Band, DictKey> = {
  1: 'fx.band.1',
  2: 'fx.band.2',
  3: 'fx.band.3',
  4: 'fx.band.4',
  5: 'fx.band.5',
};

/** Difficulty band → label used in the legend + tooltips (Spanish unless a locale is given). */
export function bandLabel(band: Band, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, BAND_KEYS[band]);
}

/** Venue short marker: Spanish L = Local / V = Visitante, English H = Home / A = Away. */
export function venueLabel(isHome: boolean, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, isHome ? 'fx.venue.home' : 'fx.venue.away');
}

/** 'J12' / 'GW12'. */
export function gwLabel(n: number, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, 'fx.gw', { n });
}

/** 'J12–J14' / 'GW12–GW14'. */
export function gwRange(start: number, end: number, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, 'fx.gwRange', { start, end });
}

/** What a cell says as a tooltip: its gameweek, opponents, venue, FDR and whether it is a double gameweek. */
export function cellTitle(gw: FixtureOutlookGW, locale: Locale = DEFAULT_LOCALE): string {
  if (gw.band === null) return translate(locale, 'fx.cell.blank');
  const opponents = gw.fixtures.map((f) => f.opponent_short).join('/');
  const venue = gw.fixtures.map((f) => venueLabel(f.is_home, locale)).join('/');
  return (
    translate(locale, 'fx.cell.title', { gw: gw.gameweek, opponents, venue, band: gw.band }) +
    (gw.is_dgw ? translate(locale, 'fx.cell.dgw') : '')
  );
}

/** The same for assistive technology on the presentation grid, where a blank cell names its gameweek too. */
export function cellAriaLabel(gw: FixtureOutlookGW, locale: Locale = DEFAULT_LOCALE): string {
  return gw.band === null ? translate(locale, 'fx.cell.blankGw', { gw: gw.gameweek }) : cellTitle(gw, locale);
}

/** Colour for the neutral "blank gameweek" cell (no fixture). */
export const BLANK_COLOR = '#6b7280';

/** `#RRGGBB` + alpha → `rgba(...)`. Falls back to the hex on a bad input. */
export function hexRgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/** Axis → label for the card chip (Spanish unless a locale is given). */
export function axisLabel(axis: FixtureAxis, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, axis === 'attack' ? 'fx.axis.attack' : 'fx.axis.defence');
}

// ---------------------------------------------------------------------------
// Team verdicts
// ---------------------------------------------------------------------------

/** The backend writes each team's one-line verdict in Spanish, from ten fixed templates (es.ts, fx.verdict.*). */
const VERDICT_KEYS: DictKey[] = [
  'fx.verdict.none',
  'fx.verdict.noRuns',
  'fx.verdict.attackGood',
  'fx.verdict.attackGoodStrong',
  'fx.verdict.attackBad',
  'fx.verdict.attackBadStrong',
  'fx.verdict.defenceGood',
  'fx.verdict.defenceGoodStrong',
  'fx.verdict.defenceBad',
  'fx.verdict.defenceBadStrong',
];

/** The Spanish template as a regular expression: {n} is a number, {span} is 'J17–J19'. */
function verdictPattern(template: string): RegExp {
  const source = template
    .replace(/[.*+?^$|\\()[\]{}]/g, '\\$&')
    .replace('\\{n\\}', '(\\d+)')
    .replace('\\{span\\}', 'J(\\d+)–J(\\d+)');
  return new RegExp(`^${source}$`);
}

const VERDICT_RULES = VERDICT_KEYS.map((key) => ({ key, pattern: verdictPattern(translate('es', key)) }));

/**
 * A team verdict in the language showing. Spanish passes through untouched. English recognises the backend's
 * templates and says the same thing in English; text it does not recognise (a new template, or a verdict the
 * backend already wrote in English) is left exactly as it came rather than guessed at.
 */
export function fixtureVerdict(verdict: string, locale: Locale = DEFAULT_LOCALE): string {
  if (locale === 'es') return verdict;
  for (const { key, pattern } of VERDICT_RULES) {
    const m = pattern.exec(verdict);
    if (!m) continue;
    const vars: Record<string, string | number> = {};
    let groups = m.slice(1);
    if (translate('es', key).includes('{n}')) vars.n = groups.shift() as string;
    if (groups.length === 2) vars.span = gwRange(Number(groups[0]), Number(groups[1]), locale);
    return translate(locale, key, vars);
  }
  return verdict;
}
