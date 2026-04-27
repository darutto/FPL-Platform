/**
 * RankingTable — structured rendering for rank_candidates OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome        === 'ok'
 *   response.intent         === 'rank_candidates'
 *   response.captain_ranking !== null
 *
 * Consumes from RankedCaptainEntry[] (stable conditional fields only):
 *   rank, web_name, team_short, captain_score, tier, set_piece_notes
 *
 * Tier badge colours match CaptainCard: see TIER_CONFIG below.
 */
import type { RankedCaptainEntry, CaptainTier } from '@/lib/types';

interface Props {
  data: RankedCaptainEntry[];
}

export default function RankingTable({ data }: Props) {
  if (data.length === 0) return null;

  return (
    <div className="mt-3 rounded-xl border border-gray-700 bg-gray-900/60 overflow-hidden text-sm">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-gray-700">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
          Candidatos a capitán
        </span>
      </div>

      {/* Rows */}
      <div className="divide-y divide-gray-800">
        {data.map((entry) => (
          <RankRow key={entry.rank} entry={entry} />
        ))}
      </div>
    </div>
  );
}

function RankRow({ entry }: { entry: RankedCaptainEntry }) {
  const { rank, web_name, team_short, captain_score, tier, set_piece_notes } = entry;
  const { label, className } = TIER_CONFIG[tier] ?? TIER_CONFIG.low_confidence;

  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      {/* Rank */}
      <span className="w-5 text-xs font-mono text-gray-500 flex-shrink-0">{rank}</span>

      {/* Player + team */}
      <div className="flex-1 min-w-0">
        <span className="font-medium text-white truncate">{web_name}</span>
        <span className="ml-1.5 text-xs text-gray-500">{team_short}</span>
        {set_piece_notes.length > 0 && (
          <span className="ml-1.5 text-[10px] text-indigo-400" title={set_piece_notes.join(', ')}>
            ★
          </span>
        )}
      </div>

      {/* Score */}
      <span className="font-mono text-sm text-white flex-shrink-0">
        {captain_score.toFixed(1)}
      </span>

      {/* Tier badge */}
      <span className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${className}`}>
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tier config — matches CaptainCard
// ---------------------------------------------------------------------------

const TIER_CONFIG: Record<
  CaptainTier,
  { label: string; className: string }
> = {
  safe: {
    label: 'Favorito',
    className: 'bg-emerald-900/60 text-emerald-300',
  },
  upside: {
    label: 'Potencial',
    className: 'bg-amber-900/60 text-amber-300',
  },
  differential: {
    label: 'Diferencial',
    className: 'bg-violet-900/60 text-violet-300',
  },
  avoid: {
    label: 'Evitar',
    className: 'bg-red-900/60 text-red-300',
  },
  low_confidence: {
    label: 'Datos limitados',
    className: 'bg-slate-700/60 text-slate-300',
  },
};
