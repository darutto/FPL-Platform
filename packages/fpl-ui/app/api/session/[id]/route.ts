/**
 * Server-side proxy → DELETE /session/{id} (clear session).
 *
 * Clears and removes an in-memory session from the backend.
 * After this call the session_id is no longer valid.
 *
 * HTTP status contract (passed through from backend):
 *   200  — session cleared; body: { status: "cleared", session_id }
 *   404  — session not found (already expired or never existed)
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

export async function DELETE(
  _request: NextRequest,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/session/${id}`, {
      method: 'DELETE',
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
