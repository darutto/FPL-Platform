/**
 * defensive-zones.ts — pure helpers for the Defensive Zones card (T4b).
 *
 * No React, no DOM — imported by DefensiveZonesCard.tsx and unit-tested
 * directly (Jest, no jsdom needed for these).
 *
 * Color semantics (design handoff, authoritative — do not invert):
 * zone/bar color encodes the USER's attacking opportunity — turquoise
 * ('opp') = best zone, gold/amber ('warm') = slight advantage, grey
 * ('cool') = none. The card's header pill uses the same coding; no coral/red
 * anywhere on the card — the card is the user's opportunity, never a warning.
 */
import type {
  DefensiveZoneCell,
  OpportunityLevel,
  ZoneLateral,
} from './types';
import { translate, type DictKey } from './i18n/dictionary';
import { DEFAULT_LOCALE, type Locale } from './i18n/locale';

// ---------------------------------------------------------------------------
// Opportunity level → labels and token classes
// ---------------------------------------------------------------------------

const LEVEL_PILL_KEYS: Record<OpportunityLevel, DictKey> = {
  opp: 'z.level.opp',
  warm: 'z.level.warm',
  cool: 'z.level.cool',
};

/** Rank-pill copy for a level (handoff §Per-zone readings), in the language showing. */
export function levelPillLabel(level: OpportunityLevel, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, LEVEL_PILL_KEYS[level]);
}

/** The same in Spanish, the default language. */
export const LEVEL_PILL_LABEL: Record<OpportunityLevel, string> = {
  opp: levelPillLabel('opp'),
  warm: levelPillLabel('warm'),
  cool: levelPillLabel('cool'),
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

const LATERAL_KEYS: Record<ZoneLateral, DictKey> = {
  left: 'z.lat.left',
  central: 'z.lat.central',
  right: 'z.lat.right',
};

const LATERAL_SHORT_KEYS: Record<ZoneLateral, DictKey> = {
  left: 'z.latShort.left',
  central: 'z.latShort.central',
  right: 'z.latShort.right',
};

/** Column heading under the pitch — the flank you attack down, as drawn
 *  (attacker faces the goal at the top; attacker's left = viewer's left). */
export function lateralLabel(lateral: ZoneLateral, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, LATERAL_KEYS[lateral]);
}

/** The same in Spanish, the default language. */
export const LATERAL_LABEL: Record<ZoneLateral, string> = {
  left: lateralLabel('left'),
  central: lateralLabel('central'),
  right: lateralLabel('right'),
};

/** Short flank name ('Izq' / 'Left'), or null for a key that is not a flank. */
function lateralShort(lateral: string | undefined, locale: Locale): string | null {
  const key = LATERAL_SHORT_KEYS[lateral as ZoneLateral];
  return key ? translate(locale, key) : null;
}

/**
 * Table zone-pill label from an engine zone key ('in-box / left' → 'Izq' / 'Left').
 * Edge-of-box zones are prefixed: 'edge-of-box / left' → 'Frontal izq' / 'Edge left'.
 */
export function zonePillLabel(zone: string, locale: Locale = DEFAULT_LOCALE): string {
  const [depth, lateral] = zone.split(' / ');
  const short = lateralShort(lateral, locale);
  if (short == null) return zone;
  return depth === 'edge-of-box' ? `${translate(locale, 'z.depth.edge')} ${short.toLowerCase()}` : short;
}

/**
 * Opportunity level for an exploiter's zone, looked up from the pitch cells
 * so the table reinforces the pitch coding. Edge-of-box zones read their
 * `frontal` cell; payloads predating `frontal_zones` have none, so they read
 * 'warm' (the zone was still a weak one).
 */
export function levelForZone(
  zone: string,
  zones: DefensiveZoneCell[],
  frontal: DefensiveZoneCell[] = [],
): OpportunityLevel {
  const [depth, lateral] = zone.split(' / ');
  const cells = depth === 'in-box' ? zones : depth === 'edge-of-box' ? frontal : [];
  const cell = cells.find((z) => z.lateral === lateral);
  return cell != null ? cell.opportunity_level : 'warm';
}

// ---------------------------------------------------------------------------
// Player "Zonas" section (Bloque 10) — PlayerCard
// ---------------------------------------------------------------------------

/**
 * A zone's share of the player's non-penalty xG as a whole percentage.
 * The backend/contract carry a 0–1 FRACTION; this is the ONE place it
 * becomes a percentage (0.5923 → 59). Never feed it an already-converted value.
 */
export function sharePercent(share: number): number {
  return Math.round(share * 100);
}

const DEPTH_KEYS: Record<string, DictKey> = {
  'in-box': 'z.depth.box',
  'edge-of-box': 'z.depth.edge',
};

/**
 * Chip label for ANY of the six engine zone keys ('in-box / central' →
 * 'Área centro', 'edge-of-box / left' → 'Frontal izq'; English 'Box centre', 'Edge left'). Unlike
 * zonePillLabel, central keeps its depth so 'Área centro' and
 * 'Frontal centro' never read the same. Unknown keys pass through.
 */
export function zoneChipLabelFor(zone: string, locale: Locale): string {
  const [depth, lateral] = zone.split(' / ');
  const short = lateralShort(lateral, locale);
  const depthKey = DEPTH_KEYS[depth];
  if (short == null || depthKey == null) return zone;
  return `${translate(locale, depthKey)} ${short.toLowerCase()}`;
}

/** The Spanish chip label. One argument on purpose: it is passed straight to `.map(...)`. */
export function zoneChipLabel(zone: string): string {
  return zoneChipLabelFor(zone, DEFAULT_LOCALE);
}

/**
 * Where an engine zone key sits on the player mini-pitch: row 0 = in the box,
 * row 1 = the edge-of-box band in front of it; col 0/1/2 = left/central/right
 * in the attacker frame (attacker's left = viewer's left). Unknown keys → null.
 */
export function pitchCell(zone: string): { row: 0 | 1; col: 0 | 1 | 2 } | null {
  const [depth, lateral] = zone.split(' / ');
  const row = depth === 'in-box' ? 0 : depth === 'edge-of-box' ? 1 : null;
  const col = lateral === 'left' ? 0 : lateral === 'central' ? 1 : lateral === 'right' ? 2 : null;
  if (row === null || col === null) return null;
  return { row, col };
}

// ---------------------------------------------------------------------------
// Player sub-line
// ---------------------------------------------------------------------------

const POSITION_KEYS: Record<string, DictKey> = {
  GKP: 'z.pos.GKP',
  DEF: 'z.pos.DEF',
  MID: 'z.pos.MID',
  FWD: 'z.pos.FWD',
};

/** FPL position code → display code in the language showing (Spanish 'MID' → 'MED'; English unchanged). '' stays ''. */
export function positionEs(position: string, locale: Locale = DEFAULT_LOCALE): string {
  const key = POSITION_KEYS[position];
  return key ? translate(locale, key) : position;
}

/**
 * 'ARS · MED' sub-line; degrades gracefully when the backend name join
 * missed (empty team_short/position segments are dropped, never rendered
 * as dangling separators).
 *
 * i75: `clubNote` ("antes en BUR") rides inside the club segment —
 * 'BRE (antes en BUR) · MED' — so a player the store still files under his
 * old club reads with his current one and says where the data came from.
 * Never rendered without a club to attach to.
 */
export function exploiterSub(
  teamShort: string,
  position: string,
  clubNote?: string | null,
  locale: Locale = DEFAULT_LOCALE,
): string {
  const club = teamShort && clubNote ? `${teamShort} (${clubNote})` : teamShort;
  return [club, positionEs(position, locale)].filter(Boolean).join(' · ');
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
