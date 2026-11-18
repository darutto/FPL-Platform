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
import { bandColor, venueLabel, hexRgba, gwLabel, type Band } from '@/lib/fixture-outlook-format';
import { teamOutlookQuestion, fixtureCellQuestion } from '@/lib/fixture-chat-links';
import type { Swing } from '@/lib/fixture-swing';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import { TeamHeader } from './FixtureTickerRow';
import { FixtureSwingPill, swingArrow, swingColor } from './FixtureSwingPill';

// Chart geometry (SVG user units == px; the chart scrolls, never stretches).
const X0 = 52;
const STEP = 74;
const Y_TOP = 22; // band 1
const Y_GAP = 20; // px between bands
const Y_BASE = 106; // area baseline, just below band 5 (y=102)
const CHART_H = 112;
const COL_W = 74; // x-axis label column width
const X_PAD = 15; // left spacer so first column centres on X0

/** Room on the right for a "swing at J16 →" pin when the swing lies beyond the visible window. */
const PIN_W = 64;

type Pt = {
  gw: number;
  band: number | null;
  /** One band per fixture: two for a double gameweek, none for a blank. */
  fixtureBands: number[];
  blank: boolean;
  opp: string;
  venue: string;
  cx: number;
  cy: number | null;
};

export function FixtureTendencyChart({
  team,
  onAsk,
  showHeader = true,
  rank,
  swing = null,
}: {
  team: TeamOutlook;
  onAsk?: (question: string) => void;
  /** i110: false when the composer already rendered TeamHeader for this team. */
  showHeader?: boolean;
  /** Place in the best-first order, passed by the /fixtures board only. */
  rank?: number;
  /** Where this team's run turns easier or harder; null/absent draws the chart as it always was. */
  swing?: Swing | null;
}) {
  const t = useT();
  const { locale } = useLocale();
  const series = team.series;
  const n = series.length;

  // Where the swing falls in THIS window: before it (-1), on a column, or already behind it (0 with an earlier gameweek).
  const firstNew = swing === null ? -1 : series.findIndex((s) => s.gameweek >= swing.gameweek);
  const beyond = swing !== null && firstNew === -1 && n > 0;
  const chartW = X0 + Math.max(0, n - 1) * STEP + 40 + (beyond ? PIN_W : 0);

  const points: Pt[] = series.map((s, i) => {
    const blank = s.band === null;
    return {
      gw: s.gameweek,
      band: s.band,
      blank,
      fixtureBands: s.fixtures.map((f) => f.band),
      opp: blank ? '—' : s.fixtures.map((f) => f.opponent_short).join('/'),
      venue: blank ? '' : s.fixtures.map((f) => venueLabel(f.is_home, locale)).join('/'),
      cx: X0 + i * STEP,
      cy: blank ? null : Y_TOP + ((s.band as number) - 1) * Y_GAP,
    };
  });

  const drawn = points.filter((p) => p.cy !== null);
  const linePoints = drawn.map((p) => `${p.cx},${p.cy}`).join(' ');
  const areaPoints =
    drawn.length >= 2 && !swing
      ? `${linePoints} ${drawn[drawn.length - 1].cx},${Y_BASE} ${drawn[0].cx},${Y_BASE}`
      : '';

  // With a swing, the run before it is grey and the run after it takes the direction's colour.
  const swingHex = swing ? swingColor(swing.direction) : null;
  const isNew = (i: number) => swing !== null && firstNew !== -1 && i >= firstNew;
  const preDrawn = swing ? drawn.filter((p) => !isNew(points.indexOf(p))) : [];
  const postDrawn = swing ? drawn.filter((p) => isNew(points.indexOf(p))) : [];
  const bridge = preDrawn.length && postDrawn.length ? [preDrawn[preDrawn.length - 1], ...postDrawn] : postDrawn;
  const dividerX = swing && firstNew > 0 ? (points[firstNew - 1].cx + points[firstNew].cx) / 2 : null;

  const avg = team.avg_band;
  const avgHex = avg === null ? '#ABA9AC' : bandColor(Math.max(1, Math.min(5, Math.round(avg))) as Band);

  const gridX1 = 34;
  const gridX2 = chartW - 24;
  const bands = [1, 2, 3, 4, 5] as const;

  return (
    <div className="space-y-3" data-testid="fixture-tendency-chart">
      {/* Header — parity with the detailed row (the same TeamHeader) */}
      {showHeader && (
        <TeamHeader
          team={team}
          rank={rank}
          badge={swing ? <FixtureSwingPill swing={swing} /> : undefined}
          onAskTeam={onAsk ? () => onAsk(teamOutlookQuestion(team.team_name, team.axis, locale)) : undefined}
        />
      )}

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

            {swing && firstNew !== 0 && (
              <rect
                x={gridX1}
                y={4}
                width={(dividerX ?? gridX2) - gridX1}
                height={Y_BASE - 4}
                fill="rgba(255,255,255,.04)"
                data-testid="fixture-swing-grey"
              />
            )}
            {areaPoints && <polygon points={areaPoints} fill={hexRgba(avgHex, 0.09)} />}
            {!swing && drawn.length >= 2 && (
              <polyline
                points={linePoints}
                fill="none"
                stroke={avgHex}
                strokeWidth={2.5}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )}
            {swing && preDrawn.length >= 2 && (
              <polyline
                points={preDrawn.map((p) => `${p.cx},${p.cy}`).join(' ')}
                fill="none"
                stroke="#ABA9AC"
                strokeOpacity={0.6}
                strokeWidth={2.2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )}
            {swing && bridge.length >= 2 && (
              <polyline
                points={bridge.map((p) => `${p.cx},${p.cy}`).join(' ')}
                fill="none"
                stroke={swingHex as string}
                strokeWidth={2.5}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )}
            {swing && dividerX !== null && (
              <g data-testid="fixture-swing-divider" aria-label={t('fx.swing.marker', { direction: t(swing.direction === 'easier' ? 'fx.swing.easier' : 'fx.swing.harder', { gw: gwLabel(swing.gameweek, locale) }), gw: gwLabel(swing.gameweek, locale) })}>
                <line x1={dividerX} x2={dividerX} y1={12} y2={Y_BASE} stroke={swingHex as string} strokeWidth={2} strokeDasharray="4 3" />
                <text x={dividerX} y={9} textAnchor="middle" style={{ fontSize: 10.5, fontWeight: 800, fill: swingHex as string }}>
                  {swingArrow(swing.direction)} {gwLabel(swing.gameweek, locale)}
                </text>
              </g>
            )}
            {swing && firstNew === 0 && (
              <text x={gridX1 + 4} y={9} data-testid="fixture-swing-since" style={{ fontSize: 10.5, fontWeight: 800, fill: swingHex as string }}>
                {swingArrow(swing.direction)}{' '}
                {t(swing.gameweek < points[0].gw ? 'fx.swing.since' : 'fx.swing.from', { gw: gwLabel(swing.gameweek, locale) })}
              </text>
            )}
            {swing && beyond && (
              <text
                x={points[n - 1].cx + 30}
                y={Y_TOP + 2 * Y_GAP + 4}
                data-testid="fixture-swing-pin"
                style={{ fontSize: 11.5, fontWeight: 800, fill: swingHex as string }}
              >
                {swingArrow(swing.direction)} {gwLabel(swing.gameweek, locale)} →
              </text>
            )}
            {points.map((p, i) => {
              if (p.blank) {
                // A blank gameweek has no difficulty: a hollow marker, never a coloured dot.
                return (
                  <circle
                    key={p.gw}
                    data-testid="fixture-blank-marker"
                    cx={p.cx}
                    cy={Y_TOP + 2 * Y_GAP}
                    r={5.5}
                    fill="none"
                    stroke="#ABA9AC"
                    strokeWidth={1.8}
                    strokeDasharray="3 2"
                  />
                );
              }
              const dim = swing !== null && !isNew(i) ? 0.5 : 1;
              const bands = p.fixtureBands.length ? p.fixtureBands : [p.band as number];
              const double = bands.length > 1;
              const tied = double && bands[0] === bands[1];
              return (
                <g key={p.gw} opacity={dim} data-testid={double ? 'fixture-double-marker' : undefined}>
                  {double && !tied && (
                    <line
                      x1={p.cx}
                      x2={p.cx}
                      y1={Y_TOP + (Math.min(...bands) - 1) * Y_GAP}
                      y2={Y_TOP + (Math.max(...bands) - 1) * Y_GAP}
                      stroke="#ABA9AC"
                      strokeWidth={2.4}
                    />
                  )}
                  {bands.map((b, j) => (
                    <circle
                      key={j}
                      cx={tied ? p.cx + (j === 0 ? -4 : 4) : p.cx}
                      cy={Y_TOP + (b - 1) * Y_GAP}
                      r={5.5}
                      fill={bandColor(b as Band)}
                      stroke="#1A1922"
                      strokeWidth={2}
                    />
                  ))}
                </g>
              );
            })}
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
                            locale,
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
  const t = useT();
  const { locale } = useLocale();
  const fg = point.blank ? '#ABA9AC' : bandColor(point.band as Band);
  const inner = (
    <>
      <span className="text-[13px] font-extrabold" style={{ color: fg }}>
        {point.opp}
      </span>
      <span className="text-[10.5px] font-bold text-bf-gray whitespace-nowrap">
        {gwLabel(point.gw, locale)}
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
        title={t('fx.cell.askOpp', { opp: point.opp })}
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
