/**
 * FootNote — the small print under a card.
 *
 * Shared card block: props are data, no question logic. A block draws the strings it is given; it never
 * computes a figure, picks wording or looks at which question was asked.
 */
'use client';

import { useSharedImage } from '@/lib/chat-ask';

interface Props {
  /** One line is a paragraph; several are stacked. Empty entries are skipped; no lines draws nothing. */
  lines: (string | null | undefined)[];
  /** Left out of the picture a user shares; kept in the app. */
  hideInShare?: boolean;
  /** For a card whose body has no padding of its own. */
  inset?: boolean;
  /** Keep the line breaks the server sent. */
  preLine?: boolean;
  /** Draw a stack even when only one line is present. */
  stacked?: boolean;
  testId?: string;
}

const RULE_TOP = 'border-t border-white/10';
const TYPE = 'text-[11px] text-bf-gray/70';

export default function FootNote({ lines, hideInShare, inset, preLine, stacked, testId }: Props) {
  const sharedImage = useSharedImage();
  const shown = lines.filter((line): line is string => line != null && line !== '');
  if (shown.length === 0 || (hideInShare && sharedImage)) return null;
  const className = `${preLine ? 'whitespace-pre-line ' : ''}${RULE_TOP} ${inset ? 'px-4 py-2' : 'pt-2'} ${TYPE}`;
  if (shown.length === 1 && !stacked) {
    return (
      <p data-testid={testId} className={className}>
        {shown[0]}
      </p>
    );
  }
  return (
    <div data-testid={testId} className={`space-y-0.5 ${className}`}>
      {shown.map((line, i) => (
        <p key={i}>{line}</p>
      ))}
    </div>
  );
}
