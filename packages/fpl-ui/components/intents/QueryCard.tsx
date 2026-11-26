'use client';

/**
 * QueryCard — one `query` answer: the reading row first, then what the state carries.
 *
 * The reading line, the table cells, the comparison figures, the notes, the message and the chips are all the
 * server's words and numbers: nothing is computed, reformatted or added here beyond the field labels. The
 * table and the comparison are drawn only on a complete answer, so a refusal never shows an empty table.
 * A state this card does not know never reaches it (lib/intent-renderer.ts shows the text alone).
 */
import type { QueryBlock, QueryComparison, QueryComparisonSide } from '@/lib/types';
import { CARD_BASE } from '@/lib/theme';
import { useQueryActions } from '@/lib/chat-ask';
import { useT } from '@/lib/i18n/LocaleProvider';
import CardTable from './CardTable';
import QueryReadingRow from './QueryReadingRow';

const CHIP = 'rounded-full border px-3 py-1.5 text-[12px] font-extrabold leading-tight transition-colors';

export default function QueryCard({ data }: { data: QueryBlock }) {
  const actions = useQueryActions();
  const t = useT();
  const complete = data.state === 'complete';
  const showNotThis = actions != null && data.spec != null && data.reading != null;

  return (
    <div data-testid="query-card" data-state={data.state} className={`mt-3 text-sm ${CARD_BASE} border border-white/10`}>
      <div className="relative z-10 space-y-3 p-4">
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

/** The two sets of matches side by side, in the order asked: [match_set, compare_to]. */
function Comparison({ data }: { data: QueryComparison }) {
  return (
    <div className="space-y-2">
      <span className="block text-[11px] font-extrabold uppercase tracking-wide text-bf-gray">{data.metric_header}</span>
      <div className="grid grid-cols-2 gap-2">
        {data.sides.map((side, i) => (
          <ComparisonColumn key={i} side={side} />
        ))}
      </div>
    </div>
  );
}

function ComparisonColumn({ side }: { side: QueryComparisonSide }) {
  const t = useT();
  const facts: Array<[string, string]> = [
    [t('query.total'), side.total_text],
    [t('query.perMatch'), side.per_match_text],
    [t('query.matches'), String(side.n)],
    [t('query.homeAway'), `${side.home} · ${side.away}`],
    ...(side.mean_fdr_text != null ? [[t('query.meanFdr'), side.mean_fdr_text] as [string, string]] : []),
  ];
  return (
    <section data-testid="query-side" aria-label={side.label} className="min-w-0 space-y-2 rounded-card bg-white/[0.035] p-3">
      <h3 className="text-[12px] font-extrabold leading-snug text-bf-text">{side.label}</h3>
      <span className="block font-display text-2xl leading-none tracking-tighter text-white">{side.value_text}</span>
      <dl className="space-y-1 text-[12px]">
        {facts.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-2">
            <dt className="text-bf-gray">{label}</dt>
            <dd className="text-right text-bf-text">{value}</dd>
          </div>
        ))}
      </dl>
      {side.per_match_values_text.length > 0 && (
        <ul className="flex flex-wrap gap-x-2 gap-y-1 border-t border-white/10 pt-2 text-[11px] text-bf-gray">
          {side.per_match_values_text.map((value, i) => (
            <li key={i}>{value}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
