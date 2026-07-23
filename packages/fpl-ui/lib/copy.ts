/**
 * copy.ts — Spanish verdict / CTA / label templates for the rich "Hi-Fi" cards
 * (ComparisonCard, TransferCard, TransferSuggestionCard).
 *
 * SINGLE SOURCE OF TRUTH for the user-facing verdict strings on these three
 * cards, so the no-imperatives rule stays auditable in one place.
 *
 * HARD RULE — opportunity framing (see packages/fpl-tactical/CONTRACT.md:73):
 *   NO imperative buy/sell wording. Banned as commands: "Mete a X",
 *   "Compra a X", "Vende a X", "Ficha a X". Always frame as an analytical
 *   read / selection / opportunity, e.g. "La mejor selección es {name}."
 *   The reference Hi-Fi prototype used "Mete a {name}." — deliberately NOT
 *   reproduced here.
 *
 * All numbers are rendered by the components from metadata; this module only
 * owns wording. Keep it string-only (no JSX, no React).
 */
import type { TransferRecommendation } from './types';

// ---------------------------------------------------------------------------
// Micro-labels (uppercase eyebrow above each card)
// ---------------------------------------------------------------------------

export const COMPARISON_LABEL = 'Comparación';
export const TRANSFER_LABEL = 'Transferencia';
export const SUGGESTION_LABEL = 'Objetivos de transferencia';

// ---------------------------------------------------------------------------
// Micro-units (uppercase unit tags under hero numbers)
// ---------------------------------------------------------------------------

export const UNIT_CAPTAIN_PTS = 'pts capitán';
// ComparisonCard shows position_score — our own 0–100 heuristic rating, not
// literal captain points. Branded "Bendito Fantasy"; the number is rendered
// with a "/100" suffix (see BF_SCORE_MAX) so the scale is explicit.
export const UNIT_BF_SCORE = 'Bendito Fantasy';
export const BF_SCORE_MAX = 100;
export const UNIT_PRICE = 'precio';
export const UNIT_FORM = 'forma';
export const UNIT_OWNERSHIP = 'propiedad';

// ---------------------------------------------------------------------------
// ComparisonCard verdicts
// ---------------------------------------------------------------------------

/** Headline verdict for a comparison. Neutral when there is no winner. */
export function comparisonVerdict(winner: string | null): string {
  return winner != null ? `La mejor selección es ${winner}.` : 'Empate técnico.';
}

/** "{winner} lidera por {margin} pts" lead strip. */
export function comparisonLead(winner: string, margin: number): string {
  return `${winner} lidera por ${margin.toFixed(1)} pts`;
}

// ---------------------------------------------------------------------------
// TransferCard verdicts (opportunity framing, never a command)
// ---------------------------------------------------------------------------

/**
 * Headline verdict for a transfer read. Semantics preserved from
 * RECOMMENDATION_CONFIG, reworded to a selection/read (never "Mete a…").
 */
export function transferVerdict(
  recommendation: TransferRecommendation,
  playerIn: string,
): string {
  switch (recommendation) {
    case 'transfer_in':
      return `La mejor selección es ${playerIn}.`;
    case 'marginal_transfer_in':
      return `${playerIn} es una mejora marginal.`;
    case 'hold':
      return 'Mantener es la lectura correcta.';
    default:
      return `La mejor selección es ${playerIn}.`;
  }
}

/** Context-strip pill prefix for the outgoing player. */
export const TRANSFER_OUT_PILL = '← Saca';

// ---------------------------------------------------------------------------
// TransferSuggestionCard verdicts
// ---------------------------------------------------------------------------

/** Headline verdict for the top-ranked suggestion. */
export function suggestionVerdict(topName: string): string {
  return `La mejor selección es ${topName}.`;
}

/** Neutral sub-line describing the ranked scope of the list. */
export const SUGGESTION_ALTERNATIVES_LABEL = 'Otras opciones';

// ---------------------------------------------------------------------------
// Shared CTA — the app cannot execute transfers, so this is an honest
// external link to the official FPL transfers page.
// ---------------------------------------------------------------------------

export const TRANSFER_CTA_URL = 'https://fantasy.premierleague.com/transfers';
export const TRANSFER_CTA_LABEL = 'Hacer la transferencia en FPL';
