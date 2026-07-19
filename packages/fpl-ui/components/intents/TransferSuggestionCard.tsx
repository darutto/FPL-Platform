/**
 * TransferSuggestionCard — rich "Hi-Fi" rendering for transfer_suggestion OK
 * turns (Phase 2.6h). Previously text-only.
 *
 * Rendered beneath final_text when:
 *   response.outcome             === 'ok'
 *   response.intent              === 'transfer_suggestion'
 *   response.transfer_suggestion !== null  (picks.length > 0)
 *
 * Consumes from TransferSuggestionMeta (stable conditional fields only):
 *   position_label, team_short, team_name, max_price, horizon, top_n,
 *   picks[].{rank, web_name, team_short, position, now_cost_m, form,
 *            avg_fdr, difficulty_label, composite_score, ownership}
 *
 * Shape (design handoff — hero + alternatives, like ChipPicksCard):
 *   - uppercase micro-label + scope pill (position / club / price cap)
 *   - verdict headline "La mejor selección es {top}." (lib/copy)
 *   - HERO panel for the #1 pick: big Archivo Black composite_score + name +
 *     form / FDR / price / ownership context
 *   - tight ranked list for the remaining picks
 *
 * Ranking is by composite_score (backend deterministic order = rank).
 * All numbers come from metadata — nothing is invented in the UI. No
 * imperative buy wording — verdict framed as a selection (lib/copy).
 */
import type { TransferSuggestionMeta, TransferSuggestionEntry } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { SUGGESTION_LABEL, SUGGESTION_ALTERNATIVES_LABEL, suggestionVerdict } from '@/lib/copy';
import { TriangleField } from './CardOrnaments';

interface Props {
  data: TransferSuggestionMeta;
}

const ACCENT = 'coralSoft' as const;

export default function TransferSuggestionCard({ data }: Props) {
  const { position_label, team_short, team_name, max_price, horizon, picks } = data;
  if (picks.length === 0) return null;

  const [top, ...rest] = picks;
  const scope = buildScope({ position_label, team_short, team_name, max_price });

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT[ACCENT].border}`}>
      <TriangleField color={ACCENT_HEX.coralSoft} corner="tr" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header — micro-label + scope */}
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-extrabold text-bf-coral-soft uppercase tracking-wide">
            {SUGGESTION_LABEL}
          </span>
          <span className="text-[11px] text-bf-gray">
            {scope} · {horizon} GW
          </span>
        </div>

        {/* Verdict headline */}
        <p className="text-lg font-extrabold leading-tight text-white">
          La mejor selección es{' '}
          <span className="text-bf-coral-soft">{top.web_name}</span>.
        </p>

        {/* Hero — #1 pick */}
        <div className="relative overflow-hidden rounded-xl border border-bf-coral-soft/40 bg-bf-coral-soft/[0.08] p-3">
          <span className="absolute right-0 top-0 rounded-bl-lg bg-bf-coral-soft px-2 py-0.5 text-[8px] font-black uppercase tracking-wider text-bf-ink">
            Pick
          </span>
          <div className="flex items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate pr-8 text-[15px] font-extrabold text-white">
                {top.web_name}
              </div>
              <div className="text-[11px] text-bf-gray">
                {top.team_short} · {top.position} · {formatPrice(top.now_cost_m)}
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-bf-text/80">
                <span>
                  Forma <span className="font-bold text-white">{top.form.toFixed(1)}</span>
                </span>
                <span>
                  FDR <span className="font-bold text-white">{top.avg_fdr.toFixed(1)}</span>{' '}
                  <span className="text-bf-gray">({top.difficulty_label})</span>
                </span>
                <span>
                  <span className="font-bold text-white">{formatOwnership(top.ownership)}</span>{' '}
                  propiedad
                </span>
              </div>
            </div>
            <div className="shrink-0 text-right leading-none">
              <span
                className="font-display tracking-tighter text-bf-coral-soft"
                style={{ fontSize: 30 }}
              >
                {top.composite_score.toFixed(1)}
              </span>
              <span className="mt-0.5 block text-[9px] font-bold uppercase tracking-wide text-bf-gray">
                índice
              </span>
            </div>
          </div>
        </div>

        {/* Alternatives — tight ranked list */}
        {rest.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] font-bold uppercase tracking-wide text-bf-gray">
              {SUGGESTION_ALTERNATIVES_LABEL}
            </p>
            <div>
              {rest.map((entry, idx) => (
                <AltRow key={entry.rank} entry={entry} banded={idx % 2 === 0} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AltRow({ entry, banded }: { entry: TransferSuggestionEntry; banded: boolean }) {
  const { rank, web_name, team_short, position, now_cost_m, composite_score } = entry;
  return (
    <div
      className={`grid grid-cols-[1.5rem_1fr_auto_auto] items-center gap-x-3 rounded px-2 py-1.5 ${
        banded ? 'bg-white/[0.035]' : ''
      }`}
    >
      <span
        className="text-base font-display tracking-tighter text-bf-coral-soft leading-none"
        style={{ opacity: Math.max(0.4, 1 - (rank - 2) * 0.12) }}
      >
        {rank}
      </span>
      <div className="min-w-0">
        <span className="font-bold text-white truncate">{web_name}</span>
        <span className="ml-1.5 text-[11px] text-bf-gray">
          {team_short} · {position}
        </span>
      </div>
      <span className="text-xs text-bf-text/80 tabular-nums">{formatPrice(now_cost_m)}</span>
      <span className="text-right font-display text-base tracking-tighter text-bf-coral-soft tabular-nums leading-none">
        {composite_score.toFixed(1)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported pure helpers — tested in transfer-suggestion-card tests.
// ---------------------------------------------------------------------------

/** Format now_cost_m (£m float) → "£7.5m". */
export function formatPrice(now_cost_m: number): string {
  return `£${now_cost_m.toFixed(1)}m`;
}

/** Format ownership float → "12.3%". */
export function formatOwnership(ownership: number): string {
  return `${ownership.toFixed(1)}%`;
}

/** Scope line: position + optional club + optional price cap. */
export function buildScope({
  position_label,
  team_short,
  team_name,
  max_price,
}: {
  position_label: string;
  team_short: string | null;
  team_name: string | null;
  max_price: number | null;
}): string {
  const parts: string[] = [];
  const club = team_name ?? team_short;
  if (club) parts.push(club);
  parts.push(position_label);
  if (max_price != null) parts.push(`≤ £${max_price.toFixed(1)}m`);
  return parts.join(' · ');
}
