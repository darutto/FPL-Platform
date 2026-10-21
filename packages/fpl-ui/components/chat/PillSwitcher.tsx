'use client';

/**
 * PillSwitcher — the brand's Spotify-style segmented pill (Music / Following).
 *
 * A rounded track holding N segments; the active one is a filled brand pill
 * with ink text, the rest are muted gray and brighten on hover. Used by the
 * workspace Chat / Calendar toggle and the (flagged-off) FPL / Mundial switch.
 */
export interface PillItem<K extends string> {
  key: K;
  label: string;
  /** Tailwind classes for this segment's filled state. Defaults to coral. */
  activeClass?: string;
}

interface Props<K extends string> {
  items: readonly PillItem<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
  /** Expose tab semantics (section nav) instead of pressed buttons (toggle). */
  tabs?: boolean;
  className?: string;
}

export default function PillSwitcher<K extends string>({ items, value, onChange, label, tabs = false, className = '' }: Props<K>) {
  return (
    <div
      role={tabs ? 'tablist' : 'group'}
      aria-label={label}
      className={`flex items-center gap-0.5 p-0.5 rounded-full bg-black/30 border border-white/10 ${className}`}
    >
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            type="button"
            {...(tabs ? { role: 'tab', 'aria-selected': active } : { 'aria-pressed': active })}
            onClick={() => { if (!active) onChange(item.key); }}
            className={`pill-segment px-3 py-1 rounded-full text-[12px] font-extrabold leading-none transition-colors ${
              active ? item.activeClass ?? 'bg-bf-coral text-bf-ink' : 'text-bf-gray hover:text-bf-text'
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
