/**
 * CardTable — reusable table shell for GenericCard (and future) card bodies.
 *
 * Design:
 *   - Outer `overflow-x-auto` wrapper so a wide table scrolls INSIDE the
 *     card — the page itself must never scroll horizontally.
 *   - `text`-kind cells are `min-w-0` + `truncate` by default (or
 *     `line-clamp-2` when `clampText` is set), so long player/news strings
 *     never blow out the row height or column width.
 *   - `mono`-kind cells use the display face (Archivo Black via font-display)
 *     for numeric/stat columns, right-aligned per the column spec.
 *   - `badge`-kind cells render as a tinted pill; GenericCardMeta doesn't
 *     carry a per-cell tone, so the tone is inferred from the cell text via
 *     `inferBadgeTone` (exported for reuse/testing).
 *
 * Props are intentionally generic (columns + rows in the backend's
 * generic_card shape) so other card components can adopt this primitive
 * later instead of hand-rolling their own table markup.
 */
import { PILL_BASE, STATUS_TONE_CLASSES, type StatusTone } from '@/lib/theme';

export interface CardTableColumn {
  header: string;
  align: 'left' | 'right';
  kind: 'text' | 'mono' | 'badge';
}

interface Props {
  columns: CardTableColumn[];
  rows: string[][];
  /** Clamp text-kind cells to 2 lines instead of a single-line truncate. */
  clampText?: boolean;
}

export default function CardTable({ columns, rows, clampText = false }: Props) {
  if (columns.length === 0 || rows.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-white/10">
            {columns.map((col, i) => (
              <th
                key={`${col.header}-${i}`}
                scope="col"
                className={`whitespace-nowrap px-3 py-2 text-[11px] font-extrabold uppercase tracking-wide text-bf-gray ${
                  col.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIdx) => (
            <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-white/[0.035]' : ''}>
              {columns.map((col, colIdx) => (
                <td
                  key={colIdx}
                  className={`min-w-0 px-3 py-2 align-top ${
                    col.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  <CardTableCell col={col} value={row[colIdx] ?? ''} clampText={clampText} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CardTableCell({
  col,
  value,
  clampText,
}: {
  col: CardTableColumn;
  value: string;
  clampText: boolean;
}) {
  if (col.kind === 'badge') {
    const tone = inferBadgeTone(value);
    return <span className={`${PILL_BASE} ${STATUS_TONE_CLASSES[tone]}`}>{value}</span>;
  }
  if (col.kind === 'mono') {
    return (
      <span className="block font-display text-sm leading-none tracking-tighter text-white">
        {value}
      </span>
    );
  }
  return (
    <span className={`min-w-0 text-bf-text/90 ${clampText ? 'line-clamp-2 block' : 'block truncate'}`}>
      {value}
    </span>
  );
}

/**
 * Best-effort tone inference for badge-kind cells. GenericCardMeta carries a
 * tone on pills/hero but not per table cell, so badge cells read common
 * status vocabulary (English + Spanish) instead. Defaults to 'warn' for
 * anything unrecognized — err toward "pay attention", matching the
 * InjuriesTable convention this primitive is designed to sit alongside.
 */
export function inferBadgeTone(text: string): StatusTone {
  const lower = text.toLowerCase();
  if (
    lower.includes('injur') ||
    lower.includes('lesion') ||
    lower.includes('suspend') ||
    lower.includes('unavailable') ||
    lower.includes('baja') ||
    lower.includes('no disponible')
  ) {
    return 'bad';
  }
  if (
    lower.includes('doubt') ||
    lower.includes('duda') ||
    lower.includes('75%') ||
    lower.includes('50%') ||
    lower.includes('25%')
  ) {
    return 'warn';
  }
  if (
    lower === 'available' ||
    lower === 'fit' ||
    lower === 'disponible' ||
    lower === 'apto' ||
    lower === 'ok'
  ) {
    return 'good';
  }
  return 'warn';
}
