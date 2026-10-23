/**
 * The language policy in one table: rollout x who is asking x cookie x browser language.
 * resolveLocale() is the only place this is decided; the layout, the provider and the
 * request bodies all use it.
 */
import { canChooseLocale, localeFromAcceptLanguage, resolveLocale, type Locale } from '@/lib/i18n/locale';
import type { LocaleRollout } from '@/lib/features';

const ROLLOUTS: LocaleRollout[] = ['off', 'admin', 'public'];

describe('localeFromAcceptLanguage', () => {
  test.each([
    ['en-GB,en;q=0.9', 'en'],
    ['en-US', 'en'],
    ['es-MX,es;q=0.9,en;q=0.8', 'es'],
    ['en;q=0.4,es;q=0.9', 'es'],
    ['fr-FR,en;q=0.5', 'en'],
    ['fr-FR,de', null],
    ['es;q=0,en;q=0.3', 'en'],
    ['', null],
    [null, null],
  ])('%s -> %s', (header, expected) => {
    expect(localeFromAcceptLanguage(header)).toBe(expected);
  });
});

describe('resolveLocale', () => {
  test('rollout off: Spanish for everyone, whatever the cookie or the browser says', () => {
    for (const isAdmin of [true, false]) {
      expect(resolveLocale({ rollout: 'off', isAdmin, cookie: 'en', acceptLanguage: 'en-GB' })).toBe('es');
    }
  });

  test('rollout admin: an admin gets the cookie, else the browser language, else Spanish', () => {
    const facts = { rollout: 'admin' as const, isAdmin: true };
    expect(resolveLocale({ ...facts, cookie: 'en', acceptLanguage: 'es-ES' })).toBe('en');
    expect(resolveLocale({ ...facts, cookie: 'es', acceptLanguage: 'en-GB' })).toBe('es');
    expect(resolveLocale({ ...facts, cookie: null, acceptLanguage: 'en-GB,en;q=0.9' })).toBe('en');
    expect(resolveLocale({ ...facts, cookie: null, acceptLanguage: 'es-ES' })).toBe('es');
    expect(resolveLocale({ ...facts, cookie: null, acceptLanguage: 'fr-FR' })).toBe('es');
    expect(resolveLocale({ ...facts })).toBe('es');
  });

  test('rollout admin: a non-admin with an en cookie, or an English browser, still gets Spanish', () => {
    expect(resolveLocale({ rollout: 'admin', isAdmin: false, cookie: 'en', acceptLanguage: 'en-GB' })).toBe('es');
  });

  test('rollout admin: signing out (no longer admin) returns Spanish', () => {
    const signedIn = { rollout: 'admin' as const, isAdmin: true, cookie: 'en' };
    expect(resolveLocale(signedIn)).toBe('en');
    expect(resolveLocale({ ...signedIn, isAdmin: false })).toBe('es');
  });

  test('rollout public: everyone chooses, admin or not', () => {
    for (const isAdmin of [true, false]) {
      expect(resolveLocale({ rollout: 'public', isAdmin, cookie: 'en' })).toBe('en');
      expect(resolveLocale({ rollout: 'public', isAdmin, acceptLanguage: 'en-GB' })).toBe('en');
      expect(resolveLocale({ rollout: 'public', isAdmin, cookie: 'es', acceptLanguage: 'en-GB' })).toBe('es');
    }
  });

  test('a cookie that is not a supported locale is ignored', () => {
    expect(resolveLocale({ rollout: 'public', isAdmin: false, cookie: 'fr', acceptLanguage: 'en-GB' })).toBe('en');
    expect(resolveLocale({ rollout: 'public', isAdmin: false, cookie: 'EN' })).toBe('es');
  });

  test('the full matrix only returns es or en, and es whenever choosing is not allowed', () => {
    const cookies = [undefined, null, 'en', 'es', 'fr'];
    const languages = [undefined, 'en-GB', 'es-ES', 'fr-FR'];
    for (const rollout of ROLLOUTS) {
      for (const isAdmin of [true, false]) {
        for (const cookie of cookies) {
          for (const acceptLanguage of languages) {
            const locale: Locale = resolveLocale({ rollout, isAdmin, cookie, acceptLanguage });
            expect(['es', 'en']).toContain(locale);
            if (!canChooseLocale({ rollout, isAdmin })) expect(locale).toBe('es');
          }
        }
      }
    }
  });
});
