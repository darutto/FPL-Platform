/**
 * WcStandingsTable — structured rendering for World Cup group standings.
 *
 * Rendered beneath final_text when response.outcome === 'ok' and
 * response.standings is a non-empty group → rows map (see
 * lib/wc-intent-renderer.ts selectWcIntentView).
 *
 * One card per group, each with its own table (PJ/G/E/P/GF/GC/DG/Pts).
 * Country names and the group key are already locale_es-localized by the
 * backend.
 */
import type { WcStandingsRow } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: Record<string, WcStandingsRow[]>;
}

export default function WcStandingsTable({ data }: Props) {
  const groups = Object.keys(data).sort();
  if (groups.length === 0) return null;

  return (
    <div className="mt-3 space-y-3 text-sm">
      {groups.map((group) => (
        <GroupTable key={group} group={group} rows={data[group]} />
      ))}
    </div>
  );
}

function GroupTable({ group, rows }: { group: string; rows: WcStandingsRow[] }) {
  if (rows.length === 0) return null;

  return (
    <div className={`${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-turquoise/20">
        <TriangleField color={ACCENT_HEX.turquoise} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          Grupo {group}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-bf-gray text-[10px] uppercase tracking-wide">
              <th className="text-left px-4 py-1.5 font-bold">Equipo</th>
              <th className="px-2 py-1.5 font-bold">PJ</th>
              <th className="px-2 py-1.5 font-bold">G</th>
              <th className="px-2 py-1.5 font-bold">E</th>
              <th className="px-2 py-1.5 font-bold">P</th>
              <th className="px-2 py-1.5 font-bold">GF</th>
              <th className="px-2 py-1.5 font-bold">GC</th>
              <th className="px-2 py-1.5 font-bold">DG</th>
              <th className="px-3 py-1.5 font-bold text-bf-turquoise">Pts</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={row.team} className={idx % 2 === 0 ? 'bg-white/[0.035]' : ''}>
                <td className="px-4 py-1.5 font-bold text-white truncate">{row.team}</td>
                <td className="px-2 py-1.5 text-center text-bf-text">{row.played}</td>
                <td className="px-2 py-1.5 text-center text-bf-text">{row.won}</td>
                <td className="px-2 py-1.5 text-center text-bf-text">{row.drawn}</td>
                <td className="px-2 py-1.5 text-center text-bf-text">{row.lost}</td>
                <td className="px-2 py-1.5 text-center text-bf-text">{row.goals_for}</td>
                <td className="px-2 py-1.5 text-center text-bf-text">{row.goals_against}</td>
                <td className="px-2 py-1.5 text-center text-bf-text">{row.goal_difference}</td>
                <td className="px-3 py-1.5 text-center font-display text-bf-turquoise tracking-tighter">
                  {row.points}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
