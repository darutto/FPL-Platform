/**
 * Pure formatting helpers for the fixture outlook ticker (Track D / FI4).
 * Kept in a .ts (no JSX) so they're trivially unit-testable.
 */
import type { FixtureAxis } from './types';

/** Difficulty band (1=easiest … 5=hardest) → hex colour (FDR ramp). */
export function bandColor(band: 1 | 2 | 3 | 4 | 5): string {
  const COLORS: Record<1 | 2 | 3 | 4 | 5, string> = {
    1: '#2ecc71',
    2: '#a8d8a8',
    3: '#f7f7a8',
    4: '#f4a262',
    5: '#e74c3c',
  };
  return COLORS[band];
}

/** Axis → Spanish label for the card chip. */
export function axisLabel(axis: FixtureAxis): string {
  return axis === 'attack' ? 'Ataque' : 'Portería a cero';
}
