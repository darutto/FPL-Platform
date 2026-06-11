/**
 * FixtureRunTable — structured rendering for player_fixture_run OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome     === 'ok'
 *   response.intent      === 'player_fixture_run'
 *   response.fixture_run !== null
 *
 * Consumes from FixtureRunMeta (stable conditional fields only):
 *   web_name, team_short, position, horizon, current_gameweek,
 *   fixtures[].gameweek, fixtures[].opponent_short,
 *   fixtures[].is_home, fixtures[].difficulty
 *
 * FDR colour scale (from V2_MVP_ROADMAP.md):
 *   1=#2ecc71 (easy) … 5=#e74c3c (hard)
 *   Applied as inline background colours so the exact spec values are used.
 *
 * Venue labels are Spanish (L=local / V=visitante).
 */
import type { FixtureRunMeta, FixtureEntry } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: FixtureRunMeta;
}

export default function FixtureRunTable({ data }: Props) {
  const { web_name, team_short, position, fixtures } = data;
  if (fixtures.length === 0) return null;

  return (
    <div className={`mt-3 ${CARD_BASE} ${CARD_ACCENT.gold.border}`}>
      <TriangleField color={ACCENT_HEX.gold} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2 text-sm">
          <span className="font-extrabold text-white">{web_name}</span>
          <span className="text-bf-gray/60">·</span>
          <span className="text-bf-gray text-xs font-bold tracking-wide">{team_short}</span>
          <span className="text-bf-gray/60">·</span>
          <span className="text-bf-gray text-xs">{position}</span>
        </div>

        {/* Fixture chips — DS .scout-fdr stack: GW strip on top, FDR pill below.
            Ramp colors come from fdrColor (V2 spec) — deliberately inline. */}
        <div className="flex flex-wrap gap-1.5">
          {fixtures.map((f) => (
            <FixtureChip key={fixtureKey(f)} entry={f} />
          ))}
        </div>

        {/* Legend */}
        <FdrLegend />
      </div>
    </div>
  );
}

function FixtureChip({ entry }: { entry: FixtureEntry }) {
  const { gameweek, opponent_short, is_home, difficulty } = entry;
  const color = fdrColor(difficulty);
  const venue = formatVenue(is_home);

  return (
    <div className="flex flex-col items-stretch rounded-md overflow-hidden min-w-[60px] bg-white/[0.04] border border-white/10">
      <span className="px-1.5 py-0.5 text-center text-[9px] font-bold uppercase tracking-wider text-bf-gray bg-white/[0.04] border-b border-white/5">
        GW{gameweek}
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

function FdrLegend() {
  const levels = [1, 2, 3, 4, 5] as const;
  return (
    <div className="flex items-center gap-2 pt-1">
      <span className="text-[10px] font-bold uppercase tracking-wider text-bf-gray/70">FDR:</span>
      {levels.map((d) => (
        <span
          key={d}
          className="text-[10px] font-bold rounded px-1.5 py-0.5"
          style={{ backgroundColor: `${fdrColor(d)}30`, color: fdrColor(d) }}
        >
          {d}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported pure helpers — tested in __tests__/component-helpers.test.ts
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

/** Spanish venue abbreviation: true → 'L' (local), false → 'V' (visitante). */
export function formatVenue(is_home: boolean): string {
  return is_home ? 'L' : 'V';
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
