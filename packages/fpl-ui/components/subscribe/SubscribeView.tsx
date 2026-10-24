/**
 * SubscribeView - the membership page, in the language it is given.
 *
 * Pure (no hooks): the page is a server component that asks the request for its language and hands it here.
 * The Patreon tier names stay as Patreon spells them; the English screen adds a descriptor (tierTitle).
 */
import {
  SUBSCRIPTION_TIERS,
  QUOTA_BUCKETS,
  allowanceLabel,
  tierPerks,
  tierTitle,
  type SubscriptionTier,
} from '@/lib/tiers';
import { translate } from '@/lib/i18n/dictionary';
import type { Locale } from '@/lib/i18n/locale';

const PATREON_URL = 'https://www.patreon.com/benditofantasy';

function TierCard({ tier, locale }: { tier: SubscriptionTier; locale: Locale }) {
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);
  return (
    <div
      className={`relative flex flex-col rounded-card bg-bf-card p-6 shadow-card ${
        tier.highlighted ? 'ring-2 ring-bf-cyan' : ''
      }`}
    >
      {tier.highlighted && (
        <span className="absolute -top-3 left-6 rounded-full bg-bf-cyan px-3 py-0.5 text-[11px] font-bold uppercase tracking-wide text-bf-ink">
          {t('sub.recommended')}
        </span>
      )}

      {/* Header: name + price */}
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-display text-lg text-bf-text">{tierTitle(tier, locale)}</h2>
        <span className="whitespace-nowrap text-sm text-bf-gray">
          <span className="font-display text-xl text-bf-text">${tier.priceUsd}</span> {t('sub.perMonth')}
        </span>
      </div>

      {/* Usage descriptor - the assistant-usage allowance, distinct from the
          community perks below. Every tier gets some assistant access, Tribuna
          included (15 msgs/day, 3x the unpaid 5); the cap grows with the
          membership. */}
      <div className="mt-3 rounded-card border border-bf-cyan/30 bg-bf-cyan/10 px-3 py-2">
        <div className="text-[10px] font-bold uppercase tracking-widest text-bf-cyan/80">
          {t('sub.usage')}
        </div>
        <div className="mt-0.5 text-sm font-semibold text-bf-text">{allowanceLabel(tier.bucket, locale)}</div>
      </div>

      {/* Community / content perks */}
      <ul className="mt-4 flex-1 space-y-1.5 text-sm text-bf-gray">
        {tierPerks(tier, locale).map((perk) => (
          <li key={perk} className="flex gap-2">
            <span className="mt-0.5 text-bf-cyan">✓</span>
            <span>{perk}</span>
          </li>
        ))}
      </ul>

      <a
        href={PATREON_URL}
        target="_blank"
        rel="noreferrer"
        className={`mt-5 inline-block w-full rounded-card px-4 py-2.5 text-center font-semibold transition ${
          tier.highlighted
            ? 'bg-bf-coral text-bf-ink hover:bg-bf-coral-soft'
            : 'bg-bf-bg text-bf-text hover:bg-bf-card/60'
        }`}
      >
        {t('sub.join')}
      </a>
    </div>
  );
}

export default function SubscribeView({ locale }: { locale: Locale }) {
  return (
    <main className="flex min-h-screen flex-col items-center bg-bf-bg px-4 py-12 text-bf-text">
      <div className="w-full max-w-4xl">
        <header className="text-center">
          <h1 className="font-display text-3xl text-bf-text">{translate(locale, 'sub.title')}</h1>
          <p className="mx-auto mt-2 max-w-xl text-sm text-bf-gray">
            {translate(locale, 'sub.intro', { n: QUOTA_BUCKETS.free.msgsPerDay })}
          </p>
        </header>

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {SUBSCRIPTION_TIERS.map((tier) => (
            <TierCard key={tier.name} tier={tier} locale={locale} />
          ))}
        </div>

        <p className="mt-8 text-center text-xs text-bf-gray">
          {translate(locale, 'sub.member')}{' '}
          <a href="/login" className="text-bf-cyan underline">
            {translate(locale, 'sub.signIn')}
          </a>{' '}
          {translate(locale, 'sub.sync')}
        </p>
      </div>
    </main>
  );
}
