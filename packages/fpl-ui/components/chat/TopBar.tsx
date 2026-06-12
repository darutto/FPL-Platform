'use client';

/**
 * TopBar — brand bar above the swipe pager (U2, Stitch Hi-Fi).
 *
 * Left: Bendito Fantasy logo + app title. Right: connected team name,
 * current GW pill (when known), and the high-contrast accessibility switch.
 *
 * Contrast switch: toggles html[data-contrast="high"], persisted in
 * localStorage. Default (off) keeps the brand-faithful white-on-coral;
 * on swaps coral surfaces to dark ink text via the `hc:` Tailwind variant.
 */
import { useEffect, useState } from 'react';

const CONTRAST_LS_KEY = 'bf_contrast';

interface Props {
  teamName?: string | null;
  gw?: number | null;
}

export default function TopBar({ teamName, gw }: Props) {
  const [highContrast, setHighContrast] = useState(false);

  // Restore persisted preference on mount.
  useEffect(() => {
    try {
      const stored = localStorage.getItem(CONTRAST_LS_KEY);
      if (stored === 'high') {
        setHighContrast(true);
        document.documentElement.dataset.contrast = 'high';
      }
    } catch { /* localStorage unavailable */ }
  }, []);

  const toggleContrast = () => {
    setHighContrast((prev) => {
      const next = !prev;
      document.documentElement.dataset.contrast = next ? 'high' : '';
      try {
        localStorage.setItem(CONTRAST_LS_KEY, next ? 'high' : 'default');
      } catch { /* ignore */ }
      return next;
    });
  };

  return (
    <div className="h-12 flex items-center gap-2.5 px-3.5 border-b border-white/10 bg-black/25 flex-shrink-0">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/logo-icon.png" alt="Bendito Fantasy" className="h-7 w-7 rounded flex-shrink-0" />
      <div className="flex flex-col leading-none">
        <span className="text-[13px] font-extrabold text-white">FPL Asistente</span>
        <span className="text-[10px] text-bf-gray mt-0.5">Bendito Fantasy</span>
      </div>

      <div className="ml-auto flex items-center gap-2.5">
        {teamName && (
          <div className="text-right leading-none hidden sm:block">
            <span className="block text-[9px] font-bold text-bf-text/40 uppercase tracking-widest">Team</span>
            <span className="block text-[11px] font-bold text-bf-turquoise mt-0.5 max-w-[160px] truncate">
              {teamName}
            </span>
          </div>
        )}
        {gw != null && (
          <span className="px-2.5 py-1 rounded-full bg-bf-coral/15 border border-bf-coral/40 text-[11px] font-bold text-bf-coral">
            GW{gw}
          </span>
        )}
        <button
          onClick={toggleContrast}
          aria-pressed={highContrast}
          title="Contraste alto (accesibilidad)"
          className={`px-2 py-1 rounded-md border text-[11px] font-extrabold transition-colors ${
            highContrast
              ? 'border-bf-turquoise/60 text-bf-turquoise bg-bf-turquoise/10'
              : 'border-white/10 text-bf-gray hover:text-bf-text hover:border-white/20'
          }`}
        >
          Aa
        </button>
      </div>
    </div>
  );
}
