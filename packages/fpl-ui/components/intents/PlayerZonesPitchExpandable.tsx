/**
 * PlayerZonesPitchExpandable — the «Zonas» mini-pitch as an accessible
 * button that opens an enlarged view (i152).
 *
 * The enlarged view is the SAME drawing (PlayerZonesPitch → PitchGeometry) at
 * a larger scale, with the same zones, colours and legend. It carries ONLY
 * the player's data: no rival picker and no rival zones (the crosses are
 * already described in the text and the rows).
 *
 * Dialog behaviour: closes with the X, Esc or a tap outside the panel; focus
 * moves inside and is trapped there, then returns to the mini-pitch button on
 * close; the page behind does not scroll while it is open. Desktop: a window
 * over the chat; ≤ 480 px: full screen.
 */
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { PlayerZonalFixture, PlayerZonalZone } from '@/lib/types';
import { sharePercent, zoneChipLabel } from '@/lib/defensive-zones';
import PlayerZonesPitch, { PITCH_LEGEND } from './PlayerZonesPitch';

interface Props {
  playerName: string;
  zones: PlayerZonalZone[];
  fixtures: PlayerZonalFixture[];
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export default function PlayerZonesPitchExpandable({ playerName, zones, fixtures }: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    // Return focus to the control that opened the dialog.
    triggerRef.current?.focus();
  }, []);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        data-testid="player-zones-pitch-button"
        aria-label={`Ampliar zonas de ${playerName}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="block w-full cursor-zoom-in rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bf-turquoise"
      >
        <PlayerZonesPitch zones={zones} fixtures={fixtures} />
      </button>
      {open && (
        <PitchDialog playerName={playerName} zones={zones} fixtures={fixtures} onClose={close} />
      )}
    </>
  );
}

function PitchDialog({
  playerName,
  zones,
  fixtures,
  onClose,
}: Props & { onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const anyFavorable = fixtures.some((f) => f.status === 'favorable');

  // Lock background scroll while open; restore whatever was there before.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  // Move focus into the dialog on open.
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== 'Tab') return;
    // Focus trap: keep Tab inside the panel.
    const nodes = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (nodes.length === 0) {
      e.preventDefault();
      return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    const active = document.activeElement;
    const inside = panelRef.current?.contains(active) ?? false;
    if (e.shiftKey && (active === first || !inside)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !inside)) {
      e.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      data-testid="player-zones-dialog-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 max-[480px]:p-0"
      onMouseDown={(e) => {
        // A press on the backdrop itself (not inside the panel) closes. The
        // default is prevented so the browser does not move focus to <body>
        // after we have returned it to the mini-pitch button.
        if (e.target === e.currentTarget) {
          e.preventDefault();
          onClose();
        }
      }}
      onKeyDown={onKeyDown}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="player-zones-dialog"
        className="relative flex max-h-full w-full max-w-[640px] flex-col gap-3 overflow-y-auto rounded-2xl border border-white/10 bg-[#15141c] p-4 shadow-2xl max-[480px]:h-full max-[480px]:max-w-none max-[480px]:rounded-none"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-sm font-extrabold text-white">
            Zonas de {playerName}
          </h2>
          <button
            ref={closeRef}
            type="button"
            data-testid="player-zones-dialog-close"
            aria-label="Cerrar"
            onClick={onClose}
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-white/15 text-lg leading-none text-bf-gray hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bf-turquoise"
          >
            ×
          </button>
        </div>

        <div className="mx-auto w-full max-w-[460px]">
          <PlayerZonesPitch zones={zones} fixtures={fixtures} variant="large" />
        </div>

        <ul className="flex flex-wrap gap-1.5" data-testid="player-zones-dialog-list">
          {zones.map((z) => (
            <li
              key={z.zone}
              className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs font-bold text-white"
            >
              {zoneChipLabel(z.zone)} · {sharePercent(z.share)}% de su xG sin penalti
            </li>
          ))}
        </ul>

        {anyFavorable && (
          <p data-testid="player-zones-dialog-legend" className="text-xs leading-snug text-bf-gray">
            {PITCH_LEGEND}
          </p>
        )}
      </div>
    </div>,
    document.body,
  );
}
