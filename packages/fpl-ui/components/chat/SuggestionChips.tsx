'use client';

/**
 * SuggestionChips — the two-step "chip wizard" for the Guided Comparison flow.
 *
 * When a bare (or partial) `/comparar` returns `needs_clarification` WITH
 * backend `suggestions`, ChatShell arms a compare wizard. This component renders
 * a bot-style, UI-owned question plus a horizontal wrap of tappable turquoise
 * pill chips (Bendito Fantasy quick-reply style):
 *
 *   Step 1 (playerA == null):  "¿Cuál es el primer jugador?"   → all options
 *   Step 2 (playerA set):      "¿Contra quién lo comparamos?"  → remaining options
 *
 * The first tap stores playerA client-side (no round trip); the second tap
 * hands the picked name back to ChatShell, which sends the canonical
 * `comparar {A} vs {B}` question through the normal send path — so the wizard
 * and free-text "A vs B" converge on the identical ComparisonCard.
 *
 * All copy here is UI-owned; the backend never dictates the wizard wording.
 */
import type { Suggestion } from '@/lib/types';

export interface CompareWizardState {
  /** First player chosen; null until the first chip is tapped. */
  playerA: string | null;
  /** Backend-supplied suggestions (already ranked). */
  options: Suggestion[];
}

interface Props {
  wizard: CompareWizardState;
  /** Called with the tapped chip's send_text. */
  onPick: (sendText: string) => void;
}

const STEP1_QUESTION = '¿Cuál es el primer jugador?';
const STEP2_QUESTION = '¿Contra quién lo comparamos?';

export default function SuggestionChips({ wizard, onPick }: Props) {
  const isStep1 = wizard.playerA == null;
  const question = isStep1 ? STEP1_QUESTION : STEP2_QUESTION;
  // Step 2 hides the already-chosen player so it can't be compared with itself.
  const chips = isStep1
    ? wizard.options
    : wizard.options.filter((o) => o.send_text !== wizard.playerA);

  return (
    <div className="mt-3" data-testid="compare-wizard">
      <p className="text-[13px] font-semibold text-bf-text/90">{question}</p>
      {!isStep1 && (
        <p className="mt-0.5 text-[11px] text-bf-gray">
          Primer jugador: <span className="text-bf-turquoise font-medium">{wizard.playerA}</span>
        </p>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip.send_text}
            type="button"
            onClick={() => onPick(chip.send_text)}
            className="inline-flex items-center rounded-full border border-bf-turquoise/40 bg-bf-turquoise/10 px-3 py-1.5 text-[13px] font-medium text-bf-turquoise transition-colors hover:bg-bf-turquoise/20 hover:border-bf-turquoise/60 active:bg-bf-turquoise/25"
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  );
}
