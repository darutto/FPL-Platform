'use client';

/**
 * WcPager — 2-screen pager for the World Cup chat shell (Iteration 2).
 *
 * Simpler sibling of SwipePager (FPL's 3-screen Squad/Chat/Commands pager):
 * WC has no squad/fantasy-team context, so there are only Chat + Comandos
 * screens. Tab-click navigation only — no swipe gestures (can be added
 * later without touching SwipePager, which stays FPL-only).
 */
import type { ReactNode } from 'react';

const LABELS = ['Chat', 'Comandos'] as const;

interface Props {
  screen: number;
  onScreenChange: (screen: number) => void;
  children: ReactNode; // exactly two screens
}

export function WcPagerScreen({
  children,
  maxWidth,
}: {
  children: ReactNode;
  maxWidth?: number;
}) {
  return (
    <div className="h-full w-full flex-shrink-0 basis-full min-w-0 p-2 box-border flex justify-center">
      <div className="w-full h-full min-w-0" style={maxWidth ? { maxWidth } : undefined}>
        {children}
      </div>
    </div>
  );
}

export default function WcPager({ screen, onScreenChange, children }: Props) {
  const goTo = (i: number) => onScreenChange(Math.max(0, Math.min(1, i)));

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden relative">
      {/* Dot pager */}
      <div className="flex items-center justify-center gap-2 py-1.5 flex-shrink-0">
        {LABELS.map((lbl, i) => (
          <button
            key={lbl}
            onClick={() => goTo(i)}
            aria-current={screen === i ? 'true' : undefined}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest transition-colors ${
              screen === i ? 'bg-bf-coral/15 text-bf-coral' : 'text-bf-text/40 hover:text-bf-text/70'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full transition-colors ${
                screen === i ? 'bg-bf-coral' : 'bg-white/25'
              }`}
            />
            {lbl}
          </button>
        ))}
      </div>

      {/* Sliding track */}
      <div className="flex-1 min-h-0 overflow-hidden relative">
        <div
          className="flex w-full h-full will-change-transform"
          style={{
            transform: `translateX(${-screen * 100}%)`,
            transition: 'transform .35s cubic-bezier(.32,.72,.36,1)',
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
