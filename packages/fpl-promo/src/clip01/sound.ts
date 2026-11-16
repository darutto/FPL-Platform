/**
 * Clip 01 sound cue sheet (30 fps). Frames match the visual events in Clip01.tsx.
 *
 * The audio files are NOT in the repo: stock licences (Pixabay, Mixkit, Artlist...) allow
 * them inside a finished video but not as standalone files in a public repo. They live in
 * docs/marketing/assets/sfx/ (gitignored) on the machine that renders, under the names
 * below, and are only loaded when the composition gets `withSound: true`.
 */
export type SfxFile = 'music' | 'tap' | 'key' | 'pop' | 'whoosh' | 'sparkle' | 'logo';
export const sfxPath = (f: SfxFile) => `assets/sfx/${f}.mp3`;

export const MUSIC = { volume: 0.28, fadeInFrames: 8, fadeOutFrom: 426 };

export const CUES: { at: number; file: SfxFile; volume: number; note: string }[] = [
  { at: 34, file: 'tap', volume: 0.6, note: 'focus the ID field' },
  ...[40, 44, 48, 52, 56, 60].map((at) => ({ at, file: 'key' as const, volume: 0.45, note: 'ID digit' })),
  { at: 62, file: 'tap', volume: 0.6, note: 'Conectar' },
  { at: 72, file: 'tap', volume: 0.6, note: 'SQUAD tab' },
  { at: 116, file: 'tap', volume: 0.6, note: 'N.J' },
  { at: 170, file: 'tap', volume: 0.6, note: 'Asistente' },
  { at: 214, file: 'pop', volume: 0.7, note: 'verdict spotlight' },
  { at: 266, file: 'whoosh', volume: 0.55, note: 'scroll to Zonas' },
  { at: 300, file: 'sparkle', volume: 0.5, note: 'his shooting cells' },
  { at: 358, file: 'sparkle', volume: 0.5, note: 'Sunderland row' },
  { at: 404, file: 'logo', volume: 0.75, note: 'logo reveal' },
];
