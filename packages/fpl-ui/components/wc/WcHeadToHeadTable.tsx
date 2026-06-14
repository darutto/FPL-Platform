/**
 * WcHeadToHeadTable — structured rendering for the head-to-head record
 * between two national teams (get_head_to_head).
 *
 * Rendered beneath final_text when response.outcome === 'ok' and
 * response.head_to_head is present (see lib/wc-intent-renderer.ts
 * selectWcIntentView). This feed only covers matches played within this
 * World Cup — ``note`` (always present) makes that scope explicit, and is
 * shown even when ``matches`` is empty.
 */
import type { WcHeadToHeadPayload, WcMatchRow } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcHeadToHeadPayload;
}

export default function WcHeadToHeadTable({ data }: Props) {
  const first = data.matches[0];
  const title = first ? `Enfrentamientos: ${first.home_team} vs ${first.away_team}` : 'Enfrentamientos directos';

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.gray.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-white/10">
        <TriangleField color={ACCENT_HEX.gray} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          {title}
        </span>
      </div>

      {data.matches.length > 0 && (
        <div>
          {data.matches.map((row, idx) => (
            <H2HRow key={row.match_id} row={row} banded={idx % 2 === 0} />
          ))}
        </div>
      )}

      <div className="px-4 py-2.5 text-xs text-bf-gray border-t border-white/5">{data.note}</div>
    </div>
  );
}

function formatDate(date: string | null): string {
  if (!date) return '';
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' });
}

function H2HRow({ row, banded }: { row: WcMatchRow; banded: boolean }) {
  const hasScore = row.home_score != null && row.away_score != null;

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="font-bold text-white truncate">{row.home_team}</span>
          <span className="font-display text-sm tracking-tighter text-bf-gray flex-shrink-0 px-2">
            {hasScore ? `${row.home_score} – ${row.away_score}` : 'vs'}
          </span>
          <span className="font-bold text-white truncate text-right">{row.away_team}</span>
        </div>
      </div>
      <div className="flex-shrink-0 text-right space-y-0.5">
        <div className="text-[10px] font-bold uppercase tracking-wide text-bf-gray">{row.status}</div>
        {row.date && <div className="text-[10px] text-bf-gray">{formatDate(row.date)}</div>}
      </div>
    </div>
  );
}
