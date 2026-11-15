import { Easing, interpolate, interpolateColors } from 'remotion';

export const ease = Easing.bezier(0.22, 1, 0.36, 1); // easeOutQuint-like
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

type Key = [frame: number, value: number];

/** Piecewise interpolation through keyframes, clamped, with one easing per segment. */
export function kf(frame: number, keys: Key[], easing = easeInOut): number {
  return interpolate(
    frame,
    keys.map((k) => k[0]),
    keys.map((k) => k[1]),
    { easing, extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );
}

export function kc(frame: number, keys: [number, string][]): string {
  const f = Math.min(Math.max(frame, keys[0][0]), keys[keys.length - 1][0]);
  return interpolateColors(
    f,
    keys.map((k) => k[0]),
    keys.map((k) => k[1]),
  );
}

/** 0→1 progress over [start, start+dur], eased. */
export function p(frame: number, start: number, dur: number, easing = ease): number {
  return interpolate(frame, [start, start + dur], [0, 1], {
    easing,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
}
