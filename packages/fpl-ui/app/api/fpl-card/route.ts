/**
 * Server-side proxy → POST /card on the backend: a card opened by a tap (no chat message, no model, no quota).
 *
 * Signed-in users only: every card is opened from the chat, which requires sign-in, and the backend rate-limits
 * per user. Identity headers and the internal token go the same way as on /ask.
 *
 * HTTP status contract (passed through from backend): 200 · 401 not signed in · 404 unknown subject ·
 * 422 bad body · 429 too often · 503 not ready.
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
    backendResponse = await fetch(`${BACKEND_URL}/card`, {
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
