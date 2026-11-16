/**
 * Clip 01 — "Toca. Pregunta. Entiende." (15 s, 1080×1920, 30 fps)
 * Approved storyboard: docs/marketing/clip-01/storyboard/ (v3, 15 Nov 2026).
 *
 * Every pixel of UI is a real capture of the app (docs/marketing/clip-01/captures/,
 * served as Remotion's public dir). Nothing is redrawn: the clip only moves a camera
 * over the captures, swaps them where the app itself changes state, and adds captions,
 * tap pulses, a privacy blur over the manager's name and the official SVG logo.
 */
import { AbsoluteFill, Audio, Img, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion';
import { kf, p } from '../anim';
import { Caption } from '../Caption';
import { C, F } from '../theme';
import { CUES, MUSIC, sfxPath } from './sound';

export type Clip01Props = { withSound?: boolean };

const Soundtrack: React.FC = () => (
  <>
    <Audio src={staticFile(sfxPath('music'))} volume={(f) =>
      MUSIC.volume * interpolate(f, [0, MUSIC.fadeInFrames, MUSIC.fadeOutFrom, CLIP01_FRAMES], [0, 1, 1, 0],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })} />
    {CUES.map((c, i) => (
      <Sequence key={i} from={c.at} layout="none">
        <Audio src={staticFile(sfxPath(c.file))} volume={c.volume} />
      </Sequence>
    ))}
  </>
);

export const CLIP01_FRAMES = 450;

const cap = (f: string) => staticFile(`clip-01/captures/${f}`);
const SCREEN_W = 1170; // captures are 390×844 CSS px at 3x

// ---------------------------------------------------------------- which real capture is on screen
type Shot = { from: number; src: string; h: number; chat?: boolean };
const SHOTS: Shot[] = [
  { from: 0, src: '00a-home.png', h: 2532 },
  { from: 36, src: 'id-entry/0-focus.png', h: 2532 },
  { from: 40, src: 'id-entry/digit-1.png', h: 2532 },
  { from: 44, src: 'id-entry/digit-2.png', h: 2532 },
  { from: 48, src: 'id-entry/digit-3.png', h: 2532 },
  { from: 52, src: 'id-entry/digit-4.png', h: 2532 },
  { from: 56, src: 'id-entry/digit-5.png', h: 2532 },
  { from: 60, src: 'id-entry/digit-6.png', h: 2532 },
  { from: 66, src: 'id-entry/7-connecting.png', h: 2532 },
  { from: 78, src: '01-squad.png', h: 2532 }, // tap on the SQUAD tab: the app switches instantly
  { from: 120, src: '02-jackson-detail.png', h: 2532 }, // tap on N.J
  { from: 180, src: '03-question-sent.png', h: 2532, chat: true }, // "Asistente →" opens Chat
  { from: 204, src: '09-answer-tall.png', h: 6147, chat: true }, // the answer replaces "Pensando…"
];
const shotAt = (f: number) => [...SHOTS].reverse().find((s) => f >= s.from)!;

// ---------------------------------------------------------------- camera (capture px → frame)
// Focus point (x, y) in capture px lands on the frame anchor; z = capture px → frame px.
const ANCHOR = { x: 540, y: 1040 };
type Cam = [frame: number, x: number, y: number, z: number];
const CAM: Cam[] = [
  [0, 585, 1266, 0.7],
  [30, 585, 1200, 0.74],
  [44, 411, 403, 1.45], // into the ID field
  [64, 430, 403, 1.45],
  [76, 585, 700, 0.92], // pull back to see the tabs
  [80, 585, 1000, 0.92],
  [118, 340, 1108, 1.28], // push-in on N.J
  [122, 340, 1108, 1.28],
  [142, 585, 1450, 1.02], // follow the card unfolding below the pitch
  [178, 640, 1520, 1.08],
  [180, 585, 760, 1.12], // Chat: the question bubble
  [204, 585, 760, 1.14],
  [218, 585, 940, 1.1], // the answer arrives: settle on the verdict and hold it
  [262, 585, 950, 1.1],
  [266, 585, 1000, 1.08],
  [290, 585, 3990, 1.0], // real scroll down the same answer to Zonas: his zones
  [322, 585, 4000, 1.04],
  [336, 585, 4010, 1.04],
  [356, 585, 4480, 1.04], // down to the Sunderland row
  [396, 585, 4500, 1.1],
];
function camera(f: number) {
  const at = (i: 1 | 2 | 3) => kf(f, CAM.map((c) => [c[0], c[i]] as [number, number]));
  return { x: at(1), y: at(2), z: at(3) };
}
// Scroll speed (capture px per frame) drives the vertical motion blur in 3c.
const scrollSpeed = (f: number) => Math.abs(camera(f + 1).y - camera(f).y);

// ---------------------------------------------------------------- tap pulses (capture px)
const TAPS: { at: number; x: number; y: number; r: number }[] = [
  { at: 34, x: 290, y: 403, r: 70 }, // focus the ID field
  { at: 62, x: 630, y: 403, r: 80 }, // Conectar
  { at: 72, x: 513, y: 196, r: 80 }, // SQUAD tab
  { at: 116, x: 279, y: 1108, r: 75 }, // N.J
  { at: 170, x: 994, y: 1603, r: 95 }, // Asistente →
];

// Highlights in the answer (tall capture px).
const CELLS = { x: 201, y: 3767, w: 512, h: 384 };
const SUNDERLAND = { x: 105, y: 4805, w: 960, h: 72 };
// Manager's name next to the team in the chat header: blurred for privacy.
const PRIVACY = { x: 100, y: 360, w: 440, h: 66 };
// The verdict: the three lines that answer the hook, spotlit while the camera holds.
const VERDICT = { x: 100, y: 750, w: 970, h: 380 };

const Pulse: React.FC<{ f: number; x: number; y: number; r: number }> = ({ f, x, y, r }) => {
  if (f < 0 || f > 16) return null;
  const t = p(f, 0, 16);
  const s = 0.6 + t * 0.9;
  return (
    <>
      <div style={{ position: 'absolute', left: x - r, top: y - r, width: 2 * r, height: 2 * r, borderRadius: '50%',
        background: 'rgba(255,255,255,0.22)', transform: `scale(${0.5 + Math.min(1, f / 5) * 0.4})`, opacity: f < 8 ? 1 : 1 - (f - 8) / 8 }} />
      <div style={{ position: 'absolute', left: x - r, top: y - r, width: 2 * r, height: 2 * r, borderRadius: '50%',
        border: `6px solid ${C.turquoise}`, transform: `scale(${s})`, opacity: 1 - t }} />
    </>
  );
};

const Glow: React.FC<{ f: number; box: { x: number; y: number; w: number; h: number }; radius: number; color: string }> = ({ f, box, radius, color }) => {
  if (f < 0) return null;
  const on = p(f, 0, 10);
  const breathe = 0.75 + 0.25 * Math.sin((f / 30) * Math.PI * 2);
  return (
    <div style={{ position: 'absolute', left: box.x - 8, top: box.y - 8, width: box.w + 16, height: box.h + 16, borderRadius: radius,
      border: `5px solid ${color}`, boxShadow: `0 0 ${46 * breathe}px ${color}, inset 0 0 ${24 * breathe}px ${color}55`, opacity: on }} />
  );
};

export const Clip01: React.FC<Clip01Props> = ({ withSound = false }) => {
  const f = useCurrentFrame();
  const shot = shotAt(f);
  const cam = camera(f);

  // Shot 5: the screen collapses into the centre and the logo takes its place.
  const out = p(f, 396, 22);
  const z = cam.z * (1 - out * 0.92);
  const left = ANCHOR.x - cam.x * z;
  const top = ANCHOR.y - cam.y * z;
  const blur = f >= 266 && f < 292 ? Math.min(26, scrollSpeed(f) / 9) : 0;

  const logoIn = p(f, 408, 18);
  const pillIn = p(f, 420, 12);
  const handleIn = p(f, 428, 12);

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, overflow: 'hidden' }}>
      {withSound && <Soundtrack />}
      <svg width={0} height={0} style={{ position: 'absolute' }}>
        <filter id="vblur"><feGaussianBlur stdDeviation={`0 ${blur}`} /></filter>
      </svg>

      {/* depth of field: the same capture, blurred and dimmed, fills the frame */}
      <Img src={cap(shot.src)} style={{ position: 'absolute', inset: -120, width: 1320, height: 2160, objectFit: 'cover',
        filter: 'blur(40px) brightness(0.32) saturate(1.15)', opacity: 1 - out }} />

      {/* the real screen under the camera */}
      <div style={{ position: 'absolute', left, top, width: SCREEN_W, height: shot.h, transform: `scale(${z})`, transformOrigin: '0 0',
        opacity: 1 - p(f, 408, 10) }}>
        <div style={{ position: 'absolute', inset: 0, borderRadius: 64, overflow: 'hidden', boxShadow: '0 40px 120px rgba(0,0,0,0.6)',
          filter: blur ? 'url(#vblur)' : undefined }}>
          <Img src={cap(shot.src)} style={{ width: SCREEN_W, height: shot.h, display: 'block' }} />
          {shot.chat && (
            <div style={{ position: 'absolute', left: PRIVACY.x, top: PRIVACY.y, width: PRIVACY.w, height: PRIVACY.h, borderRadius: 18,
              backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)', background: 'rgba(28,26,38,0.35)' }} />
          )}
        </div>
        {TAPS.map((t) => <Pulse key={t.at} f={f - t.at} x={t.x} y={t.y} r={t.r} />)}
        {shot.src === '09-answer-tall.png' && f < 272 && (() => {
          const on = p(f, 214, 10) * (1 - p(f, 262, 8));
          return (
            <div style={{ position: 'absolute', left: VERDICT.x, top: VERDICT.y, width: VERDICT.w, height: VERDICT.h, borderRadius: 34,
              boxShadow: `0 0 0 6000px rgba(18,17,26,${0.72 * on}), 0 0 ${50 * on}px ${C.turquoise}66`,
              border: `5px solid rgba(2,235,174,${on})` }} />
          );
        })()}
        {shot.src === '09-answer-tall.png' && (
          <>
            <Glow f={f - 300} box={CELLS} radius={10} color={C.turquoise} />
            <Glow f={f - 358} box={SUNDERLAND} radius={40} color={C.turquoise} />
          </>
        )}
      </div>

      {/* legibility scrim behind captions */}
      <div style={{ position: 'absolute', left: 0, right: 0, top: 0, height: 600,
        background: `linear-gradient(${C.bg}f2 0%, ${C.bg}d9 38%, ${C.bg}00 100%)`, opacity: 1 - out }} />

      <Caption text="¿Lo alineo esta semana?" start={4} end={70} y={300} />
      <Caption text="Tu equipo, en la cancha." start={80} end={114} y={300} />
      <Caption text="Toca a cualquier jugador." start={124} end={174} y={300} />
      <Caption text="Pregúntale a tu asistente." start={184} end={212} y={300} />
      <Caption text="Dónde dispara él." start={294} end={332} y={300} />
      <Caption text="Dónde concede Sunderland." start={344} end={392} y={300} accent={["Sunderland"]} />

      {/* CTA: official SVG logo, then the coral pill */}
      {f >= 404 && (
        <>
          <Img src={staticFile('assets/logo-bf.svg')} style={{ position: 'absolute', left: 540 - 230, top: 900 - 230, width: 460, height: 460,
            transform: `scale(${0.35 + 0.65 * logoIn})`, opacity: logoIn,
            filter: `drop-shadow(0 0 ${60 * logoIn}px ${C.gold}88)` }} />
          <div style={{ position: 'absolute', left: 0, right: 0, top: 1210 + (1 - pillIn) * 24, display: 'flex', justifyContent: 'center', opacity: pillIn }}>
            <div style={{ background: C.coral, color: '#fff', fontFamily: F.sans, fontWeight: 800, fontSize: 58, padding: '26px 56px',
              borderRadius: 999, boxShadow: `0 24px 70px ${C.coral}66`, whiteSpace: 'nowrap' }}>FPL Asistente · Prueba gratis</div>
          </div>
          <div style={{ position: 'absolute', left: 0, right: 0, top: 1380 + (1 - handleIn) * 24, textAlign: 'center', opacity: handleIn,
            fontFamily: F.sans, fontWeight: 700, fontSize: 44, letterSpacing: 1, color: C.gray }}>benditofantasy</div>
        </>
      )}
    </AbsoluteFill>
  );
};
