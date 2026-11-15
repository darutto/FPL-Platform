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
  cellAriaLabel,
  cellTitle,
  gwLabel,
  type Band,
} from '@/lib/fixture-outlook-format';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import {
  buildPresentationColumns,
  buildTimeline,
  competitionLegend,
  competitionColor,
  competitionTileLabel,
  type GapInfo,
  type PresentationColumn,
  type SlotMatch,
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

function PlTile({
  gw,
  ring,
  m,
  onAsk,
}: {
  gw: FixtureOutlookGW;
  ring: string | null;
  m: Metrics;
  onAsk?: () => void;
}) {
  const { locale } = useLocale();
  const blank = gw.band === null;
  const fg = blank ? BLANK_COLOR : bandColor(gw.band as Band);
  const opponents = blank ? '—' : gw.fixtures.map((f) => f.opponent_short).join('/');
  const venue = blank ? '' : gw.fixtures.map((f) => venueLabel(f.is_home, locale)).join('/');
  const style: CSSProperties = {
    minWidth: m.plW,
    height: m.plH,
    borderRadius: m.radius,
    backgroundColor: hexRgba(fg, 0.2),
    border: `1.5px solid ${hexRgba(fg, 0.55)}`,
    boxShadow: ring ? `0 0 0 2px ${hexRgba(ring, 0.7)}` : undefined,
  };
  const label = cellTitle(gw, locale);
  const inner = (
    <>
      <span className="leading-none text-bf-gray font-normal" style={{ fontSize: m.gwFont }}>{gwLabel(gw.gameweek, locale)}</span>
      <span className="font-bold leading-none tracking-tight" style={{ fontSize: m.oppFont, color: fg }}>{opponents}</span>
      <span className="leading-none font-normal text-bf-gray min-h-[11px]" style={{ fontSize: m.haFont }}>{venue}</span>
    </>
  );
  const base = 'flex flex-none flex-col items-center justify-center gap-[3px] px-1';
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
  selected,
  onPick,
}: {
  item: Extract<TimelineItem, { kind: 'extra' }>;
  m: Metrics;
  selected: boolean;
  onPick?: () => void;
}) {
  const { locale } = useLocale();
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
  const ha = venueLabel(item.match.venue === 'H', locale);
  const inner = (
    <>
      <span className="font-normal uppercase leading-none tracking-[0.1em]" style={{ fontSize: m.siglaFont, color }}>
        {competitionTileLabel(item.match.competition)}
      </span>
      <span className="mt-[3px] font-bold leading-none text-bf-text" style={{ fontSize: m.codeFont }}>{code}</span>
      <span className="mt-[2px] font-normal leading-none text-bf-gray" style={{ fontSize: m.exHaFont }}>{ha}</span>
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
  detail,
  onDetail,
  onAskCell,
}: {
  items: TimelineItem[];
  runByGw: Map<number, FixtureOutlookRun>;
  m: Metrics;
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
                onAsk={onAskCell ? () => onAskCell(item.gw) : undefined}
              />
            ) : (
              <ExtraTile
                item={item}
                m={m}
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
  const { locale } = useLocale();
  const [detail, setDetail] = useState<string | null>(null);
  const detailId = useId();
  const items = buildTimeline(team.series, extras, locale);
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

// ---------------------------------------------------------------------------
// "Presentar": one fixed grid for the whole league
// ---------------------------------------------------------------------------

/** Everything below is sized from `--r`, the height of one team row. */
const r = (k: number) => `calc(var(--r) * ${k})`;
/** Width of a slot relative to a gameweek column. */
const SLOT_FR = 0.8;
/** The text colour on an FDR fill: the app's ink, readable on all five band colours. */
const TILE_INK = '#0E0D12';
/** Where the match line runs inside a row (the vertical centre of the tile). */
const LINE_TOP = '46%';

function PresentationTile({ gw }: { gw: FixtureOutlookGW }) {
  const { locale } = useLocale();
  const blank = gw.band === null;
  const fill = blank ? hexRgba(BLANK_COLOR, 0.22) : bandColor(gw.band as Band);
  const opponents = blank ? '—' : gw.fixtures.map((f) => f.opponent_short).join('/');
  const venue = blank ? '' : gw.fixtures.map((f) => venueLabel(f.is_home, locale)).join('/');
  const label = cellAriaLabel(gw, locale);
  return (
    <div
      role="img"
      aria-label={label}
      className="flex items-center justify-center gap-[0.3em] overflow-hidden whitespace-nowrap leading-none"
      style={{
        width: '100%',
        height: r(0.8),
        marginTop: r(0.06),
        alignSelf: 'flex-start',
        borderRadius: r(0.16),
        backgroundColor: fill,
        color: blank ? BLANK_COLOR : TILE_INK,
      }}
    >
      <span className="font-extrabold tracking-tight" style={{ fontSize: r(0.42) }}>{opponents}</span>
      <span className="font-semibold opacity-55" style={{ fontSize: r(0.22) }}>{venue}</span>
    </div>
  );
}

/** One thin bar under the tiles of a run; it also crosses the slots between them so a run reads as one stretch. */
function RunBar({ run }: { run: FixtureOutlookRun | undefined }) {
  if (!run) return null;
  return (
    <span
      aria-hidden="true"
      data-testid="run-bar"
      className="absolute inset-x-0"
      style={{
        bottom: r(0.03),
        height: r(0.05),
        borderRadius: r(0.05),
        backgroundColor: runRing(run) ?? undefined,
        opacity: 0.85,
      }}
    />
  );
}

/** The rest between two matches, as a number over the line. Gold only for the rotation notice. */
function RestNumber({ gap, align }: { gap: GapInfo; align: 'center' | 'left' | 'right' }) {
  const pos: CSSProperties =
    align === 'center'
      ? { left: 0, right: 0, textAlign: 'center' }
      : align === 'left'
        ? { left: 0, width: '21%', textAlign: 'center' }
        : { right: 0, width: '21%', textAlign: 'center' };
  return (
    <span
      data-testid={gap.rotation ? 'rotation-notice' : 'rest-days'}
      className={`absolute tabular-nums leading-none ${gap.rotation ? 'font-extrabold text-bf-gold' : 'font-normal text-bf-gray/45'}`}
      style={{ ...pos, top: `calc(${LINE_TOP} - 1.45em)`, fontSize: r(gap.rotation ? 0.27 : 0.22) }}
      title={gap.cell ?? gap.sentence}
    >
      <span aria-hidden="true">{gap.days}d</span>
      <span className="sr-only">{gap.sentence}</span>
    </span>
  );
}

function SlotTile({ item, height, single }: { item: SlotMatch; height: string; single: boolean }) {
  const color = competitionColor(item.match.competition);
  return (
    <div
      role="img"
      aria-label={item.sentence}
      className="flex items-center justify-center overflow-hidden whitespace-nowrap bg-bf-ink leading-none"
      style={{
        width: '58%',
        height,
        flexDirection: single ? 'column' : 'row',
        gap: single ? r(0.03) : '0.3em',
        borderRadius: r(0.14),
        border: `1.5px solid ${color}`,
      }}
    >
      <span className="font-normal uppercase tracking-[0.08em]" style={{ fontSize: r(single ? 0.19 : 0.2), color }}>
        {competitionTileLabel(item.match.competition)}
      </span>
      <span className="font-bold text-bf-text" style={{ fontSize: r(single ? 0.3 : 0.22) }}>{item.match.opponentCode}</span>
    </div>
  );
}

/** The reserved space before a gameweek column: empty (a wider gap), or the competition tile(s) of that window. */
function Slot({ column, run }: { column: PresentationColumn; run: FixtureOutlookRun | undefined }) {
  const matches = column.slot.slice(0, 2);
  const more = column.slot.length - matches.length;
  const rotation = column.gap?.rotation ?? false;
  const rule = (side: 'left' | 'right', gold: boolean) => (
    <span
      aria-hidden="true"
      className={`absolute border-t ${gold ? 'border-solid border-bf-gold/55' : 'border-dashed border-white/10'}`}
      style={{ top: LINE_TOP, [side]: '6%', width: matches.length ? '44%' : '88%' }}
    />
  );
  return (
    <div className="relative min-w-0">
      {matches.length === 0 ? (
        <>
          {rule('left', rotation)}
          {column.gap && <RestNumber gap={column.gap} align="center" />}
        </>
      ) : (
        <>
          {rule('left', false)}
          {rule('right', rotation)}
          {matches[0].gap && <RestNumber gap={matches[0].gap} align="left" />}
          {column.gap && <RestNumber gap={column.gap} align="right" />}
          <div
            className="absolute inset-x-0 flex flex-col items-center justify-center"
            style={{ top: r(0.06), height: r(0.8), gap: r(0.04) }}
          >
            {matches.map((item) => (
              <SlotTile key={item.key} item={item} single={matches.length === 1} height={matches.length === 1 ? r(0.66) : r(0.38)} />
            ))}
            {more > 0 && (
              <span className="absolute right-[4%] font-normal text-bf-gray" style={{ bottom: 0, fontSize: r(0.2) }}>
                +{more}
              </span>
            )}
          </div>
        </>
      )}
      <RunBar run={run} />
    </div>
  );
}

/**
 * "Presentar": every club on ONE grid, so a column is the same gameweek for every team.
 * One column per gameweek, with a reserved slot before each (and before the first, when any
 * club has a match there). A club with another competition in a window shows it in that slot;
 * otherwise the slot stays empty and reads as a wider gap. The gameweek code is written once,
 * in the header row. Sized from the viewport so the 20 rows fit without scrolling.
 */
export function PresentationTimeline({
  data,
  extrasFor,
}: {
  data: FixtureOutlookMeta;
  extrasFor: (team: string) => TeamExtras | null;
}) {
  const { locale } = useLocale();
  const rows = data.teams.length || 1;
  const teams = data.teams.map((team) => ({
    team,
    columns: buildPresentationColumns(team.series, extrasFor(team.team_short), locale),
    runByGw: runsByGameweek(team.runs),
  }));
  const gameweeks = (teams[0]?.columns ?? []).map((c) => c.gw.gameweek);
  // A slot before the first column only exists when some club has a match there; then every row reserves it.
  const leading = teams.some((t) => (t.columns[0]?.slot.length ?? 0) > 0);
  const tracks = gameweeks.flatMap((_, i) =>
    i > 0 || leading ? [`minmax(0, ${SLOT_FR}fr)`, 'minmax(0, 1fr)'] : ['minmax(0, 1fr)'],
  );
  const stickyTeam: CSSProperties = { position: 'sticky', left: 0, zIndex: 2, backgroundColor: '#0E0D12' };
  return (
    <div
      data-testid="presentation-timeline"
      className="grid h-full w-full overflow-x-auto overflow-y-hidden"
      style={
        {
          // The row height every size below derives from: the viewport minus the overlay's own header and padding,
          // shared between the teams and the one header row (0.7 of a row).
          '--r': `calc((100dvh - 130px) / ${rows + 0.7})`,
          gridTemplateColumns: `${r(1.9)} ${tracks.join(' ')}`,
          gridTemplateRows: `${r(0.7)} repeat(${rows}, minmax(0, 1fr))`,
        } as CSSProperties
      }
    >
      <span style={stickyTeam} aria-hidden="true" />
      {gameweeks.map((gw, i) => (
        <span key={gw} className="contents">
          {(i > 0 || leading) && <span aria-hidden="true" />}
          <span
            data-testid="gw-header"
            className="flex items-center justify-center font-extrabold tracking-wide text-bf-gray"
            style={{ fontSize: r(0.3) }}
          >
            {gwLabel(gw, locale)}
          </span>
        </span>
      ))}
      {teams.map(({ team, columns, runByGw }) => (
        <div key={team.team_short} data-testid="presentation-row" className="contents">
          <span
            className="flex items-start font-black leading-none text-white"
            style={{ ...stickyTeam, fontSize: r(0.5), paddingTop: r(0.1) }}
          >
            {team.team_short}
          </span>
          {columns.map((column, i) => {
            const run = runByGw.get(column.gw.gameweek);
            const previousRun = i > 0 ? runByGw.get(columns[i - 1].gw.gameweek) : undefined;
            return (
              <span key={column.gw.gameweek} className="contents">
                {(i > 0 || leading) && <Slot column={column} run={run && run === previousRun ? run : undefined} />}
                <div className="relative flex min-w-0 justify-center">
                  <PresentationTile gw={column.gw} />
                  <RunBar run={run} />
                </div>
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/** The one-line legend of the presentation header: what the fill, the bar under a run, the tiles and the gold number mean. */
export function PresentationLegend({ note }: { note?: string | null }) {
  const t = useT();
  const { locale } = useLocale();
  const bands = [1, 2, 3, 4, 5] as const;
  return (
    <p
      data-testid="presentation-legend"
      className="flex items-center gap-[clamp(10px,1.2vw,22px)] whitespace-nowrap font-normal text-bf-gray"
      style={{ fontSize: 'clamp(10px, 0.85vw, 15px)' }}
    >
      <span className="inline-flex items-center gap-1.5">
        {t('fx.band.1')}
        <span className="inline-flex gap-[2px]">
          {bands.map((b) => (
            <i key={b} aria-hidden="true" className="inline-block h-[0.9em] w-[1.4em] rounded-[3px]" style={{ backgroundColor: bandColor(b) }} />
          ))}
        </span>
        {t('fx.band.4')}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <i aria-hidden="true" className="inline-block h-[3px] w-[1.6em] rounded-full" style={{ backgroundColor: GOOD_HEX }} />
        {t('fx.pl.goodRun')}
        <i aria-hidden="true" className="inline-block h-[3px] w-[1.6em] rounded-full" style={{ backgroundColor: BAD_HEX }} />
        {t('fx.pl.hardRun')}
      </span>
      {competitionLegend(locale).map((entry) => (
        <span key={entry.label} className="inline-flex items-center gap-1.5">
          <i aria-hidden="true" className="inline-block h-[0.8em] w-[0.8em] rounded-[2px] border-[1.5px]" style={{ borderColor: entry.color }} />
          {entry.short ?? entry.label}
        </span>
      ))}
      <span className="text-bf-gold">{t('fx.pl.rest')}</span>
      {note && <span data-testid="presentation-coverage">{note}</span>}
    </p>
  );
}
