/**
 * Dates and "how long ago" in both languages. Spanish must print exactly what the components
 * printed before the helper existed (the original call sites are reproduced here as the oracle).
 */
import { formatDateTime, formatDayMonth, formatDaysAgo, formatUtcDate } from '@/lib/i18n/format';
import { formatRelativeDate } from '@/components/intents/InjuriesTable';
import { formatGeneratedAt } from '@/lib/fixture-outlook-provenance';

const DAY = 86_400_000;

describe('formatDaysAgo', () => {
  test.each([
    [0, 'hoy', 'today'],
    [1, 'hace 1 día', '1 day ago'],
    [2, 'hace 2 días', '2 days ago'],
    [29, 'hace 29 días', '29 days ago'],
    [30, 'hace 4 semanas', '4 weeks ago'],
    [55, 'hace 7 semanas', '7 weeks ago'],
    [56, 'hace 1 meses', '1 month ago'],
    [90, 'hace 3 meses', '3 months ago'],
  ])('%i days', (days, es, en) => {
    expect(formatDaysAgo('es', days)).toBe(es);
    expect(formatDaysAgo('en', days)).toBe(en);
  });

  test('the injuries table keeps its Spanish default and follows the locale when given one', () => {
    const iso = new Date(Date.now() - 5 * DAY - 1000).toISOString();
    expect(formatRelativeDate(iso)).toBe('hace 5 días');
    expect(formatRelativeDate(iso, 'en')).toBe('5 days ago');
    expect(formatRelativeDate('not a date')).toBe('not a date');
  });
});

describe('dates', () => {
  const when = new Date('2026-08-21T18:30:00Z');

  test('Spanish is the es-ES Intl output the cards used', () => {
    expect(formatDayMonth('es', when)).toBe(when.toLocaleDateString('es-ES', { day: 'numeric', month: 'short' }));
    expect(formatDateTime('es', when)).toBe(
      when.toLocaleString('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }),
    );
  });

  test('English uses British formatting', () => {
    expect(formatDayMonth('en', when)).toBe(when.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }));
    expect(formatDayMonth('en', when)).toMatch(/^21 Aug/);
  });

  test('the fixed-month UTC date keeps the Spanish list, and has an English one', () => {
    expect(formatUtcDate('es', new Date('2026-09-08T22:14:03Z'))).toBe('8 sep 2026');
    expect(formatUtcDate('es', new Date('2026-01-31T00:00:00Z'))).toBe('31 ene 2026');
    expect(formatUtcDate('en', new Date('2026-09-08T22:14:03Z'))).toBe('8 Sep 2026');
    expect(formatGeneratedAt('2026-12-01T00:00:00Z')).toBe('1 dic 2026');
    expect(formatGeneratedAt('2026-12-01T00:00:00Z', 'en')).toBe('1 Dec 2026');
  });
});
