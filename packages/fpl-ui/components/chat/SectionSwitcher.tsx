'use client';

/**
 * SectionSwitcher — FPL (`/chat`) ↔ Mundial / World Cup (`/wc/chat`) pill.
 *
 * Hidden while SHOW_SECTION_SWITCHER is off (the World Cup is over; see
 * lib/features.ts). The active section is derived from the pathname
 * (anything under `/wc` is the World Cup), so it stays in sync however the
 * user landed on the page. Visuals live in the shared PillSwitcher.
 */
import { usePathname, useRouter } from 'next/navigation';
import PillSwitcher, { type PillItem } from './PillSwitcher';

type SectionKey = 'fpl' | 'wc';

const SECTIONS: readonly PillItem<SectionKey>[] = [
  { key: 'fpl', label: 'FPL', activeClass: 'bg-bf-coral text-bf-ink' },
  { key: 'wc', label: 'Mundial', activeClass: 'bg-bf-turquoise text-bf-ink' },
];
const HREFS: Record<SectionKey, string> = { fpl: '/chat', wc: '/wc/chat' };

export default function SectionSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const active: SectionKey = pathname?.startsWith('/wc') ? 'wc' : 'fpl';
  return <PillSwitcher tabs label="Sección" items={SECTIONS} value={active} onChange={(key) => router.push(HREFS[key])} />;
}
