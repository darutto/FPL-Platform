/**
 * Multi-competition furniture for the /fixtures board: the "Otras competiciones"
 * switch, the legends, and the compact grid's corner marks.
 * Rendered only when the backend returned a payload; otherwise nothing at all.
 * Titles here never contain "FDR " (the board's tests read FDR titles to see
 * which difficulty is on screen).
 */
import Link from 'next/link';
import {
  COMPETITION_LEGEND,
  competitionName,
  LOCKED_BADGE,
  LOCKED_LINE,
  LOCKED_LINK,
  rotationText,
  type TeamExtras,
} from '@/lib/fixture-competitions';

const GOLD = 'text-bf-gold';

/** «Otras competiciones»: shows or hides the whole layer. The board remembers the choice. */
export function OtherCompetitionsToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
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
      Otras competiciones
    </label>
  );
}

/**
 * «Otras competiciones» as Free/Tribuna meet it: the same switch, off and locked, with a lock and
 * «Premium». It never turns on; tapping it opens the short line below (see LockedCompetitionsLine).
 */
export function LockedCompetitionsToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
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
      Otras competiciones
      <span className="rounded-full border border-white/15 px-2 py-px text-[10px] font-normal tracking-wide text-bf-gray">
        {LOCKED_BADGE}
      </span>
    </button>
  );
}

/** The line a tap on the locked switch opens: what Premium shows, and the way to get it. */
export function LockedCompetitionsLine() {
  return (
    <p
      id="locked-competitions-line"
      role="status"
      data-testid="locked-competitions-line"
      className="text-[12.5px] font-normal text-bf-gray"
    >
      {LOCKED_LINE}{' '}
      <Link href="/subscribe" className="text-bf-turquoise hover:underline">
        {LOCKED_LINK}
      </Link>
    </p>
  );
}

/** One line: the colour of each competition, and what a gold number means. */
export function TimelineLegend() {
  return (
    <p
      data-testid="timeline-legend"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] font-normal text-bf-gray"
    >
      {COMPETITION_LEGEND.map((entry) => (
        <span key={entry.label} className="inline-flex items-center gap-1.5">
          <i
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-[2px] border-[1.5px] not-italic"
            style={{ borderColor: entry.color }}
          />
          {entry.label}
        </span>
      ))}
      <span className={GOLD}>3d dorado = descanso corto tras Europa o copa</span>
    </p>
  );
}

/** Inside a compact-grid cell: tiny corner chip(s). Presentation sizes scale with the viewport. */
export function CompactChip({
  extras,
  gameweek,
  presentation,
}: {
  extras: TeamExtras;
  gameweek: number;
  presentation: boolean;
}) {
  const size = presentation
    ? 'text-[clamp(8px,0.9vw,14px)]'
    : 'text-[7.5px]';
  const slot = extras.byGw.get(gameweek);
  if (!slot) return null;
  const codes = Array.from(new Set(slot.matches.map((m) => m.competition))).join('+');
  return (
    <span
      data-testid="competition-extras"
      title={[
        ...slot.matches.map((m) => `${competitionName(m.competition)} · ${m.opponent}`),
        ...(slot.notice ? [rotationText(slot.notice)] : []),
      ].join(' | ')}
      className={`absolute right-0.5 top-0 flex items-center gap-0.5 ${size} font-black leading-none text-white/85`}
    >
      {codes}
      {slot.notice && (
        <span data-testid="rotation-notice" className={GOLD}>
          ↻{slot.notice.restWholeDays}d
        </span>
      )}
    </span>
  );
}

/** The compact grid's legend: what the corner marks mean. */
export function CompetitionsLegend() {
  return (
    <p data-testid="competitions-legend" className="text-[12px] font-semibold text-bf-gray">
      <b className="text-white">UCL</b> Champions · <b className="text-white">UEL</b> Europa League ·{' '}
      <b className="text-white">UECL</b> Conference · <b className="text-white">FA</b> FA Cup ·{' '}
      <b className="text-white">EFL</b> Carabao ·{' '}
      <span className={GOLD}>↻ descanso corto, posible rotación</span>
    </p>
  );
}
