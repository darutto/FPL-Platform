'use client';

/**
 * The client side of the language policy. The server layout resolves the locale once
 * (resolveLocale) and hands it down; this holds it, lets an allowed visitor switch it, and
 * gives every component `useT()`. Without a provider (tests, isolated renders) the app is Spanish.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { translate, type DictKey, type TVars } from './dictionary';
import { DEFAULT_LOCALE, localeCookie, type Locale } from './locale';

interface LocaleContextValue {
  locale: Locale;
  /** The rollout lets this visitor choose (the toggle is shown). */
  canSwitch: boolean;
  setLocale: (next: Locale) => void;
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: DEFAULT_LOCALE,
  canSwitch: false,
  setLocale: () => {},
});

export function LocaleProvider({
  initialLocale,
  canSwitch,
  children,
}: {
  initialLocale: Locale;
  canSwitch: boolean;
  children: ReactNode;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  // A new server answer (sign-in/out, navigation) wins over whatever was chosen before.
  useEffect(() => setLocaleState(initialLocale), [initialLocale]);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback(
    (next: Locale) => {
      if (!canSwitch) return;
      try {
        document.cookie = localeCookie(next);
      } catch {
        // Cookies blocked: the choice still holds for this page view.
      }
      setLocaleState(next);
    },
    [canSwitch],
  );

  const value = useMemo(() => ({ locale, canSwitch, setLocale }), [locale, canSwitch, setLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}

/** `t('quota.day')`, `t('x', { n: 3 })`, in the current locale. */
export function useT(): (key: DictKey, vars?: TVars) => string {
  const { locale } = useLocale();
  return useCallback((key, vars) => translate(locale, key, vars), [locale]);
}
