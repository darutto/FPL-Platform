/**
 * Server-side proxy → POST /session (create session).
 *
 * Creates a new in-memory conversation session on the backend. The body is
 * optional — carries a seed payload (see lib/session-seed.ts) so a
 * follow-up session can start with the prior turn's already-resolved
 * state instead of empty.
 *
 * This route's body contract is JSON-only. Rather than passing through
 * whatever Content-Type the client sent (unpredictable, not real
 * trust-boundary protection), the body is parsed here and forwarded
 * re-serialized with an explicit, normalized `Content-Type: application/json`
 * header set by this route itself. An absent or unparseable body is treated
 * as "no seed" — the request is forwarded bodiless, identical to before
 * this parameter existed. The backend's own Pydantic validation is the
 * authoritative gate for a well-formed-but-invalid seed (e.g. an oversized
 * name) — this proxy layer does not duplicate that validation.
 *
 * HTTP status contract (passed through from backend):
 *   200  — session created; body: { session_id, created_at, expires_after_seconds }
 *   422  — malformed seed payload (rejected by backend validation)
 *   429  — session cap reached
 *   503  — backend not initialised
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.FPL_BACKEND_URL?.replace(/\/$/, '') ?? 'http://localhost:8000';

export async function POST(request: NextRequest) {
  let seed: unknown = null;
  try {
    const raw = await request.text();
    if (raw.trim().length > 0) {
      seed = JSON.parse(raw);
    }
  } catch {
    // Unparseable body — treat as "no seed" rather than failing the proxy;
    // the backend's own validation is the authoritative gate for anything
    // that does successfully reach it as a body.
    seed = null;
  }

  const hasSeed = seed != null && typeof seed === 'object' && Object.keys(seed).length > 0;

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/session`, {
      method: 'POST',
      ...(hasSeed
        ? {
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(seed),
          }
        : {}),
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
