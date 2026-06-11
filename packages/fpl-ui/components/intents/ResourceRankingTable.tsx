/**
 * ResourceRankingTable — structured rendering for @resource metric-ranked turns.
 *
 * Rendered beneath final_text when response.resource_rows is non-null and
 * resource is one of: top_form, top_xg, top_points, top_minutes, popular.
 *
 * Columns: rank (#), player (web_name), team (team_short), position, value.
 * Style modelled after RankingTable.tsx — same border/divider/font hierarchy,
 * no tier badges, no set-piece notes.
 */
import type { ResourceRows, ResourceRankingRow } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX, RESOURCE_ACCENT, type Accent } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: ResourceRows;
}

export default function ResourceRankingTable({ data }: Props) {
  const rows = data.rows as ResourceRankingRow[];
  const accent: Accent = RESOURCE_ACCENT[data.resource] ?? 'turquoise';

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT[accent].border}`}>
      {/* Header — per-resource accent + corner triangle ornament */}
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-white/10">
        <TriangleField color={ACCENT_HEX[accent]} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          {data.title}
        </span>
      </div>

      {/* Rows or empty state */}
      {rows.length === 0 ? (
        <p className="px-4 py-3 text-xs text-bf-gray">Sin datos</p>
      ) : (
        <div>
          {rows.map((row, idx) => (
            <ResourceRankRow
              key={`${row.web_name}-${idx}`}
              rank={idx + 1}
              row={row}
              accent={accent}
              banded={idx % 2 === 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ResourceRankRow({
  rank,
  row,
  accent,
  banded,
}: {
  rank: number;
  row: ResourceRankingRow;
  accent: Accent;
  banded: boolean;
}) {
  const { web_name, team_short, position, value } = row;
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(2);

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}>
      {/* Rank — display numeral, fading down the list */}
      <span
        className={`w-6 text-base font-display tracking-tighter flex-shrink-0 leading-none ${CARD_ACCENT[accent].heading}`}
        style={{ opacity: Math.max(0.4, 1 - (rank - 1) * 0.12) }}
      >
        {rank}
      </span>

      {/* Player + team */}
      <div className="flex-1 min-w-0">
        <span className="font-bold text-white truncate">{web_name}</span>
        <span className="ml-1.5 text-xs text-bf-gray">{team_short}</span>
      </div>

      {/* Position */}
      <span className="text-xs text-bf-gray flex-shrink-0 w-8 text-center">{position}</span>

      {/* Value — hero metric in display face */}
      <span className={`font-display text-base tracking-tighter flex-shrink-0 text-right leading-none ${CARD_ACCENT[accent].heading}`}>
        {formatted}
      </span>
    </div>
  );
}
