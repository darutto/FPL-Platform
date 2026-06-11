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
import type { TransferMeta } from '@/lib/types';
import { RECOMMENDATION_CONFIG, PILL_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';

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

  const { label, pillClass } = RECOMMENDATION_CONFIG[recommendation];
  const priceDeltaStr = formatPriceDelta(price_delta);

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coral.border}`}>
      <TriangleField color={ACCENT_HEX.coral} corner="tr" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-extrabold text-bf-coral uppercase tracking-wide">
            Transferencia
          </span>
          <span className={`${PILL_BASE} ${pillClass}`}>
            {label}
          </span>
        </div>

        {/* Player swap — OUT pill + IN, no strikethrough (DS: pills carry semantics) */}
        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center rounded-full bg-bf-coral/15 border border-bf-coral/40 px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wider text-bf-coral">
            ←
          </span>
          <span className="text-bf-gray font-medium">{player_out}</span>
          <span className="text-bf-gray/60 text-xs">→</span>
          <span className="text-white font-extrabold">{player_in}</span>
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
              <li key={i} className="text-xs text-bf-text/80 flex items-center gap-1.5">
                <span aria-hidden="true" className="inline-block w-0 h-0 border-l-[4px] border-r-[4px] border-b-[7px] border-l-transparent border-r-transparent border-b-bf-coral" />
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
    <span className={`font-mono font-bold ${positive ? 'text-bf-turquoise' : 'text-bf-coral'}`}>
      {format(value)}{' '}
      <span className="text-bf-gray font-sans font-normal">{label}</span>
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
      ? 'bg-bf-coral/10 border-bf-coral/40 text-bf-coral'
      : 'bg-bf-gold/10 border-bf-gold/40 text-bf-gold';
  return (
    <div className={`rounded-lg border px-3 py-1.5 text-xs ${cls}`}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPriceDelta(delta: number): string {
  const sign = delta > 0 ? '+' : '';
  const pounds = (Math.abs(delta) / 10).toFixed(1);
  return `${sign}${delta < 0 ? '-' : ''}£${pounds}m`;
}
