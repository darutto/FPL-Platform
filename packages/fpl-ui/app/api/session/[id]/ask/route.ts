/**
 * Server-side proxy → POST /session/{id}/ask (session turn).
 *
 * Forwards a question to an existing backend session, enabling
 * multi-turn pronoun and reference resolution.
 *
 * HTTP status contract (passed through from backend):
 *   200  — turn processed; inspect outcome/supported in body
 *   404  — session not found or expired
 *   422  — malformed request body
 *   503  — backend not initialised
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: 'Invalid JSON in request body' },
      { status: 400 },
    );
  }

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/session/${id}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
