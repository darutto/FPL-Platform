/**
 * CaptainCard — structured rendering for captain_score OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome === 'ok'
 *   response.intent  === 'captain_score'
 *   response.captain !== null
 *
 * Consumes from CaptainScoreMeta (stable conditional fields only):
 *   web_name, team_short, captain_score, tier, role_bonus, set_piece_notes
 *
 * Tier styling: lib/theme TIER_CONFIG (Bendito Fantasy DS .tier-card).
 */
import type { CaptainScoreMeta } from '@/lib/types';
import { TIER_CONFIG, TIER_BADGE_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: CaptainScoreMeta;
}

export default function CaptainCard({ data }: Props) {
  const { web_name, team_short, captain_score, tier, set_piece_notes } = data;
  const { label, icon, badgeClass, barClass } = TIER_CONFIG[tier] ?? TIER_CONFIG.low_confidence;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      <TriangleField color={ACCENT_HEX.turquoise} corner="tr" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header row */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="font-extrabold text-white text-base leading-none">{web_name}</span>
            <span className="ml-2 text-bf-turquoise text-xs font-bold tracking-wide">{team_short}</span>
          </div>
          <span className={`${TIER_BADGE_BASE} ${badgeClass}`}>
            <span className="text-[11px] leading-none">{icon}</span>
            {label}
          </span>
        </div>

        {/* Score bar */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-bf-gray">
            <span>Puntuación de capitán</span>
            <span className="font-display tracking-tighter text-white text-sm leading-none">{captain_score.toFixed(1)}</span>
          </div>
          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${barClass}`}
              style={{ width: `${Math.min(captain_score, 100)}%` }}
            />
          </div>
        </div>

        {/* Set piece notes */}
        {set_piece_notes.length > 0 && (
          <ul className="space-y-0.5">
            {set_piece_notes.map((note) => (
              <li key={note} className="text-xs text-bf-gray flex items-center gap-1.5">
                <span aria-hidden="true" className="inline-block w-0 h-0 border-l-[4px] border-r-[4px] border-b-[7px] border-l-transparent border-r-transparent border-b-bf-turquoise" />
                {translateSetPieceNote(note)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Set piece note translation
// ---------------------------------------------------------------------------

const SET_PIECE_LABELS: Record<string, string> = {
  penalty_taker_1: '1.º lanzador de penaltis',
  penalty_taker_2: '2.º lanzador de penaltis',
  freekick_taker_1: '1.º ejecutor de faltas',
  freekick_taker_2: '2.º ejecutor de faltas',
  corner_taker_1: 'Primer sacador de córners',
  corner_taker_2: '2.º sacador de córners',
};

function translateSetPieceNote(note: string): string {
  return SET_PIECE_LABELS[note] ?? note.replace(/_/g, ' ');
}
