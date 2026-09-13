import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';
import { DEV_TIER_COOKIE, isQuotaBucket } from '@/lib/tiers';

// Both assistant shells require sign-in: the FPL chat (/chat) and the World
// Cup chat (/wc/chat). Free tier is admitted (limited taste); anonymous is not.
const isProtectedRoute = createRouteMatcher(['/chat(.*)', '/wc(.*)']);

export default clerkMiddleware(async (auth, req) => {
  const { userId, sessionClaims } = await auth();
  // Quota bucket mirrored onto the Clerk session by /api/auth/sync-patreon.
  // One of QuotaBucket (lib/tiers.ts); absent → "free".
  let tier =
    (sessionClaims?.metadata as { tier?: string } | undefined)?.tier ?? 'free';

  // Dev-only tier impersonation: when NODE_ENV !== 'production' a developer can
  // set the `dev_tier` cookie (see DevTierSwitcher) to test any tier's behaviour
  // locally. Ignored in production so it can never override a real membership.
  if (process.env.NODE_ENV !== 'production') {
    const devTier = req.cookies.get(DEV_TIER_COOKIE)?.value;
    if (isQuotaBucket(devTier)) tier = devTier;
  }

  // Trust boundary: identity headers are SERVER-SET ONLY. Strip whatever the
  // client sent (an anonymous caller could otherwise forge `x-user-tier:
  // patreon_premium` straight into /api/proxy) and re-set them from the Clerk
  // session below. This happens on EVERY request, authenticated or not, and
  // the stripped headers are what the route handlers receive — see the single
  // `NextResponse.next({ request: { headers } })` exit at the bottom.
  const headers = new Headers(req.headers);
  headers.delete('x-user-id');
  headers.delete('x-user-tier');

  // Gate /chat: must be signed in, but ALL tiers (including free) get in.
  // Free is a deliberately limited taste of the assistant (5 msgs/day, enforced
  // by the backend quota) — a funnel meant to drive subscriptions, not a wall.
  // Sign-in is still required so each free user gets their own per-user quota
  // bucket rather than sharing one anonymous bucket.
  if (isProtectedRoute(req) && !userId) {
    return NextResponse.redirect(new URL('/login', req.url));
  }

  // Forward identity + tier to the backend quota system. The API proxy routes
  // (proxy, session/*, wc-proxy/*, quota, wc-quota) copy these through via
  // lib/identity-headers.ts to FastAPI's _extract_user_context, which keys
  // per-user quota on X-User-Id and enforces caps by X-User-Tier.
  if (userId) {
    headers.set('x-user-id', userId);
    headers.set('x-user-tier', tier);
  }

  // Single exit for every non-redirect path — anonymous requests MUST also go
  // through here so the stripped headers (not the originals) reach the route.
  return NextResponse.next({ request: { headers } });
});

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
};
