/**
 * Compact whole-league fixture grid. The presentation variant uses the full
 * viewport for a clean, non-interactive podcast/screen-share surface.
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
  presentation = false,
}: {
  data: FixtureOutlookMeta;
  onAsk?: (question: string) => void;
  /** Large, non-interactive layout used by the podcast/screen-share view. */
  presentation?: boolean;
}) {
  const { teams, axis } = data;
  const gameweeks = teams[0]?.series.map((s) => s.gameweek) ?? [];

  if (presentation) {
    return (
      <div
        className="grid h-full w-full gap-x-2 gap-y-1"
        style={{
          gridTemplateColumns: `minmax(76px, 1fr) repeat(${gameweeks.length}, minmax(0, 1fr))`,
          // The header + 20 teams get equal vertical slots, guaranteeing the
          // full league fits and uses the whole TV/streaming viewport.
          gridTemplateRows: `repeat(${teams.length + 1}, minmax(0, 1fr))`,
        }}
      >
        <span className="flex items-center text-[clamp(12px,1.4vw,21px)] font-extrabold tracking-wide text-bf-gray">
          EQUIPO
        </span>
        {gameweeks.map((g) => (
          <span
            key={g}
            className="flex items-center justify-center text-center text-[clamp(12px,1.4vw,21px)] font-extrabold tracking-wide text-bf-gray"
          >
            J{g}
          </span>
        ))}
        {teams.flatMap((team) => {
          const runByGw = runsByGameweek(team.runs);
          return [
            <span
              key={`${team.team_short}-label`}
              className="flex h-full items-center text-left text-[clamp(16px,1.85vw,30px)] font-black text-white"
            >
              {team.team_short}
            </span>,
            ...team.series.map((gw) => (
              <CompactCell
                key={`${team.team_short}-${gw.gameweek}`}
                gw={gw}
                runHex={runHexFor(runByGw.get(gw.gameweek))}
                presentation
              />
            )),
          ];
        })}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <div className="min-w-max">
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

        {teams.map((team) => {
          const runByGw = runsByGameweek(team.runs);
          return (
            <div key={team.team_short} className="flex items-center gap-1 py-[2px]">
              <CompactTeamButton teamName={team.team_name} teamShort={team.team_short} axis={axis} onAsk={onAsk} />
              {team.series.map((gw) => (
                <CompactCell
                  key={gw.gameweek}
                  gw={gw}
                  runHex={runHexFor(runByGw.get(gw.gameweek))}
                  onAsk={onAsk ? () => onAsk(fixtureCellQuestion(team.team_name, gw, axis)) : undefined}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function runsByGameweek(runs: FixtureOutlookRun[]): Map<number, FixtureOutlookRun> {
  const result = new Map<number, FixtureOutlookRun>();
  for (const run of runs) {
    for (let gameweek = run.start_gw; gameweek <= run.end_gw; gameweek++) result.set(gameweek, run);
  }
  return result;
}

function CompactTeamButton({
  teamName,
  teamShort,
  axis,
  onAsk,
}: {
  teamName: string;
  teamShort: string;
  axis: FixtureOutlookMeta['axis'];
  onAsk?: (question: string) => void;
}) {
  const className = 'w-[50px] text-left text-[13px] font-black text-white hover:text-bf-turquoise transition-colors';
  if (!onAsk) return <span className={className}>{teamShort}</span>;
  return (
    <button
      type="button"
      onClick={() => onAsk(teamOutlookQuestion(teamName, axis))}
      title={`${teamName} - preguntar en el chat`}
      className={className}
    >
      {teamShort}
    </button>
  );
}

function CompactCell({
  gw,
  runHex,
  onAsk,
  presentation = false,
}: {
  gw: FixtureOutlookGW;
  runHex: string | null;
  onAsk?: () => void;
  presentation?: boolean;
}) {
  const blank = gw.band === null;
  const fg = blank ? BLANK_COLOR : bandColor(gw.band as Band);
  const opponents = blank ? '—' : gw.fixtures.map((f) => f.opponent_short).join('/');
  const venue = blank ? '' : gw.fixtures.map((f) => venueLabel(f.is_home)).join('/');
  const className = presentation
    ? 'flex h-full w-full items-center justify-center gap-1 rounded-md px-1 text-center'
    : 'flex w-[54px] h-[24px] items-center justify-center gap-0.5 rounded-md transition-transform hover:-translate-y-0.5';
  const style = {
    backgroundColor: hexRgba(fg, 0.34),
    boxShadow: runHex ? `0 0 0 2px ${hexRgba(runHex, 0.7)}` : undefined,
  };
  const contents = <>
    <span className={presentation ? 'text-[clamp(16px,1.85vw,30px)] font-extrabold leading-none' : 'text-[12px] font-extrabold leading-none'} style={{ color: fg }}>
      {opponents}
    </span>
    {venue && (
      <span className={presentation ? 'text-[clamp(10px,1.1vw,18px)] font-extrabold leading-none text-white/75' : 'text-[8.5px] font-extrabold leading-none text-white/75'}>{venue}</span>
    )}
  </>;

  if (!onAsk) return <div className={className} style={style}>{contents}</div>;
  return (
    <button
      type="button"
      onClick={onAsk}
      title={blank ? 'Sin partido (jornada en blanco)' : `${opponents} ${venue} · dificultad ${gw.band} - preguntar en el chat`}
      className={className}
      style={style}
    >
      {contents}
    </button>
  );
}
