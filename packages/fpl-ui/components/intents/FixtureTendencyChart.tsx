'use client';

/**
 * FixtureTendencyChart — per-team trend line (Track D / FI5).
 *
 * "Calendario FDR" design: a full, fixed-scale chart (not a stretched
 * sparkline). Five band gridlines (1 easiest … 5 hardest) with coloured axis
 * labels, an area fill + polyline in the team's average-band colour, a dot per
 * gameweek coloured by that GW's difficulty, and an opponent / J{gw}·venue
 * label row beneath. The whole card carries the same header as the detailed
 * row (code + "Prom X.X" pill + verdict). The chart scrolls horizontally on
 * narrow screens rather than distorting.
 *
 * Deep-links preserved: the team code and each GW label column hand a
 * ready-made question to chat via `onAsk` (the /fixtures board wires it).
 */
import type { TeamOutlook, FixtureOutlookGW } from '@/lib/types';
import { bandColor, venueLabel, hexRgba, type Band } from '@/lib/fixture-outlook-format';
import { teamOutlookQuestion, fixtureCellQuestion } from '@/lib/fixture-chat-links';
import { AvgPill } from './FixtureTickerRow';

// Chart geometry (SVG user units == px; the chart scrolls, never stretches).
const X0 = 52;
const STEP = 74;
const Y_TOP = 22; // band 1
const Y_GAP = 20; // px between bands
const Y_BASE = 106; // area baseline, just below band 5 (y=102)
const CHART_H = 112;
const COL_W = 74; // x-axis label column width
const X_PAD = 15; // left spacer so first column centres on X0

type Pt = {
  gw: number;
  band: number | null;
  blank: boolean;
  opp: string;
  venue: string;
  cx: number;
  cy: number | null;
};

export function FixtureTendencyChart({
  team,
  onAsk,
}: {
  team: TeamOutlook;
  onAsk?: (question: string) => void;
}) {
  const series = team.series;
  const n = series.length;
  const chartW = X0 + Math.max(0, n - 1) * STEP + 40;

  const points: Pt[] = series.map((s, i) => {
    const blank = s.band === null;
    return {
      gw: s.gameweek,
      band: s.band,
      blank,
      opp: blank ? '—' : s.fixtures.map((f) => f.opponent_short).join('/'),
      venue: blank ? '' : s.fixtures.map((f) => venueLabel(f.is_home)).join('/'),
      cx: X0 + i * STEP,
      cy: blank ? null : Y_TOP + ((s.band as number) - 1) * Y_GAP,
    };
  });

  const drawn = points.filter((p) => p.cy !== null);
  const linePoints = drawn.map((p) => `${p.cx},${p.cy}`).join(' ');
  const areaPoints =
    drawn.length >= 2
      ? `${linePoints} ${drawn[drawn.length - 1].cx},${Y_BASE} ${drawn[0].cx},${Y_BASE}`
      : '';

  const avg = team.avg_band;
  const avgHex = avg === null ? '#ABA9AC' : bandColor(Math.max(1, Math.min(5, Math.round(avg))) as Band);

  const gridX1 = 34;
  const gridX2 = chartW - 24;
  const bands = [1, 2, 3, 4, 5] as const;

  return (
    <div className="space-y-3">
      {/* Header — parity with the detailed row */}
      <div className="flex items-center gap-3.5 flex-wrap">
        {onAsk ? (
          <button
            type="button"
            onClick={() => onAsk(teamOutlookQuestion(team.team_name, team.axis))}
            className="text-[22px] font-black tracking-tight leading-none text-white hover:text-bf-turquoise transition-colors min-w-[58px] text-left"
          >
            {team.team_short}
          </button>
        ) : (
          <span className="text-[22px] font-black tracking-tight leading-none text-white min-w-[58px]">
            {team.team_short}
          </span>
        )}
        <AvgPill avg={avg} />
        {team.verdict && <span className="text-[14.5px] text-bf-gray">{team.verdict}</span>}
      </div>

      <div className="overflow-x-auto">
        <div style={{ width: chartW }}>
          <svg width={chartW} height={CHART_H} className="overflow-visible block">
            {bands.map((b) => {
              const y = Y_TOP + (b - 1) * Y_GAP;
              return (
                <g key={b}>
                  <line x1={gridX1} y1={y} x2={gridX2} y2={y} stroke="rgba(255,255,255,.07)" />
                  <text
                    x={24}
                    y={y + 4}
                    textAnchor="end"
                    style={{ fontSize: 11, fontWeight: 700, fill: bandColor(b) }}
                  >
                    {b}
                  </text>
                </g>
              );
            })}

            {areaPoints && <polygon points={areaPoints} fill={hexRgba(avgHex, 0.09)} />}
            {drawn.length >= 2 && (
              <polyline
                points={linePoints}
                fill="none"
                stroke={avgHex}
                strokeWidth={2.5}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )}
            {drawn.map((p) => (
              <circle
                key={p.gw}
                cx={p.cx}
                cy={p.cy as number}
                r={5.5}
                fill={bandColor(p.band as Band)}
                stroke="#1A1922"
                strokeWidth={2}
              />
            ))}
          </svg>

          {/* X-axis: opponent + J{gw}·venue, one column per GW. */}
          <div className="flex mt-1">
            <div className="flex-none" style={{ width: X_PAD }} />
            {points.map((p) => (
              <GwLabel
                key={p.gw}
                point={p}
                onAsk={
                  onAsk && !p.blank
                    ? () =>
                        onAsk(
                          fixtureCellQuestion(
                            team.team_name,
                            series.find((s) => s.gameweek === p.gw) as FixtureOutlookGW,
                            team.axis,
                          ),
                        )
                    : undefined
                }
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function GwLabel({ point, onAsk }: { point: Pt; onAsk?: () => void }) {
  const fg = point.blank ? '#ABA9AC' : bandColor(point.band as Band);
  const inner = (
    <>
      <span className="text-[13px] font-extrabold" style={{ color: fg }}>
        {point.opp}
      </span>
      <span className="text-[10.5px] font-bold text-bf-gray whitespace-nowrap">
        J{point.gw}
        {point.venue ? ` · ${point.venue}` : ''}
      </span>
    </>
  );
  const cls = 'flex-none flex flex-col items-center gap-0.5';
  if (onAsk) {
    return (
      <button
        type="button"
        onClick={onAsk}
        title={`${point.opp} · preguntar en el chat`}
        className={`${cls} transition-transform hover:-translate-y-0.5`}
        style={{ width: COL_W }}
      >
        {inner}
      </button>
    );
  }
  return (
    <div className={cls} style={{ width: COL_W }}>
      {inner}
    </div>
  );
}
