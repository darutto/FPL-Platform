/**
 * The English dictionary mirrors the Spanish one. `tsc` already fails a missing key
 * (en.ts is typed `typeof es`); this checks what the type cannot: no empty English text,
 * no English that is just the Spanish pasted in, and placeholders that match.
 */
import { en } from '@/lib/i18n/en';
import { es } from '@/lib/i18n/es';
import { translate, type DictKey } from '@/lib/i18n/dictionary';

/** Keys whose English is deliberately the same as the Spanish (a brand name, a code). Keep it short. */
const SAME_IN_BOTH = new Set<string>([]);

const keys = Object.keys(es) as DictKey[];
const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();

test('both dictionaries have exactly the same keys', () => {
  expect(Object.keys(en).sort()).toEqual([...keys].sort());
});

test.each(keys)('%s: English is non-empty, differs from Spanish and keeps the same placeholders', (key) => {
  expect(en[key].trim()).not.toBe('');
  if (!SAME_IN_BOTH.has(key)) expect(en[key]).not.toBe(es[key]);
  expect(placeholders(en[key])).toEqual(placeholders(es[key]));
});

test('translate returns the text of the requested language', () => {
  expect(translate('es', 'app.title')).toBe('FPL Asistente');
  expect(translate('en', 'app.title')).toBe('FPL Assistant · Bendito Fantasy');
});
