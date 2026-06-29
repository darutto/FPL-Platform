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
import { TriangleField } from './CardOrnaments';

interface Props {
  data: FixtureOutlookMeta;
}

export default function FixtureOutlookCard({ data }: Props) {
  const { axis, teams } = data;
  if (teams.length === 0) return null;

  return (
    <div className={`mt-3 ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      <TriangleField color={ACCENT_HEX.turquoise} corner="br" />
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
  return (
    <div className="space-y-1.5">
      {/* Verdict line — the narrative leads. */}
      <div className="flex items-baseline gap-2">
        <span className="text-xs font-bold tracking-wide text-white">{team_short}</span>
        {verdict && <span className="text-[11px] leading-snug text-bf-gray">{verdict}</span>}
      </div>

      {/* GW colour strip (scrolls horizontally on narrow screens). */}
      <div className="flex gap-1 overflow-x-auto pb-0.5">
        {series.map((gw) => (
          <GwCell key={gw.gameweek} gw={gw} />
        ))}
      </div>

      {/* Run pills — the good/bad tendency callouts. */}
      {runs.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {runs.map((r) => (
            <RunPill key={`${r.type}-${r.start_gw}`} run={r} />
          ))}
        </div>
      )}
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

function RunPill({ run }: { run: FixtureOutlookRun }) {
  const good = run.type === 'good';
  const color = good ? '#2ecc71' : '#e74c3c';
  const dot = run.intensity === 'strong' ? '●' : '○';
  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] font-bold rounded px-1.5 py-0.5"
      style={{ backgroundColor: `${color}1f`, color }}
    >
      <span aria-hidden>{dot}</span>
      J{run.start_gw}–J{run.end_gw}
    </span>
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

