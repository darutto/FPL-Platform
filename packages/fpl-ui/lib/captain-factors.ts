/**
 * Plain-language captaincy factors for the card.
 *
 * Mirrors fpl_grounded_assistant/captain_factors.py deliberately: the card and
 * the prose above it must describe the same player with the same figures, so
 * both read the same fields and phrase them the same way.
 *
 * Two rules carry over with it:
 *   - Name the factor, never its coefficient. No weight or threshold appears
 *     in anything a reader sees.
 *   - Opportunity, not alarm. A partial minutes share is context for a
 *     decision, never a warning, and never painted as danger.
 */
import type { MinutesContext, RankedCaptainEntry } from '@/lib/types';
import { translate } from '@/lib/i18n/dictionary';
import type { Locale } from '@/lib/i18n/locale';

export function minutesPhrase(context?: MinutesContext | null, locale: Locale = 'es'): string | null {
  if (context == null || context.degraded) return null;
  const { minutes_played, minutes_available, starts } = context;
  if (minutes_played == null || !minutes_available) return null;
  const starts_text = starts === 1 ? translate(locale, 'factors.start') : translate(locale, 'factors.starts', { n: starts });
  return translate(locale, 'factors.minutes', { played: minutes_played, available: minutes_available, starts: starts_text });
}

export function penaltiesPhrase(order?: number | null, locale: Locale = 'es'): string | null {
  if (order == null || order <= 0) return null;
  return order === 1 ? translate(locale, 'factors.penalty1') : translate(locale, 'factors.penaltyN', { n: order });
}

export function factorPhrases(entry: RankedCaptainEntry, locale: Locale = 'es'): string[] {
  return [minutesPhrase(entry.minutes_context, locale), penaltiesPhrase(entry.penalties_order, locale)].filter(
    (phrase): phrase is string => phrase != null,
  );
}

function fullParticipation(context?: MinutesContext | null): boolean {
  return context != null && !context.degraded && context.participation_percent === 100;
}

/**
 * A note only where the ranking would mislead.
 *
 * Two parts of this product have twice asserted opposite things while the
 * reader believed the louder one. Here the score is louder, so a player who
 * plays every available minute and takes the penalties yet sits below players
 * who do neither says so on his own row.
 *
 * Kept rare on purpose: a row without a note has to mean "no surprise here".
 */
export function contradictionNote(
  entry: RankedCaptainEntry,
  all: RankedCaptainEntry[],
  locale: Locale = 'es',
): string | null {
  if (!fullParticipation(entry.minutes_context)) return null;
  if (entry.penalties_order !== 1) return null;

  const outrankedWithLess = all.filter(
    (other) => other.rank < entry.rank && !fullParticipation(other.minutes_context),
  );
  if (outrankedWithLess.length === 0) return null;

  return translate(locale, 'factors.contradiction');
}
