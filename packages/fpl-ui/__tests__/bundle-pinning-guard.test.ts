/**
 * Guard: a suite that reads the committed fixture-outlook bundle must either pin it or be listed as a live reader.
 *
 * `lib/data/fixture-outlook-*.json` is regenerated weekly by a bot PR. A suite that snapshots text derived from it
 * (the "updated on ..." stamp, the short-sample warning, verdicts) fails the Monday that PR merges. Suites listed in
 * LIVE_READERS assert invariants of whatever bundle ships, so they hold across a refresh; adding a suite here is a
 * claim that it does, and belongs in review.
 */
import fs from 'node:fs';
import path from 'node:path';

const DIR = __dirname;
const REAL = /fixture-outlook-real|buildRealSeasonOutlook|REAL_SEASON_GENERATION|fixture-outlook-20\d\d-\d\d/;
const PINNED = /jest\.mock\(\s*['"]@\/lib\/data\/fixture-outlook-2026-27\.json['"]/;

/** Read the live bundle on purpose: invariants only, no snapshot of its content. */
const LIVE_READERS = new Set([
  'fixture-chat-links-canonical.test.ts',
  'fixture-outlook-real.test.ts',
  'fixtures-board-axis-switch.test.tsx',
  'i18n-fixtures-lib.test.ts',
]);

const suites = fs.readdirSync(DIR).filter((f) => /\.test\.tsx?$/.test(f) && f !== path.basename(__filename));

test('every suite that reads the real bundle pins it or is a declared live reader', () => {
  const unguarded = suites.filter((file) => {
    const text = fs.readFileSync(path.join(DIR, file), 'utf8');
    return REAL.test(text) && !PINNED.test(text) && !LIVE_READERS.has(file);
  });
  expect(unguarded).toEqual([]);
});

test('the live-reader list names only suites that still exist and still read the bundle', () => {
  const stale = [...LIVE_READERS].filter((file) => {
    const full = path.join(DIR, file);
    return !fs.existsSync(full) || !REAL.test(fs.readFileSync(full, 'utf8')) || PINNED.test(fs.readFileSync(full, 'utf8'));
  });
  expect(stale).toEqual([]);
});
