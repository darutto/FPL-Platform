/**
 * ProvenanceStamp — which data a card was built from (i74). Always rendered when the payload carries
 * provenance: a muted caption for live-season data, a gold notice for anything else. The text is the
 * backend's `label` verbatim (it already carries the ⚠) so the card and the plain-text answers state the same
 * fact the same way.
 *
 * Shared card block: props are data, no question logic. A block draws the strings it is given; it never
 * computes a figure, picks wording or looks at which question was asked.
 */

export interface Provenance {
  label: string;
  /** Anything but 'current' is drawn as a notice. */
  status: string;
}

export default function ProvenanceStamp({ provenance }: { provenance: Provenance }) {
  const stale = provenance.status !== 'current';
  return (
    <p
      data-testid="zonal-provenance"
      data-status={provenance.status}
      className={
        stale
          ? 'mb-3.5 rounded-[8px] border border-bf-gold/35 bg-bf-gold/[0.07] px-3 py-2 text-[11.5px] font-semibold leading-snug text-bf-gold'
          : 'mb-3.5 text-[10.5px] font-medium tracking-[0.02em] text-bf-gray/55'
      }
    >
      {provenance.label}
    </p>
  );
}
