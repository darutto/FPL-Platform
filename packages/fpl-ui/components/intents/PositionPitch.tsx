/**
 * PositionPitch — the position-changes mini-pitch ("canchita") and its per-90 table, inside GenericCard.
 *
 * Two shapes, both from the backend's `position_pitch` payload (atomic_tool_cards._position_pitch):
 *   switch       old starting role (dashed ring) → new role (solid dot), joined by an arrow;
 *   fpl_listing  FPL's listed line (dashed tag, nobody played there) and the role actually played, joined by a quiet
 *                dotted link with NO arrowhead: nobody moved.
 * The pitch is the squad pitch's drawing (FullPitchLines, 400×240), attack UP and the attacker's left on the viewer's
 * left, framed like the zone pitches (centred, at most 420px wide). Roles are placed from provider role + side, never
 * from the provider grid cell. Lines and the connector scale with the pitch; dots and labels are HTML at fixed sizes,
 * so the text never scales. The table is neutral: the value since the change in bold, no colours, no +/−.
 */
import type { PitchRole, PositionPitchMeta } from '@/lib/types';
import { useLocale } from '@/lib/i18n/LocaleProvider';
import { FullPitchLines } from './PitchGeometry';
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

// SVG user units for the connector (the pitch box maps 0..100% to the 8..392 × 8..232 field).
const ux = (p: number) => 8 + (p / 100) * 384;
const uy = (p: number) => 8 + (p / 100) * 224;

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

function Label({ at, text, below }: { at: { x: number; y: number }; text: string; below: boolean }) {
  const [when, ...rest] = text.split(' · ');
  const align = at.x < 30 ? 'left-0 translate-x-0' : at.x > 70 ? 'right-0 translate-x-0' : '-translate-x-1/2';
  return (
    <span
      className={`absolute whitespace-nowrap text-[11px] leading-none ${align}`}
      style={{
        top: `calc(${at.y}% + ${below ? 12 : -24}px)`,
        ...(at.x < 30 ? { left: `calc(${at.x}% - 8px)` } : at.x > 70 ? { right: `calc(${100 - at.x}% - 8px)` } : { left: `${at.x}%` }),
      }}
    >
      <b className="font-bold text-white">{when}</b>
      {rest.length > 0 && <span className="font-medium text-bf-gray"> {rest.join(' · ')}</span>}
    </span>
  );
}

export default function PositionPitch({ data }: { data: PositionPitchMeta }) {
  const { locale } = useLocale();
  const listing = data.kind === 'fpl_listing';
  const to = placeRole(data.to);
  const from = placeRole(data.from, listing ? data.to.side : null);
  const hasBefore = data.rows.some((r) => r.before !== undefined);

  return (
    <div className="space-y-3" data-testid="position-pitch" data-kind={data.kind}>
      <div className="relative mx-auto w-full max-w-[420px] aspect-[5/3] overflow-hidden rounded-lg bg-gradient-to-b from-bf-pitch to-bf-pitch-dark">
        <svg aria-hidden="true" className="absolute inset-0 h-full w-full" viewBox="0 0 400 240" preserveAspectRatio="none">
          <g opacity={0.2}><FullPitchLines /></g>
          <Connector a={from} b={to} arrow={!listing} />
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
        {!listing && <Label at={from} text={data.labels.from} below={from.y < to.y ? false : true} />}
        <Label at={to} text={data.labels.to} below={listing ? to.y < 30 : to.y > from.y} />
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
    </div>
  );
}
