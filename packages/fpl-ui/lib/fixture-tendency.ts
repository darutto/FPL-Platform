/**
 * fixture-tendency — pure geometry + labelling for the FI5 tendency chart.
 * Kept dependency-free (no JSX) so the math is trivially unit-testable.
 *
 * "Reversed axis, good=up": bands are 1=easiest…5=hardest, so plotting the
 * raw band value would put GOOD weeks low on the chart — backwards from how
 * a trend line reads intuitively. bandY() inverts that: band 1 sits at the
 * TOP (y=0) and band 5 at the BOTTOM (y=height), so the line visibly rises
 * during good runs and dips during bad ones.
 */
import type { FixtureAxis, FixtureOutlookGW, OutlookClass } from './types';

/** Blank GWs (no fixture) get a neutral mid-chart value so the line stays
 *  continuous; the point itself is still flagged `blank` for hollow styling. */
const BLANK_BAND = 3;

/** y-coordinate for a band on a chart of the given height. Reversed: good (1) → top (0). */
export function bandY(band: number, height: number): number {
  const clamped = Math.max(1, Math.min(5, band));
  return ((clamped - 1) / 4) * height;
}

export interface TendencyPoint {
  gw: number;
  x: number;
  y: number;
  band: number | null;
  blank: boolean;
  klass: OutlookClass;
}

/** Lay out one point per gameweek across [0, width] x [0, height]. */
export function buildTendencyPoints(
  series: FixtureOutlookGW[],
  width: number,
  height: number,
): TendencyPoint[] {
  if (series.length === 0) return [];
  const step = series.length > 1 ? width / (series.length - 1) : 0;
  return series.map((gw, i) => {
    const blank = gw.band === null;
    const band = blank ? BLANK_BAND : (gw.band as number);
    return {
      gw: gw.gameweek,
      x: i * step,
      y: bandY(band, height),
      band: gw.band,
      blank,
      klass: gw.klass,
    };
  });
}

/** SVG polyline `points` attribute for a set of tendency points. */
export function tendencyPolyline(points: TendencyPoint[]): string {
  return points.map((p) => `${p.x},${p.y}`).join(' ');
}

/** Qualitative difficulty label — deliberately no fabricated probability
 *  number (Poisson/backtested probabilities are FI6, gated on Track A). */
export function qualitativeBandLabel(band: number | null, axis: FixtureAxis): string {
  if (band === null) return 'Sin partido esta jornada.';
  const upside = axis === 'attack' ? 'oportunidad de gol' : 'opción de portería a cero';
  const downside = axis === 'attack' ? 'partido complicado para marcar' : 'partido duro para la portería a cero';
  switch (band) {
    case 1:
      return `Dificultad muy baja — gran ${upside}.`;
    case 2:
      return `Dificultad baja — buena ${upside}.`;
    case 3:
      return 'Dificultad media.';
    case 4:
      return `Dificultad alta — ${downside}.`;
    default:
      return `Dificultad muy alta — ${downside}.`;
  }
}
