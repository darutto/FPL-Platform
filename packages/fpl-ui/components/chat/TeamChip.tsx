'use client';

/**
 * The club offered under a player answer when the typed name is also a club's. A tap opens that club's card
 * through POST /card: no chat message, no model. Busy and failed states stay on the chip.
 */
import { useState } from 'react';
import type { TeamChipMeta } from '@/lib/types';
import { useT } from '@/lib/i18n/LocaleProvider';

export default function TeamChip({ chip, onOpen }: { chip: TeamChipMeta; onOpen: (chip: TeamChipMeta) => Promise<void> }) {
  const t = useT();
  const [state, setState] = useState<'idle' | 'busy' | 'failed'>('idle');

  const open = async () => {
    setState('busy');
    try {
      await onOpen(chip);
      setState('idle');
    } catch {
      setState('failed');
    }
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={open}
        disabled={state === 'busy'}
        aria-busy={state === 'busy'}
        className="inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full bg-white/[0.09] px-3 text-[13px] font-semibold text-bf-text transition-colors hover:bg-white/[0.15] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bf-turquoise/60 disabled:opacity-50 sm:min-h-[36px]"
      >
        <span>{t('tc.chip', { team: chip.name })}</span>
        <span aria-hidden="true" className="font-bold text-bf-gray">›</span>
      </button>
      {state === 'failed' && (
        <span role="alert" className="text-[11px] text-bf-coral">
          {t('tc.chipFailed')}
        </span>
      )}
    </div>
  );
}
