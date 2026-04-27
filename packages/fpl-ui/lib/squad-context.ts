/**
 * Squad context normalization (V2 Phase 2f).
 *
 * Pure functions — no fetch, no React, no side effects. All testable directly.
 *
 * The official FPL API uses its own chip name codes that differ from the
 * backend SquadContext chip names:
 *
 *   FPL API     → backend SquadContext
 *   wildcard    → "wildcard"       (up to 2 per season, one per half)
 *   3xc         → "triple_captain" (1 per season)
 *   bboost      → "bench_boost"    (1 per season)
 *   freehit     → "free_hit"       (1 per season)
 *
 * Free transfers:
 *   The FPL public API does NOT expose a free_transfers_available field.
 *   Correct derivation would require walking the full season history with
 *   chip-play detection and current-GW pre-deadline state — fragile and
 *   undocumented. free_transfers is set to null here and must be provided
 *   explicitly by the user via SquadContextPanel. Every FPL player can see
 *   their exact FT count on the FPL transfers page.
 */
import type { SquadContext } from './types';

// ---------------------------------------------------------------------------
// FPL API raw shapes (server-side only — not imported into renderer)
// ---------------------------------------------------------------------------

/** Minimal fields we consume from GET /api/entry/{id}/ */
export interface FplEntryRaw {
  id: number;
  player_first_name: string;
  player_last_name: string;
  name: string;                    // squad name
  last_deadline_bank: number;      // ITB in tenths of £  (e.g. 5 = £0.5m)
  summary_event_transfers: number; // transfers submitted in current event window
  summary_event_transfers_cost: number;
}

/** One gameweek entry in history.current */
export interface FplGwHistoryEntry {
  event: number;
  event_transfers: number;
  event_transfers_cost: number;
}

/** One played chip in history.chips */
export interface FplChipHistoryEntry {
  name: string;  // FPL chip code: 'wildcard' | '3xc' | 'bboost' | 'freehit'
  event: number;
}

/** Minimal fields we consume from GET /api/entry/{id}/history/ */
export interface FplHistoryRaw {
  current: FplGwHistoryEntry[];    // one entry per completed GW this season
  chips: FplChipHistoryEntry[];    // chips used this season
}

/** Combined response from our proxy GET /api/fpl-entry/{teamId} */
export interface FplEntryResponse {
  entry: FplEntryRaw;
  history: FplHistoryRaw;
}

// ---------------------------------------------------------------------------
// Free transfer selector options (used by SquadContextPanel)
// ---------------------------------------------------------------------------

/**
 * Options for the free-transfers selector.
 * null = not set (backend treats as unknown; no hit_warning signal).
 * 1–5 covers the full FPL-allowed range.
 */
export const FT_OPTIONS: Array<number | null> = [null, 1, 2, 3, 4, 5];

// ---------------------------------------------------------------------------
// Chip name mapping
// ---------------------------------------------------------------------------

/**
 * Maximum number of times each FPL chip can be used per season.
 * Wildcard is 2 (one per half-season); all others are 1.
 */
const FPL_CHIP_MAX_USES: Record<string, number> = {
  wildcard: 2,
  '3xc':    1,
  bboost:   1,
  freehit:  1,
};

/** Maps FPL API chip codes to backend SquadContext chip name strings. */
const FPL_TO_BACKEND_CHIP: Record<string, string> = {
  wildcard: 'wildcard',
  '3xc':    'triple_captain',
  bboost:   'bench_boost',
  freehit:  'free_hit',
};

// ---------------------------------------------------------------------------
// Public pure functions
// ---------------------------------------------------------------------------

/**
 * Parse and validate a user-supplied team ID string.
 *
 * Returns the positive integer value, or null if the input is not a valid
 * FPL team ID (non-numeric, zero, negative, or implausibly large).
 *
 * FPL team IDs are sequential integers starting at 1. The upper bound of
 * 20,000,000 covers the current total FPL player base with headroom.
 */
export function validateTeamId(input: string): number | null {
  const trimmed = input.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const n = parseInt(trimmed, 10);
  if (n <= 0 || n > 20_000_000) return null;
  return n;
}

/**
 * Derive a SquadContext from the raw FPL entry and history data.
 *
 * This is the single normalization point between the FPL API and the
 * backend SquadContext shape. All field derivation lives here.
 */
export function normalizeSquadContext(
  entry: FplEntryRaw,
  history: FplHistoryRaw,
): SquadContext {
  // --- itb ---
  // last_deadline_bank is already in tenths of £, matching now_cost units.
  const itb: number | null = entry.last_deadline_bank ?? null;

  // --- free_transfers ---
  // Not derivable from the FPL public API with confidence.
  // Must be provided explicitly by the user. See module comment.
  const free_transfers: null = null;

  // --- chips_remaining ---
  // Count how many times each chip has been used this season.
  const usedCount = new Map<string, number>();
  for (const c of history.chips) {
    usedCount.set(c.name, (usedCount.get(c.name) ?? 0) + 1);
  }

  const chips_remaining: string[] = [];
  for (const [fplName, maxUses] of Object.entries(FPL_CHIP_MAX_USES)) {
    const used = usedCount.get(fplName) ?? 0;
    if (used < maxUses) {
      const backendName = FPL_TO_BACKEND_CHIP[fplName];
      // Only add each backend chip name once (wildcard: if either half still available)
      if (backendName && !chips_remaining.includes(backendName)) {
        chips_remaining.push(backendName);
      }
    }
  }

  return { itb, free_transfers, chips_remaining };
}

/**
 * Display label for a squad context — shown in SquadContextPanel header.
 * Returns null when context is not yet loaded.
 */
export function squadContextSummary(entry: FplEntryRaw): string {
  return `${entry.name} (${entry.player_first_name} ${entry.player_last_name})`;
}
