'use client';

/**
 * PlayerSignals — the «Explorar» section at the foot of PlayerCard, and the
 * pill every "go deeper" link shares.
 *
 * The verdict above the card says the fact («Juega de extremo · 6 de 6»); the
 * `Posición ›` pill here is the way into the card that explains it. The
 * backend emits it only for a verdict line it actually showed
 * (player_signals.py), and writes the localized label and the question a tap
 * sends, verbatim, to the chat. The model is only paid for on that tap.
 *
 * No zones pill here (Leo, 2026-11-13): the card's own «Zonas» section already
 * shows the pitch. The team zonal question («Quién del BHA explota al HUL ›»)
 * closes that section instead (PlayerZonasSection), and sits under the
 * fixture-cell answer (FixtureOutlookCard), both drawn with `SignalPill`.
 *
 * No pill, or no chat to send to (a shared answer) → renders nothing: no
 * heading, no row, no separator; the card is exactly as before.
 */
import type { ComponentType } from 'react';
import type { PlayerSignal } from '@/lib/types';
import { useChatAsk } from '@/lib/chat-ask';
import { useT } from '@/lib/i18n/LocaleProvider';

const MAX_PILLS = 3;

/** Crossing arrows: where he really plays. */
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

/** Target: the rival's weak zones. */
export function ZoneIcon() {
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

/** One "go deeper" pill: icon, the destination's name, chevron. A tap sends `sendText` to the chat. */
export function SignalPill({
  kind,
  label,
  sendText,
  onAsk,
}: {
  kind: PlayerSignal['kind'];
  label: string;
  sendText: string;
  onAsk: (question: string) => void;
}) {
  const Icon = ICONS[kind];
  return (
    <button
      type="button"
      data-signal={kind}
      onClick={() => onAsk(sendText)}
      className="inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full bg-white/[0.09] pl-3 pr-3 text-[13px] font-semibold text-bf-text transition-colors hover:bg-white/[0.15] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bf-turquoise/60 sm:min-h-[36px] [&>svg]:text-bf-gray"
    >
      <Icon />
      <span>{label}</span>
      <span aria-hidden="true" className="font-bold text-bf-gray">›</span>
    </button>
  );
}

export default function PlayerSignals({ signals }: { signals?: PlayerSignal[] | null }) {
  const ask = useChatAsk();
  const t = useT();
  // «Explorar» holds the position pill only; a `zone` signal belongs to the «Zonas» section.
  const shown = (signals ?? []).filter((s) => s.kind === 'position' && s.label && s.send_text).slice(0, MAX_PILLS);
  if (ask == null || shown.length === 0) return null;

  return (
    <section aria-label={t('ps.title')} className="space-y-2 border-t border-white/10 pt-2.5" data-testid="player-explore">
      {/* Same heading style as the card's «Zonas» section. */}
      <h3 aria-hidden="true" className="text-[10px] font-extrabold uppercase tracking-wider text-bf-gray">
        {t('ps.title')}
      </h3>
      <div className="flex flex-wrap gap-2">
        {shown.map((s, i) => (
          <SignalPill key={`${i}-${s.kind}`} kind={s.kind} label={s.label} sendText={s.send_text} onAsk={ask} />
        ))}
      </div>
    </section>
  );
}
