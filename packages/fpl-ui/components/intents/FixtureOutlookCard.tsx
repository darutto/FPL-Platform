/**
 * FixtureOutlookCard — structured rendering for fixture_outlook OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome         === 'ok'
 *   response.intent          === 'fixture_outlook'
 *   response.fixture_outlook !== null  (teams.length > 0)
 *
 * Track D / FI4. Two-axis fixture ticker with run detection. Foregrounds the
 * Spanish verdict (chat-first), with a per-GW colour strip and good/bad run
 * pills as visual support. The axis (attack / clean-sheet) is whatever the
 * backend resolved for the turn; the interactive toggle lives on the
 * standalone Fixtures page (FI7), not in a chat answer.
 *
 * Band colour scale (1=easiest … 5=hardest) mirrors the FDR ramp.
 */
import type {
  FixtureOutlookMeta,
  TeamOutlook,
  FixtureOutlookGW,
  FixtureOutlookRun,
} from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { bandColor, axisLabel } from '@/lib/fixture-outlook-format';
import { FingerprintWaves } from './CardOrnaments';

interface Props {
  data: FixtureOutlookMeta;
}

export default function FixtureOutlookCard({ data }: Props) {
  const { axis, teams } = data;
  if (teams.length === 0) return null;

  return (
    <div className={`mt-3 ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      {/* Analytical card → fingerprint waves (design-system semantics). */}
      <FingerprintWaves color={ACCENT_HEX.turquoise} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2 text-sm">
          <span className="font-extrabold text-white">Calendario</span>
          <span className="text-bf-gray/60">·</span>
          <span
            className="text-[10px] font-bold uppercase tracking-wider rounded px-1.5 py-0.5"
            style={{ backgroundColor: `${ACCENT_HEX.turquoise}22`, color: ACCENT_HEX.turquoise }}
          >
            {axisLabel(axis)}
          </span>
        </div>

        {/* Team rows */}
        <div className="space-y-3">
          {teams.map((t) => (
            <TeamRow key={t.team_short} team={t} />
          ))}
        </div>

        {/* Legend */}
        <BandLegend />
      </div>
    </div>
  );
}

function TeamRow({ team }: { team: TeamOutlook }) {
  const { team_short, verdict, series, runs } = team;

  // Map each GW to the run it belongs to (runs are contiguous, non-overlapping).
  const runByGw = new Map<number, FixtureOutlookRun>();
  for (const r of runs) {
    for (let g = r.start_gw; g <= r.end_gw; g++) runByGw.set(g, r);
  }
  // Slice the series into consecutive segments that share the same run (or none),
  // so a detected run renders as ONE grouped block rather than loose cells.
  type Segment = { run: FixtureOutlookRun | null; cells: FixtureOutlookGW[] };
  const segments: Segment[] = [];
  for (const gw of series) {
    const run = runByGw.get(gw.gameweek) ?? null;
    const last = segments[segments.length - 1];
    if (last && last.run === run) last.cells.push(gw);
    else segments.push({ run, cells: [gw] });
  }

  return (
    <div className="space-y-1.5">
      {/* Verdict line — the narrative leads. */}
      <div className="flex items-baseline gap-2">
        <span className="text-xs font-bold tracking-wide text-white">{team_short}</span>
        {verdict && <span className="text-[11px] leading-snug text-bf-gray">{verdict}</span>}
      </div>

      {/* GW strip: good/bad runs are grouped with a tinted ring (scrolls on
          narrow screens). The grouping IS the tendency callout. */}
      <div className="flex items-stretch gap-1 overflow-x-auto px-0.5 py-1">
        {segments.map((seg, i) =>
          seg.run ? (
            <RunGroup key={`run-${i}`} run={seg.run} cells={seg.cells} />
          ) : (
            seg.cells.map((gw) => <GwCell key={gw.gameweek} gw={gw} />)
          ),
        )}
      </div>
    </div>
  );
}

function GwCell({ gw }: { gw: FixtureOutlookGW }) {
  const blank = gw.band === null;
  const color = blank ? '#6b7280' : bandColor(gw.band as 1 | 2 | 3 | 4 | 5);
  // DGW: show both opponents compactly; blank: an em dash.
  const label = blank
    ? '—'
    : gw.fixtures.map((f) => `${f.opponent_short}${f.is_home ? '' : "'"}`).join('/');

  return (
    <div className="flex flex-col items-stretch rounded-md overflow-hidden min-w-[44px] bg-white/[0.04] border border-white/10">
      <span className="px-1 py-0.5 text-center text-[8px] font-bold uppercase tracking-wider text-bf-gray bg-white/[0.04] border-b border-white/5">
        J{gw.gameweek}
        {gw.is_dgw ? '··' : ''}
      </span>
      <span
        className="px-1 py-1 text-center text-[10px] font-extrabold tracking-tight"
        style={{ backgroundColor: `${color}33`, color }}
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
function RunGroup({ run, cells }: { run: FixtureOutlookRun; cells: FixtureOutlookGW[] }) {
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
      {/* Strong runs get a ★ (NextXI's marker); mild runs rely on the ring. */}
      {strong && (
        <span className={`shrink-0 text-[11px] leading-none ${starClass}`} aria-hidden>★</span>
      )}
      {cells.map((gw) => (
        <GwCell key={gw.gameweek} gw={gw} />
      ))}
    </div>
  );
}

function BandLegend() {
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

