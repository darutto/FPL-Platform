# fpl-promo

Short-form promo videos for FPL Asistente, built with [Remotion](https://www.remotion.dev/).
Brand tokens mirror `packages/fpl-ui/tailwind.config.ts`; on-screen data comes from real app answers (`src/data.json`).

```bash
npm install
npx remotion studio            # live preview
npx remotion render src/index.ts Clip01 out/clip01.mp4 \
  --browser-executable=/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell \
  --chrome-mode=headless-shell  # cloud container; omit both flags on a normal machine
```

Clips: `Clip01`, "Toca. Pregunta. Entiende." (storyboard: `docs/marketing/06-clip-01-plan.md`).
