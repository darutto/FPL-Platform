/**
 * Typed API client for the FPL Grounded Assistant backend.
 *
 * All requests go through /api/proxy (server-side Next.js route) to avoid
 * CORS and keep the backend URL out of the browser bundle.
 *
 * HTTP status contract (from http_contract_fixtures.json):
 *   200  — processed; inspect outcome/supported for domain result
 *   422  — malformed request (missing question)
 *   429  — session cap (sessions only)
 *   503  — backend not initialised
 */
import type { AskRequest, AskResponse } from './types';

/** Returned by POST /session (create session). */
export interface CreateSessionResult {
  session_id: string;
  created_at: number;
  expires_after_seconds: number;
}

export class FplApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'FplApiError';
  }
}

/**
 * Send a stateless question to POST /ask via the proxy.
 *
 * Always render response.final_text regardless of outcome.
 * Check response.supported and response.outcome for routing decisions.
 * Structured metadata fields (captain, comparison, etc.) are non-null
 * only when outcome='ok' and the matching intent fired.
 */
export async function ask(request: AskRequest): Promise<AskResponse> {
  const res = await fetch('/api/proxy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (res.status === 422) {
    throw new FplApiError(422, 'Question is required');
  }
  if (res.status === 503) {
    throw new FplApiError(503, 'Backend not ready — try again shortly');
  }
  if (!res.ok) {
    throw new FplApiError(res.status, `Request failed (${res.status})`);
  }

  return res.json() as Promise<AskResponse>;
}

/**
 * Create a new conversation session via the proxy.
 *
 * Returns a session_id to hold in React state. The session is in-memory on
 * the backend — it does not survive server restarts or page refreshes.
 * Throws FplApiError 429 when the backend session cap is reached.
 */
export async function createSession(): Promise<CreateSessionResult> {
  const res = await fetch('/api/session', { method: 'POST' });

  if (res.status === 429) {
    throw new FplApiError(429, 'Límite de sesiones alcanzado — inténtalo de nuevo en unos minutos');
  }
  if (res.status === 503) {
    throw new FplApiError(503, 'Backend not ready — try again shortly');
  }
  if (!res.ok) {
    throw new FplApiError(res.status, `Session creation failed (${res.status})`);
  }

  return res.json() as Promise<CreateSessionResult>;
}

/**
 * Ask a question within an existing session via the proxy.
 *
 * The backend resolves pronouns and references against previous turns.
 * Returns AskResponse shape (session_id present in the wire body but not
 * modelled here — it is not needed by the renderer).
 * Throws FplApiError 404 when the session has expired or was not found.
 */
export async function sessionAsk(
  sessionId: string,
  request: AskRequest,
): Promise<AskResponse> {
  const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (res.status === 404) {
    throw new FplApiError(404, 'Sesión expirada. Inicia una nueva conversación.');
  }
  if (res.status === 422) {
    throw new FplApiError(422, 'Question is required');
  }
  if (res.status === 503) {
    throw new FplApiError(503, 'Backend not ready — try again shortly');
  }
  if (!res.ok) {
    throw new FplApiError(res.status, `Request failed (${res.status})`);
  }

  // SessionAskResponse is structurally a superset of AskResponse (adds session_id).
  // The renderer consumes only AskResponse fields — cast is safe.
  return res.json() as Promise<AskResponse>;
}

/**
 * Clear and remove a session via the proxy.
 *
 * Fire-and-forget safe: 404 (already expired/gone) is treated as success.
 * Called when the user resets or leaves session mode.
 */
export async function clearSession(sessionId: string): Promise<void> {
  const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });

  // 404 = session already expired or gone — treat as a successful clear
  if (!res.ok && res.status !== 404) {
    throw new FplApiError(res.status, `Session clear failed (${res.status})`);
  }
}
