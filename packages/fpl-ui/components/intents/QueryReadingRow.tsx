'use client';

/**
 * QueryReadingRow — the first row inside a query card: what was computed, part by part.
 *
 * Every word comes from the backend's `query.reading` block; this component adds none. A part is drawn from
 * its label whatever its kind, so a kind added on the server needs no change here. An editable part is a pill
 * that opens its typed alternatives; picking one hands the alternative's spec back untouched (a tap is never
 * turned into text). A braked part is the one that stopped the answer.
 *
 * Without `onPick` (a shared image, an older turn) every part is plain.
 */
import { useId, useState } from 'react';
import type { QueryReading, QueryReadingAlternative, QueryReadingPart, QuerySpecDict } from '@/lib/types';

interface Props {
  reading: QueryReading;
  /** The tapped alternative's spec, with the part it replaces. */
  onPick?: (spec: QuerySpecDict, part: QueryReadingPart, alternative: QueryReadingAlternative) => void;
}

const SEGMENT = 'rounded-full px-2.5 py-1 text-[12px] font-extrabold leading-tight';
const PLAIN = 'text-bf-text';
const BRAKED = 'border border-amber-400/60 bg-amber-400/10 text-amber-300';
const PILL = 'border border-white/15 bg-black/30 text-bf-text hover:border-white/35';
const PILL_OPEN = 'border border-bf-coral bg-bf-coral text-bf-ink';

export default function QueryReadingRow({ reading, onPick }: Props) {
  const [open, setOpen] = useState<number | null>(null);
  const choicesId = useId();
  const openPart = open != null ? reading.parts[open] : undefined;

  return (
    <div data-testid="query-reading" lang={reading.lang} className="space-y-2">
      <ul className="flex flex-wrap items-center gap-1.5">
        {reading.parts.map((part, i) => {
          const tappable = onPick != null && part.editable && part.alternatives.length > 0;
          const tone = part.braked ? BRAKED : tappable ? PILL : PLAIN;
          return (
            <li key={`${part.kind}-${i}`} data-kind={part.kind} data-braked={part.braked || undefined}>
              {tappable ? (
                <button
                  type="button"
                  aria-expanded={open === i}
                  aria-controls={open === i ? choicesId : undefined}
                  onClick={() => setOpen(open === i ? null : i)}
                  className={`${SEGMENT} inline-flex items-center gap-1 transition-colors ${open === i ? PILL_OPEN : tone}`}
                >
                  {part.braked && <span aria-hidden="true">⚠</span>}
                  <span>{part.label}</span>
                  <span aria-hidden="true" className="text-[9px] opacity-70">▾</span>
                </button>
              ) : (
                <span className={`${SEGMENT} inline-flex items-center gap-1 ${tone}`}>
                  {part.braked && <span aria-hidden="true">⚠</span>}
                  <span>{part.label}</span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {openPart != null && onPick != null && (
        <div id={choicesId} role="group" aria-label={openPart.label} className="flex flex-wrap gap-1.5">
          {openPart.alternatives.map((alternative) => (
            <button
              key={alternative.label}
              type="button"
              onClick={() => {
                setOpen(null);
                onPick(alternative.spec, openPart, alternative);
              }}
              className={`${SEGMENT} border border-white/10 bg-white/[0.06] text-bf-gray transition-colors hover:text-bf-text`}
            >
              {alternative.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
