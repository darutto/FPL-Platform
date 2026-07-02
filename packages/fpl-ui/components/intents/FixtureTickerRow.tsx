/**
 * FixtureTickerRow — one team's ticker row, shared by the in-chat
 * FixtureOutlookCard and the standalone /fixtures board (FI7).
 *
 * Verdict line leads (chat-first), then a per-GW colour strip where the cells
 * of a detected good/bad run are grouped inside a tinted ring (bf-turquoise /
 * bf-coral; heavier ring + ★ for strong runs) so a run reads as one block.
 *
 * Deep-links (optional): when `onAskTeam` / `onAskCell` are provided the team
 * code and each GW cell become buttons that hand a ready-made question to chat
 * (the /fixtures board wires them); the in-chat card leaves them plain.
 */
import type {
  TeamOutlook,
  FixtureOutlookGW,
  FixtureOutlookRun,
} from '@/lib/types';
import { bandColor } from '@/lib/fixture-outlook-format';

export function FixtureTickerRow({
  team,
  onAskTeam,
  onAskCell,
}: {
  team: TeamOutlook;
  onAskTeam?: () => void;
  onAskCell?: (gw: FixtureOutlookGW) => void;
}) {
  const { team_short, verdict, series, runs } = team;

  // Map each GW to the run it belongs to (runs are contiguous, non-overlapping).
  const runByGw = new Map<number, FixtureOutlookRun>();
  for (const r of runs) {
    for (let g = r.start_gw; g <= r.end_gw; g++) runByGw.set(g, r);
  }
  // Slice into consecutive segments that share the same run (or none) so a run
  // renders as ONE grouped block rather than loose cells.
  type Segment = { run: FixtureOutlookRun | null; cells: FixtureOutlookGW[] };
  const segments: Segment[] = [];
  for (const gw of series) {
    const run = runByGw.get(gw.gameweek) ?? null;
    const last = segments[segments.length - 1];
    if (last && last.run === run) last.cells.push(gw);
    else segments.push({ run, cells: [gw] });
  }

  const teamLabel = onAskTeam ? (
    <button
      type="button"
      onClick={onAskTeam}
      className="text-xs font-bold tracking-wide text-white hover:text-bf-turquoise transition-colors"
    >
      {team_short}
    </button>
  ) : (
    <span className="text-xs font-bold tracking-wide text-white">{team_short}</span>
  );

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        {teamLabel}
        {verdict && <span className="text-[11px] leading-snug text-bf-gray">{verdict}</span>}
      </div>

      <div className="flex items-center gap-1 overflow-x-auto px-0.5 py-1">
        {segments.map((seg, i) =>
          seg.run ? (
            <RunGroup key={`run-${i}`} run={seg.run} cells={seg.cells} onAskCell={onAskCell} />
          ) : (
            seg.cells.map((gw) => (
              <GwCell key={gw.gameweek} gw={gw} onAsk={onAskCell && (() => onAskCell(gw))} />
            ))
          ),
        )}
      </div>
    </div>
  );
}

function GwCell({ gw, onAsk }: { gw: FixtureOutlookGW; onAsk?: () => void }) {
  const blank = gw.band === null;
  const color = blank ? '#6b7280' : bandColor(gw.band as 1 | 2 | 3 | 4 | 5);
  // DGW: show both opponents compactly; blank: an em dash.
  const label = blank
    ? '—'
    : gw.fixtures.map((f) => `${f.opponent_short}${f.is_home ? '' : "'"}`).join('/');

  const gwHeader = (
    <span className="px-1 py-0.5 text-center text-[8px] font-bold uppercase tracking-wider text-bf-gray bg-white/[0.04] border-b border-white/5">
      J{gw.gameweek}
      {gw.is_dgw ? '··' : ''}
    </span>
  );
  const valueClass = 'px-1 py-1 text-center text-[10px] font-extrabold tracking-tight';
  const valueStyle = { backgroundColor: `${color}33`, color };
  const shell =
    'flex flex-col items-stretch rounded-md overflow-hidden min-w-[44px] bg-white/[0.04] border border-white/10';

  if (onAsk) {
    return (
      <button
        type="button"
        onClick={onAsk}
        title={blank ? 'Sin partido (jornada en blanco)' : 'Preguntar en el chat sobre este partido'}
        className={`${shell} transition-transform hover:-translate-y-0.5 hover:border-white/25`}
      >
        {gwHeader}
        <span className={valueClass} style={valueStyle}>
          {label}
        </span>
      </button>
    );
  }

  return (
    <div className={shell}>
      {gwHeader}
      <span
        className={valueClass}
        style={valueStyle}
        title={blank ? 'Sin partido (jornada en blanco)' : undefined}
      >
        {label}
      </span>
    </div>
  );
}

/**
 * RunGroup — wraps the consecutive cells of a detected run in a tinted ring so
 * the run reads as one connected block (NextXI's grouping idea, in BF tokens).
 * good → turquoise, bad → coral; strong runs get a heavier ring + a ★ marker.
 */
function RunGroup({
  run,
  cells,
  onAskCell,
}: {
  run: FixtureOutlookRun;
  cells: FixtureOutlookGW[];
  onAskCell?: (gw: FixtureOutlookGW) => void;
}) {
  const good = run.type === 'good';
  const strong = run.intensity === 'strong';

  // Static class strings only (Tailwind JIT can't see interpolated names).
  const ringClass = good
    ? strong
      ? 'ring-2 ring-bf-turquoise/70 bg-bf-turquoise/[0.07]'
      : 'ring-1 ring-bf-turquoise/45 bg-bf-turquoise/[0.04]'
    : strong
      ? 'ring-2 ring-bf-coral/70 bg-bf-coral/[0.07]'
      : 'ring-1 ring-bf-coral/45 bg-bf-coral/[0.04]';
  const starClass = good ? 'text-bf-turquoise' : 'text-bf-coral';

  return (
    <div
      className={`flex items-center gap-1 rounded-lg px-1 py-0.5 ${ringClass}`}
      title={`${good ? 'Buena' : 'Mala'} racha J${run.start_gw}–J${run.end_gw} (${run.length} jornadas)`}
    >
      {strong && (
        <span className={`shrink-0 text-[11px] leading-none ${starClass}`} aria-hidden>★</span>
      )}
      {cells.map((gw) => (
        <GwCell key={gw.gameweek} gw={gw} onAsk={onAskCell && (() => onAskCell(gw))} />
      ))}
    </div>
  );
}

/** Difficulty band legend (1=easiest … 5=hardest). Shared with the card. */
export function BandLegend() {
  const levels = [1, 2, 3, 4, 5] as const;
  return (
    <div className="flex items-center gap-2 pt-1">
      <span className="text-[10px] font-bold uppercase tracking-wider text-bf-gray/70">Dificultad:</span>
      {levels.map((d) => (
        <span
          key={d}
          className="text-[10px] font-bold rounded px-1.5 py-0.5"
          style={{ backgroundColor: `${bandColor(d)}30`, color: bandColor(d) }}
        >
          {d}
        </span>
      ))}
    </div>
  );
}
