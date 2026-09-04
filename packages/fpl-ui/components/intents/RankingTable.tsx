/**
 * RankingTable — structured rendering for rank_candidates OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome        === 'ok'
 *   response.intent         === 'rank_candidates'
 *   response.captain_ranking !== null
 *
 * Consumes from RankedCaptainEntry[] (stable conditional fields only):
 *   rank, web_name, team_short, position, captain_score, tier, set_piece_notes
 *
 * Position is shown because the pool is open to every position: without it a
 * keeper and a forward are the same row.
 *
 * Tier badge colours match CaptainCard: see lib/theme TIER_CONFIG.
 */
import type {
  HipsterPick,
  RankedCaptainEntry,
  RankingPresentation,
  SquadExcludedEntry,
} from '@/lib/types';
import { TIER_CONFIG, TIER_BADGE_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: RankedCaptainEntry[];
  squadSource?: 'connected' | 'not_connected' | 'unavailable' | null;
  squadExcluded?: SquadExcludedEntry[] | null;
  presentation?: RankingPresentation | null;
}

export default function RankingTable({ data, squadSource, squadExcluded, presentation }: Props) {
  if (data.length === 0) return null;

  // The backend names which rows each list shows, so the card and the prose
  // above it cannot disagree about who was recommended. The fallbacks keep
  // older payloads rendering.
  const byId = new Map(
    data.filter((entry) => entry.player_id != null).map((entry) => [entry.player_id!, entry]),
  );
  const pick = (ids: number[] | undefined, fallback: RankedCaptainEntry[]) =>
    ids && ids.length > 0
      ? ids.map((id) => byId.get(id)).filter((entry): entry is RankedCaptainEntry => entry != null)
      : fallback;

  const global = pick(presentation?.global_top, data.filter((entry) => entry.rank <= 12));
  const owned = pick(presentation?.owned_top, data.filter((entry) => entry.owned));
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
        <RankingSection
          title="A) Candidatos de tu plantilla"
          entries={owned}
          hipster={presentation?.owned_hipster}
          byId={byId}
        />
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
        <RankingSection
          title="B) Mejores candidatos globales"
          entries={global}
          markOwned
          hipster={presentation?.global_hipster}
          byId={byId}
        />
      ) : (
        <RankingRows entries={data} />
      )}
    </div>
  );
}

const EXCLUSION_REASON_LABELS: Record<SquadExcludedEntry['reason'], string> = {
  unavailable: 'no disponible',
  unresolved: 'sin resolver',
};

function RankingSection({
  title,
  entries,
  markOwned = false,
  hipster,
  byId,
}: {
  title: string;
  entries: RankedCaptainEntry[];
  markOwned?: boolean;
  hipster?: HipsterPick;
  byId?: Map<number, RankedCaptainEntry>;
}) {
  const hipsterEntry =
    hipster?.player_id != null ? byId?.get(hipster.player_id) ?? null : null;

  return (
    <section>
      <h3 className="px-4 py-2 text-[11px] font-extrabold uppercase tracking-wide text-bf-gold">
        {title}
      </h3>
      {entries.length > 0 ? (
        <RankingRows entries={entries} markOwned={markOwned} />
      ) : (
        <p className="px-4 py-2.5 text-xs text-bf-gray">No hay candidatos disponibles.</p>
      )}
      {/* One lightly-owned extra, offered as an opportunity rather than a
          warning. When nobody good enough is lightly owned we say so instead
          of padding the slot with a weak player. */}
      {hipsterEntry != null && (
        <div className="border-t border-bf-turquoise/20">
          <p className="px-4 pt-2 text-[10px] font-extrabold uppercase tracking-wide text-bf-turquoise">
            Hipster
            {hipster?.selected_by_percent != null &&
              ` · lo lleva el ${hipster.selected_by_percent.toFixed(1)}%`}
          </p>
          <RankingRows entries={[hipsterEntry]} markOwned={markOwned} />
        </div>
      )}
      {hipster != null && hipster.player_id == null && (
        <p className="border-t border-white/10 px-4 py-2.5 text-xs text-bf-gray">
          Sin hipster esta jornada: nadie de poca propiedad llega al mínimo.
        </p>
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
  const { rank, web_name, team_short, position, captain_score, tier, set_piece_notes } = entry;
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
        <span className="ml-1.5 text-xs text-bf-gray">
          {position ? `${team_short} · ${position}` : team_short}
        </span>
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
