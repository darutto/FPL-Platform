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
import { useT } from '@/lib/i18n/LocaleProvider';
import type { DictKey } from '@/lib/i18n/dictionary';

interface Props {
  data: CaptainScoreMeta;
}

export default function CaptainCard({ data }: Props) {
  const t = useT();
  const { web_name, team_short, captain_score, tier, set_piece_notes } = data;
  const { labelKey, icon, badgeClass, barClass } = TIER_CONFIG[tier] ?? TIER_CONFIG.low_confidence;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      <TriangleField color={ACCENT_HEX.turquoise} corner="tr" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header row */}
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <span className="block truncate font-extrabold text-white text-base leading-none">{web_name}</span>
            <span className="ml-2 text-bf-turquoise text-xs font-bold tracking-wide">{team_short}</span>
          </div>
          <span className={`flex-shrink-0 ${TIER_BADGE_BASE} ${badgeClass}`}>
            <span className="text-[11px] leading-none">{icon}</span>
            {t(labelKey)}
          </span>
        </div>

        {/* Score bar */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-bf-gray">
            <span>{t('captain.score')}</span>
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
                {SET_PIECE_KEYS[note] ? t(SET_PIECE_KEYS[note]) : note.replace(/_/g, ' ')}
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

const SET_PIECE_KEYS: Record<string, DictKey> = {
  penalty_taker_1: 'setpiece.penalty_taker_1',
  penalty_taker_2: 'setpiece.penalty_taker_2',
  freekick_taker_1: 'setpiece.freekick_taker_1',
  freekick_taker_2: 'setpiece.freekick_taker_2',
  corner_taker_1: 'setpiece.corner_taker_1',
  corner_taker_2: 'setpiece.corner_taker_2',
};
