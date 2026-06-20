import { auth, clerkClient } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

const PATREON_STRATEGY = (process.env.NEXT_PUBLIC_CLERK_PATREON_STRATEGY ||
  'oauth_custom_patreon') as `oauth_custom_${string}`;
const PATREON_IDENTITY_URL =
  'https://www.patreon.com/api/oauth2/v2/identity?include=memberships&fields[member]=patron_status,currently_entitled_amount_cents';

/**
 * Map a patron's entitled pledge (cents) onto a backend quota bucket. The
 * Patreon ladder ($1/$5/$10/$15/$50) collapses onto 4 quota buckets — each
 * paid rung adds a distinct kind of value:
 *   $0–$1   (Tribuna)    -> free            (no assistant access)
 *   $5      (Gafete)     -> patreon_basic   (30 msgs/day, NO web search)
 *   $10     (Socio Jr)   -> patreon_plus    (60 msgs/day + web search)
 *   $15+    (Plata, Oro) -> patreon_premium (150 msgs/day + web search)
 * Plata & Oro share compute; Oro differentiates on perks, not caps.
 * Bucket names MUST match the keys in the backend quota TIERS table.
 */
function tierFromCents(
  cents: number,
): 'free' | 'patreon_basic' | 'patreon_plus' | 'patreon_premium' {
  if (cents >= 1500) return 'patreon_premium';
  if (cents >= 1000) return 'patreon_plus';
  if (cents >= 500) return 'patreon_basic';
  return 'free';
}

type Tier = ReturnType<typeof tierFromCents>;

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';
const INTERNAL_TOKEN = process.env.FPL_INTERNAL_TOKEN?.trim();

/**
 * Record a tier change in the backend audit log so free→paid conversions are
 * queryable even when the user never chats again (chat-turn rows only capture
 * users who keep using the assistant). Best-effort: a no-op when the tier is
 * unchanged, and never throws — a telemetry failure must not break sign-in.
 */
async function recordTierSync(
  userId: string,
  tier: Tier,
  previousTier: string | undefined,
): Promise<void> {
  if (tier === previousTier) return;
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (INTERNAL_TOKEN) headers['x-internal-token'] = INTERNAL_TOKEN;
    await fetch(`${BACKEND_URL}/events/tier-sync`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ user_id: userId, tier, previous_tier: previousTier ?? null }),
    });
  } catch {
    // best-effort telemetry — ignore transport errors
  }
}

/**
 * Called once after a Patreon OAuth sign-in completes (see /post-login).
 * Looks up the user's Patreon membership status via the OAuth token Clerk
 * stored during the SSO connection, then mirrors it onto the Clerk user as
 * publicMetadata.tier so middleware can gate /chat without re-calling Patreon.
 */
const ADMIN_EMAILS = (process.env.ADMIN_EMAILS ?? '')
  .split(',')
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

export async function POST() {
  const { userId } = await auth();
  if (!userId) {
    return NextResponse.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const client = await clerkClient();
  const user = await client.users.getUser(userId);
  const previousTier = (user.publicMetadata as { tier?: string }).tier;

  if (ADMIN_EMAILS.length > 0) {
    const emails = user.emailAddresses.map((e) => e.emailAddress.toLowerCase());
    if (emails.some((e) => ADMIN_EMAILS.includes(e))) {
      await client.users.updateUserMetadata(userId, {
        publicMetadata: { tier: 'patreon_premium', role: 'admin' },
      });
      await recordTierSync(userId, 'patreon_premium', previousTier);
      return NextResponse.json({ tier: 'patreon_premium' });
    }
  }

  const tokens = await client.users.getUserOauthAccessToken(userId, PATREON_STRATEGY);
  const accessToken = tokens.data[0]?.token;
  if (!accessToken) {
    return NextResponse.json({ tier: 'free' });
  }

  const identityRes = await fetch(PATREON_IDENTITY_URL, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!identityRes.ok) {
    return NextResponse.json({ error: 'patreon_api_error' }, { status: 502 });
  }

  const identity = await identityRes.json();
  const members: Array<{
    type: string;
    attributes?: { patron_status?: string; currently_entitled_amount_cents?: number };
  }> = identity.included ?? [];
  // Highest active pledge across memberships → quota bucket. Inactive patrons
  // (declined/former) contribute 0 cents and fall through to free.
  const cents = members
    .filter((m) => m.type === 'member' && m.attributes?.patron_status === 'active_patron')
    .reduce((max, m) => Math.max(max, m.attributes?.currently_entitled_amount_cents ?? 0), 0);
  const tier = tierFromCents(cents);

  await client.users.updateUserMetadata(userId, {
    publicMetadata: { tier },
  });
  await recordTierSync(userId, tier, previousTier);

  return NextResponse.json({ tier });
}
