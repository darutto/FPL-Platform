'use client';

/**
 * SwipePager — 3-screen horizontal pager (U2, Stitch Hi-Fi).
 *
 * Screens: 0 = Squad · 1 = Chat (home) · 2 = Commands.
 * Navigation: pointer drag/swipe (with vertical-scroll axis lock and edge
 * resistance), top dot pager, edge ribbon hints, and ←/→ arrow keys when
 * focus is not in a form field.
 *
 * Ported from the design prototype; drag state lives in a ref so pointer
 * moves don't re-render until the offset actually changes.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

const LABELS = ['Squad', 'Chat', 'Commands'] as const;
const SWIPE_THRESHOLD = 60; // px past which we commit to next/prev screen
const LOCK_THRESHOLD = 8; // px before we decide horizontal vs vertical

interface DragState {
  active: boolean;
  startX: number;
  startY: number;
  dx: number;
  locked: 'h' | 'v' | null;
}

interface Props {
  screen: number;
  onScreenChange: (screen: number) => void;
  children: ReactNode; // exactly three PagerScreen children
}

export function PagerScreen({
  children,
  maxWidth,
}: {
  children: ReactNode;
  /** Optional content width cap in px (design: squad 460, commands 520). */
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

export default function SwipePager({ screen, onScreenChange, children }: Props) {
  const dragRef = useRef<DragState>({ active: false, startX: 0, startY: 0, dx: 0, locked: null });
  const [dragDx, setDragDx] = useState(0);

  const goTo = useCallback(
    (i: number) => onScreenChange(Math.max(0, Math.min(2, i))),
    [onScreenChange],
  );

  // Keyboard nav — ←/→ between screens, unless typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); goTo(screen - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); goTo(screen + 1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [screen, goTo]);

  const onPointerDown = (e: React.PointerEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'BUTTON' || tag === 'SELECT' || tag === 'A') return;
    if ((e.target as HTMLElement).closest('[data-no-swipe]')) return;
    dragRef.current = { active: true, startX: e.clientX, startY: e.clientY, dx: 0, locked: null };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d.active) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    // Axis lock: if vertical wins early, abandon the swipe so content scrolls.
    if (d.locked === null) {
      if (Math.abs(dx) < LOCK_THRESHOLD && Math.abs(dy) < LOCK_THRESHOLD) return;
      d.locked = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
      if (d.locked === 'v') { d.active = false; return; }
    }
    // Resistance at the outer edges.
    let clamped = dx;
    if ((screen === 0 && dx > 0) || (screen === 2 && dx < 0)) clamped = dx * 0.25;
    d.dx = clamped;
    setDragDx(clamped);
  };

  const endDrag = () => {
    const d = dragRef.current;
    if (!d.active) { setDragDx(0); return; }
    d.active = false;
    if (d.locked === 'h' && Math.abs(d.dx) > SWIPE_THRESHOLD) {
      goTo(screen + (d.dx < 0 ? 1 : -1));
    }
    setDragDx(0);
  };

  const isDragging = dragRef.current.active && dragRef.current.locked === 'h';

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden relative">
      {/* Dot pager */}
      <div className="flex items-center justify-center gap-2 py-1.5 flex-shrink-0">
        {LABELS.map((lbl, i) => (
          <button
            key={lbl}
            onClick={() => goTo(i)}
            data-no-swipe
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

      {/* Swipe surface */}
      <div
        className={`flex-1 min-h-0 overflow-hidden relative touch-pan-y ${
          isDragging ? 'cursor-grabbing select-none' : 'cursor-grab'
        }`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={endDrag}
      >
        {/* Sliding track */}
        <div
          className="flex w-full h-full will-change-transform"
          style={{
            transform: `translateX(calc(${-screen * 100}% + ${dragDx}px))`,
            transition: isDragging ? 'none' : 'transform .35s cubic-bezier(.32,.72,.36,1)',
          }}
        >
          {children}
        </div>

        {/* Edge ribbon hints */}
        {screen === 1 && (
          <>
            <EdgeHint side="left" label="Squad" onClick={() => goTo(0)} accentClass="text-bf-turquoise" />
            <EdgeHint side="right" label="Commands" onClick={() => goTo(2)} accentClass="text-bf-coral" />
          </>
        )}
        {screen === 0 && (
          <EdgeHint side="right" label="Chat" onClick={() => goTo(1)} accentClass="text-bf-turquoise" />
        )}
        {screen === 2 && (
          <EdgeHint side="left" label="Chat" onClick={() => goTo(1)} accentClass="text-bf-coral" />
        )}
      </div>
    </div>
  );
}

function EdgeHint({
  side,
  label,
  onClick,
  accentClass,
}: {
  side: 'left' | 'right';
  label: string;
  onClick: () => void;
  accentClass: string;
}) {
  return (
    <button
      onClick={onClick}
      data-no-swipe
      title={`Ir a ${label}`}
      className={`absolute top-1/2 -translate-y-1/2 z-10 px-1 py-3.5 rounded-lg border border-white/10 bg-bf-surface/85 backdrop-blur flex flex-col items-center gap-1.5 opacity-80 hover:opacity-100 transition-opacity ${accentClass} ${
        side === 'left' ? 'left-2' : 'right-2'
      }`}
    >
      <svg aria-hidden="true" width="10" height="12" viewBox="0 0 10 12" fill="none">
        <path
          d={side === 'left' ? 'M6.5 2L2.5 6l4 4' : 'M3.5 2l4 4-4 4'}
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span
        className="text-[9px] font-extrabold tracking-[0.15em] uppercase [writing-mode:vertical-rl]"
        style={side === 'left' ? { transform: 'rotate(180deg)' } : undefined}
      >
        {label}
      </span>
    </button>
  );
}
