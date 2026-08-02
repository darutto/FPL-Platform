interface Props {
  confidence: number;
}

export default function ConfidenceBadge({ confidence }: Props) {
  return (
    <span className="inline-flex rounded-full border border-white/15 bg-white/[0.04] px-2 py-0.5 text-[11px] font-semibold text-bf-text hc:border-bf-text hc:text-bf-text">
      Confianza {Math.round(confidence * 100)}%
    </span>
  );
}
