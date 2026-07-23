/**
 * InjuryListTable — routes the injury_list intent's generic_card payload
 * through InjuriesTable's existing row treatment (status badge, chance %,
 * clamped news, relative date) instead of the generic bare CardTable.
 *
 * Why an adapter and not GenericCard directly: injury_list carries the same
 * generic_card contract as every other fallback intent (accent/title/pills/
 * columns/rows: string[][]) — it has no typed InjuryRow field of its own.
 * InjuriesTable's richer per-row formatting (status tone, "hace N días",
 * 2-line news clamp) is worth reusing rather than duplicating in CardTable,
 * so this component maps the generic string rows onto InjuryRow by matching
 * each column's header against the vocabulary the backend uses for injury
 * tables (English + Spanish; matches ResourceRows' @injuries columns).
 *
 * TS deviation from the raw contract: GenericCardMeta.rows is string[][]
 * with no typed chance_of_playing/news_added — this adapter best-effort
 * parses those back into numbers/ISO strings and degrades to '—'/null when
 * a column is missing or unparsable, rather than throwing.
 */
import type { GenericCardMeta, InjuryRow } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from './CardOrnaments';
import { InjuryRowItem } from './InjuriesTable';

interface Props {
  data: GenericCardMeta;
}

export default function InjuryListTable({ data }: Props) {
  const rows = genericCardToInjuryRows(data);

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coralSoft.border}`}>
      <div className="relative overflow-hidden border-b border-bf-coral-soft/20 px-4 py-2.5">
        <TriangleField color={ACCENT_HEX.coralSoft} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold uppercase tracking-wide text-white">
          {data.title}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="px-4 py-3 text-xs text-bf-gray">Sin lesiones reportadas</p>
      ) : (
        <div>
          {rows.map((row, idx) => (
            <InjuryRowItem key={`${row.web_name}-${idx}`} row={row} banded={idx % 2 === 0} />
          ))}
        </div>
      )}

      {data.footer != null && (
        <p className="border-t border-white/10 px-4 py-2 text-[11px] text-bf-gray/70">
          {data.footer}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Adapter — GenericCardMeta (string[][] rows) → InjuryRow[]
// ---------------------------------------------------------------------------

type ColumnKey = keyof InjuryRow | null;

/** Header keyword → InjuryRow field. First match wins; unmatched columns are ignored. */
const HEADER_MATCHERS: Array<{ field: ColumnKey; keywords: string[] }> = [
  { field: 'web_name', keywords: ['jugador', 'player', 'nombre', 'name'] },
  { field: 'team_short', keywords: ['equipo', 'team'] },
  { field: 'position', keywords: ['pos'] },
  { field: 'status_label', keywords: ['estado', 'status'] },
  { field: 'chance_of_playing', keywords: ['%', 'chance', 'probabilidad'] },
  { field: 'news', keywords: ['noticia', 'news', 'detalle'] },
  { field: 'news_added', keywords: ['fecha', 'date', 'added', 'actualizado'] },
];

function matchColumn(header: string): ColumnKey {
  const lower = header.toLowerCase();
  for (const { field, keywords } of HEADER_MATCHERS) {
    if (keywords.some((kw) => lower.includes(kw))) return field;
  }
  return null;
}

export function genericCardToInjuryRows(data: GenericCardMeta): InjuryRow[] {
  const fields = data.columns.map((col) => matchColumn(col.header));

  return data.rows.map((row, rowIdx) => {
    const out: InjuryRow = {
      web_name: '',
      team_short: '',
      position: 'MID',
      status_label: '—',
      chance_of_playing: null,
      news: '',
      news_added: null,
    };

    fields.forEach((field, colIdx) => {
      if (field == null) return;
      const raw = row[colIdx];
      if (raw == null) return;

      switch (field) {
        case 'chance_of_playing': {
          const parsed = Number.parseInt(raw.replace(/[^0-9-]/g, ''), 10);
          out.chance_of_playing = Number.isFinite(parsed) ? parsed : null;
          break;
        }
        case 'position':
          out.position = (raw as InjuryRow['position']) || 'MID';
          break;
        default:
          // web_name, team_short, status_label, news, news_added are all strings
          (out as unknown as Record<string, string>)[field] = raw;
          break;
      }
    });

    // Fallback: if no column matched a player name, use the first cell so the
    // row is still identifiable rather than a blank name.
    if (out.web_name === '' && row.length > 0) {
      out.web_name = row[0] ?? `Jugador ${rowIdx + 1}`;
    }

    return out;
  });
}
