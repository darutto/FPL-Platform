/**
 * StatComparisonTable — additive raw-stat comparison table appended below the
 * compare_players verdict in ComparisonCard (v1, first-pass — see
 * FINAL_RESPONSE_CONTRACT.md).
 *
 * Bespoke, not a CardTable extension: CardTable's per-column `kind`
 * (text|mono|badge) with string-vocabulary tone inference is the wrong
 * primitive for per-cell "this is the winner," and this table's shape (two
 * named-player columns + a label column) is closer to ComparisonCard's own
 * OptionCol layout than to CardTable's generic N-column model. Reuses
 * CardTable's mobile-hardened visual conventions literally (overflow-x-auto,
 * min-w, alternating row tint, truncate).
 *
 * Contract: the backend is fully authoritative for `better` and `kind` — this
 * component renders them exactly as provided, with no frontend override
 * logic (context rows are styled muted purely as a visual choice driven by
 * `kind`, not as a correctness guard the frontend enforces).
 */
import type { StatComparisonMeta, StatRow } from '@/lib/types';

interface Props {
  data: StatComparisonMeta;
  nameA: string;
  nameB: string;
}

export default function StatComparisonTable({ data, nameA, nameB }: Props) {
  if (!data.rows.length) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[360px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-white/10">
            <th scope="col" className="px-2 py-1.5 text-left text-[10px] font-extrabold uppercase tracking-wide text-bf-gray">
              Stat
            </th>
            <th scope="col" className="max-w-[90px] truncate px-2 py-1.5 text-right text-[10px] font-extrabold uppercase tracking-wide text-bf-gray">
              {nameA}
            </th>
            <th scope="col" className="max-w-[90px] truncate px-2 py-1.5 text-right text-[10px] font-extrabold uppercase tracking-wide text-bf-gray">
              {nameB}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <StatTableRow key={row.key} row={row} banded={i % 2 === 0} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatTableRow({ row, banded }: { row: StatRow; banded: boolean }) {
  const muted = row.kind === 'context';
  return (
    <tr className={banded ? 'bg-white/[0.035]' : ''}>
      <th
        scope="row"
        className={`min-w-0 truncate px-2 py-1.5 text-left font-normal ${
          muted ? 'text-bf-gray/70' : 'text-bf-text/80'
        }`}
      >
        {row.label}
      </th>
      <StatCell cell={row.value_a} isBetter={row.better === 'a'} muted={muted} />
      <StatCell cell={row.value_b} isBetter={row.better === 'b'} muted={muted} />
    </tr>
  );
}

function StatCell({
  cell,
  isBetter,
  muted,
}: {
  cell: StatRow['value_a'];
  isBetter: boolean;
  muted: boolean;
}) {
  return (
    <td
      data-testid={isBetter ? 'stat-cell-better' : undefined}
      className={`px-2 py-1.5 text-right font-display tabular-nums tracking-tighter ${
        isBetter
          ? 'font-extrabold text-bf-turquoise'
          : muted
            ? 'text-bf-gray/60'
            : 'text-bf-text/70'
      }`}
    >
      {isBetter && <span className="sr-only">Mejor valor: </span>}
      {cell.display}
    </td>
  );
}
