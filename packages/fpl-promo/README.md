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
