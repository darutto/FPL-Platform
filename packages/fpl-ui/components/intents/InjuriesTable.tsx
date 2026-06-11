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
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX, PILL_BASE, STATUS_TONE_CLASSES } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: ResourceRows;
}

export default function InjuriesTable({ data }: Props) {
  const rows = data.rows as InjuryRow[];

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coralSoft.border}`}>
      {/* Header — corner triangle ornament */}
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-coral-soft/20">
        <TriangleField color={ACCENT_HEX.coralSoft} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          {data.title}
        </span>
      </div>

      {/* Rows or empty state */}
      {rows.length === 0 ? (
        <p className="px-4 py-3 text-xs text-bf-gray">Sin lesiones reportadas</p>
      ) : (
        <div>
          {rows.map((row, idx) => (
            <InjuryRow key={`${row.web_name}-${idx}`} row={row} banded={idx % 2 === 0} />
          ))}
        </div>
      )}
    </div>
  );
}

function InjuryRow({ row, banded }: { row: InjuryRow; banded: boolean }) {
  const { web_name, team_short, position, status_label, chance_of_playing, news, news_added } = row;
  const { className: badgeClass, label: badgeLabel } = resolveStatusBadge(status_label);
  const chanceText = chance_of_playing != null ? `${chance_of_playing}%` : '—';
  const dateText = news_added != null ? formatRelativeDate(news_added) : '—';

  return (
    <div className={`flex items-start gap-3 px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}>
      {/* Player info */}
      <div className="flex-shrink-0 w-36 min-w-0">
        <span className="font-bold text-white truncate block">{web_name}</span>
        <span className="text-xs text-bf-gray">
          {team_short} · {position}
        </span>
      </div>

      {/* Status badge */}
      <span className={`flex-shrink-0 mt-0.5 ${PILL_BASE} ${badgeClass}`}>
        {badgeLabel}
      </span>

      {/* Chance */}
      <span className="text-xs text-bf-gray flex-shrink-0 w-8 text-center mt-0.5">
        {chanceText}
      </span>

      {/* News + date */}
      <div className="flex-1 min-w-0">
        <p className="text-xs text-bf-text/80 line-clamp-2">{news}</p>
        {dateText !== '—' && (
          <p className="text-[10px] text-bf-gray/70 mt-0.5">{dateText}</p>
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
    return { className: STATUS_TONE_CLASSES.bad, label: statusLabel };
  }
  if (lower.includes('doubt') || lower.includes('75') || lower.includes('50') || lower.includes('25')) {
    return { className: STATUS_TONE_CLASSES.warn, label: statusLabel };
  }
  if (lower === 'available' || lower === 'fit') {
    return { className: STATUS_TONE_CLASSES.good, label: statusLabel };
  }
  // Default — warn tone for anything uncertain
  return { className: STATUS_TONE_CLASSES.warn, label: statusLabel };
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
