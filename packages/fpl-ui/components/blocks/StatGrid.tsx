/**
 * StatGrid — a row of small labelled figures.
 *
 * Shared card block: props are data, no question logic. A block draws the strings it is given; it never
 * computes a figure, picks wording or looks at which question was asked.
 */

export interface GridStat {
  label: string;
  value: string;
  /** A secondary figure: smaller and gray. */
  muted?: boolean;
}

const GRID = { 3: 'grid grid-cols-3 gap-2.5', 5: 'grid grid-cols-5 gap-2' } as const;

export default function StatGrid({ columns, stats }: { columns: keyof typeof GRID; stats: GridStat[] }) {
  return (
    <div className={GRID[columns]}>
      {stats.map(({ label, value, muted = false }) => (
        <div key={label} className="min-w-0">
          <div
            className={`truncate font-display tracking-tighter leading-none ${
              muted ? 'text-sm text-bf-gray' : 'text-base text-white'
            }`}
          >
            {value}
          </div>
          <div className="text-[9px] font-bold uppercase tracking-wide text-bf-gray">{label}</div>
        </div>
      ))}
    </div>
  );
}
