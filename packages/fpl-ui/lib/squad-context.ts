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
 *   The FPL public API does not expose the FT count directly (only the
 *   authenticated /my-team/ endpoint has it), but it is derivable from the
 *   public history — see deriveFreeTransfers(). The result is the FT count
 *   available at the NEXT deadline, before any transfers the user may have
 *   already queued for it (those are only visible when authenticated).
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
// Free transfer derivation
// ---------------------------------------------------------------------------

/** Maximum number of free transfers that can be banked (FPL rule since 2024-25). */
const FT_MAX = 5;
/** Points cost of one transfer beyond the free allowance. */
const HIT_COST = 4;
/** Chips whose gameweek transfers are unlimited and do not touch the FT bank. */
const FT_EXEMPT_CHIPS = new Set(['wildcard', 'freehit']);

/**
 * Derive the free transfers available at the next deadline from the public
 * season history.
 *
 * Rules (verified empirically against live 2026-27 entries, 17/17 teams that
 * played WC/FH consistent, see PR description):
 *   - The manager's first gameweek has unlimited transfers → 1 FT afterwards.
 *   - Every subsequent gameweek: FT = min(5, FT − free_used + 1), where
 *     free_used = event_transfers − event_transfers_cost / 4.
 *   - On a wildcard / free-hit gameweek the bank is HELD as-is: transfers are
 *     free and no +1 accrues for that week.
 *
 * Every entry in history.current has passed its deadline, so walking all of
 * them yields the allowance for the upcoming one.
 *
 * Returns null when the history is empty, or when the recorded transfers
 * contradict the model (e.g. a special unlimited-transfer gameweek) — an
 * unknown is better than a confident wrong number.
 */
export function deriveFreeTransfers(history: FplHistoryRaw): number | null {
  const gws = [...(history.current ?? [])].sort((a, b) => a.event - b.event);
  if (gws.length === 0) return null;

  const exemptEvents = new Set(
    (history.chips ?? []).filter((c) => FT_EXEMPT_CHIPS.has(c.name)).map((c) => c.event),
  );

  let ft = 1; // allowance after the (unlimited) first gameweek
  for (const gw of gws.slice(1)) {
    if (exemptEvents.has(gw.event)) continue;
    const paid = Math.floor(gw.event_transfers_cost / HIT_COST);
    const freeUsed = gw.event_transfers - paid;
    // Consistency check: free transfers used must be exactly what was available
    // (if a hit was taken) or at most what was available (if not).
    if (freeUsed !== Math.min(gw.event_transfers, ft)) return null;
    ft = Math.min(FT_MAX, ft - freeUsed + 1);
  }
  return ft;
}

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
  const free_transfers = deriveFreeTransfers(history);

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
