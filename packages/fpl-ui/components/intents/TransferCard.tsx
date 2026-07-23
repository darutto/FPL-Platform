/**
 * TransferCard — rich "Hi-Fi" rendering for transfer_advice OK turns.
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
 * Shape (design handoff — TransferDecisionCard, 3 blocks):
 *   1. context strip: "← Saca {player_out}" pill + right-aligned status check
 *      (recommendation icon + label from RECOMMENDATION_CONFIG)
 *   2. verdict headline (lib/copy — opportunity framing, never "Mete a…")
 *      + one-line reason + hero panel for player_in with the score/price
 *      deltas as the big Archivo Black numbers
 *   3. single CTA link to the official FPL transfers page (the app cannot
 *      execute transfers — honest external link)
 *
 * price_delta is in tenths of £ (e.g. 10 = +£1.0m). Informational only —
 * does not change the recommendation. All numbers come from metadata.
 */
import type { TransferMeta, TransferRecommendation } from '@/lib/types';
import { RECOMMENDATION_CONFIG, PILL_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import {
  TRANSFER_LABEL,
  TRANSFER_OUT_PILL,
  TRANSFER_CTA_URL,
  TRANSFER_CTA_LABEL,
  transferVerdict,
  UNIT_CAPTAIN_PTS,
  UNIT_PRICE,
} from '@/lib/copy';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: TransferMeta;
}

/** Premise/status glyph per recommendation (context-strip right side). */
const STATUS_ICON: Record<TransferRecommendation, { icon: string; className: string }> = {
  transfer_in: { icon: '✓', className: 'text-bf-turquoise' },
  marginal_transfer_in: { icon: '~', className: 'text-bf-gold' },
  hold: { icon: '·', className: 'text-bf-gray' },
};

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

  const { label } = RECOMMENDATION_CONFIG[recommendation];
  const status = STATUS_ICON[recommendation] ?? STATUS_ICON.hold;
  const topReasons = reasons.slice(0, 3);
  const leadReason = topReasons[0];
  const restReasons = topReasons.slice(1);

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coral.border}`}>
      <TriangleField color={ACCENT_HEX.coral} corner="tr" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header — micro-label */}
        <span className="block text-xs font-extrabold text-bf-coral uppercase tracking-wide">
          {TRANSFER_LABEL}
        </span>

        {/* ── Block 1: context strip — OUT pill + status check ── */}
        <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-1.5 py-1">
          <span className="inline-flex items-center rounded-full border border-bf-coral/50 bg-bf-coral/15 px-2 py-0.5 text-[9px] font-black uppercase tracking-wider text-bf-coral">
            {TRANSFER_OUT_PILL}
          </span>
          <span className="min-w-0 truncate text-xs font-extrabold text-white">{player_out}</span>
          <span className={`ml-auto flex items-center gap-1 pr-1.5 text-[10px] font-bold ${status.className}`}>
            <span className="font-black">{status.icon}</span>
            <span className="truncate">{label}</span>
          </span>
        </div>

        {/* ── Block 2: verdict + one-line reason + hero deltas ── */}
        <div className="space-y-2">
          <p className="text-lg font-extrabold leading-tight text-white">
            {renderVerdict(recommendation, player_in)}
          </p>
          {leadReason && (
            <p className="text-xs leading-snug text-bf-gray line-clamp-2">{leadReason}</p>
          )}

          {/* Hero panel — recommended pick with the score/price deltas */}
          <div className="relative overflow-hidden rounded-xl border border-bf-coral/40 bg-bf-coral/[0.08] p-3">
            {recommendation !== 'hold' && (
              <span className="absolute right-0 top-0 rounded-bl-lg bg-bf-coral px-2 py-0.5 text-[8px] font-black uppercase tracking-wider text-white">
                Pick
              </span>
            )}
            <div className="truncate pr-10 text-[15px] font-extrabold text-white">{player_in}</div>
            <div className="mt-2 flex items-end gap-5">
              <HeroDelta
                value={formatScoreDelta(score_delta)}
                unit={UNIT_CAPTAIN_PTS}
                positive={score_delta > 0}
              />
              {price_delta !== 0 && (
                <HeroDelta
                  value={formatPriceDelta(price_delta)}
                  unit={UNIT_PRICE}
                  muted
                />
              )}
            </div>
          </div>

          {/* Remaining reasons */}
          {restReasons.length > 0 && (
            <ul className="space-y-0.5 pt-0.5">
              {restReasons.map((reason, i) => (
                <li key={i} className="flex items-start gap-1.5 text-xs text-bf-text/80">
                  <span
                    aria-hidden="true"
                    className="mt-1 inline-block h-0 w-0 shrink-0 border-l-[4px] border-r-[4px] border-b-[7px] border-l-transparent border-r-transparent border-b-bf-coral"
                  />
                  <span className="line-clamp-1">{reason}</span>
                </li>
              ))}
            </ul>
          )}

          {/* Warning banners */}
          {budget_constraint && (
            <Banner tone="warning">Supera tu presupuesto disponible</Banner>
          )}
          {hit_warning && (
            <Banner tone="caution">Usar una transferencia adicional costará −4 puntos</Banner>
          )}
        </div>

        {/* ── Block 3: single CTA — honest external link ── */}
        <a
          href={TRANSFER_CTA_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-bf-coral px-3 py-2.5 text-xs font-extrabold tracking-wide text-white transition-opacity hover:opacity-90"
        >
          {TRANSFER_CTA_LABEL}
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path
              d="M3 3h6v6M3 9l6-6"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </a>
      </div>
    </div>
  );
}

/** Verdict headline with the recommended name accented. Wording from lib/copy. */
function renderVerdict(recommendation: TransferRecommendation, playerIn: string) {
  const text = transferVerdict(recommendation, playerIn);
  const idx = text.indexOf(playerIn);
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <span className="text-bf-coral">{playerIn}</span>
      {text.slice(idx + playerIn.length)}
    </>
  );
}

function HeroDelta({
  value,
  unit,
  positive,
  muted,
}: {
  value: string;
  unit: string;
  positive?: boolean;
  muted?: boolean;
}) {
  const color = muted ? 'text-bf-gray' : positive ? 'text-bf-turquoise' : 'text-bf-gray';
  return (
    <div className="leading-none">
      <span className={`font-display tracking-tighter ${color}`} style={{ fontSize: 28 }}>
        {value}
      </span>
      <span className="mt-0.5 block text-[9px] font-bold uppercase tracking-wide text-bf-gray">
        {unit}
      </span>
    </div>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: 'warning' | 'caution';
  children: React.ReactNode;
}) {
  const cls =
    tone === 'warning'
      ? 'bg-bf-coral/10 border-bf-coral/40 text-bf-coral'
      : 'bg-bf-gold/10 border-bf-gold/40 text-bf-gold';
  return <div className={`rounded-lg border px-3 py-1.5 text-xs ${cls}`}>{children}</div>;
}

// ---------------------------------------------------------------------------
// Exported pure helpers — tested in transfer-card tests.
// ---------------------------------------------------------------------------

/** Signed captain-score delta: 7.5 → "+7.5", -1.2 → "-1.2". */
export function formatScoreDelta(delta: number): string {
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)}`;
}

/** Signed price delta (tenths of £): 10 → "+£1.0m", -5 → "-£0.5m". */
export function formatPriceDelta(delta: number): string {
  const sign = delta > 0 ? '+' : delta < 0 ? '-' : '';
  const pounds = (Math.abs(delta) / 10).toFixed(1);
  return `${sign}£${pounds}m`;
}
