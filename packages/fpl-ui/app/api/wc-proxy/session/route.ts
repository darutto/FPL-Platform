/**
 * Server-side proxy → World Cup assistant backend session endpoint.
 *
 *   POST /api/wc-proxy/session  → POST {backend}/session
 *
 * Mints a wc:-namespaced session id for multi-turn conversation mode.
 * See app/api/wc-proxy/route.ts for the shared backend-URL/error contract.
 */
import { NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.WC_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8100';

export async function POST() {
  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/session`, { method: 'POST' });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Backend unreachable: ${message}` },
      { status: 502 },
    );
  }

  const data = await backendResponse.json();
  return NextResponse.json(data, { status: backendResponse.status });
}
