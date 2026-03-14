/**
 * fpl-charts · packages/fpl-charts/src/theme.ts
 * ================================================
 * Canonical brand design tokens. Single source of truth for all FPL app styling.
 *
 * SOURCE:  Consolidated from:
 *   - Top stats per week FPL/styles/main.css     (CSS custom properties, lines 1-15)
 *   - captaincy-showdown/src/brand.ts            (BRAND object, lines 1-9)
 *   - captaincy-showdown/src/index.css           (Tailwind CSS variable overrides)
 *
 * REPLACES (do NOT delete originals until migration is approved):
 *   - captaincy-showdown/src/brand.ts            → import BRAND from here
 *   - Top stats per week FPL/styles/main.css      → import CSS variables from here
 *
 * CONSUMERS AFTER MIGRATION:
 *   - All React apps in fpl-platform/apps/
 *   - Top stats per week FPL (converted to use CSS custom properties from here)
 *   - OBS streaming overlay templates
 */

// ---------------------------------------------------------------------------
// Brand colour palette
// SOURCE: Top stats per week FPL/styles/main.css -- CSS custom properties
// ---------------------------------------------------------------------------

export const COLORS = {
  /** Primary accent — coral/orange. Used for progress bars, highlights, CTAs. */
  coral:  "#FF6A4D",

  /** Secondary accent — mint green. Used for positive deltas, scores, badges. */
  green:  "#02EBAE",

  /** Primary background — near-black purple. App backgrounds, card bases. */
  dark:   "#211F29",

  /** Tertiary accent — muted teal/blue. Used for secondary panels, borders. */
  blue:   "#1F4B59",

  /** Gold — used for rankings, trophy icons, top-pick highlights. */
  golden: "#F2C572",

  /** Pure white with opacity helpers */
  white:  "#FFFFFF",
} as const;

/** CSS custom property names — use with var(--color-brand-*) in stylesheets. */
export const CSS_VARS = {
  coral:  "--color-brand-coral",
  green:  "--color-brand-green",
  dark:   "--color-brand-dark",
  blue:   "--color-brand-blue",
  golden: "--color-brand-golden",
} as const;

/** Inject CSS custom properties into :root. Call once at app startup. */
export function injectCssVars(root: HTMLElement = document.documentElement): void {
  root.style.setProperty(CSS_VARS.coral,  COLORS.coral);
  root.style.setProperty(CSS_VARS.green,  COLORS.green);
  root.style.setProperty(CSS_VARS.dark,   COLORS.dark);
  root.style.setProperty(CSS_VARS.blue,   COLORS.blue);
  root.style.setProperty(CSS_VARS.golden, COLORS.golden);
}

// ---------------------------------------------------------------------------
// Brand config object  (SOURCE: captaincy-showdown/src/brand.ts — unchanged)
// ---------------------------------------------------------------------------

export const BRAND = {
  /** Primary background for the app and exports */
  background:       COLORS.dark,
  /** Default watermark SVG path */
  watermarkSrc:     "/logos-and-brand-art/watermark.svg",
  /** Canvas background for screenshot exports */
  exportBackground: COLORS.dark,
} as const;

// ---------------------------------------------------------------------------
// Chart colour palette (for Chart.js and custom bar charts)
// SOURCE: FPL-team-stats/script.js (inline color array used in Chart.js datasets)
// ---------------------------------------------------------------------------

export const CHART_COLORS: string[] = [
  COLORS.coral,
  COLORS.green,
  COLORS.golden,
  "#6C63FF",  // purple
  "#FF9671",  // light coral
  "#00C9A7",  // teal
  "#845EC2",  // violet
  "#FF6F91",  // pink
  "#0089BA",  // sky blue
  "#FFC75F",  // amber
];

// ---------------------------------------------------------------------------
// Risk indicator colours (used in PlayerCard)
// SOURCE: captaincy-showdown/src/components/PlayerCard.tsx::getRiskIndicator
// ---------------------------------------------------------------------------

export const RISK = {
  low:    { color: "#34D399", label: "Low Risk"    },
  medium: { color: "#FBBF24", label: "Medium Risk" },
  high:   { color: "#F87171", label: "High Risk"   },
} as const;

export function getRiskLevel(minutesRisk: number): keyof typeof RISK {
  if (minutesRisk <= 20) return "low";
  if (minutesRisk <= 60) return "medium";
  return "high";
}


