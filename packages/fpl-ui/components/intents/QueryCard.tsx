'use client';

/**
 * QueryCard — one `query` answer: the reading row first, then what the state carries.
 *
 * The reading line, the table cells, the comparison figures, the notes, the message and the chips are all the
 * server's words and numbers: nothing is computed, reformatted or added here beyond the field labels. The
 * table and the comparison are drawn only on a complete answer, so a refusal never shows an empty table.
 * A state this card does not know never reaches it (lib/intent-renderer.ts shows the text alone).
 */
import type { QueryBlock, QueryComparison, QueryComparisonMetric } from '@/lib/types';
import { ACCENT_HEX, CARD_ACCENT, CARD_BASE } from '@/lib/theme';
import { FingerprintWaves } from './CardOrnaments';
import { useQueryActions } from '@/lib/chat-ask';
import { useT } from '@/lib/i18n/LocaleProvider';
import CardTable from './CardTable';
import QueryReadingRow from './QueryReadingRow';

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
            reading={data.reading}
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

        {data.footnote != null && (
          <p data-testid="query-footnote" className="border-t border-white/10 pt-2 text-[11px] text-bf-gray/70">
            {data.footnote}
          </p>
        )}

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

/**
 * The two sets of matches side by side, in the order asked: [match_set, compare_to]. Each column is
 * ComparisonCard's option column (no winner tint: the card names none). Inside, one block per statistic: its
 * name, GenericCard's hero stat saying what the big number is, the other figure, and every match's value under
 * its gameweek. All of it is the server's text.
 */
function Comparison({ data }: { data: QueryComparison }) {
  return (
    <div role="group" aria-label={data.metric_header} className="grid grid-cols-2 gap-2.5">
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
  );
}

function MetricBlock({ metric, side }: { metric: QueryComparisonMetric; side: number }) {
  const t = useT();
  const figures = metric.sides[side];
  // The headline is one of the two figures; only the other one goes under it.
  const [otherLabel, other] =
    metric.headline === 'per_match'
      ? [t('query.total'), figures.total_text]
      : [t('query.perMatch'), figures.per_match_text];
  return (
    <div data-testid="query-metric" data-metric={metric.key} className="space-y-1.5 border-t border-white/10 pt-2">
      <h4 className="text-[11px] font-extrabold uppercase tracking-wide text-bf-cyan">{metric.label}</h4>
      <p className="space-y-0.5">
        <span className="block font-display text-2xl leading-none tracking-tighter text-white">
          {figures.value_text}
        </span>
        <span className="block text-[11px] uppercase tracking-wide text-bf-gray">{metric.hero_label}</span>
      </p>
      {other != null && (
        <p className="text-[12px] text-bf-gray">
          {otherLabel} <span className="font-bold text-bf-text">{other}</span>
        </p>
      )}
      <ul aria-label={metric.label} className="flex flex-wrap gap-1">
        {figures.series.map((match, i) => (
          <li key={i} className="flex min-w-[2.25rem] flex-col items-center gap-0.5 rounded bg-black/25 px-1 py-1">
            <span className="text-[9px] font-bold uppercase text-bf-gray">{match.label}</span>
            <span className="font-display text-[12px] leading-none tracking-tighter text-white">{match.value_text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
