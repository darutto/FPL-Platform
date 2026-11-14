'use client';

/**
 * TableConclusions — the verdict above a TABLE card (rankings, differentials, resources):
 * 0-3 one-line conclusions that talk ABOUT the table and never reprint its rows.
 *
 * The backend sends structured keys + params + evidence (`table_conclusions`); the wording
 * lives here and in lib/i18n. Same row as PlayerConclusions: icon + label on the left,
 * evidence muted on the right; on narrow screens the evidence wraps under the label.
 * An unknown key or malformed params drops that line (never shown raw); no lines → nothing.
 */

import type { ReactNode } from 'react';
import type { TableConclusion } from '@/lib/types';
import type { DictKey } from '@/lib/i18n/dictionary';
import { useT } from '@/lib/i18n/LocaleProvider';

type T = ReturnType<typeof useT>;

const SVG_PROPS = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  className: 'h-[18px] w-[18px] flex-none text-bf-purple',
};

const ICONS: Record<TableConclusion['key'], ReactNode> = {
  // One bar standing clear of the rest.
  gap: (
    <svg {...SVG_PROPS}>
      <path d="M5 20V5" />
      <path d="M12 20v-7M17 20v-5" strokeOpacity=".45" />
      <path d="M3 20h18" />
    </svg>
  ),
  // A cluster: three of the same.
  concentration: (
    <svg {...SVG_PROPS}>
      <circle cx="8" cy="9" r="3" />
      <circle cx="16" cy="9" r="3" />
      <circle cx="12" cy="16" r="3" fill="currentColor" fillOpacity=".35" />
    </svg>
  ),
  // A gem: the pick few managers have.
  opportunity: (
    <svg {...SVG_PROPS}>
      <path d="M6 4h12l3 5-9 11L3 9z" />
      <path d="M3 9h18M9 4l3 5 3-5" strokeOpacity=".45" />
    </svg>
  ),
  // How to read it.
  reading: (
    <svg {...SVG_PROPS}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6" />
      <circle cx="12" cy="7.5" r="0.6" fill="currentColor" />
    </svg>
  ),
};

/** Metric words that read the same in both languages. */
const NEUTRAL_METRIC: Record<string, string> = {
  expected_goals: 'xG',
  expected_assists: 'xA',
  expected_goal_involvements: 'xGI',
  expected_goals_conceded: 'xGC',
  ict_index: 'ICT',
  bps: 'BPS',
  bonus: 'bonus',
  defensive_contribution: 'DC',
};

/** Metric words that need translating (`tconcl.metric.<id>`). */
const WORDED_METRIC = [
  'form', 'total_points', 'points_per_game', 'minutes', 'goals_scored', 'assists', 'clean_sheets', 'saves',
  'selected_by_percent', 'now_cost',
] as const;

const POSITIONS = ['GKP', 'DEF', 'MID', 'FWD'] as const;

const isText = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0;
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;

/** The short word for a canonical metric id ("xG", "puntos", "xGI/90"), or null when this UI doesn't know it. */
export function metricLabel(metric: unknown, t: T): string | null {
  if (!isText(metric)) return null;
  const per90 = metric.endsWith('_per_90');
  const base = per90 ? metric.slice(0, -'_per_90'.length) : metric;
  const word =
    NEUTRAL_METRIC[base] ??
    ((WORDED_METRIC as readonly string[]).includes(base) ? t(`tconcl.metric.${base}` as DictKey) : null);
  if (word == null) return null;
  return per90 ? `${word}/90` : word;
}

/** A metric difference the way the ranking cards print values: whole numbers bare, the rest with two decimals (dot). */
function formatDiff(diff: number): string {
  const rounded = Math.round(diff * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

/** The line's label, or null for a key or params this UI can't word (dropped, never shown raw). */
export function conclusionLabel(c: TableConclusion, t: T): string | null {
  const raw: unknown = c;
  if (!isObj(raw) || !isObj(raw.params)) return null;
  const p = raw.params;
  switch (raw.key) {
    case 'gap': {
      const leaders = Array.isArray(p.leaders) ? p.leaders : [];
      if (!leaders.every(isText)) return null;
      if (leaders.length === 1) return t('tconcl.gap.one', { name: leaders[0] });
      if (leaders.length === 2) return t('tconcl.gap.two', { a: leaders[0], b: leaders[1] });
      return null;
    }
    case 'concentration': {
      const { count, total, value } = p;
      if (!isNum(count) || !isNum(total) || count < 1 || total < count || !isText(value)) return null;
      if (p.kind === 'position') {
        const pos = POSITIONS.find((x) => x === value);
        return pos ? t('tconcl.conc.position', { count, total, group: t(`tconcl.pos.${pos}`) }) : null;
      }
      if (p.kind === 'team') return t('tconcl.conc.team', { count, total, team: value });
      return null;
    }
    case 'opportunity':
      return p.kind === 'ownership' && isText(p.name) ? t('tconcl.opportunity', { name: p.name }) : null;
    case 'reading':
      return p.kind === 'total_metric' ? t('tconcl.reading.total') : null;
    default:
      return null;
  }
}

/**
 * The muted evidence beside the label, or null when the line has none (or it is malformed).
 * gap → "xG · 3.º a 1.19": how far the next row sits behind the closest leader; an unknown
 * metric id drops the metric word, not the evidence.
 */
export function conclusionEvidence(c: TableConclusion, t: T): string | null {
  const raw: unknown = c;
  if (!isObj(raw) || !isObj(raw.evidence)) return null;
  const ev = raw.evidence;
  if (raw.key === 'gap') {
    const leads = Array.isArray(ev.lead_values) ? ev.lead_values : [];
    if (leads.length === 0 || !leads.every(isNum) || !isNum(ev.next_value) || !isNum(ev.next_rank)) return null;
    const diff = Math.min(...leads) - ev.next_value;
    if (!(diff > 0)) return null;
    const vars = { n: ev.next_rank, diff: formatDiff(diff) };
    const metric = metricLabel(isObj(raw.params) ? raw.params.metric : null, t);
    return metric ? t('tconcl.gap.evidence', { ...vars, metric }) : t('tconcl.gap.evidenceBare', vars);
  }
  if (raw.key === 'opportunity') {
    return isNum(ev.value) ? t('tconcl.opportunity.evidence', { value: ev.value.toFixed(1) }) : null;
  }
  return null;
}

export interface TableConclusionRow {
  c: TableConclusion;
  label: string;
  evidence: string | null;
}

/** The lines that will actually render (wordable, max 3). The chat uses this to decide whether a verdict band exists. */
export function tableConclusionRows(conclusions: TableConclusion[] | undefined | null, t: T): TableConclusionRow[] {
  if (!Array.isArray(conclusions)) return [];
  return conclusions
    .map((c) => ({ c, label: conclusionLabel(c, t), evidence: conclusionEvidence(c, t) }))
    .filter((r): r is TableConclusionRow => r.label != null)
    .slice(0, 3);
}

export default function TableConclusions({ conclusions }: { conclusions: TableConclusion[] | undefined | null }) {
  const t = useT();
  const rows = tableConclusionRows(conclusions, t);
  if (rows.length === 0) return null;
  return (
    <ul aria-label={t('concl.label')} className="flex list-none flex-col gap-1.5" data-testid="table-conclusions">
      {rows.map(({ c, label, evidence }, i) => (
        <li key={`${c.key}-${i}`} className="flex flex-wrap items-start gap-x-2.5 sm:flex-nowrap sm:items-center">
          {ICONS[c.key]}
          <span className="min-w-0 flex-1 text-[15px] font-semibold text-bf-text">{label}</span>
          {evidence && (
            <span className="basis-full pl-7 text-[13px] font-medium text-bf-gray sm:basis-auto sm:pl-0 sm:whitespace-nowrap">
              {evidence}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
