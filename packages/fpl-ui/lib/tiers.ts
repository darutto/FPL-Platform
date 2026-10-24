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
import { translate, type DictKey } from './i18n/dictionary';
import { DEFAULT_LOCALE, type Locale } from './i18n/locale';

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

/** 'N messages a day' (with ' · web search' where the bucket has it), in the language showing. */
function allowanceText(msgsPerDay: number, webSearch: boolean, locale: Locale): string {
  return translate(locale, webSearch ? 'plan.allowWeb' : 'plan.allow', { n: msgsPerDay });
}

export const QUOTA_BUCKETS: Record<QuotaBucket, QuotaBucketInfo> = {
  free: {
    msgsPerDay: 5,
    msgsPerMonth: 30,
    webSearch: false,
    allowance: allowanceText(5, false, 'es'),
  },
  patreon_tribuna: {
    msgsPerDay: 15,
    msgsPerMonth: 300,
    webSearch: false,
    allowance: allowanceText(15, false, 'es'),
  },
  patreon_basic: {
    msgsPerDay: 30,
    msgsPerMonth: 600,
    webSearch: false,
    allowance: allowanceText(30, false, 'es'),
  },
  patreon_plus: {
    msgsPerDay: 60,
    msgsPerMonth: 1200,
    webSearch: true,
    allowance: allowanceText(60, true, 'es'),
  },
  patreon_premium: {
    msgsPerDay: 150,
    msgsPerMonth: 3000,
    webSearch: true,
    allowance: allowanceText(150, true, 'es'),
  },
};

/** The usage line of a bucket in the language showing; the numbers always come from QUOTA_BUCKETS. */
export function allowanceLabel(bucket: QuotaBucket, locale: Locale = DEFAULT_LOCALE): string {
  const info = QUOTA_BUCKETS[bucket];
  return allowanceText(info.msgsPerDay, info.webSearch, locale);
}

export type PlanId = 'tribuna' | 'gafete' | 'socio' | 'plata' | 'oro';

export interface SubscriptionTier {
  /** Stable id: keys the plan's dictionary entries. */
  id: PlanId;
  /** Patreon tier display name. A proper name: it is the same in every language. */
  name: string;
  /** Monthly price in USD. */
  priceUsd: number;
  /** Which backend quota bucket this pledge maps to. */
  bucket: QuotaBucket;
  /** Top community/content perks (cumulative — each tier adds to the prior), as dictionary keys. */
  perkKeys: [DictKey, DictKey, DictKey];
  /** Marks the recommended entry tier (first with web search). */
  highlighted?: boolean;
}

export const SUBSCRIPTION_TIERS: SubscriptionTier[] = [
  {
    id: 'tribuna',
    name: 'Tribuna',
    priceUsd: 1,
    bucket: 'patreon_tribuna',
    perkKeys: ['plan.tribuna.perk1', 'plan.tribuna.perk2', 'plan.tribuna.perk3'],
  },
  {
    id: 'gafete',
    name: 'Gafete de cancha',
    priceUsd: 5,
    bucket: 'patreon_basic',
    perkKeys: ['plan.gafete.perk1', 'plan.gafete.perk2', 'plan.gafete.perk3'],
  },
  {
    id: 'socio',
    name: 'Socio Junior',
    priceUsd: 10,
    bucket: 'patreon_plus',
    highlighted: true,
    perkKeys: ['plan.socio.perk1', 'plan.socio.perk2', 'plan.socio.perk3'],
  },
  {
    id: 'plata',
    name: 'Ejecutivo: carné de plata',
    priceUsd: 15,
    bucket: 'patreon_premium',
    perkKeys: ['plan.plata.perk1', 'plan.plata.perk2', 'plan.plata.perk3'],
  },
  {
    id: 'oro',
    name: 'Ejecutivo: Carné de oro',
    priceUsd: 50,
    bucket: 'patreon_premium',
    perkKeys: ['plan.oro.perk1', 'plan.oro.perk2', 'plan.oro.perk3'],
  },
];

/**
 * The tier's heading. The Patreon name is kept as Patreon spells it, in every language; the English screen
 * adds a short descriptor so an English reader knows what it is ("Tribuna · Supporter"). Spanish shows the name alone.
 */
export function tierTitle(tier: SubscriptionTier, locale: Locale = DEFAULT_LOCALE): string {
  const descriptor = translate(locale, `plan.${tier.id}.descriptor` as DictKey);
  return descriptor ? `${tier.name} · ${descriptor}` : tier.name;
}

/** The tier's three perks in the language showing. */
export function tierPerks(tier: SubscriptionTier, locale: Locale = DEFAULT_LOCALE): string[] {
  return tier.perkKeys.map((key) => translate(locale, key));
}


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
