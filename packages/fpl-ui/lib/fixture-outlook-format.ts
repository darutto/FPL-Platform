/**
 * Pure formatting helpers for the fixture outlook ticker (Track D / FI4).
 * Kept in a .ts (no JSX) so they're trivially unit-testable.
 *
 * Palette + labels follow the "Calendario FDR" readability design
 * (Bendito Fantasy design system) — see
 * .design-import/design_handoff_calendario_fdr/.
 */
import type { FixtureAxis } from './types';

export type Band = 1 | 2 | 3 | 4 | 5;

/** Difficulty band (1=easiest … 5=hardest) → hex colour (FDR ramp). */
export function bandColor(band: Band): string {
  const COLORS: Record<Band, string> = {
    1: '#02EBAE', // Fácil
    2: '#04C4D9', // Favorable
    3: '#F2C572', // Medio
    4: '#F27A5E', // Difícil
    5: '#FF6A4D', // Muy difícil
  };
  return COLORS[band];
}

/** Difficulty band → Spanish label used in the legend + tooltips. */
export function bandLabel(band: Band): string {
  const LABELS: Record<Band, string> = {
    1: 'Fácil',
    2: 'Favorable',
    3: 'Medio',
    4: 'Difícil',
    5: 'Muy difícil',
  };
  return LABELS[band];
}

/** Venue short marker: L = Local (home), V = Visitante (away). */
export function venueLabel(isHome: boolean): string {
  return isHome ? 'L' : 'V';
}

/** Colour for the neutral "blank gameweek" cell (no fixture). */
export const BLANK_COLOR = '#6b7280';

/** `#RRGGBB` + alpha → `rgba(...)`. Falls back to the hex on a bad input. */
export function hexRgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/** Axis → Spanish label for the card chip. */
export function axisLabel(axis: FixtureAxis): string {
  return axis === 'attack' ? 'Ataque' : 'Portería a cero';
}
