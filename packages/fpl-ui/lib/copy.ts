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
import { translate } from './i18n/dictionary';
import type { Locale } from './i18n/locale';

// ---------------------------------------------------------------------------
// Micro-labels (uppercase eyebrow above each card)
// ---------------------------------------------------------------------------

export const COMPARISON_LABEL = translate('es', 'cmp.label');
export const TRANSFER_LABEL = translate('es', 'transfer.label');
export const SUGGESTION_LABEL = translate('es', 'suggest.label');

// ---------------------------------------------------------------------------
// Micro-units (uppercase unit tags under hero numbers)
// ---------------------------------------------------------------------------

export const UNIT_CAPTAIN_PTS = translate('es', 'unit.captainPts');
// ComparisonCard shows position_score — our own 0–100 heuristic rating, not
// literal captain points. Branded "Bendito Fantasy"; the number is rendered
// with a "/100" suffix (see BF_SCORE_MAX) so the scale is explicit.
export const UNIT_BF_SCORE = translate('es', 'unit.bfScore');
export const BF_SCORE_MAX = 100;
export const UNIT_PRICE = translate('es', 'unit.price');
export const UNIT_FORM = translate('es', 'unit.form');
export const UNIT_OWNERSHIP = translate('es', 'unit.ownership');

// PlayerCard's micro-labels — PPG/xG/xA/xGI/ICT/Minutos have no existing
// UNIT_* to reuse; UNIT_PRICE/UNIT_FORM/UNIT_OWNERSHIP above are reused as-is.
export const UNIT_PPG = 'PPG';
export const UNIT_XG = 'xG';
export const UNIT_XA = 'xA';
export const UNIT_XGI = 'xGI';
export const UNIT_ICT = 'ICT';
export const UNIT_DC = 'DC';
export const UNIT_XG_PER_90 = 'xG/90';
export const UNIT_XA_PER_90 = 'xA/90';
export const UNIT_XGI_PER_90 = 'xGI/90';
export const UNIT_ICT_PER_90 = 'ICT/90';
export const UNIT_DC_PER_90 = 'DC/90';
export const UNIT_MINUTES = translate('es', 'unit.minutes');

// DifferentialTable's score column — short header for a narrow grid cell.
// Was mislabeled "Pts" (read as season points); it's actually position_score.
export const DIFFERENTIAL_SCORE_LABEL = 'BF';

// DifferentialTable ranks every position (GKP/DEF/MID/FWD) in one list, but
// each position's position_score is computed under a different weight
// profile (see packages/fpl-grounded-assistant/position_score.py) — a GKP's
// score and a FWD's score are not on a directly comparable scale. Shown as
// a footer caveat rather than silently implying the ranking is apples-to-apples.
export const DIFFERENTIAL_CROSS_POSITION_DISCLAIMER = translate('es', 'diff.disclaimer');

// ---------------------------------------------------------------------------
// ComparisonCard verdicts
// ---------------------------------------------------------------------------

/** Headline verdict for a comparison. Neutral when there is no winner. */
export function comparisonVerdict(winner: string | null, locale: Locale = 'es'): string {
  return winner != null ? translate(locale, 'cmp.verdict.win', { name: winner }) : translate(locale, 'cmp.verdict.tie');
}

/** "{winner} lidera por {margin} pts" lead strip. */
export function comparisonLead(winner: string, margin: number, locale: Locale = 'es'): string {
  return translate(locale, 'cmp.lead', { winner, margin: margin.toFixed(1) });
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
  locale: Locale = 'es',
): string {
  switch (recommendation) {
    case 'transfer_in':
      return translate(locale, 'transfer.verdict.in', { name: playerIn });
    case 'marginal_transfer_in':
      return translate(locale, 'transfer.verdict.marginal', { name: playerIn });
    case 'hold':
      return translate(locale, 'transfer.verdict.hold');
    default:
      return translate(locale, 'transfer.verdict.in', { name: playerIn });
  }
}

/** Context-strip pill prefix for the outgoing player. */
export const TRANSFER_OUT_PILL = translate('es', 'transfer.out');

// ---------------------------------------------------------------------------
// TransferSuggestionCard verdicts
// ---------------------------------------------------------------------------

/** Headline verdict for the top-ranked suggestion. */
export function suggestionVerdict(topName: string, locale: Locale = 'es'): string {
  return translate(locale, 'transfer.verdict.in', { name: topName });
}

/** Neutral sub-line describing the ranked scope of the list. */
export const SUGGESTION_ALTERNATIVES_LABEL = translate('es', 'suggest.others');

// ---------------------------------------------------------------------------
// Shared CTA — the app cannot execute transfers, so this is an honest
// external link to the official FPL transfers page.
// ---------------------------------------------------------------------------

export const TRANSFER_CTA_URL = 'https://fantasy.premierleague.com/transfers';
export const TRANSFER_CTA_LABEL = translate('es', 'transfer.cta');
