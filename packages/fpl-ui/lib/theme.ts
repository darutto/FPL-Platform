/**
 * theme.ts — centralized Bendito Fantasy semantic color maps (Track 3 U1).
 *
 * Single source for every card's tier/recommendation/status styling so the
 * whole UI themes against one place. Tokens live in tailwind.config.ts
 * (`bf-*`); this module maps domain semantics → token classes.
 *
 * Spanish labels are unchanged from the pre-reskin components (copy
 * integrity invariant). Only colors/decoration moved to the BF palette:
 *   emerald → turquoise · amber → gold · violet/indigo → cyan
 *   red → coral · slate → gray
 *
 * The FDR ramp is deliberately NOT here — fdrColor in FixtureRunTable owns
 * those colors (V2_MVP_ROADMAP spec, Decision 3).
 */
import type {
  CaptainTier,
  TransferRecommendation,
  ChipRecommendation,
} from './types';

// ---------------------------------------------------------------------------
// Accent hex — for SVG ornaments / inline decoration that can't take classes.
// Mirrors tailwind.config.ts theme.extend.colors.bf. Do not use in className.
// ---------------------------------------------------------------------------

export type Accent =
  | 'turquoise'
  | 'cyan'
  | 'coral'
  | 'coralSoft'
  | 'gold'
  | 'purple'
  | 'gray';

export const ACCENT_HEX: Record<Accent, string> = {
  turquoise: '#02EBAE',
  cyan: '#04C4D9',
  coral: '#FF6A4D',
  coralSoft: '#F27A5E',
  gold: '#F2C572',
  purple: '#a78bfa',
  gray: '#ABA9AC',
};

// ---------------------------------------------------------------------------
// Card shell — DS card surface: 12px radius, hairline accent border,
// translucent dark surface, soft shadow. Ornament SVGs sit behind content.
// ---------------------------------------------------------------------------

export const CARD_BASE =
  'relative overflow-hidden rounded-card bg-gradient-to-br from-bf-surface/70 to-bf-surface/55 shadow-card';

/** Per-accent border + heading classes for the card shell. */
export const CARD_ACCENT: Record<Accent, { border: string; heading: string }> = {
  turquoise: { border: 'border border-bf-turquoise/20', heading: 'text-bf-turquoise' },
  cyan: { border: 'border border-bf-cyan/20', heading: 'text-bf-cyan' },
  coral: { border: 'border border-bf-coral/20', heading: 'text-bf-coral' },
  coralSoft: { border: 'border border-bf-coral-soft/20', heading: 'text-bf-coral-soft' },
  gold: { border: 'border border-bf-gold/20', heading: 'text-bf-gold' },
  purple: { border: 'border border-bf-purple/20', heading: 'text-bf-purple' },
  gray: { border: 'border border-white/10', heading: 'text-bf-gray' },
};

// ---------------------------------------------------------------------------
// Tier badges — DS .tier-card: left accent bar + icon + uppercase label.
// ---------------------------------------------------------------------------

export const TIER_BADGE_BASE =
  'relative inline-flex items-center gap-1.5 overflow-hidden rounded px-2.5 py-0.5 pl-3 text-xs font-extrabold uppercase tracking-wide before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-[""]';

export const TIER_CONFIG: Record<
  CaptainTier,
  { label: string; icon: string; badgeClass: string; barClass: string }
> = {
  safe: {
    label: 'Favorito',
    icon: '★',
    badgeClass: 'bg-bf-turquoise/10 text-bf-turquoise before:bg-bf-turquoise',
    barClass: 'bg-bf-turquoise',
  },
  upside: {
    label: 'Potencial',
    icon: '⚡',
    badgeClass: 'bg-bf-gold/10 text-bf-gold before:bg-bf-gold',
    barClass: 'bg-bf-gold',
  },
  differential: {
    label: 'Diferencial',
    icon: '◆',
    badgeClass: 'bg-bf-cyan/10 text-bf-cyan before:bg-bf-cyan',
    barClass: 'bg-bf-cyan',
  },
  avoid: {
    label: 'Evitar',
    icon: '✕',
    badgeClass: 'bg-bf-coral/10 text-bf-coral before:bg-bf-coral',
    barClass: 'bg-bf-coral',
  },
  low_confidence: {
    label: 'Datos limitados',
    icon: '·',
    badgeClass: 'bg-bf-gray/10 text-bf-gray before:bg-bf-gray',
    barClass: 'bg-bf-gray',
  },
};

// ---------------------------------------------------------------------------
// Status pills — rounded-full tinted pills (DS risk/status pattern).
// ---------------------------------------------------------------------------

export const PILL_BASE =
  'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-bold';

export const RECOMMENDATION_CONFIG: Record<
  TransferRecommendation,
  { label: string; pillClass: string }
> = {
  transfer_in: {
    label: 'Fichar',
    pillClass: 'bg-bf-turquoise/10 border-bf-turquoise/40 text-bf-turquoise',
  },
  marginal_transfer_in: {
    label: 'Considerar',
    pillClass: 'bg-bf-gold/10 border-bf-gold/40 text-bf-gold',
  },
  hold: {
    label: 'Conservar',
    pillClass: 'bg-bf-gray/10 border-bf-gray/40 text-bf-gray',
  },
};

export const CHIP_RECOMMENDATION_CONFIG: Record<
  ChipRecommendation,
  { label: string; pillClass: string }
> = {
  conditions_favorable: {
    label: 'Condiciones favorables',
    pillClass: 'bg-bf-turquoise/10 border-bf-turquoise/40 text-bf-turquoise',
  },
  conditions_marginal: {
    label: 'Condiciones marginales',
    pillClass: 'bg-bf-gold/10 border-bf-gold/40 text-bf-gold',
  },
  conditions_unfavorable: {
    label: 'Condiciones desfavorables',
    pillClass: 'bg-bf-coral/10 border-bf-coral/40 text-bf-coral',
  },
  missing_context: {
    label: 'Datos insuficientes',
    pillClass: 'bg-bf-gray/10 border-bf-gray/40 text-bf-gray',
  },
};

export const MARGIN_CONFIG: Record<
  'narrow' | 'moderate' | 'clear',
  { text: string; pillClass: string }
> = {
  narrow: {
    text: 'ajustada',
    pillClass: 'bg-bf-gray/10 border-bf-gray/40 text-bf-gray',
  },
  moderate: {
    text: 'moderada',
    pillClass: 'bg-bf-gold/10 border-bf-gold/40 text-bf-gold',
  },
  clear: {
    text: 'clara',
    pillClass: 'bg-bf-cyan/10 border-bf-cyan/40 text-bf-cyan',
  },
};

// ---------------------------------------------------------------------------
// Injury status tones — InjuriesTable keeps its classification logic;
// only the class outputs come from here.
// ---------------------------------------------------------------------------

export type StatusTone = 'bad' | 'warn' | 'good';

export const STATUS_TONE_CLASSES: Record<StatusTone, string> = {
  bad: 'bg-bf-coral/10 border-bf-coral/40 text-bf-coral',
  warn: 'bg-bf-gold/10 border-bf-gold/40 text-bf-gold',
  good: 'bg-bf-turquoise/10 border-bf-turquoise/40 text-bf-turquoise',
};

// ---------------------------------------------------------------------------
// Quota tones — bucket boundaries are the quota contract and MUST stay
// byte-identical to the duplicated copy in quota-indicator.test.ts:
//   remaining/cap > 0.5 → ok · > 0.2 → warn · else danger
// ---------------------------------------------------------------------------

export type QuotaTone = 'ok' | 'warn' | 'danger';

export function quotaTone(remaining: number, cap: number): QuotaTone {
  if (cap <= 0) return 'danger';
  const pct = remaining / cap;
  if (pct > 0.5) return 'ok';
  if (pct > 0.2) return 'warn';
  return 'danger';
}

export const QUOTA_TONE_CLASSES: Record<
  QuotaTone,
  { pill: string; dot: string; bar: string; text: string }
> = {
  ok: {
    pill: 'text-bf-turquoise border-bf-turquoise/40 bg-bf-turquoise/10',
    dot: 'bg-bf-turquoise',
    bar: 'bg-bf-turquoise',
    text: 'text-bf-turquoise',
  },
  warn: {
    pill: 'text-bf-gold border-bf-gold/40 bg-bf-gold/10',
    dot: 'bg-bf-gold',
    bar: 'bg-bf-gold',
    text: 'text-bf-gold',
  },
  danger: {
    pill: 'text-bf-coral border-bf-coral/40 bg-bf-coral/10',
    dot: 'bg-bf-coral',
    bar: 'bg-bf-coral',
    text: 'text-bf-coral',
  },
};

// ---------------------------------------------------------------------------
// Resource accents — per-@resource card accent (Stitch RESOURCES map).
// ---------------------------------------------------------------------------

export const RESOURCE_ACCENT: Record<string, Accent> = {
  injuries: 'coralSoft',
  top_form: 'gold',
  top_xg: 'coral',
  top_points: 'turquoise',
  top_minutes: 'cyan',
  popular: 'purple',
};
