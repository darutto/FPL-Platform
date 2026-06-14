/**
 * WcFantasyTable — structured rendering for the FIFA Fantasy points
 * leaderboard (total_points, avg_points, form, price — distinct from goals).
 *
 * Rendered beneath final_text when response.outcome === 'ok' and
 * response.fantasy_top_players is non-empty (see
 * lib/wc-intent-renderer.ts selectWcIntentView). Already sorted by the
 * backend (total_points desc, then name); team/position are
 * locale_es-localized.
 */
import type { WcFantasyPlayerRow } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcFantasyPlayerRow[];
}

export default function WcFantasyTable({ data }: Props) {
  if (data.length === 0) return null;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.cyan.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-cyan/20">
        <TriangleField color={ACCENT_HEX.cyan} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          Mejores jugadores fantasy
        </span>
      </div>

      <div>
        {data.map((row, idx) => (
          <FantasyRow key={`${row.player}-${idx}`} rank={idx + 1} row={row} banded={idx % 2 === 0} />
        ))}
      </div>
    </div>
  );
}

function FantasyRow({ rank, row, banded }: { rank: number; row: WcFantasyPlayerRow; banded: boolean }) {
  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}>
      <span
        className="w-6 text-base font-display tracking-tighter text-bf-cyan flex-shrink-0 leading-none"
        style={{ opacity: Math.max(0.4, 1 - (rank - 1) * 0.12) }}
      >
        {rank}
      </span>

      <div className="flex-1 min-w-0">
        <span className="font-bold text-white truncate">{row.player}</span>
        {row.team && <span className="ml-1.5 text-xs text-bf-gray">{row.team}</span>}
        <span className="ml-1.5 text-[10px] text-bf-gray uppercase tracking-wide">{row.position}</span>
      </div>

      <div className="flex items-center gap-3 flex-shrink-0 text-right">
        <div className="leading-none">
          <span className="font-display text-base tracking-tighter text-bf-cyan">{row.total_points}</span>
          <span className="ml-1 text-[10px] text-bf-gray uppercase tracking-wide">Pts</span>
        </div>
        <div className="leading-none">
          <span className="font-display text-base tracking-tighter text-bf-text">{row.form}</span>
          <span className="ml-1 text-[10px] text-bf-gray uppercase tracking-wide">Forma</span>
        </div>
      </div>
    </div>
  );
}
