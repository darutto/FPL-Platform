'use client';

/**
 * FixturesBoard — the reusable fixture-ticker board (Track D / FI7).
 *
 * Shared by the standalone public /fixtures page and the in-app Calendario
 * pager tab. Owns the four controls (attack⇄defence axis, 5/8/10 horizon,
 * detailed⇄compact⇄tendency view) and renders the league outlook from the
 * interim data seam — real, finished 2025–26 fixtures run through the same
 * band/run engine the live tool uses (buildRealSeasonOutlook; see
 * lib/fixture-outlook-real.ts). Swap for a live fetch once the new season's
 * fixtures roll over — identical FixtureOutlookMeta shape, so nothing else
 * changes. Every team/cell deep-links via `onAsk`, which each surface
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

      {/* Board */}
      <div className={`${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
        <FingerprintWaves color={ACCENT_HEX.turquoise} corner="br" />
        <div className="relative z-10 p-4 space-y-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-extrabold text-white">Liga · orden por calendario</span>
            <span className="text-bf-gray/60">·</span>
            <span
              className="text-[10px] font-bold uppercase tracking-wider rounded px-1.5 py-0.5"
              style={{ backgroundColor: `${ACCENT_HEX.turquoise}22`, color: ACCENT_HEX.turquoise }}
            >
              {axisLabel(axis)}
            </span>
          </div>

          {view === 'detailed' && (
            <div className="divide-y divide-white/5">
              {data.teams.map((t) => (
                <div key={t.team_short} className="py-2 first:pt-0">
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
            <div className="divide-y divide-white/5">
              {data.teams.map((t) => (
                <div key={t.team_short} className="py-2.5 first:pt-0 space-y-1">
                  <button
                    type="button"
                    onClick={() => onAsk(teamOutlookQuestion(t.team_name, axis))}
                    className="text-xs font-bold tracking-wide text-white hover:text-bf-turquoise transition-colors"
                  >
                    {t.team_short}
                  </button>
                  <FixtureTendencyChart team={t} onAsk={onAsk} />
                </div>
              ))}
            </div>
          )}

          <BandLegend />

          <p className="text-[10px] leading-snug text-bf-gray/50 pt-1 border-t border-white/5">
            Calendario real de la temporada 2025–26 (finalizada), sin datos
            inventados. Ataque: dificultad FDR de FPL. Portería a cero: FDR
            ajustado por la forma atacante reciente del rival. Se reemplazará
            por el calendario real de la nueva temporada cuando la API de FPL
            lo publique.
          </p>
        </div>
      </div>
    </div>
  );
}
