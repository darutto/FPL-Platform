'use client';

/**
 * QueryCard — one `query` answer: the reading row first, then what the state carries.
 *
 * The reading line, the table cells, the comparison figures, the notes, the message and the chips are all the
 * server's words and numbers: nothing is computed, reformatted or added here beyond the field labels. The
 * table and the comparison are drawn only on a complete answer, so a refusal never shows an empty table.
 * A state this card does not know never reaches it (lib/intent-renderer.ts shows the text alone).
 */
import FootNote from '@/components/blocks/FootNote';
import HeroStat from '@/components/blocks/HeroStat';
import type { QueryBlock, QueryComparison, QueryComparisonMetric } from '@/lib/types';
import { ACCENT_HEX, CARD_ACCENT, CARD_BASE } from '@/lib/theme';
import { FingerprintWaves } from './CardOrnaments';
import { useQueryActions } from '@/lib/chat-ask';
import { useT } from '@/lib/i18n/LocaleProvider';
import CardTable from './CardTable';
import QueryReadingRow from './QueryReadingRow';

const SET_PARTS = ['match_set', 'compare_to'];

const CHIP = 'rounded-full border px-3 py-1.5 text-[12px] font-extrabold leading-tight transition-colors';

export default function QueryCard({ data }: { data: QueryBlock }) {
  const actions = useQueryActions();
  const t = useT();
  const complete = data.state === 'complete';
  const comparison = complete && data.comparison != null;
  const showNotThis = actions != null && data.spec != null && data.reading != null;

  return (
    <div
      data-testid="query-card"
      data-state={data.state}
      className={`mt-3 text-sm ${CARD_BASE} ${comparison ? CARD_ACCENT.cyan.border : CARD_ACCENT.gray.border}`}
    >
      {comparison && <FingerprintWaves color={ACCENT_HEX.cyan} corner="br" />}
      <div className="relative z-10 space-y-3 p-4">
        {comparison && (
          <span className="block text-xs font-extrabold uppercase tracking-wide text-bf-cyan">{t('cmp.label')}</span>
        )}
        {data.reading != null && (
          <QueryReadingRow
            // The column headings already say each set and its gameweeks.
            reading={
              comparison
                ? { ...data.reading, parts: data.reading.parts.filter((p) => !SET_PARTS.includes(p.kind)) }
                : data.reading
            }
            changed={data.changed_parts}
            onPick={actions ? (spec, _part, alternative) => actions.pick(spec, alternative.label) : undefined}
          />
        )}

        {data.message != null && data.message !== '' && (
          <p className="whitespace-pre-line leading-relaxed text-bf-text">{data.message}</p>
        )}

        {complete && data.table != null && <CardTable columns={data.table.columns} rows={data.table.rows} />}
        {complete && data.comparison != null && <Comparison data={data.comparison} />}

        {data.notes.length > 0 && (
          <ul data-testid="query-notes" className="space-y-1 border-t border-white/10 pt-2 text-[12px] text-bf-gray">
            {data.notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        )}

        {/* The unchecked-totals line stays in the app; a shared image leaves it out. */}
        <FootNote lines={[data.footnote]} hideInShare testId="query-footnote" />

        {actions != null && (data.chips.length > 0 || showNotThis) && (
          <div className="flex flex-wrap gap-2">
            {data.chips.map((chip) => (
              <button
                key={chip.label}
                type="button"
                onClick={() => actions.pick(chip.spec, chip.label)}
                className={`${CHIP} border-bf-turquoise/40 bg-bf-turquoise/10 text-bf-turquoise hover:bg-bf-turquoise/20`}
              >
                {chip.label}
              </button>
            ))}
            {showNotThis && (
              <button
                type="button"
                onClick={actions.correct}
                className={`${CHIP} border-white/10 text-bf-gray hover:text-bf-text`}
              >
                {t('query.notThis')}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** A figure as sent: one number, or "low–high" where two measures differ. `mid` only sizes bars and chips. */
export function readFigure(text: string): { mid: number; range: boolean } | null {
  const ends = text.split('–').map((end) => (end.trim() === '' ? NaN : Number(end)));
  if (ends.length > 2 || ends.some((end) => !Number.isFinite(end))) return null;
  return { mid: (ends[0] + ends[ends.length - 1]) / 2, range: ends.length === 2 };
}

const share = (text: string, top: number) => {
  const figure = readFigure(text);
  return figure == null || top <= 0 ? 0 : Math.max(0, Math.min(100, (100 * figure.mid) / top));
};
const highest = (texts: string[]) => Math.max(0, ...texts.map((text) => readFigure(text)?.mid ?? 0));

// The two sets, told apart without judging either: no green or red.
const SIDE_BAR = ['bg-bf-cyan', 'bg-bf-gray/60'] as const;

/**
 * The difference at a glance: two bars per statistic on one scale. Only per-match figures are paired, since a
 * count over sets of different sizes would compare nothing.
 */
function PairedBars({ data }: { data: QueryComparison }) {
  const t = useT();
  const metrics = data.metrics.filter((metric) => metric.headline === 'per_match');
  if (metrics.length === 0) return null;
  return (
    <div data-testid="query-bars" className="space-y-3 rounded-lg border border-white/10 bg-white/[0.04] p-2.5">
      {metrics.map((metric) => {
        const top = highest(metric.sides.map((side) => side.value_text));
        return (
          <div key={metric.key} data-metric={metric.key} className="space-y-1.5">
            <MetricTitle label={metric.label} unit={t('query.perMatch')} />
            {metric.sides.map((side, i) => (
              <div key={i} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] items-center gap-2">
                <span className="truncate text-[11px] text-bf-gray">{data.sides[i].title}</span>
                <span aria-hidden="true" className="h-2 overflow-hidden rounded bg-black/25">
                  <span
                    data-testid="query-bar"
                    className={`block h-full rounded ${SIDE_BAR[i]}`}
                    style={{ width: `${share(side.value_text, top)}%` }}
                  />
                </span>
                <span className="text-right font-display text-[15px] leading-none tracking-tighter text-white">
                  {side.value_text}
                </span>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function MetricTitle({ label, unit }: { label: string; unit: string }) {
  return (
    <h4 className="text-[11px] font-extrabold uppercase tracking-wide text-bf-cyan">
      {label} <span className="text-bf-gray">· {unit.toLowerCase()}</span>
    </h4>
  );
}

/**
 * The two sets of matches side by side, in the order asked: [match_set, compare_to]. Each column is
 * ComparisonCard's option column (no winner tint: the card names none). Inside, one block per statistic: its
 * name and unit, GenericCard's hero number, the other figure, and a small bar per match under its gameweek.
 */
function Comparison({ data }: { data: QueryComparison }) {
  return (
    <div role="group" aria-label={data.metric_header} className="space-y-2.5">
      <PairedBars data={data} />
      <div className="grid grid-cols-2 gap-2.5">
        {data.sides.map((side, i) => (
          <section
            key={i}
            data-testid="query-side"
            aria-label={side.title}
            className="flex min-w-0 flex-col gap-3 rounded-lg border border-white/10 bg-white/[0.04] p-2.5"
          >
            <div>
              <h3 className="font-extrabold leading-snug text-white">{side.title}</h3>
              <p className="text-[11px] text-bf-gray">{side.detail}</p>
            </div>
            {data.metrics.map((metric) => (
              <MetricBlock key={metric.key} metric={metric} side={i} />
            ))}
            <p className="mt-auto text-[11px] text-bf-gray/70">{side.venue_text}</p>
          </section>
        ))}
      </div>
    </div>
  );
}

function MetricBlock({ metric, side }: { metric: QueryComparisonMetric; side: number }) {
  const t = useT();
  const figures = metric.sides[side];
  const perMatch = metric.headline === 'per_match';
  // The headline is one of the two figures; only the other one goes under it.
  const [otherLabel, other] = perMatch
    ? [t('query.total'), figures.total_text]
    : [t('query.perMatch'), figures.per_match_text];
  // One scale for both columns, so a bar means the same on each side.
  const top = highest(metric.sides.flatMap((s) => s.series.map((match) => match.value_text)));
  const ranges = figures.series.filter((match) => readFigure(match.value_text)?.range);
  return (
    <div data-testid="query-metric" data-metric={metric.key} className="space-y-1.5 border-t border-white/10 pt-2">
      <MetricTitle label={metric.label} unit={perMatch ? t('query.perMatch') : t('query.total')} />
      <HeroStat
        size="medium"
        value={figures.value_text}
        toneClass="text-white"
        secondary={other != null ? { label: otherLabel, value: other } : null}
      />
      <ul aria-label={metric.label} className="grid grid-cols-[repeat(auto-fill,minmax(2.25rem,1fr))] gap-1">
        {figures.series.map((match, i) => {
          const figure = readFigure(match.value_text);
          return (
            <li
              key={i}
              title={figure?.range ? `${match.label}: ${match.value_text}` : undefined}
              className="flex flex-col items-center gap-1"
            >
              <span className="whitespace-nowrap font-display text-[11px] leading-none tracking-tighter text-white">
                {figure?.range ? `≈${figure.mid.toFixed(2)}` : match.value_text}
              </span>
              <span aria-hidden="true" className="flex h-6 w-full items-end justify-center border-b border-white/15">
                <span
                  className={`block w-3 rounded-t-sm ${SIDE_BAR[side]}`}
                  style={{ height: `${share(match.value_text, top)}%` }}
                />
              </span>
              <span className="text-[9px] font-bold uppercase leading-none text-bf-gray">{match.label}</span>
            </li>
          );
        })}
      </ul>
      {/* A tooltip does not exist on a phone, so each range is also written out. */}
      {ranges.length > 0 && (
        <p data-testid="query-ranges" className="text-[10px] leading-snug text-bf-gray/70">
          ≈ {t('query.midpoint')}: {ranges.map((match) => `${match.label} ${match.value_text}`).join(' · ')}
        </p>
      )}
    </div>
  );
}
