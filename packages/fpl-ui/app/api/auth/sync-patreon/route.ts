import { auth, clerkClient } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

const PATREON_STRATEGY = (process.env.NEXT_PUBLIC_CLERK_PATREON_STRATEGY ||
  'oauth_custom_patreon') as `oauth_custom_${string}`;
const PATREON_IDENTITY_URL =
  'https://www.patreon.com/api/oauth2/v2/identity?include=memberships&fields[member]=patron_status,currently_entitled_amount_cents';

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

  if (ADMIN_EMAILS.length > 0) {
    const user = await client.users.getUser(userId);
    const emails = user.emailAddresses.map((e) => e.emailAddress.toLowerCase());
    if (emails.some((e) => ADMIN_EMAILS.includes(e))) {
      await client.users.updateUserMetadata(userId, {
        publicMetadata: { tier: 'subscriber', role: 'admin' },
      });
      return NextResponse.json({ tier: 'subscriber' });
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
  const members: Array<{ type: string; attributes?: { patron_status?: string } }> =
    identity.included ?? [];
  const isActive = members.some(
    (m) => m.type === 'member' && m.attributes?.patron_status === 'active_patron'
  );
  const tier = isActive ? 'subscriber' : 'free';

  await client.users.updateUserMetadata(userId, {
    publicMetadata: { tier },
  });

  return NextResponse.json({ tier });
}
