/**
 * Europe from the StrikerAPI source: what the calendar's coverage note says. "Confirmed up to" only when all
 * three European lists are whole, with the earliest bound; otherwise "partial". Payloads without `data.europe`
 * (flag off) keep exactly the note they had.
 */
import { coverageNote, parseCompetitions } from '@/lib/fixture-competitions';

const payload = (data: Record<string, unknown>) => ({ available: true, tier: 'premium', data, teams: {} });
const comp = (status: string, until: string | null) => ({ status, complete_as_of: until });
const europe = (ucl: unknown, uel: unknown, uecl: unknown) => ({
  provenance: 'strikerapi_calendar',
  competitions: { UCL: ucl, UEL: uel, UECL: uecl },
});

describe('the coverage note with Europe from the new source', () => {
  test('all three whole: confirmed up to the earliest bound', () => {
    const view = parseCompetitions(
      payload({ europe: europe(comp('complete', '2027-01-27'), comp('complete', '2027-01-28'), comp('complete', '2026-12-17')) }),
    );
    expect(coverageNote(view, 'es')).toBe('Europa confirmada hasta el 17/12/2026');
    expect(coverageNote(view, 'en')).toBe('Europe confirmed up to 17/12/2026');
  });

  test.each([
    [comp('partial', null)],
    [comp('missing', null)],
    [comp('stale', '2027-01-27')],
    [comp('complete', 'January')],
  ])('one that is not whole (%o): partial, never a date', (bad) => {
    const view = parseCompetitions(
      payload({ europe: europe(comp('complete', '2027-01-27'), bad, comp('complete', '2027-01-28')) }),
    );
    expect(coverageNote(view, 'es')).toBe('Cobertura parcial de Europa');
  });

  test('without data.europe the note is what it was: the manual list line, or nothing', () => {
    expect(coverageNote(parseCompetitions(payload({})), 'es')).toBeNull();
    const manual = parseCompetitions(payload({ manual: { list_date: '2026-10-28' } }));
    expect(coverageNote(manual, 'es')).toBe('Cobertura parcial · Europa según la lista del 28/10/2026');
    expect(manual).not.toHaveProperty('europe');
  });
});
