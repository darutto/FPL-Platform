/**
 * defensive-zones.ts — pure helpers for the Defensive Zones card (T4b).
 *
 * No React, no DOM — imported by DefensiveZonesCard.tsx and unit-tested
 * directly (Jest, no jsdom needed for these).
 *
 * Color semantics (design handoff, authoritative — do not invert):
 * zone/bar color encodes the USER's attacking opportunity — turquoise
 * ('opp') = best zone, gold/amber ('warm') = slight advantage, grey
 * ('cool') = none. Coral is reserved for the opponent-weakness label pill;
 * never red/coral for a strong zone (red reads as "avoid").
 */
import type {
  DefensiveZoneCell,
  OpportunityLevel,
  ZoneLateral,
} from './types';

// ---------------------------------------------------------------------------
// Opportunity level → labels and token classes
// ---------------------------------------------------------------------------

/** Rank-pill copy per level (handoff §Per-zone readings). */
export const LEVEL_PILL_LABEL: Record<OpportunityLevel, string> = {
  opp: 'tu mejor zona',
  warm: 'ventaja leve',
  cool: 'sin ventaja',
};

/** Text color token per level — big % value, zone label, table numbers. */
export const LEVEL_TEXT_CLASS: Record<OpportunityLevel, string> = {
  opp: 'text-bf-turquoise',
  warm: 'text-bf-gold',
  cool: 'text-bf-gray',
};

/** Tinted pill classes per level (mirrors theme.ts pill tinting). */
export const LEVEL_PILL_CLASS: Record<OpportunityLevel, string> = {
  opp: 'bg-bf-turquoise/10 border-bf-turquoise/40 text-bf-turquoise',
  warm: 'bg-bf-gold/10 border-bf-gold/40 text-bf-gold',
  cool: 'bg-bf-gray/10 border-bf-gray/40 text-bf-gray',
};

/**
 * Zone-shade fill per level — the same palette the card already uses
 * everywhere else (bf-turquoise, bf-gold, and the muted grey from the
 * original handoff bars). SVG fills can't come from utility classes.
 */
export const ZONE_SHADE_HEX: Record<OpportunityLevel, string> = {
  opp: '#02EBAE',
  warm: '#F2C572',
  cool: '#6b6975',
};

/** Base wash opacity per level — the floor before pct scaling.
 *  Tuned down 2026-07-09: the first pass read too dark; the wash should be
 *  a light tint the pct text sits on, not a saturated block. */
const ZONE_SHADE_FLOOR: Record<OpportunityLevel, number> = {
  opp: 0.16,
  warm: 0.09,
  cool: 0.05,
};

/** Ceiling so an extreme outlier zone never becomes a solid block. */
export const ZONE_SHADE_MAX_OPACITY = 0.34;

/** Extra opacity gained per +100% over the league average. */
const ZONE_SHADE_PCT_GAIN = 0.22;

/**
 * Shade opacity for a zone region: a level-keyed floor plus a component
 * that scales with the zone's strength, so the strongest zone reads as the
 * most saturated (e.g. opp at +70% → ≈0.31 — a light tint, not a block).
 * Cool zones stay a flat faint wash — "below average" carries no intensity
 * to encode.
 */
export function zoneShadeOpacity(
  level: OpportunityLevel,
  pctOverAvg: number,
): number {
  const base = ZONE_SHADE_FLOOR[level];
  if (level === 'cool') return base;
  return Math.min(
    ZONE_SHADE_MAX_OPACITY,
    base + (Math.max(pctOverAvg, 0) / 100) * ZONE_SHADE_PCT_GAIN,
  );
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/**
 * Big per-zone reading: '+70%' for a real edge; anything below +0.5%
 * (including negative values) reads '≈ 0%' — the card encodes opportunity,
 * and "less than average" is simply no advantage, not a negative one.
 */
export function formatPct(pct: number): string {
  if (pct >= 0.5) return `+${Math.round(pct)}%`;
  return '≈ 0%';
}

/**
 * True when a zone has no real edge (below +0.5% over average, incl.
 * negatives) — the in-box reading then shows a muted '≈ media' instead of
 * numbers. Mirrors formatPct's rounding cutoff.
 */
export function isAverageZone(pctOverAvg: number): boolean {
  return pctOverAvg < 0.5;
}

/**
 * Small precise delta under the big in-box reading: one decimal, always
 * signed, typographic minus (e.g. '+69.8%', '−31.7%').
 */
export function formatDeltaFine(pctOverAvg: number): string {
  const sign = pctOverAvg >= 0 ? '+' : '−';
  return `${sign}${Math.abs(pctOverAvg).toFixed(1)}%`;
}

/** Ajuste column: one decimal, e.g. '8.7'. */
export function formatFit(fit: number): string {
  return fit.toFixed(1);
}

/** Footer penalty value, e.g. '0.140'. */
export function formatPenalty(xga: number): string {
  return xga.toFixed(3);
}

/**
 * Row fade per the handoff (rank number + score opacity 1 → .85 → .72,
 * then held at .72 for deeper rows).
 */
export function rankOpacity(rank: number): number {
  if (rank <= 1) return 1;
  if (rank === 2) return 0.85;
  return 0.72;
}

// ---------------------------------------------------------------------------
// Zone naming (attacker frame → display Spanish)
// ---------------------------------------------------------------------------

/** Column headings under the pitch — the flank you attack down, as drawn
 *  (attacker faces the goal at the top; attacker's left = viewer's left). */
export const LATERAL_LABEL: Record<ZoneLateral, string> = {
  left: 'Izquierda',
  central: 'Centro',
  right: 'Derecha',
};

const LATERAL_SHORT: Record<ZoneLateral, string> = {
  left: 'Izq',
  central: 'Centro',
  right: 'Der',
};

/**
 * Table zone-pill label from an engine zone key ('in-box / left' → 'Izq').
 * Edge-of-box zones (possible in weakest_zones but not on the pitch view)
 * are prefixed: 'edge-of-box / left' → 'Frontal izq'.
 */
export function zonePillLabel(zone: string): string {
  const [depth, lateral] = zone.split(' / ');
  const short = LATERAL_SHORT[lateral as ZoneLateral];
  if (short == null) return zone;
  return depth === 'edge-of-box' ? `Frontal ${short.toLowerCase()}` : short;
}

/**
 * Opportunity level for an exploiter's zone, looked up from the in-box
 * cells so the table reinforces the pitch coding. Edge-of-box zones have
 * no cell — they were still a weak zone, so they read 'warm'.
 */
export function levelForZone(
  zone: string,
  zones: DefensiveZoneCell[],
): OpportunityLevel {
  const [depth, lateral] = zone.split(' / ');
  if (depth === 'in-box') {
    const cell = zones.find((z) => z.lateral === lateral);
    if (cell != null) return cell.opportunity_level;
  }
  return 'warm';
}

// ---------------------------------------------------------------------------
// Player sub-line
// ---------------------------------------------------------------------------

const POSITION_ES: Record<string, string> = {
  GKP: 'POR',
  DEF: 'DEF',
  MID: 'MED',
  FWD: 'DEL',
};

/** FPL position code → Spanish display code ('MID' → 'MED'). '' stays ''. */
export function positionEs(position: string): string {
  return POSITION_ES[position] ?? position;
}

/**
 * 'ARS · MED' sub-line; degrades gracefully when the backend name join
 * missed (empty team_short/position segments are dropped, never rendered
 * as dangling separators).
 */
export function exploiterSub(teamShort: string, position: string): string {
  return [teamShort, positionEs(position)].filter(Boolean).join(' · ');
}

// ---------------------------------------------------------------------------
// Verdict highlighting
// ---------------------------------------------------------------------------

export interface VerdictSegment {
  text: string;
  highlight: boolean;
}

/**
 * Split the backend verdict so '+70%' style tokens can be bolded turquoise
 * (handoff bolds the headline pct). Pure string split — no HTML parsing.
 */
export function splitVerdict(verdict: string): VerdictSegment[] {
  return verdict
    .split(/([+-]\d+(?:[.,]\d+)?\s?%)/)
    .filter((part) => part.length > 0)
    .map((part) => ({
      text: part,
      highlight: /^[+-]\d+(?:[.,]\d+)?\s?%$/.test(part),
    }));
}
