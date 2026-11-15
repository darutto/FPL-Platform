/**
 * FixtureRunTable — structured rendering for player_fixture_run OK turns
 * (`/calendarios <jugador>`, EN `/fixtures <player>`).
 *
 * Rendered beneath final_text when:
 *   response.outcome     === 'ok'
 *   response.intent      === 'player_fixture_run'
 *   response.fixture_run !== null
 *
 * A header (name · team · position) over the player card's own fixture strip, so every
 * fixture calendar in the app draws the /fixtures tiles (Leo, 2026-11-14): our band for
 * every plan (FPL's FDR where there is none), Europe/cups and rest days for Premium, the
 * strip's small legend. The payload carries no `strip_axis`, so the band reads the FPL
 * position's axis (DEF/GKP defence, the rest attack).
 */
import type { FixtureRunMeta } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';
import { PlayerFixtureStrip } from './PlayerFixtureStrip';

interface Props {
  data: FixtureRunMeta;
}

export default function FixtureRunTable({ data }: Props) {
  const { web_name, team_short, position, fixtures } = data;
  if (fixtures.length === 0) return null;

  return (
    <div className={`mt-3 ${CARD_BASE} ${CARD_ACCENT.gold.border}`}>
      <TriangleField color={ACCENT_HEX.gold} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2 text-sm">
          <span className="min-w-0 truncate font-extrabold text-white">{web_name}</span>
          <span className="flex-shrink-0 text-bf-gray/60">·</span>
          <span className="flex-shrink-0 text-bf-gray text-xs font-bold tracking-wide">{team_short}</span>
          <span className="flex-shrink-0 text-bf-gray/60">·</span>
          <span className="flex-shrink-0 text-bf-gray text-xs">{position}</span>
        </div>

        <PlayerFixtureStrip fixtures={fixtures} teamShort={team_short} position={position} />
      </div>
    </div>
  );
}
