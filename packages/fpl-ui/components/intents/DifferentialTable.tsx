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
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: DifferentialPicksMeta;
}

export default function DifferentialTable({ data }: Props) {
  const { ownership_threshold, picks } = data;
  if (picks.length === 0) return null;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coralSoft.border}`}>
      {/* Header — corner triangle ornament, accent title */}
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-coral-soft/20 flex items-center justify-between">
        <TriangleField color={ACCENT_HEX.coralSoft} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          Diferenciales
        </span>
        <span className="relative z-10 text-xs text-bf-gray">
          &lt;{ownership_threshold.toFixed(1)}% de propietarios
        </span>
      </div>

      {/* Column labels */}
      <div className="grid grid-cols-[1.5rem_1fr_auto_auto_auto] gap-x-3 px-4 py-1.5 border-b border-white/10 text-[10px] font-bold text-bf-gray uppercase tracking-wide bg-white/[0.025]">
        <span>#</span>
        <span>Jugador</span>
        <span className="text-right">Prop</span>
        <span className="text-right">Precio</span>
        <span className="text-right">Pts</span>
      </div>

      {/* Rows — banded (DS zebra) */}
      <div>
        {picks.map((entry, idx) => (
          <DiffRow key={entry.rank} entry={entry} banded={idx % 2 === 0} />
        ))}
      </div>
    </div>
  );
}

function DiffRow({ entry, banded }: { entry: DifferentialEntry; banded: boolean }) {
  const { rank, web_name, team_short, position, ownership, now_cost, position_score } =
    entry;

  return (
    <div
      className={`grid grid-cols-[1.5rem_1fr_auto_auto_auto] gap-x-3 items-center px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}
    >
      {/* Rank — display numeral, fading down the list */}
      <span
        className="text-base font-display tracking-tighter text-bf-coral-soft leading-none"
        style={{ opacity: Math.max(0.4, 1 - (rank - 1) * 0.12) }}
      >
        {rank}
      </span>

      {/* Player */}
      <div className="min-w-0">
        <span className="font-bold text-white truncate">{web_name}</span>
        <span className="ml-1.5 text-[11px] text-bf-gray">
          {team_short} · {position}
        </span>
      </div>

      {/* Ownership */}
      <span className="text-xs text-bf-gray tabular-nums">
        {formatOwnership(ownership)}
      </span>

      {/* Price */}
      <span className="text-xs text-bf-text/80 tabular-nums">
        {formatCost(now_cost)}
      </span>

      {/* Score — hero metric in display face */}
      <span className="font-display text-base tracking-tighter text-bf-coral-soft tabular-nums text-right leading-none">
        {formatPositionScore(position_score)}
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

/** Format position score when present, otherwise show a stable placeholder. */
export function formatPositionScore(position_score?: number | null): string {
  return typeof position_score === 'number' ? position_score.toFixed(1) : '--';
}
