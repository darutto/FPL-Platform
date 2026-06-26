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
import { UserButton } from '@clerk/nextjs';
import SectionSwitcher from './SectionSwitcher';

const CONTRAST_LS_KEY = 'bf_contrast';

interface Props {
  teamName?: string | null;
  gw?: number | null;
  /** Brand title shown next to the logo. Defaults to the FPL title. */
  title?: string;
  /** Brand subtitle shown beneath the title. Defaults to "Bendito Fantasy". */
  subtitle?: string;
}

export default function TopBar({ teamName, gw, title = 'FPL Asistente', subtitle = 'Bendito Fantasy' }: Props) {
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
      <div className="flex-col leading-none hidden md:flex">
        <span className="text-[13px] font-extrabold text-white">{title}</span>
        <span className="text-[10px] text-bf-gray mt-0.5">{subtitle}</span>
      </div>

      {/* Spotify-style FPL ↔ Mundial section switcher (shared by both shells). */}
      <div className="mx-auto">
        <SectionSwitcher />
      </div>

      <div className="flex items-center gap-2.5">
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
        <UserButton
          appearance={{
            elements: {
              avatarBox: 'h-7 w-7',
              userButtonPopoverActionButton: '!opacity-100',
              userButtonPopoverActionButtonText: '!text-[#f0f0f0] !opacity-100',
              userButtonPopoverActionButtonIcon: '!text-[#f0f0f0] !opacity-100',
              userButtonPopoverFooter: 'hidden',
            },
            variables: {
              colorPrimary: '#FF6A4D',
              colorBackground: '#211F29',
              colorForeground: '#f0f0f0',
              colorMuted: '#33303f',
              colorMutedForeground: '#cfcdd9',
              colorInput: '#1c1a26',
              colorInputForeground: '#f0f0f0',
            },
          }}
        />
      </div>
    </div>
  );
}
