/**
 * Dates and "how long ago" in the language showing. One place, so no component hardcodes
 * 'es-ES', a month list or "hace N días". Spanish output is what the app printed before:
 * the numeric formats keep the 'es-ES' Intl tag and the abbreviated months keep their fixed
 * list (Intl's own Spanish abbreviations vary between engines).
 */
import { translate } from './dictionary';
import type { Locale } from './locale';

const INTL_TAG: Record<Locale, string> = { es: 'es-ES', en: 'en-GB' };
export const intlTag = (locale: Locale): string => INTL_TAG[locale];

const MONTHS: Record<Locale, readonly string[]> = {
  es: ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
};

/** '21 ago' / '21 Aug': the short day-and-month of a date. */
export function formatDayMonth(locale: Locale, date: Date): string {
  return date.toLocaleDateString(intlTag(locale), { day: 'numeric', month: 'short' });
}

/** '21 ago, 18:30' / '21 Aug, 18:30'. */
export function formatDateTime(locale: Locale, date: Date): string {
  return date.toLocaleString(intlTag(locale), { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

/** '8 sep 2026' / '8 Sep 2026', in UTC. */
export function formatUtcDate(locale: Locale, date: Date): string {
  return `${date.getUTCDate()} ${MONTHS[locale][date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

/** How long ago, from whole days: today, 1 day ago, N days ago, N weeks ago (under 8), N months ago. */
export function formatDaysAgo(locale: Locale, diffDays: number): string {
  if (diffDays === 0) return translate(locale, 'time.today');
  if (diffDays === 1) return translate(locale, 'time.dayAgo');
  if (diffDays < 30) return translate(locale, 'time.daysAgo', { n: diffDays });
  const weeks = Math.floor(diffDays / 7);
  if (weeks < 8) return translate(locale, 'time.weeksAgo', { n: weeks });
  const months = Math.floor(diffDays / 30);
  // Spanish keeps its historical "hace 1 meses"; English says "1 month ago".
  return months === 1 ? translate(locale, 'time.monthAgo') : translate(locale, 'time.monthsAgo', { n: months });
}
