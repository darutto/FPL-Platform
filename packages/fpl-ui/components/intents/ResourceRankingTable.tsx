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

interface Props {
  data: ResourceRows;
}

export default function ResourceRankingTable({ data }: Props) {
  const rows = data.rows as ResourceRankingRow[];

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
        <p className="px-4 py-3 text-xs text-gray-500">Sin datos</p>
      ) : (
        <div className="divide-y divide-gray-800">
          {rows.map((row, idx) => (
            <ResourceRankRow key={`${row.web_name}-${idx}`} rank={idx + 1} row={row} />
          ))}
        </div>
      )}
    </div>
  );
}

function ResourceRankRow({ rank, row }: { rank: number; row: ResourceRankingRow }) {
  const { web_name, team_short, position, value } = row;
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(2);

  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      {/* Rank */}
      <span className="w-5 text-xs font-mono text-gray-500 flex-shrink-0">{rank}</span>

      {/* Player + team */}
      <div className="flex-1 min-w-0">
        <span className="font-medium text-white truncate">{web_name}</span>
        <span className="ml-1.5 text-xs text-gray-500">{team_short}</span>
      </div>

      {/* Position */}
      <span className="text-xs text-gray-400 flex-shrink-0 w-8 text-center">{position}</span>

      {/* Value */}
      <span className="font-mono text-sm text-white flex-shrink-0 text-right">{formatted}</span>
    </div>
  );
}
