/**
 * Server-side proxy → GET /quota on the FPL Grounded Assistant backend.
 *
 * Forwards quota status requests from the QuotaIndicator component.
 * Query params: user_id, tier — passed through to the backend unchanged.
 * Preserves X-User-Id / X-User-Tier headers from the incoming request
 * if present.
 *
 * Environment:
 *   FPL_BACKEND_URL    — backend base URL (default: http://localhost:8000)
 *   FPL_INTERNAL_TOKEN — server-to-server secret. When the backend has this
 *                        set, GET /quota is gated on a matching
 *                        X-Internal-Token header. We attach it here (server
 *                        side) so the browser never sees the secret.
 *
 * HTTP status contract:
 *   200  — QuotaStatus JSON body
 *   502  — backend unreachable
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

const INTERNAL_TOKEN = process.env.FPL_INTERNAL_TOKEN?.trim();

export async function GET(request: NextRequest) {
  // Forward all query params (user_id, tier) to the backend
  const { searchParams } = request.nextUrl;
  const backendParams = new URLSearchParams();

  const userId = searchParams.get('user_id');
  const tier = searchParams.get('tier');
  if (userId) backendParams.set('user_id', userId);
  if (tier) backendParams.set('tier', tier);

  // Forward identity headers if provided by the client
  const forwardHeaders: HeadersInit = {};
  const xUserId = request.headers.get('x-user-id');
  const xUserTier = request.headers.get('x-user-tier');
  if (xUserId) forwardHeaders['x-user-id'] = xUserId;
  if (xUserTier) forwardHeaders['x-user-tier'] = xUserTier;

  // Attach the server-to-server token so the backend's quota gate accepts us.
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
