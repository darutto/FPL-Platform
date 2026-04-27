/**
 * Server-side proxy → POST /session (create session).
 *
 * Creates a new in-memory conversation session on the backend.
 *
 * HTTP status contract (passed through from backend):
 *   200  — session created; body: { session_id, created_at, expires_after_seconds }
 *   429  — session cap reached
 *   503  — backend not initialised
 */
import { NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

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
