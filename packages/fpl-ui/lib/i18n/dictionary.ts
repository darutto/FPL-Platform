import { en } from './en';
import { es } from './es';
import type { Locale } from './locale';

export type DictKey = keyof typeof es;
export type TVars = Record<string, string | number>;

const DICTIONARIES: Record<Locale, Record<DictKey, string>> = { es, en };

/** The text for `key` in `locale`, with `{name}` placeholders filled from `vars`. Pure: usable outside React. */
export function translate(locale: Locale, key: DictKey, vars?: TVars): string {
  const text = DICTIONARIES[locale][key] ?? es[key];
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole));
}

export const DICTIONARY_LOCALES = DICTIONARIES;
