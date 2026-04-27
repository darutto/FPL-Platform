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

interface Props {
  data: FixtureRunMeta;
}

export default function FixtureRunTable({ data }: Props) {
  const { web_name, team_short, position, fixtures } = data;
  if (fixtures.length === 0) return null;

  return (
    <div className="mt-3 rounded-xl border border-gray-700 bg-gray-900/60 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2 text-sm">
        <span className="font-semibold text-white">{web_name}</span>
        <span className="text-gray-500">·</span>
        <span className="text-gray-400 text-xs">{team_short}</span>
        <span className="text-gray-500">·</span>
        <span className="text-gray-400 text-xs">{position}</span>
      </div>

      {/* Fixture chips */}
      <div className="flex flex-wrap gap-2">
        {fixtures.map((f) => (
          <FixtureChip key={fixtureKey(f)} entry={f} />
        ))}
      </div>

      {/* Legend */}
      <FdrLegend />
    </div>
  );
}

function FixtureChip({ entry }: { entry: FixtureEntry }) {
  const { gameweek, opponent_short, is_home, difficulty } = entry;
  const color = fdrColor(difficulty);
  const venue = formatVenue(is_home);

  return (
    <div
      className="flex flex-col items-center rounded-lg px-2.5 py-1.5 min-w-[52px]"
      style={{ backgroundColor: `${color}20`, borderColor: `${color}60`, borderWidth: 1 }}
    >
      <span className="text-[10px] text-gray-500">GW{gameweek}</span>
      <span
        className="text-xs font-semibold"
        style={{ color }}
      >
        {opponent_short}
      </span>
      <span className="text-[10px] text-gray-500">{venue}</span>
    </div>
  );
}

function FdrLegend() {
  const levels = [1, 2, 3, 4, 5] as const;
  return (
    <div className="flex items-center gap-2 pt-1">
      <span className="text-[10px] text-gray-600">FDR:</span>
      {levels.map((d) => (
        <span
          key={d}
          className="text-[10px] rounded px-1"
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
