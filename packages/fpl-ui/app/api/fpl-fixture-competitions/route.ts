/**
 * Server-side proxy → GET /fixtures/competitions on the FPL backend.
 *
 * The multi-competition calendar layer of /fixtures. The tier is decided by the
 * BACKEND from the identity headers the Clerk middleware sets (the browser cannot
 * forge them); this route only forwards them. The response differs per caller, so
 * it is never cached. In production the backend answers `{ available: false }`
 * (the data source is dev-only) and the board renders nothing extra.
 *
 * Environment:
 *   FPL_BACKEND_URL — backend base URL (default: http://localhost:8000)
 */
import { NextRequest, NextResponse } from 'next/server';
import { forwardIdentityHeaders } from '@/lib/identity-headers';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

const UNAVAILABLE = { available: false };
const NO_STORE = { 'Cache-Control': 'private, no-store' };

export async function GET(request: NextRequest) {
  const query = new URLSearchParams();
  for (const name of ['team', 'from', 'to']) {
    const value = request.nextUrl.searchParams.get(name);
    if (value) query.set(name, value);
  }
  const qs = query.toString();
  try {
    const backendResponse = await fetch(
      `${BACKEND_URL}/fixtures/competitions${qs ? `?${qs}` : ''}`,
      { headers: forwardIdentityHeaders(request), cache: 'no-store' },
    );
    if (!backendResponse.ok) return NextResponse.json(UNAVAILABLE, { headers: NO_STORE });
    return NextResponse.json(await backendResponse.json(), { headers: NO_STORE });
  } catch {
    // Backend down or not carrying the endpoint yet: the base calendar is unaffected.
    return NextResponse.json(UNAVAILABLE, { headers: NO_STORE });
  }
}
