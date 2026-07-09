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
 * Intensity-bar visuals per level — inline styles for the SVG overlay
 * (gradients can't come from utility classes). Hex values are the handoff's
 * §Design Tokens: bf-turquoise, bf-gold, and the handoff's muted bar grey
 * #6b6975 (dimmer than bf-gray so an empty zone recedes).
 */
export const LEVEL_BAR_STYLE: Record<
  OpportunityLevel,
  { background: string; boxShadow?: string }
> = {
  opp: {
    background: 'linear-gradient(180deg,#02EBAE,rgba(2,235,174,.24))',
    boxShadow: '0 0 22px rgba(2,235,174,.4)',
  },
  warm: {
    background: 'linear-gradient(180deg,#F2C572,rgba(242,197,114,.25))',
  },
  cool: {
    background: 'linear-gradient(180deg,#6b6975,rgba(107,105,117,.2))',
  },
};

/**
 * Intensity-bar height per level, as % of the pitch container so the bars
 * scale with it. Derived from the handoff's px heights at 420px width
 * (container height 245px): opp 150px, warm 52px, cool 20px.
 */
export const LEVEL_BAR_HEIGHT_PCT: Record<OpportunityLevel, string> = {
  opp: '61.2%',
  warm: '21.2%',
  cool: '8.2%',
};

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

/** Column headings under the pitch, as drawn (goal at the top). */
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
