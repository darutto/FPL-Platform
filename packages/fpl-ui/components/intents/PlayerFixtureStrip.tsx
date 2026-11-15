'use client';

/**
 * The player card's next-fixtures strip (see lib/player-fixture-strip.ts). Same rules as
 * the /fixtures calendar, which leads (Leo, 2026-11-09):
 *
 * - Every plan sees our outlook band on Premier League cells, on the player's axis, with
 *   FPL's FDR where there is no band. The band never depends on the tier.
 * - Premium adds Europe/cup cells and the short-rest notice.
 * - Free gets the calendar's lock (short form: «🔒 Europa y copas · Ver con Premium»).
 * - No competitions answer (unavailable, failure): band only, no lock, no extras.
 *
 * The tier comes from the same backend answer the calendar reads (/api/fpl-fixture-competitions).
 * The outlook bundle is loaded on demand (large; the chat need not ship it up front). Until it
 * settles, the strip is the plain FDR chips.
 *
 * Layout: minimal on mobile, full from `sm` up (opponent of a cup match). Band cells carry
 * no difficulty word (Leo, 2026-11-09): the colour and the legend say it, the tooltip names it.
 */
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import type { FixtureAxis, FixtureEntry, FixtureOutlookGW } from '@/lib/types';
import { FixtureChip, fdrColor, fixtureKey } from './FixtureRunTable';
import {
  parseCompetitions,
  competitionColor,
  competitionName,
  competitionTileLabel,
  lockedLink,
  type CompetitionsView,
} from '@/lib/fixture-competitions';
import { axisLabel, bandColor, bandLabel, gwLabel, hexRgba, venueLabel, type Band } from '@/lib/fixture-outlook-format';
import { buildStrip, stripAxis, type StripCell } from '@/lib/player-fixture-strip';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';

const BANDS = [1, 2, 3, 4, 5] as const;
/** Short rest marker. Not bf-gold: that is the «Medio» band. */
const REST = 'text-bf-purple';

export function PlayerFixtureStrip({
  fixtures,
  teamShort,
  position,
  observedAxis = null,
}: {
  fixtures: FixtureEntry[];
  teamShort: string;
  position: string;
  /** The backend's axis from his observed role; null/absent = FPL position decides. */
  observedAxis?: FixtureAxis | null;
}) {
  const t = useT();
  const { locale } = useLocale();
  const axis = stripAxis(position, observedAxis);
  const [view, setView] = useState<CompetitionsView | null>(null);
  /** undefined = still loading; null = no bundle or no row for this team (FDR everywhere). */
  const [series, setSeries] = useState<FixtureOutlookGW[] | null | undefined>(undefined);

  useEffect(() => {
    if (fixtures.length === 0 || typeof fetch !== 'function') return;
    let active = true;
    (async () => {
      try {
        const response = await fetch(`/api/fpl-fixture-competitions?team=${encodeURIComponent(teamShort)}`);
        if (!response.ok) return;
        const parsed = parseCompetitions(await response.json());
        if (active) setView(parsed);
      } catch {
        // Only the Europe/cup layer depends on this: the band strip stays.
      }
    })();
    return () => {
      active = false;
    };
  }, [teamShort, fixtures.length]);

  useEffect(() => {
    if (fixtures.length === 0) return;
    let active = true;
    (async () => {
      try {
        const { buildRealSeasonOutlook } = await import('@/lib/fixture-outlook-real');
        const team = buildRealSeasonOutlook(axis).teams.find((row) => row.team_short === teamShort);
        if (active) setSeries(team?.series ?? null);
      } catch {
        if (active) setSeries(null); // No bundle: every cell falls back to FPL's FDR.
      }
    })();
    return () => {
      active = false;
    };
  }, [axis, teamShort, fixtures.length]);

  const premium = view?.tier === 'premium';
  const cells = useMemo(
    () =>
      series === undefined
        ? null
        : buildStrip(fixtures, premium ? view?.teams.get(teamShort) ?? null : null, series),
    [premium, fixtures, view, teamShort, series],
  );

  if (fixtures.length === 0) return null;

  const lock = view?.tier === 'free' && (
    <p data-testid="player-strip-locked" className="text-[11px] text-bf-gray">
      <span aria-hidden="true">🔒 </span>
      {t('pc.strip.lock')} ·{' '}
      <Link href="/subscribe" className="text-bf-turquoise hover:underline">
        {lockedLink(locale)}
      </Link>
    </p>
  );

  if (!cells) {
    return (
      <div className="space-y-1.5 border-t border-white/10 pt-2.5" data-testid="player-fixture-strip" data-tier={view?.tier ?? 'none'}>
        <div className="flex flex-wrap gap-1.5">
          {fixtures.map((f) => (
            <FixtureChip key={fixtureKey(f)} entry={f} />
          ))}
        </div>
        {lock}
      </div>
    );
  }

  const anyBand = cells.some((c) => c.kind === 'pl' && c.band !== null);
  const anyFallback = cells.some((c) => c.kind === 'pl' && c.band === null);
  const anyRest = cells.some((c) => c.kind === 'pl' && c.rest !== null);

  return (
    <div className="space-y-1.5 border-t border-white/10 pt-2.5" data-testid="player-fixture-strip" data-tier={view?.tier ?? 'none'}>
      <div className="flex flex-wrap items-start gap-1.5">
        {cells.map((cell) => (
          <StripTile key={cell.key} cell={cell} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-bf-gray">
        {anyBand && (
          <span className="inline-flex items-center gap-1" data-testid="player-strip-legend">
            {bandLabel(1, locale)}
            {BANDS.map((b) => (
              <i
                key={b}
                aria-hidden="true"
                className="inline-block h-2 w-2 rounded-[2px] not-italic"
                style={{ backgroundColor: bandColor(b) }}
              />
            ))}
            {bandLabel(5, locale)}
          </span>
        )}
        {anyRest && <span className={REST}>{t('pc.strip.restLegend')}</span>}
      </div>
      <p className="text-[10px] text-bf-gray/80" data-testid="player-strip-footnote">
        {anyBand && t('pc.strip.own', { axis: axisLabel(axis, locale) })}
        {anyBand && anyFallback && ' · '}
        {anyFallback && t('pc.strip.fdr')}
      </p>
      {lock}
    </div>
  );
}

function StripTile({ cell }: { cell: StripCell }) {
  const t = useT();
  const { locale } = useLocale();

  if (cell.kind === 'extra') {
    const color = competitionColor(cell.competition);
    const venue = venueLabel(cell.venue === 'H', locale);
    return (
      <div
        data-testid="player-strip-extra"
        title={`${competitionName(cell.competition, locale)} · ${cell.opponent} (${venue})`}
        className="flex min-w-[40px] flex-col items-stretch overflow-hidden rounded-md border bg-white/[0.02]"
        style={{ borderColor: hexRgba(color, 0.6) }}
      >
        <span className="px-1.5 py-0.5 text-center text-[9px] font-bold uppercase tracking-wider" style={{ color }}>
          {competitionTileLabel(cell.competition)}
        </span>
        <span className="px-1.5 py-1 text-center text-xs font-bold text-bf-gray">
          <span className="hidden sm:inline">{cell.opponentCode} </span>({venue})
        </span>
      </div>
    );
  }

  const hasBand = cell.band !== null;
  const color = hasBand ? bandColor(cell.band as Band) : fdrColor(cell.fdr);
  const venue = venueLabel(cell.isHome, locale);
  return (
    <div className="flex flex-col items-stretch gap-0.5" data-testid="player-strip-pl" data-source={hasBand ? 'band' : 'fdr'}>
      <div
        className="flex min-w-[60px] flex-col items-stretch overflow-hidden rounded-md border border-white/10 bg-white/[0.04]"
        title={hasBand ? bandLabel(cell.band as Band, locale) : `FDR ${cell.fdr}`}
      >
        <span className="border-b border-white/5 bg-white/[0.04] px-1.5 py-0.5 text-center text-[9px] font-bold uppercase tracking-wider text-bf-gray">
          {gwLabel(cell.gameweek, locale)}
        </span>
        <span
          className="px-1.5 py-1 text-center text-xs font-extrabold tracking-tight"
          style={{ backgroundColor: `${color}33`, color }}
        >
          {cell.opponent} ({venue})
          {/* A band cell says its difficulty by colour (legend below; word in the tooltip). */}
          {!hasBand && <> · {cell.fdr}</>}
        </span>
      </div>
      {cell.rest && (
        <span
          data-testid="player-strip-rest"
          title={t('pc.strip.restTitle', { d: cell.rest.days, comp: competitionName(cell.rest.competition, locale) })}
          className={`text-center text-[9px] font-bold ${REST}`}
        >
          {t('pc.strip.rest', { d: cell.rest.days, comp: competitionTileLabel(cell.rest.competition) })}
        </span>
      )}
    </div>
  );
}
