/**
 * Which language the app speaks. One policy, one function: the server layout, the client
 * provider and the request bodies all call resolveLocale(), so they cannot disagree.
 *
 * Pure (no cookies, no Clerk, no window): callers hand it the facts.
 */
import type { LocaleRollout } from '@/lib/features';

export type Locale = 'es' | 'en';
export const DEFAULT_LOCALE: Locale = 'es';
export const LOCALE_COOKIE = 'bf_locale';
const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

export function parseLocale(value: unknown): Locale | null {
  return value === 'es' || value === 'en' ? value : null;
}

/** First supported language of an Accept-Language header, by quality; null when it names neither. */
export function localeFromAcceptLanguage(header: string | null | undefined): Locale | null {
  if (!header) return null;
  const ranked = header
    .split(',')
    .map((part, index) => {
      const [tag, ...params] = part.trim().split(';');
      const q = params.map((p) => p.trim()).find((p) => p.startsWith('q='));
      const quality = q ? Number.parseFloat(q.slice(2)) : 1;
      return { primary: tag.trim().toLowerCase().split('-')[0], quality: Number.isFinite(quality) ? quality : 0, index };
    })
    .filter((entry) => entry.quality > 0 && (entry.primary === 'es' || entry.primary === 'en'))
    .sort((a, b) => b.quality - a.quality || a.index - b.index);
  return ranked.length ? (ranked[0].primary as Locale) : null;
}

export interface LocaleFacts {
  rollout: LocaleRollout;
  /** Clerk role 'admin'. Signed out counts as false. */
  isAdmin: boolean;
  /** The bf_locale cookie, as read (any value). */
  cookie?: string | null;
  acceptLanguage?: string | null;
}

/** May this visitor choose a language at all (the toggle, the cookie, the browser language)? */
export function canChooseLocale({ rollout, isAdmin }: Pick<LocaleFacts, 'rollout' | 'isAdmin'>): boolean {
  return rollout === 'public' || (rollout === 'admin' && isAdmin);
}

export function resolveLocale(facts: LocaleFacts): Locale {
  if (!canChooseLocale(facts)) return DEFAULT_LOCALE;
  return parseLocale(facts.cookie) ?? localeFromAcceptLanguage(facts.acceptLanguage) ?? DEFAULT_LOCALE;
}

/** The Set-Cookie string the toggle writes (client side). */
export function localeCookie(locale: Locale): string {
  return `${LOCALE_COOKIE}=${locale}; path=/; max-age=${ONE_YEAR_SECONDS}; samesite=lax`;
}
