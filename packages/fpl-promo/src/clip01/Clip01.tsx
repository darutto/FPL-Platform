/**
 * Clip 01 — "Toca. Pregunta. Entiende." (15 s, 1080×1920, 30 fps)
 * Storyboard: docs/marketing/06-clip-01-plan.md. Data: src/data.json (real app answer, N.Jackson pre-GW11).
 *
 * One morphing object carries the whole clip, anchored at the frame centre:
 * squad token → player card → "Asistente →" button → chat bubble → zones box → logo plate.
 * No cross-dissolves between shots.
 */
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from 'remotion';
import { kc, kf, p, ease } from '../anim';
import { Caption } from '../Caption';
import { C, CX, CY, F } from '../theme';
import data from '../data.json';

export const CLIP01_FRAMES = 450;

const P = data.player;
const QUESTION = `Cuéntame sobre ${P.web_name} — ¿lo alineo esta semana?`;

// ---------------------------------------------------------------- world (squad on the pitch)
const PITCH = { x: 110, y: 430, w: 860, h: 1120 };
const JAC = { x: 400, y: 1150 };
const TOKEN = 92;
// Teammates are drawn as anonymous tokens: we only show the player whose data is real.
const MATES = [
  { x: 540, y: 530 },
  { x: 230, y: 730 }, { x: 420, y: 730 }, { x: 660, y: 730 }, { x: 850, y: 730 },
  { x: 230, y: 940 }, { x: 420, y: 940 }, { x: 660, y: 940 }, { x: 850, y: 940 },
  { x: 680, y: 1150 },
];

function camera(f: number) {
  const s = kf(f, [[0, 2.1], [16, 2.1], [52, 0.92], [62, 0.92], [86, 1.35]]);
  const cx = kf(f, [[0, JAC.x], [16, JAC.x], [52, 540], [62, 540], [86, JAC.x]]);
  const cy = kf(f, [[0, JAC.y], [16, JAC.y], [52, 990], [62, 990], [86, JAC.y]]);
  return { s, cx, cy };
}
const toScreen = (f: number, wx: number, wy: number) => {
  const { s, cx, cy } = camera(f);
  return { x: (wx - cx) * s + CX, y: (wy - cy) * s + CY, s };
};

const World: React.FC<{ f: number }> = ({ f }) => {
  const { s, cx, cy } = camera(f);
  const dim = kf(f, [[86, 1], [100, 0.35], [230, 0.35], [250, 0.22]]);
  const blur = kf(f, [[86, 0], [100, 6], [240, 18]]);
  return (
    <AbsoluteFill
      style={{
        transform: `translate(${CX}px, ${CY}px) scale(${s}) translate(${-cx}px, ${-cy}px)`,
        transformOrigin: '0 0',
        filter: `blur(${blur / s}px)`,
        opacity: kf(f, [[0, 0.25], [20, 1]]) * dim,
      }}
    >
      <div
        style={{
          position: 'absolute', left: PITCH.x, top: PITCH.y, width: PITCH.w, height: PITCH.h,
          borderRadius: 18, overflow: 'hidden',
          background: `repeating-linear-gradient(180deg, ${C.pitch} 0 112px, ${C.pitchDark} 112px 224px)`,
          boxShadow: 'inset 0 0 0 3px rgba(255,255,255,.18)',
        }}
      >
        <div style={{ position: 'absolute', left: 0, right: 0, top: PITCH.h / 2, height: 3, background: 'rgba(255,255,255,.18)' }} />
        <div style={{ position: 'absolute', left: PITCH.w / 2 - 110, top: PITCH.h / 2 - 110, width: 220, height: 220, borderRadius: '50%', border: '3px solid rgba(255,255,255,.18)' }} />
        <div style={{ position: 'absolute', left: PITCH.w / 2 - 200, top: 0, width: 400, height: 150, border: '3px solid rgba(255,255,255,.18)', borderTop: 0 }} />
        <div style={{ position: 'absolute', left: PITCH.w / 2 - 200, bottom: 0, width: 400, height: 150, border: '3px solid rgba(255,255,255,.18)', borderBottom: 0 }} />
      </div>
      {MATES.map((m, i) => {
        const t = p(f, 6 + i * 2.2, 24);
        const dx = (m.x - JAC.x) * 1.8 * (1 - t);
        const dy = (m.y - JAC.y) * 1.8 * (1 - t);
        return (
          <div
            key={i}
            style={{
              position: 'absolute', left: m.x - TOKEN / 2 + dx, top: m.y - TOKEN / 2 + dy,
              width: TOKEN, height: TOKEN, borderRadius: '50%',
              background: '#163a3f', border: '4px solid rgba(255,255,255,.28)',
              opacity: t, transform: `scale(${0.6 + 0.4 * t})`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- the morphing object
function morph(f: number) {
  const tok = toScreen(f, JAC.x, JAC.y);
  const tokSize = TOKEN * tok.s;
  if (f < 95) {
    const pulse = f < 60 ? 1 + 0.06 * Math.sin((f / 30) * Math.PI * 2) : 1;
    return {
      x: tok.x, y: tok.y, w: tokSize * pulse, h: tokSize * pulse, r: (tokSize * pulse) / 2,
      bg: C.teal, border: C.turquoise, bw: 4 * tok.s,
    };
  }
  const t0 = TOKEN * 1.35;
  const K = [95, 118, 162, 182, 198, 228, 248, 375, 394];
  const val = (vals: number[]) => kf(f, K.map((k, i) => [k, vals[i]] as [number, number]));
  return {
    x: CX,
    y: val([CY, CY, CY, CY, CY, CY, 820, 820, 860]),
    w: val([t0, 780, 780, 420, 880, 880, 780, 780, 240]),
    h: val([t0, 600, 600, 96, 210, 210, 380, 380, 240]),
    r: val([t0 / 2, 28, 28, 48, 36, 36, 6, 6, 120]),
    bg: kc(f, [[95, C.teal], [118, C.card], [162, C.card], [182, C.coral], [228, C.coral], [238, C.bg], [248, 'rgba(18,17,26,0)'], [375, 'rgba(255,255,255,0.03)'], [394, C.card]]),
    border: kc(f, [[95, C.turquoise], [118, 'rgba(255,255,255,0.10)'], [162, 'rgba(255,255,255,0.10)'], [182, C.coral], [228, C.coral], [248, 'rgba(255,255,255,0.55)'], [375, 'rgba(255,255,255,0.55)'], [394, C.coral]]),
    bw: val([4, 2, 2, 0, 0, 0, 3, 3, 4]),
  };
}

const Tap: React.FC<{ f: number; at: number; x: number; y: number }> = ({ f, at, x, y }) => {
  const t = p(f, at, 16);
  if (f < at || t >= 1) return null;
  return (
    <div
      style={{
        position: 'absolute', left: x - 70, top: y - 70, width: 140, height: 140, borderRadius: '50%',
        border: `5px solid ${C.text}`, opacity: 1 - t, transform: `scale(${0.3 + t * 1.1})`,
      }}
    />
  );
};

const Stat: React.FC<{ v: string; l: string }> = ({ v, l }) => (
  <div style={{ flex: 1 }}>
    <div style={{ fontFamily: F.display, fontSize: 46, color: C.text, letterSpacing: -1 }}>{v}</div>
    <div style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 24, color: C.gray, letterSpacing: 2 }}>{l}</div>
  </div>
);

const CardContent: React.FC<{ f: number }> = ({ f }) => {
  const o = kf(f, [[110, 0], [126, 1], [158, 1], [168, 0]]);
  if (o <= 0) return null;
  const rise = (1 - p(f, 110, 18)) * 30;
  return (
    <div style={{ position: 'absolute', left: CX - 390 + 48, top: CY - 300 + 44, width: 780 - 96, opacity: o, transform: `translateY(${rise}px)` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 60, color: C.text, lineHeight: 1 }}>{P.web_name}</div>
          <div style={{ fontFamily: F.sans, fontWeight: 500, fontSize: 30, color: C.gray, marginTop: 10 }}>AVL · DEL</div>
        </div>
        <div style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 26, color: C.turquoise, border: `2px solid ${C.turquoise}`, borderRadius: 40, padding: '6px 20px', background: 'rgba(2,235,174,.10)' }}>
          Disponible
        </div>
      </div>
      <div style={{ marginTop: 34, display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span style={{ fontFamily: F.display, fontSize: 132, color: C.purple, lineHeight: 0.9, letterSpacing: -4 }}>
          {Math.round(P.total_points * p(f, 112, 26))}
        </span>
        <span style={{ fontFamily: F.display, fontSize: 40, color: C.gray }}>pts</span>
      </div>
      <div style={{ marginTop: 30, display: 'flex', gap: 20 }}>
        <Stat v={`£${P.price.toFixed(1)}m`} l="PRECIO" />
        <Stat v={`${P.ownership_pct}%`} l="SEL." />
        <Stat v={P.form.toFixed(1)} l="FORMA" />
      </div>
    </div>
  );
};

/** The card's coral button: rides from the card's foot to the centre, where the morph box becomes it. */
const AskButton: React.FC<{ f: number }> = ({ f }) => {
  if (f < 112 || f > 184) return null;
  const y = kf(f, [[162, CY + 300 - 92], [182, CY]]);
  const o = kf(f, [[112, 0], [126, 1]]);
  const press = 1 - 0.06 * Math.sin(Math.PI * p(f, 156, 8, (x) => x));
  return (
    <div
      style={{
        position: 'absolute', left: CX - 210, top: y - 48, width: 420, height: 96, borderRadius: 48,
        background: C.coral, display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: F.sans, fontWeight: 800, fontSize: 40, color: '#fff', opacity: o, transform: `scale(${press})`,
        boxShadow: '0 10px 40px rgba(255,106,77,.35)',
      }}
    >
      Asistente →
    </div>
  );
};

const Bubble: React.FC<{ f: number }> = ({ f }) => {
  const o = kf(f, [[192, 0], [198, 1], [228, 1], [236, 0]]);
  if (o <= 0) return null;
  const n = Math.floor(QUESTION.length * p(f, 196, 28, (x) => x));
  return (
    <div
      style={{
        position: 'absolute', left: CX - 440 + 44, top: CY - 105 + 30, width: 880 - 88, opacity: o,
        fontFamily: F.sans, fontWeight: 700, fontSize: 46, lineHeight: 1.22, color: '#fff',
      }}
    >
      {QUESTION.slice(0, n)}
      <span style={{ opacity: f % 16 < 8 ? 1 : 0 }}>▍</span>
    </div>
  );
};

// ---------------------------------------------------------------- zones (PlayerZonesPitch, Spanish copy)
const BOX = { x: CX - 390, y: 820 - 190, w: 780, h: 380 };
const COL = BOX.w / 3;

const Cell: React.FC<{ f: number; col: number; pct: number; start: number }> = ({ f, col, pct, start }) => {
  const t = p(f, start, 26);
  if (t <= 0) return null;
  const glow = Math.sin(Math.PI * p(f, 318, 22, (x) => x));
  return (
    <div
      style={{
        position: 'absolute', left: BOX.x + col * COL, top: BOX.y, width: COL, height: BOX.h * t,
        background: `rgba(2,235,174,${0.18 + 0.14 * t})`, border: `3px solid ${C.turquoise}`,
        boxShadow: `0 0 ${20 + 50 * glow}px rgba(2,235,174,${0.25 + 0.4 * glow})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
      }}
    >
      <span style={{ fontFamily: F.display, fontSize: 92, color: C.turquoise, letterSpacing: -3, opacity: kf(f, [[start + 6, 0], [start + 12, 1]]) }}>
        {Math.round(pct * p(f, start + 4, 24))}%
      </span>
    </div>
  );
};

const Chip: React.FC<{ f: number; at: number; y: number; children: React.ReactNode; accent?: boolean }> = ({ f, at, y, children, accent }) => {
  const t = p(f, at, 14);
  return (
    <div style={{ position: 'absolute', top: y, left: 0, right: 0, display: 'flex', justifyContent: 'center', overflow: 'hidden', height: 74 }}>
      <div
        style={{
          transform: `translateY(${(1 - t) * 80}px)`,
          fontFamily: F.sans, fontWeight: 700, fontSize: 32, borderRadius: 40, padding: '12px 28px',
          color: accent ? C.turquoise : C.text,
          background: accent ? 'rgba(2,235,174,.10)' : 'rgba(255,255,255,.06)',
          border: `2px solid ${accent ? C.turquoise : 'rgba(255,255,255,.18)'}`,
        }}
      >
        {children}
      </div>
    </div>
  );
};

const Zones: React.FC<{ f: number }> = ({ f }) => {
  if (f < 244 || f > 396) return null;
  const lines = kf(f, [[244, 0], [262, 1]]);
  const collapse = p(f, 375, 18);
  const left = data.zones.cells.find((c) => c.zone === 'box_left')!;
  const centre = data.zones.cells.find((c) => c.zone === 'box_centre')!;
  const gw11 = data.zones.matchups[0];
  const lineC = 'rgba(255,255,255,.4)';
  return (
    <AbsoluteFill style={{ transform: `scale(${1 - 0.75 * collapse})`, transformOrigin: `${CX}px 860px`, opacity: 1 - collapse }}>
      <div style={{ position: 'absolute', left: BOX.x, top: BOX.y - 74, width: BOX.w, display: 'flex', justifyContent: 'space-between', opacity: lines }}>
        <span style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 32, letterSpacing: 4, color: C.text }}>ZONAS</span>
        <span style={{ fontFamily: F.sans, fontWeight: 500, fontSize: 28, color: C.gray }}>Próximas 3 jornadas · J11–J13</span>
      </div>
      {/* goal, six-yard box, edge-of-box band and arc (PitchGeometry) */}
      <div style={{ position: 'absolute', left: CX - 60, top: BOX.y - 10, width: 120, height: 10, background: C.text, opacity: lines }} />
      <div style={{ position: 'absolute', left: CX - 130, top: BOX.y, width: 260, height: 120 * lines, border: `3px solid ${lineC}`, borderTop: 0 }} />
      <div style={{ position: 'absolute', left: BOX.x, top: BOX.y + BOX.h, width: BOX.w, height: 230 * lines, border: `3px dashed rgba(255,255,255,.22)`, borderTop: 0 }} />
      <div style={{ position: 'absolute', left: CX - 90, top: BOX.y + BOX.h - 90, width: 180, height: 180, borderRadius: '50%', border: `3px solid ${lineC}`, clipPath: 'inset(50% 0 0 0)', opacity: lines }} />
      <Cell f={f} col={1} pct={centre.pct} start={258} />
      <Cell f={f} col={0} pct={left.pct} start={280} />
      <Chip f={f} at={312} y={1255}>Área centro · {centre.pct}% de su xG sin penalti</Chip>
      <Chip f={f} at={318} y={1335}>Área izq · {left.pct}% de su xG sin penalti</Chip>
      <div style={{ position: 'absolute', top: 1432, left: 0, right: 0, textAlign: 'center', fontFamily: F.sans, fontWeight: 700, fontSize: 36, color: C.text, opacity: p(f, 326, 10), transform: `translateY(${(1 - p(f, 326, 14)) * 30}px)` }}>
        J{gw11.gw} {gw11.opp} <span style={{ color: C.gray }}>(L)</span>
      </div>
      <Chip f={f} at={332} y={1490} accent>Cruce favorable · Área centro, Área izq</Chip>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- outro
const Outro: React.FC<{ f: number }> = ({ f }) => {
  if (f < 388) return null;
  const logo = p(f, 390, 20);
  const pill = p(f, 416, 16);
  const shine = p(f, 430, 18, (x) => x);
  return (
    <>
      <div style={{ position: 'absolute', left: CX - 112, top: 860 - 112, width: 224, height: 224, borderRadius: '50%', overflow: 'hidden', opacity: logo, transform: `scale(${0.7 + 0.3 * logo})` }}>
        <Img src={staticFile('logo-icon.png')} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      </div>
      <Caption text="FPL Asistente" start={402} end={999} y={1020} size={92} />
      <div style={{ position: 'absolute', top: 1135, left: 0, right: 0, textAlign: 'center', fontFamily: F.sans, fontWeight: 500, fontSize: 36, color: C.gray, opacity: p(f, 410, 12) }}>
        de Bendito Fantasy
      </div>
      <div
        style={{
          position: 'absolute', left: CX - 230, top: 1230, width: 460, height: 104, borderRadius: 52, overflow: 'hidden',
          background: C.coral, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: F.sans, fontWeight: 800, fontSize: 44, color: '#fff',
          transform: `scale(${0.85 + 0.15 * pill})`, opacity: pill, boxShadow: '0 12px 50px rgba(255,106,77,.4)',
        }}
      >
        Prueba gratis
        <div style={{ position: 'absolute', top: 0, bottom: 0, width: 120, left: -160 + shine * 640, background: 'linear-gradient(90deg, transparent, rgba(255,255,255,.45), transparent)', transform: 'skewX(-20deg)' }} />
      </div>
    </>
  );
};

// ---------------------------------------------------------------- composition
export const Clip01: React.FC = () => {
  const f = useCurrentFrame();
  const m = morph(f);
  const push = 1 + 0.05 * (f / CLIP01_FRAMES);
  const btnTapY = CY + 300 - 92;
  return (
    <AbsoluteFill style={{ background: C.bg, overflow: 'hidden' }}>
      {/* depth: soft drifting turf far behind everything */}
      <AbsoluteFill
        style={{
          background: `repeating-linear-gradient(170deg, ${C.pitch} 0 140px, ${C.pitchDark} 140px 280px)`,
          filter: 'blur(28px)', opacity: 0.22, transform: `translateY(${-f * 0.5}px) scale(1.3)`,
        }}
      />
      <AbsoluteFill style={{ transform: `scale(${push})`, transformOrigin: `${CX}px ${CY}px` }}>
        <World f={f} />
        <div
          style={{
            position: 'absolute', left: m.x - m.w / 2, top: m.y - m.h / 2, width: m.w, height: m.h,
            borderRadius: m.r, background: m.bg, border: `${m.bw}px solid ${m.border}`, boxSizing: 'border-box',
            boxShadow: f > 100 && f < 370 ? '0 20px 60px rgba(0,0,0,.45)' : undefined,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          {f < 100 && (
            <span style={{ fontFamily: F.sans, fontWeight: 800, fontSize: m.w * 0.3, color: C.text, opacity: kf(f, [[90, 1], [99, 0]]) }}>JAC</span>
          )}
        </div>
        {f < 98 && (() => {
          const t = toScreen(f, JAC.x, JAC.y + TOKEN * 0.82);
          return (
            <div style={{ position: 'absolute', left: t.x - 200, top: t.y - 18 * t.s, width: 400, textAlign: 'center', fontFamily: F.sans, fontWeight: 700, fontSize: 26 * t.s, color: C.text, opacity: kf(f, [[88, 1], [97, 0]]) }}>
              {P.web_name}
            </div>
          );
        })()}
        <CardContent f={f} />
        <AskButton f={f} />
        <Bubble f={f} />
        <Zones f={f} />
        <Outro f={f} />
        <Tap f={f} at={88} x={CX} y={CY} />
        <Tap f={f} at={156} x={CX} y={btnTapY} />
      </AbsoluteFill>
      {/* vignette keeps the eye at the centre */}
      <AbsoluteFill style={{ background: 'radial-gradient(ellipse at 50% 47%, transparent 45%, rgba(0,0,0,.55) 100%)', pointerEvents: 'none' }} />
      <Caption text="¿Lo alineo esta semana?" start={4} end={56} />
      <Caption text="Toca a cualquier jugador." start={64} end={146} />
      <Caption text="Pregúntale a tu asistente." start={154} end={236} />
      <Caption text="Dónde dispara él. Dónde concede Sunderland." start={250} end={366} y={300} size={58} accent={['Sunderland']} />
    </AbsoluteFill>
  );
};
