/**
 * CardOrnaments — Bendito Fantasy pop-art card decoration (Stitch Hi-Fi).
 *
 * Two purely decorative, fixed-pixel SVG motifs used behind card content:
 *   - TriangleField: uniform halftone triangle grid fading toward the card
 *     centre (momentum / pick cards).
 *   - FingerprintWaves: faint sine-modulated concentric arcs (analytical /
 *     comparison cards).
 *
 * Fixed pixel dimensions — never stretch with the card, so the pattern stays
 * symmetric at any width. aria-hidden: no semantics, pointer-events none.
 * Colors come from lib/theme ACCENT_HEX (token mirror), never hardcoded here.
 */

type Corner = 'tl' | 'tr' | 'bl' | 'br';

const TRIANGLE_POS: Record<Corner, React.CSSProperties> = {
  tl: { top: 0, left: 0, transform: 'none' },
  tr: { top: 0, right: 0, transform: 'scaleX(-1)' },
  bl: { bottom: 0, left: 0, transform: 'scaleY(-1)' },
  br: { bottom: 0, right: 0, transform: 'scale(-1,-1)' },
};

export function TriangleField({
  color,
  corner = 'tr',
}: {
  color: string;
  corner?: Corner;
}) {
  const COLS = 12;
  const ROWS = 9;
  const STEP_X = 18;
  const STEP_Y = 17;
  const SIZE = 6;
  const W = COLS * STEP_X;
  const H = ROWS * STEP_Y;
  const tris: Array<[number, number, number]> = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      // distance from the anchor corner, normalised — fades toward card centre
      const d = Math.sqrt((c / (COLS - 1)) ** 2 + (r / (ROWS - 1)) ** 2) / Math.SQRT2;
      const o = Math.max(0, 0.32 * (1 - d) ** 1.4);
      if (o < 0.012) continue;
      const x = c * STEP_X + (r % 2 ? STEP_X / 2 : 0) + 4;
      const y = r * STEP_Y + 4;
      tris.push([x, y, o]);
    }
  }
  return (
    <svg
      aria-hidden="true"
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      className="pointer-events-none absolute"
      style={TRIANGLE_POS[corner]}
    >
      {tris.map(([x, y, o], i) => (
        <polygon
          key={i}
          points={`${x},${y + SIZE} ${x + SIZE},${y + SIZE} ${x + SIZE / 2},${y}`}
          fill={color}
          opacity={o}
        />
      ))}
    </svg>
  );
}

const WAVE_POS: Record<Corner, React.CSSProperties> = {
  tl: { top: 0, left: 0, transform: 'scaleY(-1)' },
  tr: { top: 0, right: 0, transform: 'scale(-1,-1)' },
  bl: { bottom: 0, left: 0, transform: 'none' },
  br: { bottom: 0, right: 0, transform: 'scaleX(-1)' },
};

export function FingerprintWaves({
  color,
  corner = 'bl',
}: {
  color: string;
  corner?: Corner;
}) {
  const W = 260;
  const H = 170;
  const RINGS = 11;
  const BASE = 24;
  const STEP = 16;
  const SEGMENTS = 40;
  const FREQ = 3.2;
  const AMP = 6;
  const paths: Array<{ d: string; o: number }> = [];
  for (let i = 0; i < RINGS; i++) {
    const r = BASE + i * STEP;
    // alternate phase so adjacent rings undulate against each other
    const phase = i % 2 ? Math.PI / FREQ : 0;
    let d = '';
    for (let s = 0; s <= SEGMENTS; s++) {
      const t = s / SEGMENTS;
      const a = t * (Math.PI / 2);
      const wave = Math.sin(t * Math.PI * FREQ + phase) * AMP;
      const rr = r + wave;
      const x = Math.cos(a) * rr;
      const yy = H - Math.sin(a) * rr;
      d += (s === 0 ? 'M' : 'L') + ` ${x.toFixed(2)} ${yy.toFixed(2)} `;
    }
    paths.push({ d, o: Math.max(0.12, 0.32 - i * 0.02) });
  }
  return (
    <svg
      aria-hidden="true"
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      className="pointer-events-none absolute"
      style={WAVE_POS[corner]}
    >
      {paths.map((p, i) => (
        <path
          key={i}
          d={p.d}
          stroke={color}
          strokeWidth="1.4"
          fill="none"
          opacity={p.o}
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}
