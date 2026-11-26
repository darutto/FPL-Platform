/**
 * PlayerZonalCard — the card of a focused zonal question («oportunidades zonales de X»).
 *
 * Rendered when intent === 'player_zonal_outlook' and `player_zonal` is non-null: a short header
 * plus the SAME «Zonas» section PlayerCard draws (pitch, zone chips, per-match rows, verdict,
 * data stamp, profile-only mode with old data, and the closing zone link).
 */
import type { PlayerZonalCardMeta } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { FingerprintWaves } from './CardOrnaments';
import PlayerZonasSection from './PlayerZonasSection';

interface Props {
  data: PlayerZonalCardMeta;
}

export default function PlayerZonalCard({ data }: Props) {
  const { web_name, team_short, position, zonal, signals } = data;
  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.purple.border}`} data-testid="player-zonal-card">
      <FingerprintWaves color={ACCENT_HEX.purple} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        <div className="min-w-0">
          <span className="block truncate text-lg font-extrabold text-white">{web_name}</span>
          <span className="text-xs text-bf-gray">
            {team_short} · {position}
          </span>
        </div>
        <PlayerZonasSection zonal={zonal} zoneLink={signals?.find((s) => s.kind === 'zone') ?? null} />
      </div>
    </div>
  );
}
