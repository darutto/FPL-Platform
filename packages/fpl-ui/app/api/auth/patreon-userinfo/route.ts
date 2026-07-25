import { NextRequest, NextResponse } from 'next/server';

const PATREON_IDENTITY_URL =
  'https://www.patreon.com/api/oauth2/v2/identity?fields[user]=email';

interface PatreonIdentity {
  data?: {
    id?: unknown;
    attributes?: {
      email?: unknown;
    };
  };
}

const NO_STORE_HEADERS = {
  'Cache-Control': 'no-store',
};

/**
 * Clerk custom-OAuth user-info adapter for Patreon.
 *
 * Patreon returns JSON:API (`data.id`, `data.attributes.email`) while Clerk
 * needs flat OIDC-style claims. Clerk calls this endpoint with the Patreon
 * bearer token; the token is forwarded only to Patreon's fixed identity URL.
 */
export async function GET(request: NextRequest) {
  const authorization = request.headers.get('authorization')?.trim() ?? '';
  if (!/^Bearer\s+\S+$/i.test(authorization)) {
    return NextResponse.json(
      { error: 'missing_bearer_token' },
      { status: 401, headers: NO_STORE_HEADERS },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(PATREON_IDENTITY_URL, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: authorization,
      },
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json(
      { error: 'patreon_unreachable' },
      { status: 502, headers: NO_STORE_HEADERS },
    );
  }

  if (!upstream.ok) {
    return NextResponse.json(
      { error: 'patreon_identity_error' },
      { status: 502, headers: NO_STORE_HEADERS },
    );
  }

  let identity: PatreonIdentity;
  try {
    identity = (await upstream.json()) as PatreonIdentity;
  } catch {
    return NextResponse.json(
      { error: 'invalid_patreon_response' },
      { status: 502, headers: NO_STORE_HEADERS },
    );
  }

  const subject = identity.data?.id;
  const email = identity.data?.attributes?.email;
  if (typeof subject !== 'string' || !subject.trim()) {
    return NextResponse.json(
      { error: 'missing_patreon_user_id' },
      { status: 502, headers: NO_STORE_HEADERS },
    );
  }

  return NextResponse.json(
    {
      sub: subject,
      ...(typeof email === 'string' && email.trim()
        ? { email, email_verified: true }
        : {}),
    },
    { headers: NO_STORE_HEADERS },
  );
}
