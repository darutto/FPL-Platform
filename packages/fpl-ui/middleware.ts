import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';
import { DEV_TIER_COOKIE, isQuotaBucket } from '@/lib/tiers';

// Both assistant shells require sign-in: the FPL chat (/chat) and the World
// Cup chat (/wc/chat). Free tier is admitted (limited taste); anonymous is not.
const isProtectedRoute = createRouteMatcher(['/chat(.*)', '/wc(.*)']);

export default clerkMiddleware(async (auth, req) => {
  const { userId, sessionClaims } = await auth();
  // Quota bucket mirrored onto the Clerk session by /api/auth/sync-patreon.
  // One of "free" | "patreon_basic" | "patreon_premium"; absent → "free".
  let tier =
    (sessionClaims?.metadata as { tier?: string } | undefined)?.tier ?? 'free';

  // Dev-only tier impersonation: when NODE_ENV !== 'production' a developer can
  // set the `dev_tier` cookie (see DevTierSwitcher) to test any tier's behaviour
  // locally. Ignored in production so it can never override a real membership.
  if (process.env.NODE_ENV !== 'production') {
    const devTier = req.cookies.get(DEV_TIER_COOKIE)?.value;
    if (isQuotaBucket(devTier)) tier = devTier;
  }

  // Gate /chat: must be signed in, but ALL tiers (including free) get in.
  // Free is a deliberately limited taste of the assistant (5 msgs/day, enforced
  // by the backend quota) — a funnel meant to drive subscriptions, not a wall.
  // Sign-in is still required so each free user gets their own per-user quota
  // bucket rather than sharing one anonymous bucket.
  if (isProtectedRoute(req) && !userId) {
    return NextResponse.redirect(new URL('/login', req.url));
  }

  // Forward identity + tier to the backend quota system. The API proxy routes
  // (wc-proxy, proxy, quota) pass these through to FastAPI's _extract_user_context,
  // which keys per-user quota on X-User-Id and enforces caps by X-User-Tier.
  if (userId) {
    const headers = new Headers(req.headers);
    headers.set('x-user-id', userId);
    headers.set('x-user-tier', tier);
    return NextResponse.next({ request: { headers } });
  }
});

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
};
