'use client';

/**
 * The player card's next-fixtures strip (see lib/player-fixture-strip.ts). Same rules as
 * the /fixtures calendar, which leads (Leo, 2026-11-09), and the SAME tiles (Leo, 2026-11-13):
 * the /fixtures timeline's Premier League tile («J11 / HUL / V», border and fill by difficulty),
 * its small outlined Europe/cup tile (UECL · UNI · L) at its real date, and the rest days between
 * tiles («4d» grey over a dashed line; gold over a solid line = short rest after Europe or a cup).
 *
 * - Every plan sees our outlook band on Premier League tiles, on the player's axis, with
 *   FPL's FDR where there is no band (same colour scale; the footnote says so, the tooltip
 *   names it). The band never depends on the tier.
 * - Premium adds the Europe/cup tiles and the rest days.
 * - Free gets the calendar's lock (short form: «🔒 Europa y copas · Ver con Premium»).
 * - No competitions answer (unavailable, failure): band only, no lock, no extras.
 *
 * The tier comes from the same backend answer the calendar reads (/api/fpl-fixture-competitions).
 * The outlook bundle is loaded on demand (large; the chat need not ship it up front). Until it
 * settles, the strip is the plain FDR chips.
 *
 * Tiles never shrink: on a narrow screen the row scrolls sideways, as /fixtures does. Legend:
 * only the strip's own small one (difficulty ramp, the short-rest note, the axis footnote).
 */
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import type { FixtureAxis, FixtureEntry, FixtureOutlookGW } from '@/lib/types';
import { FixtureChip, fixtureKey } from './FixtureRunTable';
import { DETAILED_METRICS, ExtraTile, Gap, PlTile } from './FixtureTimeline';
import { parseCompetitions, lockedLink, type CompetitionsView } from '@/lib/fixture-competitions';
import { axisLabel, bandColor, bandLabel, type Band } from '@/lib/fixture-outlook-format';
import { buildStrip, stripAxis, type StripCell } from '@/lib/player-fixture-strip';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';

const BANDS = [1, 2, 3, 4, 5] as const;

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
        : buildStrip(fixtures, premium ? view?.teams.get(teamShort) ?? null : null, series, locale),
    [premium, fixtures, view, teamShort, series, locale],
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
      {/* The /fixtures timeline row: tiles keep their size, the row scrolls on a narrow screen. */}
      <div className="overflow-x-auto pb-1" data-testid="player-strip-row">
        <div className="flex min-w-max items-start">
          {cells.map((cell, i) => (
            <div key={cell.key} className="flex flex-none items-start">
              {cell.gap ? (
                <span data-testid={cell.gap.rotation ? 'player-strip-rest' : 'player-strip-gap'} className="contents">
                  <Gap gap={cell.gap} m={DETAILED_METRICS} selected={false} />
                </span>
              ) : i > 0 ? (
                <span aria-hidden="true" className="flex-none" style={{ width: DETAILED_METRICS.spacer }} />
              ) : null}
              <StripTile cell={cell} />
            </div>
          ))}
        </div>
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
        {/* Gold, as /fixtures draws the same notice. */}
        {anyRest && <span className="text-bf-gold">{t('pc.strip.restLegend')}</span>}
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
  const { locale } = useLocale();

  if (cell.kind === 'extra') {
    return (
      <span data-testid="player-strip-extra" className="contents">
        <ExtraTile
          item={{ kind: 'extra', key: cell.key, match: cell.match, sentence: cell.sentence, gap: null }}
          m={DETAILED_METRICS}
          selected={false}
        />
      </span>
    );
  }

  const hasBand = cell.band !== null;
  // A cell without our band keeps FPL's FDR, drawn on the same 1-5 scale (the footnote says so).
  const gw: FixtureOutlookGW = {
    gameweek: cell.gameweek,
    band: hasBand ? cell.band : cell.fdr,
    klass: 'neutral',
    is_dgw: false,
    is_bgw: false,
    fixtures: [{ opponent_short: cell.opponent, is_home: cell.isHome, band: (cell.band ?? cell.fdr) as Band }],
  };
  return (
    <span data-testid="player-strip-pl" data-source={hasBand ? 'band' : 'fdr'} className="contents">
      <PlTile
        gw={gw}
        ring={null}
        m={DETAILED_METRICS}
        title={hasBand ? bandLabel(cell.band as Band, locale) : `FDR ${cell.fdr}`}
      />
    </span>
  );
}
