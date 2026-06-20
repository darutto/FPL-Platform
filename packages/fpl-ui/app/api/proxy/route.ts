/**
 * Server-side proxy → FPL Grounded Assistant backend.
 *
 * Forwards requests from the browser to the backend, keeping the
 * backend URL server-side only (not exposed in the browser bundle).
 *
 * Supported routes:
 *   POST /api/proxy          → POST  {backend}/ask
 *   GET  /api/quota          → GET   {backend}/quota?user_id=<id>&tier=<tier>
 *
 * Environment:
 *   FPL_BACKEND_URL  — backend base URL (default: http://localhost:8000)
 *
 * HTTP status contract (passed through from backend):
 *   200  — processed; inspect outcome/supported in body
 *   422  — malformed request body
 *   503  — backend not initialised
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: 'Invalid JSON in request body' },
      { status: 400 },
    );
  }

  // Forward identity + quota tier injected by middleware (Clerk session →
  // x-user-id / x-user-tier) so the backend keys per-user quota and enforces
  // the right tier caps. Absent for anonymous traffic → backend defaults free.
  const forwardHeaders: Record<string, string> = { 'Content-Type': 'application/json' };
  const xUserId = request.headers.get('x-user-id');
  const xUserTier = request.headers.get('x-user-tier');
  if (xUserId) forwardHeaders['x-user-id'] = xUserId;
  if (xUserTier) forwardHeaders['x-user-tier'] = xUserTier;

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/ask`, {
      method: 'POST',
      headers: forwardHeaders,
      body: JSON.stringify(body),
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
