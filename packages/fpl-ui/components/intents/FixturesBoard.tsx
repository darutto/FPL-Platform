'use client';

/**
 * FixturesBoard — the reusable fixture-ticker board (Track D / FI7).
 *
 * Shared by the standalone public /fixtures page and the in-app Calendario
 * pager tab. Owns the four controls (attack⇄defence axis, 5/8/10 horizon,
 * detailed⇄compact⇄tendency view) and renders the league outlook from the
 * data seam — real 2026–27 fixtures + FDR pulled from the live FPL API at
 * launch, run through the same band/run engine the live tool uses
 * (buildRealSeasonOutlook; see lib/fixture-outlook-real.ts). Identical
 * FixtureOutlookMeta shape, so nothing here changes as the season progresses.
 * Every team/cell deep-links via `onAsk`, which each surface
 * fulfils differently: the page routes to /chat?q=…, the pager prefills the
 * composer.
 */
import { useEffect, useMemo, useState } from 'react';
import { buildRealSeasonOutlook } from '@/lib/fixture-outlook-real';
import { axisLabel } from '@/lib/fixture-outlook-format';
import { teamOutlookQuestion, fixtureCellQuestion } from '@/lib/fixture-chat-links';
import {
  FIXTURE_WINDOW_SESSION_KEY,
  clampFixtureWindowStart,
  fixtureGameweeks,
  fixtureOutlookWindow,
  restoreFixtureWindow,
  type StoredFixtureWindow,
} from '@/lib/fixture-gameweek-navigation';
import { FixtureTickerRow, BandLegend } from './FixtureTickerRow';
import { FixtureCompactGrid } from './FixtureCompactGrid';
import { FixtureTendencyChart } from './FixtureTendencyChart';
import { FingerprintWaves } from './CardOrnaments';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import type { FixtureAxis } from '@/lib/types';

const HORIZONS = [5, 8, 10] as const;
const MAX_EXPORTED_HORIZON = 10;
const DAY_MS = 86_400_000;
type ViewMode = 'detailed' | 'compact' | 'tendency';

const VIEWS: Array<{ id: ViewMode; label: string }> = [
  { id: 'detailed', label: 'Detallado' },
  { id: 'compact', label: 'Compacto' },
  { id: 'tendency', label: 'Tendencia' },
];

export function FixturesBoard({
  onAsk,
  initialView = 'detailed',
}: {
  onAsk: (question: string) => void;
  initialView?: ViewMode;
}) {
  const [axis, setAxis] = useState<FixtureAxis>('attack');
  const [horizon, setHorizon] = useState<number>(8);
  const [view, setView] = useState<ViewMode>(initialView);
  const [nextGameweek, setNextGameweek] = useState<number | null>(null);
  const [windowState, setWindowState] = useState<StoredFixtureWindow | null>(null);

  // Use the largest exported schedule as the navigation source, then apply
  // the selected 5/8/10-column window below.
  const sourceData = useMemo(
    () => buildRealSeasonOutlook(axis, MAX_EXPORTED_HORIZON),
    [axis],
  );
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
        const payload = await response.json() as { next_gw?: unknown };
        if (active && Number.isInteger(payload.next_gw)) setNextGameweek(payload.next_gw as number);
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

  const moveWindow = (delta: -1 | 1) => {
    const next = clampFixtureWindowStart(startGameweek + delta, gameweeks, horizon);
    if (next !== null) setWindowState({ baseGameweek, startGameweek: next });
  };

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
              {axisLabel(a)}
            </button>
          ))}
        </div>

        {/* Horizon selector */}
        <div className="inline-flex items-center gap-1">
          <span className="text-[10px] font-bold uppercase tracking-wider text-bf-gray/60">
            Jornadas
          </span>
          {HORIZONS.map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
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
        <div className="inline-flex items-center gap-1.5" aria-label="Navegar jornadas">
          <button
            type="button"
            onClick={() => moveWindow(-1)}
            disabled={previousGameweek === null || previousGameweek === startGameweek}
            aria-label="Jornada anterior"
            className="w-7 h-7 rounded-md border border-white/10 text-bf-gray hover:text-white disabled:opacity-35 disabled:hover:text-bf-gray transition-colors"
          >
            ‹
          </button>
          <span className="text-[11px] font-extrabold text-bf-gray whitespace-nowrap" aria-live="polite">
            J{startGameweek}–J{visibleEndGameweek}
          </span>
          <button
            type="button"
            onClick={() => moveWindow(1)}
            disabled={followingGameweek === null || followingGameweek === startGameweek}
            aria-label="Jornada siguiente"
            className="w-7 h-7 rounded-md border border-white/10 text-bf-gray hover:text-white disabled:opacity-35 disabled:hover:text-bf-gray transition-colors"
          >
            ›
          </button>
        </div>

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
              {v.label}
            </button>
          ))}
        </div>
      </div>

      {/* FDR / venue / streak legend (above the board, design parity) */}
      <BandLegend />

      {/* Board */}
      <div className={`${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
        <FingerprintWaves color={ACCENT_HEX.turquoise} corner="br" />
        <div className="relative z-10 p-5 md:p-6 space-y-4">
          <div>
            <div className="flex items-baseline gap-3 flex-wrap">
              <h2 className="text-2xl font-black tracking-tight text-white">
                Liga · orden por calendario
              </h2>
              <span
                className="text-[13px] font-extrabold uppercase tracking-wider rounded-md px-3 py-1 border"
                style={{
                  backgroundColor: `${ACCENT_HEX.turquoise}26`,
                  color: ACCENT_HEX.turquoise,
                  borderColor: `${ACCENT_HEX.turquoise}66`,
                }}
              >
                {axisLabel(axis)}
              </span>
            </div>
            <p className="mt-1.5 text-sm text-bf-gray">
              Mejor calendario primero · FDR promedio J1–J{horizon}
            </p>
          </div>

          {view === 'detailed' && (
            <div>
              {data.teams.map((t) => (
                <div
                  key={t.team_short}
                  className="py-[18px] first:pt-0 border-t border-white/10 first:border-t-0"
                >
                  <FixtureTickerRow
                    team={t}
                    onAskTeam={() => onAsk(teamOutlookQuestion(t.team_name, axis))}
                    onAskCell={(gw) => onAsk(fixtureCellQuestion(t.team_name, gw, axis))}
                  />
                </div>
              ))}
            </div>
          )}
          {view === 'compact' && <FixtureCompactGrid data={data} onAsk={onAsk} />}
          {view === 'tendency' && (
            <div>
              {data.teams.map((t) => (
                <div
                  key={t.team_short}
                  className="py-[18px] first:pt-0 border-t border-white/10 first:border-t-0"
                >
                  <FixtureTendencyChart team={t} onAsk={onAsk} />
                </div>
              ))}
            </div>
          )}

          <p className="text-[10px] leading-snug text-bf-gray/50 pt-3 border-t border-white/5">
            Calendario real de la temporada 2026–27 desde la API oficial de FPL,
            sin datos inventados. Ambos ejes usan la dificultad FDR de FPL: al
            arrancar la temporada aún no hay partidos jugados, así que el eje de
            portería a cero se ajustará por la forma atacante reciente del rival
            en cuanto haya resultados. El calendario del final de temporada se
            completará según la API lo vaya publicando.
          </p>
        </div>
      </div>
    </div>
  );
}
