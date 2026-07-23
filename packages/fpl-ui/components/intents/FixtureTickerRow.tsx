/**
 * FixtureTickerRow — one team's ticker row, shared by the in-chat
 * FixtureOutlookCard and the standalone /fixtures board (FI7).
 *
 * "Calendario FDR" readability design (Bendito Fantasy DS): a team header
 * (big code + "Prom X.X" average pill + Spanish verdict), then a row of
 * per-GW cells. Each cell is a vertical stack — J{gw}, opponent code, venue
 * (L/V), and a small FDR number badge — tinted by its difficulty band. The
 * cells of a detected run are grouped inside a tinted ring (turquoise good /
 * coral bad) so the run reads as one block.
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
import {
  bandColor,
  bandLabel,
  venueLabel,
  hexRgba,
  BLANK_COLOR,
  type Band,
} from '@/lib/fixture-outlook-format';

const GOOD_HEX = '#02EBAE';
const BAD_HEX = '#FF6A4D';

/** Colours for a difficulty band (or the neutral blank-GW grey). */
function cellColors(band: number | null) {
  const fg = band === null ? BLANK_COLOR : bandColor(band as Band);
  return { fg, bg: hexRgba(fg, 0.2), bd: hexRgba(fg, 0.55) };
}

/** Opponent label for a GW cell: single, DGW join, or an em dash when blank. */
function cellOpponents(gw: FixtureOutlookGW): string {
  if (gw.fixtures.length === 0) return '—';
  return gw.fixtures.map((f) => f.opponent_short).join('/');
}

/** Venue label: L/V for a single fixture, joined for a DGW, empty when blank. */
function cellVenue(gw: FixtureOutlookGW): string {
  if (gw.fixtures.length === 0) return '';
  return gw.fixtures.map((f) => venueLabel(f.is_home)).join('/');
}

export function FixtureTickerRow({
  team,
  onAskTeam,
  onAskCell,
  showFdrNumbers = true,
}: {
  team: TeamOutlook;
  onAskTeam?: () => void;
  onAskCell?: (gw: FixtureOutlookGW) => void;
  showFdrNumbers?: boolean;
}) {
  const { team_short, verdict, series, runs, avg_band } = team;

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
      className="text-[22px] font-black tracking-tight leading-none text-white hover:text-bf-turquoise transition-colors min-w-[58px] text-left"
    >
      {team_short}
    </button>
  ) : (
    <span className="text-[22px] font-black tracking-tight leading-none text-white min-w-[58px]">
      {team_short}
    </span>
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3.5 flex-wrap">
        {teamLabel}
        <AvgPill avg={avg_band} />
        {verdict && <span className="text-[14.5px] text-bf-gray">{verdict}</span>}
      </div>

      <div className="flex items-start gap-2 overflow-x-auto flex-wrap">
        {segments.map((seg, i) => (
          <RunGroup
            key={seg.run ? `run-${i}` : `gap-${i}`}
            run={seg.run}
            cells={seg.cells}
            onAskCell={onAskCell}
            showFdrNumbers={showFdrNumbers}
          />
        ))}
      </div>
    </div>
  );
}

/** "Prom X.X" — the team's mean difficulty across the horizon, band-coloured. */
export function AvgPill({ avg }: { avg: number | null }) {
  if (avg === null) {
    return (
      <span className="text-[13px] font-extrabold rounded-full px-3 py-1 bg-white/5 text-bf-gray/70 border border-white/10 whitespace-nowrap">
        Prom —
      </span>
    );
  }
  const band = Math.max(1, Math.min(5, Math.round(avg))) as Band;
  const fg = bandColor(band);
  return (
    <span
      className="text-[13px] font-extrabold rounded-full px-3 py-1 whitespace-nowrap border"
      style={{ backgroundColor: hexRgba(fg, 0.16), color: fg, borderColor: hexRgba(fg, 0.5) }}
    >
      Prom {avg.toFixed(1)}
    </span>
  );
}

/**
 * RunGroup — wraps consecutive cells in a tinted ring when they form a run, so
 * the run reads as one connected block. good → turquoise, bad → coral.
 */
function RunGroup({
  run,
  cells,
  onAskCell,
  showFdrNumbers,
}: {
  run: FixtureOutlookRun | null;
  cells: FixtureOutlookGW[];
  onAskCell?: (gw: FixtureOutlookGW) => void;
  showFdrNumbers: boolean;
}) {
  const runHex = run ? (run.type === 'good' ? GOOD_HEX : BAD_HEX) : null;
  const wrapStyle = runHex
    ? { border: `1.5px solid ${hexRgba(runHex, 0.65)}`, backgroundColor: hexRgba(runHex, 0.05) }
    : { border: '1.5px solid transparent', backgroundColor: 'transparent' };

  return (
    <div className="flex gap-2.5 flex-wrap rounded-xl p-[7px]" style={wrapStyle}>
      {cells.map((gw) => (
        <GwCell
          key={gw.gameweek}
          gw={gw}
          runHex={runHex}
          onAsk={onAskCell && (() => onAskCell(gw))}
          showFdrNumbers={showFdrNumbers}
        />
      ))}
    </div>
  );
}

function GwCell({
  gw,
  runHex,
  onAsk,
  showFdrNumbers,
}: {
  gw: FixtureOutlookGW;
  runHex: string | null;
  onAsk?: () => void;
  showFdrNumbers: boolean;
}) {
  const blank = gw.band === null;
  const { fg, bg, bd } = cellColors(gw.band);
  const opponents = cellOpponents(gw);
  const venue = cellVenue(gw);

  const cellStyle: React.CSSProperties = {
    backgroundColor: bg,
    border: `1.5px solid ${bd}`,
    boxShadow: runHex ? `0 0 0 2px ${hexRgba(runHex, 0.7)}` : undefined,
  };

  const title = blank
    ? 'Sin partido (jornada en blanco)'
    : `J${gw.gameweek} · ${opponents} ${venue} · FDR ${gw.band}${gw.is_dgw ? ' · doble jornada' : ''}`;

  const inner = (
    <>
      <span className="text-[11px] font-bold tracking-wide text-white/60 leading-none">
        J{gw.gameweek}
        {gw.is_dgw ? '··' : ''}
      </span>
      <span className="text-[17px] font-extrabold tracking-tight leading-none" style={{ color: fg }}>
        {opponents}
      </span>
      <span className="text-[11px] font-extrabold tracking-wide text-white/85 leading-none min-h-[11px]">
        {venue}
      </span>
      {showFdrNumbers && !blank && (
        <span
          className="absolute -top-[7px] -right-[7px] w-[18px] h-[18px] rounded-full flex items-center justify-center text-[11px] font-black"
          style={{ backgroundColor: fg, color: '#211F29' }}
        >
          {gw.band}
        </span>
      )}
    </>
  );

  const base =
    'relative flex flex-col items-center gap-[3px] min-w-[66px] px-2 pt-[9px] pb-2 rounded-lg';

  if (onAsk) {
    return (
      <button
        type="button"
        onClick={onAsk}
        title={title}
        className={`${base} transition-transform hover:-translate-y-0.5`}
        style={cellStyle}
      >
        {inner}
      </button>
    );
  }
  return (
    <div className={base} style={cellStyle} title={title}>
      {inner}
    </div>
  );
}

/**
 * Rich FDR / venue / streak legend bar, shown above the board (design parity).
 * The five band chips are labelled; L/V explains the venue marker; the two
 * swatches explain the run rings.
 */
export function BandLegend() {
  const bands = [1, 2, 3, 4, 5] as const;
  return (
    <div className="flex items-center gap-3.5 flex-wrap rounded-xl bg-white/[0.04] border border-white/10 px-4 py-3">
      <span className="text-[13px] font-extrabold tracking-wide text-bf-gray">FDR</span>
      {bands.map((b) => {
        const fg = bandColor(b);
        return (
          <span
            key={b}
            className="text-[13px] font-extrabold rounded-md px-2.5 py-1 border"
            style={{ backgroundColor: hexRgba(fg, 0.18), color: fg, borderColor: hexRgba(fg, 0.5) }}
          >
            {b} · {bandLabel(b)}
          </span>
        );
      })}

      <span className="w-px h-5 bg-white/20" />

      <span className="text-[13px] font-semibold text-bf-gray">
        <b className="text-white">L</b> Local&nbsp;·&nbsp;<b className="text-white">V</b> Visitante
      </span>

      <span className="w-px h-5 bg-white/20" />

      <span className="text-[13px] font-semibold text-bf-gray flex items-center gap-1.5">
        <span
          className="inline-block w-[26px] h-[14px] rounded-[5px] border-[1.5px]"
          style={{ borderColor: hexRgba(GOOD_HEX, 0.7) }}
        />
        Racha favorable&nbsp;·&nbsp;
        <span
          className="inline-block w-[26px] h-[14px] rounded-[5px] border-[1.5px]"
          style={{ borderColor: hexRgba(BAD_HEX, 0.7) }}
        />
        Racha dura (3+)
      </span>
    </div>
  );
}
