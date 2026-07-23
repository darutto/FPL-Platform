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
import { useMemo, useState } from 'react';
import { buildRealSeasonOutlook } from '@/lib/fixture-outlook-real';
import { axisLabel } from '@/lib/fixture-outlook-format';
import { teamOutlookQuestion, fixtureCellQuestion } from '@/lib/fixture-chat-links';
import { FixtureTickerRow, BandLegend } from './FixtureTickerRow';
import { FixtureCompactGrid } from './FixtureCompactGrid';
import { FixtureTendencyChart } from './FixtureTendencyChart';
import { FingerprintWaves } from './CardOrnaments';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import type { FixtureAxis } from '@/lib/types';

const HORIZONS = [5, 8, 10] as const;
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

  const data = useMemo(() => buildRealSeasonOutlook(axis, horizon), [axis, horizon]);

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
