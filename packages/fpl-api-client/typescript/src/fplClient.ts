/**
 * fpl-api-client · packages/fpl-api-client/typescript/src/fplClient.ts
 * ======================================================================
 * Browser/Node HTTP client for the official FPL API.
 *
 * SOURCE:  Extracted and generalised from:
 *   - captaincy-showdown/src/services/http.ts         (empty file — was a placeholder)
 *   - captaincy-showdown/src/services/captaincyDataService.ts::getFixtureDifficulty
 *   - captaincy-showdown/src/utils/csvPathConfig.ts   (path conventions)
 *
 * REPLACES (do NOT delete originals until migration is approved):
 *   - captaincy-showdown/src/services/http.ts         → remove & import from here
 *
 * CONSUMERS AFTER MIGRATION:
 *   - captaincy-showdown/src/services/captaincyDataService.ts
 *   - fpl-platform/apps/fpl-chat (LLM chat backend)
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FplPlayer {
  id: number;
  first_name: string;
  second_name: string;
  web_name: string;
  team: number;        // team_id
  team_code: number;
  element_type: number; // 1=GKP 2=DEF 3=MID 4=FWD
  status: string;
  now_cost: number;
  selected_by_percent: string;
  form: string;
  expected_goals: string;
  expected_assists: string;
  expected_goal_involvements: string;
}

export interface FplTeam {
  id: number;
  name: string;
  short_name: string;
  code: number;
  strength: number;
}

export interface FplBootstrap {
  elements: FplPlayer[];
  teams: FplTeam[];
  events: FplEvent[];
}

export interface FplEvent {
  id: number;
  name: string;
  deadline_time: string;
  is_current: boolean;
  is_next: boolean;
  finished: boolean;
}

export interface FplFixture {
  id: number;
  event: number;
  team_h: number;
  team_a: number;
  team_h_difficulty: number;
  team_a_difficulty: number;
  started: boolean;
  finished: boolean;
}

// ---------------------------------------------------------------------------
// Endpoint constants
// ---------------------------------------------------------------------------

const BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/";
const FIXTURES_URL = (gw: number) =>
  `https://fantasy.premierleague.com/api/fixtures/?event=${gw}`;

// ---------------------------------------------------------------------------
// Fetch helper (browser-native fetch)
// ---------------------------------------------------------------------------

async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`FPL API error ${resp.status} for ${url}`);
  }
  return resp.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Return the full bootstrap-static payload (players + teams + events). */
export async function getBootstrap(): Promise<FplBootstrap> {
  return fetchJson<FplBootstrap>(BOOTSTRAP_URL);
}

/** Return the current gameweek number (is_current=true), or null. */
export function getCurrentGameweek(bootstrap: FplBootstrap): number | null {
  const curr = bootstrap.events.find(e => e.is_current);
  if (curr) return curr.id;
  const next = bootstrap.events.find(e => e.is_next);
  return next?.id ?? null;
}

/** Return fixtures for a specific gameweek. */
export async function getFixtures(gameweek: number): Promise<FplFixture[]> {
  return fetchJson<FplFixture[]>(FIXTURES_URL(gameweek));
}

/**
 * Return a Map<teamId, fixtureDifficulty> for a gameweek.
 *
 * SOURCE: captaincy-showdown/src/services/captaincyDataService.ts::getFixtureDifficulty
 */
export async function getFixtureDifficultyMap(
  gameweek: number,
  teams: FplTeam[]
): Promise<Map<number, number>> {
  const teamStrength = new Map(teams.map(t => [t.id, t.strength ?? 3]));
  const fixtures = await getFixtures(gameweek);
  const map = new Map<number, number>();
  for (const fix of fixtures) {
    map.set(fix.team_h, teamStrength.get(fix.team_a) ?? 3);
    map.set(fix.team_a, teamStrength.get(fix.team_h) ?? 3);
  }
  return map;
}


