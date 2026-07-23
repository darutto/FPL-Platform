'use client';

/**
 * StarterPrompts — clickable prompt chips shown on empty chat.
 *
 * The player-named prompts are DYNAMIC: on mount we fetch the current
 * most-transferred-in (top buys) and most-transferred-out (top sells) players
 * from /api/fpl-trending and weave them into the chips, so the suggestions stay
 * timely without code edits. Until that resolves — and pre-season / on any
 * error, when FPL has no transfer signal yet — we show STATIC_PROMPTS, a
 * curated set whose names are all current Premier League players (keep them so
 * if you edit them). Clicking populates the question and sends immediately.
 *
 * For slash-command starters, the text includes the command prefix
 * so parseSlashCommand picks up the intent_hint automatically.
 */
import { useEffect, useState } from 'react';

const STATIC_PROMPTS = [
  '¿A quién debería dar el brazalete?',
  '/comparar Haaland vs Bruno Fernandes',
  '¿Debería usar el triple capitán?',
  '/diferenciales menos del 10%',
  '/transferencia Cole Palmer por Saka',
  '/calendarios Haaland',
] as const;

interface TrendingResponse {
  active: boolean;
  in: string[];
  out: string[];
}

/**
 * Weave live top buys/sells into the named chips; the three generic prompts are
 * always kept. `topIn[0]` (hottest buy) anchors the compare, transfer and
 * calendar chips; `topOut[0]` (hottest sell, distinct from the buy) is the
 * sell side of the transfer suggestion.
 */
export function buildDynamicPrompts(topIn: string[], topOut: string[]): string[] {
  const buyA = topIn[0];
  const buyB = topIn[1];
  const sell = topOut.find((o) => o !== buyA) ?? topOut[0];
  return [
    '¿A quién debería dar el brazalete?',
    `/comparar ${buyA} vs ${buyB}`,
    '¿Debería usar el triple capitán?',
    '/diferenciales menos del 10%',
    `/transferencia ${sell} por ${buyA}`,
    `/calendarios ${buyA}`,
  ];
}

interface Props {
  onSelect: (prompt: string) => void;
}

export default function StarterPrompts({ onSelect }: Props) {
  const [prompts, setPrompts] = useState<readonly string[]>(STATIC_PROMPTS);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/fpl-trending');
        if (!res.ok) return;
        const data = (await res.json()) as TrendingResponse;
        // Guard here too (not just server-side): only swap when we truly have
        // enough distinct names, otherwise keep the curated static prompts.
        if (!cancelled && data.active && data.in.length >= 2 && data.out.length >= 1) {
          setPrompts(buildDynamicPrompts(data.in, data.out));
        }
      } catch {
        /* keep static prompts */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-wrap gap-2 justify-center max-w-lg">
      {prompts.map((prompt) => (
        <button
          key={prompt}
          onClick={() => onSelect(prompt)}
          className="text-xs font-bold bg-bf-turquoise/10 hover:bg-bf-turquoise/20 border border-bf-turquoise/40 text-bf-turquoise rounded-full px-3 py-1.5 transition-colors"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}
