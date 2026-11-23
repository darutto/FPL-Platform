'use client';

/**
 * LoadingWord — the generic "an answer is pending" indicator: a short football/fantasy word that changes
 * every ~2.5 s, never the same word twice in a row. Words live in the i18n dictionaries (`loading.word.N`).
 *
 * prefers-reduced-motion: one static word, no pulse and no rotation. It is only the generic indicator; the
 * EO auto-retry pending line carries real information and is rendered elsewhere, unchanged.
 */
import { useEffect, useState } from 'react';
import { useT } from '@/lib/i18n/LocaleProvider';
import type { DictKey } from '@/lib/i18n/dictionary';

export const LOADING_WORD_COUNT = 10;
export const LOADING_WORD_INTERVAL_MS = 2500;

function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** A word index different from `current` (any index when there is no current one). */
export function nextWordIndex(current: number, random: () => number = Math.random): number {
  const step = 1 + Math.floor(random() * (LOADING_WORD_COUNT - 1));
  return (current + step) % LOADING_WORD_COUNT;
}

export default function LoadingWord() {
  const t = useT();
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    const timer = setInterval(() => setIndex((current) => nextWordIndex(current)), LOADING_WORD_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <span role="status" data-testid="loading-word" className="text-bf-turquoise text-sm motion-safe:animate-pulse">
      {t(`loading.word.${index + 1}` as DictKey)}…
    </span>
  );
}
