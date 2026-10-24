/**
 * Multi-competition furniture for the /fixtures board: the "Otras competiciones"
 * switch (and its locked twin), the legends, and the compact grid's gutter marks.
 * Rendered only when the backend returned a payload; otherwise nothing at all.
 * Titles here never contain "FDR " (the board's tests read FDR titles to see
 * which difficulty is on screen).
 */
import Link from 'next/link';
import {
  competitionLegend,
  competitionColor,
  gutterSentence,
  LOCKED_BADGE,
  lockedLine,
  lockedLink,
  type CompactGutter,
} from '@/lib/fixture-competitions';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';

const GOLD = 'text-bf-gold';

/** «Otras competiciones»: shows or hides the whole layer. The board remembers the choice. */
export function OtherCompetitionsToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  const t = useT();
  return (
    <label className="inline-flex cursor-pointer select-none items-center gap-2 text-xs font-normal text-bf-gray">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className="relative h-5 w-[34px] flex-none rounded-full bg-white/15 transition-colors after:absolute after:left-[3px] after:top-[3px] after:h-[14px] after:w-[14px] after:rounded-full after:bg-bf-text after:transition-transform peer-checked:bg-bf-turquoise peer-checked:after:translate-x-[14px] peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-bf-turquoise motion-reduce:transition-none motion-reduce:after:transition-none"
      />
      {t('fx.comp.toggle')}
    </label>
  );
}

/**
 * «Otras competiciones» as Free/Tribuna meet it: the same switch, off and locked, with a lock and
 * «Premium». It never turns on; tapping it opens the short line below (see LockedCompetitionsLine).
 */
export function LockedCompetitionsToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const t = useT();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={false}
      aria-expanded={open}
      aria-controls="locked-competitions-line"
      data-testid="locked-competitions-toggle"
      onClick={onToggle}
      className="inline-flex select-none items-center gap-2 text-xs font-normal text-bf-gray focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bf-turquoise"
    >
      <span aria-hidden="true" className="relative h-5 w-[34px] flex-none rounded-full bg-white/10 after:absolute after:left-[3px] after:top-[3px] after:h-[14px] after:w-[14px] after:rounded-full after:bg-bf-gray/60" />
      <span aria-hidden="true">🔒</span>
      {t('fx.comp.toggle')}
      <span className="rounded-full border border-white/15 px-2 py-px text-[10px] font-normal tracking-wide text-bf-gray">
        {LOCKED_BADGE}
      </span>
    </button>
  );
}

/** The line a tap on the locked switch opens: what Premium shows, and the way to get it. */
export function LockedCompetitionsLine() {
  const { locale } = useLocale();
  return (
    <p
      id="locked-competitions-line"
      role="status"
      data-testid="locked-competitions-line"
      className="text-[12.5px] font-normal text-bf-gray"
    >
      {lockedLine(locale)}{' '}
      <Link href="/subscribe" className="text-bf-turquoise hover:underline">
        {lockedLink(locale)}
      </Link>
    </p>
  );
}

/** One line: the colour of each competition, and what a gold number means. */
export function TimelineLegend() {
  const t = useT();
  const { locale } = useLocale();
  return (
    <p
      data-testid="timeline-legend"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] font-normal text-bf-gray"
    >
      {competitionLegend(locale).map((entry) => (
        <span key={entry.label} className="inline-flex items-center gap-1.5">
          <i
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-[2px] border-[1.5px] not-italic"
            style={{ borderColor: entry.color }}
          />
          {entry.label}
        </span>
      ))}
      <span className={GOLD}>{t('fx.comp.restLegend')}</span>
    </p>
  );
}

/**
 * The compact grid's mark for the match(es) of other competitions that precede a gameweek: a
 * 12 px strip before the column, one rounded vertical bar per match in its competition's colour
 * (two stack, and shrink to fit the 24 px row), and a 4 px gold dot under them when the
 * rest to the Premier League match is short (the rotation notice). The whole strip is one button:
 * tapping or focusing it opens the detail line. The Premier League cell itself is untouched.
 */
export function GutterMarks({
  team,
  gutter,
  selected,
  onPick,
}: {
  team: string;
  gutter: CompactGutter;
  selected: boolean;
  onPick: () => void;
}) {
  const { locale } = useLocale();
  const strip = 'relative h-[24px] w-[12px] flex-none';
  if (gutter.matches.length === 0) return <span aria-hidden="true" className={strip} />;
  const barHeight = gutter.matches.length === 1 ? 16 : gutter.matches.length === 2 ? 10 : 6;
  return (
    <button
      type="button"
      data-testid="compact-gutter"
      aria-label={gutterSentence(team, gutter, locale)}
      aria-pressed={selected}
      onClick={onPick}
      onFocus={onPick}
      className={`${strip} flex flex-col items-center justify-center gap-[2px] rounded-[3px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-bf-turquoise`}
    >
      {gutter.matches.map((m, i) => (
        <span
          key={`${m.kickoff}-${i}`}
          data-testid="compact-bar"
          aria-hidden="true"
          className="block w-[6px] rounded-[2px]"
          style={{ height: barHeight, backgroundColor: competitionColor(m.competition) }}
        />
      ))}
      {gutter.rotation && (
        <span
          data-testid="compact-rotation-dot"
          aria-hidden="true"
          className="absolute bottom-[-3px] left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-bf-gold"
        />
      )}
    </button>
  );
}

/** The compact grid's legend, in one line: each competition's colour, and what the gold dot means. */
export function CompactLegend() {
  const t = useT();
  const { locale } = useLocale();
  return (
    <p
      data-testid="compact-legend"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] font-normal text-bf-gray"
    >
      {competitionLegend(locale).map((entry) => (
        <span key={entry.label} className="inline-flex items-center gap-1.5">
          <i
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-[2px] not-italic"
            style={{ backgroundColor: entry.color }}
          />
          {entry.label}
        </span>
      ))}
      <span className={GOLD}>{t('fx.comp.restLegendDot')}</span>
    </p>
  );
}
