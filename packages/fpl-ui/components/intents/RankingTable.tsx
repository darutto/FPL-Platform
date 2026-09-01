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
import type { RankedCaptainEntry, SquadExcludedEntry } from '@/lib/types';
import { TIER_CONFIG, TIER_BADGE_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: RankedCaptainEntry[];
  squadSource?: 'connected' | 'not_connected' | 'unavailable' | null;
  squadExcluded?: SquadExcludedEntry[] | null;
}

export default function RankingTable({ data, squadSource, squadExcluded }: Props) {
  if (data.length === 0) return null;

  const global = data.filter((entry) => entry.rank <= 12);
  const owned = data.filter((entry) => entry.owned);
  const dual = squadSource != null;

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

      {dual && squadSource === 'connected' && (
        <RankingSection title="A) Candidatos elegibles de tu plantilla (solo MID/FWD)" entries={owned} />
      )}

      {dual && squadSource === 'not_connected' && (
        <p className="px-4 py-2.5 text-xs text-bf-gray">
          No hay equipo conectado; te muestro solo el ranking global.
        </p>
      )}

      {dual && squadSource === 'unavailable' && (
        <p className="px-4 py-2.5 text-xs text-bf-gray">
          No pude cargar tu plantilla; te muestro solo el ranking global.
        </p>
      )}

      {dual && squadExcluded != null && squadExcluded.length > 0 && (
        <p className="px-4 py-2.5 text-xs text-amber-300">
          No evaluados para capitanía: {squadExcluded.map((entry) => (
            `${entry.web_name} (${EXCLUSION_REASON_LABELS[entry.reason]})`
          )).join(', ')}.
        </p>
      )}

      {dual ? (
        <RankingSection title="B) Mejores candidatos globales" entries={global} markOwned />
      ) : (
        <RankingRows entries={data} />
      )}
    </div>
  );
}

const EXCLUSION_REASON_LABELS: Record<SquadExcludedEntry['reason'], string> = {
  not_eligible_position: 'posición no elegible',
  unavailable: 'no disponible',
  unresolved: 'sin resolver',
};

function RankingSection({
  title,
  entries,
  markOwned = false,
}: {
  title: string;
  entries: RankedCaptainEntry[];
  markOwned?: boolean;
}) {
  return (
    <section>
      <h3 className="px-4 py-2 text-[11px] font-extrabold uppercase tracking-wide text-bf-gold">
        {title}
      </h3>
      {entries.length > 0 ? (
        <RankingRows entries={entries} markOwned={markOwned} />
      ) : (
        <p className="px-4 py-2.5 text-xs text-bf-gray">No hay candidatos elegibles.</p>
      )}
    </section>
  );
}

function RankingRows({ entries, markOwned = false }: { entries: RankedCaptainEntry[]; markOwned?: boolean }) {
  return (
    <div>
      {entries.map((entry, idx) => (
        <RankRow key={entry.rank} entry={entry} banded={idx % 2 === 0} markOwned={markOwned} />
      ))}
    </div>
  );
}

function RankRow({ entry, banded, markOwned = false }: { entry: RankedCaptainEntry; banded: boolean; markOwned?: boolean }) {
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
        <span className="block truncate font-bold text-white">{web_name}</span>
        <span className="ml-1.5 text-xs text-bf-gray">{team_short}</span>
        {markOwned && entry.owned && (
          <span className="ml-1.5 text-[10px] font-bold text-bf-turquoise">TUYO</span>
        )}
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
