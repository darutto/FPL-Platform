/**
 * TransferCard — structured rendering for transfer_advice OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome  === 'ok'
 *   response.intent   === 'transfer_advice'
 *   response.transfer !== null
 *
 * Consumes from TransferMeta (stable conditional fields only):
 *   player_out, player_in, recommendation, score_delta,
 *   price_delta, reasons, budget_constraint, hit_warning
 *
 * price_delta is in tenths of £ (e.g. 10 = +£1.0m).
 * Informational only — does not affect the recommendation badge.
 */
import type { TransferMeta, TransferRecommendation } from '@/lib/types';

interface Props {
  data: TransferMeta;
}

export default function TransferCard({ data }: Props) {
  const {
    player_out,
    player_in,
    recommendation,
    score_delta,
    price_delta,
    reasons,
    budget_constraint,
    hit_warning,
  } = data;

  const { label, className } = RECOMMENDATION_CONFIG[recommendation];
  const priceDeltaStr = formatPriceDelta(price_delta);

  return (
    <div className="mt-3 rounded-xl border border-gray-700 bg-gray-900/60 p-4 text-sm space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
          Transferencia
        </span>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${className}`}>
          {label}
        </span>
      </div>

      {/* Player arrow */}
      <div className="flex items-center gap-3">
        <span className="text-gray-400 font-medium line-through">{player_out}</span>
        <span className="text-gray-500 text-xs">→</span>
        <span className="text-white font-semibold">{player_in}</span>
      </div>

      {/* Delta row */}
      <div className="flex items-center gap-4 text-xs">
        <DeltaChip
          value={score_delta}
          label="pts capitán"
          format={(v) => `${v > 0 ? '+' : ''}${v.toFixed(1)}`}
          positive={score_delta > 0}
        />
        {price_delta !== 0 && (
          <DeltaChip
            value={price_delta}
            label="precio"
            format={() => priceDeltaStr}
            positive={price_delta <= 0}
          />
        )}
      </div>

      {/* Reasons */}
      {reasons.length > 0 && (
        <ul className="space-y-0.5">
          {reasons.map((reason, i) => (
            <li key={i} className="text-xs text-gray-300 flex gap-1.5">
              <span className="text-indigo-400">•</span>
              {reason}
            </li>
          ))}
        </ul>
      )}

      {/* Warning banners */}
      {budget_constraint && (
        <Banner type="warning">Supera tu presupuesto disponible</Banner>
      )}
      {hit_warning && (
        <Banner type="caution">Usar una transferencia adicional costará −4 puntos</Banner>
      )}
    </div>
  );
}

function DeltaChip({
  label,
  format,
  value,
  positive,
}: {
  value: number;
  label: string;
  format: (v: number) => string;
  positive: boolean;
}) {
  return (
    <span className={`font-mono ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
      {format(value)}{' '}
      <span className="text-gray-500 font-sans">{label}</span>
    </span>
  );
}

function Banner({
  type,
  children,
}: {
  type: 'warning' | 'caution';
  children: React.ReactNode;
}) {
  const cls =
    type === 'warning'
      ? 'bg-red-900/40 border-red-700/60 text-red-300'
      : 'bg-amber-900/40 border-amber-700/60 text-amber-300';
  return (
    <div className={`rounded-lg border px-3 py-1.5 text-xs ${cls}`}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recommendation config
// ---------------------------------------------------------------------------

const RECOMMENDATION_CONFIG: Record<
  TransferRecommendation,
  { label: string; className: string }
> = {
  transfer_in: {
    label: 'Fichar',
    className: 'bg-emerald-900/60 text-emerald-300',
  },
  marginal_transfer_in: {
    label: 'Considerar',
    className: 'bg-amber-900/60 text-amber-300',
  },
  hold: {
    label: 'Conservar',
    className: 'bg-slate-700/60 text-slate-300',
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPriceDelta(delta: number): string {
  const sign = delta > 0 ? '+' : '';
  const pounds = (Math.abs(delta) / 10).toFixed(1);
  return `${sign}${delta < 0 ? '-' : ''}£${pounds}m`;
}
