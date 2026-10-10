/**
 * PlayerZonesPitch — mini-pitch for the «Zonas» section of PlayerCard (i152).
 *
 * Draws all SIX engine zones (in the box and the edge-of-box band in front of
 * it, each left / central / right) on the same box geometry the defensive
 * zones card uses (PitchGeometry). Only zones where the player concentrates
 * xG are shaded; no zone, no pitch.
 *
 *   turquoise = the player's zone coincides with a weak zone of a favorable
 *               pending rival (fixtures[].matches)
 *   neutral   = the player's zone with no such coincidence
 *   (never red; an undrawn zone is simply not the player's)
 *
 * `share` arrives as a 0–1 fraction; it only drives the shade, and the label
 * inside the cell uses the single % conversion (sharePercent).
 */
import type { PlayerZonalFixture, PlayerZonalZone } from '@/lib/types';
import {
  ZONE_SHADE_HEX,
  pitchCell,
  sharePercent,
  zoneChipLabel,
} from '@/lib/defensive-zones';
import { PitchLines, ZONE_X, ZONE_WIDTH, ZONE_CENTER_X } from './PitchGeometry';

interface Props {
  zones: PlayerZonalZone[];
  fixtures: PlayerZonalFixture[];
}

/** Row geometry in SVG units: the box rows then the frontal band under it. */
const ROW_Y = [26, 176];
const ROW_H = [150, 130];
const VIEW_H = 316;
/** Baseline drop under each row's middle; the box row also clears the six-yard box and the goal at its top. */
const LABEL_DROP = [24, 10];

const MATCH_HEX = ZONE_SHADE_HEX.opp;
const NEUTRAL_HEX = ZONE_SHADE_HEX.cool;

/** Shade strength from the 0–1 share, clamped so a cell never becomes a block. */
export function cellOpacity(share: number, matched: boolean): number {
  const s = Math.min(Math.max(share, 0), 1);
  return matched ? 0.2 + 0.32 * s : 0.1 + 0.25 * s;
}

export default function PlayerZonesPitch({ zones, fixtures }: Props) {
  const matched = new Set<string>();
  for (const f of fixtures) {
    if (f.status !== 'favorable') continue;
    for (const m of f.matches) matched.add(m.zone);
  }

  const cells = zones
    .filter((z) => Number.isFinite(z.share) && pitchCell(z.zone) !== null)
    .map((z) => ({ ...z, cell: pitchCell(z.zone)!, hit: matched.has(z.zone) }));
  if (cells.length === 0) return null;

  const label = cells
    .map(
      (c) =>
        `${zoneChipLabel(c.zone)}: ${sharePercent(c.share)}% de su xG${
          c.hit ? ' (coincide con un cruce favorable)' : ''
        }`,
    )
    .join(' · ');

  return (
    <svg
      data-testid="player-zones-pitch"
      viewBox={`0 0 360 ${VIEW_H}`}
      className="block h-auto w-full"
      role="img"
      aria-label={label}
    >
      {/* frontal band outline, under the shaded cells */}
      <rect x="30" y={ROW_Y[1]} width="300" height={ROW_H[1]} fill="none" stroke="rgba(255,255,255,.10)" strokeWidth="1.5" strokeDasharray="4 5" />
      {cells.map((c) => (
        <rect
          key={c.zone}
          data-testid={`pitch-cell-${c.zone.replace(/[^a-z]+/g, '-')}`}
          data-match={c.hit ? 'true' : 'false'}
          x={ZONE_X[c.cell.col]}
          y={ROW_Y[c.cell.row]}
          width={ZONE_WIDTH}
          height={ROW_H[c.cell.row]}
          fill={c.hit ? MATCH_HEX : NEUTRAL_HEX}
          fillOpacity={cellOpacity(c.share, c.hit)}
          stroke={c.hit ? MATCH_HEX : 'none'}
          strokeOpacity={0.7}
          strokeWidth={c.hit ? 2 : 0}
        />
      ))}
      <PitchLines />
      {cells.map((c) => (
        <text
          key={`t-${c.zone}`}
          x={ZONE_CENTER_X[c.cell.col]}
          y={ROW_Y[c.cell.row] + ROW_H[c.cell.row] / 2 + LABEL_DROP[c.cell.row]}
          textAnchor="middle"
          fill={c.hit ? MATCH_HEX : '#ABA9AC'}
          style={{ fontSize: 28, fontWeight: 900, letterSpacing: '-1px' }}
        >
          {sharePercent(c.share)}%
        </text>
      ))}
    </svg>
  );
}
