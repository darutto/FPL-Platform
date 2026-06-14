/**
 * WcSquadTable — structured rendering for a national team's full tournament
 * squad (get_squad).
 *
 * Rendered beneath final_text when response.outcome === 'ok' and
 * response.squad.players is non-empty (see lib/wc-intent-renderer.ts
 * selectWcIntentView). Players are grouped by position — position values are
 * already locale_es-localized ("Portero", "Defensa", "Centrocampista",
 * "Delantero") — and sorted by price (desc) within each group.
 *
 * No starting-XI/"titular" indicator: this data source (FIFA Fantasy free
 * feed) only carries the registered roster, not confirmed lineups.
 */
import type { WcSquadPayload, WcSquadPlayerRow } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcSquadPayload;
}

const POSITION_ORDER = ['Portero', 'Defensa', 'Centrocampista', 'Delantero'];

export default function WcSquadTable({ data }: Props) {
  if (data.players.length === 0) return null;

  const groups = new Map<string, WcSquadPlayerRow[]>();
  for (const player of data.players) {
    const bucket = groups.get(player.position) ?? [];
    bucket.push(player);
    groups.set(player.position, bucket);
  }
  for (const bucket of groups.values()) {
    bucket.sort((a, b) => b.price - a.price);
  }
  const orderedPositions = [
    ...POSITION_ORDER.filter((p) => groups.has(p)),
    ...[...groups.keys()].filter((p) => !POSITION_ORDER.includes(p)),
  ];

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coralSoft.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-coral-soft/20">
        <TriangleField color={ACCENT_HEX.coralSoft} corner="tr" />
        <div className="relative z-10 flex items-center justify-between gap-2">
          <span className="text-xs font-extrabold text-white uppercase tracking-wide">
            Plantilla — {data.team}
          </span>
          <span className="text-[10px] font-bold text-bf-coral-soft uppercase tracking-wide flex-shrink-0">
            Grupo {data.group}
          </span>
        </div>
      </div>

      <div>
        {orderedPositions.map((position) => (
          <PositionGroup key={position} position={position} players={groups.get(position) ?? []} />
        ))}
      </div>
    </div>
  );
}

function PositionGroup({ position, players }: { position: string; players: WcSquadPlayerRow[] }) {
  return (
    <div>
      <div className="px-4 pt-2.5 pb-1 text-[10px] font-bold text-bf-gray uppercase tracking-widest">
        {position}
      </div>
      {players.map((player, idx) => (
        <div
          key={`${player.name}-${idx}`}
          className={`flex items-center justify-between gap-3 px-4 py-1.5 ${idx % 2 === 0 ? 'bg-white/[0.035]' : ''}`}
        >
          <span className="font-bold text-white truncate">{player.name}</span>
          <span className="font-display text-sm tracking-tighter text-bf-coral-soft flex-shrink-0">
            {player.price.toFixed(1)}
          </span>
        </div>
      ))}
    </div>
  );
}
