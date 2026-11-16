# fpl-promo

Short-form promo videos for FPL Asistente, built with [Remotion](https://www.remotion.dev/).

**Rule:** every piece of UI on screen is a real capture of the app. The compositions only move a camera over the captures, swap them where the app itself changes state, and add captions, tap pulses and the official logo. Nothing is redrawn.

Remotion's public dir is `docs/marketing/` (see `remotion.config.ts`), so the clips read the captures in `clip-01/captures/` and the logo in `assets/logo-bf.svg` directly.

```bash
npm install
npx remotion studio            # live preview
npx remotion render src/index.ts Clip01 out/clip01.mp4 \
  --browser-executable=/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell \
  --chrome-mode=headless-shell  # cloud container; omit both flags on a normal machine
```

Clips: `Clip01`, "Toca. Pregunta. Entiende." (approved storyboard: `docs/marketing/clip-01/storyboard/`).

## Sound (rendered locally, files never committed)

Stock music/SFX licences (Pixabay, Mixkit, Artlist…) allow the audio inside a finished
video, not as standalone files in this public repo, so `docs/marketing/assets/sfx/` is
gitignored. The cue sheet with exact frames is `src/clip01/sound.ts`.

On the machine that has the sounds:

1. Put these 7 files in `docs/marketing/assets/sfx/` (rename the chosen originals, convert to mp3 if needed):
   | File | What | Used at (frame @30fps) |
   |---|---|---|
   | `music.mp3` | lo-fi bed, 85–95 BPM, ≥15 s | 0–450, fade out from 426 |
   | `tap.mp3` | soft UI tap | 34, 62, 72, 116, 170 |
   | `key.mp3` | phone keyboard click | 40, 44, 48, 52, 56, 60 |
   | `pop.mp3` | soft pop / success chime | 214 (verdict spotlight) |
   | `whoosh.mp3` | short whoosh / swipe | 266 (scroll to Zonas) |
   | `sparkle.mp3` | sparkle / shimmer | 300, 358 (highlights) |
   | `logo.mp3` | logo reveal / soft impact | 404 |
2. Write `docs/marketing/assets/sfx/SOURCES.md` (also gitignored) with each file's site, original name and licence.
3. Render with sound:
   ```bash
   cd packages/fpl-promo
   npx remotion render src/index.ts Clip01 ../../docs/marketing/clip-01/clip01-v4.mp4 --props='{"withSound":true}'
   ```
4. Commit only the MP4 (plus a one-line source list in `docs/marketing/clip-01/README.md` if you want credit noted). Volumes live in `sound.ts`.
