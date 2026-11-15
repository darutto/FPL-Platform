/**
 * The UI literal ratchet (English version plan, section 4.2).
 *
 * Every Spanish literal the UI source still carries outside the dictionary is listed in
 * `__tests__/support/ui-spanish-literals.baseline.json`, by file. The list may only get shorter:
 *
 *   - a Spanish literal that is NOT in the baseline fails this test. Put the text in `lib/i18n/{es,en}.ts` and read
 *     it with `useT()` / `translate()`. Swapping one Spanish literal for another cannot slip through, because the
 *     comparison is by text, not by count.
 *   - a baseline entry whose literal is no longer in the code also fails: delete it. That keeps a finished slice from
 *     leaving a stale allowance behind that would quietly let the same Spanish come back.
 *
 * To rewrite the baseline after translating (it only ever shrinks in a normal change):
 *     UPDATE_LITERAL_BASELINE=1 npx jest __tests__/ui-literal-ratchet
 * A diff that GROWS the baseline is a decision for review, not a way round the test.
 */
import fs from 'node:fs';
import path from 'node:path';

import { isSpanish, scanSpanishLiterals } from './support/spanish-literals';

const ROOT = path.resolve(__dirname, '..');
const BASELINE = path.join(__dirname, 'support', 'ui-spanish-literals.baseline.json');

const found = scanSpanishLiterals(ROOT);

if (process.env.UPDATE_LITERAL_BASELINE) {
  fs.writeFileSync(BASELINE, `${JSON.stringify(found, null, 2)}\n`, 'utf8');
}
const baseline: Record<string, string[]> = JSON.parse(fs.readFileSync(BASELINE, 'utf8'));

const flat = (map: Record<string, string[]>) => Object.entries(map).flatMap(([file, texts]) => texts.map((t) => `${file} :: ${t}`));
const inBaseline = new Set(flat(baseline));
const inCode = new Set(flat(found));

test('no new Spanish literal outside the dictionary', () => {
  const added = [...inCode].filter((entry) => !inBaseline.has(entry));
  expect(added).toEqual([]);
});

test('the baseline lists nothing that is no longer in the code', () => {
  const stale = [...inBaseline].filter((entry) => !inCode.has(entry));
  expect(stale).toEqual([]);
});

describe('what counts as Spanish', () => {
  test.each([
    'Reintentar', 'No se pudo cargar la plantilla', 'Conecta tu equipo FPL', 'Tu plantilla', 'Más vendidos', '¿Quién?', 'La temporada aún no ha comenzado',
    'Cargando…', 'hace 3 días',
  ])('%s is', (text) => expect(isSpanish(text)).toBe(true));

  test.each([
    'Retry', 'Where to attack', 'rounded-md border border-white/10', 'text-bf-gray', 'en-GB', 'es-ES', 'GW12', 'Cole Palmer', 'a', '—',
    'Tap a player', '/api/fpl-squad', 'aria-pressed', 'Loading squad…', 'player-zonas-chips', 'flex-1 min-w-0 overflow-y-auto px-4 py-4 space-y-3',
  ])('%s is not', (text) => expect(isSpanish(text)).toBe(false));
});
