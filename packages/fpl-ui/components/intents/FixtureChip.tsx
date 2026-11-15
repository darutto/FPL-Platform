/**
 * The plain FDR fixture chip («J11 / FUL (L) · 2») and its pure helpers.
 *
 * Today the chip is only the fixture strip's placeholder while its outlook bundle loads
 * (PlayerFixtureStrip); every finished strip draws the /fixtures timeline tiles instead.
 * The helpers are shared: fixtureKey (DGW-safe React key), formatVenue (L/V, H/A),
 * fdrColor (the V2_MVP_ROADMAP FDR ramp, deliberately inline, not a theme token).
 */
import type { FixtureEntry } from '@/lib/types';
import { useLocale } from '@/lib/i18n/LocaleProvider';
import { gwLabel, venueLabel } from '@/lib/fixture-outlook-format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';

export function FixtureChip({ entry }: { entry: FixtureEntry }) {
  const { gameweek, opponent_short, is_home, difficulty } = entry;
  const { locale } = useLocale();
  const color = fdrColor(difficulty);
  const venue = formatVenue(is_home, locale);

  return (
    <div className="flex flex-col items-stretch rounded-md overflow-hidden min-w-[60px] bg-white/[0.04] border border-white/10">
      <span className="px-1.5 py-0.5 text-center text-[9px] font-bold uppercase tracking-wider text-bf-gray bg-white/[0.04] border-b border-white/5">
        {gwLabel(gameweek, locale)}
      </span>
      <span
        className="px-1.5 py-1 text-center text-xs font-extrabold tracking-tight"
        style={{ backgroundColor: `${color}33`, color }}
      >
        {opponent_short} ({venue}) · {difficulty}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pure helpers — tested in __tests__/component-helpers.test.ts
// ---------------------------------------------------------------------------

/** FDR difficulty → hex colour (V2_MVP_ROADMAP.md spec). */
export function fdrColor(difficulty: 1 | 2 | 3 | 4 | 5): string {
  const COLORS: Record<1 | 2 | 3 | 4 | 5, string> = {
    1: '#2ecc71',
    2: '#a8d8a8',
    3: '#f7f7a8',
    4: '#f4a262',
    5: '#e74c3c',
  };
  return COLORS[difficulty];
}

/** Venue abbreviation: Spanish true → 'L' (local) / false → 'V' (visitante); English 'H' / 'A'. */
export function formatVenue(is_home: boolean, locale: Locale = DEFAULT_LOCALE): string {
  return venueLabel(is_home, locale);
}

/**
 * Stable composite key for a FixtureEntry — safe for double gameweeks.
 *
 * gameweek alone is NOT unique in DGWs: a player can have two fixtures in
 * the same GW against different opponents. This key combines all three
 * identity fields so DGW rows are always distinct.
 *
 * Format: "{gw}-{opponent}-{H|A}"  e.g. "29-ARS-H", "29-MUN-A"
 */
export function fixtureKey(entry: FixtureEntry): string {
  return `${entry.gameweek}-${entry.opponent_short}-${entry.is_home ? 'H' : 'A'}`;
}
