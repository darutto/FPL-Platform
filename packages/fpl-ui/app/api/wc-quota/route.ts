/**
 * Server-side proxy → GET /quota on the World Cup assistant backend.
 *
 * Mirrors app/api/quota/route.ts (FPL) exactly, pointed at WC_BACKEND_URL
 * instead of FPL_BACKEND_URL, so WcQuotaIndicator reads the WC service's own
 * quota store (separate process/in-memory state from the FPL backend).
 *
 * Query params: user_id, tier — passed through to the backend unchanged.
 *
 * Environment:
 *   WC_BACKEND_URL     — backend base URL (default: http://localhost:8100)
 *   FPL_INTERNAL_TOKEN — server-to-server secret, shared with the FPL backend.
 *                        Attached here (server side) so the browser never
 *                        sees it; matches the WC backend's optional gate.
 *
 * HTTP status contract:
 *   200  — QuotaStatus JSON body
 *   502  — backend unreachable
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.WC_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8100';

const INTERNAL_TOKEN = process.env.FPL_INTERNAL_TOKEN?.trim();

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const backendParams = new URLSearchParams();

  const userId = searchParams.get('user_id');
  const tier = searchParams.get('tier');
  if (userId) backendParams.set('user_id', userId);
  if (tier) backendParams.set('tier', tier);

  const forwardHeaders: HeadersInit = {};
  const xUserId = request.headers.get('x-user-id');
  const xUserTier = request.headers.get('x-user-tier');
  if (xUserId) forwardHeaders['x-user-id'] = xUserId;
  if (xUserTier) forwardHeaders['x-user-tier'] = xUserTier;

  if (INTERNAL_TOKEN) forwardHeaders['x-internal-token'] = INTERNAL_TOKEN;

  const queryString = backendParams.toString();
  const backendUrl = `${BACKEND_URL}/quota${queryString ? `?${queryString}` : ''}`;

  let backendResponse: Response;
  try {
    backendResponse = await fetch(backendUrl, {
      method: 'GET',
      headers: forwardHeaders,
    });
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
