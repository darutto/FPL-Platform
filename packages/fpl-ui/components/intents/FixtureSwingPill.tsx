'use client';

/**
 * FixtureSwingPill — "Easier from J14 · 3.0 → 1.8 · in 3 J" for one team's swing.
 * Shown in the trend view's team header only; the detailed and compact views are
 * already dense and carry no swing marker.
 */
import { bandColor, gwLabel, hexRgba } from '@/lib/fixture-outlook-format';
import type { Swing } from '@/lib/fixture-swing';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';

/** Turquoise for a run that turns easier, coral for one that turns harder: the FDR ramp's ends. */
export function swingColor(direction: Swing['direction']): string {
  return bandColor(direction === 'easier' ? 1 : 5);
}

export function swingArrow(direction: Swing['direction']): string {
  return direction === 'easier' ? '▲' : '▼';
}

export function FixtureSwingPill({ swing }: { swing: Swing }) {
  const t = useT();
  const { locale } = useLocale();
  const color = swingColor(swing.direction);
  const gw = gwLabel(swing.gameweek, locale);
  const when = swing.inGameweeks === 0 ? t('fx.swing.now') : t('fx.swing.in', { n: swing.inGameweeks });
  return (
    <span className="inline-flex items-center gap-2 flex-wrap" data-testid="fixture-swing-pill" data-direction={swing.direction}>
      <span
        className="text-[13px] font-extrabold rounded-full px-3 py-1 whitespace-nowrap border"
        style={{ backgroundColor: hexRgba(color, 0.14), color, borderColor: hexRgba(color, 0.5) }}
      >
        {swingArrow(swing.direction)} {t(swing.direction === 'easier' ? 'fx.swing.easier' : 'fx.swing.harder', { gw })}
        <span className="ml-2 text-[11px] font-bold opacity-80">
          {swing.reference.toFixed(1)} → {swing.lead.toFixed(1)}
        </span>
      </span>
      <span className="text-[12px] text-bf-gray whitespace-nowrap">{when}</span>
    </span>
  );
}
