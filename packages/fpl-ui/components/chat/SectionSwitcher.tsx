'use client';

/**
 * SectionSwitcher — Spotify-style segmented pill that toggles between the
 * two app sections: FPL (`/chat`) and Mundial / World Cup (`/wc/chat`).
 *
 * Lives in the shared TopBar so both ChatShell and WcChatShell expose it.
 * The active segment is derived from the current pathname (anything under
 * `/wc` is the World Cup section; everything else is FPL), so it stays in
 * sync no matter how the user landed on the page.
 *
 * Visual: a rounded track holding two segments. The active segment is a
 * filled brand pill (coral on FPL, turquoise on Mundial) with high-contrast
 * ink text; the inactive segment is muted gray and brightens on hover —
 * mirroring Spotify's Music / Following control.
 */
import { usePathname, useRouter } from 'next/navigation';

interface Section {
  key: 'fpl' | 'wc';
  label: string;
  href: string;
  /** Tailwind classes for the active (filled) state. */
  activeClass: string;
}

const SECTIONS: Section[] = [
  {
    key: 'fpl',
    label: 'FPL',
    href: '/chat',
    activeClass: 'bg-bf-coral text-bf-ink',
  },
  {
    key: 'wc',
    label: 'Mundial',
    href: '/wc/chat',
    activeClass: 'bg-bf-turquoise text-bf-ink',
  },
];

export default function SectionSwitcher() {
  const pathname = usePathname();
  const router = useRouter();

  // Anything under /wc is the World Cup section; everything else is FPL.
  const activeKey: Section['key'] = pathname?.startsWith('/wc') ? 'wc' : 'fpl';

  return (
    <div
      role="tablist"
      aria-label="Sección"
      className="flex items-center gap-0.5 p-0.5 rounded-full bg-black/30 border border-white/10"
    >
      {SECTIONS.map((section) => {
        const isActive = section.key === activeKey;
        return (
          <button
            key={section.key}
            role="tab"
            aria-selected={isActive}
            onClick={() => {
              if (!isActive) router.push(section.href);
            }}
            className={`px-3 py-1 rounded-full text-[12px] font-extrabold leading-none transition-colors ${
              isActive
                ? section.activeClass
                : 'text-bf-gray hover:text-bf-text'
            }`}
          >
            {section.label}
          </button>
        );
      })}
    </div>
  );
}
