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
import type { ChipAdviceMeta, ChipRecommendation } from '@/lib/types';

interface Props {
  data: ChipAdviceMeta;
}

export default function ChipCard({ data }: Props) {
  const { chip, recommendation, gw, signal_value, signal_label, chip_unavailable } = data;
  const chipLabel = CHIP_LABELS[chip] ?? chip;
  const { label, className } = RECOMMENDATION_CONFIG[recommendation];

  return (
    <div
      className={`mt-3 rounded-xl border p-4 text-sm space-y-3 ${
        chip_unavailable
          ? 'border-gray-700/50 bg-gray-900/30 opacity-60'
          : 'border-gray-700 bg-gray-900/60'
      }`}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-white">{chipLabel}</span>
          {gw != null && (
            <span className="text-xs text-gray-500">GW{gw}</span>
          )}
        </div>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${className}`}>
          {label}
        </span>
      </div>

      {/* Signal row */}
      {signal_value != null && signal_label != null && (
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-400">{signal_label}</span>
          <span className="font-mono text-white">{signal_value.toFixed(1)}</span>
        </div>
      )}

      {/* Unavailable note */}
      {chip_unavailable && (
        <p className="text-xs text-gray-500">Chip no disponible en tu equipo</p>
      )}
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

// ---------------------------------------------------------------------------
// Recommendation config
// ---------------------------------------------------------------------------

const RECOMMENDATION_CONFIG: Record<
  ChipRecommendation,
  { label: string; className: string }
> = {
  conditions_favorable: {
    label: 'Condiciones favorables',
    className: 'bg-emerald-900/60 text-emerald-300',
  },
  conditions_marginal: {
    label: 'Condiciones marginales',
    className: 'bg-amber-900/60 text-amber-300',
  },
  conditions_unfavorable: {
    label: 'Condiciones desfavorables',
    className: 'bg-red-900/60 text-red-300',
  },
  missing_context: {
    label: 'Datos insuficientes',
    className: 'bg-slate-700/60 text-slate-300',
  },
};
