'use client';

/**
 * DevTierSwitcher — a floating dropdown (dev builds only) to impersonate any
 * quota tier locally. Writes the `dev_tier` cookie and reloads so both the
 * middleware (backend x-user-tier) and the WC shell (toggle) pick it up.
 *
 * Renders nothing in production (NODE_ENV guard) and is never bundled into the
 * real funnel — purely a developer testing aid.
 */
import { useEffect, useState } from 'react';
import { QUOTA_BUCKETS, type QuotaBucket } from '@/lib/tiers';
import { devTierEnabled, readDevTier, setDevTier } from '@/lib/dev-tier';

const OPTIONS: { value: QuotaBucket; label: string }[] = [
  { value: 'free', label: 'free · 5/día · sin web' },
  { value: 'patreon_basic', label: '$5 basic · 30/día · sin web' },
  { value: 'patreon_plus', label: '$10 plus · 60/día · web' },
  { value: 'patreon_premium', label: '$15+ premium · 150/día · web' },
];

export default function DevTierSwitcher() {
  // Read after mount to avoid an SSR/client hydration mismatch on the cookie.
  const [current, setCurrent] = useState<QuotaBucket | ''>('');
  useEffect(() => {
    setCurrent(readDevTier() ?? '');
  }, []);

  if (!devTierEnabled()) return null;

  const onChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    setDevTier(value === '' ? undefined : (value as QuotaBucket));
    // Reload so middleware re-injects x-user-tier and the toggle re-reads it.
    window.location.reload();
  };

  return (
    <div className="fixed bottom-2 left-2 z-50 flex items-center gap-1.5 rounded-md border border-bf-coral/40 bg-bf-bg/95 px-2 py-1 text-[10px] shadow-card">
      <span className="font-bold uppercase tracking-wider text-bf-coral">dev tier</span>
      <select
        value={current}
        onChange={onChange}
        aria-label="Impersonate quota tier (dev only)"
        className="rounded bg-bf-card px-1 py-0.5 text-[10px] text-bf-text outline-none"
      >
        <option value="">(real tier)</option>
        {OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {current !== '' && QUOTA_BUCKETS[current].webSearch && (
        <span className="text-bf-cyan">web ✓</span>
      )}
    </div>
  );
}
