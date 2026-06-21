/**
 * Dev-only tier override (client helpers).
 *
 * Lets a developer impersonate any quota tier locally without touching their
 * real Clerk/Patreon membership. The chosen tier is stored in the `dev_tier`
 * cookie; the middleware reads it to inject `x-user-tier` (so the backend gate
 * sees the impersonated tier) and the WC shell reads it to drive the
 * web-search toggle — keeping UI and backend in lockstep.
 *
 * HARD-GATED to non-production: every reader checks NODE_ENV, so a stray cookie
 * in prod is ignored and the real tier always wins. The backend also still
 * enforces the true gate independently.
 */
import { DEV_TIER_COOKIE, isQuotaBucket, type QuotaBucket } from './tiers';

/** Whether the dev tier override is active in this environment. */
export function devTierEnabled(): boolean {
  return process.env.NODE_ENV !== 'production';
}

/** Read the impersonated tier from the cookie (client-side). Returns undefined
 *  in production, on the server, or when no valid cookie is set. */
export function readDevTier(): QuotaBucket | undefined {
  if (!devTierEnabled() || typeof document === 'undefined') return undefined;
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${DEV_TIER_COOKIE}=([^;]+)`),
  );
  const value = match?.[1];
  return isQuotaBucket(value) ? value : undefined;
}

/** Persist the impersonated tier (client-side). Pass undefined to clear it. */
export function setDevTier(tier: QuotaBucket | undefined): void {
  if (typeof document === 'undefined') return;
  if (tier === undefined) {
    document.cookie = `${DEV_TIER_COOKIE}=; path=/; max-age=0`;
  } else {
    document.cookie = `${DEV_TIER_COOKIE}=${tier}; path=/; max-age=86400`;
  }
}
