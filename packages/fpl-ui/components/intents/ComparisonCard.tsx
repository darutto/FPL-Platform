/**
 * ComparisonCard — rich "Hi-Fi" rendering for compare_players OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome     === 'ok'
 *   response.intent      === 'compare_players'
 *   response.comparison  !== null
 *
 * Consumes from ComparisonMeta (stable conditional fields only):
 *   winner, margin, label, reasons, player_a, player_b
 *
 * Shape (design handoff — CompareCard prototype):
 *   - uppercase micro-label + margin pill (MARGIN_CONFIG)
 *   - verdict headline "La mejor selección es {winner}." (or "Empate técnico.")
 *   - side-by-side OptionCols; the winner gets a PICK tab + big Archivo Black
 *     captain_score (accent, ~30px); the loser a smaller muted number (~22px)
 *   - "{winner} lidera por {margin} pts" lead strip
 *   - reasons ≤3, each line-clamped
 *
 * All verdict wording lives in lib/copy.ts (no-imperative rule). All numbers
 * come from metadata — nothing is invented in the UI.
 *
 * player_a / player_b may be null (legacy construction). When null, only the
 * verdict + lead + reasons are shown (summary-only fallback).
 */
import type { ComparisonMeta, ComparisonPlayerContext } from '@/lib/types';
import { MARGIN_CONFIG, PILL_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { COMPARISON_LABEL, comparisonVerdict, comparisonLead, UNIT_CAPTAIN_PTS } from '@/lib/copy';
import { FingerprintWaves } from './CardOrnaments';
import StatComparisonTable from './StatComparisonTable';

interface Props {
  data: ComparisonMeta;
}

const ACCENT = 'cyan' as const;

export default function ComparisonCard({ data }: Props) {
  const { winner, margin, label, reasons, player_a, player_b, stat_comparison } = data;
  const { text: labelText, pillClass } = MARGIN_CONFIG[label] ?? MARGIN_CONFIG.moderate;
  const topReasons = reasons.slice(0, 3);

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT[ACCENT].border}`}>
      <FingerprintWaves color={ACCENT_HEX.cyan} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header — micro-label + margin pill */}
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-extrabold text-bf-cyan uppercase tracking-wide">
            {COMPARISON_LABEL}
          </span>
          <span className={`${PILL_BASE} ${pillClass}`}>Diferencia {labelText}</span>
        </div>

        {/* Verdict headline */}
        <p className="text-lg font-extrabold leading-tight text-white">
          {winner != null ? (
            <>
              La mejor selección es <span className="text-bf-turquoise">{winner}</span>.
            </>
          ) : (
            'Empate técnico.'
          )}
        </p>

        {/* Side-by-side OptionCols */}
        {player_a && player_b && (
          <div className="grid grid-cols-2 gap-2.5">
            <OptionCol player={player_a} isWinner={winner === player_a.web_name} />
            <OptionCol player={player_b} isWinner={winner === player_b.web_name} />
          </div>
        )}

        {/* Lead strip */}
        {winner != null && (
          <div className="flex items-center gap-1.5 text-xs text-bf-text/80">
            <span
              aria-hidden="true"
              className="inline-block h-0 w-0 border-l-[4px] border-r-[4px] border-b-[7px] border-l-transparent border-r-transparent border-b-bf-turquoise"
            />
            <span>
              <span className="font-bold text-white">{winner}</span> lidera por{' '}
              <span className="font-display tracking-tighter text-bf-turquoise">
                {margin.toFixed(1)}
              </span>{' '}
              pts
            </span>
          </div>
        )}

        {/* Reasons — max 3, line-clamped */}
        {topReasons.length > 0 && (
          <ul className="space-y-0.5">
            {topReasons.map((reason, i) => (
              <li
                key={i}
                className="flex items-start gap-1.5 text-xs text-bf-text/80"
              >
                <span
                  aria-hidden="true"
                  className="mt-1 inline-block h-0 w-0 shrink-0 border-l-[4px] border-r-[4px] border-b-[7px] border-l-transparent border-r-transparent border-b-bf-cyan"
                />
                <span className="line-clamp-1">{reason}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Additive raw-stat table — appended below the verdict, never
            replacing it. v1/first-pass, see FINAL_RESPONSE_CONTRACT.md. */}
        {stat_comparison && stat_comparison.rows.length > 0 && (
          <div className="border-t border-white/10 pt-1">
            <StatComparisonTable
              data={stat_comparison}
              nameA={player_a?.web_name ?? 'Jugador A'}
              nameB={player_b?.web_name ?? 'Jugador B'}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function OptionCol({
  player,
  isWinner,
}: {
  player: ComparisonPlayerContext;
  isWinner: boolean;
}) {
  return (
    <div
      className={`relative min-w-0 overflow-hidden rounded-lg border p-2.5 ${
        isWinner
          ? 'border-bf-turquoise/40 bg-bf-turquoise/10'
          : 'border-white/10 bg-white/[0.04]'
      }`}
    >
      {isWinner && (
        <span className="absolute right-0 top-0 rounded-bl-lg bg-bf-turquoise px-1.5 py-0.5 text-[8px] font-black uppercase tracking-wider text-bf-ink">
          Pick
        </span>
      )}
      <div className={`truncate font-extrabold ${isWinner ? 'text-white' : 'text-bf-text/70'}`}>
        {player.web_name}
      </div>
      <div className="text-[11px] text-bf-gray">{playerContext(player)}</div>
      <div
        className={`mt-1 font-display leading-none tracking-tighter ${
          isWinner ? 'text-bf-turquoise' : 'text-bf-gray'
        }`}
        style={{ fontSize: isWinner ? 30 : 22 }}
      >
        {player.captain_score.toFixed(1)}
      </div>
      <div className="text-[9px] font-bold uppercase tracking-wide text-bf-gray">
        {UNIT_CAPTAIN_PTS}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported pure helpers — tested in comparison-card tests.
// ---------------------------------------------------------------------------

/** Position + venue micro-row, e.g. "FWD · Local" / "MID · Visitante" / "FWD". */
export function playerContext(player: ComparisonPlayerContext): string {
  if (player.is_home === true) return `${player.position} · Local`;
  if (player.is_home === false) return `${player.position} · Visitante`;
  return player.position;
}

// Re-export copy helpers so tests can assert wording via one surface.
export { comparisonVerdict, comparisonLead };
