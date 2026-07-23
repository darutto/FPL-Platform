/**
 * FixtureCompactGrid — the whole league on one screen (Track D / FI7).
 *
 * A dense team × gameweek matrix so the full 20-team, 5/8/10-GW calendar fits
 * on one screen without scrolling — built for screen-sharing (e.g. talking
 * through the run on a podcast). "Calendario FDR" design: an EQUIPO + J{gw}
 * header row, then one solid-tinted cell per fixture (opponent + venue). Run
 * cells keep a turquoise/coral ring. Team codes and cells deep-link into chat.
 *
 * Deliberately tighter than the detailed view — small cells, minimal row
 * padding — so all 20 rows are visible at a glance on a large display.
 */
import type {
  FixtureOutlookMeta,
  FixtureOutlookGW,
  FixtureOutlookRun,
} from '@/lib/types';
import {
  bandColor,
  venueLabel,
  hexRgba,
  BLANK_COLOR,
  type Band,
} from '@/lib/fixture-outlook-format';
import { teamOutlookQuestion, fixtureCellQuestion } from '@/lib/fixture-chat-links';

const GOOD_HEX = '#02EBAE';
const BAD_HEX = '#FF6A4D';

function runHexFor(run: FixtureOutlookRun | undefined): string | null {
  if (!run) return null;
  return run.type === 'good' ? GOOD_HEX : BAD_HEX;
}

export function FixtureCompactGrid({
  data,
  onAsk,
}: {
  data: FixtureOutlookMeta;
  onAsk: (question: string) => void;
}) {
  const { teams, axis } = data;
  // All teams share the same aligned gameweek columns; take them from row 1.
  const gameweeks = teams[0]?.series.map((s) => s.gameweek) ?? [];

  return (
    <div className="overflow-x-auto">
      <div className="min-w-max">
        {/* Header row */}
        <div className="flex items-center gap-1 mb-1.5">
          <span className="w-[50px] text-[11px] font-extrabold tracking-wide text-bf-gray">
            EQUIPO
          </span>
          {gameweeks.map((g) => (
            <span
              key={g}
              className="w-[54px] text-center text-[11px] font-extrabold tracking-wide text-bf-gray"
            >
              J{g}
            </span>
          ))}
        </div>

        {/* Team rows */}
        {teams.map((t) => {
          const runByGw = new Map<number, FixtureOutlookRun>();
          for (const r of t.runs) {
            for (let g = r.start_gw; g <= r.end_gw; g++) runByGw.set(g, r);
          }
          return (
            <div key={t.team_short} className="flex items-center gap-1 py-[2px]">
              <button
                type="button"
                onClick={() => onAsk(teamOutlookQuestion(t.team_name, axis))}
                title={`${t.team_name} — preguntar en el chat`}
                className="w-[50px] text-left text-[13px] font-black text-white hover:text-bf-turquoise transition-colors"
              >
                {t.team_short}
              </button>
              {t.series.map((gw) => (
                <CompactCell
                  key={gw.gameweek}
                  gw={gw}
                  runHex={runHexFor(runByGw.get(gw.gameweek))}
                  onAsk={() => onAsk(fixtureCellQuestion(t.team_name, gw, axis))}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CompactCell({
  gw,
  runHex,
  onAsk,
}: {
  gw: FixtureOutlookGW;
  runHex: string | null;
  onAsk: () => void;
}) {
  const blank = gw.band === null;
  const fg = blank ? BLANK_COLOR : bandColor(gw.band as Band);
  const opponents = blank ? '—' : gw.fixtures.map((f) => f.opponent_short).join('/');
  const venue = blank ? '' : gw.fixtures.map((f) => venueLabel(f.is_home)).join('/');

  return (
    <button
      type="button"
      onClick={onAsk}
      title={
        blank
          ? 'Sin partido (jornada en blanco)'
          : `${opponents} ${venue} · dificultad ${gw.band} — preguntar en el chat`
      }
      className="w-[54px] h-[24px] flex items-center justify-center gap-0.5 rounded-md transition-transform hover:-translate-y-0.5"
      style={{
        backgroundColor: hexRgba(fg, 0.34),
        boxShadow: runHex ? `0 0 0 2px ${hexRgba(runHex, 0.7)}` : undefined,
      }}
    >
      <span className="text-[12px] font-extrabold leading-none" style={{ color: fg }}>
        {opponents}
      </span>
      {venue && (
        <span className="text-[8.5px] font-extrabold leading-none text-white/75">{venue}</span>
      )}
    </button>
  );
}
