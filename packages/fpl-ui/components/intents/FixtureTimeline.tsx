/**
 * One team's season as a single timeline (iteration-2 design "A").
 *
 * Premier League matches sit on one line in date order. A match of another
 * competition is a smaller, outlined tile of its own, dropped half a tile
 * below the line and placed in its real date position between them. The rest
 * between each consecutive pair is a short number in the gap over a thin
 * dashed line; the same number in gold over a solid line is the rotation notice
 * (<= 3 whole days after a European or cup match). No sentence ever sits in a
 * cell: the full phrase opens in the detail line when a tile or a gold number is
 * tapped or focused, so nothing depends on hover.
 *
 * Typography: regular weight everywhere except the rival. Secondary text uses
 * the app's grey tokens, never pure white.
 *
 * Free/Tribuna never reach this file: the server tells them only that the layer is
 * locked, and the board shows them the locked "Otras competiciones" switch instead.
 */
import { useId, useState, type CSSProperties } from 'react';
import type { FixtureOutlookGW, FixtureOutlookRun, FixtureOutlookMeta } from '@/lib/types';
import {
  bandColor,
  venueLabel,
  hexRgba,
  BLANK_COLOR,
  type Band,
} from '@/lib/fixture-outlook-format';
import {
  buildTimeline,
  competitionColor,
  type GapInfo,
  type TeamExtras,
  type TimelineItem,
} from '@/lib/fixture-competitions';

const GOOD_HEX = '#02EBAE';
const BAD_HEX = '#FF6A4D';

function runRing(run: FixtureOutlookRun | undefined): string | null {
  if (!run) return null;
  return run.type === 'good' ? GOOD_HEX : BAD_HEX;
}

function runsByGameweek(runs: FixtureOutlookRun[]): Map<number, FixtureOutlookRun> {
  const result = new Map<number, FixtureOutlookRun>();
  for (const run of runs) {
    for (let gameweek = run.start_gw; gameweek <= run.end_gw; gameweek++) result.set(gameweek, run);
  }
  return result;
}

/** Sizes of one rendering. `u` is a CSS length: the tile height of the Premier League line. */
interface Metrics {
  plW: string;
  plH: string;
  exW: string;
  exH: string;
  exTop: string;
  gapW: string;
  lineTop: string;
  gwFont: string;
  oppFont: string;
  haFont: string;
  siglaFont: string;
  codeFont: string;
  exHaFont: string;
  numFont: string;
  radius: string;
  exRadius: string;
  spacer: string;
}

const DETAILED: Metrics = {
  plW: '64px',
  plH: '64px',
  exW: '50px',
  exH: '44px',
  exTop: '26px',
  gapW: '28px',
  lineTop: '32px',
  gwFont: '10px',
  oppFont: '20px',
  haFont: '11px',
  siglaFont: '9px',
  codeFont: '16px',
  exHaFont: '9.5px',
  numFont: '11px',
  radius: '12px',
  exRadius: '10px',
  spacer: '10px',
};

/** Same proportions, scaled by `--r` (the presentation row height). */
const r = (k: number) => `calc(var(--r) * ${k})`;
const PRESENTATION: Metrics = {
  plW: r(1.5),
  plH: r(0.74),
  exW: r(1.15),
  exH: r(0.6),
  exTop: r(0.3),
  gapW: r(0.62),
  lineTop: r(0.37),
  gwFont: r(0.2),
  oppFont: r(0.4),
  haFont: r(0.2),
  siglaFont: r(0.19),
  codeFont: r(0.34),
  exHaFont: r(0.2),
  numFont: r(0.24),
  radius: r(0.16),
  exRadius: r(0.14),
  spacer: r(0.2),
};

function PlTile({
  gw,
  ring,
  m,
  onAsk,
  presentation,
}: {
  gw: FixtureOutlookGW;
  ring: string | null;
  m: Metrics;
  onAsk?: () => void;
  presentation: boolean;
}) {
  const blank = gw.band === null;
  const fg = blank ? BLANK_COLOR : bandColor(gw.band as Band);
  const opponents = blank ? '—' : gw.fixtures.map((f) => f.opponent_short).join('/');
  const venue = blank ? '' : gw.fixtures.map((f) => venueLabel(f.is_home)).join('/');
  const style: CSSProperties = {
    minWidth: m.plW,
    height: m.plH,
    borderRadius: m.radius,
    backgroundColor: hexRgba(fg, 0.2),
    border: `1.5px solid ${hexRgba(fg, 0.55)}`,
    boxShadow: ring ? `0 0 0 2px ${hexRgba(ring, 0.7)}` : undefined,
  };
  const label = blank
    ? 'Sin partido (jornada en blanco)'
    : `J${gw.gameweek} · ${opponents} ${venue} · FDR ${gw.band}${gw.is_dgw ? ' · doble jornada' : ''}`;
  // Presentation sets the rival and venue on one line: the tile is too short for three.
  const inner = presentation ? (
    <>
      <span className="leading-none text-bf-gray font-normal" style={{ fontSize: m.gwFont }}>J{gw.gameweek}</span>
      <span className="flex items-baseline gap-[0.25em] leading-none">
        <span className="font-bold tracking-tight" style={{ fontSize: m.oppFont, color: fg }}>{opponents}</span>
        <span className="font-normal text-bf-gray" style={{ fontSize: m.haFont }}>{venue}</span>
      </span>
    </>
  ) : (
    <>
      <span className="leading-none text-bf-gray font-normal" style={{ fontSize: m.gwFont }}>J{gw.gameweek}</span>
      <span className="font-bold leading-none tracking-tight" style={{ fontSize: m.oppFont, color: fg }}>{opponents}</span>
      <span className="leading-none font-normal text-bf-gray min-h-[11px]" style={{ fontSize: m.haFont }}>{venue}</span>
    </>
  );
  const base = `flex flex-none flex-col items-center justify-center ${presentation ? 'gap-[0.12em]' : 'gap-[3px]'} px-1`;
  if (onAsk) {
    return (
      <button type="button" onClick={onAsk} title={label} className={`${base} transition-transform hover:-translate-y-0.5`} style={style}>
        {inner}
      </button>
    );
  }
  return (
    <div className={base} style={style} title={label}>
      {inner}
    </div>
  );
}

function ExtraTile({
  item,
  m,
  presentation,
  selected,
  onPick,
}: {
  item: Extract<TimelineItem, { kind: 'extra' }>;
  m: Metrics;
  presentation: boolean;
  selected: boolean;
  onPick?: () => void;
}) {
  const color = competitionColor(item.match.competition);
  const style: CSSProperties = {
    width: m.exW,
    height: m.exH,
    marginTop: m.exTop,
    borderRadius: m.exRadius,
    border: `1.5px solid ${color}`,
    backgroundColor: selected ? hexRgba(color, 0.12) : 'transparent',
  };
  const code = item.match.opponentCode;
  const ha = venueLabel(item.match.venue === 'H');
  const inner = (
    <>
      <span className="font-normal uppercase leading-none tracking-[0.1em]" style={{ fontSize: m.siglaFont, color }}>
        {item.match.competition === 'UEFA-SC' ? 'SC' : item.match.competition}
      </span>
      {presentation ? (
        <span className="flex items-baseline gap-[0.2em] leading-none">
          <span className="font-bold text-bf-text" style={{ fontSize: m.codeFont }}>{code}</span>
          <span className="font-normal text-bf-gray" style={{ fontSize: m.exHaFont }}>{ha}</span>
        </span>
      ) : (
        <>
          <span className="mt-[3px] font-bold leading-none text-bf-text" style={{ fontSize: m.codeFont }}>{code}</span>
          <span className="mt-[2px] font-normal leading-none text-bf-gray" style={{ fontSize: m.exHaFont }}>{ha}</span>
        </>
      )}
    </>
  );
  const base = 'flex flex-none flex-col items-center justify-center leading-none';
  if (!onPick) {
    return (
      <div className={base} style={style} role="img" aria-label={item.sentence}>
        {inner}
      </div>
    );
  }
  return (
    <button
      type="button"
      data-testid="competition-tile"
      aria-label={item.sentence}
      aria-pressed={selected}
      onClick={onPick}
      onFocus={onPick}
      className={`${base} focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bf-turquoise`}
      style={style}
    >
      {inner}
    </button>
  );
}

/** The rest between two matches: a number over a thin line. Gold and solid when it is the rotation notice. */
function Gap({
  gap,
  m,
  selected,
  onPick,
}: {
  gap: GapInfo;
  m: Metrics;
  selected: boolean;
  onPick?: () => void;
}) {
  const colour = gap.rotation ? 'text-bf-gold' : 'text-bf-gray/60';
  const line = gap.rotation ? 'border-solid border-bf-gold/55' : 'border-dashed border-white/15';
  const number = (
    <span
      data-testid={gap.rotation ? 'rotation-notice' : 'rest-days'}
      className={`absolute left-0 right-0 text-center font-normal tabular-nums leading-none ${colour}`}
      style={{ top: `calc(${m.lineTop} - 1.5em)`, fontSize: m.numFont }}
    >
      <span aria-hidden="true">{gap.days}d</span>
      <span className="sr-only">{gap.sentence}</span>
    </span>
  );
  const frame: CSSProperties = { width: m.gapW, height: m.plH };
  const rule = <span aria-hidden="true" className={`absolute left-[3px] right-[3px] border-t ${line}`} style={{ top: m.lineTop }} />;
  if (gap.rotation && onPick) {
    return (
      <button
        type="button"
        data-testid="rotation-gap"
        aria-label={gap.cell ?? gap.sentence}
        aria-pressed={selected}
        onClick={onPick}
        onFocus={onPick}
        className="relative flex-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-bf-turquoise"
        style={frame}
      >
        {rule}
        {number}
      </button>
    );
  }
  return (
    <div className="relative flex-none" style={frame}>
      {rule}
      {number}
    </div>
  );
}

function Items({
  items,
  runByGw,
  m,
  presentation,
  detail,
  onDetail,
  onAskCell,
}: {
  items: TimelineItem[];
  runByGw: Map<number, FixtureOutlookRun>;
  m: Metrics;
  presentation: boolean;
  detail?: string | null;
  onDetail?: (key: string | null) => void;
  onAskCell?: (gw: FixtureOutlookGW) => void;
}) {
  return (
    <>
      {items.map((item, i) => {
        const gap = item.gap;
        return (
          <div key={item.key} className="flex flex-none items-start">
            {gap ? (
              <Gap gap={gap} m={m} selected={detail === `gap-${item.key}`} onPick={onDetail ? () => onDetail(`gap-${item.key}`) : undefined} />
            ) : i > 0 ? (
              <span aria-hidden="true" className="flex-none" style={{ width: m.spacer }} />
            ) : null}
            {item.kind === 'pl' ? (
              <PlTile
                gw={item.gw}
                ring={runRing(runByGw.get(item.gw.gameweek))}
                m={m}
                presentation={presentation}
                onAsk={onAskCell ? () => onAskCell(item.gw) : undefined}
              />
            ) : (
              <ExtraTile
                item={item}
                m={m}
                presentation={presentation}
                selected={detail === item.key}
                onPick={onDetail ? () => onDetail(item.key) : undefined}
              />
            )}
          </div>
        );
      })}
    </>
  );
}

/** The phrase a picked tile or gold number opens. */
function detailSentence(items: TimelineItem[], key: string | null): string | null {
  if (!key) return null;
  for (const item of items) {
    if (item.kind === 'extra' && item.key === key) return item.sentence;
    if (key === `gap-${item.key}` && item.gap) return item.gap.sentence;
  }
  return null;
}

/** "Detallado": the timeline of one team, scrolling inside its own container. */
export function TimelineLane({
  team,
  extras,
  onAskCell,
}: {
  team: FixtureOutlookMeta['teams'][number];
  extras: TeamExtras;
  onAskCell?: (gw: FixtureOutlookGW) => void;
}) {
  const [detail, setDetail] = useState<string | null>(null);
  const detailId = useId();
  const items = buildTimeline(team.series, extras);
  const runByGw = runsByGameweek(team.runs);
  const sentence = detailSentence(items, detail);
  return (
    <div
      data-testid="fixture-timeline"
      onKeyDown={(e) => {
        if (e.key === 'Escape') setDetail(null);
      }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDetail(null);
      }}
    >
      <div className="overflow-x-auto pb-2">
        <div className="flex min-w-max items-start">
          <Items
            items={items}
            runByGw={runByGw}
            m={DETAILED}
            presentation={false}
            detail={detail}
            onDetail={setDetail}
            onAskCell={onAskCell}
          />
        </div>
      </div>
      <p
        id={detailId}
        role="status"
        data-testid="competition-detail"
        className="min-h-0 pt-1 text-[12.5px] font-normal text-bf-gray empty:hidden"
      >
        {sentence}
      </p>
    </div>
  );
}

/** "Presentar": every club's timeline, sized from the viewport so the 20 rows fit without scrolling. */
export function PresentationTimeline({
  data,
  extrasFor,
}: {
  data: FixtureOutlookMeta;
  extrasFor: (team: string) => TeamExtras | null;
}) {
  const rows = data.teams.length || 1;
  return (
    <div
      data-testid="presentation-timeline"
      className="grid h-full w-full"
      style={
        {
          // The row height every size below derives from: the viewport minus the overlay's own header and padding.
          '--r': `calc((100dvh - 130px) / ${rows})`,
          gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
        } as CSSProperties
      }
    >
      {data.teams.map((team) => {
        const extras = extrasFor(team.team_short);
        const items = extras ? buildTimeline(team.series, extras) : [];
        return (
          <div key={team.team_short} className="flex min-h-0 items-start overflow-hidden">
            <span className="flex-none font-black leading-none text-white" style={{ width: r(2.6), fontSize: r(0.5) }}>
              {team.team_short}
            </span>
            <div className="flex min-w-0 items-start">
              <Items items={items} runByGw={runsByGameweek(team.runs)} m={PRESENTATION} presentation />
            </div>
          </div>
        );
      })}
    </div>
  );
}
