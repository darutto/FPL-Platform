/**
 * Subscription tiers — single source of truth for the UI.
 *
 * The Patreon ladder ($1/$5/$10/$15/$50) maps onto 5 backend quota buckets
 * (see app/api/auth/sync-patreon/route.ts and the backend quota.py TIERS
 * table). Each paid rung adds a distinct kind of value: $1 = 3× the free
 * message allowance (no other perk — see patreon_tribuna in quota.py), $5 =
 * assistant access proper, $10 = web search + 2× messages, $15 = far more
 * messages. Plata & Oro share the premium bucket (Oro differentiates on
 * perks, not caps).
 *
 * ⚠️ The compute fields below (msgsPerDay, msgsPerMonth, webSearch) MUST stay
 *    in sync with the backend: quota.py `daily_message_cap` /
 *    `monthly_message_cap` and the web-search tier gate
 *    (WEB_SEARCH_TIERS = {patreon_plus, patreon_premium}). If you retune caps
 *    in quota.py, update QUOTA_BUCKETS here too.
 */
export type QuotaBucket =
  | 'free'
  | 'patreon_tribuna'
  | 'patreon_basic'
  | 'patreon_plus'
  | 'patreon_premium';

/** Dev-only tier override cookie (see lib/dev-tier.ts + DevTierSwitcher).
 *  Honored by middleware and the WC shell ONLY when NODE_ENV !== 'production'. */
export const DEV_TIER_COOKIE = 'dev_tier';

/** Type guard: is `v` one of the known quota buckets? */
export function isQuotaBucket(v: unknown): v is QuotaBucket {
  return typeof v === 'string' && v in QUOTA_BUCKETS;
}

export interface QuotaBucketInfo {
  /** Daily message cap — the limit that binds for normal use. */
  msgsPerDay: number;
  /** Monthly message cap — quota.py `monthly_message_cap`. */
  msgsPerMonth: number;
  /** Whether the premium web-search tool is unlocked at this bucket. */
  webSearch: boolean;
  /** Short Spanish descriptor of the assistant-usage allowance. */
  allowance: string;
}

export const QUOTA_BUCKETS: Record<QuotaBucket, QuotaBucketInfo> = {
  free: {
    msgsPerDay: 5,
    msgsPerMonth: 30,
    webSearch: false,
    allowance: '5 mensajes al día',
  },
  patreon_tribuna: {
    msgsPerDay: 15,
    msgsPerMonth: 300,
    webSearch: false,
    allowance: '15 mensajes al día',
  },
  patreon_basic: {
    msgsPerDay: 30,
    msgsPerMonth: 600,
    webSearch: false,
    allowance: '30 mensajes al día',
  },
  patreon_plus: {
    msgsPerDay: 60,
    msgsPerMonth: 1200,
    webSearch: true,
    allowance: '60 mensajes al día · búsqueda web',
  },
  patreon_premium: {
    msgsPerDay: 150,
    msgsPerMonth: 3000,
    webSearch: true,
    allowance: '150 mensajes al día · búsqueda web',
  },
};

export interface SubscriptionTier {
  /** Patreon tier display name. */
  name: string;
  /** Monthly price in USD. */
  priceUsd: number;
  /** Which backend quota bucket this pledge maps to. */
  bucket: QuotaBucket;
  /** Top community/content perks (cumulative — each tier adds to the prior). */
  perks: string[];
  /** Marks the recommended entry tier (first with web search). */
  highlighted?: boolean;
}

export const SUBSCRIPTION_TIERS: SubscriptionTier[] = [
  {
    name: 'Tribuna',
    priceUsd: 1,
    bucket: 'patreon_tribuna',
    perks: [
      'Mención especial en el podcast',
      'Acceso al Discord del club',
      'Competencias exclusivas con miembros del club',
    ],
  },
  {
    name: 'Gafete de cancha',
    priceUsd: 5,
    bucket: 'patreon_basic',
    perks: [
      'Todos los beneficios de Tribuna',
      'Premios mensuales en la miniliga (mín. 5 miembros)',
      'Uniforme con escudo personalizado',
    ],
  },
  {
    name: 'Socio Junior',
    priceUsd: 10,
    bucket: 'patreon_plus',
    highlighted: true,
    perks: [
      'Todos los beneficios de Gafete de cancha',
      'Ruedas de prensa y conferencias del club',
      'Podcast exclusivo de la liga interclubes',
    ],
  },
  {
    name: 'Ejecutivo: carné de plata',
    priceUsd: 15,
    bucket: 'patreon_premium',
    perks: [
      'Todos los beneficios de Socio Junior',
      'Partidos narrados en directo en Discord',
      'Acceso prioritario a eventos (Fanfest y más)',
    ],
  },
  {
    name: 'Ejecutivo: Carné de oro',
    priceUsd: 50,
    bucket: 'patreon_premium',
    perks: [
      'Todos los beneficios de carné de plata',
      'Voto en decisiones de la directiva del club',
      'Elemento conmemorativo personalizado cada temporada',
    ],
  },
];


/**
 * The cheapest pledge that unlocks each paid bucket, cheapest first.
 *
 * Upgrade surfaces derive their tier table from this instead of hand-listing
 * rungs: the previous hand-written table in QuotaIndicator omitted Socio
 * Junior (the `highlighted` tier, and the first with web search) and offered
 * a "$30 / unlimited" tier that has never existed.
 *
 * `shortName` trims the qualifier after the colon so the long premium name
 * ("Ejecutivo: carné de plata") fits a narrow column. Mirrors UPGRADE_LADDER
 * in the backend quota.py — keep the two in step. patreon_tribuna is
 * included here (unlike the backend comment's note about collapsed rungs):
 * it is its own bucket with its own cap, not a display alias for another one.
 */
export interface PaidRung {
  bucket: QuotaBucket;
  name: string;
  shortName: string;
  priceUsd: number;
}

export const PAID_LADDER: PaidRung[] = (
  ['patreon_tribuna', 'patreon_basic', 'patreon_plus', 'patreon_premium'] as const
).map((bucket) => {
  const cheapest = SUBSCRIPTION_TIERS
    .filter((t) => t.bucket === bucket)
    .reduce((a, b) => (a.priceUsd <= b.priceUsd ? a : b));
  return {
    bucket,
    name: cheapest.name,
    shortName: cheapest.name.split(':')[0].trim(),
    priceUsd: cheapest.priceUsd,
  };
});
