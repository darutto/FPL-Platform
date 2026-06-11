/**
 * ComparisonCard — structured rendering for compare_players OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome     === 'ok'
 *   response.intent      === 'compare_players'
 *   response.comparison  !== null
 *
 * Consumes from ComparisonMeta (stable conditional fields only):
 *   winner, margin, label, reasons, player_a, player_b
 *
 * player_a / player_b may be null (legacy construction).
 * When null, only the summary row is shown.
 */
import type { ComparisonMeta, ComparisonPlayerContext } from '@/lib/types';
import { MARGIN_CONFIG, PILL_BASE, CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { FingerprintWaves } from './CardOrnaments';

interface Props {
  data: ComparisonMeta;
}

export default function ComparisonCard({ data }: Props) {
  const { winner, margin, label, reasons, player_a, player_b } = data;
  const { text: labelText, pillClass } = MARGIN_CONFIG[label] ?? MARGIN_CONFIG.moderate;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.cyan.border}`}>
      <FingerprintWaves color={ACCENT_HEX.cyan} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-extrabold text-bf-cyan uppercase tracking-wide">
            Comparación
          </span>
          <span className={`${PILL_BASE} ${pillClass}`}>
            Diferencia {labelText}
          </span>
        </div>

        {/* Player row */}
        {player_a && player_b && (
          <PlayerRow
            playerA={player_a}
            playerB={player_b}
            winner={winner}
          />
        )}

        {/* Winner summary */}
        <div className="text-xs text-bf-text/80">
          {winner != null ? (
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block w-0 h-0 border-l-[4px] border-r-[4px] border-b-[7px] border-l-transparent border-r-transparent border-b-bf-turquoise" />
              <span className="text-white font-bold">{winner}</span>
              {' '}lidera por{' '}
              <span className="font-display tracking-tighter text-bf-turquoise">{margin.toFixed(1)}</span>
              {' '}puntos
            </span>
          ) : (
            <span className="text-bf-gray">Empate — misma puntuación</span>
          )}
        </div>

        {/* Reasons */}
        {reasons.length > 0 && (
          <div className="space-y-0.5">
            <p className="text-xs text-bf-gray">Ventajas:</p>
            <ul className="space-y-0.5">
              {reasons.map((reason, i) => (
                <li key={i} className="text-xs text-bf-text/80 flex items-center gap-1.5">
                  <span aria-hidden="true" className="inline-block w-0 h-0 border-l-[4px] border-r-[4px] border-b-[7px] border-l-transparent border-r-transparent border-b-bf-cyan" />
                  {reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function PlayerRow({
  playerA,
  playerB,
  winner,
}: {
  playerA: ComparisonPlayerContext;
  playerB: ComparisonPlayerContext;
  winner: string | null;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <PlayerCell player={playerA} isWinner={winner === playerA.web_name} />
      <PlayerCell player={playerB} isWinner={winner === playerB.web_name} />
    </div>
  );
}

function PlayerCell({
  player,
  isWinner,
}: {
  player: ComparisonPlayerContext;
  isWinner: boolean;
}) {
  return (
    <div
      className={`rounded-lg p-2.5 border ${
        isWinner
          ? 'bg-bf-turquoise/10 border-bf-turquoise/40'
          : 'bg-white/[0.04] border-white/10'
      }`}
    >
      <div className="flex items-center justify-between gap-1">
        <span className={`font-extrabold ${isWinner ? 'text-white' : 'text-bf-text/70'}`}>
          {player.web_name}
        </span>
        {isWinner && (
          <span className="text-[10px] text-bf-turquoise">✓</span>
        )}
      </div>
      <div className="text-xs text-bf-gray">{player.position}</div>
      <div className={`mt-1 font-display tracking-tighter text-lg leading-none ${isWinner ? 'text-bf-turquoise' : 'text-bf-gray'}`}>
        {player.captain_score.toFixed(1)}
      </div>
    </div>
  );
}
