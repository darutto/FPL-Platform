/**
 * The user's main mini-league (EO of "my league"): which league the assistant uses when the
 * user asks about it. It is a per-browser preference kept PER TEAM (`fpl_main_league_id:<teamId>`), so
 * switching to another team and back finds each team's league again, and it is sent on every turn as
 * `main_league_id` together with that same team's id. The server never stores it.
 *
 * The server also checks that the league is one of the user's OWN, so a stale or edited value
 * can only ever produce the "which league?" question, never someone else's league.
 *
 * Every storage access is wrapped: localStorage can throw (private windows, blocked storage,
 * SSR), and the chat must keep working without it.
 */

/** The old, unkeyed key (before per-team storage). Only read once, by `migrateLegacyMainLeague`, then deleted. */
export const MAIN_LEAGUE_LS_KEY = 'fpl_main_league_id';
const TEAM_LS_KEY = 'fpl_team_id'; // the connected team (SquadContextPanel owns it)
const INDEX_LS_KEY = 'fpl_main_league_teams'; // JSON array of team ids that have a stored league, oldest first
/** How many teams' leagues are kept; the oldest beyond this are dropped. */
export const MAX_STORED_TEAMS = 10;

export function mainLeagueKey(teamId: number): string {
  return `${MAIN_LEAGUE_LS_KEY}:${teamId}`;
}

/** A league id is a positive safe integer; anything else (text, 0, NaN, a float) is no id. */
export function parseLeagueId(raw: unknown): number | null {
  const n = typeof raw === 'string' && /^\d+$/.test(raw.trim()) ? Number(raw.trim()) : raw;
  return typeof n === 'number' && Number.isSafeInteger(n) && n > 0 ? n : null;
}

function parseTeamId(raw: unknown): number | null {
  return parseLeagueId(raw); // same shape: a positive safe integer
}

function readIndex(): number[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(INDEX_LS_KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.map((x) => parseTeamId(x)).filter((x): x is number => x !== null);
  } catch {
    return [];
  }
}

/** The league stored for this team, or null (none, junk, no team, unavailable storage). */
export function readMainLeagueFor(teamId: number | null): number | null {
  if (parseTeamId(teamId) === null) return null;
  try {
    return parseLeagueId(localStorage.getItem(mainLeagueKey(teamId as number)));
  } catch {
    return null;
  }
}

/** Store this team's league, or clear it when `leagueId` is null (or not a valid id). Keeps the last few teams. */
export function writeMainLeagueFor(teamId: number | null, leagueId: number | null): void {
  const team = parseTeamId(teamId);
  if (team === null) return;
  try {
    const valid = parseLeagueId(leagueId);
    const index = readIndex().filter((t) => t !== team);
    if (valid === null) {
      localStorage.removeItem(mainLeagueKey(team));
    } else {
      localStorage.setItem(mainLeagueKey(team), String(valid));
      index.push(team);
      while (index.length > MAX_STORED_TEAMS) {
        const evicted = index.shift() as number;
        localStorage.removeItem(mainLeagueKey(evicted));
      }
    }
    localStorage.setItem(INDEX_LS_KEY, JSON.stringify(index));
  } catch {
    /* storage unavailable: the preference just does not persist */
  }
}

/**
 * One-time move of the old unkeyed value to the stored team (`fpl_team_id`) only. With no valid stored team
 * the value is dropped. The old key is always deleted, and an existing per-team value is never overwritten.
 * Returns the connected team id read from storage (or null), for the caller's own hydration.
 */
export function migrateLegacyMainLeague(): number | null {
  let team: number | null = null;
  try {
    team = parseTeamId(localStorage.getItem(TEAM_LS_KEY));
    const legacy = parseLeagueId(localStorage.getItem(MAIN_LEAGUE_LS_KEY));
    if (localStorage.getItem(MAIN_LEAGUE_LS_KEY) !== null) {
      if (team !== null && legacy !== null && readMainLeagueFor(team) === null) writeMainLeagueFor(team, legacy);
      localStorage.removeItem(MAIN_LEAGUE_LS_KEY);
    }
  } catch {
    /* storage unavailable */
  }
  return team;
}
