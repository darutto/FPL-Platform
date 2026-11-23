/**
 * Server-side proxy → POST /eo/warm on the backend: start the EO jobs for the connected team (and main league)
 * before the first question. Fire-and-forget from the chat; same gating as /api/eo-poll (signed-in only, identity
 * from the middleware, never the client). The backend rate-limits per user and checks the internal token.
 */
import { NextRequest, NextResponse } from 'next/server';
import { forwardIdentityHeaders } from '@/lib/identity-headers';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

export async function POST(request: NextRequest) {
  const headers = forwardIdentityHeaders(request, { 'Content-Type': 'application/json' });
  if (!headers['x-user-id']) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON in request body' }, { status: 400 });
  }
  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/eo/warm`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: `Backend unreachable: ${message}` }, { status: 502 });
  }
  const data = await backendResponse.json().catch(() => ({}));
  return NextResponse.json(data, { status: backendResponse.status });
}
