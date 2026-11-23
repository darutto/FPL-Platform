/**
 * Server-side proxy → POST /eo/poll on the backend: the automatic retry of a "computing" EO answer.
 *
 * Signed-in users only. The middleware sets `x-user-id` from the Clerk session (never from the client), so a
 * request without it is refused here before anything reaches the backend. The backend checks the same identity
 * (and the internal token that `forwardIdentityHeaders` attaches) and rate-limits per user.
 *
 * HTTP status contract (passed through from backend): 200 · 401 not signed in · 422 bad body · 429 too often.
 */
import { NextRequest, NextResponse } from 'next/server';
import { forwardIdentityHeaders } from '@/lib/identity-headers';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

export async function POST(request: NextRequest) {
  // Identity comes only from the helper (set by the middleware from the Clerk session, never the client).
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
    backendResponse = await fetch(`${BACKEND_URL}/eo/poll`, {
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
