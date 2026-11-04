/**
 * PositionPitch — the position-changes mini-pitch ("canchita") and its per-90 table, inside GenericCard.
 *
 * Two shapes, both from the backend's `position_pitch` payload (atomic_tool_cards._position_pitch):
 *   switch       old starting role (dashed ring) → new role (solid dot), joined by an arrow;
 *   fpl_listing  FPL's listed line (dashed tag, nobody played there) and the role actually played, joined by a quiet
 *                dotted link with NO arrowhead: nobody moved.
 * The pitch is its own vertical drawing in real proportions (68×105 m, one scale on both axes, so the circle stays a
 * circle), attack UP and the attacker's left on the viewer's left; the squad pitch keeps its own landscape drawing.
 * Roles are placed from provider role + side, never from the provider grid cell. Lines and the connector scale with
 * the pitch; dots and labels are HTML at fixed sizes, so the text never scales. The table is neutral: the value since
 * the change in bold, no colours, no +/−.
 */
import type { PitchRole, PositionPitchMeta } from '@/lib/types';
import { useLocale } from '@/lib/i18n/LocaleProvider';
import { fmt } from './InvolvementCompareCard';

/** Distance from the attacked goal (top), as a share of the pitch length, by provider role. */
const DEPTH: Record<string, number> = {
  Attacker: 0.17, 'Centre Forward': 0.17, 'Attacking Midfield': 0.33, 'Left Midfield': 0.4, 'Right Midfield': 0.4,
  'Central Midfield': 0.5, 'Defensive Midfield': 0.6, 'Left Back': 0.72, 'Right Back': 0.72, 'Centre Back': 0.79,
  Goalkeeper: 0.93,
};
/** Where an FPL listing sits when it is only a line. */
const LINE_DEPTH: Record<string, number> = { FWD: 0.17, MID: 0.45, DEF: 0.75, GKP: 0.93 };
const WIDE = new Set(['Left Midfield', 'Right Midfield', 'Left Back', 'Right Back']);

/** Position in percent of the pitch box (x across, y from the top), from role + side. */
export function placeRole(role: PitchRole, fallbackSide?: string | null): { x: number; y: number } {
  const pos = role.detailed_position ?? '';
  const side = role.side ?? fallbackSide ?? null;
  const y = 100 * (DEPTH[pos] ?? LINE_DEPTH[role.line ?? ''] ?? 0.5);
  const wide = WIDE.has(pos) || role.fpl_position != null;
  const x = side === 'left' ? (wide ? 16 : 36) : side === 'right' ? (wide ? 84 : 64) : 50;
  return { x, y };
}

// Vertical pitch, 240×360 user units (2:3 box): the field is 224×344 inside an 8-unit margin, ≈68×105 m at one scale.
const W = 240;
const H = 360;
const M = 8;
const K = 224 / 68; // units per metre
const ux = (p: number) => M + (p / 100) * (W - 2 * M);
const uy = (p: number) => M + (p / 100) * (H - 2 * M);
/** Field percent → percent of the whole box (where the HTML dots and labels sit). */
const box = (p: { x: number; y: number }) => ({ x: (100 * ux(p.x)) / W, y: (100 * uy(p.y)) / H });

/** Markings to scale: halfway line, centre circle and spot, both boxes, goal areas, penalty spots and arcs. */
export function VerticalPitchLines() {
  const cx = W / 2;
  const [box18w, box18d, box6w, box6d, spot, r] = [40.32 * K, 16.5 * K, 18.32 * K, 5.5 * K, 11 * K, 9.15 * K];
  const arcDx = Math.sqrt(r * r - (box18d - spot) ** 2);
  const ends = [
    { y0: M, dir: 1 },
    { y0: H - M, dir: -1 },
  ];
  return (
    <g fill="none" stroke="white" strokeWidth={1.5}>
      <rect x={M} y={M} width={W - 2 * M} height={H - 2 * M} strokeWidth={2} />
      <line x1={M} y1={H / 2} x2={W - M} y2={H / 2} />
      <circle cx={cx} cy={H / 2} r={r} />
      <circle cx={cx} cy={H / 2} r={1.5} fill="white" stroke="none" />
      {ends.map(({ y0, dir }) => {
        const line18 = y0 + dir * box18d;
        return (
          <g key={y0}>
            <rect x={cx - box18w / 2} y={dir > 0 ? y0 : line18} width={box18w} height={box18d} />
            <rect x={cx - box6w / 2} y={dir > 0 ? y0 : y0 - box6d} width={box6w} height={box6d} />
            <circle cx={cx} cy={y0 + dir * spot} r={1.5} fill="white" stroke="none" />
            <path d={`M${cx - arcDx} ${line18} A${r} ${r} 0 0 ${dir > 0 ? 0 : 1} ${cx + arcDx} ${line18}`} />
          </g>
        );
      })}
    </g>
  );
}

function Connector({ a, b, arrow }: { a: { x: number; y: number }; b: { x: number; y: number }; arrow: boolean }) {
  const [x1, y1, x2, y2] = [ux(a.x), uy(a.y), ux(b.x), uy(b.y)];
  const d = Math.hypot(x2 - x1, y2 - y1) || 1;
  const [dx, dy] = [(x2 - x1) / d, (y2 - y1) / d];
  const start = arrow ? 12 : 26;
  const [sx, sy, ex, ey] = [x1 + dx * start, y1 + dy * start, x2 - dx * 14, y2 - dy * 14];
  const head = `${ex},${ey} ${ex - dx * 9 - dy * 5},${ey - dy * 9 + dx * 5} ${ex - dx * 9 + dy * 5},${ey - dy * 9 - dx * 5}`;
  return arrow ? (
    <g data-connector="arrow">
      <line x1={sx} y1={sy} x2={ex - dx * 6} y2={ey - dy * 6} stroke="#04C4D9" strokeWidth={1.6} strokeDasharray="5 4"
        vectorEffect="non-scaling-stroke" />
      <polygon points={head} fill="#04C4D9" />
    </g>
  ) : (
    <line data-connector="link" x1={sx} y1={sy} x2={ex} y2={ey} stroke="rgba(171,169,172,.6)" strokeWidth={1.2}
      strokeDasharray="1.5 4" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
  );
}

// --- label placement: a label must not cross the halfway line, the centre circle or the connector -----------------
const PX = W / 280; // user units per CSS px at the narrowest box (labels are fixed-size HTML, so this is the worst case)
const CIRCLE = { cx: W / 2, cy: H / 2, r: 9.15 * K };
type Pt = { x: number; y: number };
type Rect = { x0: number; y0: number; x1: number; y1: number };
type Seg = [number, number, number, number];
/** Where a label sits relative to its dot: vertical offset in px (top edge) and how it is anchored horizontally. */
export interface Placement { dy: number; anchor: 'out' | 'center' | 'start' | 'end' | 'right-of' | 'left-of' | 'edge-start' | 'edge-end' }

const LABEL_H = 11;
const EDGE = 4; // px kept between a label and the pitch box edge
const labelWidth = (text: string) => Math.max(text.length - 2, 1) * 5.8; // px; " · " is rendered as one space

/** The label's rectangle in SVG units for a placement (same rule as the CSS in Label). */
export function labelRect(at: Pt, text: string, p: Placement): Rect {
  const [ax, ay] = [(at.x / 100) * W, (at.y / 100) * H];
  const w = labelWidth(text) * PX;
  const out = at.x < 30 ? 'start' : at.x > 70 ? 'end' : 'center';
  const anchor = p.anchor === 'out' ? out : p.anchor;
  const x0 = anchor === 'start' ? ax - 8 * PX : anchor === 'end' ? ax + 8 * PX - w : anchor === 'right-of' ? ax + 12 * PX
    : anchor === 'left-of' ? ax - 12 * PX - w : anchor === 'edge-start' ? EDGE * PX : anchor === 'edge-end' ? W - EDGE * PX - w
    : ax - w / 2;
  const y0 = ay + p.dy * PX;
  return { x0, y0, x1: x0 + w, y1: y0 + LABEL_H * PX };
}

/** True when the rectangle spills outside the pitch box (the box clips, so a label must stay fully inside it). */
export function overflowsBox(r: Rect): boolean {
  return r.x0 < EDGE * PX - 0.01 || r.x1 > W - EDGE * PX + 0.01 || r.y0 < 0 || r.y1 > H;
}

/** True when the rectangle is not fully inside the box, or sits on the halfway line, the centre circle's line or the connector. */
export function crossesMarkings(r: Rect, connector?: Seg | null): boolean {
  if (overflowsBox(r)) return true;
  const { cx, cy, r: rad } = CIRCLE;
  const [dx, dy] = [Math.max(r.x0 - cx, 0, cx - r.x1), Math.max(r.y0 - cy, 0, cy - r.y1)];
  const far = Math.hypot(Math.max(Math.abs(r.x0 - cx), Math.abs(r.x1 - cx)), Math.max(Math.abs(r.y0 - cy), Math.abs(r.y1 - cy)));
  if (Math.hypot(dx, dy) <= rad + 2 && far >= rad - 2) return true;
  if (r.y0 - 1 <= cy && cy <= r.y1 + 1) return true;
  if (!connector) return false;
  const [x1, y1, x2, y2] = connector;
  for (let i = 0; i <= 24; i += 1) {
    const [px, py] = [x1 + ((x2 - x1) * i) / 24, y1 + ((y2 - y1) * i) / 24];
    if (px >= r.x0 - 2 && px <= r.x1 + 2 && py >= r.y0 - 2 && py <= r.y1 + 2) return true;
  }
  return false;
}

const BELOW = 12;
const ABOVE = -24;

/**
 * General rule, no per-role cases: try the preferred side of the dot, then the other, then each alignment (including
 * flush with either pitch edge), then beside the dot, then clear of the centre circle above/below it; take the first
 * that stays fully inside the box and crosses none of the halfway line, the centre circle or the connector. The width
 * is an estimate (5.8 px per character), not a measurement. When nothing is clear keep the preferred one.
 */
export function placeLabel(at: Pt, text: string, preferBelow: boolean, connector?: Seg | null): Placement {
  const ay = (at.y / 100) * H;
  const [near, far] = preferBelow ? [BELOW, ABOVE] : [ABOVE, BELOW];
  const { cy, r } = CIRCLE;
  const clearAbove = (cy - r - 5 - LABEL_H * PX - ay) / PX;
  const clearBelow = (cy + r + 5 - ay) / PX;
  const candidates: Placement[] = [
    { dy: near, anchor: 'out' }, { dy: far, anchor: 'out' },
    ...(['edge-start', 'edge-end', 'center', 'start', 'end'] as const).flatMap((anchor) => [{ dy: near, anchor }, { dy: far, anchor }]),
    { dy: -LABEL_H / 2, anchor: 'right-of' }, { dy: -LABEL_H / 2, anchor: 'left-of' },
    { dy: clearAbove, anchor: 'center' }, { dy: clearBelow, anchor: 'center' },
  ];
  return candidates.find((p) => !crossesMarkings(labelRect(at, text, p), connector)) ?? candidates[0];
}

function Label({ at, text, place }: { at: Pt; text: string; place: Placement }) {
  const [when, ...rest] = text.split(' · ');
  const out = at.x < 30 ? 'start' : at.x > 70 ? 'end' : 'center';
  const anchor = place.anchor === 'out' ? out : place.anchor;
  const horizontal =
    anchor === 'start' ? { left: `calc(${at.x}% - 8px)` }
    : anchor === 'end' ? { right: `calc(${100 - at.x}% - 8px)` }
    : anchor === 'right-of' ? { left: `calc(${at.x}% + 12px)` }
    : anchor === 'left-of' ? { right: `calc(${100 - at.x}% + 12px)` }
    : anchor === 'edge-start' ? { left: '4px' }
    : anchor === 'edge-end' ? { right: '4px' }
    : { left: `${at.x}%`, transform: 'translateX(-50%)' };
  return (
    <span data-label-anchor={anchor} className="absolute whitespace-nowrap text-[11px] leading-none"
      style={{ top: `calc(${at.y}% + ${place.dy}px)`, ...horizontal }}>
      <b className="font-bold text-white">{when}</b>
      {rest.length > 0 && <span className="font-medium text-bf-gray"> {rest.join(' · ')}</span>}
    </span>
  );
}

export default function PositionPitch({ data }: { data: PositionPitchMeta }) {
  const { locale } = useLocale();
  const listing = data.kind === 'fpl_listing';
  const toField = placeRole(data.to);
  const fromField = placeRole(data.from, listing ? data.to.side : null);
  const [to, from] = [box(toField), box(fromField)];
  const hasBefore = data.rows.some((r) => r.before !== undefined);
  const connector: Seg | null = listing ? null : [ux(fromField.x), uy(fromField.y), ux(toField.x), uy(toField.y)];
  const fromPlace = placeLabel(from, data.labels.from, from.y >= to.y, connector);
  const toPlace = placeLabel(to, data.labels.to, listing ? to.y < 30 : to.y > from.y, connector);

  return (
    <div className="space-y-3" data-testid="position-pitch" data-kind={data.kind}>
      {/* 2:3 box; at most 280px wide on desktop (≈420 tall), up to 306px on a phone (height capped ≈460). */}
      <div data-testid="position-pitch-box"
        className="relative mx-auto w-full max-w-[306px] sm:max-w-[280px] aspect-[2/3] overflow-hidden rounded-lg bg-gradient-to-b from-bf-pitch to-bf-pitch-dark">
        <svg aria-hidden="true" className="absolute inset-0 h-full w-full" viewBox={`0 0 ${W} ${H}`}>
          <g opacity={0.2}><VerticalPitchLines /></g>
          <Connector a={fromField} b={toField} arrow={!listing} />
        </svg>
        {listing ? (
          <span data-role="listing"
            className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border border-dashed border-bf-gray/80 px-2 py-0.5 text-[11px] font-bold leading-none text-bf-gray"
            style={{ left: `${from.x}%`, top: `${from.y}%` }}>
            {data.labels.from}
          </span>
        ) : (
          <span data-role="old"
            className="absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-dashed border-bf-gray"
            style={{ left: `${from.x}%`, top: `${from.y}%` }} />
        )}
        <span data-role="new" className="absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-bf-cyan"
          style={{ left: `${to.x}%`, top: `${to.y}%` }} />
        {!listing && <Label at={from} text={data.labels.from} place={fromPlace} />}
        <Label at={to} text={data.labels.to} place={toPlace} />
      </div>

      {data.rows.length > 0 && (
        <div className="border-t border-white/10 pt-2.5" data-testid="position-pitch-table">
          <div className="mb-1 flex items-baseline justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wide text-bf-gray">{data.labels.table}</span>
            {hasBefore && (
              <span className="flex gap-3 text-[10px] uppercase tracking-wide text-bf-gray">
                <span className="w-12 text-right">{data.labels.before}</span>
                <span className="w-12 text-right">{data.labels.after}</span>
              </span>
            )}
          </div>
          {data.rows.map((r) => (
            <div key={r.metric} data-metric={r.metric} className="flex items-baseline justify-between gap-2 py-1 text-sm">
              <span className="text-bf-gray">{r.label}</span>
              {hasBefore ? (
                <span className="flex gap-3">
                  <span data-cell="before" className="w-12 text-right text-bf-gray">{fmt(r.before ?? null, '', locale)}</span>
                  <span data-cell="after" className="w-12 text-right font-extrabold text-white">{fmt(r.after ?? null, '', locale)}</span>
                </span>
              ) : (
                <span data-cell="value" className="font-extrabold text-white">{fmt(r.value ?? null, '', locale)}</span>
              )}
            </div>
          ))}
          {data.note && <p className="pt-1 text-[11px] text-bf-gray/70">{data.note}</p>}
        </div>
      )}
      {data.associations && (
        <p data-testid="position-pitch-associations" className="text-[11px] leading-snug text-bf-gray">{data.associations}</p>
      )}
    </div>
  );
}
