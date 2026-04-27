/**
 * DifferentialTable — structured rendering for differential_picks OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome     === 'ok'
 *   response.intent      === 'differential_picks'
 *   response.differential !== null
 *
 * Consumes from DifferentialPicksMeta (stable conditional fields only):
 *   ownership_threshold, top_n, picks[].rank, picks[].web_name,
 *   picks[].team_short, picks[].position, picks[].ownership,
 *   picks[].now_cost, picks[].position_score, picks[].is_home
 *
 * Ranking is by position_score (Phase 8a1 Layer 2 heuristic).
 * captain_score is present in the type but not displayed — position_score
 * is the operative ranking signal for differential selection.
 *
 * now_cost is in tenths of £ (e.g. 75 → £7.5m).
 * ownership is a float percentage (e.g. 1.0 → "1.0%").
 */
import type { DifferentialPicksMeta, DifferentialEntry } from '@/lib/types';

interface Props {
  data: DifferentialPicksMeta;
}

export default function DifferentialTable({ data }: Props) {
  const { ownership_threshold, picks } = data;
  if (picks.length === 0) return null;

  return (
    <div className="mt-3 rounded-xl border border-gray-700 bg-gray-900/60 overflow-hidden text-sm">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-gray-700 flex items-center justify-between">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
          Diferenciales
        </span>
        <span className="text-xs text-gray-500">
          &lt;{ownership_threshold.toFixed(1)}% de propietarios
        </span>
      </div>

      {/* Column labels */}
      <div className="grid grid-cols-[1.5rem_1fr_auto_auto_auto] gap-x-3 px-4 py-1.5 border-b border-gray-800 text-[10px] text-gray-600 uppercase tracking-wide">
        <span>#</span>
        <span>Jugador</span>
        <span className="text-right">Prop</span>
        <span className="text-right">Precio</span>
        <span className="text-right">Pts</span>
      </div>

      {/* Rows */}
      <div className="divide-y divide-gray-800">
        {picks.map((entry) => (
          <DiffRow key={entry.rank} entry={entry} />
        ))}
      </div>
    </div>
  );
}

function DiffRow({ entry }: { entry: DifferentialEntry }) {
  const { rank, web_name, team_short, position, ownership, now_cost, position_score } =
    entry;

  return (
    <div className="grid grid-cols-[1.5rem_1fr_auto_auto_auto] gap-x-3 items-center px-4 py-2.5">
      {/* Rank */}
      <span className="text-xs font-mono text-gray-500">{rank}</span>

      {/* Player */}
      <div className="min-w-0">
        <span className="font-medium text-white truncate">{web_name}</span>
        <span className="ml-1.5 text-[11px] text-gray-500">
          {team_short} · {position}
        </span>
      </div>

      {/* Ownership */}
      <span className="text-xs text-gray-400 tabular-nums">
        {formatOwnership(ownership)}
      </span>

      {/* Price */}
      <span className="text-xs text-gray-300 tabular-nums">
        {formatCost(now_cost)}
      </span>

      {/* Score */}
      <span className="text-xs font-mono text-white tabular-nums">
        {position_score.toFixed(1)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported pure helpers — tested in __tests__/component-helpers.test.ts
// ---------------------------------------------------------------------------

/** Format ownership float as percentage string: 1.0 → "1.0%" */
export function formatOwnership(ownership: number): string {
  return `${ownership.toFixed(1)}%`;
}

/** Format now_cost (tenths of £) as price string: 75 → "£7.5m" */
export function formatCost(now_cost: number): string {
  return `£${(now_cost / 10).toFixed(1)}m`;
}
