import type { Config } from 'tailwindcss';
import plugin from 'tailwindcss/plugin';

/**
 * Bendito Fantasy design tokens — extracted from the Stitch/Claude Design
 * handoff (`FPL Chat Hi-Fi.html`, design token object `T`).
 *
 * These are the frozen Track 3 U1 token contract. Components must theme
 * against these names (`bf-*`) — no default-palette utilities, no raw hex.
 * Exception: the FDR ramp in FixtureRunTable stays on the V2_MVP_ROADMAP
 * spec via the fdrColor helper (Decision 3) and is NOT tokenized here.
 */
const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bf: {
          bg: '#12111a',
          surface: '#1c1a26',
          card: '#211F29',
          teal: '#025E73',
          'teal-dark': '#01435B',
          coral: '#FF6A4D',
          'coral-soft': '#F27A5E',
          turquoise: '#02EBAE',
          cyan: '#04C4D9',
          gold: '#F2C572',
          purple: '#a78bfa',
          gray: '#ABA9AC',
          ink: '#0E0D12',
          text: '#f0f0f0',
        },
      },
      fontFamily: {
        sans: ['var(--font-barlow)', 'Barlow', 'sans-serif'],
        display: ['var(--font-archivo-black)', 'Archivo Black', 'sans-serif'],
      },
      borderRadius: {
        card: '12px',
      },
      boxShadow: {
        card: '0 4px 20px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.05)',
        menu: '0 8px 32px rgba(0,0,0,.5)',
      },
    },
  },
  plugins: [
    // High-contrast accessibility mode: `hc:` utilities apply when the user
    // enables the contrast switch (html[data-contrast="high"]). Default stays
    // brand-faithful (e.g. white on coral); hc: swaps to AA-compliant pairs.
    plugin(({ addVariant }) => {
      addVariant('hc', 'html[data-contrast="high"] &');
    }),
  ],
};

export default config;
