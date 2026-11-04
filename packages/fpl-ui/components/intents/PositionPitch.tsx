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

// --- label placement: a label stays attached to its dot, inside the field lines, clear of the connector --------------
const PX = W / 280; // user units per CSS px at the narrowest box (labels are fixed-size HTML, so this is the worst case)
const CIRCLE = { cx: W / 2, cy: H / 2, r: 9.15 * K };
type Pt = { x: number; y: number };
type Rect = { x0: number; y0: number; x1: number; y1: number };
type Seg = [number, number, number, number];
/**
 * Where a label sits relative to its dot. `lines` is 1 ("GW1–5 Right Midfield") or 2 (the span, then the role).
 * `anchor`: natural = extends towards the centre of the pitch for a dot near a side (centred for a central dot).
 */
export interface Placement { dy: number; anchor: 'natural' | 'center' | 'right-of' | 'left-of'; lines: 1 | 2 }

const LINE_H = 11;
const FIELD_GAP = 3; // px between a label and the field lines
/** A label must stay this close to its dot (px, dot centre to the nearest point of the label). */
export const MAX_DOT_DISTANCE = 28;
const labelWidth = (text: string, lines: 1 | 2) => {
  const [when, ...rest] = text.split(' · ');
  const role = rest.join(' ');
  return (lines === 1 ? Math.max(text.length - 2, 1) : Math.max(when.length, role.length, 1)) * 5.8; // px; an estimate
};

/** The label's rectangle in SVG units for a placement, clamped into the field lines (the same x the CSS uses). */
export function labelRect(at: Pt, text: string, p: Placement): Rect {
  const [ax, ay] = [(at.x / 100) * W, (at.y / 100) * H];
  const w = labelWidth(text, p.lines) * PX;
  const natural = at.x < 30 ? 'start' : at.x > 70 ? 'end' : 'center';
  const anchor = p.anchor === 'natural' ? natural : p.anchor;
  const raw = anchor === 'start' ? ax - 8 * PX : anchor === 'end' ? ax + 8 * PX - w : anchor === 'right-of' ? ax + 12 * PX
    : anchor === 'left-of' ? ax - 12 * PX - w : ax - w / 2;
  const lo = M + FIELD_GAP * PX;
  const x0 = Math.min(Math.max(raw, lo), Math.max(lo, W - lo - w));
  const y0 = ay + p.dy * PX;
  return { x0, y0, x1: x0 + w, y1: y0 + p.lines * LINE_H * PX };
}

/** True when the rectangle is not fully inside the field lines (with a small gap). */
export function outsideField(r: Rect): boolean {
  const g = FIELD_GAP * PX;
  return r.x0 < M + g - 0.01 || r.x1 > W - M - g + 0.01 || r.y0 < M + g - 0.01 || r.y1 > H - M - g + 0.01;
}

/** True when the rectangle touches the connector (the arrow or the dotted link). */
export function hitsConnector(r: Rect, connector?: Seg | null): boolean {
  if (!connector) return false;
  const [x1, y1, x2, y2] = connector;
  for (let i = 0; i <= 24; i += 1) {
    const [px, py] = [x1 + ((x2 - x1) * i) / 24, y1 + ((y2 - y1) * i) / 24];
    if (px >= r.x0 - 2 && px <= r.x1 + 2 && py >= r.y0 - 2 && py <= r.y1 + 2) return true;
  }
  return false;
}

/** How many pitch markings (the centre circle's line, the halfway line) the rectangle sits on: 0, 1 or 2. */
export function markingsHit(r: Rect): number {
  const { cx, cy, r: rad } = CIRCLE;
  const [dx, dy] = [Math.max(r.x0 - cx, 0, cx - r.x1), Math.max(r.y0 - cy, 0, cy - r.y1)];
  const far = Math.hypot(Math.max(Math.abs(r.x0 - cx), Math.abs(r.x1 - cx)), Math.max(Math.abs(r.y0 - cy), Math.abs(r.y1 - cy)));
  const ring = Math.hypot(dx, dy) <= rad + 2 && far >= rad - 2;
  const line = r.y0 - 1 <= cy && cy <= r.y1 + 1;
  return Number(ring) + Number(line);
}

/** Distance in px from the dot's centre to the nearest point of the rectangle. */
export function dotDistance(at: Pt, r: Rect): number {
  const [ax, ay] = [(at.x / 100) * W, (at.y / 100) * H];
  return Math.hypot(Math.max(r.x0 - ax, 0, ax - r.x1), Math.max(r.y0 - ay, 0, ay - r.y1)) / PX;
}

const BELOW = 12;
const aboveFor = (lines: 1 | 2) => -(lines * LINE_H + 13);

/**
 * General rule, no per-role cases. A label stays attached to its dot: under or over it, or beside it, in one or two
 * lines, extending towards the centre of the pitch, never jumping to the far side. Hard limits: inside the field lines,
 * not on the connector, within MAX_DOT_DISTANCE of the dot. First choice also keeps off the halfway line and the centre
 * circle; if no such spot exists a label may sit on those faint lines (fewest first), never on the connector or the
 * field edge. Widths are estimates (5.8 px per character), not measurements.
 */
export function placeLabel(at: Pt, text: string, preferBelow: boolean, connector?: Seg | null): Placement {
  const [near, far] = preferBelow ? ['below', 'above'] as const : ['above', 'below'] as const;
  const dyOf = (side: 'below' | 'above', lines: 1 | 2) => (side === 'below' ? BELOW : aboveFor(lines));
  const inward = at.x < 50 ? ['right-of', 'left-of'] as const : ['left-of', 'right-of'] as const;
  const candidates: Placement[] = [
    ...([1, 2] as const).flatMap((lines) => ([near, far] as const).flatMap((side) =>
      (['natural', 'center'] as const).map((anchor) => ({ dy: dyOf(side, lines), anchor, lines })))),
    ...([1, 2] as const).flatMap((lines) => inward.map((anchor) => ({ dy: -(lines * LINE_H) / 2, anchor, lines }))),
  ];
  const ok = candidates.filter((p) => {
    const r = labelRect(at, text, p);
    return !outsideField(r) && !hitsConnector(r, connector) && dotDistance(at, r) <= MAX_DOT_DISTANCE;
  });
  const clean = ok.find((p) => markingsHit(labelRect(at, text, p)) === 0);
  if (clean) return clean;
  const byMarkings = [...ok].sort((p, q) => markingsHit(labelRect(at, text, p)) - markingsHit(labelRect(at, text, q)));
  return byMarkings[0] ?? candidates[0];
}

function Label({ at, text, place }: { at: Pt; text: string; place: Placement }) {
  const [when, ...rest] = text.split(' · ');
  const role = rest.join(' · ');
  const r = labelRect(at, text, place);
  const natural = at.x < 30 ? 'start' : at.x > 70 ? 'end' : 'center';
  const anchor = place.anchor === 'natural' ? natural : place.anchor;
  const align = anchor === 'end' || anchor === 'left-of' ? 'text-right' : anchor === 'center' ? 'text-center' : 'text-left';
  return (
    <span data-label-anchor={anchor} data-label-lines={place.lines}
      className={`absolute whitespace-nowrap text-[11px] leading-none ${align}`}
      style={{
        top: `calc(${at.y}% + ${place.dy}px)`,
        // Anchor the side that touches the dot, so a real width a little under the estimate leaves no gap there.
        ...(anchor === 'end' || anchor === 'left-of' ? { right: `${(100 * (W - r.x1)) / W}%` }
          : anchor === 'center' ? { left: `${(100 * (r.x0 + r.x1)) / (2 * W)}%`, transform: 'translateX(-50%)' }
            : { left: `${(100 * r.x0) / W}%` }),
      }}>
      <b className="font-bold text-white">{when}</b>
      {role && (place.lines === 2 ? <br /> : ' ')}
      {role && <span className="font-medium text-bf-gray">{role}</span>}
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
