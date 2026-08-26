/**
 * Pure state and data helpers for the public fixture ticker's gameweek
 * navigation. Keeping these out of the component makes the session reset
 * behaviour explicit and testable.
 */
import type { FixtureOutlookMeta, FixtureOutlookRun, TeamOutlook } from './types';

export const FIXTURE_WINDOW_SESSION_KEY = 'fpl.fixture-window.v1';

export interface StoredFixtureWindow {
  /** The live `next_gw` for which the user chose this window. */
  baseGameweek: number;
  /** First gameweek currently shown in the ticker. */
  startGameweek: number;
}

export function fixtureGameweeks(data: FixtureOutlookMeta): number[] {
  return data.teams[0]?.series.map((cell) => cell.gameweek) ?? [];
}

export function clampFixtureWindowStart(
  desired: number,
  gameweeks: readonly number[],
  horizon: number,
): number | null {
  if (gameweeks.length === 0) return null;
  const min = gameweeks[0];
  // The live anchor must never be pulled backwards merely because this export
  // has not yet published enough future columns. A final partial window is
  // preferable to showing an obsolete gameweek after the daily rollover.
  const max = gameweeks[gameweeks.length - 1];
  return Math.min(Math.max(desired, min), max);
}

/**
 * Restore a manually selected window only for the same live gameweek. A new
 * `next_gw` deliberately wins over session state: J1 -> J2 opens at J2 rather
 * than leaving a stale J1 window on screen.
 */
export function restoreFixtureWindow(
  raw: string | null,
  baseGameweek: number,
  gameweeks: readonly number[],
  horizon: number,
): number | null {
  let stored: StoredFixtureWindow | null = null;
  try {
    stored = raw ? JSON.parse(raw) as StoredFixtureWindow : null;
  } catch {
    // A malformed old session value is treated exactly like no saved choice.
  }

  const desired = stored?.baseGameweek === baseGameweek
    ? stored.startGameweek
    : baseGameweek;
  return clampFixtureWindowStart(desired, gameweeks, horizon);
}

function visibleRuns(runs: FixtureOutlookRun[], start: number, end: number): FixtureOutlookRun[] {
  return runs.flatMap((run) => {
    const start_gw = Math.max(run.start_gw, start);
    const end_gw = Math.min(run.end_gw, end);
    if (start_gw > end_gw) return [];
    return [{ ...run, start_gw, end_gw, length: end_gw - start_gw + 1 }];
  });
}

function windowTeam(team: TeamOutlook, start: number, horizon: number): TeamOutlook {
  const series = team.series.filter((cell) => cell.gameweek >= start).slice(0, horizon);
  const bands = series.flatMap((cell) => cell.band === null ? [] : [cell.band]);
  const end = series.at(-1)?.gameweek ?? start;
  return {
    ...team,
    series,
    avg_band: bands.length === 0
      ? null
      : bands.reduce((total, band) => total + band, 0) / bands.length,
    runs: visibleRuns(team.runs, start, end),
  };
}

/** Return the selected contiguous ticker window without mutating the source. */
export function fixtureOutlookWindow(
  data: FixtureOutlookMeta,
  startGameweek: number,
  horizon: number,
): FixtureOutlookMeta {
  return {
    ...data,
    horizon,
    current_gameweek: startGameweek,
    // The original export is sorted for its own horizon. Once the user moves
    // the window, re-sort by the visible average so "Mejor calendario primero"
    // remains true for the columns on screen.
    teams: data.teams
      .map((team) => windowTeam(team, startGameweek, horizon))
      .sort((left, right) => {
        if (left.avg_band === null) return right.avg_band === null
          ? left.team_short.localeCompare(right.team_short)
          : 1;
        if (right.avg_band === null) return -1;
        return left.avg_band - right.avg_band || left.team_short.localeCompare(right.team_short);
      }),
  };
}
