import type { EvidenceItem } from '@/lib/evidence';
import { BASIS_LABELS, DIRECTION_LABELS } from '@/lib/evidence-presentation';
import ConfidenceBadge from './ConfidenceBadge';

interface Props {
  item: EvidenceItem;
}

export default function EvidenceChip({ item }: Props) {
  const sourceText = item.source_features.length > 0
    ? `Fuentes: ${item.source_features.join(' · ')}`
    : 'Fuentes: no indicadas';

  return (
    <div className="min-w-0 rounded-card border border-white/10 bg-white/[0.03] p-3 text-bf-text hc:border-bf-text/60">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 break-words text-sm font-bold leading-snug">{item.label}</p>
        <ConfidenceBadge confidence={item.confidence} />
      </div>
      <p className="mt-2 break-words text-sm leading-relaxed text-bf-text/85 hc:text-bf-text">{item.summary}</p>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-bf-gray hc:text-bf-text">
        <span>Base: {BASIS_LABELS[item.basis]}</span>
        <span>Dirección: {DIRECTION_LABELS[item.direction]}</span>
      </div>
      <p className="mt-2 break-words text-[11px] text-bf-gray hc:text-bf-text">{sourceText}</p>
    </div>
  );
}
