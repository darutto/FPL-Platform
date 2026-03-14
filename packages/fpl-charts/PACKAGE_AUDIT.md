# PACKAGE AUDIT — `fpl-charts`
**Status:** Pre-adoption (partially scaffolded — `theme.ts` only)
**Audit date:** 2026-03-07
**Risk level:** 🟡 MEDIUM

---

## Purpose

Shared React component library and design system for all FPL front-end applications:
- Brand colour tokens (single source of truth)
- Reusable player UI components (`PlayerCard`, `ScoreDeltaBadge`, `ComparisonView`, etc.)
- Chart abstractions (animated bar chart, xG/xA stat charts)

---

## Source Files Derived From

### Currently written (`theme.ts` only):
| Source file | Lines used | Action taken |
|---|---|---|
| `captaincy-showdown/src/brand.ts` | Full file (9 lines) | **Copied verbatim**, re-exported as `BRAND` constant |
| `Top stats per week FPL/styles/main.css` | CSS custom property values (lines 1–15) | **Extracted** as TypeScript constants in `COLORS` object |
| `FPL-team-stats/script.js` | Inline Chart.js colour array | **Extracted** as `CHART_COLORS` array |
| `captaincy-showdown/src/components/PlayerCard.tsx` | `getRiskIndicator()` logic | **Extracted** as `getRiskLevel()` + `RISK` config object |

### Not yet written (planned for Phase 5 of migration):
| Source file | Planned destination |
|---|---|
| `captaincy-showdown/src/components/PlayerCard.tsx` | `src/components/PlayerCard.tsx` |
| `captaincy-showdown/src/components/ScoreDeltaBadge.tsx` | `src/components/ScoreDeltaBadge.tsx` |
| `captaincy-showdown/src/components/ComparisonView.tsx` | `src/components/ComparisonView.tsx` |
| `captaincy-showdown/src/components/EnhancedPlayerCard.tsx` | `src/components/EnhancedPlayerCard.tsx` |
| `captaincy-showdown/src/components/VersusIndicator.tsx` | `src/components/VersusIndicator.tsx` |
| `Top stats per week FPL/scripts/chart.js` | `src/PlayerChart.ts` (TypeScript port) |

---

## What Was Copied As-Is vs Adapted

### `theme.ts`
- `BRAND` object → **copied verbatim** from `brand.ts`
- `COLORS` → **new constants** extracting the hex values previously hardcoded in both `main.css` and scattered across Tailwind class names in components
- `CHART_COLORS` → **new array** replacing the inline colour array in `FPL-team-stats/script.js`
- `CSS_VARS` → **new mapping** providing the CSS variable names from `main.css` as a typed reference
- `injectCssVars()` → **new helper** that replaces the CSS `:root {}` block with a programmatic equivalent
- `RISK` and `getRiskLevel()` → **extracted** from `PlayerCard.tsx::getRiskIndicator()` into standalone testable utilities

---

## Assumptions

1. All FPL apps use the same five brand colours. If a project diverges (e.g. a white-label version), it should import and override specific tokens rather than editing this file.
2. Components use Tailwind CSS with the custom CSS variable names (`brand-coral`, `brand-green`, etc.) defined in the consuming app's Tailwind config. The shared `theme.ts` exports the raw hex values — consuming apps are responsible for registering them with Tailwind.
3. `PlayerCard.tsx` and other components are React 19 functional components using Tailwind utility classes. They assume Tailwind's base stylesheet is loaded by the consuming app.
4. The `chart.js` `PlayerChart` class is vanilla JavaScript targeting browser DOM. A TypeScript port for this package should maintain the same class API to avoid breaking the `Top stats per week FPL` streaming overlay.

---

## Known Risks

### 🔴 HIGH: Package is largely unimplemented
Only `theme.ts` has been written. The component files (`PlayerCard.tsx`, etc.) are planned but not created. This package **cannot be adopted** until Phase 5 of the migration is executed.

**Action required:** This package should be the last to migrate. Components should be promoted from `captaincy-showdown` only after that project is stable on the other shared packages.

### 🟡 MEDIUM: Tailwind v4 in `captaincy-showdown` vs unknown versions elsewhere
`captaincy-showdown` uses Tailwind v4. The `Top stats per week FPL` dashboard uses plain CSS with custom properties (no Tailwind). A shared `PlayerCard.tsx` relying on Tailwind classes will not render correctly if imported into a non-Tailwind app. Components should either be style-agnostic (CSS modules or inline styles) or the package should clearly declare `tailwindcss >= 4.0` as a peer dependency.

### 🟡 MEDIUM: `injectCssVars()` DOM side effect
`injectCssVars()` mutates `document.documentElement`. In SSR environments (Next.js, Astro) this will throw because `document` is not defined. An SSR guard or lazy invocation pattern should be added before this function is used in SSR contexts.

### 🟡 MEDIUM: `PlayerChart.ts` port not yet written
`Top stats per week FPL` relies on the `chart.js` `PlayerChart` class hierarchy (`XGChart`, `XAssistsChart`, etc.) for its animated overlay. Until this class is ported to TypeScript in this package, the streaming dashboard cannot adopt it. The port requires maintaining identical DOM output and animation timing.

### 🟢 LOW: `BRAND.watermarkSrc` path is project-specific
`BRAND.watermarkSrc` is `/logos-and-brand-art/watermark.svg`. This path assumes the consuming app serves assets at this location. Different apps may have the watermark at a different path. This should be a configurable default, not a hardcoded string.

---

## Dependencies

| Dependency | Version | Notes |
|---|---|---|
| `react` | ≥ 19 | Peer dependency for component files |
| `react-dom` | ≥ 19 | Peer dependency |
| `tailwindcss` | ≥ 4.0 | Peer dependency for Tailwind class names |

`theme.ts` itself has **zero runtime dependencies** and can be imported by any TypeScript project.

---

## Acceptance Criteria for First Adoption

**Phase 5 minimum (theme only):**
- [ ] `COLORS.coral` equals `#FF6A4D`
- [ ] `COLORS.green` equals `#02EBAE`
- [ ] `getCsvPath` from `fpl-api-client` and `BRAND.background` from this package are both importable in the same consuming app without conflict
- [ ] `injectCssVars()` registers all five CSS custom properties in the browser `:root`

**Full component adoption (deferred to Phase 5):**
- [ ] `PlayerCard` renders identically to the `captaincy-showdown` version in visual regression tests
- [ ] All `captaincy-showdown` component unit tests pass after switching imports to this package
- [ ] `Top stats per week FPL` streaming dashboard loads without errors after `PlayerChart` port


