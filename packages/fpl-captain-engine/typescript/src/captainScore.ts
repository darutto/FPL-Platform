/**
 * fpl-captain-engine · packages/fpl-captain-engine/typescript/src/captainScore.ts
 * =================================================================================
 * Canonical captain scoring formula — TypeScript implementation.
 *
 * SOURCE:  This is the AUTHORITATIVE version, promoted from:
 *   captaincy-showdown/src/engine/captainScore.ts (full file — lines 1-50)
 *   No logic changes — only the import path of CaptainCandidate changes.
 *
 * REPLACES (do NOT delete originals until migration is approved):
 *   captaincy-showdown/src/engine/captainScore.ts
 *   → after migration: delete that file and import from this package
 *
 * CONSUMERS AFTER MIGRATION:
 *   captaincy-showdown/src/services/captaincyDataService.ts
 *   captaincy-showdown/src/engine/captainScore.spec.ts (tests move here too)
 *   Any new TS app needing captain scoring
 *
 * SCORE WEIGHTS  (canonical — must match captain_score.py exactly):
 *   form      40%
 *   fixture   30%
 *   xGI/90    20%
 *   minutes   10%
 */

// NOTE: CaptainCandidate is imported from the shared types module.
// During migration the type comes from captaincy-showdown/src/types/index.ts,
// but the canonical home is this package.

export interface CaptainCandidate {
  player_id: number;
  name: string;
  team: string;
  position: string;
  price: number;
  ownership: number;
  expected_ownership: number;
  form_score: number;         // Last 4 GW average points
  fixture_difficulty: number; // Opponent strength 1-5
  opponent?: string;
  home?: boolean;
  minutes_risk: number;       // 0-100 (higher = more rotation risk)
  xgi_per_90: number;         // Expected goal involvements per 90
  captain_score: number;      // Composite 0-100
}

export interface MatchupData {
  candidate_a: CaptainCandidate;
  candidate_b: CaptainCandidate;
  gameweek: number;
  last_updated: string;
}

// ---------------------------------------------------------------------------
// Scoring formula
// SOURCE: captaincy-showdown/src/engine/captainScore.ts::calculateCaptainScore
//         lines 19-35 — ZERO logic changes
// ---------------------------------------------------------------------------

interface PlayerStats {
  form: number;
  fixture_difficulty: number;
  xgi_per_90: number;
  minutes_risk: number;
}

export function calculateCaptainScore(player: PlayerStats): number {
  const formScore    = Math.min(Math.max((player.form / 10) * 100, 0), 100);
  const diff         = Math.min(Math.max(player.fixture_difficulty, 1), 5);
  const fixtureScore = Math.min(Math.max((6 - diff) * 20, 0), 100);
  const xgiScore     = Math.min(Math.max(player.xgi_per_90 * 50, 0), 100);
  const minutesScore = Math.min(Math.max(100 - player.minutes_risk, 0), 100);

  const total = (
    formScore    * 0.4 +
    fixtureScore * 0.3 +
    xgiScore     * 0.2 +
    minutesScore * 0.1
  );
  return Math.min(Math.max(total, 0), 100);
}

// SOURCE: captaincy-showdown/src/engine/captainScore.ts::updateCaptainScores
//         lines 40-50 — ZERO logic changes
export function updateCaptainScores(
  candidates: CaptainCandidate[]
): CaptainCandidate[] {
  return candidates.map(c => ({
    ...c,
    captain_score: calculateCaptainScore({
      form:               c.form_score,
      fixture_difficulty: c.fixture_difficulty,
      xgi_per_90:         c.xgi_per_90,
      minutes_risk:       c.minutes_risk,
    }),
  }));
}


