/**
 * Typed API client for the World Cup assistant backend.
 *
 * All requests go through /api/wc-proxy (server-side Next.js routes) to
 * avoid CORS and keep WC_BACKEND_URL out of the browser bundle — mirrors
 * lib/api.ts for the FPL domain. Kept separate (rather than parameterizing
 * lib/api.ts) because the WC contract is intentionally smaller (see
 * lib/wc-types.ts) and session_id travels in the /ask body, not the URL.
 *
 * HTTP status contract (from wc_server.py):
 *   200  — processed; inspect outcome/supported
 *   422  — malformed request (missing question)
 *   503  — backend not initialised
 */
import type { WcAskRequest, WcAskResponse, WcCreateSessionResult } from './wc-types';
import { WcApiError } from './wc-types';

/**
 * Send a question to POST /ask via /api/wc-proxy.
 *
 * Always render response.final_text regardless of outcome.
 * Pass session_id to continue a wc:-namespaced multi-turn conversation.
 */
export async function wcAsk(request: WcAskRequest): Promise<WcAskResponse> {
  const res = await fetch('/api/wc-proxy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (res.status === 422) {
    throw new WcApiError(422, 'Question is required');
  }
  if (res.status === 503) {
    throw new WcApiError(503, 'Backend not ready — try again shortly');
  }
  if (!res.ok) {
    throw new WcApiError(res.status, `Request failed (${res.status})`);
  }

  return res.json() as Promise<WcAskResponse>;
}

/**
 * Mint a new wc:-namespaced session id via /api/wc-proxy/session.
 *
 * The session is in-memory on the WC backend — it does not survive server
 * restarts. Pass the returned session_id on subsequent wcAsk() calls.
 */
export async function wcCreateSession(): Promise<WcCreateSessionResult> {
  const res = await fetch('/api/wc-proxy/session', { method: 'POST' });

  if (res.status === 503) {
    throw new WcApiError(503, 'Backend not ready — try again shortly');
  }
  if (!res.ok) {
    throw new WcApiError(res.status, `Session creation failed (${res.status})`);
  }

  return res.json() as Promise<WcCreateSessionResult>;
}
