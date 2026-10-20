'use client';

/**
 * SwipePager — N-screen horizontal pager (U2, Stitch Hi-Fi).
 *
 * Screen labels/count are driven by the `labels` prop (FPL uses
 * Calendario · Squad · Chat · Commands). Navigation: pointer drag/swipe (with
 * vertical-scroll axis lock and edge resistance), top dot pager, edge ribbon
 * hints, and ←/→ arrow keys when focus is not in a form field.
 *
 * Ported from the design prototype; drag state lives in a ref so pointer
 * moves don't re-render until the offset actually changes.
 */
import { Children, useCallback, useEffect, useRef, useState, type ReactNode, type CSSProperties } from 'react';
import { useWideWorkspace } from './useWideWorkspace';

const SWIPE_THRESHOLD = 60; // px past which we commit to next/prev screen
const LOCK_THRESHOLD = 8; // px before we decide horizontal vs vertical

interface DragState {
  active: boolean;
  pointerId: number;
  startX: number;
  startY: number;
  dx: number;
  locked: 'h' | 'v' | null;
}

// A scrollable child owns its entire gesture, including at either scroll edge.
// Do not transfer that gesture to screen navigation when it runs out of room.
function ownsGesture(target: Element, surface: Element): boolean {
  if (target.closest('[data-no-swipe], table, button, input, textarea, select, a, [contenteditable="true"], [role="dialog"]')) return true;
  for (let el: Element | null = target; el && el !== surface; el = el.parentElement) {
    const style = window.getComputedStyle(el);
    if (/auto|scroll/.test(style.overflowX) && el.scrollWidth > el.clientWidth) return true;
  }
  return false;
}

interface Props {
  screen: number;
  onScreenChange: (screen: number) => void;
  /** One label per screen; length drives the screen count. */
  labels: readonly string[];
  children: ReactNode; // one PagerScreen child per label
  /** FPL only: same four mounted screens become a desktop workspace. */
  workspace?: boolean;
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
    <div className="pager-screen h-full w-full flex-shrink-0 basis-full min-w-0 p-2 box-border flex justify-center">
      <div className="pager-content w-full h-full min-w-0" style={maxWidth ? { maxWidth } : undefined}>
        {children}
      </div>
    </div>
  );
}

export default function SwipePager({ screen, onScreenChange, labels, children, workspace = false }: Props) {
  const panels = useWideWorkspace(workspace);
  const lastCenter = useRef(2);
  if (screen === 0 || screen === 2) lastCenter.current = screen;
  const center = lastCenter.current;
  const dragRef = useRef<DragState>({ active: false, pointerId: -1, startX: 0, startY: 0, dx: 0, locked: null });
  const surfaceRef = useRef<HTMLDivElement>(null);
  const pointersRef = useRef(new Set<number>());
  const [dragDx, setDragDx] = useState(0);
  const lastScreen = labels.length - 1;

  const goTo = useCallback(
    (i: number) => onScreenChange(Math.max(0, Math.min(lastScreen, i))),
    [onScreenChange, lastScreen],
  );

  const cancelDrag = useCallback(() => {
    dragRef.current.active = false;
    dragRef.current.dx = 0;
    setDragDx(0);
  }, []);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;
    const down = (e: PointerEvent) => {
      pointersRef.current.add(e.pointerId);
      if (pointersRef.current.size > 1) cancelDrag();
    };
    const release = (e: PointerEvent) => {
      pointersRef.current.delete(e.pointerId);
      // React's surface pointerup has already committed, if eligible. Releases
      // outside the surface and all cancellations must only reset the offset.
      if (dragRef.current.pointerId === e.pointerId) cancelDrag();
    };
    const touchStart = (e: TouchEvent) => {
      if (e.touches.length > 1) cancelDrag();
    };
    const touchMove = (e: TouchEvent) => {
      const d = dragRef.current;
      if (e.touches.length !== 1 || (window.visualViewport?.scale ?? 1) > 1) {
        cancelDrag();
        return;
      }
      if (!d.active) return;
      const dx = e.touches[0].clientX - d.startX;
      const dy = e.touches[0].clientY - d.startY;
      // Keep native pan and pinch available by default. Only a deliberate
      // horizontal pager drag suppresses native panning. This must be a native
      // non-passive listener; React's touchmove listener is passive.
      if (d.locked === null && Math.max(Math.abs(dx), Math.abs(dy)) >= LOCK_THRESHOLD) {
        d.locked = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
      }
      if (d.locked === 'v') cancelDrag();
      else if (d.locked === 'h' && e.cancelable) e.preventDefault();
    };
    const blur = () => { pointersRef.current.clear(); cancelDrag(); };
    document.addEventListener('pointerdown', down, true);
    document.addEventListener('pointerup', release);
    document.addEventListener('pointercancel', release);
    surface.addEventListener('touchstart', touchStart, { passive: true });
    surface.addEventListener('touchmove', touchMove, { passive: false });
    window.addEventListener('blur', blur);
    return () => {
      document.removeEventListener('pointerdown', down, true);
      document.removeEventListener('pointerup', release);
      document.removeEventListener('pointercancel', release);
      surface.removeEventListener('touchstart', touchStart);
      surface.removeEventListener('touchmove', touchMove);
      window.removeEventListener('blur', blur);
    };
  }, [cancelDrag]);

  useEffect(() => { cancelDrag(); }, [screen, cancelDrag]);
  useEffect(() => { cancelDrag(); }, [panels.wide, cancelDrag]);

  // Keyboard nav — ←/→ between screens, unless typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (panels.wide) return;
      const target = e.target as HTMLElement;
      if (e.defaultPrevented || target.isContentEditable || document.fullscreenElement) return;
      if (target instanceof Element && !target.closest('[data-pager-navigation]') && surfaceRef.current && ownsGesture(target, surfaceRef.current)) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); goTo(screen - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); goTo(screen + 1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [screen, goTo, panels.wide]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (panels.wide) return;
    if (pointersRef.current.size > 1 || e.isPrimary === false || e.button !== 0) return;
    if ((window.visualViewport?.scale ?? 1) > 1 || document.fullscreenElement) return;
    if (ownsGesture(e.target as Element, e.currentTarget)) return;
    dragRef.current = { active: true, pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, dx: 0, locked: null };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d.active || e.pointerId !== d.pointerId) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    // Axis lock: if vertical wins early, abandon the swipe so content scrolls.
    if (d.locked === null) {
      if (Math.abs(dx) < LOCK_THRESHOLD && Math.abs(dy) < LOCK_THRESHOLD) return;
      d.locked = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
      if (d.locked === 'v') { cancelDrag(); return; }
    }
    // Resistance at the outer edges.
    let clamped = dx;
    if ((screen === 0 && dx > 0) || (screen === lastScreen && dx < 0)) clamped = dx * 0.25;
    d.dx = clamped;
    setDragDx(clamped);
  };

  const endDrag = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d.active || e.pointerId !== d.pointerId) return;
    d.active = false;
    if (d.locked === 'h' && Math.abs(d.dx) > SWIPE_THRESHOLD) {
      goTo(screen + (d.dx < 0 ? 1 : -1));
    }
    setDragDx(0);
  };

  const isDragging = dragRef.current.active && dragRef.current.locked === 'h';

  return (
    <div className={`flex-1 flex flex-col min-h-0 overflow-hidden relative ${panels.wide ? 'wide-workspace' : ''}`} data-workspace={panels.wide ? 'wide' : 'pager'}>
      {panels.wide && (
        <div className="workspace-toolbar" aria-label="Workspace navigation">
          <div className="flex items-center gap-2">
            {!panels.squad && <button type="button" onClick={() => panels.toggle('squad')}>Show squad</button>}
            {[2, 0].map(index => <button key={index} type="button" aria-pressed={center === index} onClick={() => goTo(index)}>{index === 2 ? 'Chat' : 'Calendar'}</button>)}
          </div>
          {!panels.commands && <button type="button" onClick={() => panels.toggle('commands')}>Show commands</button>}
        </div>
      )}
      {/* Dot pager */}
      <div className={`${panels.wide ? 'hidden' : 'flex'} items-center justify-center gap-2 py-1.5 flex-shrink-0`}>
        {labels.map((lbl, i) => (
          <button
            key={lbl}
            onClick={() => goTo(i)}
            data-no-swipe
            data-pager-navigation
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
        ref={surfaceRef}
        className={`flex-1 min-h-0 overflow-hidden relative touch-auto ${
          panels.wide ? '' : isDragging ? 'cursor-grabbing select-none' : 'cursor-grab'
        }`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={cancelDrag}
        onTouchCancel={cancelDrag}
        onPointerLeave={cancelDrag}
        onLostPointerCapture={cancelDrag}
      >
        {/* Sliding track */}
        <div
          className={panels.wide ? 'workspace-grid' : 'flex w-full h-full will-change-transform'}
          style={panels.wide ? {
            '--squad-column': panels.squad ? 'var(--squad-width)' : '0px',
            '--commands-column': panels.commands ? 'var(--commands-width)' : '0px',
          } as CSSProperties : {
            transform: `translateX(calc(${-screen * 100}% + ${dragDx}px))`,
            transition: isDragging ? 'none' : 'transform .35s cubic-bezier(.32,.72,.36,1)',
          }}
        >
          {workspace ? Children.map(children, (child, index) => {
            const side = index === 1 ? 'squad' : index === 3 ? 'commands' : null;
            const hidden = panels.wide && (side ? !panels[side] : center !== index);
            return <div className={`workspace-slot ${side ? 'workspace-side' : 'workspace-center'}`} data-panel={['calendar', 'squad', 'chat', 'commands'][index]} data-collapsed={side && hidden ? 'true' : undefined} aria-hidden={hidden || undefined} inert={hidden || undefined} style={hidden && !side ? { visibility: 'hidden', pointerEvents: 'none' } : undefined}>
              {side && <div className="workspace-panel-heading"><span>{side === 'squad' ? 'Squad' : 'Commands'}</span><button type="button" aria-label={`Collapse ${side}`} onClick={() => panels.toggle(side)}>Collapse</button></div>}
              {child}
            </div>;
          }) : children}
        </div>

        {/* Desktop-only hints: on mobile these overlap content; tabs and swipe remain available. */}
        {!panels.wide && screen > 0 && (
          <EdgeHint
            side="left"
            label={labels[screen - 1]}
            onClick={() => goTo(screen - 1)}
            accentClass="text-bf-turquoise"
          />
        )}
        {!panels.wide && screen < lastScreen && (
          <EdgeHint
            side="right"
            label={labels[screen + 1]}
            onClick={() => goTo(screen + 1)}
            accentClass="text-bf-coral"
          />
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
      data-pager-navigation
      title={`Ir a ${label}`}
      className={`absolute top-1/2 -translate-y-1/2 z-10 px-1 py-3.5 rounded-lg border border-white/10 bg-bf-surface/85 backdrop-blur hidden md:flex flex-col items-center gap-1.5 opacity-80 hover:opacity-100 transition-opacity ${accentClass} ${
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
