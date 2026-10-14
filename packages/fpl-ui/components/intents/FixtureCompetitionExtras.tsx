/**
 * Multi-competition marks for the /fixtures board (premium detail / free tease).
 * Rendered only when the backend returned a payload; otherwise nothing at all.
 * Titles here never contain "FDR " (the board's tests read FDR titles to see
 * which difficulty is on screen).
 */
import Link from 'next/link';
import {
  competitionName,
  freeTeaseText,
  freeTeaseTitle,
  restLabel,
  rotationText,
  ROTATION_OPPORTUNITY,
  type TeamExtras,
} from '@/lib/fixture-competitions';

const GOLD = 'text-bf-gold';

export function CompetitionBadge({ code }: { code: string }) {
  return (
    <span
      data-testid="competition-badge"
      title={competitionName(code)}
      className="rounded-[4px] border border-white/20 bg-white/[0.08] px-1 text-[9px] font-black leading-[14px] tracking-wide text-white/85"
    >
      {code}
    </span>
  );
}

/** Under a detailed-view cell: extra matches with rest days, and the rotation notice. */
export function CellExtras({ extras, gameweek }: { extras: TeamExtras; gameweek: number }) {
  if (extras.kind === 'free') {
    const n = extras.countByGw.get(gameweek);
    if (!n) return null;
    return (
      <Link
        href="/subscribe"
        data-testid="competition-tease"
        title={freeTeaseTitle(n)}
        className="mt-1 block text-center text-[10px] font-extrabold text-bf-gray/80 hover:text-white"
      >
        {freeTeaseText(n)}
      </Link>
    );
  }
  const slot = extras.byGw.get(gameweek);
  if (!slot) return null;
  return (
    <div data-testid="competition-extras" className="mt-1 flex max-w-[84px] flex-col items-center gap-0.5">
      {slot.matches.map((m, i) => {
        const rest = restLabel(m.restBefore);
        return (
          <span
            key={i}
            title={`${competitionName(m.competition)} · ${m.opponent} (${m.venue === 'H' ? 'local' : 'visitante'})${rest ? ` · ${rest} de descanso` : ''}`}
            className="flex w-full items-center justify-center gap-1 text-[10px] font-bold leading-tight text-white/75"
          >
            <CompetitionBadge code={m.competition} />
            <span className="truncate">{m.opponent}</span>
            <span className="text-white/50">{m.venue === 'H' ? 'L' : 'V'}</span>
          </span>
        );
      })}
      {slot.matches.map((m, i) => {
        const rest = restLabel(m.restBefore);
        return rest ? (
          <span key={`r${i}`} className="text-[9px] font-semibold text-bf-gray/70">
            {rest} desde el anterior
          </span>
        ) : null;
      })}
      {slot.notice && (
        <span
          data-testid="rotation-notice"
          title={ROTATION_OPPORTUNITY}
          className={`text-center text-[9.5px] font-extrabold leading-tight ${GOLD}`}
        >
          {rotationText(slot.notice)}
        </span>
      )}
    </div>
  );
}

/** Inside a compact-grid cell: tiny corner chip(s). Presentation sizes scale with the viewport. */
export function CompactChip({
  extras,
  gameweek,
  presentation,
}: {
  extras: TeamExtras;
  gameweek: number;
  presentation: boolean;
}) {
  const size = presentation
    ? 'text-[clamp(8px,0.9vw,14px)]'
    : 'text-[7.5px]';
  if (extras.kind === 'free') {
    const n = extras.countByGw.get(gameweek);
    if (!n) return null;
    return (
      <span
        data-testid="competition-tease"
        title={freeTeaseTitle(n)}
        className={`absolute right-0.5 top-0 ${size} font-black leading-none text-white/70`}
      >
        {freeTeaseText(n)}
      </span>
    );
  }
  const slot = extras.byGw.get(gameweek);
  if (!slot) return null;
  const codes = Array.from(new Set(slot.matches.map((m) => m.competition))).join('+');
  return (
    <span
      data-testid="competition-extras"
      title={[
        ...slot.matches.map((m) => `${competitionName(m.competition)} · ${m.opponent}`),
        ...(slot.notice ? [rotationText(slot.notice)] : []),
      ].join(' | ')}
      className={`absolute right-0.5 top-0 flex items-center gap-0.5 ${size} font-black leading-none text-white/85`}
    >
      {codes}
      {slot.notice && (
        <span data-testid="rotation-notice" className={GOLD}>
          ↻{slot.notice.restWholeDays}d
        </span>
      )}
    </span>
  );
}

/** One line above the board: what the badges mean (premium) or how to unlock them (free). */
export function CompetitionsLegend({ tier, tease }: { tier: 'premium' | 'free'; tease: boolean }) {
  if (tier === 'free') {
    if (!tease) return null;
    return (
      <p data-testid="competitions-upsell" className="text-[12px] font-semibold text-bf-gray">
        🔒 Hay semanas con partidos extra de copas y Europa.{' '}
        <Link href="/subscribe" className="font-extrabold text-bf-turquoise hover:underline">
          Ver con Premium
        </Link>
      </p>
    );
  }
  return (
    <p data-testid="competitions-legend" className="text-[12px] font-semibold text-bf-gray">
      <b className="text-white">UCL</b> Champions · <b className="text-white">UEL</b> Europa League ·{' '}
      <b className="text-white">UECL</b> Conference · <b className="text-white">FA</b> FA Cup ·{' '}
      <b className="text-white">EFL</b> Carabao ·{' '}
      <span className={GOLD}>↻ descanso corto, posible rotación</span>
    </p>
  );
}
