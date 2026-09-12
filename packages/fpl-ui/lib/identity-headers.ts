/**
 * Identity forwarding — the ONLY way an API route should pass the caller's
 * identity to a backend.
 *
 * Trust model:
 *   - `middleware.ts` strips any incoming `x-user-id` / `x-user-tier` on every
 *     request and re-sets them from the Clerk session when one exists. So by
 *     the time a route handler runs, these headers are server-set or absent —
 *     never client-supplied.
 *   - Route handlers copy them onto the backend request with this helper.
 *     Absent headers (anonymous traffic) are simply not forwarded; the backend
 *     defaults to `anonymous` / `free`.
 *
 * Every `app/api/**` route that talks to a chat backend must use this helper
 * (enforced by `__tests__/identity-forwarding-inventory.test.ts`) so a new
 * route cannot silently drop the caller's tier — that was i79: the follow-up
 * session turn went through `/session/{id}/ask` without identity and a
 * premium member became `anonymous / free` mid-conversation.
 */
import type { NextRequest } from 'next/server';

export const IDENTITY_HEADERS = ['x-user-id', 'x-user-tier'] as const;

/**
 * Returns the identity headers to forward, merged over `base`.
 * Only headers actually present on the incoming request are copied.
 */
export function forwardIdentityHeaders(
  request: NextRequest,
  base: Record<string, string> = {},
): Record<string, string> {
  const out: Record<string, string> = { ...base };
  for (const name of IDENTITY_HEADERS) {
    const value = request.headers.get(name);
    if (value) out[name] = value;
  }
  return out;
}
