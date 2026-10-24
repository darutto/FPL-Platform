'use client';

/**
 * FixturesBoard — the reusable fixture-ticker board (Track D / FI7).
 *
 * Shared by the standalone public /fixtures page and the in-app Calendario
 * pager tab. Owns the four controls (attack⇄defence axis, 5/8/10 horizon,
 * detailed⇄compact⇄tendency view) and renders the league outlook from the
 * data seam — real 2026–27 fixtures + FDR run through the same band/run engine
 * the live tool uses (buildRealSeasonOutlook; see lib/fixture-outlook-real.ts).
 * Identical FixtureOutlookMeta shape, so nothing here changes as the season
 * progresses. Every team/cell deep-links via `onAsk`, which each surface
 * fulfils differently: the page routes to /chat?q=…, the pager prefills the
 * composer.
 *
 * The board also states, in the card, what its data actually is: which season,
 * how many played gameweeks stand behind the difficulty, and — crucially —
 * whether the two axes are genuinely different signals. A bundle exported on
 * launch day has them collapsed onto FDR, so the Ataque / Portería a cero
 * switcher does nothing; that shipped unannounced for six weeks with only a
 * footnote in the small print, which is why the notice is now in the card.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  buildRealSeasonOutlook,
  REAL_SEASON_GENERATION,
  REAL_SEASON_HORIZONS,
} from '@/lib/fixture-outlook-real';
import {
  fixtureOutlookProvenance,
  type FixtureOutlookProvenance,
} from '@/lib/fixture-outlook-provenance';
import { axisLabel, gwLabel, gwRange } from '@/lib/fixture-outlook-format';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import type { DictKey } from '@/lib/i18n/dictionary';
import { fitCompactWindow, fitFixtureWindow, rowColumns } from '@/lib/fixture-board-fit';
import { teamOutlookQuestion, fixtureCellQuestion } from '@/lib/fixture-chat-links';
import {
  FIXTURE_WINDOW_SESSION_KEY,
  clampFixtureWindowStart,
  fixtureGameweeks,
  fixtureOutlookWindow,
  restoreFixtureWindow,
  type StoredFixtureWindow,
} from '@/lib/fixture-gameweek-navigation';
import {
  extrasFor as competitionExtrasFor,
  parseCompetitions,
  type CompetitionsView,
} from '@/lib/fixture-competitions';
import {
  CompactLegend,
  LockedCompetitionsLine,
  LockedCompetitionsToggle,
  OtherCompetitionsToggle,
  TimelineLegend,
} from './FixtureCompetitionExtras';
import { PresentationLegend, PresentationTimeline } from './FixtureTimeline';
import { usePresentationAccess } from '@/lib/presentation-access';
import { FixtureTickerRow, BandLegend } from './FixtureTickerRow';
import { FixtureCompactGrid } from './FixtureCompactGrid';
import { FixtureTendencyChart } from './FixtureTendencyChart';
import { FingerprintWaves } from './CardOrnaments';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import type { FixtureAxis } from '@/lib/types';

const HORIZONS = REAL_SEASON_HORIZONS;
/** Wide workspace only: a wider center can hold a longer window (cells never stretch). */
const WIDE_HORIZON = 12;
const DAY_MS = 86_400_000;
/** Presentation shows fewer gameweeks than the board: 6 by default, 8 on request. */
const PRESENTATION_HORIZONS = [6, 8] as const;
const OTHER_COMPETITIONS_KEY = 'fpl-fixtures-other-competitions';
type ViewMode = 'detailed' | 'compact' | 'tendency';

const VIEWS: Array<{ id: ViewMode; label: DictKey }> = [
  { id: 'detailed', label: 'fx.view.detailed' },
  { id: 'compact', label: 'fx.view.compact' },
  { id: 'tendency', label: 'fx.view.tendency' },
];

export function FixturesBoard({
  onAsk,
  initialView = 'detailed',
}: {
  onAsk: (question: string) => void;
  initialView?: ViewMode;
}) {
  const t = useT();
  const { locale } = useLocale();
  const [axis, setAxis] = useState<FixtureAxis>('attack');
  // Inside the wide workspace the window follows the room available (largest
  // option that fits) until the user picks a width; elsewhere it stays at 8.
  const [view, setView] = useState<ViewMode>(initialView);
  const rowsRef = useRef<HTMLDivElement>(null);
  const [rowsWidth, setRowsWidth] = useState<number | null>(null);
  const [pickedHorizon, setPickedHorizon] = useState<number | null>(null);
  const fit = rowsWidth === null ? null : view === 'compact' ? fitCompactWindow(rowsWidth) : fitFixtureWindow(rowsWidth);
  const horizon = pickedHorizon ?? fit?.horizon ?? 8;
  // Wide workspace + Compact: the title block shrinks to one line so the whole league fits on screen.
  const condensed = view === 'compact' && fit !== null;
  const rowColumnCount = rowsWidth === null ? 1 : rowColumns(rowsWidth, horizon);
  const horizons: readonly number[] = fit === null ? HORIZONS : [...HORIZONS, WIDE_HORIZON];
  const [nextGameweek, setNextGameweek] = useState<number | null>(null);
  // Live yardstick for the provenance stamp: how far the real league has
  // got, so "this bundle is behind the season" is measured, not assumed.
  const [finishedGameweek, setFinishedGameweek] = useState<number | null>(null);
  const [windowState, setWindowState] = useState<StoredFixtureWindow | null>(null);
  const [presentationMode, setPresentationMode] = useState(false);
  const presentationRef = useRef<HTMLDivElement>(null);
  const canPresent = usePresentationAccess();
  const [presentationHorizon, setPresentationHorizon] = useState<number>(PRESENTATION_HORIZONS[0]);
  // Multi-competition layer. The backend decides the tier; null (production, or any failure) = the board as before.
  const [competitions, setCompetitions] = useState<CompetitionsView | null>(null);

  // The full season is the navigation source; the selector below is a window
  // width over it, never a request for a differently-sized export.
  const sourceData = useMemo(() => buildRealSeasonOutlook(axis), [axis]);
  const gameweeks = useMemo(() => fixtureGameweeks(sourceData), [sourceData]);
  const fallbackGameweek = gameweeks[0] ?? 1;
  const baseGameweek = clampFixtureWindowStart(
    nextGameweek ?? fallbackGameweek,
    gameweeks,
    horizon,
  ) ?? fallbackGameweek;
  const startGameweek = windowState?.baseGameweek === baseGameweek
    ? windowState.startGameweek
    : baseGameweek;
  const data = useMemo(
    () => fixtureOutlookWindow(sourceData, startGameweek, horizon),
    [horizon, sourceData, startGameweek],
  );
  const visibleEndGameweek = data.teams[0]?.series.at(-1)?.gameweek ?? startGameweek;
  const provenance = useMemo(
    () => fixtureOutlookProvenance(REAL_SEASON_GENERATION, finishedGameweek, locale),
    [finishedGameweek, locale],
  );
  const presentationStart = clampFixtureWindowStart(startGameweek, gameweeks, presentationHorizon) ?? startGameweek;
  const presentationData = useMemo(
    () => fixtureOutlookWindow(sourceData, presentationStart, presentationHorizon),
    [presentationHorizon, presentationStart, sourceData],
  );
  const presentationEnd = presentationData.teams[0]?.series.at(-1)?.gameweek ?? presentationStart;
  const previousGameweek = clampFixtureWindowStart(startGameweek - 1, gameweeks, horizon);
  const followingGameweek = clampFixtureWindowStart(startGameweek + 1, gameweeks, horizon);

  // Re-check daily. The route has a daily server cache, so this is one small
  // request per open session rather than a live polling loop.
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch('/api/fpl-fixture-status');
        if (!response.ok) return;
        const payload = await response.json() as { next_gw?: unknown; finished_gw?: unknown };
        if (!active) return;
        if (Number.isInteger(payload.next_gw)) setNextGameweek(payload.next_gw as number);
        if (Number.isInteger(payload.finished_gw)) setFinishedGameweek(payload.finished_gw as number);
      } catch {
        // The committed schedule remains a safe offline fallback.
      }
    };
    void load();
    const timer = window.setInterval(load, DAY_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const response = await fetch('/api/fpl-fixture-competitions');
        if (!response.ok) return;
        const view = parseCompetitions(await response.json());
        if (active) setCompetitions(view);
      } catch {
        // The competitions layer is an enhancement; the base calendar never depends on it.
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // A saved manual window applies only while FPL's `next_gw` is unchanged.
  // On the J1 -> J2 rollover this resolves back to J2 automatically.
  useEffect(() => {
    if (gameweeks.length === 0) return;
    let saved: string | null = null;
    try {
      saved = window.sessionStorage.getItem(FIXTURE_WINDOW_SESSION_KEY);
    } catch {
      // Storage can be disabled; navigation still works in memory.
    }
    const restored = restoreFixtureWindow(saved, baseGameweek, gameweeks, horizon);
    if (restored !== null) setWindowState({ baseGameweek, startGameweek: restored });
  }, [baseGameweek, gameweeks, horizon]);

  useEffect(() => {
    if (windowState?.baseGameweek !== baseGameweek) return;
    try {
      window.sessionStorage.setItem(FIXTURE_WINDOW_SESSION_KEY, JSON.stringify(windowState));
    } catch {
      // Session storage is an enhancement, never a dependency.
    }
  }, [baseGameweek, windowState]);

  // The "Otras competiciones" switch. Off (or no layer at all) hands every view `null`, which is exactly the Premier-only calendar.
  const [showOthers, setShowOthers] = useState(true);
  useEffect(() => {
    try {
      if (window.localStorage.getItem(OTHER_COMPETITIONS_KEY) === '0') setShowOthers(false);
    } catch {
      // Storage can be disabled; the switch still works in memory.
    }
  }, []);
  const changeShowOthers = (next: boolean) => {
    setShowOthers(next);
    try {
      window.localStorage.setItem(OTHER_COMPETITIONS_KEY, next ? '1' : '0');
    } catch {
      // The choice just isn't remembered.
    }
  };
  // Free/Tribuna: the server sent only "locked". They never get a layer, just the locked switch.
  const [lockedOpen, setLockedOpen] = useState(false);
  const layer = showOthers && competitions?.tier === 'premium' ? competitions : null;
  const extrasFor = (team: string) => competitionExtrasFor(layer, team);

  const moveWindow = (delta: -1 | 1) => {
    const next = clampFixtureWindowStart(startGameweek + delta, gameweeks, horizon);
    if (next !== null) setWindowState({ baseGameweek, startGameweek: next });
  };

  const openPresentation = () => {
    setView('compact');
    setPresentationMode(true);
    void presentationRef.current?.requestFullscreen?.().catch(() => {
      // The fixed overlay remains useful when native fullscreen is unavailable.
    });
  };

  const closePresentation = async () => {
    setPresentationMode(false);
    if (document.fullscreenElement) await document.exitFullscreen();
  };

  useEffect(() => {
    const syncFullscreen = () => {
      if (!document.fullscreenElement) setPresentationMode(false);
    };
    document.addEventListener('fullscreenchange', syncFullscreen);
    return () => document.removeEventListener('fullscreenchange', syncFullscreen);
  }, []);

  useEffect(() => {
    const el = rowsRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      // The workspace class lands after mount, so it is checked on every measure.
      if (!el.closest('.wide-workspace')) { setRowsWidth(null); return; }
      // Hidden (the other center tab) reports 0 width: keep the last fit.
      if (el.clientWidth === 0) return;
      setRowsWidth(el.clientWidth);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Axis toggle */}
        <div className="inline-flex rounded-full border border-white/10 bg-white/[0.03] p-0.5">
          {(['attack', 'defence'] as FixtureAxis[]).map((a) => (
            <button
              key={a}
              onClick={() => setAxis(a)}
              aria-pressed={axis === a}
              className={`px-3 py-1 text-xs font-bold rounded-full transition-colors ${
                axis === a
                  ? 'bg-bf-turquoise/15 text-bf-turquoise'
                  : 'text-bf-gray hover:text-white'
              }`}
            >
              {axisLabel(a, locale)}
            </button>
          ))}
        </div>

        {/* Horizon selector */}
        <div className="inline-flex items-center gap-1">
          <span className="text-[10px] font-bold uppercase tracking-wider text-bf-gray/60">
            {t('fx.horizon')}
          </span>
          {horizons.map((h) => (
            <button
              key={h}
              onClick={() => setPickedHorizon(h)}
              aria-pressed={horizon === h}
              className={`w-8 py-1 text-xs font-bold rounded-md border transition-colors ${
                horizon === h
                  ? 'border-bf-turquoise/50 bg-bf-turquoise/10 text-bf-turquoise'
                  : 'border-white/10 text-bf-gray hover:text-white'
              }`}
            >
              {h}
            </button>
          ))}
        </div>

        {/* Gameweek window navigation */}
        <div className="inline-flex items-center gap-1.5" aria-label={t('fx.nav.label')}>
          <button
            type="button"
            onClick={() => moveWindow(-1)}
            disabled={previousGameweek === null || previousGameweek === startGameweek}
            aria-label={t('fx.nav.prev')}
            className="w-7 h-7 rounded-md border border-white/10 text-bf-gray hover:text-white disabled:opacity-35 disabled:hover:text-bf-gray transition-colors"
          >
            ‹
          </button>
          <span className="text-[11px] font-extrabold text-bf-gray whitespace-nowrap" aria-live="polite">
            {gwRange(startGameweek, visibleEndGameweek, locale)}
          </span>
          <button
            type="button"
            onClick={() => moveWindow(1)}
            disabled={followingGameweek === null || followingGameweek === startGameweek}
            aria-label={t('fx.nav.next')}
            className="w-7 h-7 rounded-md border border-white/10 text-bf-gray hover:text-white disabled:opacity-35 disabled:hover:text-bf-gray transition-colors"
          >
            ›
          </button>
        </div>

        {competitions?.tier === 'premium' && (
          <OtherCompetitionsToggle checked={showOthers} onChange={changeShowOthers} />
        )}
        {competitions?.tier === 'free' && (
          <LockedCompetitionsToggle open={lockedOpen} onToggle={() => setLockedOpen((open) => !open)} />
        )}

        {/* View toggle */}
        <div className="inline-flex rounded-full border border-white/10 bg-white/[0.03] p-0.5 ml-auto">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              onClick={() => setView(v.id)}
              aria-pressed={view === v.id}
              className={`px-3 py-1 text-xs font-bold rounded-full transition-colors ${
                view === v.id
                  ? 'bg-bf-coral/15 text-bf-coral'
                  : 'text-bf-gray hover:text-white'
              }`}
            >
              {t(v.label)}
            </button>
          ))}
        </div>
        {canPresent && (
          <button
            type="button"
            onClick={openPresentation}
            className="rounded-full border border-bf-turquoise/40 bg-bf-turquoise/10 px-3 py-1 text-xs font-bold text-bf-turquoise transition-colors hover:bg-bf-turquoise/20"
          >
            {t('fx.present')}
          </button>
        )}
      </div>

      {competitions?.tier === 'free' && lockedOpen && <LockedCompetitionsLine />}

      {/* FDR / venue / streak legend (above the board, design parity); condensed Compact carries it in its header line */}
      {!condensed && <BandLegend />}
      {layer && (view === 'detailed' ? <TimelineLegend /> : view === 'compact' ? <CompactLegend /> : null)}

      {/* Board */}
      <div className={`${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
        <FingerprintWaves color={ACCENT_HEX.turquoise} corner="br" />
        <div className="relative z-10 p-5 md:p-6 space-y-4">
          {condensed ? (
            <CompactHeader axis={axis} start={startGameweek} end={visibleEndGameweek} provenance={provenance} />
          ) : (
            <>
              <div>
                <div className="flex items-baseline gap-3 flex-wrap">
                  <h2 className="text-2xl font-black tracking-tight text-white">
                    {t('fx.league.title')}
                  </h2>
                  <span
                    className="text-[13px] font-extrabold uppercase tracking-wider rounded-md px-3 py-1 border"
                    style={{
                      backgroundColor: `${ACCENT_HEX.turquoise}26`,
                      color: ACCENT_HEX.turquoise,
                      borderColor: `${ACCENT_HEX.turquoise}66`,
                    }}
                  >
                    {axisLabel(axis, locale)}
                  </span>
                </div>
                <p className="mt-1.5 text-sm text-bf-gray">
                  {t('fx.league.subtitle', { range: gwRange(startGameweek, visibleEndGameweek, locale) })}
                </p>
              </div>

              <div className="max-w-prose">
                <FixtureProvenanceStamp provenance={provenance} />
              </div>
            </>
          )}

          {/* Wrapped so a test can read what the board is actually showing.
              The axis-switcher bug was invisible to every existing test
              precisely because nothing ever compared one rendering to
              another. */}
          <div ref={rowsRef} data-testid="fixture-board-rows">
          {view === 'detailed' && (
            <div className="fixture-rows" style={{ '--row-cols': rowColumnCount, '--row-rows': Math.ceil(data.teams.length / rowColumnCount) } as CSSProperties}>
              {data.teams.map((team, index) => (
                <div
                  key={team.team_short}
                  className="py-[18px] first:pt-0 border-t border-white/10 first:border-t-0"
                >
                  <FixtureTickerRow
                    rank={index + 1}
                    team={team}
                    onAskTeam={() => onAsk(teamOutlookQuestion(team.team_name, axis, locale))}
                    onAskCell={(gw) => onAsk(fixtureCellQuestion(team.team_name, gw, locale))}
                    extras={extrasFor(team.team_short)}
                  />
                </div>
              ))}
            </div>
          )}
          {view === 'compact' && <FixtureCompactGrid data={data} onAsk={onAsk} extrasFor={extrasFor} layerActive={layer !== null} />}
          {view === 'tendency' && (
            <div className="fixture-rows" style={{ '--row-cols': rowColumnCount, '--row-rows': Math.ceil(data.teams.length / rowColumnCount) } as CSSProperties}>
              {data.teams.map((team, index) => (
                <div
                  key={team.team_short}
                  className="py-[18px] first:pt-0 border-t border-white/10 first:border-t-0"
                >
                  <FixtureTendencyChart team={team} rank={index + 1} onAsk={onAsk} />
                </div>
              ))}
            </div>
          )}
          </div>

          {!condensed && <FooterNote />}
        </div>
      </div>

      <div
          ref={presentationRef}
          data-no-swipe
          className={presentationMode
            ? 'fixed inset-0 z-[100] flex min-h-[100dvh] flex-col overflow-hidden bg-bf-ink px-[clamp(16px,3vw,56px)] py-[clamp(14px,2.5vh,36px)] text-white'
            : 'pointer-events-none fixed inset-0 -z-10 flex min-h-[100dvh] flex-col overflow-hidden opacity-0'}
          aria-label={t('fx.present.aria')}
          aria-hidden={!presentationMode}
        >
          <div className="mb-[clamp(6px,1vh,14px)] flex items-center gap-[clamp(10px,1.4vw,28px)] whitespace-nowrap">
            <span className="text-[clamp(16px,1.7vw,30px)] font-black tracking-tight">{t('fx.present.title')}</span>
            <span className="text-[clamp(11px,1vw,18px)] font-extrabold uppercase tracking-wider text-bf-turquoise">
              {axisLabel(axis, locale)} · {gwRange(presentationStart, presentationEnd, locale)}
            </span>
            <div className="hidden min-w-0 flex-1 overflow-hidden lg:block">
              {layer ? (
                <PresentationLegend />
              ) : (
                <span className="text-[clamp(10px,0.85vw,15px)] font-bold text-bf-gray">
                  {t('fx.present.legend')}
                </span>
              )}
            </div>
            <div className="ml-auto inline-flex items-center gap-1" role="group" aria-label={t('fx.present.horizonGroup')}>
              {PRESENTATION_HORIZONS.map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => setPresentationHorizon(h)}
                  aria-pressed={presentationHorizon === h}
                  className={`rounded-md border px-[clamp(8px,0.8vw,14px)] py-[clamp(2px,0.3vw,6px)] text-[clamp(10px,0.9vw,15px)] font-bold transition-colors ${
                    presentationHorizon === h
                      ? 'border-bf-turquoise/50 bg-bf-turquoise/10 text-bf-turquoise'
                      : 'border-white/15 text-bf-gray hover:text-white'
                  }`}
                >
                  {t('fx.present.horizonOption', { n: h })}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={closePresentation}
              className="rounded-md border border-white/15 px-3 py-1.5 text-[clamp(10px,1vw,14px)] font-bold text-bf-gray hover:text-white"
            >
              {t('fx.present.exit')} <span className="text-white/50">Esc</span>
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {layer ? (
              // The timeline only exists while presenting: the overlay is otherwise a hidden copy of the board.
              presentationMode && <PresentationTimeline data={presentationData} extrasFor={extrasFor} />
            ) : (
              <FixtureCompactGrid data={presentationData} presentation />
            )}
          </div>
        </div>
    </div>
  );
}

/**
 * The /fixtures provenance stamp — same shape as the i74 zonal one: a muted
 * caption for data that needs no caveat, a gold notice when it does. Both
 * strings come from the bundle's own `generation` block via
 * fixtureOutlookProvenance, so the card cannot word the fact differently from
 * what was actually built.
 */
function FixtureProvenanceStamp({ provenance }: { provenance: FixtureOutlookProvenance }) {
  return (
    <div data-testid="fixture-provenance" data-status={provenance.status}>
      <p className="mt-2 text-[10.5px] font-medium tracking-[0.02em] text-bf-gray/55">
        {provenance.label}
      </p>
      {provenance.warning && (
        <p
          data-testid="fixture-provenance-warning"
          className="mt-2 rounded-[8px] border border-bf-gold/35 bg-bf-gold/[0.07] px-3 py-2 text-[11.5px] font-semibold leading-snug text-bf-gold"
        >
          {provenance.warning}
        </p>
      )}
    </div>
  );
}

function FooterNote() {
  const t = useT();
  return (
    <p className="max-w-prose text-[10px] leading-snug text-bf-gray/50 pt-3 border-t border-white/5">
      {t('fx.footer')}
    </p>
  );
}

/**
 * Compact in the wide workspace: title, axis, window, legend and the data note on ONE line (it wraps only when
 * the panel is too narrow). The note is not dropped: an icon opens it inline, with the same provenance stamp,
 * warning and footer the full block shows, and its tooltip carries the warning (or the stamp) too.
 */
function CompactHeader({ axis, start, end, provenance }: {
  axis: FixtureAxis; start: number; end: number; provenance: FixtureOutlookProvenance;
}) {
  const t = useT();
  const { locale } = useLocale();
  const [open, setOpen] = useState(false);
  const warned = Boolean(provenance.warning);
  return (
    <div data-testid="compact-header">
      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap">
          <h2 className="text-lg font-black tracking-tight text-white">{t('fx.league.title')}</h2>
          <span
            className="text-[11px] font-extrabold uppercase tracking-wider rounded-md px-2.5 py-0.5 border"
            style={{
              backgroundColor: `${ACCENT_HEX.turquoise}26`,
              color: ACCENT_HEX.turquoise,
              borderColor: `${ACCENT_HEX.turquoise}66`,
            }}
          >
            {axisLabel(axis, locale)}
          </span>
          <span className="text-[13px] text-bf-gray whitespace-nowrap">
            {t('fx.league.subtitle', { range: gwRange(start, end, locale) })}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-x-3 gap-y-1.5 flex-wrap justify-end">
          <BandLegend inline />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label={t('fx.dataNote')}
            title={provenance.warning ?? provenance.label}
            className={`flex h-7 w-7 flex-none items-center justify-center rounded-full border text-[13px] font-black leading-none transition-colors ${
              warned
                ? 'border-bf-gold/50 bg-bf-gold/10 text-bf-gold hover:bg-bf-gold/20'
                : 'border-white/15 text-bf-gray hover:text-white'
            }`}
          >
            {warned ? '!' : 'i'}
          </button>
        </div>
      </div>
      {open && (
        <div data-testid="compact-note" className="mt-3 space-y-2 max-w-prose">
          <FixtureProvenanceStamp provenance={provenance} />
          <p className="text-[11px] leading-snug text-bf-gray/70">{t('fx.footer')}</p>
        </div>
      )}
    </div>
  );
}
