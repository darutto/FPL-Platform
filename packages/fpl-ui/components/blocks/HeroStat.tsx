/**
 * HeroStat — a card's big number with what it is.
 *
 * Shared card block: props are data, no question logic. A block draws the strings it is given; it never
 * computes a figure, picks wording or looks at which question was asked.
 */

interface Props {
  value: string | number;
  /** `score`: the unit beside the number. `delta`, `large`, `medium`: the number alone, the caption under it. */
  size: 'score' | 'delta' | 'large' | 'medium';
  /** Unit beside a `score` number, e.g. "pts". */
  suffix?: string;
  /** What the number is. */
  caption?: string;
  /** The other figure, said under the number. */
  secondary?: { label: string; value: string } | null;
  /** Text colour of the number. */
  toneClass?: string;
  /** Pixel size of a `score` number. */
  scorePx?: number;
  /** Extra classes for the number row of a `score`. */
  className?: string;
}

/** Returns its parts without a wrapper, so the card keeps its own spacing. */
export default function HeroStat(props: Props) {
  const { value, size, suffix, caption, secondary, toneClass = '', scorePx = 30, className = '' } = props;
  if (size === 'delta') {
    return (
      <div className="leading-none">
        <span className={`font-display tracking-tighter ${toneClass}`} style={{ fontSize: 28 }}>
          {value}
        </span>
        <span className="mt-0.5 block text-[9px] font-bold uppercase tracking-wide text-bf-gray">{caption}</span>
      </div>
    );
  }
  return (
    <>
      {size === 'score' ? (
        <>
          <div
            className={`${className} flex items-baseline gap-0.5 font-display leading-none tracking-tighter ${toneClass}`}
          >
            <span style={{ fontSize: scorePx }}>{value}</span>
            <span className="text-[11px] font-bold text-bf-gray">{suffix}</span>
          </div>
          {caption != null && (
            <div className="text-[9px] font-bold uppercase tracking-wide text-bf-gray">{caption}</div>
          )}
        </>
      ) : (
        <>
          <span
            className={`block font-display ${size === 'large' ? 'text-3xl' : 'text-2xl'} leading-none tracking-tighter ${toneClass}`}
          >
            {value}
          </span>
          {caption != null && <span className="text-[11px] uppercase tracking-wide text-bf-gray">{caption}</span>}
        </>
      )}
      {secondary != null && (
        <p className="text-[12px] text-bf-gray">
          {secondary.label} <span className="font-bold text-bf-text">{secondary.value}</span>
        </p>
      )}
    </>
  );
}
