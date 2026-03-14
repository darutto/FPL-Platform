/**
 * fpl-api-client · packages/fpl-api-client/typescript/src/csvLoader.ts
 * ======================================================================
 * Unified CSV loader with in-memory caching and Papa Parse integration.
 *
 * SOURCE:  Promoted from:
 *   - captaincy-showdown/src/services/dataClient.ts    (empty file — was a placeholder)
 *   - captaincy-showdown/src/services/cache.ts         (in-memory cache)
 *   - captaincy-showdown/src/utils/dataLoader.ts       (loadCSVData — the real implementation)
 *   - captaincy-showdown/src/services/http.ts          (empty placeholder)
 *
 * REPLACES (do NOT delete originals until migration is approved):
 *   - captaincy-showdown/src/utils/dataLoader.ts  → remove & import from here
 *   - captaincy-showdown/src/services/cache.ts    → remove & import from here
 *
 * CONSUMERS AFTER MIGRATION:
 *   - captaincy-showdown/src/utils/performanceEnricher.ts
 *   - captaincy-showdown/src/services/captaincyDataService.ts
 *   - any new app that reads local CSV files
 */

// NOTE: This module depends on Papa Parse.
// In browser environments: import Papa from 'papaparse'
// In Node environments:    npm install papaparse

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CsvLoaderOptions {
  /** Papa Parse dynamicTyping — auto-converts numbers. Default: true. */
  dynamicTyping?: boolean;
  /** Strip leading/trailing whitespace from values. Default: true. */
  skipEmptyLines?: boolean;
}

// ---------------------------------------------------------------------------
// In-memory cache
// ---------------------------------------------------------------------------

const _cache = new Map<string, unknown[]>();

export function clearCache(): void {
  _cache.clear();
}

export function getCacheSize(): number {
  return _cache.size;
}

// ---------------------------------------------------------------------------
// CSV loading
// ---------------------------------------------------------------------------

/**
 * Load and parse a CSV file from a URL. Results are cached by URL.
 *
 * SOURCE: captaincy-showdown/src/utils/dataLoader.ts::loadCSVData
 *         captaincy-showdown/src/services/cache.ts
 */
export async function loadCSVData<T>(
  url: string,
  options: CsvLoaderOptions = {}
): Promise<T[]> {
  if (_cache.has(url)) {
    return _cache.get(url) as T[];
  }

  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`CSV load failed (${resp.status}): ${url}`);
  }
  const text = await resp.text();

  // Dynamic import so bundlers can tree-shake if CSV loading isn't used
  const Papa = await import("papaparse").then(m => m.default ?? m);

  const result = Papa.parse<T>(text, {
    header: true,
    dynamicTyping: options.dynamicTyping ?? true,
    skipEmptyLines: options.skipEmptyLines ?? true,
  });

  if (result.errors.length > 0) {
    console.warn(`CSV parse warnings for ${url}:`, result.errors.slice(0, 3));
  }

  _cache.set(url, result.data);
  return result.data;
}

// ---------------------------------------------------------------------------
// Path helper (mirrors csvPathConfig.ts — single source of truth)
// ---------------------------------------------------------------------------

export type DataType =
  | "playerstats"
  | "players"
  | "teams"
  | "matches"
  | "fixtures"
  | "playermatchstats";

export interface CsvPathOptions {
  season?: string;      // e.g. "2025-2026"
  gameweek?: number;    // e.g. 1
  tournament?: string;  // e.g. "Premier League"
  dataType: DataType;
}

/**
 * Generate the URL path to a FPL data CSV file.
 *
 * SOURCE: captaincy-showdown/src/utils/csvPathConfig.ts::getCsvPath (full file, lines 11-34)
 *
 * IMPORTANT: This is the canonical implementation. The copy in
 *   captaincy-showdown/src/utils/csvPathConfig.ts should be deleted
 *   and replaced with an import from this package after migration.
 */
export function getCsvPath({
  season = "2025-2026",
  gameweek,
  tournament,
  dataType,
}: CsvPathOptions): string {
  if (gameweek !== undefined) {
    if (dataType === "matches" || dataType === "fixtures") {
      if (season === "2024-2025") {
        return `/data/${season}/matches/GW${gameweek}/matches.csv`;
      }
      return `/data/${season}/By Gameweek/GW${gameweek}/fixtures.csv`;
    }
    return `/data/${season}/By Gameweek/GW${gameweek}/${dataType}.csv`;
  }
  if (tournament) {
    return `/data/${season}/By Tournament/${tournament}/${dataType}.csv`;
  }
  if (season === "2024-2025") {
    return `/data/${season}/${dataType}/${dataType}.csv`;
  }
  return `/data/${season}/${dataType}.csv`;
}


