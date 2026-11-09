'use client';

/**
 * PlayerSignals — the row of «señales» at the foot of PlayerCard.
 *
 * Up to 3 tappable pills (Spotify-style: icon + shortest label). Each one says
 * another card has something to say about this player; a tap sends the pill's
 * `send_text` to the chat verbatim, which opens that card. The backend decides
 * which signals exist (player_signals.py, deterministic, no LLM) and writes the
 * localized label and question; this component only draws them.
 *
 * No signals, or no chat to send to (shared answer) → renders nothing: no
 * empty row, no separator, the card exactly as before.
 */
import type { ComponentType } from 'react';
import type { PlayerSignal } from '@/lib/types';
import { useChatAsk } from '@/lib/chat-ask';
import { useT } from '@/lib/i18n/LocaleProvider';

const MAX_SIGNALS = 3;

/** Crossing arrows: he starts somewhere other than his FPL line. */
function PositionIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4 flex-none fill-none stroke-current" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 3h5v5" />
      <path d="M4 20 21 3" />
      <path d="M21 16v5h-5" />
      <path d="m15 15 6 6" />
      <path d="m4 4 5 5" />
    </svg>
  );
}

/** Target: a near rival concedes in his zone. */
function ZoneIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4 flex-none fill-none stroke-current" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  );
}

const ICONS: Record<PlayerSignal['kind'], ComponentType> = {
  position: PositionIcon,
  zone: ZoneIcon,
};

export default function PlayerSignals({ signals }: { signals?: PlayerSignal[] | null }) {
  const ask = useChatAsk();
  const t = useT();
  const shown = (signals ?? []).filter((s) => s.kind in ICONS && s.label && s.send_text).slice(0, MAX_SIGNALS);
  if (ask == null || shown.length === 0) return null;

  return (
    <div role="group" aria-label={t('ps.aria')} className="flex flex-wrap gap-2 border-t border-white/10 pt-3">
      {shown.map((s, i) => {
        const Icon = ICONS[s.kind];
        return (
          <button
            key={`${i}-${s.kind}`}
            type="button"
            data-signal={s.kind}
            onClick={() => ask(s.send_text)}
            className="inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full bg-white/[0.09] pl-3 pr-3.5 text-[13px] font-semibold text-bf-text transition-colors hover:bg-white/[0.15] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bf-turquoise/60 sm:min-h-[36px] [&>svg]:text-bf-gray"
          >
            <Icon />
            <span>{s.label}</span>
          </button>
        );
      })}
    </div>
  );
}
