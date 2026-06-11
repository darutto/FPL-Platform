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
 * Tier badge colours match CaptainCard: see lib/theme TIER_CONFIG.
 */
import type { RankedCaptainEntry } from '@/lib/types';
import { TIER_CONFIG, TIER_BADGE_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: RankedCaptainEntry[];
}

export default function RankingTable({ data }: Props) {
  if (data.length === 0) return null;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.gold.border}`}>
      {/* Header — triangle ornament peeks from the corner (tables get the
          ornament only here, never behind data rows) */}
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-gold/20">
        <TriangleField color={ACCENT_HEX.gold} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          Candidatos a capitán
        </span>
      </div>

      {/* Rows — banded (DS zebra), no hairline dividers */}
      <div>
        {data.map((entry, idx) => (
          <RankRow key={entry.rank} entry={entry} banded={idx % 2 === 0} />
        ))}
      </div>
    </div>
  );
}

function RankRow({ entry, banded }: { entry: RankedCaptainEntry; banded: boolean }) {
  const { rank, web_name, team_short, captain_score, tier, set_piece_notes } = entry;
  const { label, icon, badgeClass } = TIER_CONFIG[tier] ?? TIER_CONFIG.low_confidence;

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}>
      {/* Rank — display numeral, fading down the list */}
      <span
        className="w-6 text-base font-display tracking-tighter text-bf-gold flex-shrink-0 leading-none"
        style={{ opacity: Math.max(0.4, 1 - (rank - 1) * 0.12) }}
      >
        {rank}
      </span>

      {/* Player + team */}
      <div className="flex-1 min-w-0">
        <span className="font-bold text-white truncate">{web_name}</span>
        <span className="ml-1.5 text-xs text-bf-gray">{team_short}</span>
        {set_piece_notes.length > 0 && (
          <span className="ml-1.5 text-[10px] text-bf-turquoise" title={set_piece_notes.join(', ')}>
            ★
          </span>
        )}
      </div>

      {/* Score — hero metric */}
      <span className="font-display text-base tracking-tighter text-bf-gold flex-shrink-0 leading-none">
        {captain_score.toFixed(1)}
      </span>

      {/* Tier badge */}
      <span className={`flex-shrink-0 ${TIER_BADGE_BASE} ${badgeClass}`}>
        <span className="text-[11px] leading-none">{icon}</span>
        {label}
      </span>
    </div>
  );
}
