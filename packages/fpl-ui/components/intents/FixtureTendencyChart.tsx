'use client';

/**
 * FixtureTendencyChart — per-team trend line (Track D / FI5).
 *
 * A compact sparkline (no axis labels) rendered inline; tapping the chart
 * itself (or the "Tendencia" label) expands it to a full chart with GW
 * labels. Tapping a point opens a small popover with the fixture's
 * opponent/venue and a qualitative difficulty label — deliberately NOT a
 * fabricated probability number (real Poisson modelling is FI6, gated on
 * Track A's historical backtesting). "Reversed axis, good=up": the line
 * rises during good runs and dips during bad ones (see lib/fixture-tendency).
 *
 * The svg itself carries the expand/collapse tap target (not just the small
 * label above it) so the chart graphic — the thing a user naturally taps —
 * does something, rather than falling through to a sibling "ask about this
 * team" button.
 */
import { useState } from 'react';
import type { TeamOutlook, FixtureOutlookGW, FixtureOutlookRun } from '@/lib/types';
import { bandColor } from '@/lib/fixture-outlook-format';
import { buildTendencyPoints, qualitativeBandLabel, type TendencyPoint } from '@/lib/fixture-tendency';
import { fixtureCellQuestion } from '@/lib/fixture-chat-links';

const COMPACT_H = 32;
const FULL_H = 72;

export function FixtureTendencyChart({
  team,
  onAsk,
}: {
  team: TeamOutlook;
  onAsk?: (question: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [activeGw, setActiveGw] = useState<number | null>(null);

  const height = expanded ? FULL_H : COMPACT_H;
  const width = 100; // viewBox units; SVG scales to container via preserveAspectRatio=none
  const points = buildTendencyPoints(team.series, width, height);

  const runByGw = new Map<number, FixtureOutlookRun>();
  for (const r of team.runs) {
    for (let g = r.start_gw; g <= r.end_gw; g++) runByGw.set(g, r);
  }

  // Split the polyline into segments so each run gets its own tinted stroke.
  type Segment = { run: FixtureOutlookRun | null; pts: TendencyPoint[] };
  const segments: Segment[] = [];
  points.forEach((p) => {
    const run = runByGw.get(p.gw) ?? null;
    const last = segments[segments.length - 1];
    if (last && last.run === run) {
      last.pts.push(p);
    } else {
      // Carry the previous point over so segments connect (no visual gaps).
      segments.push({ run, pts: last ? [last.pts[last.pts.length - 1], p] : [p] });
    }
  });

  const strokeFor = (run: FixtureOutlookRun | null) => {
    if (!run) return 'rgba(255,255,255,0.25)';
    return run.type === 'good' ? '#02EBAE' : '#FF6A4D';
  };
  const strokeWidthFor = (run: FixtureOutlookRun | null) =>
    run?.intensity === 'strong' ? 2.4 : run ? 1.8 : 1.2;

  const active = activeGw != null ? team.series.find((s) => s.gameweek === activeGw) : null;

  const toggle = () => {
    setExpanded((v) => !v);
    setActiveGw(null);
  };

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-bf-gray/60 hover:text-bf-gray transition-colors"
      >
        Tendencia
        <span className="text-[8px]">{expanded ? '▴' : '▾'}</span>
      </button>

      <div className="relative">
        {/* Chart area: sized exactly to the svg so the dot overlay's
            percentage positions (below) line up with it — not with the
            taller wrapper that also holds the GW-label row and popover. */}
        <div className="relative" style={{ height }}>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="none"
            className="w-full h-full cursor-pointer"
            role="button"
            aria-label={`${expanded ? 'Contraer' : 'Expandir'} tendencia de calendario de ${team.team_name}`}
            onClick={toggle}
          >
            {segments.map((seg, i) => (
              <polyline
                key={i}
                points={seg.pts.map((p) => `${p.x},${p.y}`).join(' ')}
                fill="none"
                stroke={strokeFor(seg.run)}
                strokeWidth={strokeWidthFor(seg.run)}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}
          </svg>

          {/* Dots as an HTML overlay, not SVG circles: the chart's viewBox is
              deliberately stretched (preserveAspectRatio="none") to fill any
              container width, which would flatten true circles into ellipses.
              Plain rounded-full divs, positioned by percentage, stay round. */}
          {expanded &&
            points.map((p) => {
              const isActive = activeGw === p.gw;
              return (
                <button
                  key={p.gw}
                  type="button"
                  aria-label={`J${p.gw}`}
                  onClick={(e) => {
                    // Stop the point tap from also bubbling to the svg's
                    // expand/collapse toggle beneath it.
                    e.stopPropagation();
                    setActiveGw((g) => (g === p.gw ? null : p.gw));
                  }}
                  className={`absolute rounded-full transition-all ${
                    p.blank ? 'border border-white/40 bg-transparent' : ''
                  } ${isActive ? 'ring-2 ring-white/50' : ''}`}
                  style={{
                    left: `${(p.x / width) * 100}%`,
                    top: `${(p.y / height) * 100}%`,
                    width: isActive ? 8 : 5,
                    height: isActive ? 8 : 5,
                    transform: 'translate(-50%, -50%)',
                    backgroundColor: p.blank ? undefined : bandColor(p.band as 1 | 2 | 3 | 4 | 5),
                  }}
                />
              );
            })}
        </div>

        {expanded && (
          <div className="flex justify-between px-0.5 mt-0.5">
            {team.series.map((s) => (
              <span
                key={s.gameweek}
                className={`text-[8px] font-bold ${activeGw === s.gameweek ? 'text-white' : 'text-bf-gray/50'}`}
              >
                J{s.gameweek}
              </span>
            ))}
          </div>
        )}

        {active && (
          <FixturePopover
            gw={active}
            team={team}
            run={runByGw.get(active.gameweek) ?? null}
            onAsk={onAsk}
            onClose={() => setActiveGw(null)}
          />
        )}
      </div>
    </div>
  );
}

/** "Racha buena en curso: 3 jornadas (J3–J5)." — schedule-only, no advice. */
function runMembershipLine(run: FixtureOutlookRun): string {
  const kind = run.type === 'good' ? 'buena' : 'mala';
  return `Racha ${kind} en curso: ${run.length} jornadas (J${run.start_gw}–J${run.end_gw}).`;
}

function FixturePopover({
  gw,
  team,
  run,
  onAsk,
  onClose,
}: {
  gw: FixtureOutlookGW;
  team: TeamOutlook;
  /** The detected run this GW belongs to, if any (real data — no invented streaks). */
  run: FixtureOutlookRun | null;
  onAsk?: (question: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="mt-1.5 rounded-md border border-white/10 bg-black/60 px-2.5 py-2 text-[11px] leading-snug space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="font-bold text-white">
          J{gw.gameweek}
          {gw.is_dgw ? ' · doble jornada' : ''}
        </span>
        <button type="button" onClick={onClose} className="text-bf-gray/60 hover:text-white text-xs leading-none">
          ✕
        </button>
      </div>

      {gw.fixtures.length === 0 ? (
        <p className="text-bf-gray">Sin partido esta jornada.</p>
      ) : (
        gw.fixtures.map((f, i) => (
          <div key={i}>
            <p className="text-bf-gray">
              <span className="font-medium text-white">
                {team.team_short} vs {f.opponent_short}
              </span>{' '}
              — {f.is_home ? 'en casa' : 'fuera'}
            </p>
            <p className="text-bf-gray">{qualitativeBandLabel(f.band, team.axis)}</p>
          </div>
        ))
      )}

      {run && <p className="text-bf-gray/80 italic">{runMembershipLine(run)}</p>}

      {onAsk && (
        <button
          type="button"
          onClick={() => onAsk(fixtureCellQuestion(team.team_name, gw, team.axis))}
          className="text-[10px] font-bold text-bf-turquoise hover:text-bf-turquoise/80 transition-colors"
        >
          Preguntar en el chat →
        </button>
      )}
    </div>
  );
}
