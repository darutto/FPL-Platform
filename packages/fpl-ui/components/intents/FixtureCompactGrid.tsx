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
  gwLabel,
  type Band,
} from '@/lib/fixture-outlook-format';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import { useState, type CSSProperties } from 'react';
import { compactGutter, gutterSentence, type TeamExtras } from '@/lib/fixture-competitions';
import { GutterMarks } from './FixtureCompetitionExtras';
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
  extrasFor,
  layerActive = false,
}: {
  data: FixtureOutlookMeta;
  onAsk?: (question: string) => void;
  /** Multi-competition layer lookup per team code (the gutter marks). */
  extrasFor?: (team: string) => TeamExtras | null;
  /** True when the "Otras competiciones" layer is on: every row then gets the 12 px gutters, so columns stay aligned. */
  layerActive?: boolean;
  /** Large, non-interactive layout used by the podcast/screen-share view. */
  presentation?: boolean;
}) {
  const { teams, axis } = data;
  const t = useT();
  const { locale } = useLocale();
  const gameweeks = teams[0]?.series.map((s) => s.gameweek) ?? [];
  // The detail line of the tapped (or focused) gutter: `team:gameweek`.
  const [picked, setPicked] = useState<string | null>(null);

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
          {t('fx.team')}
        </span>
        {gameweeks.map((g) => (
          <span
            key={g}
            className="flex items-center justify-center text-center text-[clamp(12px,1.4vw,21px)] font-extrabold tracking-wide text-bf-gray"
          >
            {gwLabel(g, locale)}
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

  let detail: string | null = null;
  if (picked && layerActive) {
    const [pickedTeam, pickedGw] = picked.split(':');
    detail = gutterSentence(pickedTeam, compactGutter(extrasFor?.(pickedTeam) ?? null, Number(pickedGw)), locale);
  }

  return (
    <div
      className="fx-compact"
      style={{ '--n': gameweeks.length, '--teams': Math.max(1, teams.length), '--layer': layerActive ? 1 : 0 } as CSSProperties}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setPicked(null);
      }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setPicked(null);
      }}
    >
      <div className="fx-scroll overflow-x-auto">
        <div className="fx-table min-w-max">
          <div className="fx-head flex items-center gap-1 mb-1.5">
            <span className="fx-team-col fx-gw font-extrabold tracking-wide text-bf-gray">
              {t('fx.team')}
            </span>
            {gameweeks.map((g) => (
              <span key={g} className="contents">
                {layerActive && <span aria-hidden="true" className="w-[12px] flex-none" />}
                <span className="fx-cell-w fx-gw text-center font-extrabold tracking-wide text-bf-gray">
                  {gwLabel(g, locale)}
                </span>
              </span>
            ))}
          </div>

          {teams.map((team, index) => {
            const runByGw = runsByGameweek(team.runs);
            const extras = layerActive ? extrasFor?.(team.team_short) ?? null : null;
            return (
              <div key={team.team_short} className="flex items-center gap-1 py-[2px]">
                <CompactTeamButton teamName={team.team_name} teamShort={team.team_short} rank={index + 1} axis={axis} onAsk={onAsk} />
                {team.series.map((gw) => (
                  <span key={gw.gameweek} className="contents">
                    {layerActive && (
                      <GutterMarks
                        team={team.team_short}
                        gutter={compactGutter(extras, gw.gameweek)}
                        selected={picked === `${team.team_short}:${gw.gameweek}`}
                        onPick={() => setPicked(`${team.team_short}:${gw.gameweek}`)}
                      />
                    )}
                    <CompactCell
                      gw={gw}
                      runHex={runHexFor(runByGw.get(gw.gameweek))}
                      onAsk={onAsk ? () => onAsk(fixtureCellQuestion(team.team_name, gw, locale)) : undefined}
                    />
                  </span>
                ))}
              </div>
            );
          })}
        </div>
      </div>
      {detail && (
        // Fixed to the viewport (the board's card clips overflow, so `sticky` would not hold): it stays
        // in view whichever of the 20 rows was tapped, and has its own close button for touch.
        <div
          data-testid="compact-detail-bar"
          className="fixed inset-x-3 bottom-3 z-50 mx-auto flex max-w-[936px] items-start gap-3 rounded-lg border border-white/10 bg-bf-surface px-3 py-2 shadow-menu"
        >
          <p role="status" data-testid="compact-detail" className="min-w-0 flex-1 text-[12.5px] font-normal text-bf-gray">
            {detail}
          </p>
          <button
            type="button"
            aria-label={t('fx.closeDetail')}
            onClick={() => setPicked(null)}
            className="flex-none text-[14px] leading-none text-bf-gray hover:text-bf-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-bf-turquoise"
          >
            ✕
          </button>
        </div>
      )}
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
  rank,
  axis,
  onAsk,
}: {
  teamName: string;
  teamShort: string;
  rank: number;
  axis: FixtureOutlookMeta['axis'];
  onAsk?: (question: string) => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const className = 'fx-team-col fx-team text-left font-black text-white hover:text-bf-turquoise transition-colors';
  const label = <><span className="fx-rank" aria-label={t('fx.rank', { n: rank })}>{rank}</span>{teamShort}</>;
  if (!onAsk) return <span className={className}>{label}</span>;
  return (
    <button
      type="button"
      onClick={() => onAsk(teamOutlookQuestion(teamName, axis, locale))}
      title={t('fx.cell.askTeam', { team: teamName })}
      className={className}
    >
      {label}
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
  const t = useT();
  const { locale } = useLocale();
  const blank = gw.band === null;
  const fg = blank ? BLANK_COLOR : bandColor(gw.band as Band);
  const opponents = blank ? '—' : gw.fixtures.map((f) => f.opponent_short).join('/');
  const venue = blank ? '' : gw.fixtures.map((f) => venueLabel(f.is_home, locale)).join('/');
  const className = presentation
    ? 'flex h-full w-full items-center justify-center gap-1 rounded-md px-1 text-center'
    : 'fx-cell flex items-center justify-center gap-0.5 rounded-md transition-transform hover:-translate-y-0.5';
  const style = {
    backgroundColor: hexRgba(fg, 0.34),
    boxShadow: runHex ? `0 0 0 2px ${hexRgba(runHex, 0.7)}` : undefined,
  };
  const contents = <>
    <span className={presentation ? 'text-[clamp(16px,1.85vw,30px)] font-extrabold leading-none' : 'fx-opp font-extrabold leading-none'} style={{ color: fg }}>
      {opponents}
    </span>
    {venue && (
      <span className={presentation ? 'text-[clamp(10px,1.1vw,18px)] font-extrabold leading-none text-white/75' : 'fx-venue font-extrabold leading-none text-white/75'}>{venue}</span>
    )}
  </>;

  if (!onAsk) return <div className={className} style={style}>{contents}</div>;
  return (
    <button
      type="button"
      onClick={onAsk}
      title={blank ? t('fx.cell.blank') : t('fx.cell.askCell', { opponents, venue, band: gw.band as number })}
      className={className}
      style={style}
    >
      {contents}
    </button>
  );
}
