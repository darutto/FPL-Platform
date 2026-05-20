/**
 * InjuriesTable — structured rendering for @injuries turns.
 *
 * Rendered beneath final_text when response.resource_rows is non-null and
 * resource === 'injuries'.
 *
 * Columns: player (web_name + team_short + position), status badge,
 * chance_of_playing %, news (clamped to ~2 lines), news_added (relative).
 */
import type { ResourceRows, InjuryRow } from '@/lib/types';

interface Props {
  data: ResourceRows;
}

export default function InjuriesTable({ data }: Props) {
  const rows = data.rows as InjuryRow[];

  return (
    <div className="mt-3 rounded-xl border border-gray-700 bg-gray-900/60 overflow-hidden text-sm">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-gray-700">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
          {data.title}
        </span>
      </div>

      {/* Rows or empty state */}
      {rows.length === 0 ? (
        <p className="px-4 py-3 text-xs text-gray-500">Sin lesiones reportadas</p>
      ) : (
        <div className="divide-y divide-gray-800">
          {rows.map((row, idx) => (
            <InjuryRow key={`${row.web_name}-${idx}`} row={row} />
          ))}
        </div>
      )}
    </div>
  );
}

function InjuryRow({ row }: { row: InjuryRow }) {
  const { web_name, team_short, position, status_label, chance_of_playing, news, news_added } = row;
  const { className: badgeClass, label: badgeLabel } = resolveStatusBadge(status_label);
  const chanceText = chance_of_playing != null ? `${chance_of_playing}%` : '—';
  const dateText = news_added != null ? formatRelativeDate(news_added) : '—';

  return (
    <div className="flex items-start gap-3 px-4 py-2.5">
      {/* Player info */}
      <div className="flex-shrink-0 w-36 min-w-0">
        <span className="font-medium text-white truncate block">{web_name}</span>
        <span className="text-xs text-gray-500">
          {team_short} · {position}
        </span>
      </div>

      {/* Status badge */}
      <span
        className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 mt-0.5 ${badgeClass}`}
      >
        {badgeLabel}
      </span>

      {/* Chance */}
      <span className="text-xs text-gray-400 flex-shrink-0 w-8 text-center mt-0.5">
        {chanceText}
      </span>

      {/* News + date */}
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-300 line-clamp-2">{news}</p>
        {dateText !== '—' && (
          <p className="text-[10px] text-gray-600 mt-0.5">{dateText}</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveStatusBadge(statusLabel: string): { className: string; label: string } {
  const lower = statusLabel.toLowerCase();
  if (lower.includes('injur') || lower.includes('suspend') || lower.includes('unavailable')) {
    return { className: 'bg-red-900/60 text-red-300', label: statusLabel };
  }
  if (lower.includes('doubt') || lower.includes('75') || lower.includes('50') || lower.includes('25')) {
    return { className: 'bg-amber-900/60 text-amber-300', label: statusLabel };
  }
  if (lower === 'available' || lower === 'fit') {
    return { className: 'bg-emerald-900/60 text-emerald-300', label: statusLabel };
  }
  // Default — amber for anything uncertain
  return { className: 'bg-amber-900/60 text-amber-300', label: statusLabel };
}

/**
 * Formats an ISO date string as a simple relative string in Spanish.
 * Falls back to the raw string if parsing fails.
 */
function formatRelativeDate(isoString: string): string {
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    const now = Date.now();
    const diffMs = now - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return 'hoy';
    if (diffDays === 1) return 'hace 1 día';
    if (diffDays < 30) return `hace ${diffDays} días`;
    const diffWeeks = Math.floor(diffDays / 7);
    if (diffWeeks < 8) return `hace ${diffWeeks} semanas`;
    const diffMonths = Math.floor(diffDays / 30);
    return `hace ${diffMonths} meses`;
  } catch {
    return isoString;
  }
}
