'use client';

/**
 * InvolvementCompareCard — R6 two-player involvement comparison (get_player_involvement with compare_player).
 *
 * Rendered by GenericCard when generic_card.involvement_compare is set. Two views, switched by icons in the header:
 *   - Per 90: five face-off bars. The winner keeps full weight; the other figure is dimmed with a thinner bar. A tie
 *     (winner null) dims neither. The backward share never has a winner: both in neutral gray.
 *   - By match: the per-match series of the chosen metric on one gameweek axis, a faint dashed least-squares line per
 *     player, and each player's per-90 average with the backend's trend mark (up/down/steady; none under 3 matches).
 *
 * Colour is conservative: only bars, lines and dots carry the player colour (cyan / coral-soft). Every figure is in the
 * text colour; the winner is marked by typographic weight, never by colour. A null value is a gap, never 0.
 * Every number, label and winner comes from the backend payload; the UI computes only geometry (and the drawn line,
 * with the same least-squares fit over axis positions the backend uses for the mark).
 */
import { useEffect, useRef, useState } from 'react';
import type {
  InvolvementCompareMeta,
  InvolvementPer90Row,
  InvolvementSeriesMetric,
  InvolvementSide,
  InvolvementTrend,
} from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { FingerprintWaves } from './CardOrnaments';
import { intlTag } from '@/lib/i18n/format';
import type { Locale } from '@/lib/i18n/locale';
import { useLocale } from '@/lib/i18n/LocaleProvider';

interface Props {
  data: InvolvementCompareMeta;
}

type View = 'per90' | 'series';
type SeriesKey = InvolvementSeriesMetric['metric'];

const COLOR = { a: ACCENT_HEX.cyan, b: '#F27A5E' } as const; // bf-cyan, bf-coral-soft
const BAR_BG = { a: 'bg-bf-cyan', b: 'bg-bf-coral-soft' } as const;

/** Typography by role. Winner and tie share the full figure; the other side is dimmed; no-winner metrics are neutral. */
export const FIGURE_CLASS = {
  lead: 'font-display text-[17px] leading-none tracking-tight text-bf-text',
  dim: 'font-display text-[17px] leading-none tracking-tight text-bf-text/40',
  neutral: 'font-semibold text-[15px] leading-none text-bf-text/70',
} as const;

/**
 * A figure in the language showing: per-90 metrics always carry one decimal (58,0 · 1,0 · 40,0) so the two sides read
 * at the same precision; a percentage keeps no decimal when it has none. Spanish uses the decimal comma and "85 %".
 */
export function fmt(value: number | null, unit: string, locale: Locale): string {
  if (value == null) return '–';
  const digits = unit === '%' && Number.isInteger(value) ? 0 : 1;
  const text = value.toLocaleString(intlTag(locale), { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (!unit) return text;
  return locale === 'es' ? `${text} ${unit}` : `${text}${unit}`;
}

function role(side: InvolvementSide, winner: InvolvementSide | null, hasWinner: boolean): keyof typeof FIGURE_CLASS {
  if (!hasWinner) return 'neutral';
  if (winner == null || winner === side) return 'lead';
  return 'dim';
}

// ---------------------------------------------------------------------------------------------------------- icons

const ICON_PATHS: Record<string, string> = {
  touches: 'M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16M12 4v4M12 16v4M4 12h4M16 12h4',
  key_passes: 'M8 8.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 1 0 0-7M11.5 12H20M17 12v3M20 12v2',
  passes: 'M4 12h14M14 7l5 5-5 5',
  pass_accuracy: 'M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6',
  backward_share: 'M20 12H6M10 7l-5 5 5 5',
  per90: 'M4 7h7M13 7h7M7 12h4M13 12h5M5 17h6M13 17h4',
  series: 'M3 17l5-5 4 3 8-8M15 7h5v5',
};

function Icon({ name, className = 'h-4 w-4' }: { name: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

const TREND_GLYPH: Record<InvolvementTrend, string> = { up: '↗', down: '↘', flat: '→' };

// ---------------------------------------------------------------------------------------------------- switchers

function IconSwitch<K extends string>({
  items, value, onChange, label, neutral = false,
}: {
  items: { key: K; icon: string; label: string }[];
  value: K;
  onChange: (key: K) => void;
  label: string;
  neutral?: boolean;
}) {
  return (
    <div role="group" aria-label={label}
      className="flex items-center gap-0.5 rounded-full border border-white/10 bg-black/30 p-0.5">
      {items.map((item) => {
        const active = item.key === value;
        const on = neutral ? 'bg-white/15 text-bf-text' : 'bg-bf-coral text-bf-ink';
        return (
          <button key={item.key} type="button" aria-pressed={active} aria-label={item.label} title={item.label}
            onClick={() => { if (!active) onChange(item.key); }}
            className={`rounded-full px-2.5 py-1 leading-none transition-colors ${active ? on : 'text-bf-gray hover:text-bf-text'}`}>
            <Icon name={item.icon} />
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------ per 90

function Per90Row({ row }: { row: InvolvementPer90Row }) {
  const { locale } = useLocale();
  const hasWinner = row.metric !== 'backward_share';
  const top = Math.max(row.a ?? 0, row.b ?? 0) * 1.08 || 1;
  const side = (s: InvolvementSide) => {
    const value = row[s];
    const r = role(s, row.winner, hasWinner);
    const bar = !hasWinner
      ? 'h-1.5 bg-bf-gray/45'
      : `${BAR_BG[s]} ${r === 'dim' ? 'h-[5px] opacity-60' : 'h-2'}`;
    return (
      <div className={`flex min-w-0 flex-1 flex-col justify-end gap-1.5 ${s === 'a' ? 'text-left' : 'text-right'}`}>
        <span data-role={r} data-side={s} className={FIGURE_CLASS[r]}>{fmt(value, row.unit, locale)}</span>
        {value != null && (
          <div className={`rounded ${bar} ${s === 'a' ? 'ml-auto' : 'mr-auto'}`}
            style={{ width: `${Math.round((100 * value) / top)}%` }} />
        )}
      </div>
    );
  };
  return (
    <div className="flex items-end gap-2.5" data-metric={row.metric}>
      {side('a')}
      <div className="flex w-[74px] flex-none flex-col items-center gap-0.5 text-[11px] font-bold text-bf-gray">
        <Icon name={row.metric} />
        <span>{row.label}</span>
      </div>
      {side('b')}
    </div>
  );
}

// -------------------------------------------------------------------------------------------------- by match

const CHART_H = 128;
const PAD = { l: 14, r: 30, t: 12, b: 22 };

function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(200, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Least squares over the known values at their axis positions: the same fit the backend reads the trend from. */
export function fitLine(values: (number | null)[]): { at: (x: number) => number } | null {
  const pts = values.flatMap((v, i) => (v == null ? [] : [[i, v] as const]));
  if (pts.length < 3) return null;
  const xm = pts.reduce((s, [x]) => s + x, 0) / pts.length;
  const ym = pts.reduce((s, [, y]) => s + y, 0) / pts.length;
  const sxx = pts.reduce((s, [x]) => s + (x - xm) ** 2, 0);
  const slope = sxx ? pts.reduce((s, [x, y]) => s + (x - xm) * (y - ym), 0) / sxx : 0;
  return { at: (x) => ym + slope * (x - xm) };
}

/** Consecutive known values as separate runs, so a gap breaks the line instead of joining over it. */
export function runs(values: (number | null)[]): [number, number][][] {
  const out: [number, number][][] = [];
  let cur: [number, number][] = [];
  values.forEach((v, i) => {
    if (v == null) {
      if (cur.length) out.push(cur);
      cur = [];
    } else cur.push([i, v]);
  });
  if (cur.length) out.push(cur);
  return out;
}

function Chart({ metric, labels, width }: { metric: InvolvementSeriesMetric; labels: string[]; width: number }) {
  const n = Math.max(labels.length, 1);
  const all = [...metric.a, ...metric.b].filter((v): v is number => v != null);
  const top = Math.max(1, ...all) * 1.15;
  const x = (i: number) => PAD.l + (n === 1 ? 0 : (i * (width - PAD.l - PAD.r)) / (n - 1));
  const y = (v: number) => PAD.t + (CHART_H - PAD.t - PAD.b) * (1 - v / top);

  const player = (s: InvolvementSide) => {
    const values = metric[s];
    const fit = fitLine(values);
    const lastIdx = values.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0).pop();
    return (
      <g key={s} data-series={s}>
        {fit && (
          <line data-trendline={s} x1={x(0)} y1={y(fit.at(0))} x2={x(n - 1)} y2={y(fit.at(n - 1))}
            stroke={COLOR[s]} strokeOpacity={0.45} strokeWidth={1.4} strokeDasharray="5 4" />
        )}
        {runs(values).map((run, k) => (
          <polyline key={k} data-run={s} fill="none" stroke={COLOR[s]} strokeOpacity={0.85} strokeWidth={1.6}
            strokeLinejoin="round" points={run.map(([i, v]) => `${x(i)},${y(v)}`).join(' ')} />
        ))}
        {values.map((v, i) => (v == null ? null : <circle key={i} cx={x(i)} cy={y(v)} r={3.3} fill={COLOR[s]} />))}
        {lastIdx != null && (
          <text x={x(lastIdx) + 8} y={y(values[lastIdx] as number) + 4} fontSize={11} fontWeight={700}
            fill={s === 'a' ? '#f0f0f0' : 'rgba(240,240,240,.6)'}>{values[lastIdx]}</text>
        )}
      </g>
    );
  };

  return (
    <svg width={width} height={CHART_H} role="img" aria-label={metric.label} className="block">
      <line x1={PAD.l - 6} x2={width - PAD.r + 12} y1={y(0)} y2={y(0)} stroke="rgba(255,255,255,.08)" />
      {player('b')}
      {player('a')}
      {labels.map((label, i) => (
        <text key={i} x={x(i)} y={CHART_H - 6} textAnchor="middle" fontSize={10} fontWeight={700} fill="#ABA9AC">
          {label}
        </text>
      ))}
    </svg>
  );
}

function TrendMark({ trend, labels }: { trend: InvolvementTrend | null; labels: InvolvementCompareMeta['labels'] }) {
  if (trend == null) return null;
  const label = labels[`trend_${trend}` as const];
  return (
    <span role="img" aria-label={label} title={label} data-trend={trend}
      className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-white/20 text-xs text-bf-text/85">
      {TREND_GLYPH[trend]}
    </span>
  );
}

function SeriesView({ data }: { data: InvolvementCompareMeta }) {
  const { locale } = useLocale();
  const [key, setKey] = useState<SeriesKey>('touches');
  const [ref, width] = useWidth<HTMLDivElement>(320);
  const metric = data.series.metrics.find((m) => m.metric === key) ?? data.series.metrics[0];
  if (!metric) return null;
  const avg = (s: InvolvementSide) => {
    const r = role(s, metric.avg_winner, true);
    return <span data-role={r} data-side={s} className={FIGURE_CLASS[r]}>{fmt(metric[`avg_${s}`], '', locale)}</span>;
  };
  return (
    <div className="flex flex-col gap-2.5" data-view="series">
      <div className="flex items-center justify-between gap-2">
        <IconSwitch<SeriesKey>
          neutral
          label={data.labels.view_series}
          value={key}
          onChange={setKey}
          items={data.series.metrics.map((m) => ({ key: m.metric, icon: m.metric, label: m.label }))}
        />
        <span className="text-xs font-bold text-bf-gray">{metric.label}</span>
      </div>
      <div ref={ref} className="w-full">
        <Chart metric={metric} labels={data.series.gw_labels} width={width} />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-bf-cyan" aria-hidden="true" />
          {avg('a')}
          <TrendMark trend={metric.trend_a} labels={data.labels} />
        </span>
        <span className="text-xs font-semibold text-bf-gray">{data.labels.avg}</span>
        <span className="flex items-center gap-2">
          <TrendMark trend={metric.trend_b} labels={data.labels} />
          {avg('b')}
          <span className="h-2 w-2 rounded-full bg-bf-coral-soft" aria-hidden="true" />
        </span>
      </div>
    </div>
  );
}

// -------------------------------------------------------------------------------------------------------- card

export default function InvolvementCompareCard({ data }: Props) {
  const [view, setView] = useState<View>('per90');
  return (
    <div className={`mt-3 w-full max-w-[560px] text-sm ${CARD_BASE} ${CARD_ACCENT.cyan.border}`}
      data-testid="involvement-compare-card">
      <FingerprintWaves color={ACCENT_HEX.cyan} corner="br" />
      <div className="relative z-10 flex flex-col gap-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-extrabold uppercase tracking-wide text-bf-cyan">{data.labels.title}</span>
          <IconSwitch<View>
            label={data.labels.title}
            value={view}
            onChange={setView}
            items={[
              { key: 'per90', icon: 'per90', label: data.labels.view_per90 },
              { key: 'series', icon: 'series', label: data.labels.view_series },
            ]}
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5 text-[15px] font-extrabold text-white">
            <span className="h-2 w-2 flex-none rounded-full bg-bf-cyan" aria-hidden="true" />
            {data.a.name}
            {data.a.team && <small className="text-[11px] font-bold text-bf-gray">{data.a.team}</small>}
          </span>
          <span className="flex min-w-0 items-center gap-1.5 text-[15px] font-extrabold text-white">
            {data.b.team && <small className="text-[11px] font-bold text-bf-gray">{data.b.team}</small>}
            {data.b.name}
            <span className="h-2 w-2 flex-none rounded-full bg-bf-coral-soft" aria-hidden="true" />
          </span>
        </div>
        {view === 'per90' ? (
          <div className="flex flex-col gap-2.5" data-view="per90">
            {data.per90.map((row) => <Per90Row key={row.metric} row={row} />)}
          </div>
        ) : (
          <SeriesView data={data} />
        )}
        <div className="space-y-0.5 border-t border-white/10 pt-2 text-[11px] text-bf-gray/70">
          <p>{data.footer}</p>
          {data.note && <p>{data.note}</p>}
          {data.provenance && <p>{data.provenance}</p>}
        </div>
      </div>
    </div>
  );
}
