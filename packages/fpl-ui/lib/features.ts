/**
 * Feature flags. The World Cup is over, so the app is FPL-only for now.
 * Flip this back on to bring the FPL / Mundial switch to the TopBar; the
 * /wc routes, shell and backend were left in place on purpose.
 */
export const SHOW_SECTION_SWITCHER = false;

/**
 * Who may use the English version.
 *   'off'    - Spanish for everyone; the cookie and the browser language are ignored.
 *   'admin'  - owner accounts (Clerk publicMetadata.role === 'admin') choose; everyone else is pinned to Spanish.
 *   'public' - everyone chooses (cookie, else the browser language).
 * Decided in one place, by resolveLocale() in lib/i18n/locale.ts.
 */
export type LocaleRollout = 'off' | 'admin' | 'public';
export const LOCALE_ROLLOUT: LocaleRollout = 'admin';
