/**
 * FixtureCompactGrid — the whole league on one screen (Track D / FI7).
 *
 * A dense team × gameweek matrix so the full 5/8/10-GW calendar fits without
 * scrolling — built for screen-sharing (e.g. talking through the run on a
 * podcast). Same band colours and run semantics as the detailed ticker, just
 * shrunk: each cell is band-tinted, run cells carry a turquoise/coral ring
 * (heavier for strong runs). Team codes and cells deep-link into chat.
 */
import type {
  FixtureOutlookMeta,
  FixtureOutlookGW,
  FixtureOutlookRun,
} from '@/lib/types';
import { bandColor } from '@/lib/fixture-outlook-format';
import { teamOutlookQuestion, fixtureCellQuestion } from '@/lib/fixture-chat-links';

/** Per-cell ring for a run cell — static class strings only (Tailwind JIT). */
function runRingClass(run: FixtureOutlookRun | undefined): string {
  if (!run) return '';
  const strong = run.intensity === 'strong';
  if (run.type === 'good') {
    return strong ? 'ring-2 ring-bf-turquoise/70' : 'ring-1 ring-bf-turquoise/45';
  }
  return strong ? 'ring-2 ring-bf-coral/70' : 'ring-1 ring-bf-coral/45';
}

export function FixtureCompactGrid({
  data,
  onAsk,
}: {
  data: FixtureOutlookMeta;
  onAsk: (question: string) => void;
}) {
  const { teams, axis } = data;
  // All teams share the same aligned gameweek columns; take them from row 1.
  const gameweeks = teams[0]?.series.map((s) => s.gameweek) ?? [];

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-1 text-center">
        <thead>
          <tr>
            <th className="text-left text-[9px] font-bold uppercase tracking-wider text-bf-gray/60 pl-1">
              Equipo
            </th>
            {gameweeks.map((g) => (
              <th
                key={g}
                className="text-[9px] font-bold uppercase tracking-wider text-bf-gray/60"
              >
                J{g}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {teams.map((t) => {
            const runByGw = new Map<number, FixtureOutlookRun>();
            for (const r of t.runs) {
              for (let g = r.start_gw; g <= r.end_gw; g++) runByGw.set(g, r);
            }
            return (
              <tr key={t.team_short}>
                <th scope="row" className="text-left">
                  <button
                    type="button"
                    onClick={() => onAsk(teamOutlookQuestion(t.team_name, axis))}
                    title={`${t.team_name} — preguntar en el chat`}
                    className="text-[11px] font-extrabold tracking-wide text-white hover:text-bf-turquoise transition-colors pl-1 pr-2"
                  >
                    {t.team_short}
                  </button>
                </th>
                {t.series.map((gw) => (
                  <CompactCell
                    key={gw.gameweek}
                    gw={gw}
                    run={runByGw.get(gw.gameweek)}
                    onAsk={() => onAsk(fixtureCellQuestion(t.team_name, gw, axis))}
                  />
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CompactCell({
  gw,
  run,
  onAsk,
}: {
  gw: FixtureOutlookGW;
  run: FixtureOutlookRun | undefined;
  onAsk: () => void;
}) {
  const blank = gw.band === null;
  const color = blank ? '#6b7280' : bandColor(gw.band as 1 | 2 | 3 | 4 | 5);
  const label = blank
    ? '—'
    : gw.fixtures.map((f) => `${f.opponent_short}${f.is_home ? '' : "'"}`).join('/');

  return (
    <td>
      <button
        type="button"
        onClick={onAsk}
        title={
          blank
            ? 'Sin partido (jornada en blanco)'
            : `${label} · dificultad ${gw.band} — preguntar en el chat`
        }
        className={`w-full min-w-[38px] rounded px-0.5 py-1 text-[9px] font-extrabold leading-none tracking-tight transition-transform hover:-translate-y-0.5 ${runRingClass(run)}`}
        style={{ backgroundColor: `${color}33`, color }}
      >
        {label}
      </button>
    </td>
  );
}
