/**
 * WcFixturesTable — structured rendering for World Cup fixtures, results,
 * and live matches.
 *
 * Rendered beneath final_text when response.outcome === 'ok' and
 * response.fixtures is non-empty (see lib/wc-intent-renderer.ts
 * selectWcIntentView). Team names and status are already locale_es-localized
 * by the backend ("En vivo", "Finalizado", "Programado", ...).
 */
import type { WcMatchRow } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcMatchRow[];
  title?: string;
}

const LIVE_STATUSES = new Set(['En vivo', 'Primer tiempo', 'Segundo tiempo', 'Descanso', 'Prórroga', 'Penales']);

export default function WcFixturesTable({ data, title = 'Partidos' }: Props) {
  if (data.length === 0) return null;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coral.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-coral/20">
        <TriangleField color={ACCENT_HEX.coral} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          {title}
        </span>
      </div>

      <div>
        {data.map((row, idx) => (
          <MatchRow key={row.match_id} row={row} banded={idx % 2 === 0} />
        ))}
      </div>
    </div>
  );
}

function formatDate(date: string | null): string {
  if (!date) return '';
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' });
}

function MatchRow({ row, banded }: { row: WcMatchRow; banded: boolean }) {
  const hasScore = row.home_score != null && row.away_score != null;
  const hasPenalties = row.penalty_home != null && row.penalty_away != null;
  const isLive = LIVE_STATUSES.has(row.status);

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="font-bold text-white truncate">{row.home_team}</span>
          <span className="font-display text-sm tracking-tighter text-bf-coral flex-shrink-0 px-2 text-center">
            {hasScore ? `${row.home_score} – ${row.away_score}` : 'vs'}
            {hasPenalties && (
              <div className="text-[10px] text-bf-gray font-sans tracking-normal">
                pen {row.penalty_home}-{row.penalty_away}
              </div>
            )}
          </span>
          <span className="font-bold text-white truncate text-right">{row.away_team}</span>
        </div>
      </div>

      <div className="flex-shrink-0 text-right space-y-0.5">
        <div
          className={`text-[10px] font-bold uppercase tracking-wide ${
            isLive ? 'text-bf-coral' : 'text-bf-gray'
          }`}
        >
          {row.status}
          {isLive && row.minute != null && ` · ${row.minute}'`}
        </div>
        {!isLive && row.date && <div className="text-[10px] text-bf-gray">{formatDate(row.date)}</div>}
      </div>
    </div>
  );
}
