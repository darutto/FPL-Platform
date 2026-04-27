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

interface Props {
  data: ComparisonMeta;
}

export default function ComparisonCard({ data }: Props) {
  const { winner, margin, label, reasons, player_a, player_b } = data;
  const { text: labelText, className: labelClass } = MARGIN_CONFIG[label] ?? MARGIN_CONFIG.moderate;

  return (
    <div className="mt-3 rounded-xl border border-gray-700 bg-gray-900/60 p-4 text-sm space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
          Comparación
        </span>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${labelClass}`}>
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
      <div className="text-xs text-gray-300">
        {winner != null ? (
          <>
            <span className="text-white font-medium">{winner}</span>
            {' '}lidera por{' '}
            <span className="font-mono text-white">{margin.toFixed(1)}</span>
            {' '}puntos
          </>
        ) : (
          <span className="text-gray-400">Empate — misma puntuación</span>
        )}
      </div>

      {/* Reasons */}
      {reasons.length > 0 && (
        <div className="space-y-0.5">
          <p className="text-xs text-gray-500">Ventajas:</p>
          <ul className="space-y-0.5">
            {reasons.map((reason, i) => (
              <li key={i} className="text-xs text-gray-300 flex gap-1.5">
                <span className="text-indigo-400">•</span>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}
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
      className={`rounded-lg p-2.5 ${
        isWinner ? 'bg-indigo-900/40 border border-indigo-700/60' : 'bg-gray-800/50'
      }`}
    >
      <div className="flex items-center justify-between gap-1">
        <span className={`font-semibold ${isWinner ? 'text-white' : 'text-gray-300'}`}>
          {player.web_name}
        </span>
        {isWinner && (
          <span className="text-[10px] text-indigo-300">✓</span>
        )}
      </div>
      <div className="text-xs text-gray-500">{player.position}</div>
      <div className="mt-1 font-mono text-sm text-white">
        {player.captain_score.toFixed(1)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Margin label config
// ---------------------------------------------------------------------------

const MARGIN_CONFIG: Record<
  'narrow' | 'moderate' | 'clear',
  { text: string; className: string }
> = {
  narrow: {
    text: 'ajustada',
    className: 'bg-slate-700/60 text-slate-300',
  },
  moderate: {
    text: 'moderada',
    className: 'bg-amber-900/60 text-amber-300',
  },
  clear: {
    text: 'clara',
    className: 'bg-indigo-900/60 text-indigo-300',
  },
};
