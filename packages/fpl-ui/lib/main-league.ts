/**
 * The user's main mini-league (EO of "my league"): which league the assistant uses when the
 * user asks about it. The id is a per-browser preference stored next to the connected team id
 * (`fpl_team_id`) and sent on every turn as `main_league_id`; the server never stores it.
 *
 * The server also checks that the league is one of the user's OWN, so a stale or edited value
 * can only ever produce the "which league?" question, never someone else's league.
 *
 * Every storage access is wrapped: localStorage can throw (private windows, blocked storage,
 * SSR), and the chat must keep working without it.
 */

export const MAIN_LEAGUE_LS_KEY = 'fpl_main_league_id';

/** A league id is a positive safe integer; anything else (text, 0, NaN, a float) is no id. */
export function parseLeagueId(raw: unknown): number | null {
  const n = typeof raw === 'string' && /^\d+$/.test(raw.trim()) ? Number(raw.trim()) : raw;
  return typeof n === 'number' && Number.isSafeInteger(n) && n > 0 ? n : null;
}

export function readMainLeagueId(): number | null {
  try {
    return parseLeagueId(localStorage.getItem(MAIN_LEAGUE_LS_KEY));
  } catch {
    return null;
  }
}

/** Store the id, or clear it when `id` is null (or not a valid id). */
export function writeMainLeagueId(id: number | null): void {
  try {
    const valid = parseLeagueId(id);
    if (valid === null) localStorage.removeItem(MAIN_LEAGUE_LS_KEY);
    else localStorage.setItem(MAIN_LEAGUE_LS_KEY, String(valid));
  } catch {
    /* storage unavailable: the preference just does not persist */
  }
}
