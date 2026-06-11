/**
 * ChipCard — structured rendering for chip_advice OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome === 'ok'
 *   response.intent  === 'chip_advice'
 *   response.chip    !== null
 *
 * Consumes from ChipAdviceMeta (stable conditional fields only):
 *   chip, recommendation, gw, signal_value, signal_label, chip_unavailable
 *
 * chip_unavailable=true: greyed state, "chip no disponible" note.
 * missing_context: neutral state (no strong signal available, e.g. free_hit
 *   without DGW/BGW data).
 */
import type { ChipAdviceMeta } from '@/lib/types';
import { CHIP_RECOMMENDATION_CONFIG, PILL_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: ChipAdviceMeta;
}

export default function ChipCard({ data }: Props) {
  const { chip, recommendation, gw, signal_value, signal_label, chip_unavailable } = data;
  const chipLabel = CHIP_LABELS[chip] ?? chip;
  const { label, pillClass } = CHIP_RECOMMENDATION_CONFIG[recommendation];

  return (
    <div
      className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.purple.border} ${
        chip_unavailable ? 'opacity-60' : ''
      }`}
    >
      <TriangleField color={ACCENT_HEX.purple} corner="tr" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header row */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-extrabold text-white">{chipLabel}</span>
            {gw != null && (
              <span className="inline-flex items-center rounded-full bg-bf-purple/10 border border-bf-purple/40 px-2 py-0.5 text-[10px] font-bold text-bf-purple">GW{gw}</span>
            )}
          </div>
          <span className={`${PILL_BASE} ${pillClass}`}>
            {label}
          </span>
        </div>

        {/* Signal row */}
        {signal_value != null && signal_label != null && (
          <div className="flex items-center justify-between text-xs">
            <span className="text-bf-gray">{signal_label}</span>
            <span className="font-display tracking-tighter text-bf-purple text-base leading-none">{signal_value.toFixed(1)}</span>
          </div>
        )}

        {/* Unavailable note */}
        {chip_unavailable && (
          <p className="text-xs text-bf-gray">Chip no disponible en tu equipo</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chip name labels (Spanish)
// ---------------------------------------------------------------------------

const CHIP_LABELS: Record<string, string> = {
  triple_captain: 'Triple Capitán',
  wildcard: 'Comodín',
  bench_boost: 'Impulso de Banca',
  free_hit: 'Ficha Libre',
};
