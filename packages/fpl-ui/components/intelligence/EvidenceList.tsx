'use client';

import { useId } from 'react';
import type { EvidenceItem } from '@/lib/evidence';
import { prepareEvidenceItems } from '@/lib/evidence-presentation';
import EvidenceChip from './EvidenceChip';

interface Props {
  evidence: readonly EvidenceItem[] | null | undefined;
}

export default function EvidenceList({ evidence }: Props) {
  const headingId = useId();
  const prepared = prepareEvidenceItems(evidence ?? []);
  if (prepared.length === 0) return null;

  return (
    <section className="mt-3 min-w-0" aria-labelledby={headingId}>
      <h3 id={headingId} className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-bf-turquoise hc:text-bf-text">
        Evidencia
      </h3>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {prepared.map(({ item, key }) => (
          <li key={key} className="min-w-0">
            <EvidenceChip item={item} />
          </li>
        ))}
      </ul>
    </section>
  );
}
