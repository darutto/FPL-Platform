/**
 * Clip 01 sound cue sheet (30 fps). Frames match the visual events in Clip01.tsx.
 *
 * The audio files are NOT in the repo: stock licences (Pixabay, Mixkit, Artlist...) allow
 * them inside a finished video but not as standalone files in a public repo. They live in
 * docs/marketing/assets/sfx/ (gitignored) on the machine that renders, under the names
 * below, and are only loaded when the composition gets `withSound: true`.
 */
export type SfxFile = 'music' | 'tap' | 'key' | 'pop' | 'whoosh' | 'sparkle' | 'logo' | 'voice';
export const sfxPath = (f: SfxFile) => `assets/sfx/${f}.mp3`;

/**
 * Music bed. music.mp3 is a 15.0 s edit, not the raw track: the track's first 3 bars
 * joined on a downbeat to its last bars and natural ending, sped up ~5% (pitch kept) so
 * the final hit lands at 13.0 s (frame 390) and its decay ends at 15 s (MUSIC.end); the
 * clip's last second is voice and logo only. The recipe
 * is in docs/marketing/assets/sfx/SOURCES.md. The fade-out here is only a safety tail.
 */
export const MUSIC = { volume: 0.28, fadeInFrames: 4, fadeOutFrom: 438, end: 450, duck: 0.55, duckRamp: 4 };

/**
 * Voice-over (Leo, voice.mp3, 48 kHz mono). Each line is cut from the take by source
 * frame (`from`/`to`, @30fps, measured from its pauses) and anchored at clip frame `at`
 * to the visual it names. The music ducks to MUSIC.duck while a line plays.
 */
export const VOICE: { at: number; from: number; to: number; volume: number; line: string }[] = [
  { at: 6, from: 51, to: 84, volume: 1, line: '¿Lo alineo esta semana?' },
  { at: 34, from: 101, to: 124, volume: 1, line: 'Conecta tu equipo,' },
  { at: 108, from: 134, to: 216, volume: 1, line: 'toca cualquier jugador y pregúntale a tu asistente.' },
  { at: 192, from: 229, to: 256, volume: 1, line: 'Respuesta clara:' },
  { at: 220, from: 260, to: 292, volume: 1, line: 'sí, alinéalo.' },
  { at: 288, from: 304, to: 338, volume: 1, line: 'Mira dónde dispara él' },
  { at: 332, from: 343, to: 387, volume: 1, line: 'y dónde concede Sunderland.' },
  { at: 386, from: 404, to: 438, volume: 1, line: 'Tu asistente técnico.' },
  { at: 433, from: 448, to: 479, volume: 1, line: 'Pruébalo gratis.' },
];

export const CUES: { at: number; file: SfxFile; volume: number; note: string }[] = [
  { at: 34, file: 'tap', volume: 0.35, note: 'focus the ID field' },
  ...[40, 44, 48, 52, 56, 60].map((at) => ({ at, file: 'key' as const, volume: 0.9, note: 'ID digit' })),
  { at: 62, file: 'tap', volume: 0.35, note: 'Conectar' },
  { at: 72, file: 'tap', volume: 0.35, note: 'SQUAD tab' },
  { at: 116, file: 'tap', volume: 0.35, note: 'N.J' },
  { at: 170, file: 'tap', volume: 0.35, note: 'Asistente' },
  { at: 214, file: 'pop', volume: 0.85, note: 'verdict spotlight' },
  { at: 266, file: 'whoosh', volume: 0.55, note: 'scroll to Zonas' },
  { at: 300, file: 'sparkle', volume: 0.85, note: 'his shooting cells' },
  { at: 358, file: 'sparkle', volume: 0.85, note: 'Sunderland row' },
  { at: 404, file: 'logo', volume: 0.75, note: 'logo reveal' },
];
